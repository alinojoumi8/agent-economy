"""Draft outside biology against actual movement, lifecycle and estate services.

These controlled fixtures explicitly select draft services. Domain restart and
the daily age-clock case do not enable a Semantics-21 World or prove its replay.
"""
import hashlib
import json
from pathlib import Path
import random
import shutil

import pytest

from engine.core import Economy
from engine.lifecycle import OUTSIDE_LIFE_POLICY
from engine.population import PopulationBoundary
from engine.population_history import ResidenceError
from engine.store import Store

from .test_population_authority import finance, move
from .test_population_movements import moving, advance, propose
from .test_population_residence_history import residence_case, contents
from .test_population_commitments import local_services
from .test_semantics20_service_commitments import services, prepare_service
from .test_semantics20_estate_cases import estate_case
from .test_semantics19_estate_cash import spent_loan


@pytest.fixture
def outside_life(moving):
    moving.e.lifecycle.engine_semantics_version = 21
    return moving


def depart(c):
    movement = propose(c)
    advance(c, 1)
    assert c.e.population.settle(1, movement)["status"] == "applied"
    c.e.households.record_census(1)
    return movement


def controlled_draw(monkeypatch, c, **values):
    """Declared mechanism fixtures; never evidence of native demographic rates."""
    called = []

    def draw(tick, person, mechanism):
        called.append((tick, person, mechanism))
        return values.get(mechanism, 1.0) if person == c.person else 1.0

    monkeypatch.setattr(c.e.lifecycle, "_draw", draw)
    return called


@pytest.mark.parametrize("initial,mechanism,roll,expected,event", [
    ("healthy", "illness_onset", 0.0, "sick", "illness_onset"),
    ("sick", "sick_transition", 0.0, "critical", "illness_critical"),
    ("sick", "sick_transition", 0.1, "healthy", "recovery"),
    ("critical", "critical_transition", 0.2, "healthy", "recovery"),
])
def test_outside_health_evolves_with_evidence_and_no_local_bill(outside_life, monkeypatch,
        initial, mechanism, roll, expected, event):
    c, e = outside_life, outside_life.e
    depart(c)
    e.store.update("agents", c.person, health=initial)
    controlled_draw(monkeypatch, c, **{mechanism: roll})
    before = finance(e)
    e.lifecycle.run_nightly(2)
    assert e.store.scalar("SELECT health FROM agents WHERE id=?", (c.person,)) == expected
    row = e.store.query_one("SELECT * FROM events WHERE kind=? AND subject_id=? ORDER BY id DESC LIMIT 1", (event, c.person))
    assert json.loads(row["payload_json"]) == {"agent_id": c.person, "residence": "outside",
                                               "outside_life_policy": OUTSIDE_LIFE_POLICY}
    assert finance(e) == before
    e.households.record_census(2)
    assert c.history.census_values(2)["known_living_outside"] == 1
    assert e.ledger.reconcile()[0]


def test_local_epidemic_changes_only_the_resident_threshold(outside_life, monkeypatch):
    c, e = outside_life, outside_life.e
    depart(c)
    e.store.record_metric(2, "epidemic_multiplier", 100.0)
    # The same draw is above the baseline onset hazard and below the local shock.
    monkeypatch.setattr(e.lifecycle, "_draw", lambda tick, person, mechanism: 0.001 if mechanism == "illness_onset" else 1.0)
    e.lifecycle.run_nightly(2)
    assert e.store.scalar("SELECT health FROM agents WHERE id=?", (c.person,)) == "healthy"
    assert e.store.scalar("SELECT health FROM agents WHERE id=?", (c.heir,)) == "sick"
    payload = e.store.scalar("SELECT payload_json FROM events WHERE kind='illness_onset' AND subject_id=?", (c.heir,))
    assert json.loads(payload) == {"agent_id": c.heir}


@pytest.mark.parametrize("multiplier", [1, 3])
def test_medical_service_checks_residence_and_return_uses_existing_health_and_cash(outside_life, multiplier):
    c, e = outside_life, outside_life.e
    depart(c)
    e.store.update("agents", c.person, health="sick")
    before = finance(e)
    e.lifecycle._charge_medical(2, c.person, multiplier=multiplier)
    assert finance(e) == before
    move(e, c.person, 2, cause="return", key="back")
    assert e.store.scalar("SELECT health FROM agents WHERE id=?", (c.person,)) == "sick"
    assert e.ledger.agent_checking_id(c.person) == c.wallet
    cash = e.ledger.balance(c.wallet)
    assert cash > 0
    e.lifecycle._charge_medical(3, c.person, multiplier=multiplier)
    assert e.ledger.balance(c.wallet) == 0
    assert e.store.scalar("SELECT COUNT(*) FROM transactions WHERE kind='medical_cost'") == 1
    assert e.ledger.reconcile()[0]


