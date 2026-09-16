"""Currency-separated estate principal, real cash, loss, rollback and replay."""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import random
import sqlite3

import pytest

from engine.core import Economy
from engine.credit import LoanTerms
from engine.estates import EstateError
from engine.ledger import SYS_COMMODITY, SYS_EXTERNAL, SYS_GOV, SYS_LOSS
from engine.lifecycle import Lifecycle
from engine.migrations import registry
from engine.schema import SCHEMA_VERSION
from engine.store import Store
from research.export_bundle import export_bundle, validate_bundle
from research.hashing import HashContractError, canonical_hashes, load_hash_contract
from run_config import load_config
from world.replay_verify import verify_replay

from .conftest import make_agent, make_bank
from .test_semantics17_household_decisions import _world
from .test_semantics18_daily_time import employer


@pytest.fixture
def estate(store):
    config = {"engine_semantics_version": 19, "seed": 1,
              "lifecycle": {"birth_annual_prob": 0, "population_mode": "drift"}}
    store.execute("UPDATE run_meta SET config_json=?", (json.dumps(config),))
    e = Economy(store, config, random.Random(1), random.Random(2))
    e.ensure_system_accounts()
    bank = make_bank(e)
    person, account = make_agent(e, bank, "Owner", cash=100)
    heir, heir_account = make_agent(e, bank, "Beneficiary", cash=0)
    store.insert("social_ties", agent_a=person, agent_b=heir, weight=1)
    e.households.initialize()
    return e, bank, person, account, heir, heir_account


def foreign_bank(e, currency):
    reserve = e.ledger.create_account("bank", None, "reserve", currency_code=currency, opening_cents=100_000)
    equity = e.ledger.create_account("bank", None, "equity", currency_code=currency)
    bank = e.store.insert("banks", name=currency, reserve_account_id=reserve, equity_account_id=equity,
                         risk_policy_json="{}", currency_code=currency, status="open")
    for account in (reserve, equity):
        e.store.update("accounts", account, owner_id=bank)
    return bank


def spent_loan(e, bank, person, account, principal):
    previous = e.ledger.agent_checking_id(person)
    e.store.update("agents", person, checking_account_id=account)
    loan = e.bank.disburse_loan(0, bank, "agent", person,
                              LoanTerms(principal, 0, 30, 30), collateral={"cash": principal})
    assert loan is not None
    currency = e.store.scalar("SELECT currency_code FROM accounts WHERE id=?", (account,))
    e.ledger.transfer(0, account, e.ledger.system_account(SYS_COMMODITY, currency_code=currency), principal)
    e.store.update("agents", person, checking_account_id=previous)
    return loan


def assert_valid(e):
    e.cash_estates.check_invariants()
    e.earned_wages.check_invariants()
    assert e.ledger.reconcile()[0]


