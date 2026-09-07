"""Known-answer work/care tradeoffs, claims, failure atomicity and replay."""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import random
import sqlite3

import pytest

from agents.citizen_actions import citizen_world_action_types
from agents.participant import ParticipantService
from agents.policies import citizen_decision, founder_decision
from engine.actions import ActionExecutor
from engine.core import Economy
from engine.daily_time import TimeBudgetError
from engine.earned_wages import WageClaimError
from engine.firms import DEFAULT_PRODUCT
from engine.ledger import SYS_EXTERNAL
from engine.migrations import registry
from engine.store import Store
from research.export_bundle import export_bundle, validate_bundle
from research.hashing import HashContractError, canonical_hashes, load_hash_contract
from server.projections.city_society import build_city_households
from run_config import load_config
from world.replay_verify import verify_replay

from .conftest import make_agent, make_bank
from .test_semantics17_household_decisions import _world
from .test_semantics13_construction import _config as construction_config, _owner, _advance_to_building


@pytest.fixture
def timed(store):
    config = {"engine_semantics_version": 18, "seed": 1,
              "households": {"care_minutes_per_child": 480},
              "lifecycle": {"birth_annual_prob": 0, "population_mode": "drift"}}
    store.execute("UPDATE run_meta SET config_json=?", (json.dumps(config),))
    e = Economy(store, config, random.Random(1), random.Random(2))
    e.ensure_system_accounts()
    bank = make_bank(e)
    people = [make_agent(e, bank, f"Person {i}", age=30, cadence_json='{"career":1}') for i in range(3)]
    e.households.initialize()
    return e, bank, [p[0] for p in people], [p[1] for p in people]


def employer(e, bank, actor=None, *, wage=30_000, interval=30, cash=1_000_000, founder=None):
    firm = e.store.insert("firms", name="Employer", status="private", founder_agent_id=founder,
                          product_json=json.dumps(DEFAULT_PRODUCT), founded_tick=0)
    account = e.ledger.create_account("firm", firm, "checking", bank_id=bank, opening_cents=cash)
    e.store.update("firms", firm, account_id=account)
    if actor is not None:
        employment = e.store.insert("employments", agent_id=actor, firm_id=firm, wage_cents=wage,
            pay_interval_ticks=interval, start_tick=0, next_pay_tick=interval, status="active")
        e.store.update("agents", actor, employer_id=firm)
    else:
        employment = None
    return firm, account, employment


def plan(e, actor, tick=0, *, key="plan", work=480, care=0, children=None, firm=None):
    return e.daily_time.submit_plan(tick, actor, {"request_key": key, "work_minutes": work,
        "care_minutes": care, "care_child_ids": children, "work_firm_id": firm})


def validate(e):
    e.daily_time.check_invariants()
    e.earned_wages.check_invariants()
    assert e.ledger.reconcile()[0]


def test_childcare_reduces_actual_wages_and_output_over_a_full_period(timed):
    e, bank, (guardian, _, _), accounts = timed
    child = e.households.birth(1, guardian)
    firm, _, _ = employer(e, bank, guardian)
    deposits = e.ledger.total_deposits_cents()
    cash = e.ledger.balance(accounts[0])
    for tick in range(1, 31):
        e.daily_time.prepare_day(tick)
        e.firms.process_payroll(tick)
        e.firms.produce(tick)
        if tick == 1:
            assert e.ledger.balance(accounts[0]) == cash
            # Only production spends deposits; accrual itself changes no cash.
            assert e.ledger.total_deposits_cents() == deposits - 5 * DEFAULT_PRODUCT["base_input_cost_cents"]
    assert e.store.scalar("SELECT SUM(worked_minutes) FROM wage_accruals") == 30 * 420
    assert e.store.scalar("SELECT SUM(earned_cents) FROM wage_accruals") == 26_250
    assert e.ledger.balance(accounts[0]) - cash == 26_250
    assert e.store.scalar("SELECT inventory FROM firms WHERE id=?", (firm,)) == 157
    assert e.store.scalar("SELECT carry_numerator FROM firm_labor_days WHERE tick=30") == 240
    assert e.store.scalar("SELECT SUM(delivered_minutes) FROM child_care_days WHERE child_id=?", (child,)) == 30 * 480
    assert e.store.scalar("SELECT MAX(allocated_minutes) FROM time_days") == 960
    validate(e)


