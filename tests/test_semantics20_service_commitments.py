"""Real service purchases and underwriting across death and firm succession."""
import asyncio
import copy
import hashlib
import json
import random
from types import SimpleNamespace

import pytest

from engine.actions import ActionExecutor
from engine.core import Economy
from engine.estates import EstateError
from engine.lifecycle import Lifecycle
from research.hashing import canonical_hashes
from world.replay_verify import verify_replay

from .conftest import make_agent, make_bank
from .test_semantics17_household_decisions import _world
from .test_semantics20_civic_succession import available_adult, civic_config
from .test_semantics20_personal_authority import item_for, validate


@pytest.fixture
def services(store):
    config = {"engine_semantics_version": 20, "seed": 1,
              "lifecycle": {"population_mode": "drift", "birth_annual_prob": 0},
              "family_decisions": {"scripted_matching": False},
              "health": {"premium_cents": 40, "premium_interval_ticks": 2},
              "cognition": {"duration_ticks": 2, "flash_cost_cents": 100,
                            "premium_cost_cents": 300}}
    store.execute("UPDATE run_meta SET config_json=?", (json.dumps(config),))
    e = Economy(store, config, random.Random(1), random.Random(2))
    e.ensure_system_accounts()
    store.insert("regions", id=1, region_key="home", name="Home", currency_code="USD",
                 population_target=4, specialization_json="{}", x=0, y=0, legal_ruleset="test")
    bank = make_bank(e)
    operator, _ = make_agent(e, bank, "Insurer operator", cash=300_000, region_id=1)
    heir, _ = make_agent(e, bank, "Successor", cash=10_000, region_id=1)
    client, _ = make_agent(e, bank, "Insured employee", cash=100_000, region_id=1)
    officer, _ = make_agent(e, bank, "Credit officer", kind="staff", role="credit_officer", region_id=1)
    firm = e.firms.found_firm(0, operator, "Continuing insurer", "insurance", opening_capital_cents=100_000)
    store.insert("social_ties", agent_a=operator, agent_b=heir, weight=1)
    store.insert("social_ties", agent_a=client, agent_b=heir, weight=1)
    e.households.initialize()
    executor = ActionExecutor(e)
    job = e.labor.post_job(0, firm, "Insurance worker", 1000)
    application = e.labor.apply_job(0, client, job)
    offer = executor.execute_action(0, operator, {"type": "make_job_offer", "application_id": application, "wage": 1000})
    assert offer["ok"], offer
    accepted = executor.execute_action(0, client, {"type": "accept_job_offer", "offer_id": offer["offer_id"]})
    assert accepted["ok"], accepted
    return SimpleNamespace(e=e, bank=bank, operator=operator, heir=heir, client=client,
                           officer=officer, firm=firm, executor=executor)


def act(s, tick, person, **action):
    result = s.executor.execute_action(tick, person, action)
    assert result["ok"], result
    return result


def money_history(e, kind):
    return (
        [tuple(r) for r in e.store.query("SELECT * FROM transactions WHERE kind=? ORDER BY id", (kind,))],
        [tuple(r) for r in e.store.query("SELECT * FROM ledger_entries WHERE txn_id IN "
            "(SELECT id FROM transactions WHERE kind=?) ORDER BY id", (kind,))],
    )


def buy_insurance(s):
    return act(s, 0, s.client, type="buy_insurance")["policy_id"]


def apply_loan(s, *, as_firm=False, tick=0, person=None, amount=1000):
    borrower = person if person is not None else (s.operator if as_firm else s.client)
    action = {"type": "apply_loan", "bank_id": s.bank, "amount": amount, "purpose": "Working funds"}
    if as_firm:
        action.update(as_firm=True, firm_id=s.firm)
    return act(s, tick, borrower, **action)["application_id"]


def test_purchased_insurance_ends_without_later_premiums_or_inherited_cover(services):
    s, e = services, services.e
    policy = buy_insurance(s)
    opening = dict(e.store.query_one("SELECT * FROM insurance_policies WHERE id=?", (policy,)))
    paid = money_history(e, "insurance_premium")
    e.lifecycle.settle_death(1, s.client)
    assert json.loads(item_for(e, s.client, "insurance")["snapshot_json"]) == opening
    assert tuple(e.store.query_one("SELECT status,end_tick FROM insurance_policies WHERE id=?", (policy,))) == ("cancelled", 1)
    heir_cash = e.ledger.balance(e.ledger.agent_checking_id(s.heir))
    for tick in (2, 4):
        e.lifecycle._collect_premiums(tick)
    assert money_history(e, "insurance_premium") == paid
    assert e.ledger.balance(e.ledger.agent_checking_id(s.heir)) == heir_cash
    assert e.store.scalar("SELECT COUNT(*) FROM insurance_policies WHERE agent_id=?", (s.heir,)) == 0
    assert not s.executor.execute_action(4, s.client, {"type": "buy_insurance"})["ok"]
    validate(e)


