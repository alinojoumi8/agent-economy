"""Case-specific party authority and consenting counsel under Semantics 20."""
from __future__ import annotations

import json

from .estates import EstateError
from .types import positive_integer_id


class LegalRepresentation:
    POLICY = "recorded_party_mandates_v1"
    OPEN = ("filed", "pleading", "hearing", "settlement_offered")
    SCOPES = frozenset({"submit_filing", "propose_settlement", "accept_settlement"})
    PROCEDURAL = frozenset({"file_claim", "submit_filing", "request_legal_counsel", "end_legal_counsel"})
    EFFECTS = {"file_claim": "legal_matter_filed", "submit_filing": "legal_filing_submitted",
               "propose_settlement": "settlement_offered", "accept_settlement": "matter_settled",
               "request_legal_counsel": "legal_counsel_requested", "end_legal_counsel": "legal_counsel_ended"}

    def __init__(self, economy):
        self.e, self.store = economy, economy.store
        self.enabled = economy.engine_semantics_version >= 20

    @staticmethod
    def party(matter, side):
        return matter[f"{side}_type"], int(matter[f"{side}_id"])

    def _adult(self, actor_id):
        return self.store.query_one("SELECT * FROM agents WHERE id=? AND alive=1 AND age>=18 "
            "AND NOT EXISTS(SELECT 1 FROM estate_cases c WHERE c.deceased_agent_id=agents.id)", (actor_id,))

    def direct(self, actor_id, matter, side, *, allow_outside_self=False):
        """An estate capacity is valid only for these legal actions."""
        if side not in {"claimant", "respondent"} or self._adult(actor_id) is None:
            return None
        kind, party_id = self.party(matter, side)
        if (self.e.engine_semantics_version >= 21 and not self.e.population.is_available(actor_id)
                and not (allow_outside_self and kind == "agent" and party_id == actor_id)):
            return None
        if kind == "agent":
            case = self.store.query_one("SELECT * FROM estate_cases WHERE deceased_agent_id=?", (party_id,))
            if case is not None:
                if case["completed_event_id"] is None:
                    return None
                authority = self.e.estate_securities.authority(case["id"], actor_id)
                if authority is None:
                    return None
                proof = {key: value for key, value in authority.items() if key != "weight"}
                return {"capacity": "estate", "estate_id": case["id"], "source": proof}
            if actor_id == party_id:
                return {"capacity": "self", "estate_id": None, "source": {}}
            return None
        if self.e.legal.controls(actor_id, kind, party_id):
            source = {"role": self.store.scalar("SELECT role FROM agents WHERE id=?", (actor_id,))}
            if kind == "firm":
                source["stewardship_id"] = self.store.scalar("SELECT id FROM firm_stewardships "
                    "WHERE firm_id=? AND ended_tick IS NULL", (party_id,))
            return {"capacity": "organization", "estate_id": None, "source": source}
        return None

    def authorize(self, tick, actor_id, matter, action, side=None, *, allow_counsel=True):
        matter = dict(matter)
        if side is not None and side not in {"claimant", "respondent"}:
            return None
        if self._adult(actor_id) is None:
            return None
        if self.e.engine_semantics_version >= 21 and not self.e.population.is_available(actor_id):
            return None
        if self.store.scalar("SELECT id FROM estate_cases WHERE completed_event_id IS NULL LIMIT 1"):
            return None
        choices = []
        for candidate in ("claimant", "respondent"):
            direct = self.direct(actor_id, matter, candidate)
            if direct is not None:
                choices.append((candidate, {**direct, "counsel_request_id": None}))
            elif allow_counsel and matter.get("id") and action in self.SCOPES:
                mandate = self.mandate(actor_id, matter["id"], candidate, action, tick)
                if mandate is not None:
                    choices.append((candidate, {"capacity": "counsel", "estate_id": None,
                        "counsel_request_id": mandate["id"], "source": {"request_id": mandate["id"]}}))
        adversarial = None
        if len(choices) == 2 and side is not None and action in self.PROCEDURAL and all(
                grant["capacity"] != "counsel" for _, grant in choices):
            chosen, authority = next((s, grant) for s, grant in choices if s == side)
            other, other_authority = next((s, grant) for s, grant in choices if s != side)
            adversarial = {"side": other, **other_authority}
        elif len(choices) == 1 and (side is None or choices[0][0] == side):
            chosen, authority = choices[0]
        else:
            return None
        return self._proof(tick, actor_id, matter, action, chosen, authority, adversarial=adversarial)

    def _proof(self, tick, actor_id, matter, action, chosen, authority, *, adversarial=None):
        actor = self._adult(actor_id)
        kind, party_id = self.party(matter, chosen)
        return {"policy": self.POLICY, "tick": tick, "action": action, "actor_id": actor_id,
            "actor_age": actor["age"], "side": chosen, "party_type": kind, "party_id": party_id,
            "parties": {s: list(self.party(matter, s)) for s in ("claimant", "respondent")},
            "estate_frontier": self.store.scalar("SELECT COALESCE(MAX(id),0) FROM estate_cases"),
            "administration_end_frontier": self.store.scalar("SELECT COALESCE(MAX(id),0) FROM estate_administration_ends"),
            "counsel_end_frontier": self.store.scalar("SELECT COALESCE(MAX(id),0) FROM legal_counsel_ends"),
            "adversarial_authority": adversarial,
            **authority}

    def begin(self, proof):
        return self.store.log_event(proof["tick"], "legal_action_authorized", proof,
            phase="EXECUTION", subject_type=proof["party_type"], subject_id=proof["party_id"])

    def record(self, matter_id, proof, event_id, effect_event_id):
        values = {key: proof[key] for key in ("tick", "action", "actor_id", "side", "party_type", "party_id",
                                             "capacity", "estate_id", "counsel_request_id")}
        return self.store.insert("legal_action_authorities", matter_id=matter_id, **values,
            proof_json=json.dumps(proof, sort_keys=True), event_id=event_id, effect_event_id=effect_event_id)

    def _response(self, request_id):
        return self.store.query_one("SELECT * FROM legal_counsel_responses WHERE request_id=?", (request_id,))

    def _current_requests(self):
        return self.store.query("SELECT r.* FROM legal_counsel_requests r WHERE "
            "NOT EXISTS(SELECT 1 FROM legal_counsel_ends e WHERE e.request_id=r.id) AND "
            "NOT EXISTS(SELECT 1 FROM legal_counsel_responses a WHERE a.request_id=r.id AND a.decision='declined') ORDER BY r.id")

    @staticmethod
    def _anchor(proof):
        source = proof["source"]
        return (proof["capacity"], proof["estate_id"], proof.get("counsel_request_id"),
                tuple((key, json.dumps(source.get(key), sort_keys=True)) for key in
                      ("beneficiary_id", "guardian_id", "administration_id", "path", "stewardship_id", "role")))

    def invalid_reason(self, request, tick):
        matter = self.store.query_one("SELECT * FROM legal_matters WHERE id=?", (request["matter_id"],))
        if matter is None or matter["status"] not in self.OPEN:
            return "matter_closed"
        if self._adult(request["counsel_id"]) is None or not self.e.legal._is_lawyer(request["counsel_id"]):
            return "counsel_unavailable"
        if self.counsel_conflict(request):
            return "counsel_unavailable"
        response = self._response(request["id"])
        if response is None and tick >= request["expires_tick"]:
            return "expired"
        retain_client = (self.e.engine_semantics_version >= 21 and response is not None
                         and response["decision"] == "accepted")
        current = self.direct(request["requester_id"], matter, request["side"], allow_outside_self=retain_client)
        event = self.store.query_one("SELECT payload_json FROM events WHERE id=?", (request["authority_event_id"],))
        if current is None or event is None or self._anchor(current) != self._anchor(json.loads(event["payload_json"])):
            return "client_authority_lost"
        other = "respondent" if request["side"] == "claimant" else "claimant"
        if self.direct(request["requester_id"], matter, other) is not None and any(
                scope != "submit_filing" for scope in json.loads(request["scopes_json"])):
            return "client_authority_lost"
        return None

    def mandate(self, actor_id, matter_id, side, action, tick):
        for request in self.store.query("SELECT r.* FROM legal_counsel_requests r JOIN legal_counsel_responses a "
                "ON a.request_id=r.id WHERE r.matter_id=? AND r.side=? AND r.counsel_id=? AND a.decision='accepted' "
                "AND a.tick<=? AND NOT EXISTS(SELECT 1 FROM legal_counsel_ends e WHERE e.request_id=r.id) ORDER BY r.id",
                (matter_id, side, actor_id, tick)):
            if action in json.loads(request["scopes_json"]) and self.invalid_reason(request, tick) is None:
                return request
        return None

    def _end(self, tick, request, reason, actor_id=None):
        if self.store.scalar("SELECT id FROM legal_counsel_ends WHERE request_id=?", (request["id"],)):
            return None
        payload = {"request_id": request["id"], "actor_id": actor_id, "reason": reason}
        event = self.store.log_event(tick, "legal_counsel_ended", payload, phase="EXECUTION" if actor_id is not None else "NIGHT_CLOSE",
            subject_type="legal_matter", subject_id=request["matter_id"])
        self.store.insert("legal_counsel_ends", request_id=request["id"], tick=tick,
                          actor_id=actor_id, reason=reason, event_id=event)
        if request["side"] == "claimant":
            self.store.execute("UPDATE legal_matters SET counsel_agent_id=NULL WHERE id=? AND counsel_agent_id=?",
                               (request["matter_id"], request["counsel_id"]))
        return event

    def reconcile(self, tick):
        if not self.enabled:
            return
        for request in self._current_requests():
            reason = self.invalid_reason(request, tick)
            if reason:
                self._end(tick, request, reason)
        self.e.estate_administration.reconcile(tick)

    def close_person(self, tick, estate_id, actor_id):
        for request in self._current_requests():
            if actor_id in (request["requester_id"], request["counsel_id"]):
                self.e.estate_cases._item(estate_id, "legal_counsel_mandate", request, "extinguished")
                self._end(tick, request, "counsel_unavailable" if actor_id == request["counsel_id"] else "client_authority_lost")

    def release_for_departure(self, tick, movement_id, actor_id):
        """Keep an accepted local mandate for an outside client's own rights."""
        for request in self._current_requests():
            if actor_id not in (request["requester_id"], request["counsel_id"]):
                continue
            if actor_id == request["counsel_id"]:
                reason = "counsel_unavailable"
            else:
                reason = self.invalid_reason(request, tick)
                if reason is None:
                    continue
            self.e.civic_authority.record_departure_binding(tick, movement_id, actor_id, "legal_counsel_mandate", request)
            self._end(tick, request, reason)

    def counsel_conflict(self, request):
        matter = self.store.query_one("SELECT * FROM legal_matters WHERE id=?", (request["matter_id"],))
        other = "respondent" if request["side"] == "claimant" else "claimant"
        if self.direct(request["counsel_id"], matter, other) is not None:
            return "counsel controls the opposing party"
        if self.store.scalar("SELECT r.id FROM legal_counsel_requests r JOIN legal_counsel_responses a ON a.request_id=r.id "
                "WHERE r.matter_id=? AND r.side=? AND r.counsel_id=? AND a.decision='accepted' LIMIT 1",
                (request["matter_id"], other, request["counsel_id"])):
            return "counsel previously accepted representation of the opposing side"
        return None

    def request(self, tick, actor_id, action):
        if not self.enabled:
            return {"ok": False, "reason": "legal mandates require semantics 20"}
        matter_id, counsel_id = positive_integer_id(action.get("matter_id")), positive_integer_id(action.get("counsel_agent_id"))
        side, scopes = action.get("side"), action.get("scopes", ["submit_filing", "propose_settlement"])
        if matter_id is None or counsel_id is None or side not in {"claimant", "respondent"}:
            return {"ok": False, "reason": "a matter, side and counsel identity are required"}
        if not isinstance(scopes, list) or not scopes or any(not isinstance(s, str) or s not in self.SCOPES for s in scopes):
            return {"ok": False, "reason": "counsel scopes must name supported legal actions"}
        matter = self.store.query_one("SELECT * FROM legal_matters WHERE id=?", (matter_id,))
        if matter is None or matter["status"] not in self.OPEN or tick < matter["filed_tick"]:
            return {"ok": False, "reason": "counsel needs an open matter"}
        if actor_id == counsel_id or self._adult(counsel_id) is None or not self.e.legal._is_lawyer(counsel_id):
            return {"ok": False, "reason": "choose another living adult lawyer"}
        proof = self.authorize(tick, actor_id, matter, "request_legal_counsel", side, allow_counsel=False)
        if proof is None:
            return {"ok": False, "reason": "only the represented party may request counsel"}
        if proof["adversarial_authority"] is not None and any(scope != "submit_filing" for scope in scopes):
            return {"ok": False, "reason": "dual-party authority permits procedural counsel only"}
        conflict = self.counsel_conflict({"matter_id": matter_id, "side": side, "counsel_id": counsel_id})
        if conflict:
            return {"ok": False, "reason": conflict}
        previous = [r for r in self._current_requests() if (r["matter_id"], r["side"]) == (matter_id, side)]
        if any(self.invalid_reason(r, tick) is None for r in previous):
            return {"ok": False, "reason": "end the current counsel request before replacing it"}
        with self.e.estate_cases._batch():
            for old in previous:
                self._end(tick, old, self.invalid_reason(old, tick))
            proof = self.authorize(tick, actor_id, matter, "request_legal_counsel", side, allow_counsel=False)
            authority_event = self.begin(proof)
            payload = {"matter_id": matter_id, "side": side, "requester_id": actor_id, "counsel_id": counsel_id,
                "requested_tick": tick, "expires_tick": tick + 7, "scopes_json": json.dumps(sorted(set(scopes))),
                "authority_event_id": authority_event}
            event = self.store.log_event(tick, "legal_counsel_requested", payload, phase="EXECUTION",
                subject_type="legal_matter", subject_id=matter_id)
            request_id = self.store.insert("legal_counsel_requests", **payload, event_id=event)
            self.record(matter_id, proof, authority_event, event)
            return {"ok": True, "request_id": request_id, "event_id": event}

    def respond(self, tick, actor_id, action):
        request_id = positive_integer_id(action.get("request_id"))
        choice = action.get("decision")
        request = self.store.query_one("SELECT * FROM legal_counsel_requests WHERE id=?", (request_id,)) if request_id else None
        actor = self._adult(actor_id)
        if not self.enabled or request is None or actor is None or request["counsel_id"] != actor_id or choice not in {"accept", "decline"}:
            return {"ok": False, "reason": "only the requested living lawyer may accept or decline"}
        if self._response(request_id) is not None or self.store.scalar("SELECT id FROM legal_counsel_ends WHERE request_id=?", (request_id,)):
            return {"ok": False, "reason": "counsel request already has a response or ending"}
        reason = self.invalid_reason(request, tick)
        if tick < request["requested_tick"] or reason:
            return {"ok": False, "reason": reason or "response predates the request"}
        conflict = self.counsel_conflict(request)
        if choice == "accept" and conflict:
            return {"ok": False, "reason": conflict}
        with self.e.estate_cases._batch():
            payload = {"request_id": request_id, "tick": tick, "actor_age": actor["age"],
                       "decision": "accepted" if choice == "accept" else "declined"}
            event = self.store.log_event(tick, "legal_counsel_responded", payload, phase="EXECUTION",
                subject_type="legal_matter", subject_id=request["matter_id"])
            response_id = self.store.insert("legal_counsel_responses", **payload, event_id=event)
            if choice == "accept" and request["side"] == "claimant":
                self.store.update("legal_matters", request["matter_id"], counsel_agent_id=actor_id)
            return {"ok": True, "response_id": response_id, "request_id": request_id, "event_id": event}

    def end(self, tick, actor_id, action):
        request_id = positive_integer_id(action.get("request_id"))
        request = self.store.query_one("SELECT * FROM legal_counsel_requests WHERE id=?", (request_id,)) if request_id else None
        if not self.enabled or request is None or self._adult(actor_id) is None or tick < request["requested_tick"]:
            return {"ok": False, "reason": "a living party or assigned lawyer must end the mandate"}
        if self.store.scalar("SELECT id FROM legal_counsel_ends WHERE request_id=?", (request_id,)):
            return {"ok": False, "reason": "counsel request already ended"}
        matter = self.store.query_one("SELECT * FROM legal_matters WHERE id=?", (request["matter_id"],))
        response = self._response(request_id)
        if response is not None and response["decision"] == "declined":
            return {"ok": False, "reason": "counsel request was declined"}
        if actor_id == request["counsel_id"]:
            if response is None:
                return {"ok": False, "reason": "decline the pending request before appointment"}
            proof = self._proof(tick, actor_id, matter, "end_legal_counsel", request["side"],
                {"capacity": "counsel", "estate_id": None, "counsel_request_id": request_id, "source": {"request_id": request_id}})
            reason = "withdrawn"
        else:
            proof = self.authorize(tick, actor_id, matter, "end_legal_counsel", request["side"], allow_counsel=False)
            reason = "revoked"
        if proof is None:
            return {"ok": False, "reason": "actor does not represent this client"}
        with self.e.estate_cases._batch():
            before = self.begin(proof)
            event = self._end(tick, request, reason, actor_id)
            self.record(request["matter_id"], proof, before, event)
            return {"ok": True, "request_id": request_id, "event_id": event}

    def assignments(self, actor_id, tick):
        return [dict(request) for request in self._current_requests() if request["counsel_id"] == actor_id
            and self._response(request["id"]) is not None and self._response(request["id"])["decision"] == "accepted"
            and request["requested_tick"] <= tick and self._response(request["id"])["tick"] <= tick
            and self.invalid_reason(request, tick) is None]

    def context_for(self, actor_id, tick):
        pending, eligible = [], []
        for request in self._current_requests():
            if request["counsel_id"] != actor_id or request["requested_tick"] > tick or self._response(request["id"]) is not None or self.invalid_reason(request, tick):
                continue
            conflict = self.counsel_conflict(request)
            pending.append({"request_id": request["id"], "matter_id": request["matter_id"], "side": request["side"],
                "requester_id": request["requester_id"], "expires_tick": request["expires_tick"],
                "scopes": json.loads(request["scopes_json"]), "conflict": conflict})
            eligible.append({"type": "respond_legal_counsel", "request_id": request["id"],
                             "decision": "decline" if conflict else "accept"})
            if len(pending) == 5:
                break
        return {"policy": self.POLICY, "pending_requests": pending, "eligible_actions": eligible[:1]}

    def matter_views(self, actor_id, tick, *, estate=False):
        """Private, bounded factual work for an accepted lawyer or estate party."""
        matters = []
        assignments = self.assignments(actor_id, tick) if not estate else []
        if estate:
            for row in self.store.query("SELECT * FROM legal_matters WHERE status IN ('filed','pleading','hearing','settlement_offered') "
                                        "AND filed_tick<=? ORDER BY id", (tick,)):
                for side in ("claimant", "respondent"):
                    proof = self.authorize(tick, actor_id, row, "submit_filing", side, allow_counsel=False)
                    if proof and proof["capacity"] == "estate":
                        assignments.append({"matter_id": row["id"], "side": side, "scopes_json": json.dumps(sorted(self.SCOPES))})
        for assignment in assignments:
            matter = self.store.query_one("SELECT * FROM legal_matters WHERE id=?", (assignment["matter_id"],))
            if matter is None or matter["filed_tick"] > tick:
                continue
            scopes = [scope for scope in json.loads(assignment["scopes_json"])
                      if self.authorize(tick, actor_id, matter, scope, assignment["side"]) is not None]
            metadata = json.loads(matter["metadata_json"] or "{}")
            raw = metadata.get("evidence_event_ids", []) if isinstance(metadata, dict) else []
            explicit = [metadata.get("source_event_id")] if isinstance(metadata, dict) else []
            explicit.extend(raw if isinstance(raw, list) else [])
            explicit = {value for item in explicit if (value := positive_integer_id(item)) is not None}
            sources = ["(subject_type='contract' AND subject_id=?)"]
            source_args = [matter["contract_id"]]
            if explicit:
                sources.append("id IN (" + ",".join("?" for _ in explicit) + ")")
                source_args.extend(sorted(explicit))
            events = [{"event_id": event["id"], "tick": event["tick"], "kind": event["kind"],
                       "facts": json.loads(event["payload_json"])} for event in self.store.query(
                "SELECT id,tick,kind,payload_json FROM events WHERE tick<=? AND kind IN "
                "('obligation_breached','obligation_performed','wage_missed','wage_earned','wage_paid') "
                "AND (" + " OR ".join(sources) + ") ORDER BY id LIMIT 12", (tick, *source_args))]
            filings = [dict(row) for row in self.store.query("SELECT id filing_id,filing_type,filer_type,filer_id,admitted,evidence_event_ids_json "
                "FROM legal_filings WHERE matter_id=? AND tick<=? ORDER BY id", (matter["id"], tick))]
            for filing in filings:
                filing["evidence_event_ids"] = json.loads(filing.pop("evidence_event_ids_json"))
            remedy = json.loads(matter["requested_remedy_json"] or "{}")
            try:
                remedy_valid = isinstance(remedy, dict) and self.e.legal._validate_remedy(matter, remedy) is None
            except (TypeError, ValueError, OverflowError):
                remedy_valid = False
            kind, party_id = self.party(matter, assignment["side"])
            matters.append({"matter_id": matter["id"], "status": matter["status"], "matter_type": matter["matter_type"],
                "claim_type": matter["claim_type"], "contract_id": matter["contract_id"],
                "claimant": {"type": matter["claimant_type"], "id": matter["claimant_id"]},
                "respondent": {"type": matter["respondent_type"], "id": matter["respondent_id"]},
                "side": assignment["side"], "represented_party": {"type": kind, "id": party_id},
                "authorized_actions": scopes, "request_id": assignment.get("id"),
                "response_due_tick": matter["response_due_tick"], "requested_remedy": remedy if remedy_valid else {},
                "settlement": json.loads(matter["settlement_json"] or "{}"), "evidence_events": events[:12], "filings": filings})
            if len(matters) == 5:
                break
        return matters

    def _check_authority(self, row, proof):
        actor = self.store.query_one("SELECT * FROM agents WHERE id=?", (row["actor_id"],))
        if actor is None or proof["actor_age"] < 18 or actor["age"] < proof["actor_age"]:
            raise EstateError("legal party authority has invalid actor age")
        if self.e.engine_semantics_version >= 21 and not self.e.population.history.is_living_resident(
                row["actor_id"], row["tick"], event_frontier=row["event_id"]-1):
            raise EstateError("legal party authority was not locally available at its event")
        for field, table, event_field in (("estate_frontier", "estate_cases", "completed_event_id"),
                ("administration_end_frontier", "estate_administration_ends", "event_id"),
                ("counsel_end_frontier", "legal_counsel_ends", "event_id")):
            actual = self.store.scalar(f"SELECT COALESCE(MAX(id),0) FROM {table} WHERE {event_field}<?", (row["event_id"],))
            if proof[field] != actual:
                raise EstateError("legal party authority has an incorrect historical frontier")
        if self.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=? AND id<=?",
                             (row["actor_id"], proof["estate_frontier"])):
            raise EstateError("legal party authority was already deceased")
        if row["capacity"] == "self":
            if (row["party_type"], row["party_id"]) != ("agent", row["actor_id"]):
                raise EstateError("personal legal authority has the wrong party")
        elif row["capacity"] == "organization":
            if row["party_type"] == "firm":
                interval_id = proof["source"].get("stewardship_id")
                if interval_id is None:
                    founder = self.store.scalar("SELECT founder_agent_id FROM firms WHERE id=?", (row["party_id"],))
                    if founder != row["actor_id"]:
                        raise EstateError("legal firm authority lacks its original founder")
                else:
                    interval = self.store.query_one("SELECT * FROM firm_stewardships WHERE id=?", (interval_id,))
                    if interval is None or (interval["firm_id"], interval["steward_agent_id"]) != (row["party_id"], row["actor_id"]) or (
                            interval["started_tick"] > row["tick"] or interval["recorded_event_id"] >= row["event_id"] or
                            (interval["ended_tick"] is not None and interval["ended_tick"] < row["tick"])):
                        raise EstateError("legal firm authority lacks its recorded operator")
            elif row["party_type"] not in {"government", "agency"} or proof["source"].get("role") not in {"gov_official", "regulator"}:
                raise EstateError("legal institutional authority has invalid role evidence")
        elif row["capacity"] == "estate":
            case = self.store.query_one("SELECT * FROM estate_cases WHERE id=?", (row["estate_id"],))
            if case is None or case["deceased_agent_id"] != row["party_id"] or row["party_type"] != "agent":
                raise EstateError("legal estate authority has the wrong nominee")
            source = proof["source"]
            if source.get("administration_id") is not None:
                self.e.estate_administration.check_order_authority({"estate_id": case["id"],
                    "actor_id": row["actor_id"], "actor_age": proof["actor_age"],
                    "administration_id": source["administration_id"],
                    "administration_end_frontier": proof["administration_end_frontier"],
                    "beneficiary_id": None, "guardian_id": None, "beneficiary_age": None, "path_json": "[]"}, row["tick"])
            else:
                route, case_id = source["path"], case["id"]
                if not route:
                    raise EstateError("legal estate authority lacks its beneficial path")
                for index, member_id in enumerate(route):
                    member = self.store.query_one("SELECT * FROM estate_beneficiaries WHERE id=?", (member_id,))
                    if member is None or member["estate_id"] != case_id or member["agent_id"] is None:
                        raise EstateError("legal estate authority has an invalid beneficial path")
                    descendant = self.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=? AND id<=?",
                        (member["agent_id"], proof["estate_frontier"]))
                    if index < len(route)-1:
                        if descendant is None:
                            raise EstateError("legal estate authority predates its beneficial path")
                        case_id = descendant
                    elif descendant is not None or member["agent_id"] != source["beneficiary_id"]:
                        raise EstateError("legal estate authority has the wrong living beneficiary")
                if source["guardian_id"] is None:
                    if row["actor_id"] != source["beneficiary_id"] or source["beneficiary_age"] < 18:
                        raise EstateError("legal estate authority lacks an adult beneficiary")
                else:
                    guardian = self.store.query_one("SELECT * FROM guardianships WHERE id=?", (source["guardian_id"],))
                    if guardian is None or guardian["guardian_agent_id"] != row["actor_id"] or (
                            guardian["child_agent_id"] != source["beneficiary_id"] or source["beneficiary_age"] >= 18
                            or guardian["started_tick"] > row["tick"] or
                            (guardian["ended_tick"] is not None and guardian["ended_tick"] < row["tick"])):
                        raise EstateError("legal estate authority lacks its recorded guardian")
        elif row["capacity"] == "counsel":
            request = self.store.query_one("SELECT * FROM legal_counsel_requests WHERE id=?", (row["counsel_request_id"],))
            response = self._response(request["id"]) if request is not None else None
            if request is None or (request["matter_id"], request["side"], request["counsel_id"]) != (
                    row["matter_id"], row["side"], row["actor_id"]) or response is None or response["decision"] != "accepted" or (
                    response["event_id"] >= row["event_id"] or (row["action"] != "end_legal_counsel" and
                    row["action"] not in json.loads(request["scopes_json"]))):
                raise EstateError("legal counsel acted without a matching accepted mandate")
            if self.store.scalar("SELECT id FROM legal_counsel_ends WHERE request_id=? AND id<=?",
                                 (request["id"], proof["counsel_end_frontier"])):
                raise EstateError("legal counsel acted after its recorded mandate ended")
        adversarial = proof.get("adversarial_authority")
        if adversarial is not None:
            other = "respondent" if row["side"] == "claimant" else "claimant"
            if not isinstance(adversarial, dict) or adversarial.get("side") != other or (
                    row["action"] not in self.PROCEDURAL or row["capacity"] == "counsel" or
                    adversarial.get("capacity") not in {"self", "estate", "organization"} or
                    adversarial.get("counsel_request_id") is not None):
                raise EstateError("dual-party authority exceeds its recorded procedural capacity")
            kind, party_id = proof["parties"][other]
            other_proof = {**proof, **adversarial, "party_type": kind, "party_id": party_id,
                           "adversarial_authority": None}
            other_row = {**dict(row), **{key: other_proof[key] for key in
                ("side", "party_type", "party_id", "capacity", "estate_id", "counsel_request_id")}}
            self._check_authority(other_row, other_proof)

    def check_invariants(self):
        if not self.enabled:
            return
        if self.store.scalar("SELECT m.id FROM legal_matters m WHERE NOT EXISTS(SELECT 1 FROM legal_action_authorities a "
                             "WHERE a.matter_id=m.id AND a.action='file_claim') LIMIT 1"):
            raise EstateError("legal matter lacks recorded claimant authority")
        if self.store.scalar("SELECT e.id FROM events e WHERE (e.kind IN ('legal_matter_filed','legal_filing_submitted',"
                "'settlement_offered','matter_settled','legal_counsel_requested') OR "
                "(e.kind='legal_counsel_ended' AND json_extract(e.payload_json,'$.actor_id') IS NOT NULL)) AND "
                "NOT EXISTS(SELECT 1 FROM legal_action_authorities a WHERE a.effect_event_id=e.id) LIMIT 1"):
            raise EstateError("legal action effect lacks recorded party authority")
        for row in self.store.query("SELECT * FROM legal_action_authorities ORDER BY id"):
            proof = json.loads(row["proof_json"])
            matter = self.store.query_one("SELECT * FROM legal_matters WHERE id=?", (row["matter_id"],))
            event = self.store.query_one("SELECT * FROM events WHERE id=?", (row["event_id"],))
            effect = self.store.query_one("SELECT * FROM events WHERE id=?", (row["effect_event_id"],))
            if matter is None or proof.get("policy") != self.POLICY or any(row[key] != proof.get(key)
                    for key in ("tick", "action", "actor_id", "side", "party_type", "party_id", "capacity", "estate_id", "counsel_request_id")):
                raise EstateError("legal action authority has inconsistent party evidence")
            if proof["parties"] != {s: list(self.party(matter, s)) for s in ("claimant", "respondent")}:
                raise EstateError("legal action authority changed its matter parties")
            if event is None or event["kind"] != "legal_action_authorized" or event["tick"] != row["tick"] or (
                    json.loads(event["payload_json"]) != proof or event["subject_type"] != row["party_type"] or event["subject_id"] != row["party_id"]):
                raise EstateError("legal action authority lacks its pre-action event")
            if effect is None or effect["kind"] != self.EFFECTS[row["action"]] or effect["tick"] != row["tick"] or (
                    effect["subject_type"] != "legal_matter" or effect["subject_id"] != row["matter_id"] or effect["id"] <= event["id"]):
                raise EstateError("legal action authority lacks its matching later effect")
            if row["action"] == "file_claim" and (row["side"] != "claimant" or matter["filed_tick"] != row["tick"]):
                raise EstateError("legal claim lacks authority from the named claimant")
            if row["action"] == "submit_filing":
                filing_id = json.loads(effect["payload_json"]).get("filing_id")
                filing = self.store.query_one("SELECT * FROM legal_filings WHERE id=?", (filing_id,))
                if filing is None or (filing["matter_id"], filing["tick"], filing["filer_type"], filing["filer_id"]) != (
                        row["matter_id"], row["tick"], row["party_type"], row["party_id"]):
                    raise EstateError("legal filing changed its authorized party")
            if row["action"] == "accept_settlement":
                offer = json.loads(matter["settlement_json"])
                proposer = self.store.query_one("SELECT * FROM legal_action_authorities WHERE id=?", (offer.get("authority_id"),))
                if offer.get("accepted_by") != row["actor_id"] or offer.get("accepted_tick") != row["tick"] or proposer is None or (
                        proposer["matter_id"] != row["matter_id"] or proposer["action"] != "propose_settlement" or
                        proposer["side"] == row["side"] or proposer["effect_event_id"] >= row["event_id"]):
                    raise EstateError("legal settlement lacks separate recorded party authority")
            self._check_authority(row, proof)
        self._check_counsel()

    def _check_counsel(self):
        for table in ("legal_counsel_responses", "legal_counsel_ends"):
            if self.store.scalar(f"SELECT e.id FROM {table} e LEFT JOIN legal_counsel_requests r ON r.id=e.request_id WHERE r.id IS NULL LIMIT 1"):
                raise EstateError("orphaned counsel consent or ending")
        accepted_sides = {}
        for request in self.store.query("SELECT * FROM legal_counsel_requests ORDER BY id"):
            payload = {key: request[key] for key in ("matter_id", "side", "requester_id", "counsel_id",
                "requested_tick", "expires_tick", "scopes_json", "authority_event_id")}
            event = self.store.query_one("SELECT * FROM events WHERE id=?", (request["event_id"],))
            authority = self.store.query_one("SELECT * FROM legal_action_authorities WHERE event_id=?", (request["authority_event_id"],))
            scopes = json.loads(request["scopes_json"])
            if not isinstance(scopes, list) or not scopes or any(s not in self.SCOPES for s in scopes) or scopes != sorted(set(scopes)):
                raise EstateError("counsel request has invalid action scopes")
            if event is None or event["kind"] != "legal_counsel_requested" or event["tick"] != request["requested_tick"] or (
                    event["subject_type"] != "legal_matter" or event["subject_id"] != request["matter_id"] or json.loads(event["payload_json"]) != payload):
                raise EstateError("counsel request lacks its matching offer event")
            if authority is None or (authority["matter_id"], authority["side"], authority["actor_id"], authority["action"], authority["effect_event_id"]) != (
                    request["matter_id"], request["side"], request["requester_id"], "request_legal_counsel", request["event_id"]):
                raise EstateError("counsel request lacks its client's recorded mandate")
            if json.loads(authority["proof_json"]).get("adversarial_authority") is not None and any(
                    scope != "submit_filing" for scope in scopes):
                raise EstateError("dual-party client delegated settlement authority")
            response = self._response(request["id"])
            ending = self.store.query_one("SELECT * FROM legal_counsel_ends WHERE request_id=?", (request["id"],))
            if response is not None:
                actor = self.store.query_one("SELECT * FROM agents WHERE id=?", (request["counsel_id"],))
                reply = self.store.query_one("SELECT * FROM events WHERE id=?", (response["event_id"],))
                response_payload = {key: response[key] for key in ("request_id", "tick", "actor_age", "decision")}
                if actor is None or actor["age"] < response["actor_age"] or not request["requested_tick"] <= response["tick"] < request["expires_tick"]:
                    raise EstateError("counsel response has invalid identity, age or time")
                if self.e.engine_semantics_version >= 21 and not self.e.population.history.is_living_resident(
                        request["counsel_id"], response["tick"], event_frontier=response["event_id"]-1):
                    raise EstateError("counsel responded while not locally available")
                if reply is None or reply["kind"] != "legal_counsel_responded" or reply["tick"] != response["tick"] or (
                        reply["id"] <= request["event_id"] or reply["subject_type"] != "legal_matter" or reply["subject_id"] != request["matter_id"]
                        or json.loads(reply["payload_json"]) != response_payload):
                    raise EstateError("counsel response lacks its matching consent event")
                if self.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=? AND completed_event_id<?",
                                     (request["counsel_id"], response["event_id"])):
                    raise EstateError("counsel responded after death")
                if response["decision"] == "accepted":
                    key = (request["matter_id"], request["counsel_id"])
                    if key in accepted_sides and accepted_sides[key] != request["side"]:
                        raise EstateError("counsel accepted both sides of one matter")
                    accepted_sides[key] = request["side"]
            if ending is not None:
                end_event = self.store.query_one("SELECT * FROM events WHERE id=?", (ending["event_id"],))
                end_payload = {key: ending[key] for key in ("request_id", "actor_id", "reason")}
                if ending["tick"] < request["requested_tick"] or end_event is None or end_event["kind"] != "legal_counsel_ended" or (
                        end_event["tick"] != ending["tick"] or end_event["subject_type"] != "legal_matter" or end_event["subject_id"] != request["matter_id"]
                        or json.loads(end_event["payload_json"]) != end_payload or end_event["id"] <= request["event_id"]
                        or (response is not None and end_event["id"] <= response["event_id"])):
                    raise EstateError("counsel ending lacks its correctly ordered event")
