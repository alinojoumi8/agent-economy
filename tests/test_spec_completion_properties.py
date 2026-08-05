"""Property-style and hard-rule evidence for TECH-SPEC sections 5, 8, 9, and 14."""
from __future__ import annotations

import asyncio
import json
import random

import pytest
from fastapi.testclient import TestClient

import run as cli
from agents.policies import (
    citizen_decision,
    credit_officer_decision,
    founder_decision,
    workforce_recovery_actions,
)
from agents.prompts import ContextBuilder, SYSTEM_PREFIX
from agents.runtime import _gather_fail_fast
from engine.actions import ActionExecutor
from engine.credit import LoanTerms
from llm.adapters import AdapterResult
from llm.gateway import (
    Gateway,
    LLMRequest,
    ProviderUnavailable,
    sanitize_provider_error,
    sanitize_provider_raw,
)
from run import DEFAULT_CONFIG
from server.app import create_app
from tests.conftest import make_agent, make_bank
from world.loop import World
from world.replay_verify import verify_replay
from world.shocks import Shocks


def _listed_firm(economy, founder: int, name: str = "ListedCo") -> int:
    firm_id = economy.firms.found_firm(0, founder, name, "tech")
    economy.store.update("firms", firm_id, status="listed")
    return firm_id


def test_real_provider_prompt_exposes_counterparty_ids_as_json_integers():
    context = {
        "agent": {"name": "Buyer", "age": 30, "occupation": "teacher"},
        "prices": [{"firm_id": 7, "product": "food_good", "price": 120,
                    "inventory": 9}],
        "jobs": [{"job_id": 2, "firm_id": 7, "title": "teacher", "wage": 500}],
    }
    system, user = ContextBuilder.__new__(ContextBuilder).render_prompt(context)

    assert '"firm_id":7' in user
    assert '"job_id":2' in user
    assert "firm7:" not in user and "job2@" not in user
    assert system == SYSTEM_PREFIX
    assert "MUST be a JSON integer" in system


def test_inventory_aware_shoppers_do_not_all_herd_to_one_seller():
    selected_firms = set()
    for seed in range(1, 61):
        decision = citizen_decision({
            "rng_seed": seed,
            "inventory_aware_shopping_enabled": True,
            "agent": {
                "id": seed, "health": "healthy", "retired": False,
                "dependents": 0, "risk_tolerance": 0.5,
            },
            "state": {
                "checking_balance": 100_000, "employed": True, "shares": {},
            },
            "beliefs": {},
            "news": [],
            "heard": [],
            "prices": [
                {"firm_id": 1, "product": "food", "price": 100, "inventory": 100},
                {"firm_id": 2, "product": "food", "price": 100, "inventory": 100},
                {"firm_id": 3, "product": "food", "price": 100, "inventory": 100},
            ],
            "jobs": [],
            "banks": [],
        })
        selected_firms.add(next(
            action["firm_id"] for action in decision["actions"]
            if action["type"] == "buy_goods"))

    assert selected_firms == {1, 2, 3}


def test_scripted_founder_posts_one_job_at_genesis_wage_when_below_target():
    decision = founder_decision({
        "workforce_recovery_enabled": True,
        "agent": {"id": 7, "health": "healthy"},
        "state": {"checking_balance": 100_000},
        "my_firm": {
            "firm_id": 4,
            "name": "Capacity Co",
            "inventory": 20,
            "price": 500,
            "unit_cost": 200,
            "cash": 2_000_000,
            "employees": 2,
            "payroll": 500_000,
            "recent_sales": 10,
            "target_headcount": 3,
            "open_jobs": 0,
            "has_pending_loan": False,
            "has_pending_pitch": False,
            "is_private": True,
        },
        "firm_applications": [],
        "firm_job_offers": [],
    })

    assert [
        action for action in decision["actions"] if action["type"] == "post_job"
    ] == [{
        "type": "post_job",
        "firm_id": 4,
        "title": "worker",
        "wage": 250_000,
    }]


def test_operational_recovery_uses_founder_default_when_target_is_missing():
    context = {
        "workforce_recovery_enabled": True,
        "workforce_recovery_operational_enabled": True,
        "workforce_recovery_batch_size": 4,
        "my_firm": {
            "firm_id": 4,
            "sector": "manufacturing",
            "inventory": 20,
            "price": 500,
            "unit_cost": 200,
            "cash": 2_000_000,
            "employees": 2,
            "payroll": 500_000,
            "open_jobs": 0,
        },
        "firm_applications": [],
        "firm_job_offers": [],
    }

    assert workforce_recovery_actions(context) == [{
        "type": "post_job",
        "firm_id": 4,
        "title": "worker",
        "wage": 250_000,
    }]


def test_operational_workforce_recovery_posts_a_bounded_batch_at_genesis_wage():
    context = {
        "workforce_recovery_enabled": True,
        "workforce_recovery_operational_enabled": True,
        "workforce_recovery_batch_size": 4,
        "my_firm": {
            "firm_id": 4,
            "sector": "manufacturing",
            "inventory": 20,
            "price": 500,
            "unit_cost": 200,
            "cash": 40_000_000,
            "employees": 3,
            "payroll": 750_000,
            "target_headcount": 80,
            "open_jobs": 1,
        },
        "firm_applications": [],
        "firm_job_offers": [],
    }

    actions = workforce_recovery_actions(
        context,
        proposed_actions=[{
            "type": "post_job",
            "firm_id": 4,
            "title": "worker",
            "wage": 250_000,
        }],
    )

    assert actions == [{
        "type": "post_job",
        "firm_id": 4,
        "title": "worker",
        "wage": 250_000,
    }] * 3


def test_operational_workforce_recovery_advances_pending_hiring_stages():
    actions = workforce_recovery_actions({
        "workforce_recovery_enabled": True,
        "workforce_recovery_operational_enabled": True,
        "workforce_recovery_batch_size": 4,
        "my_firm": {
            "firm_id": 4,
            "sector": "manufacturing",
            "inventory": 20,
            "price": 500,
            "unit_cost": 200,
            "cash": 40_000_000,
            "employees": 3,
            "payroll": 750_000,
            "target_headcount": 80,
            "open_jobs": 2,
        },
        "firm_applications": [{
            "application_id": 10,
            "posted_wage": 250_000,
            "current_offer_id": None,
            "job_pending_offer_count": 0,
        }],
        "firm_job_offers": [{
            "offer_id": 20,
            "application_id": 11,
            "requested_wage": 260_000,
        }],
    })

    assert actions[:2] == [
        {"type": "accept_job_offer", "offer_id": 20},
        {"type": "make_job_offer", "application_id": 10, "wage": 250_000},
    ]
    assert actions[2:] == [{
        "type": "post_job",
        "firm_id": 4,
        "title": "worker",
        "wage": 250_000,
    }] * 4