def test_foreign_primary_does_not_hide_domestic_wallets_or_net_currencies(estate):
    e, bank, person, account, heir, heir_account = estate
    other_bank = make_bank(e, name="Second USD bank")
    savings = e.ledger.create_account("agent", person, "savings", bank_id=other_bank, opening_cents=200)
    cad_bank = foreign_bank(e, "CAD")
    cad = e.ledger.create_account("agent", person, "fx", currency_code="CAD", opening_cents=100)
    euro = e.ledger.create_account("agent", person, "fx", currency_code="EUR", opening_cents=11)
    usd_first = spent_loan(e, bank, person, account, 450)
    usd_second = spent_loan(e, other_bank, person, account, 50)
    cad_loan = spent_loan(e, cad_bank, person, cad, 80)
    e.store.update("agents", person, checking_account_id=cad)
    before = {b: dict(e.bank.get(b)) for b in (bank, other_bank, cad_bank)}
    reserves = {b: e.ledger.balance(row["reserve_account_id"]) for b, row in before.items()}
    e.lifecycle.settle_death(1, person)
    claims = {row["loan_id"]: row for row in e.store.query("SELECT * FROM estate_loan_claims")}
    assert (claims[usd_first]["paid_cents"], claims[usd_first]["written_off_cents"]) == (300, 150)
    assert (claims[usd_second]["paid_cents"], claims[usd_second]["written_off_cents"]) == (0, 50)
    assert (claims[cad_loan]["paid_cents"], claims[cad_loan]["written_off_cents"]) == (80, 0)
    for b, payment, loss in ((bank, 300, 150), (other_bank, 0, 50), (cad_bank, 80, 0)):
        assert e.ledger.balance(before[b]["reserve_account_id"]) == reserves[b] + payment
        assert e.ledger.balance(before[b]["equity_account_id"]) == -loss
    assert e.ledger.balance(e.ledger.system_account(SYS_LOSS)) == 200
    assert e.ledger.balance(heir_account) == 0
    inherited = {row["currency_code"]: row["total"] for row in e.store.query(
        "SELECT currency_code,SUM(balance_cents) AS total FROM accounts WHERE owner_type='agent' AND owner_id=? GROUP BY currency_code", (heir,))}
    assert inherited == {"USD": 0, "CAD": 20, "EUR": 11}
    assert all(e.ledger.balance(a) == 0 for a in (account, savings, cad, euro))
    assert e.store.scalar("SELECT COUNT(*) FROM estate_cash_assets") == 4
    assert e.store.scalar("SELECT SUM(outstanding_cents) FROM loans") == 0
    assert_valid(e)


@pytest.mark.parametrize("cash,principal", [(0, 0), (0, 70), (30, 70), (70, 70), (71, 70), (100, 0)])
@pytest.mark.parametrize("has_heir", [False, True])
def test_cash_principal_waterfall_known_answers(estate, cash, principal, has_heir):
    e, bank, person, account, _, heir_account = estate
    e.ledger.transfer(0, account, e.ledger.system_account(SYS_COMMODITY), 100)
    if cash:
        e.ledger.transfer(0, e.ledger.system_account(SYS_EXTERNAL), account, cash)
    if not has_heir:
        e.store.execute("DELETE FROM social_ties")
    if principal:
        spent_loan(e, bank, person, account, principal)
    government = e.ledger.system_account(SYS_GOV)
    e.lifecycle.settle_death(1, person)
    assert e.ledger.balance(account) == 0
    assert e.ledger.balance(heir_account if has_heir else government) == max(0, cash-principal)
    assert e.ledger.balance(e.bank.get(bank)["equity_account_id"]) == -max(0, principal-cash)
    asset = e.store.query_one("SELECT * FROM estate_cash_assets")
    assert (asset["opening_cents"], asset["loan_paid_cents"], asset["residual_cents"]) == (cash, min(cash, principal), max(0, cash-principal))
    settled = canonical_hashes(e.store)["authoritative_sha256"]
    e.lifecycle.settle_death(2, person)
    assert canonical_hashes(e.store)["authoritative_sha256"] == settled
    assert_valid(e)


def test_foreign_escheat_uses_its_own_system_currency_and_does_not_consume_claims(estate):
    e, _, person, _, _, _ = estate
    e.store.execute("DELETE FROM social_ties")
    e.ledger.create_account("agent", person, "fx", currency_code="CAD", opening_cents=75)
    # Non-cash rights are not silently consumed as spendable estate cash.
    noncash = e.ledger.create_account("agent", person, "other_receivable", opening_cents=33)
    e.lifecycle.settle_death(1, person)
    assert e.ledger.balance(e.ledger.system_account(SYS_GOV, currency_code="CAD")) == 75
    assert e.ledger.balance(noncash) == 33
    assert e.store.scalar("SELECT COUNT(*) FROM estate_cash_assets WHERE account_id=?", (noncash,)) == 0
    assert_valid(e)


