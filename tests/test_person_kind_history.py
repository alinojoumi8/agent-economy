"""A real later staff succession must not change past research cohorts."""
import json
from types import SimpleNamespace

import pytest

from engine.person_kind_history import PersonKindHistoryError, person_kinds_at
from engine.position_history import cash_distribution_at
from research.hashing import canonical_hashes
from research.household_positions import household_positions
from .test_semantics20_civic_succession import city_world, available_adult


def promote(world, tick=3):
    store, economy = world.store, world.economy
    candidate = available_adult(world)
    region = store.scalar("SELECT region_id FROM agents WHERE id=?", (candidate,))
    staff = store.query_one("SELECT * FROM agency_staff WHERE region_id=? AND active=1", (region,))
    original = staff["agent_id"]
    before = household_positions(store, tick=0)
    economy.lifecycle.settle_death(tick, original)
    economy.city.run_nightly(tick)
    event = store.query_one("SELECT * FROM events WHERE kind='agency_staff_succeeded' "
                            "AND tick=? AND subject_id=?", (tick, candidate))
    assert event is not None
    store.execute("UPDATE run_meta SET tick=?,active_tick=NULL", (tick,))
    return SimpleNamespace(store=store, economy=economy, candidate=candidate,
                           original=original, before=before, event=dict(event), tick=tick)


def test_later_promotion_preserves_full_earlier_report_and_current_cash(city_world, monkeypatch):
    case = promote(city_world)
    before = canonical_hashes(case.store)
    assert household_positions(case.store, tick=0) == case.before
    assert person_kinds_at(case.store, 0)[case.original] == "staff"
    assert person_kinds_at(case.store, 0)[case.candidate] == "citizen"
    assert person_kinds_at(case.store, case.tick)[case.candidate] == "staff"
    current = cash_distribution_at(case.store, case.tick)
    assert all(case.candidate not in row["person_cash_cents"] for row in current.values())

    def old_current_kinds(store, tick):
        return {r["agent_id"]: r["kind"] for r in store.query(
            "SELECT p.agent_id,a.kind FROM person_lifecycle p JOIN agents a ON a.id=p.agent_id "
            "WHERE p.origin_tick<=?", (tick,))}

    monkeypatch.setattr("engine.position_history.person_kinds_at", old_current_kinds)
    assert cash_distribution_at(case.store, case.tick) == current
    assert canonical_hashes(case.store) == before


def test_same_day_proposal_precedes_nightly_promotion_and_later_boundary_follows_it(city_world):
    store, economy = city_world.store, city_world.economy
    candidate = available_adult(city_world)
    partner = store.scalar("SELECT id FROM agents WHERE kind='citizen' AND id<>? AND age>=18 "
                           "AND alive=1 AND role IS NULL ORDER BY id LIMIT 1", (candidate,))
    a, b = sorted((candidate, partner))
    store.execute("INSERT OR REPLACE INTO social_ties(agent_a,agent_b,weight) VALUES (?,?,0.9)", (a, b))
    proposal = economy.families.propose(3, candidate, "partnership", "same-day-kind", partner_id=partner)
    assert proposal["ok"], proposal
    proposed = store.query_one("SELECT id FROM events WHERE kind='household_decision_proposed' "
        "AND json_extract(payload_json,'$.household_decision_id')=?", (proposal["household_decision_id"],))
    assert proposed is not None
    case = promote(city_world, 3)
    assert proposed["id"] < case.event["id"]
    later = store.log_event(3, "boundary_probe", {}, phase="NIGHT_CLOSE")
    assert person_kinds_at(store, 3, before_event_id=proposed["id"])[candidate] == "citizen"
    assert person_kinds_at(store, 3, before_event_id=case.event["id"])[candidate] == "citizen"
    assert person_kinds_at(store, 3, before_event_id=later)[candidate] == "staff"
    assert person_kinds_at(store, 3)[candidate] == "staff"
    with pytest.raises(PersonKindHistoryError, match="event boundary"):
        person_kinds_at(store, 2, before_event_id=proposed["id"])


def test_ending_staff_assignment_does_not_recreate_citizenship(city_world):
    case = promote(city_world)
    staff = case.store.query_one("SELECT * FROM agency_staff WHERE agent_id=?", (case.candidate,))
    case.economy.city._end_staff_assignment(4, staff)
    case.store.execute("UPDATE run_meta SET tick=4")
    assert person_kinds_at(case.store, 4)[case.candidate] == "staff"
    assert household_positions(case.store, tick=0) == case.before


@pytest.mark.parametrize("fault", ["missing_event", "missing_assignment", "wrong_phase",
                                   "wrong_identity", "duplicate_event", "wrong_current_kind",
                                   "noninteger_identity"])
def test_inconsistent_role_history_is_unavailable_without_mutating_source(city_world, fault):
    case = promote(city_world)
    s, event = case.store, case.event
    if fault == "missing_event":
        s.execute("DELETE FROM events WHERE id=?", (event["id"],))
    elif fault == "missing_assignment":
        s.execute("DELETE FROM agency_staff WHERE agent_id=?", (case.candidate,))
    elif fault == "wrong_phase":
        s.execute("UPDATE events SET phase='EXECUTION' WHERE id=?", (event["id"],))
    elif fault in ("wrong_identity", "noninteger_identity"):
        value = json.loads(event["payload_json"])
        value["semantic_receipt"]["object"]["id"] = (
            case.candidate + 1 if fault == "wrong_identity" else float(case.candidate))
        s.execute("UPDATE events SET payload_json=? WHERE id=?", (json.dumps(value), event["id"]))
    elif fault == "duplicate_event":
        s.insert("events", **{k: v for k, v in event.items() if k != "id"})
    else:
        s.update("agents", case.candidate, kind="citizen")
    before = canonical_hashes(s)
    with pytest.raises(PersonKindHistoryError):
        household_positions(s, tick=0)
    assert canonical_hashes(s) == before
