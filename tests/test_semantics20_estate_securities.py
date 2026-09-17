"""Realized estate securities preserve creditor priority and market evidence."""
import asyncio
import copy
import hashlib
import json
import sqlite3

import pytest

from engine.actions import ActionExecutor
from engine.estates import EstateError
from engine.ledger import SYS_COMMODITY, SYS_LOSS
from engine.lifecycle import Lifecycle
from research.export_bundle import export_bundle, validate_bundle
from research.hashing import canonical_hashes
from world.replay_verify import verify_replay

from .conftest import make_agent
from .test_semantics19_estate_cash import foreign_bank, spent_loan
from .test_semantics17_household_decisions import _world
from .test_semantics20_civic_succession import available_adult, civic_config
from .test_semantics20_estate_cases import estate_case, validate
from .test_semantics20_legal_awards import award_case, claim, decide, check as validate_award
from .test_semantics20_estate_disputes import dismiss, reserve


def indebted_security_estate(estate_case):
    e, bank, person, wallet, heir, heir_wallet = estate_case
    e.ledger.transfer(0, wallet, e.ledger.system_account(SYS_COMMODITY), e.ledger.balance(wallet))
    loan = spent_loan(e, bank, person, wallet, 100)
    firm = e.firms.found_firm(0, person, "Estate issuer", "manufacturing",
                              opening_capital_cents=0, shares=10)
    # Declared listed-company genesis; the subsequent price comes from orders.
    e.store.update("firms", firm, status="listed")
    buyer, buyer_wallet = make_agent(e, bank, "Funded buyer", cash=200, region_id=1)
    e.households.register_person(0, buyer, "genesis")
    return e, bank, person, wallet, heir, heir_wallet, loan, firm, buyer, buyer_wallet


def test_funded_security_sale_recovers_estate_debt_before_inheritance(estate_case):
    e, bank, person, wallet, heir, heir_wallet, loan, firm, buyer, buyer_wallet = indebted_security_estate(estate_case)
    e.lifecycle.settle_death(1, person)
    estate_id = e.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=?", (person,))
    equity = e.bank.get(bank)["equity_account_id"]
    assert e.ledger.balance(equity) == -100
    assert e.ledger.balance(e.ledger.system_account(SYS_LOSS)) == 100
    actions = ActionExecutor(e)
    sale = actions.execute_action(2, heir, {"type": "place_order", "estate_id": estate_id,
        "firm_id": firm, "side": "sell", "qty": 10, "limit_price": 20})
    purchase = actions.execute_action(2, buyer, {"type": "place_order", "firm_id": firm,
        "side": "buy", "qty": 10, "limit_price": 20})
    assert sale["ok"] and purchase["ok"], (sale, purchase)
    fills = e.exchange.match_firm(2, firm)
    assert [(fill.qty, fill.price_cents) for fill in fills] == [(10, 20)]
    assert e.ledger.balance(equity) == e.ledger.balance(e.ledger.system_account(SYS_LOSS)) == 0
    assert e.ledger.balance(heir_wallet) == 100
    assert e.ledger.balance(wallet) == e.ledger.balance(buyer_wallet) == 0
    assert e.store.scalar("SELECT status FROM loans WHERE id=?", (loan,)) == "paid"
    assert e.exchange.shares_held(firm, "agent", buyer) == 10
    assert e.exchange.shares_held(firm, "agent", person) == e.exchange.shares_held(firm, "agent", heir) == 0
    validate(e)