def test_outside_parent_has_no_hazard_birth_and_scheduled_birth_is_rejected(outside_life, monkeypatch):
    c, e = outside_life, outside_life.e
    depart(c)
    e.lifecycle.p["birth_annual_prob"] = 1.0
    e.households.p["scheduled_births"] = [{"tick": 3, "parent_agent_id": c.person}]
    called = controlled_draw(monkeypatch, c, birth=0.0)
    before = finance(e)
    for tick in (2, 3):
        e.lifecycle.run_nightly(tick)
        e.households.record_census(tick)
    assert not any(person == c.person and mechanism == "birth" for _, person, mechanism in called)
    assert e.store.scalar("SELECT COUNT(*) FROM agents") == 2
    assert e.store.scalar("SELECT COUNT(*) FROM events WHERE kind='scheduled_birth_rejected' AND subject_id=?", (c.person,)) == 1
    assert e.store.scalar("SELECT COUNT(*) FROM person_lifecycle WHERE origin='birth'") == 0
    assert finance(e) == before


@pytest.mark.parametrize("kind,active", [("insurance", "active"), ("compute", "active"), ("loan", "pending")])
def test_nightly_lifecycle_rejects_reactivated_local_commitment_before_any_effect(local_services, kind, active):
    s, e = local_services, local_services.e
    e.lifecycle.engine_semantics_version = 21
    table, source_id, _ = prepare_service(s, kind)
    move(e, s.client, 0)
    e.store.update(table, source_id, status=active)
    before = contents(e.store)
    with pytest.raises(ResidenceError, match="commitment"):
        e.lifecycle.run_nightly(2)
    assert contents(e.store) == before


@pytest.mark.parametrize("cause", ["natural", "illness"])
def test_outside_death_settles_retained_assets_and_cancels_return_without_replacement(outside_life, monkeypatch, cause):
    c, e = outside_life, outside_life.e
    e.firms.found_firm(0, c.person, "Retained firm", "manufacturing", opening_capital_cents=20, shares=100)
    loan = spent_loan(e, c.bank, c.person, c.wallet, 30)
    e.ledger.create_account("agent", c.person, "fx", currency_code="EUR", opening_cents=37)
    depart(c)
    returned = propose(c, tick=1, due=2, cause="return", destination=1, key="back")
    e.lifecycle.p["population_mode"] = "stable"
    if cause == "illness":
        e.store.update("agents", c.person, health="critical")
    controlled_draw(monkeypatch, c, **{"mortality" if cause == "natural" else "critical_transition": 0.0})
    e.lifecycle.run_nightly(2)
    e.population.run_nightly(2)
    assert e.store.scalar("SELECT status FROM population_movements WHERE id=?", (returned,)) == "cancelled"
    assert e.store.scalar("SELECT alive FROM agents WHERE id=?", (c.person,)) == 0
    assert e.store.scalar("SELECT status FROM loans WHERE id=?", (loan,)) == "paid"
    assert e.store.scalar("SELECT COUNT(*) FROM events WHERE kind='arrival_scheduled'") == 0
    death = json.loads(e.store.scalar("SELECT payload_json FROM events WHERE kind='death' AND subject_id=?", (c.person,)))
    assert (death["cause"], death["residence"], death["outside_life_policy"]) == (cause, "outside", OUTSIDE_LIFE_POLICY)
    assert e.ledger.balance(c.heir_wallet) == 50
    assert e.store.scalar("SELECT balance_cents FROM accounts WHERE owner_type='agent' AND owner_id=? AND currency_code='EUR'", (c.heir,)) == 37
    e.households.record_census(2)
    census = c.history.census_values(2)
    assert (census["resident_deaths"], census["closing_residents"], census["known_living_outside"], census["returns"]) == (0, 1, 0, 0)
    e.estate_cases.check_invariants()
    e.business_control.check_invariants()
    assert e.ledger.reconcile()[0]
    before = contents(e.store)
    e.lifecycle.settle_death(2, c.person, cause=cause)
    assert contents(e.store) == before


