"""Estate cash arrives once, pays recorded claims and reaches actual heirs."""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import random
import sqlite3

import pytest

from engine.core import Economy
from engine.estates import EstateError
from engine.ledger import Leg, SYS_COMMODITY, SYS_EXTERNAL, SYS_GOV, SYS_LOSS
from engine.lifecycle import Lifecycle
from engine.migrations import registry
from engine.schema import SCHEMA_VERSION
from engine.store import Store
from research.export_bundle import export_bundle, validate_bundle
from research.hashing import HashContractError, canonical_hashes, load_hash_contract
from run_config import load_config
from world.replay_verify import verify_replay

from .conftest import make_agent, make_bank
from .test_semantics18_daily_time import employer
from .test_semantics19_estate_cash import foreign_bank, spent_loan
from .test_semantics17_household_decisions import _world
from .test_semantics13_construction import _config as construction_config, _owner, _propose, _permit_clerk


@pytest.fixture
def estate_case(store):
    config = {"engine_semantics_version": 20, "seed": 1,
              "lifecycle": {"birth_annual_prob": 0, "population_mode": "drift"},
              "family_decisions": {"scripted_matching": False}}
    store.execute("UPDATE run_meta SET config_json=?", (json.dumps(config),))
    e = Economy(store, config, random.Random(1), random.Random(2))
    e.ensure_system_accounts()
    store.insert("regions", id=1, region_key="region-1", name="Home", currency_code="USD",
                 population_target=10, specialization_json="{}", x=0, y=0, legal_ruleset="test")
    bank = make_bank(e)
    person, wallet = make_agent(e, bank, "Owner", region_id=1, cash=100)
    heir, heir_wallet = make_agent(e, bank, "Heir", region_id=1, cash=0)
    store.insert("social_ties", agent_a=person, agent_b=heir, weight=1)
    e.households.initialize()
    return e, bank, person, wallet, heir, heir_wallet


def validate(e):
    e.estate_cases.check_invariants()
    e.business_control.check_invariants()
    e.earned_wages.check_invariants()
    assert e.ledger.reconcile()[0]
    assert e.estate_cases._pending is None


@pytest.mark.parametrize("principal", [0, 30, 100, 170])
@pytest.mark.parametrize("has_heir", [False, True])
def test_known_cash_waterfalls_and_duplicate_death(estate_case, principal, has_heir):
    e, bank, person, wallet, _, heir_wallet = estate_case
    if principal:
        spent_loan(e, bank, person, wallet, principal)
    if not has_heir:
        e.store.execute("DELETE FROM social_ties")
    e.lifecycle.settle_death(1, person)
    assert e.ledger.balance(wallet) == 0
    assert e.ledger.balance(heir_wallet if has_heir else e.ledger.system_account(SYS_GOV)) == max(0, 100-principal)
    assert e.ledger.balance(e.bank.get(bank)["equity_account_id"]) == -max(0, principal-100)
    assert e.store.scalar("SELECT COUNT(*) FROM cash_estates") == 0
    before = canonical_hashes(e.store)["authoritative_sha256"]
    e.lifecycle.settle_death(2, person)
    assert canonical_hashes(e.store)["authoritative_sha256"] == before
    validate(e)