def test_replay_purpose_follows_recorded_operator_intervals(estate_case):
    from world.replay_verify import _action_purposes_for, _row_llm_expectations, _canonical_llm_reference

    e, bank, person, wallet, heir, heir_wallet, loan, firm, buyer, buyer_wallet = indebted_security_estate(estate_case)
    config = dict(e.config, llm={"institutional_role_purposes": True})
    e.store.execute("UPDATE run_meta SET config_json=?", (json.dumps(config),))
    e.lifecycle.settle_death(1, person)
    estate_id = e.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=?", (person,))
    order(e, 3, heir, firm, "sell", 10, estate_id=estate_id)
    order(e, 3, buyer, firm, "buy", 10)
    assert sum(fill.qty for fill in e.exchange.match_firm(3, firm)) == 10
    e.business_control.refresh_custody(3)

    def purposes(actor, tick):
        return _action_purposes_for(e.store.conn, actor, tick, "citizen")

    # Decisions happen before market clearing. Day-granularity intervals admit
    # either phase on a transition day, and never extend authority beyond it.
    assert purposes(heir, 1) == {"founder", "decision"}
    assert purposes(heir, 2) == {"founder"}
    assert purposes(heir, 3) == purposes(buyer, 3) == {"founder", "decision"}
    assert purposes(person, 2) == purposes(buyer, 2) == purposes(heir, 4) == {"decision"}
    assert purposes(buyer, 4) == {"founder"}
    unrelated, _ = make_agent(e, bank, "Unrelated observer", cash=0, region_id=1)
    assert purposes(unrelated, 3) == {"decision"}
    validate(e)
    # The day permits either purpose, but a recorded founder decision cannot
    # cite a different decision-purpose call from the same actor and tick.
    row = dict(tick=3, agent_id=heir, purpose="founder")
    expected, valid = _row_llm_expectations(e.store.conn, "agent_decisions", row)
    reference = {1: {"llm_call": dict(tick=3, agent_id=heir, role="citizen", purpose="decision")}}
    assert not _canonical_llm_reference(1, reference, expected, valid)[1]
    reference[1]["llm_call"]["purpose"] = "founder"
    assert _canonical_llm_reference(1, reference, expected, valid)[1]
    # Bankruptcy is processed before that day's decisions in this engine;
    # stewardship boundary handling must preserve that stricter legacy rule.
    e.store.update("firms", firm, status="bankrupt", bankrupt_tick=5)
    assert purposes(buyer, 5) == {"decision"}


@pytest.mark.parametrize("frontier_kind", ["future", "before_estate"])
def test_security_authority_rejects_impossible_estate_frontiers(estate_case, frontier_kind):
    e, _, person, _, heir, _, _, firm, buyer, _ = indebted_security_estate(estate_case)
    if frontier_kind == "before_estate":
        e.lifecycle.settle_death(1, buyer)
        e.lifecycle.settle_death(2, person)
        tick = 3
    else:
        e.lifecycle.settle_death(1, person)
        tick = 2
    estate_id = e.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=?", (person,))
    quote = order(e, tick, heir, firm, "sell", 10, estate_id=estate_id)
    if frontier_kind == "future":
        e.lifecycle.settle_death(5, buyer)
    auth = dict(e.estate_securities.authorization(quote))
    validate(e)
    # An otherwise valid authority proof cannot cite a later death or exclude
    # the very estate whose shares it purported to authorize. Keep the stored
    # immutable proof unchanged while submitting the corrupt copy for audit.
    auth["estate_frontier_id"] = e.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=?", (buyer,))
    with pytest.raises(EstateError, match="estate frontier"):
        e.estate_securities._check_authorization(auth)


def test_late_in_kind_inheritance_enters_a_deceased_heirs_creditor_pool(estate_case):
    e, bank, person, wallet, heir, heir_wallet, loan, firm, buyer, buyer_wallet = indebted_security_estate(estate_case)
    descendant, descendant_wallet = make_agent(e, bank, "Next beneficiary", cash=0, region_id=1)
    e.households.register_person(0, descendant, "genesis")
    e.store.insert("social_ties", agent_a=heir, agent_b=descendant, weight=100)
    heir_loan = spent_loan(e, bank, heir, heir_wallet, 50)
    e.lifecycle.settle_death(1, person)
    e.lifecycle.settle_death(2, heir)
    heir_estate = e.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=?", (heir,))
    # The first estate pays its bank with real cash; its in-kind residual must
    # then face the already deceased heir's own creditors before descendants.
    e.ledger.transfer(3, buyer_wallet, wallet, 100)
    assert e.store.scalar("SELECT status FROM loans WHERE id=?", (loan,)) == "paid"
    assert e.exchange.shares_held(firm, "agent", person) == 0
    assert e.exchange.shares_held(firm, "agent", heir) == 10
    assert e.exchange.shares_held(firm, "agent", descendant) == 0
    assert e.store.scalar("SELECT source_transfer_id FROM estate_security_lots WHERE estate_id=?", (heir_estate,)) is not None
    validate(e)
    order(e, 4, descendant, firm, "sell", 5, estate_id=heir_estate)
    order(e, 4, buyer, firm, "buy", 5)
    assert sum(fill.qty for fill in e.exchange.match_firm(4, firm)) == 5
    assert e.store.scalar("SELECT status FROM loans WHERE id=?", (heir_loan,)) == "paid"
    assert e.ledger.balance(e.bank.get(bank)["equity_account_id"]) == 0
    assert e.ledger.balance(descendant_wallet) == 50
    assert e.ledger.balance(wallet) == e.ledger.balance(heir_wallet) == e.ledger.balance(buyer_wallet) == 0
    assert e.exchange.shares_held(firm, "agent", buyer) == e.exchange.shares_held(firm, "agent", descendant) == 5
    assert e.exchange.shares_held(firm, "agent", heir) == 0
    validate(e)


