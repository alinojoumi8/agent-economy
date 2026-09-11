"""Court and settlement balances survive death without duplicate debt collection."""
from __future__ import annotations

import json
import random
import sqlite3
from types import SimpleNamespace

import pytest

from engine.actions import ActionExecutor
from engine.core import Economy
from engine.ledger import SYS_EXTERNAL
from research.export_bundle import export_bundle, validate_bundle
from research.hashing import canonical_hashes

from .conftest import make_agent, make_bank
from .test_v2_legal import _payment_contract
from .test_semantics19_estate_cash import spent_loan, foreign_bank


@pytest.fixture
def award_case(store):
    config = {"engine_semantics_version": 20, "seed": 1,
              "lifecycle": {"birth_annual_prob": 0, "population_mode": "drift"},
              "family_decisions": {"scripted_matching": False}}
    store.execute("UPDATE run_meta SET config_json=?", (json.dumps(config),))
    e = Economy(store, config, random.Random(1), random.Random(2))
    e.ensure_system_accounts()
    store.insert("regions", id=1, region_key="home", name="Home", currency_code="USD",
                 population_target=4, specialization_json="{}", x=0, y=0, legal_ruleset="test")
    bank = make_bank(e)
    person, wallet = make_agent(e, bank, "Debtor", region_id=1, cash=100)
    heir, heir_wallet = make_agent(e, bank, "Heir", region_id=1, cash=0)
    creditor, creditor_wallet = make_agent(e, bank, "Claimant", region_id=1, cash=0)
    judge, _ = make_agent(e, bank, "Judge", region_id=1, cash=0, kind="staff", occupation="judge", role="judge")
    store.insert("social_ties", agent_a=person, agent_b=heir, weight=1)
    store.insert("social_ties", agent_a=creditor, agent_b=heir, weight=1)
    e.households.initialize()
    return SimpleNamespace(e=e, bank=bank, person=person, wallet=wallet, heir=heir, heir_wallet=heir_wallet,
                           creditor=creditor, creditor_wallet=creditor_wallet, judge=judge, executor=ActionExecutor(e))


def check(case):
    e = case.e
    e.legal_awards.check_invariants()
    e.estate_cases.check_invariants()
    e.business_control.check_invariants()
    assert e.ledger.reconcile()[0]
    assert e.estate_cases._pending is None


def claim(case, amount=170, *, contract=True, currency=None, contract_id=None, tick=1):
    e = case.e
    if contract and contract_id is None:
        contract_id = _payment_contract(case.executor, case.creditor, case.person, due_tick=0, amount=amount)
    if contract:
        e.legal.run_nightly(tick)
        event = e.store.scalar("SELECT id FROM events WHERE kind='obligation_breached' AND subject_id=? ORDER BY id DESC LIMIT 1", (contract_id,))
    else:
        event = e.store.log_event(tick, "fixture_loss_evidence", {"amount_cents": amount}, phase="EXECUTION")
    requested = {"type": "damages", "amount_cents": amount}
    if currency:
        requested["currency_code"] = currency
    result = case.executor.execute_action(tick, case.creditor, {"type": "file_claim", "contract_id": contract_id,
        "claimant": {"type": "agent", "id": case.creditor}, "respondent": {"type": "agent", "id": case.person},
        "claim_type": "breach" if contract else "loss", "requested_remedy": requested})
    assert result["ok"], result
    matter = result["matter_id"]
    result = case.executor.execute_action(tick, case.creditor, {"type": "submit_filing", "matter_id": matter,
        "filer_type": "agent", "filer_id": case.creditor, "filing_type": "evidence", "evidence_event_ids": [event],
        "body": "Recorded evidence for the bounded remedy."})
    assert result["ok"], result
    return matter, event


def decide(case, matter, event, amount, *, tick=1, **fields):
    return case.e.legal.issue_decision(tick, case.judge, {"matter_id": matter, "outcome": "claimant",
        "findings": [{"key": "liability", "value": True}], "evidence_event_ids": [event],
        "remedy": {"type": "damages", "amount_cents": amount, **fields}})


def receive(case, amount, *, tick=4, wallet=None, currency="USD"):
    return case.e.ledger.transfer(tick, case.e.ledger.system_account(SYS_EXTERNAL, currency_code=currency),
                                 case.wallet if wallet is None else wallet, amount)


