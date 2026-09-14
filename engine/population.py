"""Pending external household movements and atomic demographic settlement.

Semantics 21 is still unregistered. The facade and local admission hooks are
being integrated before ordinary worlds can enable this draft regime.
"""
from __future__ import annotations

import json

from .population_history import POLICY, ResidenceError, ResidenceHistory, _integer, _request_key
from .population_commitments import PopulationCommitments


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


class MovementError(ResidenceError):
    """An inadmissible movement request."""


class MovementInvalidated(MovementError):
    """Formerly agreed demographic terms no longer describe current people."""


class PopulationBoundary:
    def __init__(self, economy):
        self.e = economy
        self.store = economy.store
        self.enabled = economy.engine_semantics_version >= 21
        self.history = ResidenceHistory(self.store) if self.enabled else None
        self.commitments = PopulationCommitments(self) if self.enabled else None

    def _require_enabled(self):
        if not self.enabled:
            raise MovementError("external population movements require Semantics 21")

    def is_local(self, agent_id, tick):
        self._require_enabled()
        return self.history.is_living_resident(agent_id, tick)

    def is_available(self, agent_id):
        """Current local authority; never use this to filter financial owners."""
        self._require_enabled()
        return agent_id is not None and self.history.is_current_resident(agent_id)

    def outside_action_allowed(self, actor_id, action, *, tick=None):
        """Admit only return requests/assents from a living outside adult."""
        self._require_enabled()
        actor = self.store.query_one("SELECT alive,age FROM agents WHERE id=?", (actor_id,))
        if not actor or not actor['alive'] or actor['age'] < 18 or not isinstance(action, dict):
            return False
        if tick is None:
            if self.is_available(actor_id):
                return False
        else:
            state = self.history.state_at(actor_id, tick)
            if state is None or state['state'] != 'outside':
                return False
        if action.get('type') == 'propose_population_movement':
            return action.get('cause') == 'return'
        if action.get('type') != 'respond_population_movement':
            return False
        movement_id = action.get('movement_id')
        if type(movement_id) is not int or movement_id <= 0 or not self.store.query_one(
                'SELECT id FROM population_movements WHERE id=?', (movement_id,)):
            return False
        row = self._read(movement_id)
        return (json.loads(row['terms_json'])['cause'] == 'return'
                and actor_id in json.loads(row['snapshot_json'])['adult_ids'])

    def action_context(self, actor_id, tick):
        from .population_actions import movement_context
        return movement_context(self, actor_id, tick)

    def _snapshot(self, actor_id, tick):
        actor = self.store.query_one("SELECT * FROM agents WHERE id=?", (actor_id,))
        membership = self.e.households.membership(actor_id)
        if not actor or not actor["alive"] or not membership:
            raise MovementInvalidated("movement actor no longer has a living household membership")
        home = self.store.query_one("SELECT * FROM households WHERE id=?", (membership["household_id"],))
        if not home or home["dissolved_tick"] is not None or home["formed_tick"] > tick:
            raise MovementInvalidated("movement household is no longer current")
        members, adults, states = [], [], set()
        rows = self.store.query(
            "SELECT m.*,a.alive,a.age,a.region_id FROM household_memberships m JOIN agents a ON a.id=m.agent_id "
            "WHERE m.household_id=? AND m.left_tick IS NULL ORDER BY m.agent_id", (home["id"],))
        if not 1 <= len(rows) <= 128:
            raise MovementError("movement household must have 1 to 128 members")
        for row in rows:
            person = self.history._person(row["agent_id"])
            if not row["alive"] or row["joined_tick"] > tick or row["region_id"] != home["region_id"]:
                raise MovementInvalidated("household membership changed or needs reconciliation")
            age = self.e.households.age_at(person["birth_tick"], tick)
            if row["age"] != age or (row["role"] == "dependent") != (age < 18):
                raise MovementInvalidated("household adulthood changed or needs reconciliation")
            state = self.history.state_at(row["agent_id"], tick)
            if state is None:
                raise ResidenceError("movement member lacks selected residence evidence")
            latest = self.store.scalar(
                "SELECT id FROM person_residence_events WHERE agent_id=? ORDER BY event_id DESC LIMIT 1",
                (row["agent_id"],))
            if latest != state["id"]:
                raise ResidenceError("movement cannot precede later residence history")
            guardian = self.store.query_one(
                "SELECT * FROM guardianships WHERE child_agent_id=? AND ended_tick IS NULL", (row["agent_id"],))
            members.append({"agent_id": row["agent_id"], "membership_id": row["id"],
                "joined_tick": row["joined_tick"], "adult": age >= 18, "role": row["role"],
                "birth_tick": person["birth_tick"], "residence_id": state["id"], "state": state["state"],
                "guardian_relation_id": guardian["id"] if guardian else None,
                "guardian_id": guardian["guardian_agent_id"] if guardian else None})
            states.add(state["state"])
            if age >= 18:
                adults.append(row["agent_id"])
        if len(states) != 1:
            raise MovementInvalidated("household has inconsistent residence states")
        if actor_id not in adults:
            raise MovementInvalidated("movement requires an affected adult actor")
        return {"household_id": home["id"], "region_id": home["region_id"],
                "formed_tick": home["formed_tick"], "members": members, "adult_ids": adults}

    def _terms(self, cause, member_ids, destination_region_id, care_plan):
        if cause not in ("departure", "return"):
            raise MovementError("movement cause must be departure or return")
        if not isinstance(member_ids, (list, tuple)) or not 1 <= len(member_ids) <= 128:
            raise MovementError("movement requires 1 to 128 member IDs")
        members = sorted(_integer(value, "member_id", minimum=1) for value in member_ids)
        if len(set(members)) != len(members):
            raise MovementError("duplicate movement member")
        if cause == "return":
            _integer(destination_region_id, "destination_region_id", minimum=1)
        elif destination_region_id is not None:
            raise MovementError("departure has no modeled destination region")
        if not isinstance(care_plan, (list, tuple)) or len(care_plan) > 128:
            raise MovementError("care_plan must list at most 128 child dispositions")
        care = []
        for item in care_plan:
            if not isinstance(item, dict) or set(item) != {"child_id", "guardian_id"}:
                raise MovementError("care disposition requires child_id and guardian_id")
            care.append({key: _integer(item[key], key, minimum=1) for key in ("child_id", "guardian_id")})
        care.sort(key=lambda item: item["child_id"])
        if len({item["child_id"] for item in care}) != len(care):
            raise MovementError("duplicate child care disposition")
        return {"cause": cause, "member_ids": members, "destination_region_id": destination_region_id,
                "care_plan": care, "accounting_policy": POLICY}

    def _admit(self, actor_id, terms, snapshot):
        members = {item["agent_id"]: item for item in snapshot["members"]}
        movers = set(terms["member_ids"])
        if actor_id not in movers or not movers <= members.keys():
            raise MovementError("actor and moving people must belong to the affected household")
        expected = "resident" if terms["cause"] == "departure" else "outside"
        if any(item["state"] != expected for item in members.values()):
            raise MovementError(f"{terms['cause']} requires a {expected} household")
        if terms["cause"] == "return" and not self.store.query_one(
                "SELECT id FROM regions WHERE id=?", (terms["destination_region_id"],)):
            raise MovementError("return destination region does not exist")
        minors = {person for person, item in members.items() if not item["adult"]}
        if {item["child_id"] for item in terms["care_plan"]} != minors:
            raise MovementError("every affected minor needs an explicit care disposition")
        for care in terms["care_plan"]:
            guardian = members.get(care["guardian_id"])
            if not guardian or not guardian["adult"]:
                raise MovementError("care disposition requires an affected adult guardian")
            if (care["child_id"] in movers) != (care["guardian_id"] in movers):
                raise MovementError("child and designated guardian must share the resulting household and residence")

    def _event(self, tick, kind, actor_id, payload, phase):
        return self.store.log_event(tick, kind, json.loads(_json(payload)), phase=phase,
                                    subject_type="agent", subject_id=actor_id, importance=2.0)

    def _read(self, movement_id):
        return read_movement(self.store, movement_id)

    def _check_event(self, event_id, tick, actor_id, kind, expected):
        _check_movement_event(self.store, event_id, tick, actor_id, kind, expected)

    @staticmethod
    def _result(row):
        return {"movement_id": row["id"], "status": row["status"], "due_tick": row["due_tick"],
                "closed_tick": row["closed_tick"], "reason": row["reason"],
                "destination_household_id": row["destination_household_id"]}

    def propose(self, tick, actor_id, cause, member_ids, request_key, *, due_tick,
                destination_region_id=None, care_plan=(), phase="EXECUTION"):
        self._require_enabled()
        _integer(tick, "tick")
        _integer(actor_id, "actor_id", minimum=1)
        _integer(due_tick, "due_tick", minimum=1)
        _request_key(request_key)
        if due_tick <= tick or phase not in {"GENESIS", "EXECUTION", "NIGHT_CLOSE"}:
            raise MovementError("movement must be prospective and use a supported phase")
        terms = self._terms(cause, member_ids, destination_region_id, care_plan)
        with self.store.savepoint("population_propose"):
            existing = self.store.query_one("SELECT id FROM population_movements WHERE actor_id=? AND request_key=?",
                                            (actor_id, request_key))
            if existing:
                row = self._read(existing["id"])
                if row["terms_json"] != _json(terms) or row["due_tick"] != due_tick or row["created_tick"] != tick:
                    raise MovementError("request key already binds different movement terms")
                return self._result(row)
            snapshot = self._snapshot(actor_id, tick)
            self._admit(actor_id, terms, snapshot)
            if self.store.query_one("SELECT id FROM population_movements WHERE household_id=? AND status='pending'",
                                    (snapshot["household_id"],)):
                raise MovementError("household already has a pending population movement")
            for adult in snapshot["adult_ids"]:
                if self.e.families.pending_interests(adult):
                    raise MovementError("affected adult already has a pending household agreement")
            event = self._event(tick, "population_movement_proposed", actor_id,
                {"request_key": request_key, "due_tick": due_tick, "terms": terms, "snapshot": snapshot}, phase)
            movement = self.store.insert("population_movements", actor_id=actor_id,
                household_id=snapshot["household_id"], request_key=request_key, created_tick=tick, due_tick=due_tick,
                terms_json=_json(terms), snapshot_json=_json(snapshot), proposal_event_id=event)
            self._assent(tick, self._read(movement), actor_id, "accept", phase)
            return self._result(self._read(movement))

    def _assent(self, tick, row, actor_id, decision, phase):
        event = self._event(tick, "population_movement_assent", actor_id,
                             {"movement_id": row["id"], "decision": decision}, phase)
        self.store.insert("population_movement_assents", movement_id=row["id"], actor_id=actor_id,
                          tick=tick, decision=decision, event_id=event)

    def _current(self, row, tick):
        try:
            current = self._snapshot(row["actor_id"], tick)
        except MovementInvalidated:
            return "household_snapshot_changed"
        return "" if _json(current) == row["snapshot_json"] else "household_snapshot_changed"

    def respond(self, tick, actor_id, movement_id, decision, *, phase="EXECUTION"):
        self._require_enabled()
        _integer(tick, "tick")
        _integer(actor_id, "actor_id", minimum=1)
        _integer(movement_id, "movement_id", minimum=1)
        if decision not in {"accept", "decline", "withdraw"} or phase not in {"EXECUTION", "NIGHT_CLOSE", "GENESIS"}:
            raise MovementError("unsupported movement response or phase")
        with self.store.savepoint("population_respond"):
            row = self._read(movement_id)
            if actor_id not in json.loads(row["snapshot_json"])["adult_ids"]:
                raise MovementError("only an affected adult may respond to this movement")
            existing = self.store.query_one("SELECT * FROM population_movement_assents "
                "WHERE movement_id=? AND actor_id=? AND decision=?", (movement_id, actor_id, decision))
            if existing:
                self._check_event(existing["event_id"], existing["tick"], actor_id,
                                  "population_movement_assent", {"movement_id": movement_id, "decision": decision})
                if tick != existing["tick"]:
                    raise MovementError("response retry has a different tick")
                return self._result(row)
            if row["status"] != "pending" or not row["created_tick"] <= tick <= row["due_tick"]:
                raise MovementError("movement is closed or response is outside its pending interval")
            reason = self._current(row, tick)
            if reason:
                return self._finish(tick, row, "cancelled", reason, phase=phase)
            if decision == "withdraw" and not self.store.query_one(
                    "SELECT id FROM population_movement_assents WHERE movement_id=? AND actor_id=? AND decision='accept'",
                    (movement_id, actor_id)):
                raise MovementError("cannot withdraw an assent that was never recorded")
            self._assent(tick, row, actor_id, decision, phase)
            if decision != "accept":
                return self._finish(tick, row, "cancelled", "adult_" + decision, phase=phase)
            return self._result(row)

    def _finish(self, tick, row, status, reason, *, destination=None, residence_ids=(), phase="NIGHT_CLOSE"):
        payload = {"movement_id": row["id"], "status": status, "reason": reason,
                   "destination_household_id": destination, "residence_ids": list(residence_ids)}
        event = self._event(tick, "population_movement_closed", row["actor_id"], payload, phase)
        self.store.update("population_movements", row["id"], status=status, closed_tick=tick, reason=reason,
                          destination_household_id=destination, outcome_event_id=event)
        return self._result(self._read(row["id"]))

    def settle(self, tick, movement_id):
        """Settle one due group or record why its prior agreement cannot apply."""
        self._require_enabled()
        _integer(tick, "tick", minimum=1)
        _integer(movement_id, "movement_id", minimum=1)
        with self.store.savepoint("population_settle"):
            row = self._read(movement_id)
            if row["status"] != "pending":
                self.commitments.check_invariants()
                return self._result(row)
            if tick < row["due_tick"]:
                raise MovementError("movement is not due")
            if self.store.query_one("SELECT tick FROM population_resident_census WHERE tick>=? LIMIT 1", (tick,)):
                raise MovementError("movement settlement cannot rewrite a recorded census")
            reason = "missed_due_tick" if tick > row["due_tick"] else self._current(row, tick)
            snapshot, terms = json.loads(row["snapshot_json"]), json.loads(row["terms_json"])
            accepted = set()
            for assent in self.store.query("SELECT * FROM population_movement_assents WHERE movement_id=? ORDER BY id", (movement_id,)):
                self._check_event(assent["event_id"], assent["tick"], assent["actor_id"], "population_movement_assent",
                                  {"movement_id": movement_id, "decision": assent["decision"]})
                if assent["decision"] != "accept" or not row["created_tick"] <= assent["tick"] <= tick:
                    raise ResidenceError("pending movement contains invalid assent evidence")
                accepted.add(assent["actor_id"])
            if reason or accepted != set(snapshot["adult_ids"]):
                return self._finish(tick, row, "cancelled", reason or "missing_adult_assent")
            self._admit(row["actor_id"], terms, snapshot)
            members = {item["agent_id"]: item for item in snapshot["members"]}
            residence_ids = [self.history.transition(tick, person, terms["cause"],
                previous_id=members[person]["residence_id"], request_key=f"population:{movement_id}")
                for person in terms["member_ids"]]
            destination = self.e.households.apply_population_movement(tick, movement_id, terms, snapshot)
            if terms["cause"] == "departure":
                for person in terms["member_ids"]:
                    self.commitments.end_person(tick, movement_id, person)
                    self.e.labor.end_for_departure(tick, person, movement_id)
                    self.e.civic_authority.release_for_departure(tick, movement_id, person)
                self.e.business_control.release_unavailable(tick, movement_id)
            self.e.business_control.refresh_custody(tick)
            self.e.project_rights.refresh(tick)
            self.e.legal_representation.reconcile(tick)
            self.e.families.invalidate_for_population_movement(tick, snapshot["adult_ids"], movement_id)
            result = self._finish(tick, row, "applied", "applied", destination=destination, residence_ids=residence_ids)
            self.commitments.check_invariants()
            return result

    def run_nightly(self, tick):
        if not self.enabled:
            return
        for row in self.store.query("SELECT id FROM population_movements WHERE status='pending' AND due_tick<=? ORDER BY due_tick,id", (tick,)):
            self.settle(tick, row["id"])


