"""Real permit work survives staff death; personal applications and permits do not."""
import asyncio
import copy
import hashlib
import json

import pytest

from engine.estates import EstateError
from engine.lifecycle import Lifecycle
from research.hashing import canonical_hashes
from world.replay_verify import verify_replay

from .test_semantics12_civic_city import _application, _lawyer_id, _same_region_applicants
from .test_semantics13_construction import _config
from .test_semantics17_household_decisions import _world
from .test_semantics20_personal_authority import item_for, validate


def civic_config():
    config = _config(semantics=20, enabled=False)
    config["entrepreneurship"]["enabled"] = False
    config.setdefault("lifecycle", {}).update(population_mode="drift", birth_annual_prob=0)
    config.setdefault("households", {})["scheduled_births"] = []
    config.setdefault("family_decisions", {})["scripted_matching"] = False
    config["city"]["business_permits"]["discretionary_competitor_floor"] = 0
    return config


@pytest.fixture
def city_world(tmp_path):
    world = _world(tmp_path / "city-estates.db", civic_config())
    available_adult(world)
    try:
        yield world
    finally:
        world.close()


def available_adult(world):
    # Declared genesis unemployment among existing adults. Preserve the recorded
    # population/census and every account; this is not a modeled resignation.
    first, second = _same_region_applicants(world.store, 2)
    person = world.store.scalar(
        "SELECT a.id FROM agents a WHERE a.alive=1 AND a.kind='citizen' "
        "AND a.age BETWEEN 18 AND 60 AND a.retired=0 AND a.role IS NULL "
        "AND a.region_id=? AND a.id NOT IN (?,?) AND NOT EXISTS "
        "(SELECT 1 FROM firm_operations f WHERE f.operator_agent_id=a.id "
        "AND f.status IN ('private','listed')) ORDER BY a.id LIMIT 1",
        (first["region_id"], first["id"], second["id"]))
    assert person is not None
    world.store.execute("UPDATE employments SET status='ended',end_tick=0 WHERE agent_id=? AND status='active'", (person,))
    world.store.update("agents", person, employer_id=None)
    return person


def apply(world, *, tick=1, applicant=None, name="Continuing Permit"):
    if applicant is None:
        applicant = _same_region_applicants(world.store, 1)[0]["id"]
    result = world.economy.city.apply_business_permit(
        tick, applicant, _application(_lawyer_id(world.store), name))
    assert result["ok"], result
    return applicant, result["case_id"]


def under_review(world):
    person, case = apply(world)
    city = world.economy.city
    city.finalize(1)
    appointment = world.store.query_one("SELECT * FROM service_appointments WHERE case_id=?", (case,))
    tick = appointment["scheduled_tick"]
    city.run_nightly(tick)
    world.economy.daily_time.prepare_day(tick)
    result = city.attend_appointment(tick, person, appointment["id"])
    assert result["ok"], result
    city.finalize(tick)
    task = world.store.query_one("SELECT * FROM institution_tasks WHERE source_case_id=?", (case,))
    assert task is not None and task["status"] == "assigned"
    return person, case, dict(task), tick


def decide(world, tick, clerk, case):
    return world.economy.city.decide_business_permit(tick, clerk, case, "approve", "market_capacity_supported")


def test_staff_death_releases_real_work_and_existing_successor_completes_the_same_case(city_world):
    world = city_world
    e, store = world.economy, world.store
    person, case, task, tick = under_review(world)
    clerk = task["assigned_agent_id"]
    staff = dict(store.query_one("SELECT * FROM agency_staff WHERE agent_id=? AND active=1", (clerk,)))
    original_case = dict(store.query_one("SELECT * FROM service_cases WHERE id=?", (case,)))
    e.lifecycle.settle_death(tick + 1, clerk)
    assert dict(store.query_one("SELECT * FROM service_cases WHERE id=?", (case,))) == original_case
    assert json.loads(item_for(e, clerk, "agency_staff")["snapshot_json"]) == staff
    assert json.loads(item_for(e, clerk, "institutional_assignment")["snapshot_json"]) == task
    assert tuple(store.query_one("SELECT status,assigned_agent_id,assigned_tick FROM institution_tasks WHERE id=?", (task["id"],))) == ("pending", None, None)
    assert not decide(world, tick + 1, clerk, case)["ok"]
    assert not decide(world, tick + 1, person, case)["ok"]
    population = store.scalar("SELECT COUNT(*) FROM agents")
    transactions = store.scalar("SELECT COUNT(*) FROM transactions")
    e.city.run_nightly(tick + 1)
    successor = store.scalar("SELECT assigned_agent_id FROM institution_tasks WHERE id=?", (task["id"],))
    assert successor is not None and successor != clerk
    assert store.scalar("SELECT COUNT(*) FROM agents") == population
    assert store.scalar("SELECT COUNT(*) FROM transactions") == transactions
    assert decide(world, tick + 1, successor, case)["ok"]
    assert store.scalar("SELECT status FROM institution_tasks WHERE id=?", (task["id"],)) == "completed"
    assert store.scalar("SELECT holder_agent_id FROM civic_authorizations WHERE case_id=?", (case,)) == person
    assert e.city.agency_detail(staff["agency_id"], tick)["active_staff"] == 1
    assert e.city.agency_detail(staff["agency_id"], tick + 1)["active_staff"] == 1
    validate(e)