def test_a_valid_premium_precedes_death_in_the_same_nightly_cycle(services, monkeypatch):
    s, e = services, services.e
    policy = buy_insurance(s)
    monkeypatch.setattr(e.lifecycle, "_draw", lambda tick, person, mechanism:
                        0.0 if person == s.client and mechanism == "mortality" else 1.0)
    e.lifecycle.run_nightly(2)
    paid = money_history(e, "insurance_premium")
    assert len(paid[0]) == 2
    assert tuple(e.store.query_one("SELECT status,end_tick FROM insurance_policies WHERE id=?", (policy,))) == ("cancelled", 2)
    opening = json.loads(item_for(e, s.client, "insurance")["snapshot_json"])
    assert opening["next_premium_tick"] == 4
    e.lifecycle._collect_premiums(4)
    assert money_history(e, "insurance_premium") == paid
    validate(e)


def test_insurance_and_premiums_survive_the_insurers_operator(services):
    s, e = services, services.e
    policy = buy_insurance(s)
    opening = dict(e.store.query_one("SELECT * FROM insurance_policies WHERE id=?", (policy,)))
    e.lifecycle.settle_death(1, s.operator)
    assert dict(e.store.query_one("SELECT * FROM insurance_policies WHERE id=?", (policy,))) == opening
    assert item_for(e, s.operator, "insurance") is None
    assert e.business_control.operator_at(s.firm) == s.heir
    account = e.firms.get(s.firm)["account_id"]
    before = e.ledger.balance(account)
    e.lifecycle._collect_premiums(2)
    assert e.ledger.balance(account) == before + opening["premium_cents"]
    assert e.store.scalar("SELECT status FROM insurance_policies WHERE id=?", (policy,)) == "active"
    assert e.firms.get(s.firm)["founder_agent_id"] == s.operator
    patient_account = e.ledger.agent_checking_id(s.client)
    patient_cash = e.ledger.balance(patient_account)
    e.lifecycle._charge_medical(2, s.client)
    cost = e.lifecycle.p["medical_cost_cents"]
    covered = cost * opening["coverage_bps"] // 10_000
    assert e.ledger.balance(account) == before + opening["premium_cents"] - covered
    assert e.ledger.balance(patient_account) == patient_cash - (cost - covered)
    assert e.store.scalar("SELECT COUNT(*) FROM transactions WHERE kind='insurance_claim'") == 1
    validate(e)


@pytest.mark.parametrize("payer,active", [("agent", False), ("agent", True), ("firm", False), ("firm", True), ("government", True)])
def test_paid_compute_access_ends_for_the_recipient_without_reactivation(services, payer, active):
    s, e = services, services.e
    person = s.officer if payer == "government" else s.client
    if payer == "agent":
        subscription = act(s, 0, person, type="buy_compute_plan", tier="flash")["subscription_id"]
        kind = "compute_subscription"
    elif payer == "firm":
        result = act(s, 0, s.operator, type="set_compute_sponsorship", firm_id=s.firm, tier="flash", max_seats=1)
        assert result["agent_ids"] == [person]
        subscription = result["subscription_ids"][0]
        kind = "compute_sponsorship"
    else:
        e.cognition.run_nightly(0)
        subscription = e.cognition.current_subscription(person, 0)["id"]
        kind = "public_compute_sponsorship"
    if active and payer != "government":
        e.cognition.run_nightly(1)
    opening = dict(e.store.query_one("SELECT * FROM compute_subscriptions WHERE id=?", (subscription,)))
    assert opening["status"] == ("active" if active else "pending")
    paid = money_history(e, kind)
    death = 2 if active and payer != "government" else 1
    e.lifecycle.settle_death(death, person)
    assert json.loads(item_for(e, person, "compute_access")["snapshot_json"]) == opening
    for tick in (death, death + e.cognition.duration_ticks + 1):
        e.cognition.run_nightly(tick)
        assert e.cognition.current_subscription(person, tick) is None
    assert e.store.scalar("SELECT status FROM compute_subscriptions WHERE id=?", (subscription,)) == "cancelled"
    assert e.store.scalar("SELECT COUNT(*) FROM compute_subscriptions WHERE agent_id=?", (person,)) == 1
    assert money_history(e, kind) == paid
    assert e.store.scalar("SELECT COUNT(*) FROM compute_subscriptions WHERE agent_id=?", (s.heir,)) == 0
    assert not s.executor.execute_action(death + 4, person, {"type": "buy_compute_plan", "tier": "flash"})["ok"]
    validate(e)