def test_shared_care_releases_guardian_time_without_duplicate_child_coverage(timed):
    e, bank, (guardian, helper, _), _ = timed
    child = e.households.birth(1, guardian)
    # Share residence without creating an economic partnership or shared assets.
    old = e.households.membership(helper)
    e.store.update("household_memberships", old["id"], left_tick=0, end_reason="test")
    e.store.insert("household_memberships", household_id=e.households.membership(guardian)["household_id"],
                   agent_id=helper, role="adult", joined_tick=0)
    employer(e, bank, guardian)
    plan(e, helper, work=0, care=480, children=[child])
    e.daily_time.prepare_day(1)
    assert e.store.scalar("SELECT worked_minutes FROM wage_accruals") == 480
    assert e.store.scalar("SELECT earned_cents FROM wage_accruals") == 1000
    assert e.store.scalar("SELECT delivered_minutes FROM child_care_days") == 480
    assert e.store.scalar("SELECT COUNT(*) FROM time_allocations WHERE kind='care'") == 1
    assert e.store.scalar("SELECT agent_id FROM time_allocations WHERE kind='care'") == helper
    validate(e)


def test_plan_is_prospective_idempotent_and_explicit_zero_care_is_respected(timed):
    e, bank, (actor, _, _), _ = timed
    e.households.birth(1, actor)
    employer(e, bank, actor)
    e.daily_time.prepare_day(1)
    first = plan(e, actor, tick=1, care=0)
    assert first["effective_tick"] == 2
    assert plan(e, actor, tick=2, care=0)["idempotent"]
    assert e.store.scalar("SELECT worked_minutes FROM wage_accruals WHERE tick=1") == 420
    with pytest.raises(TimeBudgetError, match="different time terms"):
        plan(e, actor, work=0)
    e.daily_time.prepare_day(2)
    assert e.store.scalar("SELECT delivered_minutes FROM child_care_days WHERE tick=2") == 0
    assert e.store.scalar("SELECT worked_minutes FROM wage_accruals WHERE tick=2") == 480
    before = canonical_hashes(e.store)["authoritative_sha256"]
    e.daily_time.prepare_day(2)
    assert canonical_hashes(e.store)["authoritative_sha256"] == before
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        e.store.execute("UPDATE time_plans SET work_minutes=0")
    validate(e)


@pytest.mark.parametrize("field,value", [("work_minutes", True), ("care_minutes", 1.5),
    ("work_minutes", "480"), ("work_firm_id", True), ("care_child_ids", [True]), ("care_child_ids", [1,1])])
def test_strict_plan_rejects_invalid_types_and_duplicate_targets(timed, field, value):
    e, _, (actor, _, _), _ = timed
    action = {"type": "set_time_plan", "request_key": "bad", "work_minutes": 480, "care_minutes": 0, field: value}
    assert not ActionExecutor(e).execute_action(1, actor, action)["ok"]
    assert e.store.scalar("SELECT COUNT(*) FROM time_plans") == 0


def test_minor_outsider_and_time_overcommit_are_rejected(timed):
    e, _, (actor, outsider, _), _ = timed
    child = e.households.birth(1, actor)
    with pytest.raises(TimeBudgetError, match="living adult"):
        plan(e, child)
    with pytest.raises(TimeBudgetError, match="household members"):
        plan(e, outsider, children=[child], care=120)
    with pytest.raises(TimeBudgetError, match="exceed"):
        plan(e, actor, care=600)
    assert "set_time_plan" not in citizen_world_action_types(17)
    assert "set_time_plan" in citizen_world_action_types(18)


