"""Ownership and operating authority across generations; expanded with estates."""
from __future__ import annotations

import json
import random

import pytest

from agents.memory import Memory
from agents.prompts import ContextBuilder
from engine.actions import ActionExecutor
from engine.core import Economy
from engine.business_control import operated_firms_at
from research.hashing import canonical_hashes

from .conftest import make_agent, make_bank


@pytest.fixture
def succession(store):
    config = {"engine_semantics_version": 20, "seed": 1,
              "lifecycle": {"birth_annual_prob": 0, "population_mode": "drift"}}
    store.execute("UPDATE run_meta SET config_json=?", (json.dumps(config),))
    e = Economy(store, config, random.Random(1), random.Random(2))
    e.ensure_system_accounts()
    bank = make_bank(e)
    founder, _ = make_agent(e, bank, "Founder", cash=200_000)
    heir, _ = make_agent(e, bank, "Heir", cash=0)
    outsider, _ = make_agent(e, bank, "Outsider", cash=0)
    firm = e.firms.found_firm(0, founder, "Continuing firm", "manufacturing", opening_capital_cents=100_000)
    store.insert("social_ties", agent_a=founder, agent_b=heir, weight=1)
    e.households.initialize()
    return e, bank, founder, heir, outsider, firm


def check(e):
    e.business_control.check_invariants()
    e.cash_estates.check_invariants()
    e.estate_cases.check_invariants()
    e.daily_time.check_invariants()
    assert e.ledger.reconcile()[0]


def test_successor_can_price_and_work_without_rewriting_founder(succession):
    e, _, founder, heir, outsider, firm = succession
    executor = ActionExecutor(e)
    assert not executor.execute_action(0, heir, {"type": "set_price", "firm_id": firm, "price": 333})["ok"]
    e.lifecycle.settle_death(1, founder)
    assert e.store.scalar("SELECT founder_agent_id FROM firms WHERE id=?", (firm,)) == founder
    assert e.business_control.operator_at(firm, 0) == founder
    assert e.business_control.operator_at(firm, 1) == heir
    assert e.business_control.operator_at(firm) == heir
    assert [row["id"] for row in operated_firms_at(e.store, founder, 0)] == [firm]
    assert operated_firms_at(e.store, heir, 0) == []
    assert [row["id"] for row in operated_firms_at(e.store, heir, 1)] == [firm]
    assert e.exchange.shares_held(firm, "agent", heir) == 1000
    assert e.exchange.shares_held(firm, "agent", founder) == 0
    assert executor.execute_action(1, heir, {"type": "set_price", "firm_id": firm, "price": 333})["ok"]
    assert e.firms.product(e.firms.get(firm))["unit_price_cents"] == 333
    assert not executor.execute_action(1, outsider, {"type": "set_price", "firm_id": firm, "price": 1})["ok"]
    assert not e.legal.controls(founder, "firm", firm)
    assert e.legal.controls(heir, "firm", firm)
    assert e.construction._controls_firm(heir, firm)
    context = ContextBuilder(e, Memory(e.store, e.config), e.config)
    actor = e.store.query_one("SELECT * FROM agents WHERE id=?", (heir,))
    assert context.purpose_for(actor) == "founder"
    assert context.build(actor, 1)["my_firm"]["firm_id"] == firm
    e.daily_time.prepare_day(1)
    e.firms.produce(1)
    assert e.store.scalar("SELECT delivered_minutes FROM time_allocations WHERE agent_id=? AND kind='owner_work'", (heir,)) == 480
    assert e.store.scalar("SELECT inventory FROM firms WHERE id=?", (firm,)) > 0
    check(e)


def test_no_heir_preserves_securities_and_an_existing_manager_can_operate(succession):
    e, _, founder, _, manager, firm = succession
    e.store.execute("DELETE FROM social_ties")
    e.store.update("agents", manager, role="manager", employer_id=firm)
    e.store.insert("employments", agent_id=manager, firm_id=firm, wage_cents=30_000,
                   pay_interval_ticks=30, start_tick=0, next_pay_tick=30, status="active")
    e.lifecycle.settle_death(1, founder)
    assert e.firms.get(firm)["status"] == "private"
    assert e.exchange.shares_held(firm, "system", 0) == 1000
    assert e.business_control.operator_at(firm) == manager
    assert e.business_control.controls(manager, firm)
    assert e.store.scalar("SELECT capacity FROM firm_stewardships WHERE ended_tick IS NULL") == "employee"
    check(e)