def test_partner_and_children_share_cash_and_securities_without_shared_debt(estate_case):
    e, bank, person, wallet, partner, partner_wallet = estate_case
    decision = e.families.propose(0, person, "partnership", "pair", partner_id=partner)["household_decision_id"]
    e.families.respond(0, partner, decision, "accept")
    children = [e.households.birth(tick, person) for tick in (1, 2)]
    firm = e.firms.found_firm(1, person, "Estate firm", "manufacturing", shares=1001)
    # 100 cents and 1001 shares use independent largest remainders.
    e.lifecycle.settle_death(3, person)
    beneficiaries = e.store.query("SELECT agent_id,basis,weight FROM estate_beneficiaries ORDER BY agent_id")
    assert [tuple(row) for row in beneficiaries] == [(partner, "partner", 1)] + [(child, "child", 1) for child in children]
    assert e.ledger.balance(partner_wallet) == 34
    assert [e.ledger.balance(e.ledger.agent_checking_id(child)) for child in children] == [33, 33]
    assert [e.exchange.shares_held(firm, "agent", owner) for owner in [partner, *children]] == [334, 334, 333]
    assert e.ledger.balance(wallet) == 0
    assert e.business_control.operator_at(firm) == partner
    assert e.store.scalar("SELECT COUNT(*) FROM loans WHERE borrower_type='agent' AND borrower_id=?", (partner,)) == 0
    validate(e)


def test_late_cash_reverses_bank_loss_before_residual_inheritance(estate_case):
    e, bank, person, wallet, _, heir_wallet = estate_case
    loan = spent_loan(e, bank, person, wallet, 170)
    reserve, equity = (e.bank.get(bank)[key] for key in ("reserve_account_id", "equity_account_id"))
    reserve_before = e.ledger.balance(reserve)
    e.lifecycle.settle_death(1, person)
    assert e.ledger.balance(equity) == -70
    source = e.ledger.system_account(SYS_EXTERNAL)
    original = e.ledger.transfer(2, source, wallet, 20, kind="late_refund")
    assert e.ledger.balance(reserve) == reserve_before + 120
    assert e.ledger.balance(equity) == -50
    assert e.ledger.balance(e.ledger.system_account(SYS_LOSS)) == 50
    assert e.store.scalar("SELECT status FROM loans WHERE id=?", (loan,)) == "default"
    e.ledger.transfer(3, source, wallet, 80, kind="late_refund")
    assert e.ledger.balance(reserve) == reserve_before + 170
    assert e.ledger.balance(equity) == e.ledger.balance(e.ledger.system_account(SYS_LOSS)) == 0
    assert e.ledger.balance(heir_wallet) == 30 and e.ledger.balance(wallet) == 0
    assert e.store.scalar("SELECT status FROM loans WHERE id=?", (loan,)) == "paid"
    assert e.store.scalar("SELECT received_cents FROM estate_receipts WHERE origin_transaction_id=?", (original,)) == 20
    assert e.store.scalar("SELECT COUNT(*) FROM estate_claim_losses") == 1
    validate(e)


def test_currency_priority_and_contract_receipts_do_not_spend_the_heirs_cash(estate_case):
    e, bank, person, wallet, heir, heir_wallet = estate_case
    e.ledger.transfer(0, e.ledger.system_account(SYS_EXTERNAL), heir_wallet, 40)
    cad_bank = foreign_bank(e, "CAD")
    cad = e.ledger.create_account("agent", person, "fx", currency_code="CAD", opening_cents=90)
    spent_loan(e, bank, person, wallet, 150)
    cad_loan = spent_loan(e, cad_bank, person, cad, 40)
    # A partial personal contract stays collectible against the estate only.
    obligation = e.store.insert("obligations", contract_id=1, clause_id=1, obligation_type="payment",
        obligor_type="agent", obligor_id=person, obligee_type="agent", obligee_id=heir,
        due_tick=30, amount_cents=20, currency_code="USD")
    e.lifecycle.settle_death(1, person)
    assert e.ledger.balance(heir_wallet) == 40
    assert e.store.scalar("SELECT status FROM obligations WHERE id=?", (obligation,)) == "pending"
    assert e.store.scalar("SELECT status FROM loans WHERE id=?", (cad_loan,)) == "paid"
    assert e.store.scalar("SELECT SUM(balance_cents) FROM accounts WHERE owner_type='agent' AND owner_id=? AND currency_code='CAD'", (heir,)) == 50
    e.ledger.transfer(2, e.ledger.system_account(SYS_EXTERNAL), wallet, 60)
    assert e.ledger.balance(heir_wallet) == 50  # 50 principal, then 10 contract cents.
    assert e.store.scalar("SELECT status FROM obligations WHERE id=?", (obligation,)) == "pending"
    e.ledger.transfer(3, e.ledger.system_account(SYS_EXTERNAL), wallet, 15)
    assert e.ledger.balance(heir_wallet) == 65  # remaining 10 contract, 5 inheritance.
    assert e.store.scalar("SELECT status FROM obligations WHERE id=?", (obligation,)) == "performed"
    validate(e)