@pytest.mark.parametrize("stage", ["scheduled", "review"])
def test_applicant_death_closes_personal_work_atomically_and_keeps_fees_and_history(city_world, stage):
    world = city_world
    e, store = world.economy, world.store
    if stage == "review":
        person, case, task, tick = under_review(world)
    else:
        person, case = apply(world)
        e.city.finalize(1)
        tick = 1
    original = dict(store.query_one("SELECT * FROM service_cases WHERE id=?", (case,)))
    fees = [tuple(r) for r in store.query("SELECT * FROM ledger_entries WHERE txn_id=? ORDER BY id", (original["fee_transaction_id"],))]
    e.lifecycle.settle_death(tick + 1, person)
    assert json.loads(item_for(e, person, "civic_application")["snapshot_json"]) == original
    assert tuple(store.query_one("SELECT status,reason_code FROM service_cases WHERE id=?", (case,))) == ("abandoned", "applicant_deceased")
    assert not store.scalar("SELECT COUNT(*) FROM service_appointments WHERE case_id=? AND status='scheduled'", (case,))
    assert not store.scalar("SELECT COUNT(*) FROM institution_tasks WHERE source_case_id=? AND status IN ('pending','assigned')", (case,))
    if stage == "scheduled":
        appointment = item_for(e, person, "civic_appointment")
        lease = json.loads(appointment["snapshot_json"])["lease_id"]
        assert tuple(store.query_one("SELECT status,ended_tick FROM occupancy_leases WHERE id=?", (lease,))) == ("cancelled", tick + 1)
    else:
        assert not decide(world, tick + 1, task["assigned_agent_id"], case)["ok"]
    assert [tuple(r) for r in store.query("SELECT * FROM ledger_entries WHERE txn_id=? ORDER BY id", (original["fee_transaction_id"],))] == fees
    store.set_meta(tick=tick + 1)
    before = canonical_hashes(store)["authoritative_sha256"]
    assert e.city.public_summary(tick)["queue"]["depth"] == 1
    assert e.city.public_summary(tick + 1)["queue"]["depth"] == 0
    assert "application_payload" not in json.dumps(e.city.public_summary(tick))
    assert canonical_hashes(store)["authoritative_sha256"] == before
    validate(e)


def test_unused_permit_is_revoked_without_transferring_the_holders_identity(city_world):
    world = city_world
    e, store = world.economy, world.store
    person, case, task, tick = under_review(world)
    result = decide(world, tick + 1, task["assigned_agent_id"], case)
    assert result["ok"], result
    permit = dict(store.query_one("SELECT * FROM civic_authorizations WHERE case_id=?", (case,)))
    e.lifecycle.settle_death(tick + 2, person)
    assert json.loads(item_for(e, person, "civic_authorization")["snapshot_json"]) == permit
    assert store.scalar("SELECT status FROM civic_authorizations WHERE id=?", (permit["id"],)) == "revoked"
    assert store.scalar("SELECT holder_agent_id FROM civic_authorizations WHERE id=?", (permit["id"],)) == person
    assert e.city.active_authorization(person, tick + 2) is None
    assert store.scalar("SELECT status FROM service_cases WHERE id=?", (case,)) == "approved"
    validate(e)