def test_operational_recovery_respects_combined_payroll_and_headcount():
    actions = workforce_recovery_actions({
        "workforce_recovery_enabled": True,
        "workforce_recovery_operational_enabled": True,
        "workforce_recovery_batch_size": 4,
        "my_firm": {
            "firm_id": 4,
            "sector": "manufacturing",
            "inventory": 20,
            "price": 500,
            "unit_cost": 200,
            "cash": 1_050_000,
            "employees": 1,
            "payroll": 500_000,
            "target_headcount": 3,
            "open_jobs": 0,
        },
        "firm_applications": [{
            "application_id": 10,
            "posted_wage": 250_000,
            "current_offer_id": None,
            "job_pending_offer_count": 0,
        }],
        "firm_job_offers": [{
            "offer_id": 20,
            "application_id": 11,
            "requested_wage": 300_000,
        }],
    })

    assert actions == [
        {"type": "accept_job_offer", "offer_id": 20},
        {"type": "make_job_offer", "application_id": 10, "wage": 250_000},
    ]


def test_operational_workforce_recovery_reserves_jobs_with_pending_offers():
    actions = workforce_recovery_actions({
        "workforce_recovery_enabled": True,
        "workforce_recovery_operational_enabled": True,
        "workforce_recovery_batch_size": 1,
        "my_firm": {
            "firm_id": 4,
            "price": 500,
            "cash": 40_000_000,
            "employees": 3,
            "payroll": 750_000,
            "target_headcount": 80,
            "open_jobs": 2,
        },
        "firm_applications": [{
            "application_id": 10,
            "posted_wage": 250_000,
            "current_offer_id": None,
            "job_pending_offer_count": 1,
        }, {
            "application_id": 11,
            "posted_wage": 250_000,
            "current_offer_id": None,
            "job_pending_offer_count": 0,
        }],
        "firm_job_offers": [],
    })

    assert actions[0] == {
        "type": "make_job_offer",
        "application_id": 11,
        "wage": 250_000,
    }


def test_application_aware_job_seekers_distribute_across_equal_openings():
    selected_jobs = set()
    for seed in range(1, 61):
        decision = citizen_decision({
            "rng_seed": seed,
            "job_application_aware_enabled": True,
            "agent": {
                "id": seed, "health": "healthy", "retired": False,
                "dependents": 0, "risk_tolerance": 0.5,
            },
            "state": {
                "checking_balance": 0, "employed": False, "shares": {},
            },
            "beliefs": {},
            "news": [],
            "heard": [],
            "prices": [],
            "jobs": [
                {"job_id": 1, "firm_id": 1, "wage": 250_000,
                 "application_count": 0},
                {"job_id": 2, "firm_id": 2, "wage": 250_000,
                 "application_count": 0},
                {"job_id": 3, "firm_id": 3, "wage": 250_000,
                 "application_count": 0},
            ],
            "banks": [],
        })
        selected_jobs.add(next(
            action["job_id"] for action in decision["actions"]
            if action["type"] == "apply_job"))

    assert selected_jobs == {1, 2, 3}


def test_real_provider_prompt_disambiguates_cents_from_currency_units():
    context = {
        "agent": {"name": "Counsel", "age": 51, "occupation": "lawyer"},
        "state": {
            "checking_balance": 300_000, "bank_id": 1, "currency_code": "NSD",
            "debt": 0, "employed": False, "net_worth": 300_000, "shares": {},
        },
    }

    system, user = ContextBuilder.__new__(ContextBuilder).render_prompt(context)

    assert "300000 cents equals 3000.00 currency units" in system
    assert "checking_balance_cents=300000 cents (= 3000.00 NSD)" in user
    assert "net_worth_cents=300000 cents (= 3000.00 NSD)" in user


def test_provider_batch_failure_cancels_outstanding_work():
    state = {"cancelled": 0}

    async def fail():
        await asyncio.sleep(0.01)
        raise RuntimeError("provider unavailable")

    async def slow():
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            state["cancelled"] += 1
            raise

    async def scenario():
        with pytest.raises(RuntimeError, match="provider unavailable"):
            await _gather_fail_fast([fail(), slow(), slow()])

    asyncio.run(scenario())
    assert state["cancelled"] == 2


def test_actions_require_living_actor_and_counterparty(economy):
    bank = make_bank(economy)
    sender, _ = make_agent(economy, bank, "Sender", 10_000)
    recipient, recipient_acct = make_agent(economy, bank, "Recipient", 10_000)
    executor = ActionExecutor(economy)

    economy.store.update("agents", sender, alive=0)
    dead_actor = executor.execute_action(1, sender, {"type": "do_nothing"})
    assert not dead_actor["ok"] and dead_actor["reason"] == "actor not alive"

    economy.store.update("agents", sender, alive=1)
    economy.store.update("agents", recipient, alive=0)
    dead_counterparty = executor.execute_action(
        1, sender, {"type": "transfer", "to_account": recipient_acct, "amount": 100})
    assert not dead_counterparty["ok"] and "not alive" in dead_counterparty["reason"]

    missing = executor.execute_action(1, 999_999, {"type": "do_nothing"})
    assert not missing["ok"] and missing["reason"] == "actor missing"


def test_action_handler_exception_rolls_back_partial_writes(economy, monkeypatch):
    bank = make_bank(economy)
    actor, _ = make_agent(economy, bank, "Atomic Actor", 10_000)
    executor = ActionExecutor(economy)

    def fail_after_write(tick, actor_id, action, phase):
        economy.store.log_event(
            tick, "partial_action_write", {"actor_id": actor_id}, phase=phase)
        raise RuntimeError("handler failed after writing")

    monkeypatch.setattr(executor, "_do_do_nothing", fail_after_write)
    result = executor.execute_action(1, actor, {"type": "do_nothing"})

    assert not result["ok"] and "handler failed after writing" in result["reason"]
    assert economy.store.scalar(
        "SELECT COUNT(*) FROM events WHERE kind='partial_action_write'", default=0) == 0
    assert economy.store.scalar(
        "SELECT COUNT(*) FROM events WHERE kind='action_rejected'", default=0) == 1


def test_engine_does_not_rewrite_counterparty_or_invent_market_price(economy):
    bank = make_bank(economy)
    buyer, _ = make_agent(economy, bank, "Buyer", 100_000)
    seller, _ = make_agent(economy, bank, "Seller", 100_000)
    alternative_owner, _ = make_agent(economy, bank, "Alternative", 100_000)
    empty_firm = economy.firms.found_firm(0, seller, "Empty", "retail")
    stocked_firm = economy.firms.found_firm(0, alternative_owner, "Stocked", "retail")
    economy.store.update("firms", stocked_firm, inventory=20)
    executor = ActionExecutor(economy)

    rejected = executor.execute_action(
        1, buyer, {"type": "buy_goods", "firm_id": empty_firm, "qty": 1})
    assert not rejected["ok"] and rejected["reason"] == "out of stock"
    assert economy.firms.get(stocked_firm)["inventory"] == 20

    listed = _listed_firm(economy, seller)
    economy.exchange.place_order(1, buyer, listed, "buy", 1, None, "market")
    economy.exchange.place_order(1, seller, listed, "sell", 1, None, "market")
    assert economy.exchange.match_firm(1, listed) == []
    assert economy.exchange.last_price(listed) is None
    assert economy.store.scalar("SELECT COUNT(*) FROM trades", default=0) == 0