def test_inherited_deposits_settle_reserves_between_banks(estate):
    e, bank, person, _, _, heir_account = estate
    other = make_bank(e, name="Beneficiary bank")
    e.store.update("accounts", heir_account, bank_id=other)
    from_reserve, to_reserve = (e.bank.get(b)["reserve_account_id"] for b in (bank, other))
    initial = (e.ledger.balance(from_reserve), e.ledger.balance(to_reserve))
    e.lifecycle.settle_death(1, person)
    assert e.ledger.balance(heir_account) == 100
    assert e.ledger.balance(from_reserve) == initial[0] - 100
    assert e.ledger.balance(to_reserve) == initial[1] + 100
    transaction = e.store.scalar("SELECT transaction_id FROM estate_cash_transfers")
    assert e.store.scalar("SELECT COUNT(*) FROM ledger_entries WHERE txn_id=?", (transaction,)) == 4
    assert_valid(e)


def test_equal_social_ties_use_person_id_and_self_ties_cannot_inherit(estate):
    e, bank, person, _, heir, heir_account = estate
    other, _ = make_agent(e, bank, "Equal tie", cash=0)
    e.store.insert("social_ties", agent_a=person, agent_b=other, weight=1)
    e.store.insert("social_ties", agent_a=person, agent_b=person, weight=100)
    e.lifecycle.settle_death(1, person)
    assert e.store.scalar("SELECT heir_id FROM cash_estates") == heir
    assert e.ledger.balance(heir_account) == 100
    assert_valid(e)


def test_collectible_wages_repay_creditors_while_unpaid_wages_remain_inherited_claims(estate):
    e, bank, person, account, heir, heir_account = estate
    _, firm_account, _ = employer(e, bank, person, cash=400)
    e.daily_time.prepare_day(1)
    assert e.store.scalar("SELECT SUM(earned_cents) FROM wage_accruals") == 1000
    spent_loan(e, bank, person, account, 600)
    e.lifecycle.settle_death(1, person)
    assert e.store.scalar("SELECT opening_cents FROM estate_cash_assets") == 500
    claim = e.store.query_one("SELECT * FROM estate_loan_claims")
    assert (claim["paid_cents"], claim["written_off_cents"]) == (500, 100)
    assert e.ledger.balance(firm_account) == 0 and e.ledger.balance(heir_account) == 0
    holder = e.store.query_one("SELECT * FROM wage_claim_holders WHERE ended_tick IS NULL")
    assert holder["owner_id"] == heir
    assert e.ledger.balance(holder["receivable_account_id"]) == 600
    assert_valid(e)


@pytest.mark.parametrize("failure", ["chargeoff", "after_cash"])
def test_any_death_failure_rolls_back_cash_creditor_loss_wages_and_receipts(estate, monkeypatch, failure):
    e, bank, person, account, _, _ = estate
    employer(e, bank, person, cash=40)
    e.daily_time.prepare_day(1)
    spent_loan(e, bank, person, account, 200)
    before = canonical_hashes(e.store)["authoritative_sha256"]
    if failure == "chargeoff":
        original = e.ledger.post
        def fail(tick, kind, *args, **kwargs):
            if kind == "estate_loan_loss":
                raise RuntimeError("injected loss failure")
            return original(tick, kind, *args, **kwargs)
        monkeypatch.setattr(e.ledger, "post", fail)
    else:
        def fail(*args, **kwargs):
            raise RuntimeError("injected later death failure")
        monkeypatch.setattr(e.lifecycle, "_transfer_shares_on_death", fail)
    with pytest.raises(RuntimeError, match="injected"):
        e.lifecycle.settle_death(1, person)
    assert canonical_hashes(e.store)["authoritative_sha256"] == before
    assert e.store.scalar("SELECT alive FROM agents WHERE id=?", (person,)) == 1
    assert e.store.scalar("SELECT COUNT(*) FROM cash_estates") == 0
    assert_valid(e)


