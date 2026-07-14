"""Semantics-7 retirement liquidity, cadence, and social participation."""

import json
import random

from agents.participant import ParticipantService
from agents.personas.library import Persona
from agents.memory import Memory
from agents.policies import citizen_decision
from agents.prompts import ContextBuilder
from agents.scheduler import Scheduler
from engine.actions import ActionExecutor
from engine.core import Economy
from tests.conftest import make_bank
from world.genesis import Genesis
from world.newsroom import Conversations


def _economy(store, semantics: int = 7, **lifecycle) -> Economy:
    config = {
        "engine_semantics_version": semantics,
        "lifecycle": lifecycle,
    }
    economy = Economy(store, config, random.Random(11), random.Random(12))
    economy.ensure_system_accounts()
    return economy


def _retiree(economy: Economy, bank_id: int, *, retired: bool = True,
             savings_currency: str = "USD") -> tuple[int, int, int]:
    agent_id = economy.store.insert(
        "agents", name="Retiree", kind="citizen", occupation="retiree", age=70,
        alive=1, retired=int(retired), health="healthy", cadence_json="{}")
    checking = economy.ledger.create_account(
        "agent", agent_id, "checking", bank_id=bank_id, label="retiree:checking",
        opening_cents=10_000, currency_code="USD")
    savings = economy.ledger.create_account(
        "agent", agent_id, "savings", bank_id=bank_id, label="retiree:savings",
        opening_cents=200_000, currency_code=savings_currency)
    economy.store.update(
        "agents", agent_id, checking_account_id=checking, savings_account_id=savings)
    return agent_id, checking, savings


def test_retiree_withdraws_only_own_same_currency_savings(store):
    economy = _economy(store)
    bank_id = make_bank(economy)
    agent_id, checking, savings = _retiree(economy, bank_id)
    executor = ActionExecutor(economy)

    result = executor.execute_action(
        3, agent_id, {"type": "withdraw_savings", "amount": 75_000})

    assert result["ok"] is True
    assert economy.ledger.balance(checking) == 85_000
    assert economy.ledger.balance(savings) == 125_000
    assert economy.store.scalar(
        "SELECT COUNT(*) FROM transactions WHERE kind='retirement_savings_withdrawal'") == 1
    assert economy.store.scalar(
        "SELECT COUNT(*) FROM events WHERE kind='retirement_savings_withdrawal'") == 1
    ok, diagnostics = economy.ledger.reconcile()
    assert ok, diagnostics


def test_withdrawal_rejects_historical_nonretiree_cross_currency_and_wrong_owner(store):
    historical = _economy(store, semantics=6)
    bank_id = make_bank(historical)
    agent_id, checking, savings = _retiree(historical, bank_id)
    result = ActionExecutor(historical).execute_action(
        1, agent_id, {"type": "withdraw_savings", "amount": 1_000})
    assert result == {"ok": False, "reason": "unknown action type: withdraw_savings"}
    assert historical.ledger.balance(checking) == 10_000
    assert historical.ledger.balance(savings) == 200_000

    historical.config["engine_semantics_version"] = 7
    executor = ActionExecutor(historical)
    historical.store.update("agents", agent_id, retired=0)
    assert executor.execute_action(
        2, agent_id, {"type": "withdraw_savings", "amount": 1_000})["reason"] == (
            "only retirees may withdraw savings")
    historical.store.update("agents", agent_id, retired=1)
    historical.store.execute(
        "UPDATE accounts SET currency_code='EUR' WHERE id=?", (savings,))
    assert executor.execute_action(
        3, agent_id, {"type": "withdraw_savings", "amount": 1_000})["reason"] == (
            "savings and checking must use the same currency")

    other_id = historical.store.insert(
        "agents", name="Other", kind="citizen", occupation="retiree", age=72,
        alive=1, retired=1)
    historical.store.execute(
        "UPDATE accounts SET currency_code='USD',owner_id=? WHERE id=?", (other_id, savings))
    assert executor.execute_action(
        4, agent_id, {"type": "withdraw_savings", "amount": 1_000})["reason"] == (
            "accounts are not the actor's declared savings and checking")