def test_late_receipt_follows_two_generations_of_recorded_estates(estate_case):
    e, bank, person, wallet, heir, heir_wallet = estate_case
    final, final_wallet = make_agent(e, bank, "Next heir", cash=0)
    e.households.register_person(0, final, "genesis")
    e.store.insert("social_ties", agent_a=heir, agent_b=final, weight=2)
    e.lifecycle.settle_death(1, person)
    e.lifecycle.settle_death(2, heir)
    assert e.ledger.balance(final_wallet) == 100
    e.ledger.transfer(3, e.ledger.system_account(SYS_EXTERNAL), wallet, 101)
    assert e.ledger.balance(wallet) == e.ledger.balance(heir_wallet) == 0
    assert e.ledger.balance(final_wallet) == 201
    assert e.store.scalar("SELECT COUNT(*) FROM estate_receipts WHERE tick=3") == 2
    validate(e)


def test_unpaid_wages_remain_a_nominee_claim_and_only_real_cash_is_distributed(estate_case):
    e, bank, person, wallet, _, heir_wallet = estate_case
    _, firm_wallet, _ = employer(e, bank, person, cash=0)
    e.daily_time.prepare_day(1)
    claim = e.store.query_one("SELECT * FROM wage_claims")
    assert claim["accrued_cents"] == 1000
    e.lifecycle.settle_death(2, person)
    assert e.ledger.balance(heir_wallet) == 100
    holder = e.earned_wages.holder(claim["id"])
    assert holder["owner_id"] == person
    assert e.ledger.balance(holder["receivable_account_id"]) == 1000
    e.ledger.transfer(3, e.ledger.system_account(SYS_EXTERNAL), firm_wallet, 1000)
    assert e.earned_wages.settle(3, claim["id"]) == 1000
    assert e.ledger.balance(heir_wallet) == 1100
    assert e.ledger.balance(wallet) == e.ledger.balance(holder["receivable_account_id"]) == 0
    assert e.store.scalar("SELECT COUNT(*) FROM estate_receipts WHERE origin_transaction_id IN (SELECT transaction_id FROM wage_settlements)") == 1
    validate(e)


def test_failed_late_distribution_rolls_back_original_payment_and_hook_recovers(estate_case, monkeypatch):
    e, _, person, wallet, _, heir_wallet = estate_case
    e.lifecycle.settle_death(1, person)
    before = canonical_hashes(e.store)["authoritative_sha256"]
    original = e.estate_cases._disburse
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected after estate disbursement")
    monkeypatch.setattr(e.estate_cases, "_disburse", fail)
    with pytest.raises(RuntimeError, match="injected"):
        e.ledger.transfer(2, e.ledger.system_account(SYS_EXTERNAL), wallet, 55)
    assert canonical_hashes(e.store)["authoritative_sha256"] == before
    assert e.estate_cases._pending is None
    monkeypatch.setattr(e.estate_cases, "_disburse", original)
    e.ledger.transfer(2, e.ledger.system_account(SYS_EXTERNAL), wallet, 55)
    assert e.ledger.balance(heir_wallet) == 155
    validate(e)