def order(e, tick, actor, firm, side, qty, *, estate_id=None, price=20):
    action = dict(type="place_order", firm_id=firm, side=side, qty=qty, limit_price=price)
    if estate_id is not None:
        action["estate_id"] = estate_id
    result = ActionExecutor(e).execute_action(tick, actor, action)
    assert result["ok"], result
    return result["order_id"]


@pytest.mark.parametrize("deficit_wallet", ["checking", "fx"])
def test_sale_cash_clears_existing_deficits_before_bank_and_heirs(estate_case, deficit_wallet):
    e, bank, person, wallet, heir, heir_wallet, loan, firm, buyer, buyer_wallet = indebted_security_estate(estate_case)
    deficit = wallet if deficit_wallet == "checking" else e.ledger.create_account("agent", person, "fx", currency_code="USD")
    e.ledger.transfer(0, deficit, e.ledger.system_account(SYS_COMMODITY), 30)
    e.lifecycle.settle_death(1, person)
    estate_id = e.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=?", (person,))
    order(e, 2, heir, firm, "sell", 10, estate_id=estate_id)
    order(e, 2, buyer, firm, "buy", 10)
    assert sum(fill.qty for fill in e.exchange.match_firm(2, firm)) == 10
    assert e.ledger.balance(heir_wallet) == 70
    assert e.ledger.balance(wallet) == e.ledger.balance(deficit) == e.ledger.balance(buyer_wallet) == 0
    assert e.store.scalar("SELECT status FROM loans WHERE id=?", (loan,)) == "paid"
    assert e.ledger.balance(e.bank.get(bank)["equity_account_id"]) == 0
    validate(e)


def test_estate_sale_stops_at_the_buyers_actual_affordability(estate_case):
    e, bank, person, wallet, heir, heir_wallet, loan, firm, buyer, buyer_wallet = indebted_security_estate(estate_case)
    e.lifecycle.settle_death(1, person)
    estate_id = e.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=?", (person,))
    order(e, 2, heir, firm, "sell", 10, estate_id=estate_id)
    buy = order(e, 2, buyer, firm, "buy", 10)
    # The funded order is accepted, then another actual payment reduces cash
    # before matching; settlement must recheck affordability at that moment.
    e.ledger.transfer(2, buyer_wallet, e.ledger.system_account(SYS_COMMODITY), 135)
    assert sum(fill.qty for fill in e.exchange.match_firm(2, firm)) == 3
    assert e.store.scalar("SELECT status FROM orders WHERE id=?", (buy,)) == "cancelled"
    assert e.ledger.balance(buyer_wallet) == 5
    assert e.ledger.balance(heir_wallet) == 0
    assert e.ledger.balance(e.bank.get(bank)["equity_account_id"]) == -40
    assert e.exchange.shares_held(firm, "agent", person) == 7
    assert e.exchange.shares_held(firm, "agent", buyer) == 3
    before = canonical_hashes(e.store)["authoritative_sha256"]
    assert not e.exchange.match_firm(2, firm)
    assert canonical_hashes(e.store)["authoritative_sha256"] == before
    validate(e)


def test_business_steward_selection_uses_remaining_estate_units_after_sales(estate_case):
    e, bank, person, wallet, heir, heir_wallet, loan, firm, buyer, buyer_wallet = indebted_security_estate(estate_case)
    coowner, coowner_wallet = make_agent(e, bank, "Coowner", cash=4, region_id=1)
    coheir, _ = make_agent(e, bank, "Coowner beneficiary", cash=0, region_id=1)
    for actor in (coowner, coheir):
        e.households.register_person(0, actor, "genesis")
    e.store.insert("social_ties", agent_a=coowner, agent_b=coheir, weight=1)
    order(e, 0, person, firm, "sell", 4, price=1)
    order(e, 0, coowner, firm, "buy", 4, price=1)
    assert sum(fill.qty for fill in e.exchange.match_firm(0, firm)) == 4
    e.ledger.transfer(0, wallet, e.ledger.system_account(SYS_COMMODITY), 4)
    spent_loan(e, bank, coowner, coowner_wallet, 100)
    e.lifecycle.settle_death(1, person)
    e.lifecycle.settle_death(1, coowner)
    assert e.business_control.operator_at(firm) == heir  # six units versus four
    estate_id = e.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=?", (person,))
    order(e, 2, heir, firm, "sell", 5, estate_id=estate_id, price=1)
    order(e, 2, buyer, firm, "buy", 5, price=1)
    assert sum(fill.qty for fill in e.exchange.match_firm(2, firm)) == 5
    # This buyer has no beneficiaries or debts, so its units pass to the system.
    # The two remaining indebted estates hold one unit and four units; sold
    # quantities cannot continue to give the first representative precedence.
    e.lifecycle.settle_death(3, buyer)
    e.business_control.refresh_custody(3)
    assert e.exchange.shares_held(firm, "agent", person) == 1
    assert e.exchange.shares_held(firm, "agent", coowner) == 4
    assert e.business_control.operator_at(firm) == coheir
    assert e.ledger.balance(e.bank.get(bank)["equity_account_id"]) == -195
    validate(e)


