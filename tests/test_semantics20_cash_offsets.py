"""Cash deficits settle within their estate and currency before inheritance."""
import asyncio
import copy
import hashlib
import json
import sqlite3

import pytest

from engine.estates import EstateError
from engine.ledger import Leg, SYS_COMMODITY, SYS_EXTERNAL, SYS_GOV
from engine.lifecycle import Lifecycle
from research.export_bundle import export_bundle, validate_bundle
from research.hashing import HashContractError, canonical_hashes, load_hash_contract
from world.replay_verify import verify_replay

from .conftest import make_agent, make_bank
from .test_semantics17_household_decisions import _world
from .test_semantics19_estate_cash import estate, spent_loan
from .test_semantics20_civic_succession import available_adult, civic_config
from .test_semantics20_estate_cases import estate_case, validate


def mixed_wallets(e, bank, person, checking, *, savings=100, deficit=50):
    savings_id = e.ledger.create_account("agent", person, "savings", bank_id=bank,
                                         opening_cents=savings)
    e.ledger.transfer(0, checking, e.ledger.system_account(SYS_COMMODITY),
                      e.ledger.balance(checking) + deficit)
    assert e.ledger.reconcile()[0]
    return savings_id


@pytest.mark.parametrize("has_heir", [True, False])
def test_same_currency_deficit_is_settled_before_the_residual_leaves_the_estate(estate_case, has_heir):
    e, bank, person, checking, _, heir_wallet = estate_case
    savings = mixed_wallets(e, bank, person, checking)
    if not has_heir:
        e.store.execute("DELETE FROM social_ties")
    recipient = heir_wallet if has_heir else e.ledger.system_account(SYS_GOV)
    e.lifecycle.settle_death(1, person)
    assert e.ledger.balance(recipient) == 50
    assert e.ledger.balance(checking) == e.ledger.balance(savings) == 0
    offset = e.store.query_one("SELECT * FROM estate_cash_offsets")
    assert (offset["destination_account_id"], offset["negative_before_cents"], offset["amount_cents"]) == (checking, -50, 50)
    assert e.store.scalar("SELECT source_account_id FROM estate_receipts WHERE id=?", (offset["receipt_id"],)) == savings
    assert e.store.scalar("SELECT available_cents FROM estate_receipts WHERE origin_transaction_id=?", (offset["transaction_id"],)) == 0
    opening = {r["source_id"]: json.loads(r["snapshot_json"])["balance_cents"] for r in e.store.query("SELECT * FROM estate_items WHERE kind='cash'")}
    assert opening == {checking: -50, savings: 100}
    validate(e)


def negative_fx(e, person, amount, *, currency="USD"):
    account = e.ledger.create_account("agent", person, "fx", currency_code=currency)
    e.ledger.transfer(0, account, e.ledger.system_account(SYS_COMMODITY, currency_code=currency), amount)
    return account


@pytest.mark.parametrize("available", [25, 50, 65, 80, 95])
def test_partial_offsets_follow_wallet_id_order_and_stop_at_available_cash(estate_case, available):
    e, bank, person, checking, _, heir_wallet = estate_case
    savings = mixed_wallets(e, bank, person, checking, savings=available)
    second = negative_fx(e, person, 30)
    e.lifecycle.settle_death(1, person)
    first_paid = min(50, available)
    second_paid = min(30, max(0, available - 50))
    assert e.ledger.balance(checking) == -50 + first_paid
    assert e.ledger.balance(second) == -30 + second_paid
    assert e.ledger.balance(savings) == 0
    assert e.ledger.balance(heir_wallet) == max(0, available - 80)
    expected = [(checking, first_paid)] + ([(second, second_paid)] if second_paid else [])
    assert [tuple(r) for r in e.store.query("SELECT destination_account_id,amount_cents FROM estate_cash_offsets ORDER BY id")] == expected
    validate(e)