@pytest.mark.parametrize("active", [False, True])
def test_living_workers_keep_company_access_and_the_successor_can_renew_it(services, active):
    s, e = services, services.e
    result = act(s, 0, s.operator, type="set_compute_sponsorship", firm_id=s.firm, tier="flash", max_seats=1)
    subscription = result["subscription_ids"][0]
    if active:
        e.cognition.run_nightly(1)
    opening = dict(e.store.query_one("SELECT * FROM compute_subscriptions WHERE id=?", (subscription,)))
    death = 2 if active else 1
    e.lifecycle.settle_death(death, s.operator)
    assert dict(e.store.query_one("SELECT * FROM compute_subscriptions WHERE id=?", (subscription,))) == opening
    assert item_for(e, s.operator, "compute_access") is None
    e.cognition.run_nightly(death)
    assert e.cognition.current_subscription(s.client, death)["id"] == subscription
    renewed = act(s, 2, s.heir, type="set_compute_sponsorship", firm_id=s.firm, tier="flash", max_seats=1)
    assert renewed["agent_ids"] == [s.client]
    e.cognition.run_nightly(3)
    assert e.cognition.current_subscription(s.client, 3)["id"] == renewed["subscription_ids"][0]
    assert e.store.scalar("SELECT COUNT(*) FROM transactions WHERE kind='compute_sponsorship'") == 2
    assert e.firms.get(s.firm)["founder_agent_id"] == s.operator
    validate(e)


@pytest.mark.parametrize("as_firm", [False, True])
def test_actual_loan_underwriting_distinguishes_the_person_from_the_company(services, as_firm):
    s, e = services, services.e
    application = apply_loan(s, as_firm=as_firm)
    opening = dict(e.store.query_one("SELECT * FROM loan_applications WHERE id=?", (application,)))
    person = s.operator if as_firm else s.client
    e.lifecycle.settle_death(1, person)
    if as_firm:
        assert dict(e.store.query_one("SELECT * FROM loan_applications WHERE id=?", (application,))) == opening
    before = e.store.scalar("SELECT COUNT(*) FROM transactions")
    decision = s.executor.execute_action(2, s.officer, {"type": "approve_loan", "application_id": application, "term_ticks": 60})
    if as_firm:
        assert decision["ok"], decision
        assert item_for(e, person, "loan_application") is None
        loan = e.store.query_one("SELECT * FROM loans WHERE id=?", (decision["loan_id"],))
        assert (loan["borrower_type"], loan["borrower_id"]) == ("firm", s.firm)
        assert e.business_control.operator_at(s.firm) == s.heir
        heir_cash = e.ledger.balance(e.ledger.agent_checking_id(s.heir))
        e.bank.process_due_loans(loan["next_due_tick"])
        assert e.store.scalar("SELECT outstanding_cents FROM loans WHERE id=?", (loan["id"],)) < loan["outstanding_cents"]
        assert e.ledger.balance(e.ledger.agent_checking_id(s.heir)) == heir_cash
    else:
        assert not decision["ok"] and decision["reason"] == "application not pending"
        assert e.store.scalar("SELECT COUNT(*) FROM transactions") == before
        assert json.loads(item_for(e, person, "loan_application")["snapshot_json"]) == opening
        assert tuple(e.store.query_one("SELECT status,decided_tick FROM loan_applications WHERE id=?", (application,))) == ("expired", 1)
        replacement = apply_loan(s, tick=2, person=s.heir)
        assert act(s, 2, s.officer, type="approve_loan", application_id=replacement)["loan_id"]
        assert e.store.scalar("SELECT COUNT(*) FROM loans WHERE borrower_type='agent' AND borrower_id=?", (person,)) == 0
    validate(e)