def test_invalid_creditor_currency_aborts_death_before_any_transfer(estate):
    e, bank, person, account, _, _ = estate
    spent_loan(e, bank, person, account, 200)
    foreign = foreign_bank(e, "CAD")
    e.store.update("banks", bank, equity_account_id=e.bank.get(foreign)["equity_account_id"])
    before = canonical_hashes(e.store)["authoritative_sha256"]
    with pytest.raises(EstateError, match="creditor accounts"):
        e.lifecycle.settle_death(1, person)
    assert canonical_hashes(e.store)["authoritative_sha256"] == before


def test_receipts_are_immutable_and_ledger_tampering_is_detected(estate):
    e, bank, person, account, _, _ = estate
    spent_loan(e, bank, person, account, 200)
    e.lifecycle.settle_death(1, person)
    for table, field in (("cash_estates", "tick"), ("estate_cash_assets", "opening_cents"),
                         ("estate_loan_claims", "principal_cents"), ("estate_cash_transfers", "amount_cents")):
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            e.store.execute(f"UPDATE {table} SET {field}={field}+1")
        with pytest.raises(sqlite3.IntegrityError, match="permanent"):
            e.store.execute(f"DELETE FROM {table}")
    with pytest.raises(sqlite3.IntegrityError, match="permanent"):
        e.store.execute("UPDATE cash_estates SET completed_event_id=NULL")
    transaction = e.store.scalar("SELECT chargeoff_transaction_id FROM estate_loan_claims")
    e.store.execute("UPDATE ledger_entries SET delta_cents=delta_cents*2 WHERE txn_id=?", (transaction,))
    with pytest.raises(EstateError, match="bank loss"):
        e.cash_estates.check_invariants()


def test_negative_cash_is_disclosed_and_not_netted_with_another_wallet(estate):
    e, _, person, account, _, heir_account = estate
    deficit = e.ledger.create_account("agent", person, "fx")
    e.ledger.transfer(0, deficit, e.ledger.system_account(SYS_COMMODITY), 30)
    e.lifecycle.settle_death(1, person)
    assert e.ledger.balance(account) == 0 and e.ledger.balance(heir_account) == 100
    assert e.ledger.balance(deficit) == -30
    assert e.store.scalar("SELECT opening_cents FROM estate_cash_assets WHERE account_id=?", (deficit,)) == -30
    # A later refund is outside the death-time component. History remains true.
    e.ledger.transfer(2, e.ledger.system_account(SYS_EXTERNAL), account, 5)
    assert_valid(e)


def test_estate_receipts_are_hashed_exported_and_cannot_hide_under_an_older_contract(estate, tmp_path):
    e, bank, person, account, _, _ = estate
    spent_loan(e, bank, person, account, 200)
    e.lifecycle.settle_death(1, person)
    hashes = canonical_hashes(e.store)
    assert hashes["contract_id"] == "hash-contract-v6"
    assert hashes["tables"]["cash_estates"]["row_count"] == 1
    with pytest.raises(HashContractError, match="requires hash-contract-v6"):
        canonical_hashes(e.store, load_hash_contract("research/hash-contract-v5.json"))
    manifest = validate_bundle(export_bundle(e.store, tmp_path / "exports"))
    assert manifest["tables"]["estate_loan_claims"]["row_count"] == 1
    e.store.execute("UPDATE run_meta SET config_json=?", (json.dumps({"engine_semantics_version": 18}),))
    with pytest.raises(HashContractError, match="populated estate"):
        canonical_hashes(e.store)


def test_semantics18_retains_its_primary_wallet_and_historical_loss_behavior(estate):
    e, bank, person, account, _, heir_account = estate
    e.lifecycle.engine_semantics_version = 18
    e.engine_semantics_version = 18
    e.store.execute("UPDATE run_meta SET config_json=?", (json.dumps({"engine_semantics_version": 18}),))
    spent_loan(e, bank, person, account, 200)
    foreign = e.ledger.create_account("agent", person, "fx", currency_code="CAD")
    e.store.update("agents", person, checking_account_id=foreign)
    e.lifecycle.settle_death(1, person)
    assert e.ledger.balance(heir_account) == 100
    assert e.store.scalar("SELECT outstanding_cents FROM loans") == 200
    assert e.ledger.balance(e.bank.get(bank)["equity_account_id"]) == 0
    assert e.store.scalar("SELECT COUNT(*) FROM cash_estates") == 0
    assert canonical_hashes(e.store)["contract_id"] == "hash-contract-v5"