def test_work_is_not_duplicated_across_a_founders_firms(timed):
    e, bank, (actor, _, _), _ = timed
    first, _, _ = employer(e, bank, founder=actor)
    second, _, _ = employer(e, bank, founder=actor)
    e.daily_time.prepare_day(1)
    e.firms.produce(1)
    assert e.store.scalar("SELECT SUM(productive_minutes) FROM firm_labor_days") == 480
    assert e.store.scalar("SELECT inventory FROM firms WHERE id=?", (first,)) == 6
    assert e.store.scalar("SELECT inventory FROM firms WHERE id=?", (second,)) == 0
    plan(e, actor, 1, firm=second)
    e.daily_time.prepare_day(2)
    e.firms.produce(2)
    assert e.store.scalar("SELECT inventory FROM firms WHERE id=?", (second,)) == 6
    e.firms.produce(2)
    assert e.store.scalar("SELECT inventory FROM firms WHERE id=?", (second,)) == 6
    validate(e)


@pytest.mark.parametrize("state", [{"health":"critical"}, {"retired":1}])
def test_daily_health_and_retirement_prevent_work(timed, state):
    e, bank, (actor, _, _), _ = timed
    employer(e, bank, actor)
    e.store.update("agents", actor, **state)
    e.daily_time.prepare_day(1)
    assert e.store.scalar("SELECT COUNT(*) FROM wage_accruals") == 0
    validate(e)


def test_subcent_carry_partial_taxed_payment_and_ended_employment(timed):
    e, bank, (actor, _, _), accounts = timed
    firm, firm_cash, employment = employer(e, bank, actor, wage=10, interval=3, cash=6)
    e.store.record_metric(0, "tax_rate_bps", 2500)
    initial = e.ledger.balance(accounts[0])
    deposits = e.ledger.total_deposits_cents()
    for tick in range(1, 4):
        e.daily_time.prepare_day(tick)
    assert [r[0] for r in e.store.query("SELECT earned_cents FROM wage_accruals ORDER BY tick")] == [3,3,4]
    assert e.ledger.total_deposits_cents() == deposits
    e.firms.process_payroll(3)
    claim = e.store.query_one("SELECT * FROM wage_claims")
    assert claim["paid_cents"] == 6 and e.earned_wages.outstanding(claim) == 4
    assert e.firms.get(firm)["status"] == "private"
    assert e.ledger.balance(accounts[0]) - initial == 5
    e.store.update("employments", employment, status="ended", end_tick=3)
    e.store.update("agents", actor, employer_id=None)
    e.ledger.transfer(4, e.ledger.system_account(SYS_EXTERNAL), firm_cash, 4, kind="test_funding")
    e.firms.process_payroll(4)
    assert e.ledger.balance(accounts[0]) - initial == 8
    assert e.store.scalar("SELECT closed_tick FROM wage_claims") == 4
    validate(e)


def test_inheritance_transfers_unpaid_claim_without_cash_and_bankruptcy_writes_it_off(timed):
    e, bank, (actor, heir, _), accounts = timed
    firm, _, _ = employer(e, bank, actor, cash=0)
    e.store.insert("social_ties", agent_a=actor, agent_b=heir, weight=1.0)
    e.daily_time.prepare_day(1)
    initial = e.ledger.balance(accounts[0]) + e.ledger.balance(accounts[1])
    e.lifecycle.settle_death(2, actor)
    assert e.ledger.balance(accounts[1]) == initial
    claim = e.store.query_one("SELECT * FROM wage_claims")
    holder = e.earned_wages.holder(claim["id"])
    assert holder["owner_id"] == heir and e.earned_wages.outstanding(claim) == 1000
    assert e.ledger.balance(holder["receivable_account_id"]) == 1000
    validate(e)
    e.firms.bankrupt_firm(2, firm)
    assert e.ledger.balance(accounts[1]) == initial
    assert e.store.scalar("SELECT written_off_cents FROM wage_claims") == 1000
    assert e.store.scalar("SELECT closed_tick FROM wage_claims") == 2
    validate(e)