def test_resident_death_still_schedules_the_declared_stable_replacement(outside_life, monkeypatch):
    c, e = outside_life, outside_life.e
    e.lifecycle.p["population_mode"] = "stable"
    controlled_draw(monkeypatch, c, mortality=0.0)
    e.lifecycle.run_nightly(1)
    assert e.store.scalar("SELECT COUNT(*) FROM events WHERE kind='arrival_scheduled'") == 1
    death = json.loads(e.store.scalar("SELECT payload_json FROM events WHERE kind='death' AND subject_id=?", (c.person,)))
    assert "residence" not in death and "outside_life_policy" not in death
    e.households.record_census(1)
    assert c.history.census_values(1)["resident_deaths"] == 1


def test_return_then_death_on_the_same_day_uses_the_residence_at_death(outside_life, monkeypatch):
    c, e = outside_life, outside_life.e
    depart(c)
    returned = propose(c, tick=1, due=2, cause="return", destination=1, key="back")
    controlled_draw(monkeypatch, c)
    e.lifecycle.run_nightly(2)
    e.population.run_nightly(2)
    assert e.store.scalar("SELECT status FROM population_movements WHERE id=?", (returned,)) == "applied"
    e.lifecycle.settle_death(2, c.person)
    e.households.record_census(2)
    census = c.history.census_values(2)
    assert (census["returns"], census["resident_deaths"], census["closing_residents"]) == (1, 1, 1)
    death = json.loads(e.store.scalar("SELECT payload_json FROM events WHERE kind='death' AND subject_id=?", (c.person,)))
    assert "residence" not in death


def test_outside_estate_failure_rolls_back_and_retry_settles_once(outside_life, monkeypatch):
    c, e = outside_life, outside_life.e
    spent_loan(e, c.bank, c.person, c.wallet, 30)
    depart(c)
    before = contents(e.store)
    original = e.store.log_event

    def fail(tick, kind, payload, **kw):
        if kind == "death":
            raise RuntimeError("injected outside death event failure")
        return original(tick, kind, payload, **kw)

    monkeypatch.setattr(e.store, "log_event", fail)
    with pytest.raises(RuntimeError, match="outside death event"):
        e.lifecycle.settle_death(2, c.person)
    assert contents(e.store) == before
    monkeypatch.setattr(e.store, "log_event", original)
    e.lifecycle.settle_death(2, c.person)
    assert e.store.scalar("SELECT COUNT(*) FROM estate_cases WHERE deceased_agent_id=?", (c.person,)) == 1
    assert e.ledger.balance(c.heir_wallet) == 70
    assert e.ledger.reconcile()[0]


def test_departure_does_not_change_any_persons_keyed_biology_draw(outside_life):
    c, e = outside_life, outside_life.e
    keys = [(tick, person, mechanism) for tick in (2, 3, 365) for person in (c.person, c.heir)
            for mechanism in ("mortality", "illness_onset", "sick_transition", "critical_transition")]
    before = [e.lifecycle._draw(*key) for key in keys]
    depart(c)
    assert [e.lifecycle._draw(*key) for key in keys] == before


def test_outside_retirement_uses_the_original_birthdate_and_keeps_assets(outside_life, monkeypatch):
    c, e = outside_life, outside_life.e
    depart(c)
    birth_tick = e.store.scalar("SELECT birth_tick FROM person_lifecycle WHERE agent_id=?", (c.person,))
    target = birth_tick + 365 * e.lifecycle.p["retirement_age"]
    controlled_draw(monkeypatch, c)
    before = finance(e)
    # A selected-boundary retirement fixture; the age-clock test below runs daily.
    e.lifecycle.run_nightly(target)
    assert e.store.scalar("SELECT retired FROM agents WHERE id=?", (c.person,)) == 1
    assert e.store.scalar("SELECT life_stage FROM person_lifecycle WHERE agent_id=?", (c.person,)) == "retired"
    assert not e.population.is_available(c.person)
    assert finance(e) == before


