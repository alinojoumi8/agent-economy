"""Residence persistence and census, pending the complete population integration.

This is an internal history service, not a departure command. Its draft schema
is not yet registered: ordinary worlds cannot opt into partially wired movement.
The movement service must settle care, authority and participation in the same
outer savepoint before this history becomes an enabled behavior contract.
"""
from __future__ import annotations

import json
import sqlite3

from .migrations.v026_population_residence import verify as verify_schema

POLICY = "retained_assets_no_transfer_v1"
ORIGINS = frozenset({"genesis", "birth", "arrival", "engine_created"})


class ResidenceError(ValueError):
    """A supported residence record is missing, inconsistent or inadmissible."""


def _integer(value, name: str, *, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= 2**63 - 1:
        raise ResidenceError(f"{name} must be an integer at least {minimum}")
    return value


def _request_key(value) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 96 or not value.isprintable():
        raise ResidenceError("request_key must be 1 to 96 characters without control characters")
    return value


class ResidenceHistory:
    def __init__(self, store):
        self.store = store
        self._verify_schema()

    def _verify_schema(self):
        try:
            verify_schema(self.store.conn)
        except RuntimeError as exc:
            raise ResidenceError(str(exc)) from exc

    def _person(self, agent_id):
        person = self.store.query_one(
            "SELECT p.*,a.alive AS agent_alive,a.died_tick AS agent_died_tick,a.arrived_tick AS agent_arrived_tick "
            "FROM person_lifecycle p JOIN agents a ON a.id=p.agent_id WHERE p.agent_id=?", (agent_id,))
        if person is None:
            raise ResidenceError("residence requires a recorded person origin")
        if (person["origin_tick"] != person["agent_arrived_tick"]
                or (person["death_tick"] is None) != bool(person["agent_alive"])
                or person["death_tick"] != person["agent_died_tick"]):
            raise ResidenceError("person life identity disagrees with residence source")
        return person

    def _validate_record(self, row, *, previous=None):
        """Check source evidence independently of insert-time SQL guards."""
        row = dict(row)
        person = self._person(row["agent_id"])
        event = self.store.query_one("SELECT * FROM events WHERE id=?", (row["event_id"],))
        if event is None:
            raise ResidenceError("residence event evidence is missing")
        try:
            payload = json.loads(event["payload_json"])
        except (ValueError, TypeError) as exc:
            raise ResidenceError("residence event payload is invalid") from exc
        expected = {key: row[key] for key in (
            "state", "cause", "previous_id", "request_key", "ledger_frontier", "accounting_policy")}
        if (not isinstance(payload, dict) or payload != expected
                or any(type(payload[key]) is not type(value) for key, value in expected.items())
                or event["kind"] != "population_residence_recorded"
                or event["subject_type"] != "agent" or event["subject_id"] != row["agent_id"]
                or event["tick"] != row["tick"]
                or event["phase"] != ("GENESIS" if row["cause"] == "genesis" else "NIGHT_CLOSE")):
            raise ResidenceError("residence event disagrees with its record")
        if row["accounting_policy"] != POLICY or row["state"] not in {"resident", "outside"}:
            raise ResidenceError("unsupported residence policy or state")
        if row["tick"] < person["origin_tick"]:
            raise ResidenceError("residence precedes the person origin")
        if person["death_tick"] is not None:
            death = self._death_event(person)
            if row["tick"] > person["death_tick"] or row["event_id"] >= death["id"]:
                raise ResidenceError("residence changes after recorded death")
        if row["previous_id"] is None:
            if (row["cause"] != person["origin"] or row["tick"] != person["origin_tick"]
                    or row["cause"] not in ORIGINS or row["state"] != "resident"):
                raise ResidenceError("residence origin disagrees with immutable identity")
        else:
            if previous is None:
                previous = self.store.query_one(
                    "SELECT * FROM person_residence_events WHERE id=?", (row["previous_id"],))
            if (previous is None or previous["id"] != row["previous_id"]
                    or previous["agent_id"] != row["agent_id"]
                    or previous["tick"] > row["tick"] or previous["event_id"] >= row["event_id"]
                    or previous["state"] == row["state"]
                    or row["cause"] != ("departure" if row["state"] == "outside" else "return")
                    or previous["ledger_frontier"] > row["ledger_frontier"]):
                raise ResidenceError("residence predecessor or chronological state is inconsistent")
        if row["ledger_frontier"] > self.store.scalar("SELECT COALESCE(MAX(id),0) FROM transactions"):
            raise ResidenceError("residence ledger frontier is missing")
        return row

    def _death_event(self, person):
        events = self.store.query(
            "SELECT id,tick,payload_json FROM events WHERE kind='death' AND subject_type='agent' "
            "AND subject_id=? AND tick=? ORDER BY id", (person["agent_id"], person["death_tick"]))
        if len(events) != 1:
            raise ResidenceError("person death needs one matching event")
        try:
            payload = json.loads(events[0]["payload_json"])
        except (ValueError, TypeError) as exc:
            raise ResidenceError("death event payload is invalid") from exc
        if (not isinstance(payload, dict) or type(payload.get("agent_id")) is not int
                or payload["agent_id"] != person["agent_id"]):
            raise ResidenceError("death event identity disagrees with the person")
        return events[0]

    def record_origin(self, agent_id: int) -> int:
        agent_id = _integer(agent_id, "agent_id", minimum=1)
        person = self._person(agent_id)
        return self._record(person["origin_tick"], agent_id, "resident", person["origin"], None, "origin")

    def transition(self, tick: int, agent_id: int, cause: str, *, previous_id: int, request_key: str) -> int:
        """Record an already admitted movement inside its caller's transaction."""
        tick = _integer(tick, "tick", minimum=1)
        agent_id = _integer(agent_id, "agent_id", minimum=1)
        previous_id = _integer(previous_id, "previous_id", minimum=1)
        request_key = _request_key(request_key)
        if cause not in ("departure", "return"):
            raise ResidenceError("movement cause must be departure or return")
        state = "outside" if cause == "departure" else "resident"
        return self._record(tick, agent_id, state, cause, previous_id, request_key)

    def _record(self, tick, agent_id, state, cause, previous_id, request_key):
        with self.store.savepoint("population_residence"):
            existing = self.store.query_one(
                "SELECT * FROM person_residence_events WHERE agent_id=? AND request_key=?",
                (agent_id, request_key))
            if existing is not None:
                self._validate_record(existing)
                if any(existing[key] != value for key, value in {
                        "tick": tick, "state": state, "cause": cause, "previous_id": previous_id}.items()):
                    raise ResidenceError("request key already binds different residence terms")
                return int(existing["id"])
            frontier = int(self.store.scalar("SELECT COALESCE(MAX(id),0) FROM transactions"))
            payload = dict(state=state, cause=cause, previous_id=previous_id, request_key=request_key,
                           ledger_frontier=frontier, accounting_policy=POLICY)
            event_id = self.store.log_event(
                tick, "population_residence_recorded", payload,
                phase="GENESIS" if cause == "genesis" else "NIGHT_CLOSE",
                subject_type="agent", subject_id=agent_id, importance=2.0)
            try:
                return self.store.insert("person_residence_events", agent_id=agent_id, tick=tick,
                                         event_id=event_id, **payload)
            except sqlite3.IntegrityError as exc:
                raise ResidenceError(str(exc)) from exc

    def state_at(self, agent_id: int, tick: int, *, event_frontier: int | None = None) -> dict | None:
        """Residence at a selected boundary, independent of whether the person lives."""
        agent_id = _integer(agent_id, "agent_id", minimum=1)
        tick = _integer(tick, "tick")
        if event_frontier is not None:
            event_frontier = _integer(event_frontier, "event_frontier")
        person = self._person(agent_id)
        if person["origin_tick"] > tick:
            return None
        params = [agent_id, tick]
        clause = ""
        if event_frontier is not None:
            params.append(event_frontier)
            clause = " AND event_id<=?"
        row = self.store.query_one(
            "SELECT * FROM person_residence_events WHERE agent_id=? AND tick<=?" + clause
            + " ORDER BY tick DESC,event_id DESC LIMIT 1", params)
        if row is None:
            if event_frontier is not None:
                origin = self.store.query_one(
                    "SELECT * FROM person_residence_events WHERE agent_id=? AND previous_id IS NULL", (agent_id,))
                if origin is not None:
                    self._validate_record(origin)
                    if origin["event_id"] > event_frontier:
                        return None
            raise ResidenceError("selected person has no supported residence history")
        return self._validate_record(row)

    def is_living_resident(self, agent_id: int, tick: int, *, event_frontier: int | None = None) -> bool:
        """Local participation eligibility; financial ownership must not use this filter."""
        state = self.state_at(agent_id, tick, event_frontier=event_frontier)
        if state is None or state["state"] != "resident":
            return False
        person = self._person(agent_id)
        if person["death_tick"] is None or person["death_tick"] > tick:
            return True
        if person["death_tick"] < tick or event_frontier is None:
            return False
        return self._death_event(person)["id"] > event_frontier

    def audit_history(self) -> dict:
        """Check complete chains and bindings without writing a repair."""
        self._verify_schema()
        prior = {}
        count = 0
        for row in self.store.conn.execute("SELECT * FROM person_residence_events ORDER BY event_id"):
            expected = prior.get(row["agent_id"])
            if row["previous_id"] != (expected["id"] if expected is not None else None):
                raise ResidenceError("residence chain skips or branches from its predecessor")
            valid = self._validate_record(row, previous=expected)
            prior[row["agent_id"]] = valid
            count += 1
        missing = self.store.query_one(
            "SELECT agent_id FROM person_lifecycle WHERE NOT EXISTS "
            "(SELECT 1 FROM person_residence_events r WHERE r.agent_id=person_lifecycle.agent_id) LIMIT 1")
        if missing is not None:
            raise ResidenceError("person origin lacks its residence history")
        return {"people": len(prior), "residence_records": count}

    def is_current_resident(self, agent_id: int) -> bool:
        """Current operational eligibility, separate from selected-day readers."""
        agent_id = _integer(agent_id, "agent_id", minimum=1)
        person = self._person(agent_id)
        row = self.store.query_one(
            "SELECT * FROM person_residence_events WHERE agent_id=? ORDER BY event_id DESC LIMIT 1", (agent_id,))
        if row is None:
            raise ResidenceError("current person has no supported residence history")
        return self._validate_record(row)["state"] == "resident" and person["death_tick"] is None

    def _population_at(self, tick: int) -> tuple[int, int]:
        residents = outside = 0
        for person in self.store.conn.execute(
                "SELECT * FROM person_lifecycle WHERE origin_tick<=? ORDER BY agent_id", (tick,)):
            state = self.state_at(person["agent_id"], tick)
            if person["death_tick"] is not None and person["death_tick"] <= tick:
                continue
            if state["state"] == "resident":
                residents += 1
            else:
                outside += 1
        return residents, outside

    def census_values(self, tick: int) -> dict:
        """Derive local population flows from identity, residence and death evidence."""
        tick = _integer(tick, "tick")
        closing, outside = self._population_at(tick)
        if tick == 0:
            if self.store.scalar("SELECT COUNT(*) FROM person_lifecycle WHERE origin_tick=0 AND origin<>'genesis'"):
                raise ResidenceError("genesis census requires a declared genesis opening stock")
            opening = closing
        else:
            previous = self.store.query_one("SELECT * FROM population_resident_census WHERE tick=?", (tick - 1,))
            if previous is None:
                raise ResidenceError("resident census requires the preceding committed day")
            opening = int(previous["closing_residents"])
            recomputed, _ = self._population_at(tick - 1)
            if opening != recomputed:
                raise ResidenceError("previous resident census disagrees with historical evidence")
        flows = {"birth": 0, "arrival": 0, "return": 0, "engine_created": 0, "departure": 0}
        for row in self.store.conn.execute("SELECT * FROM person_residence_events WHERE tick=? ORDER BY id", (tick,)):
            self._validate_record(row)
            if row["cause"] in flows:
                flows[row["cause"]] += 1
        resident_deaths = 0
        for person in self.store.conn.execute("SELECT * FROM person_lifecycle WHERE death_tick=? ORDER BY agent_id", (tick,)):
            event = self._death_event(person)
            state = self.state_at(person["agent_id"], tick, event_frontier=event["id"] - 1)
            resident_deaths += state["state"] == "resident"
        values = dict(tick=tick, opening_residents=opening, births=flows["birth"], arrivals=flows["arrival"],
                      returns=flows["return"], other_entries=flows["engine_created"], departures=flows["departure"],
                      resident_deaths=resident_deaths, closing_residents=closing,
                      known_living_outside=outside, total_known_living=closing + outside)
        if closing != opening + sum(flows[k] for k in ("birth", "arrival", "return", "engine_created")) - flows["departure"] - resident_deaths:
            raise ResidenceError("resident census identity does not reconcile")
        return values

    def record_census(self, tick: int) -> dict:
        with self.store.savepoint("resident_census"):
            values = self.census_values(tick)
            existing = self.store.query_one("SELECT * FROM population_resident_census WHERE tick=?", (tick,))
            if existing is not None:
                if dict(existing) != values:
                    raise ResidenceError("cannot rewrite a recorded resident census")
            else:
                self.store.insert("population_resident_census", **values)
            return values