def test_late_receipts_and_direct_absorption_cannot_pay_the_same_deficit_twice(estate_case):
    e, bank, person, checking, _, heir_wallet = estate_case
    savings = mixed_wallets(e, bank, person, checking, savings=0)
    second = negative_fx(e, person, 30)
    e.lifecycle.settle_death(1, person)
    external = e.ledger.system_account(SYS_EXTERNAL)
    e.ledger.transfer(2, external, checking, 20)
    assert e.ledger.balance(checking) == -30 and e.ledger.balance(heir_wallet) == 0
    e.ledger.transfer(3, external, savings, 50)
    assert e.ledger.balance(checking) == 0 and e.ledger.balance(second) == -10
    assert e.ledger.balance(heir_wallet) == 0
    e.ledger.transfer(4, external, second, 25)
    assert e.ledger.balance(checking) == e.ledger.balance(savings) == e.ledger.balance(second) == 0
    assert e.ledger.balance(heir_wallet) == 15  # 95 external cents minus the original 80 deficit.
    assert [tuple(r) for r in e.store.query("SELECT destination_account_id,negative_before_cents,amount_cents FROM estate_cash_offsets ORDER BY id")] == [(checking, -30, 30), (second, -30, 20)]
    assert e.store.scalar("SELECT SUM(available_cents) FROM estate_receipts WHERE origin_transaction_id IN "
        "(SELECT transaction_id FROM estate_cash_offsets)") == 0
    validate(e)


@pytest.mark.parametrize("mode", ["one_transaction", "checking_first", "savings_first"])
def test_queued_credit_balances_are_reconstructed_at_processing_not_first_receipt(estate_case, mode):
    e, bank, person, checking, _, heir_wallet = estate_case
    savings = mixed_wallets(e, bank, person, checking, savings=0)
    second = negative_fx(e, person, 30)
    e.lifecycle.settle_death(1, person)
    external = e.ledger.system_account(SYS_EXTERNAL)
    with e.estate_cases._batch():
        if mode == "one_transaction":
            e.ledger.post(2, "paired_refund", [Leg(checking, 100), Leg(savings, 100), Leg(external, -200)])
        else:
            wallets = (checking, savings) if mode == "checking_first" else (savings, checking)
            for wallet in wallets:
                e.ledger.transfer(2, external, wallet, 100)
    assert e.ledger.balance(heir_wallet) == 120
    assert e.ledger.balance(checking) == e.ledger.balance(savings) == e.ledger.balance(second) == 0
    assert [tuple(r) for r in e.store.query("SELECT destination_account_id,amount_cents FROM estate_cash_offsets")] == [(second, 30)]
    validate(e)


def test_offset_across_banks_has_the_actual_reserve_settlement_legs(estate_case):
    e, bank, person, checking, _, heir_wallet = estate_case
    source_bank = make_bank(e, "Savings bank")
    savings = mixed_wallets(e, source_bank, person, checking)
    source_reserve = e.bank.get(source_bank)["reserve_account_id"]
    target_reserve = e.bank.get(bank)["reserve_account_id"]
    before = (e.ledger.balance(source_reserve), e.ledger.balance(target_reserve))
    e.lifecycle.settle_death(1, person)
    offset = e.store.query_one("SELECT * FROM estate_cash_offsets")
    assert e.cash_estates._transaction_legs(offset["transaction_id"], 1, "USD") == {
        savings: -50, checking: 50, source_reserve: -50, target_reserve: 50}
    # The residual 50 also crosses from the savings bank to the heir's bank.
    assert (e.ledger.balance(source_reserve), e.ledger.balance(target_reserve)) == (before[0] - 100, before[1] + 100)
    assert e.ledger.balance(heir_wallet) == 50
    validate(e)