@pytest.mark.parametrize("health", ["healthy", "critical"])
def test_seeded_outside_lifecycle_matches_after_store_reopen_without_changing_source(outside_life, tmp_path, health):
    c, e = outside_life, outside_life.e
    depart(c)
    e.store.update("agents", c.person, health=health)
    propose(c, tick=1, due=5, cause="return", destination=1, key="back")
    source = Path(e.store.conn.execute("PRAGMA database_list").fetchone()[2])
    e.store.close()
    stamp = (hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns)
    results = []
    for restart in (False, True):
        path = tmp_path / ("restarted.db" if restart else "continuous.db")
        shutil.copy2(source, path)
        store = None
        try:
            for tick in range(2, 10):
                if store is None:
                    store = Store(path)
                    config = json.loads(store.scalar("SELECT config_json FROM run_meta"))
                    current = Economy(store, config, random.Random(1), random.Random(2))
                    current.engine_semantics_version = current.lifecycle.engine_semantics_version = 21
                    current.population = PopulationBoundary(current)
                    current.labor.engine_semantics_version = 21
                    current.labor.population = current.population
                with store.savepoint("outside_day"):
                    current.lifecycle.run_nightly(tick)
                    current.population.run_nightly(tick)
                    current.households.record_census(tick)
                if restart and tick in (3, 6):
                    store.close()
                    store = None
            current.population.commitments.check_invariants()
            assert current.ledger.reconcile()[0]
            state = contents(store)
            # As in the recorded replay contract, event wall-clock write time
            # is not simulation state. Every other column and table must match.
            columns = [row[1] for row in store.conn.execute("PRAGMA table_info(events)") if row[1] != "created_at"]
            state["events"] = [tuple(row[name] for name in columns) for row in store.query("SELECT * FROM events ORDER BY id")]
            results.append(state)
        finally:
            if store is not None:
                store.close()
    assert results[0] == results[1]
    assert (hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns) == stamp


def test_daily_outside_age_clock_reaches_adulthood_and_return_without_endowment(outside_life, monkeypatch):
    c, e = outside_life, outside_life.e
    advance(c, 1)
    child = e.households.birth(1, c.person)
    wallet = e.ledger.agent_checking_id(child)
    e.households.record_census(1)
    movement = propose(c, [c.person, child], tick=1, due=2, care=[{"child_id": child, "guardian_id": c.person}])
    advance(c, 2)
    e.population.settle(2, movement)
    # Isolate the continuous age/care contract; stochastic biology is tested above.
    monkeypatch.setattr(e.lifecycle, "_draw", lambda *args: 1.0)
    before = finance(e)
    adulthood = 1 + 18 * 365
    for tick in range(2, adulthood + 1):
        with e.store.savepoint("outside_day"):
            e.lifecycle.run_nightly(tick)
            e.daily_time.prepare_day(tick)
            e.households.provision_children(tick)
            e.households.record_census(tick)
    assert e.store.scalar("SELECT age FROM agents WHERE id=?", (child,)) == 18
    assert e.households.membership(child)["role"] == "adult"
    assert e.households.guardian_id(child) is None
    assert e.store.scalar("SELECT COUNT(*) FROM events WHERE kind='adulthood' AND subject_id=?", (child,)) == 1
    assert not e.store.query("SELECT 1 FROM time_days WHERE agent_id IN (?,?)", (c.person, child))
    assert not e.store.query("SELECT 1 FROM child_care_days WHERE child_id=?", (child,))
    assert not e.store.query("SELECT 1 FROM child_needs WHERE child_agent_id=?", (child,))
    assert e.store.scalar("SELECT COUNT(*) FROM llm_calls") == 0
    assert finance(e) == before
    returned = propose(c, [c.person, child], tick=adulthood, due=adulthood+1, cause="return", destination=1, key="adult-back")
    e.population.respond(adulthood, child, returned, "accept")
    e.lifecycle.run_nightly(adulthood+1)
    e.population.run_nightly(adulthood+1)
    e.daily_time.prepare_day(adulthood+1)
    e.households.record_census(adulthood+1)
    assert e.ledger.agent_checking_id(child) == wallet and e.ledger.balance(wallet) == 0
    assert e.population.is_available(child)
    assert e.store.scalar("SELECT COUNT(*) FROM time_days WHERE agent_id=? AND tick=?", (child, adulthood+1)) == 1
    assert c.history.census_values(adulthood+1)["returns"] == 2
    assert finance(e) == before
    e.households.check_invariants(adulthood+1)
    assert e.ledger.reconcile()[0]