def test_negative_wallet_receipts_record_absorption_and_net_credits_only(estate_case):
    e, _, person, wallet, _, heir_wallet = estate_case
    e.ledger.transfer(0, wallet, e.ledger.system_account(SYS_COMMODITY), 150)
    e.lifecycle.settle_death(1, person)
    assert e.ledger.balance(wallet) == -50
    e.ledger.transfer(2, e.ledger.system_account(SYS_EXTERNAL), wallet, 30)
    assert e.ledger.balance(heir_wallet) == 0
    original = e.ledger.post(3, "net_credit", [Leg(wallet, 100), Leg(wallet, -20),
                                             Leg(e.ledger.system_account(SYS_EXTERNAL), -80)])
    assert e.ledger.balance(heir_wallet) == 60 and e.ledger.balance(wallet) == 0
    assert [tuple(row) for row in e.store.query("SELECT received_cents,available_cents FROM estate_receipts ORDER BY id")] == [(30, 0), (80, 60)]
    assert e.store.scalar("SELECT origin_transaction_id FROM estate_receipts ORDER BY id DESC LIMIT 1") == original
    validate(e)


def test_estate_records_are_immutable_and_self_beneficiaries_are_rejected(estate_case):
    e, _, person, _, _, _ = estate_case
    e.lifecycle.settle_death(1, person)
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        e.store.execute("UPDATE estate_receipts SET received_cents=999")
    with pytest.raises(sqlite3.IntegrityError, match="permanent"):
        e.store.execute("DELETE FROM estate_beneficiaries")
    with pytest.raises(EstateError, match="repeated"):
        e.estate_cases.open(1, person)
    validate(e)


def test_queued_receipts_attribute_a_deficit_to_the_credit_that_absorbed_it(estate_case):
    e, bank, person, wallet, heir, heir_wallet = estate_case
    next_person, next_wallet = make_agent(e, bank, "Final recipient", cash=0)
    e.households.register_person(0, next_person, "genesis")
    e.store.insert("social_ties", agent_a=heir, agent_b=next_person, weight=2)
    savings = e.ledger.create_account("agent", person, "savings", bank_id=bank)
    e.lifecycle.settle_death(1, person)
    e.ledger.transfer(1, heir_wallet, e.ledger.system_account(SYS_COMMODITY), 150)
    e.lifecycle.settle_death(2, heir)
    e.ledger.post(3, "two_wallet_refund", [Leg(wallet, 100), Leg(savings, 100),
                                          Leg(e.ledger.system_account(SYS_EXTERNAL), -200)])
    assert e.ledger.balance(next_wallet) == 150
    assert [tuple(row) for row in e.store.query("SELECT received_cents,post_balance_cents,available_cents FROM estate_receipts "
        "WHERE source_account_id=? AND tick=3 ORDER BY id", (heir_wallet,))] == [(100, 50, 50), (100, 150, 100)]
    validate(e)


def test_case_inventory_is_exported_and_cannot_be_hidden_under_v6(estate_case, tmp_path):
    e, bank, person, wallet, _, _ = estate_case
    spent_loan(e, bank, person, wallet, 170)
    e.lifecycle.settle_death(1, person)
    e.ledger.transfer(2, e.ledger.system_account(SYS_EXTERNAL), wallet, 80)
    hashes = canonical_hashes(e.store)
    assert hashes["contract_id"] == "hash-contract-v7"
    assert hashes["tables"]["estate_receipts"]["row_count"] == 2
    with pytest.raises(HashContractError, match="requires hash-contract-v7"):
        canonical_hashes(e.store, load_hash_contract("research/hash-contract-v6.json"))
    manifest = validate_bundle(export_bundle(e.store, tmp_path / "export"))
    assert manifest["tables"]["estate_cases"]["row_count"] == 1
    assert manifest["tables"]["estate_disbursements"]["row_count"] == 3
    e.store.execute("UPDATE run_meta SET config_json=?", (json.dumps({"engine_semantics_version": 19}),))
    with pytest.raises(HashContractError, match="populated asset succession"):
        canonical_hashes(e.store)


