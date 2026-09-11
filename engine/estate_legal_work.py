"""Read-only claim opportunities from retained, unpaid estate rights."""
from __future__ import annotations

import json

from .estates import EstateError


class EstateLegalWork:
    POLICY = "recorded_estate_receivables_v1"

    def __init__(self, economy):
        self.e, self.store = economy, economy.store

    def rights(self, estate_id):
        """Current unpaid instruments; a ready legal claim is a separate fact."""
        owner = self.store.scalar("SELECT deceased_agent_id FROM estate_cases WHERE id=?", (estate_id,))
        if owner is None:
            return
        for row in self.store.query("SELECT o.*,c.offered_tick FROM obligations o JOIN contracts c ON c.id=o.contract_id "
                "WHERE o.obligee_type='agent' AND o.obligee_id=? AND o.status IN ('pending','breached') "
                "AND o.obligation_type IN ('payment','indemnity') AND o.amount_cents>0 "
                "AND NOT EXISTS(SELECT 1 FROM legal_award_obligations a WHERE a.obligation_id=o.id) ORDER BY o.id", (owner,)):
            remaining = row["amount_cents"] - self.e.legal_awards._prior_obligation_payments(row)
            if remaining > 0:
                yield {"kind": "obligation", "id": row["id"], "owner": owner,
                       "unpaid_cents": remaining, "row": dict(row)}
        for row in self.store.query("SELECT c.*,h.started_tick AS holder_started_tick FROM wage_claims c "
                "JOIN wage_claim_holders h ON h.claim_id=c.id WHERE h.owner_type='agent' AND h.owner_id=? "
                "AND h.ended_tick IS NULL AND c.closed_tick IS NULL ORDER BY c.id", (owner,)):
            remaining = self.e.earned_wages.outstanding(row)
            if remaining > 0:
                yield {"kind": "wage_claim", "id": row["id"], "owner": owner,
                       "unpaid_cents": remaining, "row": dict(row)}

    def has_rights(self, estate_id):
        return next(self.rights(estate_id), None) is not None

    def _contract_action(self, tick, right):
        row = right["row"]
        if row["offered_tick"] > tick or row["status"] != "breached" or row["breached_tick"] is None or row["breached_tick"] > tick:
            return None, "waiting_for_recorded_breach"
        event = self.store.query_one("SELECT id FROM events WHERE tick<=? AND kind='obligation_breached' "
            "AND subject_type='contract' AND subject_id=? AND json_extract(payload_json,'$.obligation_id')=? ORDER BY id LIMIT 1",
            (tick, row["contract_id"], row["id"]))
        if event is None:
            return None, "missing_breach_evidence"
        for matter in self.store.query("SELECT * FROM legal_matters WHERE contract_id=? AND claimant_type='agent' "
                "AND claimant_id=? AND respondent_type=? AND respondent_id=? AND filed_tick<=? ORDER BY id",
                (row["contract_id"], right["owner"], row["obligor_type"], row["obligor_id"], tick)):
            requested = json.loads(matter["requested_remedy_json"] or "{}")
            identifiers = requested.get("obligation_ids") if isinstance(requested, dict) else None
            # An unscoped existing claim needs clarification, not another case.
            if not isinstance(identifiers, list) or row["id"] in identifiers:
                return None, "already_presented"
            if self.store.scalar("SELECT f.id FROM legal_filings f JOIN json_each(f.evidence_event_ids_json) j "
                    "JOIN events e ON e.id=j.value WHERE f.matter_id=? AND f.tick<=? AND e.tick<=? "
                    "AND e.kind IN ('obligation_breached','obligation_performed') "
                    "AND json_extract(e.payload_json,'$.obligation_id')=? LIMIT 1", (matter["id"], tick, tick, row["id"])):
                return None, "already_presented"
        return {"type": "file_claim", "matter_type": "civil", "claim_type": "unpaid_estate_obligation",
            "contract_id": row["contract_id"], "claimant": {"type": "agent", "id": right["owner"]},
            "respondent": {"type": row["obligor_type"], "id": row["obligor_id"]},
            "requested_remedy": {"type": "damages", "amount_cents": row["amount_cents"],
                "currency_code": row["currency_code"], "obligation_ids": [row["id"]]},
            "metadata": {"source_event_id": event["id"], "evidence_event_ids": [event["id"]],
                         "estate_claim_source": {"kind": right["kind"], "id": right["id"]}}}, None

    def _wage_action(self, tick, right):
        row = right["row"]
        if row["opened_tick"] > tick or row["holder_started_tick"] > tick:
            return None, "right_not_yet_recorded"
        event = self.store.query_one("SELECT id,payload_json FROM events WHERE tick<=? AND kind='wage_missed' "
            "AND json_extract(payload_json,'$.claim_id')=? ORDER BY id DESC LIMIT 1", (tick, row["id"]))
        if event is None:
            return None, "waiting_for_recorded_wage_arrears"
        payload = json.loads(event["payload_json"])
        try:
            scopes = self.e.wage_awards.preview(tick, right["owner"], row["firm_id"], [{
                "claim_id": row["id"], "through_accrual_id": payload.get("through_accrual_id")}])
        except EstateError:
            return None, "wage_interval_unavailable"
        scope = scopes[0]
        if self.store.scalar("SELECT s.id FROM legal_wage_scopes s JOIN legal_matters m ON m.id=s.matter_id "
                "WHERE s.claim_id=? AND s.start_cents<? AND s.end_cents>? AND m.filed_tick<=? LIMIT 1",
                (row["id"], scope["end_cents"], scope["start_cents"], tick)):
            return None, "already_presented"
        return {"type": "file_claim", "matter_type": "labor", "claim_type": "unpaid_wages",
            "claimant": {"type": "agent", "id": right["owner"]}, "respondent": {"type": "firm", "id": row["firm_id"]},
            "requested_remedy": {"type": "damages", "amount_cents": scope["end_cents"] - scope["start_cents"],
                "currency_code": scope["currency_code"], "wage_scopes": [{
                    "claim_id": row["id"], "through_accrual_id": scope["through_accrual_id"]}]},
            "metadata": {"source_event_id": event["id"], "evidence_event_ids": [event["id"]],
                         "estate_claim_source": {"kind": right["kind"], "id": right["id"]}}}, None

    def context_for(self, actor_id, tick):
        result = {"policy": self.POLICY, "rights": [], "eligible_actions": []}
        if self.e.legal_representation._adult(actor_id) is None:
            return result
        for case in self.store.query("SELECT * FROM estate_cases WHERE completed_event_id IS NOT NULL AND opened_tick<=? ORDER BY id", (tick,)):
            if self.e.estate_securities.authority(case["id"], actor_id) is None:
                continue
            for right in self.rights(case["id"]):
                recorded = (right["row"]["offered_tick"] if right["kind"] == "obligation" else
                            max(right["row"]["opened_tick"], right["row"]["holder_started_tick"]))
                if recorded > tick:
                    continue
                action, blocked = (self._contract_action(tick, right) if right["kind"] == "obligation"
                                   else self._wage_action(tick, right))
                if action is not None:
                    party = action["respondent"]
                    matter = {"claimant_type": "agent", "claimant_id": right["owner"],
                              "respondent_type": party["type"], "respondent_id": party["id"]}
                    proof = self.e.legal_representation.authorize(tick, actor_id, matter, "file_claim", "claimant", allow_counsel=False)
                    if proof is None:
                        action, blocked = None, "party_authority_unavailable"
                    elif not self.e.legal.enabled:
                        action, blocked = None, "legal_mechanics_disabled"
                    elif action["requested_remedy"]["amount_cents"] > self.e.legal.max_damages_cents:
                        action, blocked = None, "requested_relief_above_ruleset_limit"
                if len(result["rights"]) < 5:
                    result["rights"].append({"estate_id": case["id"], "nominee_agent_id": right["owner"],
                        "source_key": right["kind"] + ":" + str(right["id"]),
                        "unpaid_cents": right["unpaid_cents"], "currency_code": right["row"]["currency_code"],
                        "blocked_reason": blocked})
                if action is not None:
                    result["eligible_actions"] = [action]
                    return result
        return result
