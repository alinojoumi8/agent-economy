"""Actual local requests end at departure; ownership and earned debts survive.

Fixtures explicitly enable draft services. No public Semantics-21 profile or
full World replay is enabled by these tests.
"""
import json
import random
import sqlite3
from types import SimpleNamespace

import pytest

from engine.core import Economy
from engine.population import PopulationBoundary
from engine.population_history import ResidenceError
from engine.store import Store

from .test_population_authority import enable_draft, move, age_at, finance, population_property
from .test_population_residence_history import contents
from .test_semantics20_project_rights import property_world
from .test_semantics20_service_commitments import services, prepare_service, act, apply_loan, buy_insurance, money_history
from .test_semantics19_estate_cash import spent_loan
from .test_semantics20_property_sales import sale_case as property_sale_case, bid as property_bid, accept as property_accept
from .test_v2_regions import _qualified_migration_destination


@pytest.fixture
def local_services(services):
    s = services
    enable_draft(SimpleNamespace(economy=s.e, store=s.e.store, runtime=SimpleNamespace(executor=s.executor)))
    return s


def ending(e, kind, source_id):
    return e.store.query_one("SELECT * FROM population_commitment_endings WHERE kind=? AND source_id=?", (kind, source_id))


@pytest.mark.parametrize("kind", ["insurance", "compute", "loan"])
def test_personal_service_ends_atomically_without_refund_or_identity_transfer(local_services, kind):
    s, e = local_services, local_services.e
    table, source_id, closed_status = prepare_service(s, kind)
    original = dict(e.store.query_one(f"SELECT * FROM {table} WHERE id=?", (source_id,)))
    before = finance(e)
    movement = move(e, s.client, 0)
    key = {"insurance": "insurance", "compute": "compute_access", "loan": "loan_application"}[kind]
    record = ending(e, key, source_id)
    assert record["movement_id"] == movement
    assert json.loads(record["evidence_json"])["snapshot"] == original
    assert e.store.scalar(f"SELECT status FROM {table} WHERE id=?", (source_id,)) == closed_status
    assert finance(e) == before
    e.population.commitments.check_invariants()
    move(e, s.client, 1, cause="return", key="back")
    assert e.store.scalar(f"SELECT status FROM {table} WHERE id=?", (source_id,)) == closed_status
    assert finance(e) == before
    assert e.ledger.reconcile()[0]


def test_departed_policyholder_pays_no_later_premium_and_return_needs_new_cover(local_services):
    s, e = local_services, local_services.e
    policy = buy_insurance(s)
    paid = money_history(e, "insurance_premium")
    move(e, s.client, 0)
    for tick in (2, 4):
        e.lifecycle._collect_premiums(tick)
    assert money_history(e, "insurance_premium") == paid
    move(e, s.client, 4, cause="return", key="back")
    e.lifecycle._collect_premiums(6)
    assert money_history(e, "insurance_premium") == paid
    new_policy = act(s, 6, s.client, type="buy_insurance")["policy_id"]
    assert new_policy != policy
    assert e.store.scalar("SELECT status FROM insurance_policies WHERE id=?", (policy,)) == "cancelled"
    e.population.commitments.check_invariants()


@pytest.mark.parametrize("payer,active", [("agent", False), ("agent", True), ("firm", False), ("firm", True), ("government", True)])
def test_departure_ends_paid_compute_without_renewal_or_refund(local_services, payer, active):
    s, e = local_services, local_services.e
    person = s.officer if payer == "government" else s.client
    if payer == "agent":
        subscription = act(s, 0, person, type="buy_compute_plan", tier="flash")["subscription_id"]
        payment_kind = "compute_subscription"
    elif payer == "firm":
        subscription = act(s, 0, s.operator, type="set_compute_sponsorship", firm_id=s.firm,
                           tier="flash", max_seats=1)["subscription_ids"][0]
        payment_kind = "compute_sponsorship"
    else:
        e.cognition.run_nightly(0)
        subscription = e.cognition.current_subscription(person, 0)["id"]
        payment_kind = "public_compute_sponsorship"
    if active and payer != "government":
        e.cognition.run_nightly(1)
    paid = money_history(e, payment_kind)
    tick = 1 if active and payer != "government" else 0
    move(e, person, tick)
    for later in (tick+1, tick+4):
        e.cognition.run_nightly(later)
        assert e.cognition.current_subscription(person, later) is None
    assert e.store.scalar("SELECT status FROM compute_subscriptions WHERE id=?", (subscription,)) == "cancelled"
    assert e.store.scalar("SELECT COUNT(*) FROM compute_subscriptions WHERE agent_id=?", (person,)) == 1
    assert money_history(e, payment_kind) == paid
    e.population.commitments.check_invariants()