def test_retirement_transition_and_genesis_apply_retired_cadence(store):
    economy = _economy(
        store, retired_act_every=2, retired_portfolio_every=4, retired_news_every=1)
    bank_id = make_bank(economy)
    agent_id, _, _ = _retiree(economy, bank_id, retired=False)
    economy.store.update(
        "agents", agent_id, cadence_json=json.dumps({"act": 9, "portfolio": 12, "career": 30}))

    economy.lifecycle._retire(8, agent_id)

    row = economy.store.query_one("SELECT retired,cadence_json FROM agents WHERE id=?", (agent_id,))
    assert row["retired"] == 1
    assert json.loads(row["cadence_json"]) == {
        "act": 2, "career": 30, "news": 1, "portfolio": 4,
    }

    genesis = Genesis.__new__(Genesis)
    genesis.config = {
        "engine_semantics_version": 7,
        "lifecycle": {"retired_act_every": 2, "retired_portfolio_every": 4,
                      "retired_news_every": 1},
    }
    persona = Persona(
        "A", 70, "retiree", 1, 1, {}, 0.2, 0.0, [1])
    assert genesis._cadence_for(persona) == {
        "act": 2, "portfolio": 4, "career": 30, "news": 1,
    }

    genesis.config["lifecycle"]["retirement_age"] = 70
    younger = Persona("B", 68, "worker", 1, 1, {}, 0.2, 0.0, [1])
    assert genesis._is_retired(younger) is False
    assert genesis._cadence_for(younger) == {
        "act": 3, "portfolio": 7, "career": 30}
    genesis.config["lifecycle"]["retirement_age"] = 60
    younger = Persona("C", 62, "worker", 1, 1, {}, 0.2, 0.0, [1])
    assert genesis._is_retired(younger) is True
    assert genesis._cadence_for(younger) == {
        "act": 2, "portfolio": 4, "career": 30, "news": 1}
    genesis.config["engine_semantics_version"] = 6
    genesis.config["lifecycle"]["retirement_age"] = 70
    legacy = Persona("D", 68, "worker", 1, 1, {}, 0.2, 0.0, [1])
    assert genesis._is_retired(legacy) is True
    assert genesis._cadence_for(legacy) == {
        "act": 3, "portfolio": 7, "career": 30}


def test_retirees_skip_career_wakes_and_receive_news_wakes(store):
    economy = _economy(store, retired_news_every=97)
    bank_id = make_bank(economy)
    agent_id, _, _ = _retiree(economy, bank_id)
    economy.store.update(
        "agents", agent_id,
        cadence_json=json.dumps({"act": 101, "portfolio": 103, "career": 7, "news": 97}))
    row = economy.store.query_one("SELECT * FROM agents WHERE id=?", (agent_id,))

    sem7 = Scheduler(economy.store, {
        "engine_semantics_version": 7, "lifecycle": {"retired_news_every": 97}})
    career_tick = agent_id + 7
    assert sem7._citizen_wakes(row, career_tick, 1) is False
    news_tick = agent_id + 97
    assert sem7._citizen_wakes(row, news_tick, 1) is True

    sem6 = Scheduler(economy.store, {"engine_semantics_version": 6})
    assert sem6._citizen_wakes(row, career_tick, 1) is True


class _Context:
    def build(self, agent, tick):
        return {"state": {}, "prices": [], "jobs": [], "listed_firms": [], "banks": []}


def test_participant_catalog_exposes_drawdown_but_not_job_search(store):
    economy = _economy(store)
    bank_id = make_bank(economy)
    agent_id, _, _ = _retiree(economy, bank_id)
    service = ParticipantService(
        economy.store, _Context(), {"engine_semantics_version": 7})

    catalog = {item["type"]: item for item in service.action_catalog(agent_id)}

    assert "withdraw_savings" in catalog
    assert catalog["withdraw_savings"]["enabled"] is True
    assert "apply_job" not in catalog


