"""Draft movement service against real household, labor and time mechanics.

Only the disposable fixture enables the draft services. Public Semantics 21,
complete city/authority handling, outside life and source replay remain gated.
"""
import json
import random
import sqlite3

import pytest

from agents.scheduler import Scheduler
from engine.actions import ActionExecutor
from engine.core import Economy
from engine.population import MovementError, PopulationBoundary
from engine.population_history import ResidenceError
from engine.daily_time import TimeBudgetError
from engine.store import Store

from .conftest import make_agent
from .test_population_residence_history import residence_case, contents
from .test_semantics20_estate_cases import estate_case
from .test_semantics18_daily_time import employer
from .test_semantics19_estate_cash import spent_loan


@pytest.fixture
def moving(residence_case):
    c = residence_case
    # Exercise real draft services without weakening public version validation.
    c.e.engine_semantics_version = c.e.labor.engine_semantics_version = 21
    c.e.population = PopulationBoundary(c.e)
    c.e.labor.population = c.e.population
    return c


def advance(c, tick):
    for person in c.e.store.query("SELECT * FROM agents WHERE alive=1 ORDER BY id"):
        c.e.households.advance_age(tick, person)


def join(c):
    destination = c.e.households.membership(c.person)["household_id"]
    c.e.families._move_members(0, [{"agent_id": c.heir}], destination, "fixture_join")


def child_household(c):
    join(c)
    advance(c, 1)
    child = c.e.households.birth(1, c.person)
    c.e.households.record_census(1)
    return child


def propose(c, members=None, *, tick=0, due=1, key="trip", cause="departure", care=(), destination=None):
    return c.e.population.propose(tick, c.person, cause, members or [c.person], key, due_tick=due,
        care_plan=care, destination_region_id=destination)["movement_id"]


def rows(c, table):
    return [tuple(row) for row in c.e.store.query(f'SELECT * FROM "{table}" ORDER BY rowid')]


def test_departure_return_preserve_people_financial_claims_and_no_second_endowment(moving):
    c = moving
    c.e.firms.found_firm(0, c.person, "Retained ownership", "manufacturing", shares=100)
    spent_loan(c.e, c.bank, c.person, c.wallet, 30)
    fx = c.e.ledger.create_account("agent", c.person, "fx", currency_code="EUR", opening_cents=37)
    financial = {table: rows(c, table) for table in (
        "accounts", "ledger_entries", "transactions", "loans", "shares", "estate_cases")}
    identity = rows(c, "person_lifecycle")
    movement = propose(c)
    advance(c, 1)
    result = c.e.population.settle(1, movement)
    assert result["status"] == "applied"
    assert c.e.store.scalar("SELECT alive FROM agents WHERE id=?", (c.person,)) == 1
    c.e.households.record_census(1)
    assert c.history.census_values(1)["departures"] == 1
    assert c.history.census_values(1)["closing_residents"] == 1
    returned = propose(c, tick=1, due=2, key="back", cause="return", destination=1)
    advance(c, 2)
    assert c.e.population.settle(2, returned)["status"] == "applied"
    c.e.households.record_census(2)
    assert c.history.census_values(2)["returns"] == 1
    assert c.history.census_values(2)["arrivals"] == 0
    assert financial == {table: rows(c, table) for table in financial}
    assert identity == rows(c, "person_lifecycle")
    assert c.e.ledger.balance(fx) == 37
    assert c.e.ledger.reconcile()[0]
    before = contents(c.e.store)
    assert c.e.population.settle(1, movement) == result
    assert propose(c) == movement
    assert contents(c.e.store) == before