def read_movement(store, movement_id):
    row = store.query_one("SELECT * FROM population_movements WHERE id=?", (movement_id,))
    if row is None:
        raise MovementError("movement does not exist")
    expected = {"request_key": row["request_key"], "due_tick": row["due_tick"],
                "terms": json.loads(row["terms_json"]), "snapshot": json.loads(row["snapshot_json"])}
    _check_movement_event(store, row["proposal_event_id"], row["created_tick"], row["actor_id"],
                      "population_movement_proposed", expected)
    if row["status"] != "pending":
        event = store.query_one("SELECT * FROM events WHERE id=?", (row["outcome_event_id"],))
        if event is None:
            raise ResidenceError("movement outcome event is missing")
        residence_ids = []
        if row["status"] == "applied":
            if event["phase"] != "NIGHT_CLOSE":
                raise ResidenceError("applied movement has an invalid phase")
            terms = expected["terms"]
            members = {item["agent_id"]: item for item in expected["snapshot"]["members"]}
            for person in terms["member_ids"]:
                state = store.query_one("SELECT * FROM person_residence_events WHERE agent_id=? AND request_key=?",
                                             (person, f"population:{movement_id}"))
                if state is None:
                    raise ResidenceError("applied movement lacks a member's residence record")
                ResidenceHistory(store)._validate_record(state)
                if (state["tick"] != row["closed_tick"] or state["cause"] != terms["cause"]
                        or state["previous_id"] != members[person]["residence_id"]
                        or state["event_id"] >= row["outcome_event_id"]):
                    raise ResidenceError("applied movement residence disagrees with its agreed snapshot")
                residence_ids.append(state["id"])
        _check_movement_event(store, row["outcome_event_id"], row["closed_tick"], row["actor_id"],
            "population_movement_closed", {"movement_id": row["id"], "status": row["status"],
                "reason": row["reason"], "destination_household_id": row["destination_household_id"],
                "residence_ids": residence_ids})
    return row


def _check_movement_event(store, event_id, tick, actor_id, kind, expected):
    event = store.query_one("SELECT * FROM events WHERE id=?", (event_id,))
    if (event is None or event["tick"] != tick or event["subject_type"] != "agent"
            or event["subject_id"] != actor_id or event["kind"] != kind
            or _json(json.loads(event["payload_json"])) != _json(expected)):
        raise ResidenceError("movement event disagrees with its recorded terms")