def test_preexisting_unpaid_award_is_collected_from_the_estate_once(award_case):
    c = award_case
    matter, event = claim(c)
    result = decide(c, matter, event, 170)
    assert result["ok"], result
    award = result["enforcement"]["award_id"]
    assert result["enforcement"]["paid_cents"] == 100
    assert result["enforcement"]["unpaid_cents"] == 70
    assert c.e.store.scalar("SELECT status FROM obligations") == "adjudicated"
    assert not c.e.legal.perform_obligation(1, c.person, 1)["ok"]
    before = canonical_hashes(c.e.store)["authoritative_sha256"]
    assert not decide(c, matter, event, 170)["ok"]
    assert canonical_hashes(c.e.store)["authoritative_sha256"] == before
    c.e.lifecycle.settle_death(2, c.person)
    assert c.e.store.scalar("SELECT principal_cents FROM estate_claims WHERE kind='legal_award'") == 70
    receive(c, 90)
    assert c.e.ledger.balance(c.creditor_wallet) == 170
    assert c.e.ledger.balance(c.heir_wallet) == 20
    assert c.e.legal_awards.paid(award) == 170
    check(c)


def test_later_decision_replaces_unpaid_contract_claim_and_credits_prior_estate_payments(award_case):
    c = award_case
    contract = _payment_contract(c.executor, c.creditor, c.person, due_tick=0, amount=150)
    c.e.lifecycle.settle_death(2, c.person)
    assert c.e.ledger.balance(c.creditor_wallet) == 100
    opening = dict(c.e.store.query_one("SELECT * FROM estate_cases"))
    old_receipt = dict(c.e.store.query_one("SELECT * FROM estate_receipts"))
    matter, event = claim(c, 150, contract_id=contract, tick=3)
    result = decide(c, matter, event, 120, tick=3)
    assert result["ok"], result
    assert result["enforcement"]["credited_cents"] == 100
    assert result["enforcement"]["unpaid_cents"] == 20
    assert c.e.store.scalar("SELECT amount_cents FROM estate_claim_releases") == 50
    added = c.e.store.query_one("SELECT * FROM estate_claims WHERE kind='legal_award'")
    assert added["registered_after_receipt_id"] == old_receipt["id"]
    assert added["is_opening"] == 0
    receive(c, 40)
    assert c.e.ledger.balance(c.creditor_wallet) == 120
    assert c.e.ledger.balance(c.heir_wallet) == 20
    assert dict(c.e.store.query_one("SELECT * FROM estate_cases")) == opening
    assert dict(c.e.store.query_one("SELECT * FROM estate_receipts WHERE id=?", (old_receipt["id"],))) == old_receipt
    check(c)


def test_late_award_obeys_bank_priority_and_never_uses_the_heirs_existing_cash(award_case):
    c = award_case
    matter, event = claim(c, 30, contract=False)
    spent_loan(c.e, c.bank, c.person, c.wallet, 170)
    receive(c, 25, tick=1, wallet=c.heir_wallet)
    c.e.lifecycle.settle_death(2, c.person)
    result = decide(c, matter, event, 30, tick=3)
    assert result["ok"], result
    receive(c, 90)
    assert c.e.ledger.balance(c.creditor_wallet) == 20
    assert c.e.ledger.balance(c.heir_wallet) == 25
    receive(c, 30, tick=5)
    assert c.e.ledger.balance(c.creditor_wallet) == 30
    assert c.e.ledger.balance(c.heir_wallet) == 45
    check(c)


def test_award_currency_is_preserved_after_death_and_does_not_consume_other_wallets(award_case):
    c = award_case
    foreign_bank(c.e, "CAD")
    cad = c.e.ledger.create_account("agent", c.person, "fx", currency_code="CAD", opening_cents=10)
    matter, event = claim(c, 70, contract=False, currency="CAD")
    result = decide(c, matter, event, 70, currency_code="CAD")
    assert result["ok"], result
    assert result["enforcement"]["paid_cents"] == 10
    assert c.e.ledger.balance(c.wallet) == 100
    c.e.lifecycle.settle_death(2, c.person)
    assert c.e.ledger.balance(c.heir_wallet) == 100
    receive(c, 10, tick=3)
    assert c.e.ledger.balance(c.heir_wallet) == 110
    receive(c, 80, wallet=cad, currency="CAD")
    assert c.e.store.scalar("SELECT SUM(balance_cents) FROM accounts WHERE owner_type='agent' AND owner_id=? AND currency_code='CAD'", (c.creditor,)) == 70
    assert c.e.store.scalar("SELECT SUM(balance_cents) FROM accounts WHERE owner_type='agent' AND owner_id=? AND currency_code='CAD'", (c.heir,)) == 20
    check(c)