def test_adjudication_keeps_securities_until_the_replacement_award_is_paid(award_case):
    c = award_case
    firm = c.e.firms.found_firm(0, c.person, "Contested issuer", "manufacturing", opening_capital_cents=0, shares=10)
    c.e.store.update("firms", firm, status="listed")
    buyer, buyer_wallet = make_agent(c.e, c.bank, "Judgment sale buyer", cash=200, region_id=1)
    c.e.households.register_person(0, buyer, "genesis")
    matter, event = claim(c, 150)
    c.e.lifecycle.settle_death(2, c.person)
    assert c.e.ledger.balance(reserve(c, matter)["escrow_account_id"]) == 100
    assert c.e.exchange.shares_held(firm, "agent", c.person) == 10
    result = decide(c, matter, event, 120, tick=3)
    assert result["ok"], result
    # Releasing the old contract and admitting its replacement is one operation.
    # Its still-unpaid 20 cents must not briefly expose the securities to heirs.
    assert c.e.store.scalar("SELECT COUNT(*) FROM estate_security_releases") == 0
    assert c.e.ledger.balance(c.creditor_wallet) == 100
    assert c.e.ledger.balance(c.heir_wallet) == 0
    validate_award(c)
    estate_id = c.e.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=?", (c.person,))
    order(c.e, 4, c.heir, firm, "sell", 1, estate_id=estate_id)
    order(c.e, 4, buyer, firm, "buy", 1)
    assert sum(fill.qty for fill in c.e.exchange.match_firm(4, firm)) == 1
    assert c.e.ledger.balance(c.creditor_wallet) == 120
    assert c.e.ledger.balance(c.heir_wallet) == 0
    assert c.e.ledger.balance(buyer_wallet) == 180
    assert c.e.exchange.shares_held(firm, "agent", c.heir) == 9
    assert c.e.exchange.shares_held(firm, "agent", buyer) == 1
    validate_award(c)


def test_zero_cash_dismissal_releases_custodied_securities_without_a_sale(award_case):
    c = award_case
    c.e.ledger.transfer(0, c.wallet, c.e.ledger.system_account(SYS_COMMODITY), 100)
    firm = c.e.firms.found_firm(0, c.person, "Unfunded dispute issuer", "manufacturing", opening_capital_cents=0, shares=10)
    matter, _ = claim(c, 80, contract=False)
    c.e.lifecycle.settle_death(2, c.person)
    assert c.e.ledger.balance(reserve(c, matter)["escrow_account_id"]) == 0
    assert c.e.exchange.shares_held(firm, "agent", c.person) == 10
    transactions = c.e.store.scalar("SELECT COUNT(*) FROM transactions")
    dismiss(c, matter, 3)
    assert c.e.exchange.shares_held(firm, "agent", c.person) == 0
    assert c.e.exchange.shares_held(firm, "agent", c.heir) == 10
    assert c.e.store.scalar("SELECT COUNT(*) FROM transactions") == transactions
    assert c.e.store.scalar("SELECT COUNT(*) FROM trades") == 0
    assert c.e.ledger.balance(c.heir_wallet) == c.e.ledger.balance(c.creditor_wallet) == 0
    validate_award(c)