def test_persistent_wage_arrears_reach_resolution_after_one_contract_period(timed):
    e, bank, (actor, _, _), _ = timed
    firm, _, _ = employer(e, bank, actor, wage=10, interval=3, cash=6)
    for tick in range(1, 7):
        e.daily_time.prepare_day(tick)
        e.firms.process_payroll(tick)
        if tick < 6:
            assert e.firms.get(firm)["status"] == "private"
    assert e.firms.get(firm)["status"] == "bankrupt"
    assert e.store.scalar("SELECT paid_cents FROM wage_claims") == 6
    assert e.store.scalar("SELECT written_off_cents FROM wage_claims") == 14
    validate(e)


def test_wage_write_off_failure_rolls_back_the_entire_firm_resolution(timed, monkeypatch):
    e, bank, (actor, _, _), _ = timed
    firm, _, _ = employer(e, bank, actor, cash=0)
    e.daily_time.prepare_day(1)
    before = canonical_hashes(e.store)["authoritative_sha256"]
    def fail(*args):
        raise WageClaimError("injected accounting failure")
    monkeypatch.setattr(e.earned_wages, "write_off_firm", fail)
    with pytest.raises(WageClaimError, match="injected"):
        e.firms.bankrupt_firm(2, firm)
    assert canonical_hashes(e.store)["authoritative_sha256"] == before
    assert e.firms.get(firm)["status"] == "private"
    validate(e)


def test_timed_action_failure_rolls_back_money_and_time_and_retry_is_once(timed):
    e, _, (actor, _, _), accounts = timed
    e.daily_time.prepare_day(1)
    initial = e.ledger.balance(accounts[0])
    def fail():
        e.ledger.transfer(1, accounts[0], e.ledger.system_account(SYS_EXTERNAL), 50, kind="test_activity")
        return {"ok": False, "reason": "not feasible"}
    assert not e.daily_time.perform(1, actor, "test-fail", "study", 120, {}, fail)["ok"]
    assert e.ledger.balance(accounts[0]) == initial
    assert e.daily_time.remaining(1, actor) == 960
    success = e.cognition.study_skill(1, actor, "labor", proposal_id=99)
    assert success["ok"]
    cash = e.ledger.balance(accounts[0])
    assert e.daily_time.remaining(1, actor) == 840
    assert e.cognition.study_skill(1, actor, "labor", proposal_id=99) == success
    assert e.ledger.balance(accounts[0]) == cash
    assert e.daily_time.remaining(1, actor) == 840
    assert not e.daily_time.perform(1, actor, "too-big", "study", 841, {}, lambda:{"ok":True})["ok"]
    validate(e)


def test_time_and_claims_are_hashed_and_exported_with_no_old_contract_escape(timed, tmp_path):
    e, bank, (actor, _, _), _ = timed
    employer(e, bank, actor)
    e.daily_time.prepare_day(1)
    hashes = canonical_hashes(e.store)
    assert hashes["contract_id"] == "hash-contract-v5"
    assert hashes["tables"]["wage_accruals"]["row_count"] == 1
    with pytest.raises(HashContractError, match="requires hash-contract-v5"):
        canonical_hashes(e.store, load_hash_contract("research/hash-contract-v4.json"))
    manifest = validate_bundle(export_bundle(e.store, tmp_path / "exports"))
    assert manifest["tables"]["time_allocations"]["row_count"] == 2
    e.store.execute("UPDATE run_meta SET config_json=?", (json.dumps({"engine_semantics_version":17}),))
    with pytest.raises(HashContractError, match="populated daily time"):
        canonical_hashes(e.store)


def test_foreign_primary_wallet_does_not_convert_earned_wages(timed):
    e, bank, (actor, _, _), accounts = timed
    employer(e, bank, actor, interval=1, wage=1200)
    foreign = e.ledger.create_account("agent", actor, "fx", currency_code="CAD")
    e.store.update("agents", actor, checking_account_id=foreign)
    initial = e.ledger.balance(accounts[0])
    e.daily_time.prepare_day(1)
    e.firms.process_payroll(1)
    assert e.ledger.balance(foreign) == 0
    assert e.ledger.balance(accounts[0]) == initial + 1200
    assert e.store.scalar("SELECT currency_code FROM wage_claims") == "USD"
    validate(e)


