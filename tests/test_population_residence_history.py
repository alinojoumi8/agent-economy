"""Draft residence persistence, conservation and historical population proofs.

These tests exercise the history layer only. They do not establish household
movement admission, absent-actor exclusion or an enabled Semantics-21 world.
"""
from pathlib import Path
from types import SimpleNamespace
import hashlib
import json
import sqlite3

import pytest

from engine.migrations import registered_migrations
from engine.migrations.v026_population_residence import SQL
from engine.population_history import ResidenceError, ResidenceHistory
from engine.schema import SCHEMA_VERSION
from engine.semantics import CURRENT_ENGINE_SEMANTICS_VERSION, validate_engine_semantics_version
from engine.store import Store, open_read_only_connection

from .conftest import make_agent
from .test_semantics19_estate_cash import spent_loan
from .test_semantics20_estate_cases import estate_case


def contents(store, *, protected_only=False):
    excluded = {"events", "person_residence_events", "population_resident_census"} if protected_only else set()
    names = [row[0] for row in store.conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    return {name: [tuple(row) for row in store.conn.execute(f'SELECT * FROM "{name}" ORDER BY rowid')]
            for name in names if name not in excluded and not name.startswith("sqlite_")}


@pytest.fixture
def residence_case(estate_case):
    e, bank, person, wallet, heir, heir_wallet = estate_case
    # Explicit fixture installation: no registered migration or public opt-in.
    e.store.conn.executescript(SQL)
    history = ResidenceHistory(e.store)
    origins = {agent: history.record_origin(agent) for agent in (person, heir)}
    history.record_census(0)
    return SimpleNamespace(e=e, bank=bank, person=person, wallet=wallet, heir=heir,
                           heir_wallet=heir_wallet, history=history, origins=origins)


def test_unfinished_population_boundary_is_not_advertised(store):
    assert SCHEMA_VERSION == 25 and CURRENT_ENGINE_SEMANTICS_VERSION == 20
    assert 26 not in {migration.version for migration in registered_migrations()}
    with pytest.raises(ValueError, match="unsupported"):
        validate_engine_semantics_version(21)
    before = contents(store)
    with pytest.raises(ResidenceError, match="missing"):
        ResidenceHistory(store)
    assert contents(store) == before


def test_history_preserves_all_financial_and_identity_rows_and_never_refunds_arrival(residence_case):
    c = residence_case
    c.e.firms.found_firm(0, c.person, "Retained company", "manufacturing", shares=100)
    spent_loan(c.e, c.bank, c.person, c.wallet, 30)
    c.e.ledger.create_account("agent", c.person, "fx", currency_code="EUR", opening_cents=37, tick=0)
    before = contents(c.e.store, protected_only=True)
    departure = c.history.transition(1, c.person, "departure", previous_id=c.origins[c.person], request_key="trip-1-out")
    out = c.history.record_census(1)
    assert (out["closing_residents"], out["known_living_outside"], out["departures"], out["total_known_living"]) == (1, 1, 1, 2)
    returned = c.history.transition(2, c.person, "return", previous_id=departure, request_key="trip-1-back")
    back = c.history.record_census(2)
    assert (back["opening_residents"], back["returns"], back["arrivals"], back["closing_residents"]) == (1, 1, 0, 2)
    assert contents(c.e.store, protected_only=True) == before
    assert c.e.ledger.reconcile()[0]
    assert [c.history.state_at(c.person, tick)["state"] for tick in (0, 1, 2)] == ["resident", "outside", "resident"]
    exact = contents(c.e.store)
    assert c.history.record_origin(c.person) == c.origins[c.person]
    assert c.history.transition(1, c.person, "departure", previous_id=c.origins[c.person], request_key="trip-1-out") == departure
    assert c.history.transition(2, c.person, "return", previous_id=departure, request_key="trip-1-back") == returned
    assert c.history.record_census(1) == out
    assert contents(c.e.store) == exact
    assert c.history.audit_history() == {"people": 2, "residence_records": 4}


def test_stale_predecessor_and_conflicting_retry_roll_back_their_events(residence_case):
    c = residence_case
    departure = c.history.transition(1, c.person, "departure", previous_id=c.origins[c.person], request_key="out")
    c.history.transition(2, c.person, "return", previous_id=departure, request_key="back")
    before = contents(c.e.store)
    with pytest.raises(ResidenceError, match="predecessor"):
        c.history.transition(3, c.person, "departure", previous_id=c.origins[c.person], request_key="stale")
    with pytest.raises(ResidenceError, match="different residence terms"):
        c.history.transition(3, c.person, "departure", previous_id=c.origins[c.person], request_key="out")
    assert contents(c.e.store) == before


def test_outer_movement_transaction_can_roll_back_every_history_and_event(residence_case):
    c = residence_case
    before = contents(c.e.store)
    with pytest.raises(ResidenceError, match="predecessor"):
        with c.e.store.savepoint("future_group_movement"):
            c.history.transition(1, c.person, "departure", previous_id=c.origins[c.person], request_key="group")
            c.history.transition(1, c.heir, "departure", previous_id=c.origins[c.person], request_key="group")
    assert contents(c.e.store) == before


def test_injected_storage_failure_leaves_no_orphan_residence_event(residence_case):
    c = residence_case
    c.e.store.execute("CREATE TRIGGER fail_residence BEFORE INSERT ON person_residence_events BEGIN SELECT RAISE(ABORT,'injected'); END")
    before = contents(c.e.store)
    with pytest.raises(ResidenceError, match="injected"):
        c.history.transition(1, c.person, "departure", previous_id=c.origins[c.person], request_key="out")
    assert contents(c.e.store) == before


def test_first_arrival_birth_and_outside_death_have_distinct_census_flows(residence_case):
    c = residence_case
    child = c.e.households.birth(1, c.person)
    c.history.record_origin(child)
    newcomer, _ = make_agent(c.e, c.bank, "New arrival", cash=0, region_id=1, arrived_tick=1)
    c.e.households.register_person(1, newcomer, "arrival")
    c.history.record_origin(newcomer)
    first = c.history.record_census(1)
    assert (first["births"], first["arrivals"], first["returns"], first["closing_residents"]) == (1, 1, 0, 4)
    c.history.transition(2, c.person, "departure", previous_id=c.origins[c.person], request_key="out")
    c.e.lifecycle.settle_death(2, c.person)
    second = c.history.record_census(2)
    assert (second["departures"], second["resident_deaths"], second["closing_residents"], second["total_known_living"]) == (1, 0, 3, 3)
    c.e.lifecycle.settle_death(3, c.heir)
    third = c.history.record_census(3)
    assert (third["resident_deaths"], third["closing_residents"], third["known_living_outside"]) == (1, 2, 0)
    assert c.history.record_census(1) == first
    assert c.history.state_at(newcomer, 0) is None
    assert c.history.audit_history() == {"people": 4, "residence_records": 5}


def test_same_day_return_and_death_use_the_residence_before_death_event(residence_case):
    c = residence_case
    departure = c.history.transition(1, c.person, "departure", previous_id=c.origins[c.person], request_key="out")
    c.history.record_census(1)
    returned = c.history.transition(2, c.person, "return", previous_id=departure, request_key="back")
    event = c.e.store.scalar("SELECT event_id FROM person_residence_events WHERE id=?", (returned,))
    assert c.history.state_at(c.person, 2, event_frontier=event - 1)["state"] == "outside"
    assert c.history.state_at(c.person, 2, event_frontier=event)["state"] == "resident"
    assert not c.history.is_living_resident(c.person, 1)
    c.e.lifecycle.settle_death(2, c.person)
    death = c.e.store.scalar("SELECT id FROM events WHERE kind='death' AND subject_id=?", (c.person,))
    assert c.history.is_living_resident(c.person, 0)
    assert c.history.is_living_resident(c.person, 2, event_frontier=death - 1)
    assert not c.history.is_living_resident(c.person, 2, event_frontier=death)
    assert not c.history.is_living_resident(c.person, 2)
    assert not c.history.is_living_resident(c.person, 3)
    values = c.history.record_census(2)
    assert (values["returns"], values["resident_deaths"], values["closing_residents"], values["total_known_living"]) == (1, 1, 1, 1)
    with pytest.raises(ResidenceError, match="living person"):
        c.history.transition(3, c.person, "departure", previous_id=returned, request_key="after-death")


def test_same_day_origin_respects_the_selected_event_frontier(residence_case):
    c = residence_case
    origin = c.history.state_at(c.person, 0)
    assert c.history.state_at(c.person, 0, event_frontier=origin["event_id"] - 1) is None
    assert c.history.state_at(c.person, 0, event_frontier=origin["event_id"])["state"] == "resident"
    assert not c.history.is_living_resident(c.person, 0, event_frontier=origin["event_id"] - 1)


def test_same_day_chain_follows_event_order_when_surrogate_ids_differ(residence_case):
    c = residence_case
    frontier = c.e.store.scalar("SELECT MAX(id) FROM transactions")
    predecessor = c.origins[c.person]
    events = []
    for row_id, state, cause in ((100, "outside", "departure"), (10, "resident", "return")):
        payload = dict(state=state, cause=cause, previous_id=predecessor, request_key=cause,
                       ledger_frontier=frontier, accounting_policy="retained_assets_no_transfer_v1")
        event_id = c.e.store.log_event(1, "population_residence_recorded", payload,
                                      phase="NIGHT_CLOSE", subject_type="agent", subject_id=c.person)
        c.e.store.insert("person_residence_events", id=row_id, agent_id=c.person, tick=1, event_id=event_id, **payload)
        events.append(event_id)
        predecessor = row_id
    assert c.history.state_at(c.person, 1, event_frontier=events[0])["id"] == 100
    assert c.history.state_at(c.person, 1)["id"] == 10
    values = c.history.record_census(1)
    assert (values["opening_residents"], values["returns"], values["departures"], values["closing_residents"]) == (2, 1, 1, 2)
    assert c.history.audit_history() == {"people": 2, "residence_records": 4}
    assert c.history.transition(2, c.person, "departure", previous_id=10, request_key="again") > 100


@pytest.mark.parametrize("damage", ["boolean_predecessor", "extra_key", "wrong_subject", "wrong_phase"])
def test_sql_admission_rejects_event_evidence_that_does_not_bind_the_transition(residence_case, damage):
    c = residence_case
    frontier = c.e.store.scalar("SELECT MAX(id) FROM transactions")
    payload = dict(state="outside", cause="departure", previous_id=c.origins[c.person],
                   request_key="raw", ledger_frontier=frontier, accounting_policy="retained_assets_no_transfer_v1")
    invalid_payload = dict(payload)
    if damage == "boolean_predecessor":
        assert c.origins[c.person] == 1
        invalid_payload["previous_id"] = True
    if damage == "extra_key":
        invalid_payload["unrecorded"] = 1
    before = contents(c.e.store)
    with pytest.raises(sqlite3.IntegrityError, match="does not bind"):
        with c.e.store.savepoint("raw_invalid_residence"):
            event = c.e.store.log_event(1, "population_residence_recorded", invalid_payload,
                phase="MORNING" if damage == "wrong_phase" else "NIGHT_CLOSE",
                subject_type="agent", subject_id=c.heir if damage == "wrong_subject" else c.person)
            c.e.store.insert("person_residence_events", agent_id=c.person, tick=1, event_id=event, **payload)
    assert contents(c.e.store) == before


def test_future_or_missing_history_is_never_a_guessed_resident(residence_case):
    c = residence_case
    newcomer, _ = make_agent(c.e, c.bank, "Unregistered residence", cash=0, region_id=1, arrived_tick=2)
    c.e.households.register_person(2, newcomer, "arrival")
    assert c.history.state_at(newcomer, 1) is None
    with pytest.raises(ResidenceError, match="event_frontier"):
        c.history.state_at(newcomer, 1, event_frontier=-1)
    before = contents(c.e.store)
    with pytest.raises(ResidenceError, match="no supported residence history"):
        c.history.state_at(newcomer, 2)
    with pytest.raises(ResidenceError, match="lacks its residence history"):
        c.history.audit_history()
    assert contents(c.e.store) == before


@pytest.mark.parametrize("damage", ["state", "identity", "boolean_frontier", "extra_key"])
def test_mutated_event_evidence_is_rejected_without_repair(residence_case, damage):
    c = residence_case
    row = c.history.state_at(c.person, 0)
    event = c.e.store.query_one("SELECT * FROM events WHERE id=?", (row["event_id"],))
    payload = json.loads(event["payload_json"])
    if damage == "state":
        payload["state"] = "outside"
    elif damage == "boolean_frontier":
        payload["ledger_frontier"] = True
    elif damage == "extra_key":
        payload["unrecorded"] = 1
    if damage == "identity":
        c.e.store.update("events", event["id"], subject_id=c.heir)
    else:
        c.e.store.update("events", event["id"], payload_json=json.dumps(payload))
    before = contents(c.e.store)
    with pytest.raises(ResidenceError, match="event disagrees"):
        c.history.state_at(c.person, 0)
    with pytest.raises(ResidenceError, match="event disagrees"):
        c.history.audit_history()
    assert contents(c.e.store) == before


def test_death_identity_corruption_cannot_be_counted_as_a_valid_exit(residence_case):
    c = residence_case
    c.e.lifecycle.settle_death(1, c.person)
    death = c.e.store.query_one("SELECT * FROM events WHERE kind='death' AND subject_id=?", (c.person,))
    payload = json.loads(death["payload_json"])
    payload["agent_id"] = c.heir
    c.e.store.update("events", death["id"], payload_json=json.dumps(payload))
    before = contents(c.e.store)
    with pytest.raises(ResidenceError, match="death event identity"):
        c.history.record_census(1)
    assert contents(c.e.store) == before


@pytest.mark.parametrize("damage", [{"alive": 0}, {"died_tick": 3}, {"arrived_tick": 2}])
def test_life_identity_disagreement_is_not_silently_treated_as_residence(residence_case, damage):
    c = residence_case
    c.e.store.update("agents", c.person, **damage)
    before = contents(c.e.store)
    with pytest.raises(ResidenceError, match="life identity"):
        c.history.is_living_resident(c.person, 0)
    with pytest.raises(ResidenceError, match="life identity"):
        c.history.audit_history()
    assert contents(c.e.store) == before


def test_recorded_census_refuses_backfilled_movement_and_requires_prior_day(residence_case):
    c = residence_case
    with pytest.raises(ResidenceError, match="preceding committed day"):
        c.history.record_census(2)
    c.history.record_census(1)
    before = contents(c.e.store)
    with pytest.raises(ResidenceError, match="rewrite a recorded census"):
        c.history.transition(1, c.person, "departure", previous_id=c.origins[c.person], request_key="late")
    assert contents(c.e.store) == before


@pytest.mark.parametrize("table,column", [("person_residence_events", "tick"), ("population_resident_census", "opening_residents")])
def test_residence_and_census_history_cannot_be_updated_or_deleted(residence_case, table, column):
    store = residence_case.e.store
    before = contents(store)
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        store.execute(f"UPDATE {table} SET {column}={column}")
    with pytest.raises(sqlite3.IntegrityError, match="permanent"):
        store.execute(f"DELETE FROM {table}")
    assert contents(store) == before


@pytest.mark.parametrize("kwargs", [
    {"tick": True}, {"agent_id": False}, {"previous_id": True},
    {"tick": 0}, {"tick": -1}, {"tick": 2**63}, {"request_key": ""},
    {"request_key": "x" * 97}, {"request_key": "bad\nkey"},
    {"request_key": "bad\x7fkey"}, {"request_key": "bad\x85key"}, {"cause": "death"},
])
def test_invalid_movement_inputs_do_not_touch_the_database(residence_case, kwargs):
    c = residence_case
    args = dict(tick=1, agent_id=c.person, cause="departure", previous_id=c.origins[c.person], request_key="out")
    args.update(kwargs)
    before = contents(c.e.store)
    with pytest.raises(ResidenceError):
        c.history.transition(**args)
    assert contents(c.e.store) == before


def test_historical_census_reopens_through_a_closed_read_only_source(residence_case):
    c = residence_case
    c.history.transition(1, c.person, "departure", previous_id=c.origins[c.person], request_key="out")
    expected = c.history.record_census(1)
    path = Path(c.e.store.path)
    c.e.store.close()
    before = (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
    reader = Store.from_read_only_connection(path, open_read_only_connection(path, require_closed=True))
    try:
        history = ResidenceHistory(reader)
        assert history.census_values(1) == expected
        assert history.state_at(c.person, 0)["state"] == "resident"
        assert history.audit_history() == {"people": 2, "residence_records": 3}
    finally:
        reader.close()
    assert (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns) == before
    assert not any(Path(str(path) + suffix).exists() for suffix in ("-wal", "-shm", "-journal"))