def test_partial_sales_recover_principal_then_release_unsold_shares_in_kind(estate_case):
    e, bank, person, wallet, heir, heir_wallet, loan, firm, buyer, buyer_wallet = indebted_security_estate(estate_case)
    e.lifecycle.settle_death(1, person)
    estate_id = e.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=?", (person,))
    assert e.exchange.shares_held(firm, "agent", heir) == 0
    assert e.business_control.operator_at(firm) == heir
    sale = order(e, 2, heir, firm, "sell", 10, estate_id=estate_id)
    order(e, 2, buyer, firm, "buy", 3)
    assert sum(fill.qty for fill in e.exchange.match_firm(2, firm)) == 3
    assert e.ledger.balance(e.bank.get(bank)["equity_account_id"]) == -40
    assert e.exchange.shares_held(firm, "agent", person) == 7
    assert e.ledger.balance(heir_wallet) == 0
    assert e.store.scalar("SELECT COUNT(*) FROM estate_security_releases") == 0
    validate(e)
    order(e, 3, buyer, firm, "buy", 2)
    assert sum(fill.qty for fill in e.exchange.match_firm(3, firm)) == 2
    assert e.store.scalar("SELECT status FROM loans WHERE id=?", (loan,)) == "paid"
    assert e.store.scalar("SELECT status FROM orders WHERE id=?", (sale,)) == "cancelled"
    assert e.exchange.shares_held(firm, "agent", person) == 0
    assert e.exchange.shares_held(firm, "agent", heir) == 5
    assert e.exchange.shares_held(firm, "agent", buyer) == 5
    assert e.store.scalar("SELECT qty FROM estate_security_releases") == 5
    assert e.ledger.balance(heir_wallet) == e.ledger.balance(wallet) == 0
    assert e.ledger.balance(buyer_wallet) == 100
    validate(e)


def test_another_real_payment_releases_the_unliquidated_security(estate_case):
    e, bank, person, wallet, heir, _, loan, firm, _, buyer_wallet = indebted_security_estate(estate_case)
    e.lifecycle.settle_death(1, person)
    # Existing counterparty cash pays the debt; no stock price is needed.
    e.ledger.transfer(2, buyer_wallet, wallet, 100, kind="counterparty_payment")
    assert e.exchange.shares_held(firm, "agent", heir) == 10
    assert e.exchange.shares_held(firm, "agent", person) == 0
    assert e.store.scalar("SELECT qty FROM estate_security_releases") == 10
    assert e.store.scalar("SELECT status FROM loans WHERE id=?", (loan,)) == "paid"
    assert e.store.scalar("SELECT COUNT(*) FROM trades") == 0
    validate(e)


@pytest.mark.parametrize("attempt", ["unrelated_actor", "purchase", "too_many", "personal_sale", "before_custody"])
def test_estate_authority_cannot_buy_oversell_or_use_another_persons_identity(estate_case, attempt):
    e, _, person, _, heir, _, _, firm, buyer, _ = indebted_security_estate(estate_case)
    e.lifecycle.settle_death(1, person)
    estate_id = e.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=?", (person,))
    action = dict(type="place_order", estate_id=estate_id, firm_id=firm, side="sell", qty=10, limit_price=20)
    actor, tick = heir, 2
    if attempt == "unrelated_actor":
        actor = buyer
    elif attempt == "purchase":
        action["side"] = "buy"
    elif attempt == "too_many":
        action["qty"] = 11
    elif attempt == "personal_sale":
        action.pop("estate_id")
    else:
        tick = 0
    result = ActionExecutor(e).execute_action(tick, actor, action)
    assert not result["ok"], result
    assert e.store.scalar("SELECT COUNT(*) FROM orders") == 0
    assert e.store.scalar("SELECT COUNT(*) FROM estate_security_orders") == 0
    assert e.exchange.shares_held(firm, "agent", person) == 10
    validate(e)


def test_estate_liquidation_does_not_invent_a_price_for_two_market_orders(estate_case):
    e, _, person, _, heir, _, _, firm, buyer, _ = indebted_security_estate(estate_case)
    e.lifecycle.settle_death(1, person)
    estate_id = e.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=?", (person,))
    order(e, 2, heir, firm, "sell", 10, estate_id=estate_id, price=None)
    order(e, 2, buyer, firm, "buy", 10, price=None)
    assert e.exchange.last_price(firm) is None
    before = canonical_hashes(e.store)["authoritative_sha256"]
    assert e.exchange.match_firm(2, firm) == []
    assert canonical_hashes(e.store)["authoritative_sha256"] == before
    validate(e)