@pytest.mark.parametrize("existing", [False, True])
def test_return_uses_existing_currency_wallet_and_can_create_empty_local_wallet(moving, existing):
    c = moving
    fx = c.e.ledger.create_account("agent", c.person, "fx", currency_code="EUR", opening_cents=37) if existing else None
    c.e.store.insert("regions", id=2, region_key="euro", name="Euro", currency_code="EUR",
        population_target=5, specialization_json="{}", x=1, y=1, legal_ruleset="test")
    movement = propose(c)
    advance(c, 1)
    c.e.population.settle(1, movement)
    before = {table: rows(c, table) for table in ("transactions", "ledger_entries", "loans")}
    original_account = dict(c.e.store.query_one("SELECT * FROM accounts WHERE id=?", (c.wallet,)))
    returned = propose(c, tick=1, due=2, key="euro-back", cause="return", destination=2)
    advance(c, 2)
    c.e.population.settle(2, returned)
    account_id = c.e.store.scalar("SELECT checking_account_id FROM agents WHERE id=?", (c.person,))
    account = c.e.store.query_one("SELECT * FROM accounts WHERE id=?", (account_id,))
    assert account["currency_code"] == "EUR" and c.e.ledger.balance(account_id) == (37 if existing else 0)
    if existing:
        assert account_id == fx
    assert dict(c.e.store.query_one("SELECT * FROM accounts WHERE id=?", (c.wallet,))) == original_account
    assert before == {table: rows(c, table) for table in before}


def test_partial_household_requires_remaining_adult_assent_and_explicit_care(moving):
    c = moving
    child = child_household(c)
    care = [{"child_id": child, "guardian_id": c.heir}]
    movement = propose(c, tick=1, due=2, care=care)
    assert c.e.households.guardian_id(child) == c.person
    c.e.population.respond(1, c.heir, movement, "accept")
    advance(c, 2)
    result = c.e.population.settle(2, movement)
    assert result["status"] == "applied"
    assert c.e.households.guardian_id(child) == c.heir
    assert c.e.households.membership(child)["household_id"] == c.e.households.membership(c.heir)["household_id"]
    assert result["destination_household_id"] != c.e.households.membership(child)["household_id"]
    assert c.history.is_living_resident(child, 2) and not c.history.is_living_resident(c.person, 2)
    assert c.e.store.scalar("SELECT reason FROM guardianships WHERE child_agent_id=? AND ended_tick IS NULL", (child,)) == "population_adult_assent_v1"
    c.e.households.check_invariants(2)


def test_moving_minor_keeps_named_guardian_but_delivers_no_local_care(moving):
    c = moving
    child = child_household(c)
    care = [{"child_id": child, "guardian_id": c.person}]
    movement = propose(c, [c.person, child], tick=1, due=2, care=care)
    c.e.population.respond(1, c.heir, movement, "accept")
    advance(c, 2)
    c.e.population.settle(2, movement)
    c.e.daily_time.prepare_day(2)
    c.e.households.provision_children(2)
    assert c.e.households.guardian_id(child) == c.person
    assert not c.e.store.query("SELECT * FROM time_days WHERE agent_id IN (?,?) AND tick=2", (c.person, child))
    assert not c.e.store.query("SELECT * FROM child_care_days WHERE child_id=? AND tick=2", (child,))
    assert not c.e.store.query("SELECT * FROM child_needs WHERE child_agent_id=? AND tick=2", (child,))
    with pytest.raises(ValueError, match="outside births"):
        c.e.households.birth(3, c.person)


def test_missing_assent_cancels_group_without_any_movement(moving):
    c = moving
    join(c)
    movement = propose(c, [c.person, c.heir])
    advance(c, 1)
    homes, residence = rows(c, "household_memberships"), rows(c, "person_residence_events")
    result = c.e.population.settle(1, movement)
    assert result["reason"] == "missing_adult_assent"
    assert rows(c, "household_memberships") == homes
    assert rows(c, "person_residence_events") == residence
    with pytest.raises(MovementError, match="closed"):
        c.e.population.respond(1, c.heir, movement, "accept")