def test_no_candidate_leaves_a_real_vacancy_and_pending_work_without_new_people_or_money(city_world):
    world = city_world
    e, store = world.economy, world.store
    _, case, task, tick = under_review(world)
    clerk = task["assigned_agent_id"]
    staff = dict(store.query_one("SELECT * FROM agency_staff WHERE agent_id=? AND active=1", (clerk,)))
    # Declared candidate constraint: all otherwise unemployed local adults have
    # retired. Actual worker death and subsequent staffing still use the engine.
    candidates = store.query("SELECT id FROM agents WHERE alive=1 AND kind='citizen' AND role IS NULL AND employer_id IS NULL AND region_id=?", (staff["region_id"],))
    assert candidates
    for candidate in candidates:
        store.update("agents", candidate["id"], retired=1)
    e.lifecycle.settle_death(tick + 1, clerk)
    before = (store.scalar("SELECT COUNT(*) FROM agents"), store.scalar("SELECT COUNT(*) FROM transactions"))
    for day in (tick + 1, tick + 2):
        e.city.run_nightly(day)
        assert e.city.agency_detail(staff["agency_id"], day)["active_staff"] == 0
        assert store.scalar("SELECT status FROM institution_tasks WHERE id=?", (task["id"],)) == "pending"
        assert (store.scalar("SELECT COUNT(*) FROM agents"), store.scalar("SELECT COUNT(*) FROM transactions")) == before
    # A recorded existing adult becomes available. No automatic heir or new
    # population is created; the usual stable candidate ordering applies.
    candidate = next(r["id"] for r in candidates if not e.business_control.operated_firms(r["id"]))
    store.update("agents", candidate, retired=0)
    e.city.run_nightly(tick + 3)
    assert store.scalar("SELECT assigned_agent_id FROM institution_tasks WHERE id=?", (task["id"],)) == candidate
    assert decide(world, tick + 3, candidate, case)["ok"]
    e.estate_cases.check_invariants()
    assert e.ledger.reconcile()[0]


@pytest.mark.parametrize("binding", ["applicant", "staff"])
def test_city_failure_rolls_back_death_inventory_fees_and_every_assignment(city_world, monkeypatch, binding):
    world = city_world
    e = world.economy
    person, _, task, tick = under_review(world)
    method = "_abandon_case_after_death" if binding == "applicant" else "_end_staff_assignment"
    deceased = person if binding == "applicant" else task["assigned_agent_id"]
    original = getattr(e.city, method)

    def fail_after_closure(day, case):
        original(day, case)
        raise RuntimeError("injected city closure failure")

    monkeypatch.setattr(e.city, method, fail_after_closure)
    before = canonical_hashes(world.store)["authoritative_sha256"]
    with pytest.raises(RuntimeError, match="injected city"):
        e.lifecycle.settle_death(tick + 1, deceased)
    assert canonical_hashes(world.store)["authoritative_sha256"] == before
    assert e.estate_cases._pending is None
    monkeypatch.setattr(e.city, method, original)
    e.lifecycle.settle_death(tick + 1, deceased)
    validate(e)


@pytest.mark.parametrize("staff_first", [True, False])
def test_same_day_staff_and_applicant_deaths_never_requeue_a_cancelled_case(city_world, staff_first):
    world = city_world
    e, store = world.economy, world.store
    person, case, task, tick = under_review(world)
    people = [task["assigned_agent_id"], person] if staff_first else [person, task["assigned_agent_id"]]
    for deceased in people:
        e.lifecycle.settle_death(tick + 1, deceased)
    e.city.run_nightly(tick + 1)
    e.city.finalize(tick + 1)
    assert tuple(store.query_one("SELECT status,completed_tick FROM institution_tasks WHERE id=?", (task["id"],))) == ("cancelled", tick + 1)
    assert store.scalar("SELECT status FROM service_cases WHERE id=?", (case,)) == "abandoned"
    assert store.scalar("SELECT COUNT(*) FROM civic_authorizations WHERE case_id=?", (case,)) == 0
    validate(e)


def test_used_permit_and_incorporated_company_survive_founder_death(city_world):
    world = city_world
    e, store = world.economy, world.store
    person, case, task, tick = under_review(world)
    assert decide(world, tick + 1, task["assigned_agent_id"], case)["ok"]
    action = e.city.founding_opportunity(person, tick + 2)["action"]
    founded = world.runtime.executor.execute_action(tick + 2, person, action)
    assert founded["ok"], founded
    permit = dict(store.query_one("SELECT * FROM civic_authorizations WHERE case_id=?", (case,)))
    assert (permit["status"], permit["consumed_by_firm_id"]) == ("consumed", founded["firm_id"])
    firm = dict(store.query_one("SELECT * FROM firms WHERE id=?", (founded["firm_id"],)))
    accounts = [tuple(row) for row in store.query("SELECT id,balance_cents FROM accounts WHERE owner_type='firm' AND owner_id=? ORDER BY id", (founded["firm_id"],))]
    e.lifecycle.settle_death(tick + 3, person)
    assert dict(store.query_one("SELECT * FROM civic_authorizations WHERE case_id=?", (case,))) == permit
    assert item_for(e, person, "civic_authorization") is None
    assert dict(store.query_one("SELECT * FROM firms WHERE id=?", (founded["firm_id"],))) == firm
    assert [tuple(row) for row in store.query("SELECT id,balance_cents FROM accounts WHERE owner_type='firm' AND owner_id=? ORDER BY id", (founded["firm_id"],))] == accounts
    assert not e.business_control.controls(person, founded["firm_id"])
    validate(e)