def test_personal_loan_request_expires_but_disbursed_loan_keeps_its_payment_schedule(local_services):
    s, e = local_services, local_services.e
    first = apply_loan(s)
    approved = act(s, 0, s.officer, type="approve_loan", application_id=first, rate_bps=300, term_ticks=30)
    e.bank.process_due_loans(7)
    loan = dict(e.store.query_one("SELECT * FROM loans WHERE id=?", (approved["loan_id"],)))
    # A fresh request follows the bank's one-week application interval.
    pending = apply_loan(s, tick=8, amount=2000)
    before = finance(e)
    move(e, s.client, 8)
    assert finance(e) == before
    assert not s.executor.execute_action(10, s.officer, {"type": "approve_loan", "application_id": pending})["ok"]
    assert dict(e.store.query_one("SELECT * FROM loans WHERE id=?", (loan["id"],))) == loan
    e.bank.process_due_loans(loan["next_due_tick"])
    assert e.store.scalar("SELECT outstanding_cents FROM loans WHERE id=?", (loan["id"],)) < loan["outstanding_cents"]
    assert not e.population.is_available(s.client)
    assert e.ledger.reconcile()[0]


def test_departing_operator_keeps_company_request_and_employees_compute(local_services):
    s, e = local_services, local_services.e
    request = apply_loan(s, as_firm=True)
    subscription = act(s, 0, s.operator, type="set_compute_sponsorship", firm_id=s.firm,
                       tier="flash", max_seats=1)["subscription_ids"][0]
    # Declared co-ownership gives the existing resident a succession interest.
    e.exchange._adjust_shares(s.firm, "agent", s.operator, -100)
    e.exchange._adjust_shares(s.firm, "agent", s.heir, 100)
    before_request = dict(e.store.query_one("SELECT * FROM loan_applications WHERE id=?", (request,)))
    before_subscription = dict(e.store.query_one("SELECT * FROM compute_subscriptions WHERE id=?", (subscription,)))
    move(e, s.operator, 0)
    assert dict(e.store.query_one("SELECT * FROM loan_applications WHERE id=?", (request,))) == before_request
    assert dict(e.store.query_one("SELECT * FROM compute_subscriptions WHERE id=?", (subscription,))) == before_subscription
    assert e.business_control.operator_at(s.firm) == s.heir
    assert act(s, 2, s.officer, type="approve_loan", application_id=request)["loan_id"]
    e.cognition.run_nightly(2)
    assert e.cognition.current_subscription(s.client, 2)["id"] == subscription
    assert e.ledger.reconcile()[0]


@pytest.mark.parametrize("side", ["buy", "sell"])
def test_partial_stock_order_cancels_only_its_unfilled_remainder(local_services, side):
    s, e = local_services, local_services.e
    e.store.update("firms", s.firm, status="listed")
    person = s.client if side == "buy" else s.operator
    counterparty = s.operator if side == "buy" else s.client
    order = e.exchange.place_order(0, person, s.firm, side, 5, 10)
    assert order is not None
    other = "sell" if side == "buy" else "buy"
    assert e.exchange.place_order(0, counterparty, s.firm, other, 1, 10) is not None
    assert sum(fill.qty for fill in e.exchange.match_firm(0, s.firm)) == 1
    original = dict(e.store.query_one("SELECT * FROM orders WHERE id=?", (order,)))
    assert original["status"] == "partial"
    before = finance(e)
    move(e, person, 0)
    assert e.store.scalar("SELECT status FROM orders WHERE id=?", (order,)) == "cancelled"
    assert json.loads(ending(e, "stock_order", order)["evidence_json"])["snapshot"] == original
    assert e.exchange.place_order(2, counterparty, s.firm, other, 4, 10) is not None
    assert e.exchange.match_firm(2, s.firm) == []
    assert finance(e) == before
    assert e.ledger.reconcile()[0]


def test_ipo_bid_withdraws_without_a_cash_refund_or_new_share_allocation(local_services):
    s, e = local_services, local_services.e
    opened = e.firms.open_ipo(30, s.operator, s.firm, 100, 10)
    assert opened["ok"], opened
    offered = e.firms.place_ipo_bid(30, s.client, opened["offering_id"], 100, 10)
    assert offered["ok"], offered
    before = finance(e)
    move(e, s.client, 30)
    assert e.store.scalar("SELECT status FROM ipo_bids WHERE id=?", (offered["bid_id"],)) == "cancelled"
    e.firms.close_ipo(31, s.operator, opened["offering_id"])
    assert e.store.scalar("SELECT status FROM ipo_offerings WHERE id=?", (opened["offering_id"],)) != "listed"
    assert finance(e) == before
    assert e.exchange.shares_held(s.firm, "agent", s.client) == 0