def test_real_rehearsal_resumes_and_replays_death_receipts_exactly(tmp_path, monkeypatch, caplog):
    config = load_config("runs/estate-cash-rehearsal.yaml")
    config["checkpoint_dir"] = str(tmp_path / "checkpoints")
    config["households"]["scheduled_births"] = []
    # A deterministic mortality boundary fixture, applied to source and replay;
    # it is not a claim about the configured population's mortality calibration.
    original = Lifecycle._draw
    def draw(self, tick, agent_id, mechanism):
        if tick == 1 and agent_id == 11 and mechanism == "mortality":
            return 0.0
        return original(self, tick, agent_id, mechanism)
    monkeypatch.setattr(Lifecycle, "_draw", draw)
    path = tmp_path / "source.db"
    source = _world(path, config)
    try:
        asyncio.run(source.step())
        assert source.store.scalar("SELECT COUNT(*) FROM cash_estates") >= 1
    finally:
        source.close()
    source = _world(path, config)
    try:
        asyncio.run(source.step())
        assert_valid(source.economy)
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
        assert_valid(replay.economy)
        assert not any("action.execution.failed" in record.message for record in caplog.records)
    finally:
        replay.close()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_schema23_semantics18_source_replays_without_being_upgraded(tmp_path, monkeypatch):
    config = load_config("runs/daily-time-rehearsal.yaml")
    config["checkpoint_dir"] = str(tmp_path / "checkpoints")
    migrations = registry._MIGRATIONS
    monkeypatch.setattr(registry, "_MIGRATIONS", tuple(m for m in migrations if m.version < 24))
    path = tmp_path / "old.db"
    source = _world(path, config)
    try:
        source.store.execute("UPDATE run_meta SET schema_version=23")
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
        replay.store.insert("cash_estates", deceased_agent_id=11, tick=1,
            policy="positive_cash_bank_principal_v1", cash_account_count=0, loan_count=0)
        assert "cash_estates" in verify_replay(path, replay.store.path)["differences"]
    finally:
        replay.close()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_schema24_failed_migration_rolls_back_and_successful_reopen_is_additive(tmp_path, monkeypatch):
    path = tmp_path / "schema23.db"
    migrations = registry._MIGRATIONS
    monkeypatch.setattr(registry, "_MIGRATIONS", tuple(m for m in migrations if m.version < 24))
    store = Store(str(path))
    store.init_run_meta("old", 1, {"engine_semantics_version": 18})
    store.execute("UPDATE run_meta SET schema_version=23")
    actor = store.insert("agents", name="Existing", kind="citizen", age=42)
    store.close()
    migration = next(m for m in migrations if m.version == 24)
    broken = registry.Migration.create(24, migration.name, migration.sql + "\nINVALID SQL;", verify=migration.verify)
    monkeypatch.setattr(registry, "_MIGRATIONS", tuple(broken if m.version == 24 else m for m in migrations))
    with pytest.raises(registry.MigrationError):
        Store(str(path))
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT schema_version FROM run_meta").fetchone()[0] == 23
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='cash_estates'").fetchone() is None
        assert conn.execute("SELECT age FROM agents WHERE id=?", (actor,)).fetchone()[0] == 42
    monkeypatch.setattr(registry, "_MIGRATIONS", migrations)
    for _ in range(2):
        store = Store(str(path))
        try:
            assert store.scalar("SELECT schema_version FROM run_meta") == SCHEMA_VERSION
            assert store.scalar("SELECT COUNT(*) FROM cash_estates") == 0
            assert store.scalar("SELECT age FROM agents WHERE id=?", (actor,)) == 42
        finally:
            store.close()