@pytest.mark.parametrize("foreign_cash", [20, 60])
def test_each_currency_clears_its_own_deficits_without_conversion(estate_case, foreign_cash):
    e, bank, person, checking, heir, heir_wallet = estate_case
    mixed_wallets(e, bank, person, checking)
    foreign_negative = negative_fx(e, person, 30, currency="CAD")
    foreign_positive = e.ledger.create_account("agent", person, "fx", currency_code="CAD", opening_cents=foreign_cash)
    e.lifecycle.settle_death(1, person)
    assert e.ledger.balance(heir_wallet) == 50
    assert e.ledger.balance(foreign_negative) == -max(0, 30 - foreign_cash)
    assert e.ledger.balance(foreign_positive) == 0
    assert e.store.scalar("SELECT COALESCE(SUM(balance_cents),0) FROM accounts WHERE owner_type='agent' AND owner_id=? AND currency_code='CAD'", (heir,)) == max(0, foreign_cash - 30)
    assert {r[0] for r in e.store.query("SELECT t.currency_code FROM estate_cash_offsets o JOIN transactions t ON t.id=o.transaction_id")} == {"USD", "CAD"}
    validate(e)


@pytest.mark.parametrize("principal", [30, 80])
def test_cash_deficits_precede_bank_claims_and_later_recovery_still_precedes_heirs(estate_case, principal):
    e, bank, person, checking, _, heir_wallet = estate_case
    loan = spent_loan(e, bank, person, checking, principal)
    savings = mixed_wallets(e, bank, person, checking)
    e.lifecycle.settle_death(1, person)
    claim = e.store.query_one("SELECT * FROM estate_claims WHERE kind='bank_principal' AND source_id=?", (loan,))
    assert e.estate_cases._paid(claim["id"]) == min(50, principal)
    assert e.ledger.balance(heir_wallet) == max(0, 50 - principal)
    assert e.ledger.balance(checking) == 0
    if principal == 80:
        assert e.store.scalar("SELECT amount_cents FROM estate_claim_losses WHERE claim_id=?", (claim["id"],)) == 30
        e.ledger.transfer(2, e.ledger.system_account(SYS_EXTERNAL), savings, 40)
        assert e.estate_cases._paid(claim["id"]) == 80
        assert e.ledger.balance(heir_wallet) == 10
        assert e.ledger.balance(e.bank.get(bank)["equity_account_id"]) == 0
    assert e.store.scalar("SELECT SUM(amount_cents) FROM estate_cash_offsets") == 50
    validate(e)