def test_claim_without_heir_remains_non_cash_until_collected(timed):
    e, bank, (actor, _, _), _ = timed
    from engine.ledger import SYS_GOV
    _, cash, _ = employer(e, bank, actor, cash=0)
    gov = e.ledger.system_account(SYS_GOV)
    e.daily_time.prepare_day(1)
    before = e.ledger.balance(gov)
    checking = e.ledger.agent_checking_id(actor)
    estate_cash = e.ledger.balance(checking)
    e.lifecycle.settle_death(2, actor)
    holder = e.earned_wages.holder(1)
    assert holder["owner_type"] == "system" and holder["owner_id"] is None
    assert e.ledger.balance(gov) == before + estate_cash
    e.ledger.transfer(2, e.ledger.system_account(SYS_EXTERNAL), cash, 1000, kind="test_funding")
    e.firms.process_payroll(2)
    assert e.ledger.balance(gov) == before + estate_cash + 1000
    assert e.ledger.balance(holder["receivable_account_id"]) == 0
    validate(e)


def test_changed_employment_period_rejects_day_atomically(timed):
    e, bank, (actor, _, _), _ = timed
    _, _, employment = employer(e, bank, actor)
    e.daily_time.prepare_day(1)
    before = [tuple(row) for row in e.store.query("SELECT * FROM accounts ORDER BY id")]
    e.store.update("employments", employment, pay_interval_ticks=2)
    with pytest.raises(WageClaimError, match="new employment contract"):
        e.daily_time.prepare_day(2)
    assert e.store.scalar("SELECT COUNT(*) FROM time_days WHERE tick=2") == 0
    assert [tuple(row) for row in e.store.query("SELECT * FROM accounts ORDER BY id")] == before
    validate(e)


def test_named_care_does_not_silently_extend_to_a_new_child(timed):
    e, _, (actor, _, _), _ = timed
    original = e.households.birth(1, actor)
    plan(e, actor, tick=1, care=480, children=[original])
    e.store.update("agents", original, age=18)
    newborn = e.households.birth(2, actor)
    e.daily_time.prepare_day(2)
    assert e.store.scalar("SELECT delivered_minutes FROM child_care_days WHERE child_id=?", (newborn,)) == 0
    assert e.store.scalar("SELECT COUNT(*) FROM time_allocations WHERE kind='care'") == 0
    validate(e)


@pytest.mark.parametrize("available,can_attend", [(960, True), (480, False)])
def test_civic_time_reservation_is_not_attendance_and_must_fit(tmp_path, available, can_attend):
    config = construction_config(semantics=18)
    config["daily_time"] = {"available_minutes":available}
    world = _world(tmp_path / "appointment.db", config)
    try:
        e = world.economy
        opportunity = None
        for application_tick in range(1, 5):
            for person in e.store.query("SELECT * FROM agents WHERE alive=1 AND role IS NULL ORDER BY id"):
                context = world.runtime.ctx.build(person, application_tick)
                candidate = context.get("entrepreneurship_opportunity")
                if candidate and candidate.get("action", {}).get("type") == "apply_business_permit":
                    actor, opportunity = person["id"], candidate["action"]
                    break
            if opportunity:
                break
        assert opportunity
        result = world.runtime.executor.execute_action(application_tick, actor, opportunity)
        assert result["ok"], result
        e.city.finalize(application_tick)
        appointment = e.store.query_one("SELECT * FROM service_appointments WHERE case_id=?", (result["case_id"],))
        tick = appointment["scheduled_tick"]
        e.city.run_nightly(tick)
        e.daily_time.prepare_day(tick)
        reservation = e.store.query_one("SELECT * FROM time_allocations WHERE agent_id=? AND kind='civic'", (actor,))
        assert bool(reservation) == can_attend
        before = e.daily_time.remaining(tick, actor)
        if can_attend:
            assert reservation["delivered_minutes"] == 0
        attended = e.city.attend_appointment(tick, actor, appointment["id"])
        assert attended["ok"] == can_attend, attended
        assert e.daily_time.remaining(tick, actor) == before
        if can_attend:
            assert e.store.scalar("SELECT delivered_minutes FROM time_allocations WHERE id=?", (reservation["id"],)) == 480
            assert e.city.attend_appointment(tick, actor, appointment["id"]) == attended
        assert e.store.scalar("SELECT COUNT(*) FROM time_allocations WHERE agent_id=? AND kind='employment'", (actor,)) == 0
        validate(e)
    finally:
        world.close()