@pytest.mark.parametrize("decision", ["decline", "withdraw"])
def test_adult_can_decline_or_withdraw_and_old_accept_cannot_reopen(moving, decision):
    c = moving
    join(c)
    movement = propose(c, [c.person, c.heir])
    if decision == "withdraw":
        c.e.population.respond(0, c.heir, movement, "accept")
    result = c.e.population.respond(0, c.heir, movement, decision)
    assert result["status"] == "cancelled"
    assert c.e.population.respond(0, c.heir, movement, decision) == result
    if decision == "withdraw":
        assert c.e.population.respond(0, c.heir, movement, "accept") == result
    advance(c, 1)
    assert c.e.population.settle(1, movement) == result
    assert c.history.is_living_resident(c.person, 1)


@pytest.mark.parametrize("change", ["birth", "death", "membership", "custody"])
def test_due_group_cancels_changed_demographic_snapshot(moving, change):
    c = moving
    child = child_household(c)
    care = [{"child_id": child, "guardian_id": c.person}]
    movement = propose(c, [c.person, child], tick=1, due=2, care=care)
    c.e.population.respond(1, c.heir, movement, "accept")
    advance(c, 2)
    if change == "birth":
        c.e.households.birth(2, c.person)
    elif change == "death":
        c.e.lifecycle.settle_death(2, c.person)
    elif change == "membership":
        c.e.households.split_household(2, c.heir)
    elif change == "custody":
        c.e.store.execute("UPDATE guardianships SET ended_tick=2,end_reason='fixture' WHERE child_agent_id=?", (child,))
        c.e.store.insert("guardianships", child_agent_id=child, guardian_agent_id=c.heir, started_tick=2, reason="fixture")
    before = rows(c, "person_residence_events")
    assert c.e.population.settle(2, movement)["reason"] == "household_snapshot_changed"
    assert rows(c, "person_residence_events") == before


def test_real_birthday_requires_fresh_assent_instead_of_reusing_child_disposition(moving):
    c = moving
    advance(c, 1)
    teenager, _ = make_agent(c.e, c.bank, "Almost adult", age=17, cash=0, region_id=1, arrived_tick=1)
    c.e.households.register_person(1, teenager, "arrival")
    destination = c.e.households.membership(c.person)["household_id"]
    c.e.families._move_members(1, [{"agent_id": teenager}], destination, "fixture_join")
    c.e.households.reconcile_custody(1)
    birth_tick = c.e.store.scalar("SELECT birth_tick FROM person_lifecycle WHERE agent_id=?", (teenager,))
    birthday = birth_tick + 18 * 365
    movement = propose(c, [c.person, teenager], tick=1, due=birthday,
                       care=[{"child_id": teenager, "guardian_id": c.person}])
    advance(c, birthday)
    assert c.e.store.scalar("SELECT age FROM agents WHERE id=?", (teenager,)) == 18
    assert c.e.population.settle(birthday, movement)["reason"] == "household_snapshot_changed"


@pytest.mark.parametrize("care_kind", ["missing", "split", "minor_guardian", "unrelated", "duplicate"])
def test_invalid_child_dispositions_are_rejected_without_events(moving, care_kind):
    c = moving
    child = child_household(c)
    care = {"missing": [], "split": [{"child_id": child, "guardian_id": c.person}],
        "minor_guardian": [{"child_id": child, "guardian_id": child}],
        "unrelated": [{"child_id": child, "guardian_id": 99999}],
        "duplicate": [{"child_id": child, "guardian_id": c.heir}] * 2}[care_kind]
    before = contents(c.e.store)
    with pytest.raises(ResidenceError):
        propose(c, tick=1, due=2, care=care)
    assert contents(c.e.store) == before


