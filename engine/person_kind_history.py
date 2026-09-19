"""Selected-boundary person kinds from the recorded citizen-to-staff transition."""
from __future__ import annotations

import json


class PersonKindHistoryError(ValueError):
    """The recorded role transition cannot support a historical kind."""


def staff_promotion_identity(event) -> tuple[int, int, int, int]:
    """Validate the shared citizen-to-clerk receipt; callers bind its assignment."""
    person = event["subject_id"]
    if event["subject_type"] != "agent" or event["phase"] != "NIGHT_CLOSE":
        raise PersonKindHistoryError("invalid person-kind transition")
    try:
        payload = json.loads(event["payload_json"])
        role, region, place = (payload[k] for k in ("role_key", "region_id", "place_id"))
        semantic = payload["semantic_receipt"]
        agency = semantic["actor"]["id"]
        if (role != "permit_clerk" or any(type(v) is not int for v in (region, place, agency))
                or type(semantic["object"]["id"]) is not int
                or semantic != {"actor": {"type": "agency", "id": agency},
                    "verb": "reassigned", "object": {"type": "agent", "id": person},
                    "outcome": "active"}):
            raise ValueError("transition identity")
    except (ValueError, KeyError, TypeError) as exc:
        raise PersonKindHistoryError("invalid person-kind transition payload") from exc
    return person, agency, region, place


def person_kinds_at(store, tick: int, *, before_event_id: int | None = None) -> dict[int, str]:
    """Read kinds at day close, or immediately before a recorded same-day event.

    Origin eligibility is day-scoped. Lifetimes and membership remain the
    caller's responsibility. Existing kinds are immutable except for the
    citizen-to-permit-staff transition recorded by City._promote_successor.
    Staff assignment ending does not change kind back to citizen.
    """
    if type(tick) is not int or tick < 0:
        raise ValueError("tick must be a nonnegative integer")
    if before_event_id is not None:
        if type(before_event_id) is not int or not 0 < before_event_id < 2**63:
            raise ValueError("before_event_id must be a positive SQLite integer")
        event = store.query_one("SELECT tick FROM events WHERE id=?", (before_event_id,))
        if event is None or event["tick"] != tick:
            raise PersonKindHistoryError("event boundary is not recorded on the selected day")
    people = {r["agent_id"]: r["kind"] for r in store.query(
        "SELECT p.agent_id,a.kind FROM person_lifecycle p JOIN agents a ON a.id=p.agent_id "
        "WHERE p.origin_tick<=? ORDER BY p.agent_id", (tick,))}
    cutoff = tick if before_event_id is not None else tick + 1
    transitions = {}
    for event in store.query(
            "SELECT * FROM events WHERE kind='agency_staff_succeeded' AND tick>=? ORDER BY tick,id",
            (cutoff,)):
        person, agency, region, place = staff_promotion_identity(event)
        if person in transitions:
            raise PersonKindHistoryError("invalid or repeated person-kind transition")
        assignments = store.query(
            "SELECT id FROM agency_staff WHERE agent_id=? AND agency_id=? AND region_id=? "
            "AND place_id=? AND role_key=? AND effective_tick=? AND created_tick=?",
            (person, agency, region, place, "permit_clerk", event["tick"], event["tick"]))
        if len(assignments) != 1:
            raise PersonKindHistoryError("person-kind transition lacks one matching staff assignment")
        transitions[person] = event
        if person in people:
            if people[person] != "staff":
                raise PersonKindHistoryError("recorded promotion disagrees with current person kind")
            if (event["tick"] > tick or before_event_id is not None
                    and event["id"] >= before_event_id):
                people[person] = "citizen"

    # A later first appointment for an already registered person is not a
    # genesis staff identity. Missing its promotion receipt means unknown
    # history, not permission to back-project today's staff kind.
    for assignment in store.query(
            "SELECT s.agent_id FROM agency_staff s JOIN person_lifecycle p ON p.agent_id=s.agent_id "
            "JOIN agents a ON a.id=s.agent_id WHERE a.kind='staff' AND s.created_tick>p.origin_tick "
            "AND s.effective_tick>=? AND NOT EXISTS (SELECT 1 FROM agency_staff prior "
            "WHERE prior.agent_id=s.agent_id AND prior.created_tick<s.created_tick)",
            (cutoff,)):
        if assignment["agent_id"] not in transitions:
            raise PersonKindHistoryError("later staff appointment lacks recorded kind history")
    return people