def test_founding_order_phase_and_weekly_loan_rules(economy):
    bank = make_bank(economy)
    founder, _ = make_agent(economy, bank, "Founder", 1_000)
    lawyer, _ = make_agent(economy, bank, "Lawyer", 0, occupation="lawyer")
    executor = ActionExecutor(economy)

    before = economy.store.scalar("SELECT COUNT(*) FROM firms", default=0)
    rejected = executor.execute_action(1, founder, {
        "type": "found_company", "lawyer_agent_id": lawyer, "name": "TooRich",
        "opening_capital": 2_000,
    })
    assert not rejected["ok"] and rejected["reason"] == "insufficient opening capital"
    assert economy.store.scalar("SELECT COUNT(*) FROM firms", default=0) == before

    firm = _listed_firm(economy, founder)
    wrong_phase = executor.execute_action(1, founder, {
        "type": "place_order", "firm_id": firm, "side": "sell", "qty": 1,
        "limit_price": 500,
    }, phase="MARKET")
    assert not wrong_phase["ok"] and "EXECUTION" in wrong_phase["reason"]

    first = executor.execute_action(
        1, founder, {"type": "apply_loan", "bank_id": bank, "amount": 500})
    assert first["ok"]
    economy.store.update("loan_applications", first["application_id"], status="denied")
    duplicate = executor.execute_action(
        2, founder, {"type": "apply_loan", "bank_id": bank, "amount": 500})
    assert not duplicate["ok"] and "within a week" in duplicate["reason"]

    firm_first = executor.execute_action(1, founder, {
        "type": "apply_loan", "bank_id": bank, "amount": 500,
        "as_firm": True, "firm_id": firm,
    })
    assert firm_first["ok"]
    economy.store.update("loan_applications", firm_first["application_id"], status="approved")
    firm_duplicate = executor.execute_action(2, founder, {
        "type": "apply_loan", "bank_id": bank, "amount": 500,
        "as_firm": True, "firm_id": firm,
    })
    assert not firm_duplicate["ok"] and "within a week" in firm_duplicate["reason"]


@pytest.mark.parametrize("seed", [3, 17, 101])
def test_random_valid_action_sequences_always_reconcile(economy, seed):
    """Seeded generated action sequences exercise conservation as a property."""
    rng = random.Random(seed)
    bank = make_bank(economy, reserves=100_000_000)
    people = [make_agent(economy, bank, f"P{i}", 2_000_000)[0] for i in range(8)]
    owner = people[0]
    shop = economy.firms.found_firm(
        0, owner, "Property Shop", "retail", opening_capital_cents=500_000)
    economy.store.update("firms", shop, inventory=1_000)
    economy.firms.set_price(0, shop, 100)
    executor = ActionExecutor(economy)

    for tick in range(1, 121):
        actor = rng.choice(people)
        if rng.random() < 0.7:
            recipient = rng.choice([p for p in people if p != actor])
            destination = economy.ledger.agent_checking_id(recipient)
            result = executor.execute_action(tick, actor, {
                "type": "transfer", "to_account": destination,
                "amount": rng.randint(1, 2_000),
            })
        else:
            result = executor.execute_action(
                tick, actor, {"type": "buy_goods", "firm_id": shop, "qty": 1})
        assert result["ok"], result
        ok, diagnostic = economy.ledger.reconcile()
        assert ok, diagnostic


@pytest.mark.parametrize("seed", [5, 23, 71])
def test_random_lifecycle_event_storms_always_reconcile(economy, seed):
    """Random death/health ordering with loans and heirs never corrupts money."""
    rng = random.Random(seed)
    bank = make_bank(economy, reserves=500_000_000)
    people = [make_agent(
        economy, bank, f"Life{i}", rng.randint(20_000, 100_000), age=rng.randint(18, 95))[0]
        for i in range(36)]
    for left, right in zip(people, people[1:]):
        economy.store.insert(
            "social_ties", agent_a=left, agent_b=right, weight=rng.random())
    for borrower in rng.sample(people, 12):
        economy.bank.disburse_loan(
            0, bank, "agent", borrower, LoanTerms(rng.randint(1_000, 10_000), 800, 360, 30))

    deaths = rng.sample(people, 28)
    for tick, agent_id in enumerate(deaths, start=1):
        health = rng.choice(["healthy", "sick", "critical"])
        economy.store.update("agents", agent_id, health=health)
        economy.lifecycle.settle_death(tick, agent_id, cause=f"storm:{health}")
        ok, diagnostic = economy.ledger.reconcile()
        assert ok, diagnostic