def test_fx_order_cannot_buy_currency_after_departure(population_property):
    world, owner, _ = population_property
    e = world.economy
    quote = e.store.scalar("SELECT currency_code FROM accounts WHERE id=?", (owner["checking_account_id"],))
    base = e.store.scalar("SELECT code FROM currencies WHERE code<>? ORDER BY code LIMIT 1", (quote,))
    order = e.regions.place_fx_order(1, owner["id"], {"pair": f"{base}/{quote}", "side": "buy", "qty": 10})
    assert order["ok"], order
    before = finance(e)
    move(e, owner["id"], 1)
    assert e.store.scalar("SELECT status FROM fx_orders WHERE id=?", (order["order_id"],)) == "cancelled"
    assert e.regions.match_fx(2) == []
    assert finance(e) == before


def test_pending_internal_migration_cannot_move_an_outside_household(population_property):
    world, _, _ = population_property
    e = world.economy
    owner = e.store.query_one("SELECT a.* FROM agents a WHERE a.kind='citizen' AND a.alive=1 AND a.age>=18 "
        "AND a.health='healthy' AND a.retired=0 AND a.role IS NULL AND NOT EXISTS "
        "(SELECT 1 FROM employments j WHERE j.agent_id=a.id AND j.status='active') ORDER BY a.id LIMIT 1")
    assert owner is not None
    destination, tick = _qualified_migration_destination(e.store, owner)
    request = e.regions.request_migration(tick, owner["id"], destination, "Work opportunity")
    assert request["ok"], request
    move(e, owner["id"], tick)
    before = finance(e)
    e.regions.run_nightly(tick+1)
    assert e.store.scalar("SELECT status FROM migrations WHERE id=?", (request["migration_id"],)) == "cancelled"
    assert e.store.scalar("SELECT region_id FROM agents WHERE id=?", (owner["id"],)) == owner["region_id"]
    assert finance(e) == before


@pytest.mark.parametrize("kind", ["insurance", "compute", "loan"])
@pytest.mark.parametrize("damage", ["status", "holder", "terms", "event"])
def test_independent_commitment_audit_rejects_reactivation_or_changed_source(local_services, kind, damage):
    s, e = local_services, local_services.e
    table, source_id, _ = prepare_service(s, kind)
    movement = move(e, s.client, 0)
    if damage == "event":
        row = e.store.query_one("SELECT * FROM population_commitment_endings ORDER BY id LIMIT 1")
        e.store.update("events", row["event_id"], payload_json="{}")
    else:
        field, value = {
            "status": ("status", "pending" if kind != "insurance" else "active"),
            "holder": ("borrower_id" if kind == "loan" else "agent_id", s.heir),
            "terms": ({"loan": "amount_cents", "compute": "price_cents", "insurance": "premium_cents"}[kind], 9876),
        }[damage]
        e.store.update(table, source_id, **{field: value})
    with pytest.raises(ResidenceError, match="commitment"):
        e.population.commitments.check_invariants()
    before_retry = contents(e.store)
    with pytest.raises(ResidenceError, match="commitment"):
        e.population.settle(1, movement)
    assert contents(e.store) == before_retry


def test_ending_record_is_immutable_and_an_orphan_event_fails_audit(local_services):
    s, e = local_services, local_services.e
    buy_insurance(s)
    move(e, s.client, 0)
    for sql in ("UPDATE population_commitment_endings SET tick=2", "DELETE FROM population_commitment_endings"):
        with pytest.raises(sqlite3.IntegrityError):
            e.store.execute(sql)
    row = e.store.query_one("SELECT * FROM population_commitment_endings ORDER BY id LIMIT 1")
    e.store.log_event(1, "population_commitment_ended", json.loads(row["evidence_json"]),
                      phase="NIGHT_CLOSE", subject_type="agent", subject_id=s.client)
    with pytest.raises(ResidenceError, match="immutable record"):
        e.population.commitments.check_invariants()


def test_failure_after_services_end_restores_every_group_effect(local_services, monkeypatch):
    s, e = local_services, local_services.e
    for kind in ("insurance", "compute", "loan"):
        prepare_service(s, kind)
    movement = e.population.propose(0, s.client, "departure", [s.client], "atomic", due_tick=1)["movement_id"]
    age_at(e, 1)
    before = contents(e.store)
    original = e.civic_authority.release_for_departure

    def fail(*args):
        original(*args)
        raise RuntimeError("injected later closure")

    monkeypatch.setattr(e.civic_authority, "release_for_departure", fail)
    with pytest.raises(RuntimeError, match="injected later"):
        e.population.settle(1, movement)
    assert contents(e.store) == before