def test_construction_cannot_exceed_time_or_charge_a_repeat_on_another_day(tmp_path):
    config = construction_config(semantics=18)
    world = _world(tmp_path / "construction.db", config)
    try:
        e = world.economy
        owner = _owner(world)
        actor = owner["id"]
        project, _ = _advance_to_building(world, owner)
        plan(e, actor, tick=4, work=0)
        e.city.run_nightly(5)
        e.daily_time.prepare_day(5)
        e.daily_time._allocate(5, actor, "other-study", "study", 900, "study")
        action = {"type":"perform_construction_work", "project_id":project, "work_units":2,
                  "wage_cents":100, "procurement_cents":100, "dedupe_key":"timed-work"}
        initial = canonical_hashes(e.store)["authoritative_sha256"]
        result = e.construction.perform_work(5, actor, action)
        assert not result["ok"] and "time" in result["reason"]
        assert canonical_hashes(e.store)["authoritative_sha256"] == initial
        e.city.run_nightly(6)
        e.daily_time.prepare_day(6)
        result = e.construction.perform_work(6, actor, action)
        assert result["ok"], result
        assert e.daily_time.remaining(6, actor) == 840
        assert e.store.scalar("SELECT contributed_work_units FROM construction_projects WHERE id=?", (project,)) == 2
        e.city.run_nightly(7)
        e.daily_time.prepare_day(7)
        assert e.construction.perform_work(7, actor, action)["idempotent"]
        assert e.daily_time.remaining(7, actor) == 960
        assert e.store.scalar("SELECT contributed_work_units FROM construction_projects WHERE id=?", (project,)) == 2
        validate(e)
    finally:
        world.close()


def test_city_care_projection_uses_only_selected_day_and_visible_children(timed):
    e, _, (actor, _, _), _ = timed
    child = e.households.birth(1, actor)
    e.store.update("agents", actor, population_tier="core")
    e.store.update("agents", child, population_tier="core")
    e.daily_time.prepare_day(1)
    e.households.provision_children(1)
    households = build_city_households(e.store, as_of_tick=1)["items"]
    need = next(need for h in households for need in h["child_needs"] if need["child_agent_id"] == child)
    assert need["care_delivered_minutes"] == 480 and need["care_unmet_minutes"] == 0
    assert need["care_status"] == "delivered"
    assert all(not h["child_needs"] for h in build_city_households(e.store, as_of_tick=0)["items"])
    e.store.update("agents", child, population_tier="peripheral", pinned_core=0)
    assert all(need["child_agent_id"] != child for h in build_city_households(e.store, as_of_tick=1)["items"] for need in h["child_needs"])