def test_oil_and_rate_shocks_produce_downstream_agent_decisions(economy):
    """The shock changes context; an agent, not the engine, chooses the outcome."""
    bank = make_bank(economy, reserves=500_000_000)
    founder, _ = make_agent(economy, bank, "Founder", 1_000_000)
    firm = economy.firms.found_firm(
        0, founder, "AdaptiveCo", "manufacturing", opening_capital_cents=500_000)
    economy.store.update("firms", firm, inventory=20)
    executor = ActionExecutor(economy)
    shocks = Shocks(economy, {})

    def founder_context():
        row = economy.firms.get(firm)
        product = economy.firms.product(row)
        return {
            "my_firm": {
                "firm_id": firm, "name": row["name"], "inventory": int(row["inventory"]),
                "price": int(product["unit_price_cents"]),
                "unit_cost": int(product["base_input_cost_cents"] * economy.firms.commodity_index()),
                "cash": economy.ledger.balance(int(row["account_id"])),
                "employees": 1, "payroll": 0, "recent_sales": 10,
                "target_headcount": 1, "has_pending_loan": False,
                "has_pending_pitch": False, "is_private": True,
            },
            "agent": {"id": founder, "health": "healthy"},
            "state": {"checking_balance": 500_000},
        }

    baseline_action = next(
        action for action in founder_decision(founder_context())["actions"]
        if action["type"] == "set_price")
    oil_id = shocks.schedule(
        "oil", "shock", {"tick": 1}, params={"multiplier": 2.0}, label="oil proof")
    shocks.evaluate(1)
    oil_action = next(
        action for action in founder_decision(founder_context())["actions"]
        if action["type"] == "set_price")
    assert oil_action["price"] > baseline_action["price"]
    assert executor.execute_action(2, founder, oil_action)["ok"]
    assert economy.store.metric_latest("commodity_index") == pytest.approx(2.0)
    assert economy.firms.product(economy.firms.get(firm))["unit_price_cents"] == oil_action["price"]
    assert economy.store.query_one(
        "SELECT id FROM events WHERE kind='shock_fired' "
        "AND json_extract(payload_json,'$.shock_id')=?", (oil_id,))

    borrower, _ = make_agent(economy, bank, "Borrower", 100_000)
    officer, _ = make_agent(
        economy, bank, "Officer", 0, role="credit_officer", employer_id=bank)
    application = executor.execute_action(
        3, borrower, {"type": "apply_loan", "bank_id": bank, "amount": 5_000})
    assert application["ok"]
    pending = [{
        "id": application["application_id"], "amount_cents": 5_000,
        "borrower_income_cents": 10_000, "borrower_net_worth_cents": 100_000,
    }]
    low_quote = credit_officer_decision(
        {"policy_rate_bps": 500, "pending_loan_apps": pending})["actions"][0]
    rate_id = shocks.schedule(
        "policy_rate", "shock", {"tick": 4}, params={"rate_bps": 900}, label="rate proof")
    shocks.evaluate(4)
    high_quote = credit_officer_decision(
        {"policy_rate_bps": economy.policy_rate_bps(), "pending_loan_apps": pending})["actions"][0]
    assert high_quote["rate_bps"] - low_quote["rate_bps"] == 400
    approved = executor.execute_action(5, officer, high_quote)
    assert approved["ok"]
    loan_rate = economy.store.scalar("SELECT rate_bps FROM loans WHERE id=?", (approved["loan_id"],))
    assert loan_rate == high_quote["rate_bps"]
    rate_event = economy.store.query_one(
        "SELECT payload_json FROM events WHERE kind='policy_rate_set' "
        "AND json_extract(payload_json,'$.via')='shock' ORDER BY id DESC LIMIT 1")
    payload = json.loads(rate_event["payload_json"])
    assert payload["old_bps"] != payload["new_bps"] == 900
    assert rate_id


def test_budget_transitions_are_durable_and_cost_has_agent_breakdown(tmp_path):
    config = {
        "seed": 1,
        "population": {"size": 2},
        "banks": {"count": 1},
        "firms": {"count": 1, "listed": 0},
        "budget": {"cap_usd": 1.0, "oracle_reserve_usd": 0.1,
                   "conversation_pairs": 15, "thresholds": [0.60, 0.80, 0.95]},
        "llm": {"default_route": {"provider": "scripted", "model": "scripted"},
                "routes": {}},
        "checkpoint_every": 0,
        "outlets": [],
    }
    from engine.store import Store
    store = Store(str(tmp_path / "budget.db"))
    store.init_run_meta("budget", 1, config)
    world = World(store, config)
    world.initialize()
    gateway: Gateway = world.gateway
    agent_id = int(store.scalar("SELECT id FROM agents WHERE alive=1 ORDER BY id LIMIT 1"))
    req = LLMRequest(role="citizen", purpose="decision", agent_id=agent_id, tick=1)
    result = AdapterResult(text='{"actions":[]}', in_tokens=10, out_tokens=10)

    for cost in (0.54, 0.18, 0.135, 0.045):
        gateway._log_call(req, "synthetic", "synthetic", f"k-{cost}", result, cost, False, 1)

    transitions = store.query(
        "SELECT payload_json FROM events WHERE kind='budget_degradation' ORDER BY id")
    assert [json.loads(row["payload_json"])["to_level"] for row in transitions] == [1, 2, 3, 4]
    assert gateway.governor.should_pause()
    assert gateway.governor.total_spend() == pytest.approx(0.9)
    assert gateway._estimate_cost(
        LLMRequest(role="citizen", purpose="decision", system="é", user="x", max_tokens=10),
        {"in": 1.0, "out": 1.0, "cache": 0.1}) >= (259 + 10) * 2 / 1_000_000

    app = create_app(world)
    with TestClient(app) as client:
        body = client.get("/api/cost").json()
    assert body["by_agent"]
    assert body["by_agent"][0]["agent_id"] == agent_id
    assert body["by_agent"][0]["cost_usd"] == pytest.approx(0.9)
    store.close()