@pytest.mark.parametrize("binding", ["staff", "task", "case", "permit"])
def test_city_invariants_reject_restored_dead_authority(city_world, binding):
    world = city_world
    e, store = world.economy, world.store
    person, case, task, tick = under_review(world)
    if binding in {"staff", "task"}:
        deceased = task["assigned_agent_id"]
        staff = store.scalar("SELECT id FROM agency_staff WHERE agent_id=? AND active=1", (deceased,))
    else:
        deceased = person
    if binding == "permit":
        assert decide(world, tick + 1, task["assigned_agent_id"], case)["ok"]
    e.lifecycle.settle_death(tick + 2, deceased)
    if binding == "staff":
        store.update("agency_staff", staff, active=1)
    elif binding == "task":
        store.update("institution_tasks", task["id"], status="assigned", assigned_agent_id=deceased)
    elif binding == "case":
        store.update("service_cases", case, status="under_review")
    else:
        store.execute("UPDATE civic_authorizations SET status='active' WHERE case_id=?", (case,))
    with pytest.raises(EstateError, match="active city rights"):
        e.estate_cases.check_invariants()


def test_actual_nightly_permit_handoff_survives_restarts_and_exact_replay(tmp_path, monkeypatch, caplog):
    config = civic_config()
    config["checkpoint_dir"] = str(tmp_path / "checkpoints")
    identities = {}
    draw = Lifecycle._draw

    def forced_deaths(self, tick, person, mechanism):
        if tick == 2 and mechanism == "mortality" and person in (identities["clerk"], identities["applicant"]):
            return 0.0
        return draw(self, tick, person, mechanism)

    monkeypatch.setattr(Lifecycle, "_draw", forced_deaths)

    def open_seeded(path, settings, *, replay=False):
        world = _world(path, settings, replay=replay)
        if world.store.tick != 0:
            return world
        identities["candidate"] = available_adult(world)
        first, second = _same_region_applicants(world.store, 2)
        for index, applicant in enumerate((first, second)):
            world.store.update("agents", applicant["id"], population_tier="core", pinned_core=1,
                               cadence_json='{"act":1,"career":1}')
            _, case = apply(world, tick=0, applicant=applicant["id"], name=f"Nightly Case {index}")
            identities["durable_case" if index == 0 else "cancelled_case"] = case
        identities["applicant"] = second["id"]
        identities["clerk"] = world.store.scalar("SELECT agent_id FROM agency_staff WHERE active=1 AND region_id=? ORDER BY id LIMIT 1", (first["region_id"],))
        world.economy.city.finalize(0)
        return world

    source_path = tmp_path / "source-city.db"
    for day in range(1, 4):
        source = open_seeded(source_path, config)
        try:
            asyncio.run(source.step())
            if day == 1:
                task = source.store.query_one("SELECT assigned_agent_id,status FROM institution_tasks WHERE source_case_id=?", (identities["durable_case"],))
                assert task is not None and tuple(task) == (identities["clerk"], "assigned")
            if day >= 2:
                assert item_for(source.economy, identities["clerk"], "institutional_assignment") is not None
                assert item_for(source.economy, identities["applicant"], "civic_application") is not None
                assert source.store.scalar("SELECT status FROM service_cases WHERE id=?", (identities["cancelled_case"],)) == "abandoned"
            if day == 3:
                task = source.store.query_one("SELECT assigned_agent_id,status FROM institution_tasks WHERE source_case_id=?", (identities["durable_case"],))
                assert tuple(task) == (identities["candidate"], "completed")
            source.economy.estate_cases.check_invariants()
        finally:
            source.close()
    before = hashlib.sha256(source_path.read_bytes()).hexdigest()
    settings = copy.deepcopy(config)
    settings["replay_source_path"] = str(source_path)
    replay = open_seeded(tmp_path / "replay-city.db", settings, replay=True)
    try:
        for _ in range(3):
            asyncio.run(replay.step())
        proof = verify_replay(source_path, replay.store.path)
        assert proof["exact"], proof["differences"]
        assert not any("action.execution.failed" in record.message for record in caplog.records)
        replay.economy.estate_cases.check_invariants()
    finally:
        replay.close()
    assert hashlib.sha256(source_path.read_bytes()).hexdigest() == before