def test_a_payment_before_death_remains_recorded_and_the_closed_loan_cannot_charge_again(services):
    s, e = services, services.e
    application = apply_loan(s, amount=3000)
    loan_id = act(s, 0, s.officer, type="approve_loan", application_id=application, term_ticks=60)["loan_id"]
    loan = e.store.query_one("SELECT * FROM loans WHERE id=?", (loan_id,))
    due = loan["next_due_tick"]
    e.bank.process_due_loans(due)
    outstanding = e.store.scalar("SELECT outstanding_cents FROM loans WHERE id=?", (loan_id,))
    assert 0 < outstanding < 3000
    earlier_entries = [tuple(r) for r in e.store.query("SELECT * FROM ledger_entries ORDER BY id")]
    e.lifecycle.settle_death(due, s.client)
    assert [tuple(r) for r in e.store.query("SELECT * FROM ledger_entries ORDER BY id LIMIT ?", (len(earlier_entries),))] == earlier_entries
    assert e.store.scalar("SELECT principal_cents FROM estate_claims WHERE kind='bank_principal' AND source_id=?", (loan_id,)) == outstanding
    assert tuple(e.store.query_one("SELECT status,outstanding_cents FROM loans WHERE id=?", (loan_id,))) == ("paid", 0)
    transactions = e.store.scalar("SELECT COUNT(*) FROM transactions")
    e.bank.process_due_loans(due + 30)
    assert e.store.scalar("SELECT COUNT(*) FROM transactions") == transactions
    validate(e)


def prepare_service(s, kind):
    if kind == "insurance":
        return "insurance_policies", buy_insurance(s), "cancelled"
    if kind == "compute":
        result = act(s, 0, s.client, type="buy_compute_plan", tier="flash")
        return "compute_subscriptions", result["subscription_id"], "cancelled"
    return "loan_applications", apply_loan(s), "expired"