def test_real_daily_time_rehearsal_resumes_and_replays_exactly(tmp_path, caplog):
    config = load_config("runs/daily-time-rehearsal.yaml")
    config["checkpoint_dir"] = str(tmp_path / "checkpoints")
    path = tmp_path / "source.db"
    source = _world(path, config)
    try:
        for _ in range(2):
            asyncio.run(source.step())
        assert source.store.scalar("SELECT COUNT(*) FROM wage_accruals") > 0
        assert source.store.scalar("SELECT SUM(delivered_minutes) FROM child_care_days") > 0
    finally:
        source.close()
    source = _world(path, config)
    try:
        asyncio.run(source.step())
        validate(source.economy)
    finally:
        source.close()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    replay_config = copy.deepcopy(config)
    replay_config["replay_source_path"] = str(path)
    replay = _world(tmp_path / "replay.db", replay_config, replay=True)
    try:
        for _ in range(3):
            asyncio.run(replay.step())
        proof = verify_replay(path, replay.store.path)
        assert proof["exact"], proof["differences"]
        validate(replay.economy)
        assert not any("action.execution.failed" in record.message for record in caplog.records)
    finally:
        replay.close()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_daily_plans_are_available_to_models_scripted_and_external_citizens(tmp_path):
    config = load_config("runs/daily-time-rehearsal.yaml")
    world = _world(tmp_path / "catalog.db", config)
    try:
        asyncio.run(world.step())
        actor = world.store.query_one("SELECT * FROM agents WHERE id=11")
        context = world.runtime.ctx.build(actor, 1)
        system, prompt = world.runtime.ctx.render_prompt(context)
        assert "set_time_plan" in system and "DAILY TIME" in prompt
        catalog = ParticipantService(world.store, world.runtime.ctx, config).action_catalog(actor["id"])
        assert any(item["type"] == "set_time_plan" for item in catalog)
        # Force only the declared time baseline to be the relevant decision.
        context = {"daily_time": context["daily_time"]}
        assert citizen_decision(context)["actions"][0]["type"] == "set_time_plan"
        assert founder_decision({**context,"my_firm":{"firm_id":1}})["actions"][0]["type"] == "set_time_plan"
    finally:
        world.close()


def test_schema22_semantics17_source_replays_without_rewriting_original(tmp_path, monkeypatch):
    config = load_config("runs/household-decisions-rehearsal.yaml")
    config["checkpoint_dir"] = str(tmp_path / "checkpoints")
    migrations = registry._MIGRATIONS
    monkeypatch.setattr(registry, "_MIGRATIONS", tuple(m for m in migrations if m.version < 23))
    path = tmp_path / "old.db"
    source = _world(path, config)
    try:
        source.store.execute("UPDATE run_meta SET schema_version=22")
        asyncio.run(source.step())
    finally:
        source.close()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(registry, "_MIGRATIONS", migrations)
    config["replay_source_path"] = str(path)
    replay = _world(tmp_path / "new.db", config, replay=True)
    try:
        asyncio.run(replay.step())
        proof = verify_replay(path, replay.store.path)
        assert proof["exact"], proof["differences"]
        replay.store.insert("time_days", tick=1, agent_id=11, available_minutes=960)
        assert "time_days" in verify_replay(path, replay.store.path)["differences"]
    finally:
        replay.close()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_daily_time_migration_failure_preserves_the_schema22_source(tmp_path, monkeypatch):
    path = tmp_path / "schema22.db"
    migrations = registry._MIGRATIONS
    monkeypatch.setattr(registry, "_MIGRATIONS", tuple(m for m in migrations if m.version < 23))
    store = Store(str(path))
    store.init_run_meta("old", 1, {"engine_semantics_version":17})
    store.execute("UPDATE run_meta SET schema_version=22")
    actor = store.insert("agents", name="Existing", kind="citizen", age=42)
    store.close()
    migration = next(m for m in migrations if m.version == 23)
    broken = registry.Migration.create(23, migration.name, migration.sql + "\nINVALID SQL;", verify=migration.verify)
    monkeypatch.setattr(registry, "_MIGRATIONS", tuple(broken if m.version == 23 else m for m in migrations))
    with pytest.raises(registry.MigrationError):
        Store(str(path))
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT schema_version FROM run_meta").fetchone()[0] == 22
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='time_days'").fetchone() is None
        assert conn.execute("SELECT age FROM agents WHERE id=?", (actor,)).fetchone()[0] == 42
    monkeypatch.setattr(registry, "_MIGRATIONS", migrations)
    store = Store(str(path))
    try:
        assert store.scalar("SELECT schema_version FROM run_meta") == 23
        assert store.scalar("SELECT COUNT(*) FROM time_days") == 0
        assert store.scalar("SELECT age FROM agents WHERE id=?", (actor,)) == 42
    finally:
        store.close()