def test_commitment_history_reopens_and_terminal_movement_does_not_repeat_it(local_services):
    s, e = local_services, local_services.e
    buy_insurance(s)
    movement = move(e, s.client, 0)
    before = contents(e.store)
    path = e.store.conn.execute("PRAGMA database_list").fetchone()[2]
    e.store.close()
    reopened = Store(path)
    try:
        restored = Economy(reopened, e.config, random.Random(1), random.Random(2))
        restored.engine_semantics_version = 21
        restored.population = PopulationBoundary(restored)
        restored.population.commitments.check_invariants()
        assert restored.population.settle(1, movement)["status"] == "applied"
        assert contents(reopened) == before
    finally:
        reopened.close()


def test_property_bid_ends_on_departure_and_past_reason_survives_return(population_property):
    c = property_sale_case(population_property)
    offered = property_bid(c)
    assert offered["ok"], offered
    before = finance(c.e)
    move(c.e, c.buyer["id"], 10)
    assert c.store.scalar("SELECT reason FROM estate_property_bid_ends WHERE bid_id=?", (offered["bid_id"],)) == "buyer_unavailable"
    assert not property_accept(c, offered["bid_id"])["ok"]
    assert finance(c.e) == before
    move(c.e, c.buyer["id"], 11, cause="return", key="buyer-back")
    c.e.estate_property_sales.check_invariants()
    assert finance(c.e) == before


def private_share_case(s):
    e = s.e
    # This compact service fixture declares its currency explicitly, as the
    # normal regional genesis does before creating a currency-bound sale.
    e.store.execute("INSERT INTO currencies(code,name,numeraire_rate_ppm,issuer_region_id) "
                    "VALUES('USD','US dollar',1000000,1) ON CONFLICT(code) DO NOTHING")
    wallet = e.ledger.agent_checking_id(s.operator)
    spent_loan(e, s.bank, s.operator, wallet, 500_000)
    age_at(e, 1)
    e.lifecycle.settle_death(1, s.operator)
    estate = e.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=?", (s.operator,))
    lot = e.estate_securities.lots(estate)[0]
    currency = e.store.scalar("SELECT currency_code FROM accounts WHERE id=?", (e.ledger.agent_checking_id(s.client),))
    offered = act(s, 1, s.client, type="place_estate_unlisted_bid", lot_id=lot["id"], qty=lot["qty"],
        buyer_account_id=e.ledger.agent_checking_id(s.client), amount_cents=1000, currency_code=currency,
        expires_tick=6, request_key="funded-client")
    return offered


def test_private_share_bid_ends_without_distributing_the_estate(local_services):
    s, e = local_services, local_services.e
    offered = private_share_case(s)
    before = finance(e)
    move(e, s.client, 1)
    assert e.store.scalar("SELECT reason FROM estate_unlisted_bid_ends WHERE bid_id=?", (offered["bid_id"],)) == "buyer_unavailable"
    assert not s.executor.execute_action(2, s.heir, {"type": "accept_estate_unlisted_bid", "bid_id": offered["bid_id"]})["ok"]
    assert finance(e) == before
    move(e, s.client, 2, cause="return", key="private-buyer-back")
    e.estate_unlisted_sales.check_invariants()
    assert finance(e) == before


def test_recorded_property_buyer_death_still_supports_ending_with_residence_enabled(population_property):
    c = property_sale_case(population_property)
    offered = property_bid(c)
    assert offered["ok"], offered
    age_at(c.e, 11)
    c.e.lifecycle.settle_death(11, c.buyer["id"])
    c.e.estate_property_sales.reconcile(11)
    assert c.store.scalar("SELECT reason FROM estate_property_bid_ends WHERE bid_id=?", (offered["bid_id"],)) == "buyer_unavailable"
    c.e.estate_property_sales.check_invariants()
    opened = c.store.scalar("SELECT completed_event_id FROM estate_cases WHERE deceased_agent_id=?", (c.buyer["id"],))
    assert not c.e.estate_property_sales.buyer_unavailable_at(c.buyer["id"], 10, opened)
    assert not c.e.estate_property_sales.buyer_unavailable_at(c.buyer["id"], 11, opened)
    assert c.e.ledger.reconcile()[0]


def test_recorded_private_buyer_death_still_supports_ending_with_residence_enabled(local_services):
    s, e = local_services, local_services.e
    offered = private_share_case(s)
    age_at(e, 2)
    e.lifecycle.settle_death(2, s.client)
    e.estate_unlisted_sales.reconcile(2)
    assert e.store.scalar("SELECT reason FROM estate_unlisted_bid_ends WHERE bid_id=?", (offered["bid_id"],)) == "buyer_unavailable"
    e.estate_unlisted_sales.check_invariants()
    opened = e.store.scalar("SELECT completed_event_id FROM estate_cases WHERE deceased_agent_id=?", (s.client,))
    assert not e.estate_unlisted_sales.buyer_unavailable_at(s.client, 1, opened)
    assert not e.estate_unlisted_sales.buyer_unavailable_at(s.client, 2, opened)
    assert e.ledger.reconcile()[0]