@pytest.mark.parametrize("late", [False, True])
def test_offset_and_distribution_failure_roll_back_the_complete_funding_boundary(estate_case, monkeypatch, late):
    e, bank, person, checking, _, heir_wallet = estate_case
    savings = mixed_wallets(e, bank, person, checking, savings=0 if late else 100)
    if late:
        e.lifecycle.settle_death(1, person)
    before = canonical_hashes(e.store)["authoritative_sha256"]
    original = e.estate_cases._disburse
    def fail_after_payment(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected after cash offset and distribution")
    monkeypatch.setattr(e.estate_cases, "_disburse", fail_after_payment)
    def fund():
        if late:
            return e.ledger.transfer(2, e.ledger.system_account(SYS_EXTERNAL), savings, 100)
        return e.lifecycle.settle_death(1, person)
    with pytest.raises(RuntimeError, match="injected after cash offset"):
        fund()
    assert canonical_hashes(e.store)["authoritative_sha256"] == before
    assert e.estate_cases._pending is None
    assert e.store.scalar("SELECT COUNT(*) FROM estate_cash_offsets") == 0
    monkeypatch.setattr(e.estate_cases, "_disburse", original)
    fund()
    assert e.ledger.balance(heir_wallet) == 50
    validate(e)


def test_balanced_ledger_cannot_hide_skipped_deficit_priority(estate_case, monkeypatch):
    e, bank, person, checking, _, heir_wallet = estate_case
    mixed_wallets(e, bank, person, checking)
    monkeypatch.setattr(e.estate_cases, "_offset_cash_deficits", lambda receipt, remaining: remaining)
    e.lifecycle.settle_death(1, person)
    assert e.ledger.reconcile()[0] and e.ledger.balance(heir_wallet) == 100
    with pytest.raises(EstateError, match="cash deficit offsets violate"):
        e.estate_cases.check_invariants()


def test_cash_offset_evidence_cannot_be_rewritten_or_deleted(estate_case):
    e, bank, person, checking, _, _ = estate_case
    mixed_wallets(e, bank, person, checking)
    e.lifecycle.settle_death(1, person)
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        e.store.execute("UPDATE estate_cash_offsets SET negative_before_cents=-60")
    with pytest.raises(sqlite3.IntegrityError, match="permanent"):
        e.store.execute("DELETE FROM estate_cash_offsets")
    validate(e)


@pytest.mark.parametrize("field", ["negative_before_cents", "destination_account_id"])
def test_changed_offset_balance_or_wallet_fails_reconciliation(estate_case, field):
    e, bank, person, checking, _, heir_wallet = estate_case
    mixed_wallets(e, bank, person, checking)
    e.lifecycle.settle_death(1, person)
    offset = e.store.query_one("SELECT * FROM estate_cash_offsets")
    e.store.execute("DROP TRIGGER estate_cash_offsets_immutable")
    e.store.update("estate_cash_offsets", offset["id"], **{field: -60 if field == "negative_before_cents" else heir_wallet})
    assert e.ledger.reconcile()[0]
    with pytest.raises(EstateError, match="cash deficit"):
        e.estate_cases.check_invariants()


def test_offset_without_a_source_receipt_is_not_accepted_as_evidence(estate_case):
    e, bank, person, checking, _, _ = estate_case
    mixed_wallets(e, bank, person, checking)
    e.lifecycle.settle_death(1, person)
    transaction = e.store.scalar("SELECT MAX(id) FROM transactions")
    with pytest.raises((EstateError, sqlite3.IntegrityError), match="estate receipt|FOREIGN KEY"):
        e.store.insert("estate_cash_offsets", receipt_id=99999, destination_account_id=checking,
                       negative_before_cents=-1, amount_cents=1, transaction_id=transaction)
        e.estate_cases.check_invariants()


def test_legacy_semantics19_keeps_its_recorded_wallet_behavior(estate):
    e, bank, person, checking, _, heir_wallet = estate
    mixed_wallets(e, bank, person, checking)
    e.lifecycle.settle_death(1, person)
    assert e.ledger.balance(checking) == -50 and e.ledger.balance(heir_wallet) == 100
    assert e.store.scalar("SELECT COUNT(*) FROM estate_cash_offsets") == 0
    e.cash_estates.check_invariants()
    assert e.ledger.reconcile()[0]


def test_cash_offsets_are_in_the_required_hash_and_export_contract(estate_case, tmp_path):
    e, bank, person, checking, _, _ = estate_case
    mixed_wallets(e, bank, person, checking)
    e.lifecycle.settle_death(1, person)
    hashes = canonical_hashes(e.store)
    assert hashes["tables"]["estate_cash_offsets"]["row_count"] == 1
    with pytest.raises(HashContractError, match="requires hash-contract-v7"):
        canonical_hashes(e.store, load_hash_contract("research/hash-contract-v6.json"))
    manifest = validate_bundle(export_bundle(e.store, tmp_path / "export"))
    assert manifest["tables"]["estate_cash_offsets"]["row_count"] == 1
    validate(e)


def test_a_deceased_beneficiarys_own_deficit_settles_before_the_next_generation(estate_case):
    e, bank, person, checking, heir, heir_wallet = estate_case
    descendant, descendant_wallet = make_agent(e, bank, "Next generation", cash=0)
    e.households.register_person(0, descendant, "genesis")
    e.store.insert("social_ties", agent_a=heir, agent_b=descendant, weight=2)
    savings = mixed_wallets(e, bank, person, checking)
    heir_deficit = negative_fx(e, heir, 80)
    e.lifecycle.settle_death(1, person)
    assert e.ledger.balance(heir_wallet) == 50
    e.lifecycle.settle_death(2, heir)
    assert e.ledger.balance(heir_deficit) == -30 and e.ledger.balance(descendant_wallet) == 0
    e.ledger.transfer(3, e.ledger.system_account(SYS_EXTERNAL), savings, 70)
    assert e.ledger.balance(descendant_wallet) == 40
    assert all(e.ledger.balance(wallet) == 0 for wallet in (checking, savings, heir_wallet, heir_deficit))
    assert [tuple(r) for r in e.store.query("SELECT c.deceased_agent_id,o.amount_cents FROM estate_cash_offsets o "
        "JOIN estate_receipts r ON r.id=o.receipt_id JOIN estate_cases c ON c.id=r.estate_id ORDER BY o.id")] == [(person, 50), (heir, 50), (heir, 30)]
    assert e.estate_cases._pending is None
    validate(e)


def test_nightly_cash_offsets_survive_restart_and_exact_recorded_replay(tmp_path, monkeypatch, caplog):
    config = civic_config()
    config["checkpoint_dir"] = str(tmp_path / "checkpoints")
    config["lifecycle"].update(illness_onset_annual_young=0, illness_onset_annual_old=0)
    identities = {}
    draw = Lifecycle._draw

    def forced_death(self, tick, person, mechanism):
        if tick == 1 and person == identities["person"] and mechanism == "mortality":
            return 0.0
        return draw(self, tick, person, mechanism)

    monkeypatch.setattr(Lifecycle, "_draw", forced_death)

    def open_seeded(path, settings, *, replay=False):
        world = _world(path, settings, replay=replay)
        if world.store.tick != 0:
            return world
        e, store = world.economy, world.store
        person = available_adult(world)
        store.update("agents", person, cadence_json='{"act":9999,"portfolio":9999,"career":9999,"news":9999}')
        checking = e.ledger.agent_checking_id(person)
        account = store.query_one("SELECT * FROM accounts WHERE id=?", (checking,))
        assert account["balance_cents"] >= 1000
        # Genesis already gives this person savings; preserve and fund that
        # wallet so the expected source is the first opening cash receipt.
        savings = store.scalar("SELECT id FROM accounts WHERE owner_type='agent' AND owner_id=? "
            "AND kind='savings' AND currency_code=? ORDER BY id LIMIT 1", (person, account["currency_code"]))
        assert savings is not None
        e.ledger.transfer(0, checking, savings, 1000)
        # Declared stress at genesis: use existing cash and the ledger's existing
        # deficit support. This does not add a person or an external endowment.
        e.ledger.transfer(0, checking, e.ledger.system_account(SYS_COMMODITY, currency_code=account["currency_code"]),
                          e.ledger.balance(checking) + 50)
        identities.update(person=person, checking=checking, savings=savings)
        return world

    source_path = tmp_path / "source-offsets.db"
    for _ in range(3):
        source = open_seeded(source_path, config)
        try:
            asyncio.run(source.step())
            offset = source.store.query_one("SELECT o.*,r.source_account_id FROM estate_cash_offsets o "
                "JOIN estate_receipts r ON r.id=o.receipt_id JOIN estate_cases c ON c.id=r.estate_id "
                "WHERE c.deceased_agent_id=? AND o.destination_account_id=?", (identities["person"], identities["checking"]))
            assert offset is not None
            assert (offset["source_account_id"], offset["negative_before_cents"], offset["amount_cents"]) == (identities["savings"], -50, 50)
            assert source.economy.ledger.balance(identities["checking"]) == source.economy.ledger.balance(identities["savings"]) == 0
            source.economy.estate_cases.check_invariants()
        finally:
            source.close()
    before = hashlib.sha256(source_path.read_bytes()).hexdigest()
    settings = copy.deepcopy(config)
    settings["replay_source_path"] = str(source_path)
    replay = open_seeded(tmp_path / "replayed-offsets.db", settings, replay=True)
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