@pytest.mark.parametrize("failure", ["sale_record", "creditor_payment"])
def test_a_late_trade_failure_restores_cash_holdings_claims_and_orders(estate_case, monkeypatch, failure):
    e, _, person, _, heir, _, _, firm, buyer, _ = indebted_security_estate(estate_case)
    e.lifecycle.settle_death(1, person)
    estate_id = e.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=?", (person,))
    order(e, 2, heir, firm, "sell", 10, estate_id=estate_id)
    order(e, 2, buyer, firm, "buy", 10)
    component, name = (e.estate_securities, "record_sale") if failure == "sale_record" else (e.estate_cases, "_disburse")
    original = getattr(component, name)

    def fail_after_record(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected estate sale failure")

    before = canonical_hashes(e.store)["authoritative_sha256"]
    monkeypatch.setattr(component, name, fail_after_record)
    with pytest.raises(RuntimeError, match="injected estate sale"):
        e.exchange.match_firm(2, firm)
    assert canonical_hashes(e.store)["authoritative_sha256"] == before
    assert e.estate_cases._pending is e.estate_cases._security_updates is None
    monkeypatch.setattr(component, name, original)
    assert len(e.exchange.match_firm(2, firm)) == 1
    validate(e)


def test_death_of_a_representative_invalidates_the_quote_and_records_a_descendants_new_authority(estate_case):
    e, bank, person, wallet, heir, heir_wallet, _, firm, buyer, _ = indebted_security_estate(estate_case)
    descendant, descendant_wallet = make_agent(e, bank, "Later beneficiary", cash=0, region_id=1)
    e.households.register_person(0, descendant, "genesis")
    e.store.insert("social_ties", agent_a=heir, agent_b=descendant, weight=2)
    e.lifecycle.settle_death(1, person)
    estate_id = e.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=?", (person,))
    old_order = order(e, 2, heir, firm, "sell", 10, estate_id=estate_id)
    e.lifecycle.settle_death(2, heir)
    order(e, 3, buyer, firm, "buy", 10)
    assert e.exchange.match_firm(3, firm) == []
    assert e.store.scalar("SELECT status FROM orders WHERE id=?", (old_order,)) == "cancelled"
    new_order = order(e, 3, descendant, firm, "sell", 10, estate_id=estate_id)
    assert len(e.exchange.match_firm(3, firm)) == 1
    auth = e.store.query_one("SELECT * FROM estate_security_orders WHERE order_id=?", (new_order,))
    assert len(json.loads(auth["path_json"])) == 2
    assert e.ledger.balance(descendant_wallet) == 100
    assert e.ledger.balance(wallet) == e.ledger.balance(heir_wallet) == 0
    validate(e)


def test_reconciliation_rejects_a_release_that_skips_unpaid_creditors(estate_case, monkeypatch):
    e, _, person, _, heir, _, _, firm, _, _ = indebted_security_estate(estate_case)
    e.lifecycle.settle_death(1, person)
    estate_id = e.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=?", (person,))
    monkeypatch.setattr(e.estate_securities, "needs_custody", lambda *args: False)
    e.estate_securities.release_ready(2, estate_id)
    assert e.exchange.shares_held(firm, "agent", heir) == 10
    assert e.ledger.reconcile()[0]
    with pytest.raises(EstateError, match="before creditor settlement"):
        e.estate_cases.check_invariants()


def test_security_evidence_is_immutable_and_rejects_orphaned_release_rows(estate_case):
    e, _, person, _, heir, _, _, firm, buyer, _ = indebted_security_estate(estate_case)
    e.lifecycle.settle_death(1, person)
    estate_id = e.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=?", (person,))
    order(e, 2, heir, firm, "sell", 10, estate_id=estate_id)
    order(e, 2, buyer, firm, "buy", 10)
    e.exchange.match_firm(2, firm)
    for table in ("estate_security_lots", "estate_security_releases", "estate_security_orders",
                  "estate_security_sales", "estate_security_sale_lots"):
        assert e.store.scalar(f"SELECT COUNT(*) FROM {table}") > 0
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            e.store.execute(f"UPDATE {table} SET id=id")
        with pytest.raises(sqlite3.IntegrityError, match="permanent"):
            e.store.execute(f"DELETE FROM {table}")
    with pytest.raises((sqlite3.IntegrityError, EstateError), match="FOREIGN KEY|orphaned"):
        e.store.insert("estate_security_releases", lot_id=999999, tick=2, qty=0, **e.estate_securities._frontier())
        e.estate_cases.check_invariants()


def test_custody_context_is_private_and_does_not_relabel_the_pool_as_personal_shares(estate_case):
    e, _, person, _, heir, _, _, firm, buyer, _ = indebted_security_estate(estate_case)
    e.lifecycle.settle_death(1, person)
    contexts = e.estate_securities.context_for(heir, 2)
    assert len(contexts) == 1
    position = contexts[0]["securities"][0]
    assert position["firm_id"] == firm and position["custody_qty"] == 10
    assert position["order_scope"]["estate_id"] == contexts[0]["estate_id"]
    assert e.exchange.shares_held(firm, "agent", heir) == 0
    assert e.estate_securities.context_for(buyer, 2) == []
    assert e.estate_securities.context_for(heir, 0) == []
    validate(e)


def test_a_guardian_sells_for_the_minor_and_loses_quote_authority_when_the_ward_is_adult(estate_case):
    e, _, person, _, guardian, _, _, firm, buyer, _ = indebted_security_estate(estate_case)
    child = e.households.birth(1, person)
    membership = e.households.membership(guardian)
    e.store.update("household_memberships", membership["id"], left_tick=1, end_reason="fixture")
    e.store.insert("household_memberships", household_id=e.households.membership(person)["household_id"],
                   agent_id=guardian, role="adult", joined_tick=1)
    e.lifecycle.settle_death(2, person)
    estate_id = e.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=?", (person,))
    assert e.estate_securities.context_for(guardian, 3)[0]["authority"] == "guardian"
    old_order = order(e, 3, guardian, firm, "sell", 10, estate_id=estate_id)
    auth = e.store.query_one("SELECT * FROM estate_security_orders WHERE order_id=?", (old_order,))
    assert auth["beneficiary_id"] == child and auth["guardian_id"] is not None
    # The engine fixture advances eligibility to the child's eighteenth birthday.
    birthday = 1 + 18 * 365
    e.store.update("agents", child, age=18)
    e.households.reconcile_custody(birthday)
    e.business_control.refresh_custody(birthday)
    assert e.store.scalar("SELECT status FROM orders WHERE id=?", (old_order,)) == "cancelled"
    assert e.estate_securities.context_for(guardian, birthday) == []
    order(e, birthday, child, firm, "sell", 10, estate_id=estate_id)
    order(e, birthday, buyer, firm, "buy", 10)
    assert len(e.exchange.match_firm(birthday, firm)) == 1
    assert e.ledger.balance(e.ledger.agent_checking_id(child)) == 100
    validate(e)


def test_a_representatives_home_currency_cannot_redirect_foreign_estate_proceeds(estate_case):
    e, home_bank, person, home_wallet, heir, heir_wallet = estate_case
    e.ledger.transfer(0, home_wallet, e.ledger.system_account(SYS_COMMODITY), 100)
    foreign = foreign_bank(e, "CAD")
    foreign_wallet = e.ledger.create_account("agent", person, "checking", bank_id=foreign, currency_code="CAD")
    loan = spent_loan(e, foreign, person, foreign_wallet, 100)
    e.store.update("agents", person, checking_account_id=foreign_wallet)
    firm = e.firms.found_firm(0, person, "Foreign estate issuer", "manufacturing", shares=10)
    e.store.update("firms", firm, status="listed")
    e.store.update("agents", person, checking_account_id=home_wallet)
    buyer, _ = make_agent(e, home_bank, "Foreign funded buyer", cash=0, region_id=1)
    buyer_wallet = e.ledger.create_account("agent", buyer, "checking", bank_id=foreign, currency_code="CAD", opening_cents=200)
    e.store.update("agents", buyer, checking_account_id=buyer_wallet)
    e.households.register_person(0, buyer, "genesis")
    e.lifecycle.settle_death(1, person)
    estate_id = e.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=?", (person,))
    sale = order(e, 2, heir, firm, "sell", 10, estate_id=estate_id)
    assert e.store.scalar("SELECT account_id FROM estate_security_orders WHERE order_id=?", (sale,)) == foreign_wallet
    order(e, 2, buyer, firm, "buy", 10)
    assert len(e.exchange.match_firm(2, firm)) == 1
    assert e.store.scalar("SELECT status FROM loans WHERE id=?", (loan,)) == "paid"
    assert e.ledger.balance(heir_wallet) == 0
    assert e.store.scalar("SELECT SUM(balance_cents) FROM accounts WHERE owner_type='agent' AND owner_id=? "
                          "AND currency_code='CAD'", (heir,)) == 100
    assert e.ledger.balance(buyer_wallet) == e.ledger.balance(foreign_wallet) == 0
    validate(e)


def test_recorded_decisions_trade_estate_securities_after_restart_and_replay(tmp_path, monkeypatch, caplog):
    config = civic_config()
    config["checkpoint_dir"] = str(tmp_path / "checkpoints")
    config["lifecycle"].update(illness_onset_annual_young=0, illness_onset_annual_old=0)
    identities = {}
    original_draw = Lifecycle._draw

    def forced_death(self, tick, person, mechanism):
        if tick == 1 and person == identities["person"] and mechanism == "mortality":
            return 0.0
        return original_draw(self, tick, person, mechanism)

    monkeypatch.setattr(Lifecycle, "_draw", forced_death)

    def open_seeded(path, settings, *, replay=False):
        world = _world(path, settings, replay=replay)
        e, store = world.economy, world.store
        if store.tick == 0:
            person = available_adult(world)
            wallet = e.ledger.agent_checking_id(person)
            currency = store.scalar("SELECT currency_code FROM accounts WHERE id=?", (wallet,))
            others = store.query("SELECT a.id FROM agents a JOIN accounts ac ON ac.id=a.checking_account_id "
                "WHERE a.alive=1 AND a.kind='citizen' AND a.age>=18 AND a.retired=0 "
                "AND a.id<>? AND ac.currency_code=? AND ac.balance_cents>=10000 ORDER BY ac.balance_cents DESC,a.id LIMIT 2",
                (person, currency))
            assert len(others) == 2
            heir, buyer = (row["id"] for row in others)
            store.insert("social_ties", agent_a=person, agent_b=heir, weight=1000)
            firm = e.firms.found_firm(0, person, "Declared estate issuer", "manufacturing",
                                     opening_capital_cents=10_000, shares=10)
            store.update("firms", firm, status="listed")
            for actor in (person, heir, buyer):
                store.update("agents", actor, cadence_json='{"act":1,"portfolio":9999,"career":9999,"news":9999}')
            for account in store.query("SELECT * FROM accounts WHERE owner_type='agent' AND owner_id=? "
                    "AND kind IN ('checking','savings','fx') AND balance_cents>0 ORDER BY id", (person,)):
                e.ledger.transfer(0, account["id"], e.ledger.system_account(SYS_COMMODITY, currency_code=account["currency_code"]), account["balance_cents"])
            bank = store.scalar("SELECT bank_id FROM accounts WHERE id=?", (wallet,))
            # A declared insolvency stress uses an actual reserves-funded loan.
            # Ordinary day-one transfers may repay some principal before death.
            loan = spent_loan(e, bank, person, wallet, 1_000_000)
            identities.update(person=person, heir=heir, buyer=buyer, firm=firm, loan=loan)
            # Complete the declared genesis after adding its issuer. Reopening
            # must not be what first creates that company's physical workplace.
            e.city.initialize(0)
        adapter = world.gateway.scripted
        for purpose, original in list(adapter.policies.items()):
            def prescribed(context, original=original):
                if replay:
                    raise AssertionError("replay must read recorded decisions")
                actor = context.get("agent", {}).get("id")
                if actor not in (identities["person"], identities["heir"], identities["buyer"]):
                    return original(context)
                actions = [{"type": "do_nothing"}]
                if context["tick"] == 2 and context.get("purpose") in ("decision", "founder"):
                    if actor == identities["heir"]:
                        positions = [(case, item) for case in context.get("estate_securities", [])
                            for item in case["securities"] if item["firm_id"] == identities["firm"]]
                        assert len(positions) == 1
                        actions = [{**positions[0][1]["order_scope"], "qty": 10, "limit_price": 20}]
                    elif actor == identities["buyer"]:
                        assert not any(case["deceased_agent_id"] == identities["person"] for case in context.get("estate_securities", []))
                        actions = [dict(type="place_order", firm_id=identities["firm"], side="buy", qty=10, limit_price=20)]
                return {"reasoning": "Prescribed estate custody acceptance decision.", "actions": actions}
            adapter.register(purpose, prescribed)
        return world

    source_path = tmp_path / "source-securities.db"
    committed = None
    for day in range(1, 4):
        source = open_seeded(source_path, config)
        try:
            if committed is not None:
                assert canonical_hashes(source.store)["authoritative_sha256"] == committed
            asyncio.run(source.step())
            if day >= 2:
                assert source.store.scalar("SELECT SUM(qty) FROM trades WHERE firm_id=?", (identities["firm"],)) == 10
                assert source.store.scalar("SELECT COUNT(*) FROM estate_security_sales") >= 1
            source.economy.estate_cases.check_invariants()
            if day == 3:
                manifest = validate_bundle(export_bundle(source.store, tmp_path / "export"))
                for table in ("estate_security_lots", "estate_security_releases", "estate_security_orders",
                              "estate_security_sales", "estate_security_sale_lots"):
                    assert manifest["tables"][table]["row_count"] > 0
            committed = canonical_hashes(source.store)["authoritative_sha256"]
        finally:
            source.close()
    before = hashlib.sha256(source_path.read_bytes()).hexdigest()
    settings = copy.deepcopy(config)
    settings["replay_source_path"] = str(source_path)
    replay = open_seeded(tmp_path / "replayed-securities.db", settings, replay=True)
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