def test_award_payment_to_a_deceased_claimant_routes_through_both_recorded_estates(award_case):
    c = award_case
    matter, event = claim(c, 170)
    assert decide(c, matter, event, 170)["ok"]
    c.e.lifecycle.settle_death(2, c.person)
    c.e.lifecycle.settle_death(3, c.creditor)
    assert c.e.ledger.balance(c.heir_wallet) == 100
    receive(c, 90)
    assert c.e.ledger.balance(c.creditor_wallet) == 0
    assert c.e.ledger.balance(c.wallet) == 0
    assert c.e.ledger.balance(c.heir_wallet) == 190
    check(c)


def test_accepted_settlement_retains_the_unpaid_amount_after_death(award_case):
    c = award_case
    matter, _ = claim(c, 150)
    offered = c.e.legal.propose_settlement(1, c.creditor, matter, {"remedy": {"type": "damages", "amount_cents": 150}})
    assert offered["ok"], offered
    accepted = c.e.legal.accept_settlement(1, c.person, matter)
    assert accepted["ok"], accepted
    assert accepted["enforcement"]["unpaid_cents"] == 50
    c.e.lifecycle.settle_death(2, c.person)
    receive(c, 75)
    assert c.e.ledger.balance(c.creditor_wallet) == 150
    assert c.e.ledger.balance(c.heir_wallet) == 25
    assert c.e.store.scalar("SELECT basis FROM legal_awards") == "settlement"
    check(c)


def test_failed_award_recording_rolls_back_decision_debt_replacement_and_payment(award_case, monkeypatch):
    c = award_case
    matter, event = claim(c)
    before = canonical_hashes(c.e.store)["authoritative_sha256"]
    original = c.e.legal_awards.note_payment
    def fail(*args, **kwargs):
        raise RuntimeError("injected award receipt failure")
    monkeypatch.setattr(c.e.legal_awards, "note_payment", fail)
    with pytest.raises(RuntimeError, match="injected"):
        decide(c, matter, event, 170)
    assert canonical_hashes(c.e.store)["authoritative_sha256"] == before
    assert c.e.estate_cases._pending is None
    monkeypatch.setattr(c.e.legal_awards, "note_payment", original)
    assert decide(c, matter, event, 170)["ok"]
    check(c)


def test_late_cash_failure_rolls_back_the_original_incoming_credit(award_case, monkeypatch):
    c = award_case
    matter, event = claim(c)
    assert decide(c, matter, event, 170)["ok"]
    c.e.lifecycle.settle_death(2, c.person)
    before = canonical_hashes(c.e.store)["authoritative_sha256"]
    def fail(*args, **kwargs):
        raise RuntimeError("injected late award receipt failure")
    monkeypatch.setattr(c.e.legal_awards, "note_payment", fail)
    with pytest.raises(RuntimeError, match="injected"):
        receive(c, 90)
    assert canonical_hashes(c.e.store)["authoritative_sha256"] == before
    check(c)


def test_awards_export_immutable_ledger_links_and_reject_cross_party_obligations(award_case, tmp_path):
    c = award_case
    matter, event = claim(c)
    rejected = decide(c, matter, event, 170, obligation_ids=[999999])
    assert not rejected["ok"] and rejected["repairable"]
    assert c.e.store.scalar("SELECT COUNT(*) FROM legal_awards") == 0
    result = decide(c, matter, event, 170)
    assert result["ok"], result
    c.e.lifecycle.settle_death(2, c.person)
    receive(c, 90)
    manifest = validate_bundle(export_bundle(c.e.store, tmp_path / "awards-export"))
    for table, count in [("legal_awards", 1), ("legal_award_obligations", 1), ("legal_award_payments", 2)]:
        assert manifest["tables"][table]["row_count"] == count
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        c.e.store.execute("UPDATE legal_awards SET awarded_cents=1")
    with pytest.raises(sqlite3.IntegrityError, match="permanent"):
        c.e.store.execute("DELETE FROM legal_award_payments")
    check(c)


def test_expired_future_contract_releases_its_unpaid_estate_claim(award_case):
    c = award_case
    contract = _payment_contract(c.executor, c.creditor, c.person, due_tick=20, amount=150)
    c.e.store.update("contracts", contract, expiry_tick=2)
    c.e.lifecycle.settle_death(1, c.person)
    assert c.e.ledger.balance(c.creditor_wallet) == 100
    c.e.legal.run_nightly(3)
    assert c.e.store.scalar("SELECT reason FROM estate_claim_releases") == "contract_expired"
    assert c.e.store.scalar("SELECT amount_cents FROM estate_claim_releases") == 50
    receive(c, 30)
    assert c.e.ledger.balance(c.creditor_wallet) == 100
    assert c.e.ledger.balance(c.heir_wallet) == 30
    check(c)