@pytest.mark.parametrize("failure", ["second_residence", "household", "employment", "outcome"])
def test_storage_failure_rolls_back_every_person_and_local_effect(moving, failure):
    c = moving
    join(c)
    employer(c.e, c.bank, c.person)
    movement = propose(c, [c.person, c.heir])
    advance(c, 1)
    triggers = {
        "second_residence": f"BEFORE INSERT ON person_residence_events WHEN NEW.agent_id={c.heir}",
        "household": "BEFORE INSERT ON household_memberships",
        "employment": "BEFORE UPDATE ON employments",
        "outcome": "BEFORE UPDATE ON population_movements",
    }
    c.e.population.respond(1, c.heir, movement, "accept")
    c.e.store.execute(f"CREATE TRIGGER injected_move {triggers[failure]} BEGIN SELECT RAISE(ABORT,'injected movement failure'); END")
    before = contents(c.e.store)
    with pytest.raises((sqlite3.IntegrityError, ResidenceError), match="injected movement failure"):
        c.e.population.settle(1, movement)
    assert contents(c.e.store) == before
    c.e.store.execute("DROP TRIGGER injected_move")
    assert c.e.population.settle(1, movement)["status"] == "applied"


def test_work_ends_but_accrued_wages_remain_and_absent_actor_is_not_scheduled(moving):
    c = moving
    firm, _, employment = employer(c.e, c.bank, c.person)
    advance(c, 1)
    c.e.daily_time.prepare_day(1)
    wage_claims = rows(c, "wage_claims")
    assert wage_claims
    movement = propose(c, tick=1, due=2)
    advance(c, 2)
    c.e.population.settle(2, movement)
    assert rows(c, "wage_claims") == wage_claims
    assert c.e.store.scalar("SELECT status FROM employments WHERE id=?", (employment,)) == "ended"
    scheduler = Scheduler(c.e.store, {**c.e.config, "engine_semantics_version": 21})
    assert c.person not in [row["id"] for row in scheduler.scheduled_agents(3)]
    executor = ActionExecutor(c.e)
    executor.engine_semantics_version = 21  # Draft domain branch; public admission remains capped at 20.
    assert not executor.execute_action(2, c.person, {"type": "do_nothing"})["ok"]
    job = c.e.labor.post_job(2, firm, "New job", 50)
    assert c.e.labor.apply_job(2, c.person, job) is None
    with pytest.raises(TimeBudgetError, match="outside"):
        c.e.daily_time.submit_plan(2, c.person, {"request_key": "new", "work_minutes": 1, "care_minutes": 0})
    c.e.daily_time.prepare_day(2)
    assert not c.e.store.query("SELECT * FROM time_allocations WHERE tick=2 AND agent_id=?", (c.person,))
    before_cash = c.e.ledger.balance(c.wallet)
    c.e.earned_wages.process_due(2)
    paid = c.e.store.query_one("SELECT * FROM wage_claims WHERE employee_id=?", (c.person,))
    assert paid["paid_cents"] == paid["accrued_cents"] > 0 and paid["closed_tick"] == 2
    assert c.e.ledger.balance(c.wallet) > before_cash
    assert not c.history.is_living_resident(c.person, 2)
    assert c.e.ledger.reconcile()[0]


def test_independent_job_offers_end_when_the_candidate_departs(moving):
    c = moving
    firm, _, _ = employer(c.e, c.bank, founder=c.heir)
    job = c.e.labor.post_job(0, firm, "Open job", 50)
    application = c.e.labor.apply_job(0, c.person, job)
    offer = c.e.labor.make_offer(0, application, c.heir, 60)
    movement = propose(c)
    advance(c, 1)
    c.e.population.settle(1, movement)
    assert c.e.store.scalar("SELECT status FROM job_offers WHERE id=?", (offer,)) == "rejected"
    assert c.e.store.scalar("SELECT state FROM applications WHERE id=?", (application,)) == "rejected"
    assert c.e.labor.accept_offer(1, offer, c.person) is None


def test_failed_resident_census_rolls_back_all_living_census(moving):
    c = moving
    advance(c, 1)
    c.e.store.execute("CREATE TRIGGER injected_census BEFORE INSERT ON population_resident_census BEGIN SELECT RAISE(ABORT,'injected census'); END")
    before = contents(c.e.store)
    with pytest.raises(sqlite3.IntegrityError, match="injected census"):
        c.e.households.record_census(1)
    assert contents(c.e.store) == before