def test_case_rehearsal_resumes_and_replays_without_rewriting_source(tmp_path, monkeypatch, caplog):
    config = load_config("runs/estate-cash-rehearsal.yaml")
    config["engine_semantics_version"] = 20
    config["checkpoint_dir"] = str(tmp_path / "checkpoints")
    config["households"]["scheduled_births"] = []
    original = Lifecycle._draw
    def draw(self, tick, agent_id, mechanism):
        if tick == 1 and agent_id == 11 and mechanism == "mortality":
            return 0.0
        return original(self, tick, agent_id, mechanism)
    monkeypatch.setattr(Lifecycle, "_draw", draw)
    path = tmp_path / "source.db"
    for _ in range(2):
        source = _world(path, config)
        try:
            asyncio.run(source.step())
            assert source.store.scalar("SELECT COUNT(*) FROM estate_cases") >= 1
            validate(source.economy)
        finally:
            source.close()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    replay_config = copy.deepcopy(config)
    replay_config["replay_source_path"] = str(path)
    replay = _world(tmp_path / "replay.db", replay_config, replay=True)
    try:
        for _ in range(2):
            asyncio.run(replay.step())
        proof = verify_replay(path, replay.store.path)
        assert proof["exact"], proof["differences"]
        validate(replay.economy)
        assert not any("action.execution.failed" in record.message for record in caplog.records)
    finally:
        replay.close()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_schema25_migration_rolls_back_and_preserves_existing_runs(tmp_path, monkeypatch):
    path = tmp_path / "schema24.db"
    migrations = registry._MIGRATIONS
    monkeypatch.setattr(registry, "_MIGRATIONS", tuple(m for m in migrations if m.version < 25))
    store = Store(str(path))
    store.init_run_meta("old", 1, {"engine_semantics_version": 19})
    store.execute("UPDATE run_meta SET schema_version=24")
    actor = store.insert("agents", name="Existing", kind="citizen", age=42)
    store.close()
    migration = next(m for m in migrations if m.version == 25)
    broken = registry.Migration.create(25, migration.name, migration.sql + "\nINVALID SQL;", verify=migration.verify)
    monkeypatch.setattr(registry, "_MIGRATIONS", tuple(broken if m.version == 25 else m for m in migrations))
    with pytest.raises(registry.MigrationError):
        Store(str(path))
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT schema_version FROM run_meta").fetchone()[0] == 24
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='estate_cases'").fetchone() is None
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='project_interest_lots'").fetchone() is None
        assert conn.execute("SELECT age FROM agents WHERE id=?", (actor,)).fetchone()[0] == 42
    monkeypatch.setattr(registry, "_MIGRATIONS", migrations)
    for _ in range(2):
        store = Store(str(path))
        try:
            assert store.scalar("SELECT schema_version FROM run_meta") == SCHEMA_VERSION
            assert store.scalar("SELECT COUNT(*) FROM estate_cases") == 0
            assert store.scalar("SELECT COUNT(*) FROM project_interest_lots") == 0
            assert store.scalar("SELECT COUNT(*) FROM project_stewardships") == 0
            assert store.scalar("SELECT age FROM agents WHERE id=?", (actor,)) == 42
        finally:
            store.close()