def test_semantics7_context_exposes_declared_savings_and_target_without_jobs(store):
    economy = _economy(store, retirement_liquidity_target_cents=125_000)
    bank_id = make_bank(economy)
    agent_id, _, _ = _retiree(economy, bank_id)
    owner = economy.store.insert(
        "agents", name="Owner", kind="citizen", occupation="founder", age=40, alive=1)
    firm_id = economy.firms.found_firm(0, owner, "Jobs", "services")
    economy.labor.post_job(0, firm_id, "worker", 10_000)
    config = {
        "engine_semantics_version": 7,
        "lifecycle": {"retirement_liquidity_target_cents": 125_000},
    }
    builder = ContextBuilder(economy, Memory(economy.store, config), config)

    context = builder.build(
        economy.store.query_one("SELECT * FROM agents WHERE id=?", (agent_id,)), 1)

    assert context["savings_balance"] == 200_000
    assert context["state"]["savings_balance"] == 200_000
    assert context["retirement_drawdown_target_cents"] == 125_000
    assert context["jobs"] == []
    assert context["career_day"] is False
    _, prompt = builder.render_prompt(context)
    assert prompt.count("[STATE]") == 1
    assert "[RETIREMENT LIQUIDITY] savings 200000c" in prompt

    # The savings addition must not disturb the historical local-currency
    # state branch when no retirement fields are present.
    _, legacy_prompt = builder.render_prompt({
        "agent": {"id": agent_id, "name": "Legacy"},
        "state": {
            "checking_balance": 10_000, "bank_id": bank_id,
            "currency_code": "USD", "debt": 0, "employed": False,
            "net_worth": 10_000, "shares": {},
        },
    })
    assert legacy_prompt.count("[STATE]") == 1
    assert "[RETIREMENT LIQUIDITY]" not in legacy_prompt


def test_scripted_retiree_draws_shortfall_before_consumption():
    decision = citizen_decision({
        "rng_seed": 1,
        "agent": {"id": 4, "retired": True, "health": "healthy", "dependents": 0},
        "state": {"checking_balance": 20_000, "savings_balance": 200_000,
                  "employed": False},
        "savings_balance": 200_000,
        "retirement_drawdown_target_cents": 100_000,
        "prices": [{"firm_id": 9, "price": 1_000, "inventory": 20,
                    "product": "food"}],
        "beliefs": {}, "news": [], "heard": [], "jobs": [{"job_id": 7, "wage": 50_000}],
    })

    assert decision["actions"][0] == {"type": "withdraw_savings", "amount": 80_000}
    assert decision["actions"][1]["type"] == "buy_goods"
    assert all(action["type"] != "apply_job" for action in decision["actions"])


class _FixedRandom:
    def random(self):
        return 0.4


def test_retiree_ties_receive_greater_conversation_pair_weight(store):
    economy = _economy(store)
    bank_id = make_bank(economy)
    ids = []
    for index in range(4):
        agent_id, _, _ = _retiree(economy, bank_id, retired=index == 2)
        economy.store.update("agents", agent_id, name=f"A{index}")
        ids.append(agent_id)
    economy.store.insert("social_ties", agent_a=ids[0], agent_b=ids[1], weight=1.0)
    economy.store.insert("social_ties", agent_a=ids[2], agent_b=ids[3], weight=1.0)
    economy.prng = _FixedRandom()

    sem6 = Conversations(economy, object(), {"engine_semantics_version": 6})
    sem7 = Conversations(
        economy, object(), {"engine_semantics_version": 7,
                            "conversations": {"retiree_pair_weight": 1.75}})

    assert sem6._sample_pairs(1, 1) == [(ids[0], ids[1])]
    assert sem7._sample_pairs(1, 1) == [(ids[2], ids[3])]