@pytest.mark.parametrize("kind", ["insurance", "compute", "loan"])
def test_later_death_failure_restores_the_actual_service_and_all_payments(services, monkeypatch, kind):
    s, e = services, services.e
    table, source, closed = prepare_service(s, kind)
    opening = dict(e.store.query_one(f"SELECT * FROM {table} WHERE id=?", (source,)))
    before = canonical_hashes(e.store)["authoritative_sha256"]
    original = e.civic_authority.close_person
    def fail_after_closing(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected after service closing")
    monkeypatch.setattr(e.civic_authority, "close_person", fail_after_closing)
    with pytest.raises(RuntimeError, match="injected after service closing"):
        e.lifecycle.settle_death(1, s.client)
    assert canonical_hashes(e.store)["authoritative_sha256"] == before
    assert dict(e.store.query_one(f"SELECT * FROM {table} WHERE id=?", (source,))) == opening
    assert e.estate_cases._pending is None
    monkeypatch.setattr(e.civic_authority, "close_person", original)
    e.lifecycle.settle_death(1, s.client)
    assert e.store.scalar(f"SELECT status FROM {table} WHERE id=?", (source,)) == closed
    validate(e)


@pytest.mark.parametrize("kind,reopened", [("insurance", "active"), ("compute", "pending"), ("compute", "active"), ("loan", "pending")])
def test_reactivated_service_for_a_dead_person_fails_reconciliation(services, kind, reopened):
    s, e = services, services.e
    table, source, closed = prepare_service(s, kind)
    e.lifecycle.settle_death(1, s.client)
    e.store.update(table, source, status=reopened)
    with pytest.raises(EstateError, match="deceased person"):
        e.estate_cases.check_invariants()
    e.store.update(table, source, status=closed)
    validate(e)


@pytest.mark.parametrize("kind", ["insurance", "compute", "loan"])
@pytest.mark.parametrize("change", ["holder", "terms"])
def test_ended_service_keeps_its_original_holder_and_payment_terms(services, kind, change):
    s, e = services, services.e
    table, source, _ = prepare_service(s, kind)
    e.lifecycle.settle_death(1, s.client)
    row = e.store.query_one(f"SELECT * FROM {table} WHERE id=?", (source,))
    if change == "holder":
        field = "borrower_id" if kind == "loan" else "agent_id"
        changed = s.heir
    else:
        field = {"insurance": "premium_cents", "compute": "price_cents", "loan": "amount_cents"}[kind]
        changed = row[field] + 1
    e.store.update(table, source, **{field: changed})
    with pytest.raises(EstateError, match="ended service record changed"):
        e.estate_cases.check_invariants()
    e.store.update(table, source, **{field: row[field]})
    validate(e)


def test_service_closing_survives_full_world_restart_and_exact_replay(tmp_path, monkeypatch, caplog):
    config = civic_config()
    config["checkpoint_dir"] = str(tmp_path / "checkpoints")
    config.setdefault("health", {}).update(premium_cents=40, premium_interval_ticks=1)
    config.setdefault("cognition", {}).update(duration_ticks=1, flash_cost_cents=100,
        initial_distribution={"local": 1.0, "flash": 0.0, "premium": 0.0})
    identities = {}
    draw = Lifecycle._draw

    def forced_death(self, tick, person, mechanism):
        if tick == 1 and person == identities["client"] and mechanism == "mortality":
            return 0.0
        return draw(self, tick, person, mechanism)

    monkeypatch.setattr(Lifecycle, "_draw", forced_death)

    def open_seeded(path, settings, *, replay=False):
        world = _world(path, settings, replay=replay)
        if world.store.tick != 0:
            return world
        e, store = world.economy, world.store
        client = available_adult(world)
        identities["client"] = client
        account = store.query_one("SELECT ac.* FROM agents a JOIN accounts ac ON ac.id=a.checking_account_id WHERE a.id=?", (client,))
        insurer = store.query_one("SELECT id FROM firms WHERE sector='insurance' AND status<>'bankrupt' AND currency_code=? ORDER BY id LIMIT 1", (account["currency_code"],))
        if insurer is None:
            # Declare the initial insurance service using an existing adult and
            # existing cash. Do not create people or an external cash endowment.
            operator = store.scalar("SELECT f.operator_agent_id FROM firm_operations f JOIN agents a ON a.id=f.operator_agent_id "
                "JOIN accounts ac ON ac.id=a.checking_account_id WHERE f.currency_code=? AND f.status IN ('private','listed') "
                "AND a.alive=1 AND ac.balance_cents>=10000 ORDER BY f.id LIMIT 1", (account["currency_code"],))
            assert operator is not None
            e.firms.found_firm(0, operator, "Genesis service insurer", "insurance", opening_capital_cents=10_000)
        executor = ActionExecutor(e)
        s = SimpleNamespace(e=e, client=client, executor=executor, bank=account["bank_id"])
        identities["policy"] = buy_insurance(s)
        identities["subscription"] = act(s, 0, client, type="buy_compute_plan", tier="flash")["subscription_id"]
        application = apply_loan(s)
        officer = store.scalar("SELECT id FROM agents WHERE alive=1 AND role='credit_officer' ORDER BY id LIMIT 1")
        assert officer is not None
        identities["loan"] = act(s, 0, officer, type="approve_loan", application_id=application, term_ticks=60)["loan_id"]
        return world

    source_path = tmp_path / "source-services.db"
    for day in range(1, 4):
        source = open_seeded(source_path, config)
        try:
            asyncio.run(source.step())
            store = source.store
            assert tuple(store.query_one("SELECT status,end_tick FROM insurance_policies WHERE id=?", (identities["policy"],))) == ("cancelled", 1)
            assert store.scalar("SELECT COUNT(*) FROM transactions WHERE kind='insurance_premium' AND memo IN (?,?)",
                (f"new policy agent {identities['client']}", f"premium policy {identities['policy']}")) == 2
            assert store.scalar("SELECT status FROM compute_subscriptions WHERE id=?", (identities["subscription"],)) == "cancelled"
            assert store.scalar("SELECT COUNT(*) FROM compute_subscriptions WHERE agent_id=? AND status IN ('active','pending')", (identities["client"],)) == 0
            assert tuple(store.query_one("SELECT status,outstanding_cents FROM loans WHERE id=?", (identities["loan"],))) == ("paid", 0)
            assert item_for(source.economy, identities["client"], "insurance") is not None
            source.economy.estate_cases.check_invariants()
        finally:
            source.close()
    before = hashlib.sha256(source_path.read_bytes()).hexdigest()
    settings = copy.deepcopy(config)
    settings["replay_source_path"] = str(source_path)
    replay = open_seeded(tmp_path / "replayed-services.db", settings, replay=True)
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