def test_json_repair_accounts_for_both_provider_completions(tmp_path, monkeypatch):
    from engine.store import Store
    config = {
        "budget": {"cap_usd": 10.0, "oracle_reserve_usd": 1.0},
        "llm": {
            "provider_retries": 0,
            "providers": {"network": {
                "kind": "openai_compat", "base_url": "https://invalid.example/v1",
                "api_key_env": "REPAIR_TEST_KEY",
            }},
            "default_route": {"provider": "network", "model": "repair-test"},
            "routes": {},
            "pricing": {"repair-test": {"in": 1.0, "out": 2.0, "cache": 0.1}},
        },
    }
    store = Store(str(tmp_path / "repair.db"))
    store.init_run_meta("repair", 1, config)
    monkeypatch.setenv("REPAIR_TEST_KEY", "test-only")
    gateway = Gateway(store, config)

    class InvalidThenValid:
        def __init__(self):
            self.calls = 0

        async def complete(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return AdapterResult(
                    text="not json", in_tokens=100, out_tokens=20,
                    cached_in_tokens=40, raw={"attempt": 1})
            return AdapterResult(
                text='{"reasoning":"fixed","actions":[]}',
                in_tokens=120, out_tokens=30, cached_in_tokens=60,
                raw={"attempt": 2})

    adapter = InvalidThenValid()
    gateway.adapters["network"] = adapter
    response = asyncio.run(gateway.complete(
        LLMRequest(role="citizen", purpose="decision", system="stable", user="dynamic")))

    assert adapter.calls == 2 and response.ok
    assert response.in_tokens == 220 and response.out_tokens == 50
    expected_cost = (120 / 1_000_000) * 1.0 + (100 / 1_000_000) * 0.1 \
        + (50 / 1_000_000) * 2.0
    assert response.cost_usd == pytest.approx(expected_cost)
    row = store.query_one("SELECT * FROM llm_calls")
    payload = json.loads(row["response_json"])
    assert payload["raw"]["provider_calls"] == 2
    assert row["in_tokens"] == 220 and row["out_tokens"] == 50
    store.close()


def test_semantic_contract_repair_is_one_durable_call_and_precedes_transform(
        tmp_path, monkeypatch):
    from engine.store import Store
    config = {
        "budget": {"cap_usd": 10.0, "oracle_reserve_usd": 1.0},
        "llm": {
            "provider_retries": 0,
            "providers": {"network": {
                "kind": "openai_compat", "base_url": "https://invalid.example/v1",
                "api_key_env": "SEMANTIC_REPAIR_TEST_KEY",
            }},
            "default_route": {"provider": "network", "model": "semantic-repair"},
            "routes": {},
            "pricing": {
                "semantic-repair": {"in": 1.0, "out": 2.0, "cache": 0.1}},
        },
    }
    store = Store(str(tmp_path / "semantic-repair.db"))
    store.init_run_meta("semantic-repair", 1, config)
    monkeypatch.setenv("SEMANTIC_REPAIR_TEST_KEY", "test-only")
    gateway = Gateway(store, config)

    class InvalidEnumThenValid:
        def __init__(self):
            self.messages = []

        async def complete(self, _model, messages, **_kwargs):
            self.messages.append(messages)
            confidence = "medium" if len(self.messages) == 1 else "med"
            return AdapterResult(
                text=json.dumps({"p": 0.2, "confidence": confidence}),
                in_tokens=10, out_tokens=5, raw={"attempt": len(self.messages)})

    adapter = InvalidEnumThenValid()
    gateway.adapters["network"] = adapter
    transform_row_counts = []

    def validate(parsed):
        if parsed.get("confidence") not in {"low", "med", "high"}:
            return "confidence must be low, med, or high"
        return None

    def transform(parsed):
        transform_row_counts.append(store.scalar("SELECT COUNT(*) FROM llm_calls"))
        return parsed

    response = asyncio.run(gateway.complete(
        LLMRequest(role="oracle", purpose="oracle", system="stable", user="dynamic"),
        parsed_validator=validate, parsed_transform=transform))

    assert response.ok and response.parsed["confidence"] == "med"
    assert len(adapter.messages) == 2
    assert "Contract error: confidence must be low, med, or high" in (
        adapter.messages[1][-1]["content"])
    assert transform_row_counts == [1]
    assert store.scalar("SELECT COUNT(*) FROM llm_calls") == 1
    row = store.query_one("SELECT response_json,in_tokens,out_tokens FROM llm_calls")
    payload = json.loads(row["response_json"])
    assert json.loads(payload["text"])["confidence"] == "med"
    assert payload["raw"] == {
        "provider_calls": 2,
        "repair": {"initial": {"attempt": 1}, "final": {"attempt": 2}},
    }
    assert row["in_tokens"] == 20 and row["out_tokens"] == 10
    store.close()


@pytest.mark.parametrize(("bad_field", "bad_value", "repair_error"), [
    ("confidence", "medium", "confidence must be low, med, or high"),
    ("p", float("nan"), "forecast probability must be between 0 and 1"),
    ("insufficient_data", True,
     "governed forecast must provide a checkable prediction"),
])
@pytest.mark.parametrize(("semantics_version", "campaign_version", "repairs"), [
    (6, 7, False),
    (7, 6, False),
    (7, 7, True),
])
def test_oracle_semantic_answer_repair_requires_semantics7_and_campaign7(
        tmp_path, monkeypatch, bad_field, bad_value, repair_error,
        semantics_version, campaign_version, repairs):
    from engine.store import Store
    key = f"ORACLE_SEMANTIC_REPAIR_{semantics_version}_{bad_field.upper()}"
    monkeypatch.setenv(key, "test-only")
    config = {
        "seed": semantics_version,
        "engine_semantics_version": semantics_version,
        "population": {"size": 4},
        "banks": {"count": 1},
        "firms": {"count": 2, "listed": 0},
        "budget": {"cap_usd": 10.0, "oracle_reserve_usd": 10.0,
                   "conversation_pairs": 0},
        "oracle": {"default_horizon_ticks": 30, "max_horizon_ticks": 365,
                   "strict_resolution_rules": True},
        "llm": {
            "provider_retries": 0,
            "providers": {"network": {
                "kind": "openai_compat", "base_url": "https://invalid.example/v1",
                "api_key_env": key,
            }},
            "default_route": {"provider": "scripted", "model": "scripted"},
            "routes": {
                "oracle": {"provider": "network", "model": "oracle-semantic"}},
            "pricing": {
                "oracle-semantic": {"in": 0.0, "out": 0.0, "cache": 0.0}},
        },
        "checkpoint_every": 0,
        "outlets": [],
    }
    store = Store(str(
        tmp_path / f"oracle-semantic-{semantics_version}-{campaign_version}-{bad_field}.db"))
    store.init_run_meta("oracle-semantic", config["seed"], config)
    world = World(store, config)
    world.initialize()

    class OracleSequence:
        def __init__(self):
            self.purposes = []
            self.messages = []

        async def complete(self, _model, messages, **kwargs):
            purpose = kwargs["purpose"]
            self.purposes.append(purpose)
            self.messages.append(messages)
            if purpose == "oracle_plan":
                payload = {"queries": [{
                    "tool": "read_news",
                    "args": {"from_tick": 0, "to_tick": 0, "limit": 1},
                }]}
            else:
                answer_attempt = self.purposes.count("oracle")
                payload = {
                    "p": 0.2,
                    "drivers": ["bounded evidence"],
                    "confidence": "med",
                    "resolution_rule": {
                        "type": "bank_run", "window": 5, "deposit_drop": 0.3},
                    "deadline_tick": 30,
                    "reasoning": "bounded answer",
                }
                if answer_attempt == 1:
                    payload[bad_field] = bad_value
            return AdapterResult(
                text=json.dumps(payload), in_tokens=10, out_tokens=5,
                raw={"purpose": purpose, "ordinal": len(self.purposes)})

    adapter = OracleSequence()
    world.gateway.adapters["network"] = adapter
    contract = {
        "campaign_id": "test-oracle-campaign",
        "campaign_version": campaign_version,
        "campaign_key": "bank_run_t000",
        "scheduled_tick": 0,
        "resolution_rule": {
            "type": "bank_run", "window": 5, "deposit_drop": 0.3},
        "deadline_tick": 30,
    }
    try:
        result = asyncio.run(world.oracle.ask(
            "What is the probability of a bank run within 30 ticks?",
            governed_contract=contract))
        answer_rows = store.query(
            "SELECT response_json FROM llm_calls "
            "WHERE role='oracle' AND purpose='oracle'")
        assert len(answer_rows) == 1
        if repairs:
            assert result["p"] == 0.2
            assert result["confidence"] == "med"
            assert adapter.purposes == ["oracle_plan", "oracle", "oracle"]
            answer_payload = json.loads(answer_rows[0]["response_json"])
            assert answer_payload["raw"]["provider_calls"] == 2
            assert json.loads(answer_payload["text"])["confidence"] == "med"
            assert repair_error in adapter.messages[-1][-1]["content"]
            prediction = store.query_one(
                "SELECT p,confidence,status FROM predictions WHERE id=?",
                (result["prediction_id"],))
            assert prediction["p"] == 0.2
            assert prediction["confidence"] == "med"
            assert prediction["status"] == "open"
        else:
            assert result["insufficient_data"] is True
            assert adapter.purposes == ["oracle_plan", "oracle"]
            answer_payload = json.loads(answer_rows[0]["response_json"])
            assert "provider_calls" not in answer_payload["raw"]
            prediction = store.query_one(
                "SELECT p,status FROM predictions WHERE id=?",
                (result["prediction_id"],))
            assert prediction["p"] is None
            assert prediction["status"] == "insufficient_data"
    finally:
        world.close()


def test_non_governed_oracle_insufficient_data_does_not_repair(
        tmp_path, monkeypatch):
    from engine.store import Store
    monkeypatch.setenv("ORACLE_NONGOVERNED_TEST_KEY", "test-only")
    config = {
        "seed": 7,
        "engine_semantics_version": 7,
        "population": {"size": 4},
        "banks": {"count": 1},
        "firms": {"count": 2, "listed": 0},
        "budget": {"cap_usd": 10.0, "oracle_reserve_usd": 10.0,
                   "conversation_pairs": 0},
        "oracle": {"default_horizon_ticks": 30, "max_horizon_ticks": 365,
                   "strict_resolution_rules": True},
        "llm": {
            "provider_retries": 0,
            "providers": {"network": {
                "kind": "openai_compat", "base_url": "https://invalid.example/v1",
                "api_key_env": "ORACLE_NONGOVERNED_TEST_KEY",
            }},
            "default_route": {"provider": "scripted", "model": "scripted"},
            "routes": {
                "oracle": {"provider": "network", "model": "oracle-nongoverned"}},
            "pricing": {
                "oracle-nongoverned": {"in": 0.0, "out": 0.0, "cache": 0.0}},
        },
        "checkpoint_every": 0,
        "outlets": [],
    }
    store = Store(str(tmp_path / "oracle-nongoverned.db"))
    store.init_run_meta("oracle-nongoverned", config["seed"], config)
    world = World(store, config)
    world.initialize()

    class InsufficientSequence:
        def __init__(self):
            self.purposes = []

        async def complete(self, _model, _messages, **kwargs):
            purpose = kwargs["purpose"]
            self.purposes.append(purpose)
            payload = (
                {"queries": [{
                    "tool": "read_news",
                    "args": {"from_tick": 0, "to_tick": 0, "limit": 1},
                }]}
                if purpose == "oracle_plan"
                else {"insufficient_data": True, "reason": "not enough evidence"})
            return AdapterResult(
                text=json.dumps(payload), in_tokens=10, out_tokens=5,
                raw={"purpose": purpose})

    adapter = InsufficientSequence()
    world.gateway.adapters["network"] = adapter
    try:
        result = asyncio.run(world.oracle.ask("Is the moon made of cheese?"))
        assert result["insufficient_data"] is True
        assert result["reason"] == "not enough evidence"
        assert adapter.purposes == ["oracle_plan", "oracle"]
        assert store.scalar(
            "SELECT COUNT(*) FROM llm_calls WHERE role='oracle' AND purpose='oracle'") == 1
    finally:
        world.close()


def test_semantics7_governed_oracle_repair_replays_exactly_offline(
        tmp_path, monkeypatch):
    monkeypatch.setenv("ORACLE_REPAIR_REPLAY_TEST_KEY", "test-only")
    config = {
        "seed": 7,
        "engine_semantics_version": 7,
        "population": {"size": 4},
        "banks": {"count": 1},
        "firms": {"count": 2, "listed": 0},
        "budget": {"cap_usd": 10.0, "oracle_reserve_usd": 10.0,
                   "conversation_pairs": 0},
        "oracle": {"default_horizon_ticks": 30, "max_horizon_ticks": 365,
                   "strict_resolution_rules": True},
        "llm": {
            "provider_retries": 0,
            "providers": {"network": {
                "kind": "openai_compat", "base_url": "https://invalid.example/v1",
                "api_key_env": "ORACLE_REPAIR_REPLAY_TEST_KEY",
            }},
            "default_route": {"provider": "scripted", "model": "scripted"},
            "routes": {
                "oracle": {"provider": "network", "model": "oracle-replay"}},
            "pricing": {
                "oracle-replay": {"in": 0.0, "out": 0.0, "cache": 0.0}},
        },
        "checkpoint_every": 0,
        "outlets": [],
    }
    question = "What is the probability of a bank run within 30 ticks?"
    contract = {
        "campaign_id": "test-oracle-repair-replay",
        "campaign_version": 7,
        "campaign_key": "bank_run_t000",
        "scheduled_tick": 0,
        "resolution_rule": {
            "type": "bank_run", "window": 5, "deposit_drop": 0.3},
        "deadline_tick": 30,
    }

    class RepairSequence:
        def __init__(self):
            self.purposes = []

        async def complete(self, _model, _messages, **kwargs):
            purpose = kwargs["purpose"]
            self.purposes.append(purpose)
            if purpose == "oracle_plan":
                payload = {"queries": [{
                    "tool": "read_news",
                    "args": {"from_tick": 0, "to_tick": 0, "limit": 1},
                }]}
            else:
                payload = {
                    "p": 0.2,
                    "drivers": ["bounded evidence"],
                    "confidence": (
                        "medium" if self.purposes.count("oracle") == 1 else "med"),
                    "resolution_rule": contract["resolution_rule"],
                    "deadline_tick": contract["deadline_tick"],
                    "reasoning": "bounded answer",
                }
            return AdapterResult(
                text=json.dumps(payload), in_tokens=10, out_tokens=5,
                raw={"purpose": purpose, "ordinal": len(self.purposes)})

    source_store, source_world, source_id = cli.open_run(
        config, None, None, data_dir=tmp_path)
    source_path = source_store.path
    adapter = RepairSequence()
    source_world.gateway.adapters["network"] = adapter
    replay_world = None
    try:
        source_result = asyncio.run(source_world.oracle.ask(
            question, governed_contract=contract))
        source_answer = source_store.query_one(
            "SELECT response_json FROM llm_calls "
            "WHERE role='oracle' AND purpose='oracle'")
        assert source_store.scalar(
            "SELECT COUNT(*) FROM llm_calls "
            "WHERE role='oracle' AND purpose='oracle'") == 1
        assert json.loads(source_answer["response_json"])["raw"]["provider_calls"] == 2
        assert adapter.purposes == ["oracle_plan", "oracle", "oracle"]
        source_prediction = dict(source_store.query_one(
            "SELECT p,reasoning,resolution_rule_json,confidence,drivers_json,"
            "deadline_tick,status FROM predictions"))
        source_world.close()

        replay_store, replay_world, _ = cli.open_run(
            {}, None, source_id, data_dir=tmp_path)

        class NoNetwork:
            def __init__(self):
                self.calls = 0

            async def complete(self, *_args, **_kwargs):
                self.calls += 1
                raise AssertionError("exact replay must not dispatch to a provider")

        no_network = NoNetwork()
        replay_world.gateway.adapters["network"] = no_network
        replay_result = asyncio.run(replay_world.oracle.ask(
            question, governed_contract=contract))
        replay_answer = replay_store.query_one(
            "SELECT response_json FROM llm_calls "
            "WHERE role='oracle' AND purpose='oracle'")
        tracker = replay_world.gateway.replay_execution_stats()

        assert replay_result == source_result
        assert dict(replay_store.query_one(
            "SELECT p,reasoning,resolution_rule_json,confidence,drivers_json,"
            "deadline_tick,status FROM predictions")) == source_prediction
        assert json.loads(replay_answer["response_json"])["raw"]["provider_calls"] == 2
        assert no_network.calls == 0
        assert tracker["live_dispatch_count"] == 0
        assert tracker["compatibility_fallback_matches"] == 0
        assert tracker["exact_key_matches"] == tracker["consumed_source_calls"]
        assert tracker["all_nonoperational_calls_consumed_once"] is True
        proof = verify_replay(source_path, replay_store.path)
        assert proof["exact"] is True
        assert proof["differences"] == []
    finally:
        if replay_world is not None:
            replay_world.close()
        else:
            source_world.close()


def test_gateway_redacts_tagged_private_reasoning_before_persisting(
        tmp_path, monkeypatch):
    from engine.store import Store
    config = {
        "budget": {"cap_usd": 10.0, "oracle_reserve_usd": 1.0},
        "llm": {
            "provider_retries": 0,
            "providers": {"network": {
                "kind": "openai_compat", "base_url": "https://invalid.example/v1",
                "api_key_env": "PRIVACY_TEST_KEY",
            }},
            "default_route": {"provider": "network", "model": "privacy-test"},
            "routes": {},
            "pricing": {"privacy-test": {"in": 0.0, "out": 0.0, "cache": 0.0}},
        },
    }
    store = Store(str(tmp_path / "privacy.db"))
    store.init_run_meta("privacy", 1, config)
    monkeypatch.setenv("PRIVACY_TEST_KEY", "test-only")
    gateway = Gateway(store, config)
    provider_payload = {
        "analysis": "private structured reasoning",
        "reasoning": "bounded public rationale",
        "actions": [{
            "type": "do_nothing",
            "metadata": {"thinking": "private nested reasoning"},
            "content": [
                {"type": "reasoning", "text": "private typed reasoning"},
                {"type": "text", "text": "public action metadata"},
            ],
        }],
    }
    provider_text = (
        "<think>private scratch work</think>"
        + json.dumps(provider_payload))

    class TaggedReasoningAdapter:
        async def complete(self, *args, **kwargs):
            return AdapterResult(
                text=provider_text, in_tokens=10, out_tokens=10,
                raw={"choices": [{"message": {
                    "content": provider_text,
                    "reasoning_content": "private raw reasoning",
                    "diagnostic": (
                        'first {"analysis":"private raw fragment one",'
                        '"status":"public first"} second '
                        '{"reasoning_content":"private raw fragment two",'
                        '"finish_reason":"stop"}'
                    ),
                    "malformed": (
                        '{"type":"reasoning","text":"private malformed raw"'
                    ),
                    "blocks": [
                        {"type": "reasoning", "text": "private raw typed reasoning"},
                        {"type": "text", "text": "public raw metadata"},
                    ],
                }}]},
            )

    gateway.adapters["network"] = TaggedReasoningAdapter()
    response = asyncio.run(gateway.complete(
        LLMRequest(role="citizen", purpose="decision", tick=1)))

    assert response.ok
    assert response.parsed["reasoning"] == "bounded public rationale"
    assert "analysis" not in response.parsed
    assert response.parsed["actions"][0]["metadata"] == {}
    assert response.parsed["actions"][0]["content"] == [
        {"type": "text", "text": "public action metadata"}]
    persisted = store.query_one("SELECT response_json FROM llm_calls")
    payload = json.loads(persisted["response_json"])
    serialized = json.dumps(payload)
    for private_text in (
            "private scratch work", "private structured reasoning",
            "private nested reasoning", "private typed reasoning",
            "private raw reasoning", "private raw typed reasoning",
            "private raw fragment one", "private raw fragment two",
            "private malformed raw"):
        assert private_text not in serialized
    assert "<think>" not in serialized
    assert '"analysis"' not in serialized
    assert "reasoning_content" not in serialized
    raw_message = payload["raw"]["choices"][0]["message"]
    assert "public first" in raw_message["diagnostic"]
    assert '"finish_reason":"stop"' in raw_message["diagnostic"]
    assert raw_message["malformed"] == "[REDACTED]"
    store.close()


def test_provider_text_sanitizers_cover_multiple_and_malformed_json_fragments():
    raw = sanitize_provider_raw({
        "api_key": "raw-credential-sentinel",
        "content": (
            'prefix {"analysis":"first-fragment-private","status":"public-one"} '
            'middle {"reasoning_details":"second-fragment-private",'
            '"finish_reason":"stop"} suffix'
        ),
        "malformed": (
            r'provider payload {\"thinking\":\"escaped-malformed-private\"'
        ),
        "unicode_malformed": (
            r'provider {"\u0061nalysis":"unicode-malformed-private"'
        ),
        "nested": {"credential": "nested-credential-sentinel", "status": "ok"},
    })
    serialized_raw = json.dumps(raw)

    assert "first-fragment-private" not in serialized_raw
    assert "second-fragment-private" not in serialized_raw
    assert "public-one" in serialized_raw
    assert "finish_reason" in serialized_raw
    assert raw["malformed"] == "[REDACTED]"
    assert raw["unicode_malformed"] == "[REDACTED]"
    assert raw["api_key"] == "[REDACTED]"
    assert raw["nested"] == {"credential": "[REDACTED]", "status": "ok"}
    assert "credential-sentinel" not in serialized_raw

    error = sanitize_provider_error(
        'first {"analysis":"error-fragment-private","error":"public error"} '
        'second {"thoughts":"error-second-private","status":"unavailable"}')
    assert "error-fragment-private" not in error
    assert "error-second-private" not in error
    assert "public error" in error and "unavailable" in error

    malformed_error = sanitize_provider_error(
        '{"type":"reasoning","text":"malformed-error-private"')
    assert malformed_error == "[REDACTED]"
    assert "malformed-error-private" not in malformed_error

    unicode_error = sanitize_provider_error(
        r'provider {"reason\u0069ng_content":"unicode-error-private"')
    assert unicode_error == "[REDACTED]"
    assert "unicode-error-private" not in unicode_error


def test_gateway_sanitizes_provider_errors_before_preflight_and_events(
        tmp_path, monkeypatch):
    from engine.store import Store
    config = {
        "budget": {"cap_usd": 10.0, "oracle_reserve_usd": 1.0},
        "llm": {
            "provider_retries": 0,
            "providers": {"network": {
                "kind": "openai_compat", "base_url": "https://invalid.example/v1",
                "api_key_env": "ERROR_PRIVACY_TEST_KEY",
            }},
            "default_route": {"provider": "network", "model": "error-test"},
            "routes": {},
            "pricing": {"error-test": {"in": 0.0, "out": 0.0, "cache": 0.0}},
        },
    }
    store = Store(str(tmp_path / "provider-errors.db"))
    store.init_run_meta("provider-errors", 1, config)
    monkeypatch.setenv("ERROR_PRIVACY_TEST_KEY", "test-only")
    gateway = Gateway(store, config)

    class FailingAdapter:
        @staticmethod
        def _message(stage):
            first = (
                f"api_key={stage}-credential <think>{stage}-tagged-private</think> "
                + json.dumps({
                    "analysis": f"{stage}-structured-private",
                    "api_key": f"{stage}-json-credential",
                    "error": "provider unavailable",
                }))
            if stage == "preflight":
                return first + " second " + json.dumps({
                    "reasoning_content": "preflight-second-fragment-private",
                    "status": "public preflight status",
                })
            return first + ' malformed {"analysis":"completion-malformed-private"'

        async def healthcheck(self, model):
            raise RuntimeError(self._message("preflight"))

        async def complete(self, *args, **kwargs):
            raise RuntimeError(self._message("completion"))

    gateway.adapters["network"] = FailingAdapter()
    preflight = asyncio.run(gateway.preflight(live=True))
    with pytest.raises(ProviderUnavailable) as exc_info:
        asyncio.run(gateway.complete(
            LLMRequest(role="citizen", purpose="decision", tick=1)))

    event = store.query_one(
        "SELECT payload_json FROM events WHERE kind='provider_failure' ORDER BY id DESC")
    serialized = json.dumps({
        "preflight": preflight,
        "exception": str(exc_info.value),
        "event": json.loads(event["payload_json"]),
    })
    for private_text in (
            "preflight-credential", "preflight-tagged-private",
            "preflight-structured-private", "preflight-json-credential",
            "preflight-second-fragment-private",
            "completion-credential", "completion-tagged-private",
            "completion-structured-private", "completion-json-credential",
            "completion-malformed-private"):
        assert private_text not in serialized
    assert "<think>" not in serialized
    assert '"analysis"' not in serialized
    assert "[REDACTED]" in serialized
    assert "public preflight status" in serialized
    assert json.loads(event["payload_json"])["error"] == "[REDACTED]"
    store.close()


def test_empty_success_completions_are_metered_and_degrade_to_noop(tmp_path, monkeypatch):
    from engine.store import Store
    config = {
        "budget": {"cap_usd": 10.0, "oracle_reserve_usd": 1.0},
        "llm": {
            "provider_retries": 0,
            "providers": {"network": {
                "kind": "openai_compat", "base_url": "https://invalid.example/v1",
                "api_key_env": "EMPTY_TEST_KEY",
            }},
            "default_route": {"provider": "network", "model": "empty-test"},
            "routes": {},
            "pricing": {"empty-test": {"in": 1.0, "out": 2.0, "cache": 0.1}},
        },
    }
    store = Store(str(tmp_path / "empty.db"))
    store.init_run_meta("empty", 1, config)
    monkeypatch.setenv("EMPTY_TEST_KEY", "test-only")
    gateway = Gateway(store, config)

    class EmptyAdapter:
        def __init__(self):
            self.calls = 0

        async def complete(self, *args, **kwargs):
            self.calls += 1
            return AdapterResult(
                text="", in_tokens=100, out_tokens=4096,
                cached_in_tokens=40, raw={"finish_reason": "length"})

    adapter = EmptyAdapter()
    gateway.adapters["network"] = adapter
    response = asyncio.run(gateway.complete(
        LLMRequest(role="citizen", purpose="decision", system="stable", user="dynamic")))

    assert adapter.calls == 2
    assert not response.ok
    assert response.parsed["actions"] == [{"type": "do_nothing"}]
    assert response.text == (
        '{"actions":[{"type":"do_nothing"}],'
        '"reasoning":"unparseable output; no-op"}')
    assert response.in_tokens == 200 and response.out_tokens == 8192
    expected_cost = (120 * 1.0 + 80 * 0.1 + 8192 * 2.0) / 1_000_000
    assert response.cost_usd == pytest.approx(expected_cost)
    row = store.query_one("SELECT * FROM llm_calls")
    assert row["in_tokens"] == 200 and row["out_tokens"] == 8192
    assert row["cost_usd"] == pytest.approx(expected_cost)
    assert json.loads(row["response_json"])["text"] == response.text
    assert store.scalar("SELECT COUNT(*) FROM events WHERE kind='provider_failure'") == 0
    store.close()


def test_schema_hint_repairs_valid_json_with_the_wrong_contract(tmp_path, monkeypatch):
    from engine.store import Store
    config = {
        "budget": {"cap_usd": 10.0, "oracle_reserve_usd": 1.0},
        "llm": {
            "provider_retries": 0,
            "providers": {"network": {
                "kind": "openai_compat", "base_url": "https://invalid.example/v1",
                "api_key_env": "SCHEMA_TEST_KEY",
            }},
            "default_route": {"provider": "network", "model": "schema-test"},
            "routes": {},
        },
    }
    store = Store(str(tmp_path / "schema.db"))
    store.init_run_meta("schema", 1, config)
    monkeypatch.setenv("SCHEMA_TEST_KEY", "test-only")
    gateway = Gateway(store, config)

    class WrongThenValid:
        def __init__(self):
            self.calls = 0

        async def complete(self, *args, **kwargs):
            self.calls += 1
            text = ('{"observations":[]}' if self.calls == 1 else
                    '{"summary":"fixed","importance":2,"belief_updates":[]}')
            return AdapterResult(text=text, in_tokens=10, out_tokens=10, raw={})

    adapter = WrongThenValid()
    gateway.adapters["network"] = adapter
    schema = '{"summary":"concise memory","importance":1.0,"belief_updates":[]}'
    response = asyncio.run(gateway.complete(
        LLMRequest(role="citizen", purpose="memory", user="observations"),
        schema_hint=schema))

    assert adapter.calls == 2
    assert response.ok
    assert response.parsed["summary"] == "fixed"
    store.close()


def test_no_argument_runtime_uses_fail_closed_live_desktop_profile():
    assert DEFAULT_CONFIG == "runs/evolving-live.yaml"
    config = cli.load_config(DEFAULT_CONFIG)
    assert config["engine_semantics_version"] == 11
    assert config["llm"]["live_only"] is True
    assert config["llm"]["require_preflight_live"] is True
