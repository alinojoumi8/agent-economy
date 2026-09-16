"""Disinterested legal decisions with recorded pre-enforcement authority."""
from __future__ import annotations

import json

from .estates import EstateError
from .legal import DECISION_ROLES


class LegalDecisionAuthority:
    POLICY = "disinterested_estate_adjudication_v1"

    def __init__(self, economy):
        self.e = economy
        self.store = economy.store
        self.enabled = economy.engine_semantics_version >= 20

    def _frontiers(self):
        return {field: self.store.scalar(f"SELECT COALESCE(MAX(id),0) FROM {table}") for field, table in (
            ("estate_frontier", "estate_cases"), ("administration_frontier", "estate_administrations"),
            ("stewardship_frontier", "firm_stewardships"), ("counsel_response_frontier", "legal_counsel_responses"))}

    def _recorded_conflicts(self, tick, actor_id, matter, frontiers):
        """These permanent conflicts remain reconstructible after later changes."""
        reasons = []
        if matter["counsel_agent_id"] == actor_id:
            reasons.append("counsel_for_matter")
        if self.store.scalar("SELECT r.id FROM legal_counsel_requests r JOIN legal_counsel_responses a ON a.request_id=r.id "
                "WHERE r.matter_id=? AND r.counsel_id=? AND a.decision='accepted' AND a.id<=? AND a.tick<=? LIMIT 1",
                (matter["id"], actor_id, frontiers["counsel_response_frontier"], tick)):
            reasons.append("recorded_counsel_for_matter")
        for side in ("claimant", "respondent"):
            kind, party_id = matter[f"{side}_type"], matter[f"{side}_id"]
            if kind == "agent":
                if actor_id == party_id:
                    reasons.append(f"{side}:personal_party")
                if self.store.scalar("SELECT a.id FROM estate_administrations a JOIN estate_cases c ON c.id=a.estate_id "
                        "WHERE c.deceased_agent_id=? AND c.id<=? AND a.id<=? AND a.started_tick<=? "
                        "AND a.administrator_agent_id=? LIMIT 1",
                        (party_id, frontiers["estate_frontier"], frontiers["administration_frontier"], tick, actor_id)):
                    reasons.append(f"{side}:public_estate_trustee")
            elif kind == "firm" and self.store.scalar("SELECT id FROM firm_stewardships WHERE firm_id=? "
                    "AND steward_agent_id=? AND capacity='estate' AND id<=? AND started_tick<=? LIMIT 1",
                    (party_id, actor_id, frontiers["stewardship_frontier"], tick)):
                reasons.append(f"{side}:estate_business_steward")
        return reasons

    def assess(self, tick, actor_id, matter):
        """Read-only admission for the engine and private decision work queues."""
        actor = self.store.query_one("SELECT * FROM agents WHERE id=?", (actor_id,))
        if actor is None or not actor["alive"] or actor["age"] < 18 or actor["role"] not in DECISION_ROLES:
            return {"eligible": False, "reason": "only a living adult judge or authorized regulator may decide"}
        if self.e.engine_semantics_version >= 21 and (
                not self.e.population.is_available(actor_id) or not self.e.population.is_local(actor_id, tick)):
            return {"eligible": False, "reason": "decision maker is not locally available"}
        if self.store.scalar("SELECT id FROM estate_cases WHERE completed_event_id IS NULL LIMIT 1"):
            return {"eligible": False, "reason": "estate settlement is still in progress"}
        frontiers = self._frontiers()
        if self.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=? AND id<=?",
                             (actor_id, frontiers["estate_frontier"])):
            return {"eligible": False, "reason": "decision maker's personal authority has ended"}
        reasons = self._recorded_conflicts(tick, actor_id, matter, frontiers)
        for side in ("claimant", "respondent"):
            kind, party_id = matter[f"{side}_type"], matter[f"{side}_id"]
            if kind == "agent":
                estate = self.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=? AND id<=?",
                                            (party_id, frontiers["estate_frontier"]))
                if estate and self.e.estate_securities.authority(estate, actor_id) is not None:
                    reasons.append(f"{side}:estate_representative")
            elif self.e.legal.controls(actor_id, kind, party_id):
                reasons.append(f"{side}:party_controller")
            if kind == "firm":
                if self.store.scalar("SELECT 1 FROM shares WHERE firm_id=? AND holder_type='agent' AND holder_id=? AND qty>0",
                                     (party_id, actor_id)):
                    reasons.append(f"{side}:shareholder")
                for estate in self.store.query("SELECT DISTINCT estate_id FROM estate_security_lots l WHERE firm_id=? "
                        "AND started_tick<=? AND NOT EXISTS(SELECT 1 FROM estate_security_releases r WHERE r.lot_id=l.id)",
                        (party_id, tick)):
                    if self.e.estate_securities.authority(estate["estate_id"], actor_id) is not None and any(
                            self.e.estate_securities.remaining(lot) > 0
                            for lot in self.e.estate_securities.lots(estate["estate_id"], party_id)):
                        reasons.append(f"{side}:estate_security_interest")
        reasons = sorted(set(reasons))
        return {"eligible": not reasons, "reason": "conflict of interest: " + ", ".join(reasons) if reasons else None,
                "conflicts": reasons, "actor_id": actor_id, "actor_age": actor["age"], "actor_role": actor["role"],
                "policy": self.POLICY, "tick": tick, **frontiers}

    def reject(self, tick, actor_id, matter_id, assessment):
        self.store.log_event(tick, "legal_decision_recused", {"matter_id": matter_id, "actor_id": actor_id,
            "policy": self.POLICY, "reason": assessment["reason"]}, phase="EXECUTION",
            subject_type="legal_matter", subject_id=matter_id)
        return {"ok": False, "reason": assessment["reason"]}

    def begin(self, matter_id, assessment):
        if not assessment["eligible"]:
            raise EstateError("conflicted legal authority cannot be recorded as admitted")
        proof = {key: value for key, value in assessment.items() if key not in {"eligible", "reason", "conflicts"}}
        event = self.store.log_event(proof["tick"], "legal_decision_authority_checked", {"matter_id": matter_id, **proof},
            phase="EXECUTION", subject_type="legal_matter", subject_id=matter_id)
        return {**proof, "event_id": event}

    def record(self, decision_id, proof):
        return self.store.insert("legal_decision_authorities", decision_id=decision_id, **proof)

    def check_invariants(self):
        if not self.enabled:
            return
        if self.store.scalar("SELECT d.id FROM legal_decisions d LEFT JOIN legal_decision_authorities a ON a.decision_id=d.id "
                             "WHERE a.id IS NULL LIMIT 1"):
            raise EstateError("legal decision lacks its pre-enforcement authority")
        for proof in self.store.query("SELECT * FROM legal_decision_authorities ORDER BY id"):
            decision = self.store.query_one("SELECT * FROM legal_decisions WHERE id=?", (proof["decision_id"],))
            if decision is None or decision["decision_maker_id"] != proof["actor_id"] or decision["tick"] != proof["tick"]:
                raise EstateError("legal decision has the wrong authority identity or time")
            matter = self.store.query_one("SELECT * FROM legal_matters WHERE id=?", (decision["matter_id"],))
            event = self.store.query_one("SELECT * FROM events WHERE id=?", (proof["event_id"],))
            payload = {key: proof[key] for key in ("actor_id", "actor_age", "actor_role", "policy", "tick",
                                                  "estate_frontier", "administration_frontier", "stewardship_frontier", "counsel_response_frontier")}
            payload["matter_id"] = matter["id"] if matter is not None else None
            if event is None or matter is None or event["kind"] != "legal_decision_authority_checked" or (
                    event["tick"] != proof["tick"] or event["subject_type"] != "legal_matter" or event["subject_id"] != matter["id"]
                    or json.loads(event["payload_json"]) != payload or event["id"] >= decision["enforcement_event_id"]):
                raise EstateError("legal decision lacks its matching pre-enforcement authority event")
            actor = self.store.query_one("SELECT * FROM agents WHERE id=?", (proof["actor_id"],))
            if actor is None or actor["age"] < proof["actor_age"] or proof["actor_role"] not in DECISION_ROLES or (
                    actor["died_tick"] is not None and actor["died_tick"] < proof["tick"]):
                raise EstateError("legal decision has invalid decision-maker evidence")
            if self.e.engine_semantics_version >= 21 and not self.e.population.history.is_living_resident(
                    proof["actor_id"], proof["tick"], event_frontier=proof["event_id"]-1):
                raise EstateError("legal decision authority was not locally available at its event")
            for field, table, tick_field in (("estate_frontier", "estate_cases", "opened_tick"),
                    ("administration_frontier", "estate_administrations", "started_tick"),
                    ("stewardship_frontier", "firm_stewardships", "started_tick"),
                    ("counsel_response_frontier", "legal_counsel_responses", "tick")):
                if proof[field] and not self.store.scalar(f"SELECT 1 FROM {table} WHERE id=? AND {tick_field}<=?",
                                                          (proof[field], proof["tick"])):
                    raise EstateError("legal decision has an invalid authority frontier")
            for field, table, event_field in (("estate_frontier", "estate_cases", "completed_event_id"),
                    ("administration_frontier", "estate_administrations", "event_id"),
                    ("stewardship_frontier", "firm_stewardships", "recorded_event_id"),
                    ("counsel_response_frontier", "legal_counsel_responses", "event_id")):
                actual_frontier = self.store.scalar(f"SELECT COALESCE(MAX(id),0) FROM {table} WHERE {event_field}<?",
                                                    (proof["event_id"],))
                if actual_frontier != proof[field]:
                    raise EstateError(f"legal decision omits or invents its {field} authority frontier")
            if self._recorded_conflicts(proof["tick"], proof["actor_id"], matter, proof):
                raise EstateError("legal decision was made with a recorded conflict of interest")
            if self.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=? AND id<=?",
                                 (proof["actor_id"], proof["estate_frontier"])):
                raise EstateError("legal decision uses a deceased decision maker")