def test_bad_keys_overlapping_requests_and_late_settlement(moving):
    c = moving
    before = contents(c.e.store)
    with pytest.raises(ResidenceError):
        propose(c, [True])
    assert contents(c.e.store) == before
    movement = propose(c)
    with pytest.raises(MovementError, match="different movement terms"):
        propose(c, due=2)
    with pytest.raises(MovementError, match="already has"):
        propose(c, key="second")
    with pytest.raises(ResidenceError, match="integer"):
        c.e.population.settle(True, movement)
    advance(c, 2)
    assert c.e.population.settle(2, movement)["reason"] == "missed_due_tick"


def test_sql_guards_and_event_reader_detect_changed_agreements(moving):
    c = moving
    movement = propose(c)
    for statement in (
        "UPDATE population_movements SET due_tick=3",
        "DELETE FROM population_movements",
        "UPDATE population_movement_assents SET actor_id=999",
        "DELETE FROM population_movement_assents",
    ):
        with pytest.raises(sqlite3.IntegrityError):
            c.e.store.execute(statement)
    event = c.e.store.scalar("SELECT proposal_event_id FROM population_movements WHERE id=?", (movement,))
    c.e.store.update("events", event, payload_json='{}')
    advance(c, 1)
    with pytest.raises(ResidenceError, match="event disagrees"):
        c.e.population.settle(1, movement)
    assert c.history.is_living_resident(c.person, 1)


def test_terminal_retry_rechecks_the_actual_settled_residence_evidence(moving):
    c = moving
    movement = propose(c)
    advance(c, 1)
    c.e.population.settle(1, movement)
    event = c.e.store.query_one("SELECT * FROM events WHERE kind='population_movement_closed'")
    payload = json.loads(event["payload_json"])
    payload["residence_ids"] = []
    c.e.store.update("events", event["id"], payload_json=json.dumps(payload))
    with pytest.raises(ResidenceError, match="event disagrees"):
        c.e.population.settle(1, movement)


def test_resident_action_can_pay_an_outside_owner_without_giving_them_a_local_turn(moving):
    c = moving
    c.e.ledger.transfer(0, c.wallet, c.heir_wallet, 20)
    movement = propose(c)
    advance(c, 1)
    c.e.population.settle(1, movement)
    before = c.e.ledger.balance(c.wallet)
    executor = ActionExecutor(c.e)
    executor.engine_semantics_version = 21
    result = executor.execute_action(1, c.heir, {"type": "transfer", "to_account": c.wallet, "amount": 11})
    assert result["ok"] and c.e.ledger.balance(c.wallet) == before + 11
    assert c.e.ledger.balance(c.heir_wallet) == 9
    assert not c.history.is_living_resident(c.person, 1)
    assert c.e.ledger.reconcile()[0]


def test_pending_group_survives_store_reopen_and_due_processing_is_idempotent(moving):
    c = moving
    join(c)
    movement = propose(c, [c.person, c.heir])
    c.e.population.respond(0, c.heir, movement, "accept")
    path = c.e.store.conn.execute("PRAGMA database_list").fetchone()[2]
    c.e.store.close()
    reopened = Store(path)
    try:
        e = Economy(reopened, c.e.config, random.Random(1), random.Random(2))
        e.engine_semantics_version = e.labor.engine_semantics_version = 21
        e.population = PopulationBoundary(e)
        e.labor.population = e.population
        for person in reopened.query("SELECT * FROM agents WHERE alive=1 ORDER BY id"):
            e.households.advance_age(1, person)
        e.population.run_nightly(1)
        assert reopened.scalar("SELECT status FROM population_movements WHERE id=?", (movement,)) == "applied"
        assert not e.population.is_local(c.person, 1) and not e.population.is_local(c.heir, 1)
        e.households.record_census(1)
        before = contents(reopened)
        e.population.run_nightly(1)
        assert contents(reopened) == before
    finally:
        reopened.close()