def test_real_construction_refund_keeps_the_contributor_and_routes_the_deceased_wallet(tmp_path):
    config = construction_config(semantics=20)
    config.setdefault("households", {})["scheduled_births"] = []
    world = _world(tmp_path / "refund.db", config)
    try:
        e = world.economy
        owner = _owner(world)
        donor = e.store.query_one("SELECT a.*,ac.balance_cents FROM agents a JOIN accounts ac ON ac.id=a.checking_account_id "
            "WHERE a.alive=1 AND a.age>=18 AND a.id<>? AND a.region_id=? AND ac.balance_cents>=1200 ORDER BY a.id LIMIT 1",
            (owner["id"], owner["region_id"]))
        assert donor is not None
        e.store.execute("DELETE FROM social_ties WHERE agent_a=? OR agent_b=?", (donor["id"], donor["id"]))
        e.store.insert("social_ties", agent_a=donor["id"], agent_b=owner["id"], weight=10)
        proposed = _propose(world, owner)
        assert proposed["ok"], proposed
        project = proposed["project_id"]
        executor = world.runtime.executor
        permit = executor.execute_action(2, owner["id"], {"type": "apply_construction_permit",
            "project_id": project, "dedupe_key": "refund-permit-0001"})
        assert permit["ok"], permit
        approved = executor.execute_action(3, _permit_clerk(world, owner["region_id"]), {
            "type": "decide_construction_permit", "case_id": permit["permit_case_id"],
            "decision": "approve", "reason_code": "requirements_verified", "dedupe_key": "refund-approval-0001"})
        assert approved["ok"], approved
        funded = executor.execute_action(4, donor["id"], {"type": "contribute_construction_funding",
            "project_id": project, "amount_cents": 1200, "dedupe_key": "refund-funding-0001"})
        assert funded["ok"], funded
        e.lifecycle.settle_death(5, donor["id"])
        before = e.ledger.balance(owner["checking_account_id"])
        cancelled = executor.execute_action(6, owner["id"], {"type": "cancel_construction", "project_id": project,
            "reason_code": "owner_cancelled", "dedupe_key": "refund-cancel-0001"})
        assert cancelled["ok"], cancelled
        assert cancelled["refund_cents"] == 1200
        refund = e.store.query_one("SELECT * FROM construction_contributions WHERE project_id=? AND contribution_type='refund'", (project,))
        assert refund["actor_agent_id"] == donor["id"]
        assert refund["source_account_id"] == donor["checking_account_id"]
        receipt = e.store.query_one("SELECT * FROM estate_receipts WHERE origin_transaction_id=?", (refund["transaction_id"],))
        assert receipt is not None and receipt["received_cents"] == 1200
        assert e.ledger.balance(donor["checking_account_id"]) == 0
        assert e.ledger.balance(owner["checking_account_id"]) == before + 1200
        validate(e)
    finally:
        world.close()


def test_invalid_creditor_currency_rejects_the_entire_death(estate_case):
    e, bank, person, wallet, _, _ = estate_case
    spent_loan(e, bank, person, wallet, 170)
    e.store.update("accounts", e.bank.get(bank)["equity_account_id"], currency_code="CAD")
    before = canonical_hashes(e.store)["authoritative_sha256"]
    with pytest.raises(EstateError, match="wrong identity or currency"):
        e.lifecycle.settle_death(1, person)
    assert canonical_hashes(e.store)["authoritative_sha256"] == before
    assert e.estate_cases._pending is None


def test_personal_service_and_pending_requests_end_without_binding_a_survivor(estate_case):
    e, bank, person, _, heir, _ = estate_case
    service = e.store.insert("obligations", contract_id=1, clause_id=1, obligation_type="service",
        obligor_type="agent", obligor_id=person, obligee_type="agent", obligee_id=heir, due_tick=30)
    application = e.store.insert("loan_applications", tick=0, bank_id=bank, borrower_type="agent",
        borrower_id=person, amount_cents=100, purpose="personal")
    e.lifecycle.settle_death(1, person)
    assert e.store.scalar("SELECT status FROM obligations WHERE id=?", (service,)) == "cancelled"
    assert e.store.scalar("SELECT status FROM loan_applications WHERE id=?", (application,)) == "expired"
    assert e.store.scalar("SELECT COUNT(*) FROM estate_items WHERE kind IN ('personal_obligation','loan_application') AND disposition='extinguished'") == 2
    assert e.store.scalar("SELECT COUNT(*) FROM obligations WHERE obligor_type='agent' AND obligor_id=?", (heir,)) == 0
    validate(e)