def test_a_minor_owns_shares_while_the_guardian_has_temporary_operating_authority(succession):
    e, _, founder, guardian, _, firm = succession
    child = e.households.birth(1, founder)
    membership = e.households.membership(guardian)
    e.store.update("household_memberships", membership["id"], left_tick=1, end_reason="fixture")
    e.store.insert("household_memberships", household_id=e.households.membership(founder)["household_id"],
                   agent_id=guardian, role="adult", joined_tick=1)
    e.store.insert("social_ties", agent_a=founder, agent_b=child, weight=10)
    e.lifecycle.settle_death(2, founder)
    assert e.exchange.shares_held(firm, "agent", child) == 1000
    assert e.exchange.shares_held(firm, "agent", guardian) == 0
    assert e.business_control.operator_at(firm) == guardian
    assert not e.business_control.controls(child, firm)
    assert e.business_control.controls(guardian, firm)
    e.store.update("agents", child, age=18)
    e.households.reconcile_custody(3)
    e.business_control.refresh_custody(3)
    assert e.business_control.operator_at(firm, 2) == guardian
    assert e.business_control.operator_at(firm, 3) == child
    assert e.business_control.controls(child, firm)
    assert not e.business_control.controls(guardian, firm)
    assert e.store.scalar("SELECT COUNT(*) FROM employments WHERE agent_id=?", (child,)) == 0
    check(e)


def test_successor_death_transfers_operation_again_and_duplicate_death_is_inert(succession):
    e, _, founder, heir, next_heir, firm = succession
    e.store.insert("social_ties", agent_a=heir, agent_b=next_heir, weight=2)
    e.lifecycle.settle_death(1, founder)
    e.lifecycle.settle_death(2, heir)
    assert e.business_control.operator_at(firm, 0) == founder
    assert e.business_control.operator_at(firm, 1) == heir
    assert e.business_control.operator_at(firm, 2) == next_heir
    assert e.exchange.shares_held(firm, "agent", next_heir) == 1000
    before = canonical_hashes(e.store)["authoritative_sha256"]
    e.lifecycle.settle_death(3, founder)
    e.lifecycle.settle_death(3, heir)
    assert canonical_hashes(e.store)["authoritative_sha256"] == before
    check(e)


def test_late_stewardship_failure_rolls_back_the_whole_death(succession, monkeypatch):
    e, _, founder, _, _, _ = succession
    before = canonical_hashes(e.store)["authoritative_sha256"]
    def fail(*args, **kwargs):
        raise RuntimeError("injected stewardship failure")
    monkeypatch.setattr(e.business_control, "replace", fail)
    with pytest.raises(RuntimeError, match="injected"):
        e.lifecycle.settle_death(1, founder)
    assert canonical_hashes(e.store)["authoritative_sha256"] == before
    check(e)


def test_weighted_share_distribution_conserves_integer_units(succession):
    e, _, founder, heir, other, firm = succession
    second = e.firms.found_firm(0, founder, "Indivisible shares", "manufacturing", shares=1001)
    e.business_control.distribute_shares(1, founder, [(other, 1), (heir, 1)])
    assert e.exchange.shares_held(firm, "agent", heir) == 500
    assert e.exchange.shares_held(firm, "agent", other) == 500
    assert e.store.scalar("SELECT SUM(qty) FROM shares WHERE firm_id=?", (firm,)) == 1000
    assert e.store.scalar("SELECT shares_outstanding FROM firms WHERE id=?", (firm,)) == 1000
    assert e.exchange.shares_held(second, "agent", heir) == 501
    assert e.exchange.shares_held(second, "agent", other) == 500
    movements = e.store.query("SELECT * FROM share_movements WHERE movement_type='estate_inheritance'")
    assert len(movements) == 4 and sum(row["qty"] for row in movements) == 2001
    assert all(row["price_cents"] is None and row["amount_cents"] == 0 and row["transaction_id"] is None for row in movements)
    check(e)
