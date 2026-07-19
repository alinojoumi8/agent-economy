from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from agents.memory import Memory
from agents.participant import ParticipantError, ParticipantService
from agents.policies import citizen_decision
from agents.prompts import ContextBuilder
from .conftest import make_agent, make_bank
from engine.actions import ActionExecutor
from engine.core import Economy
from engine.store import load_json
from research.counterfactual import _arm_config
from research.scenarios import load_scenario
from world.metrics import Metrics


def _economy(store, **entrepreneurship_overrides):
    entrepreneurship = {
        "enabled": True,
        "new_arrivals_only": True,
        "review_interval_ticks": 30,
        "minimum_ticks_after_arrival": 1,
        "minimum_age": 21,
        "minimum_risk_tolerance": 0.65,
        "minimum_opening_capital_cents": 100_000,
        "personal_reserve_cents": 100_000,
        "opening_capital_share_bps": 3_500,
        "maximum_active_competitors": 3,
        "sales_lookback_ticks": 30,
        "stockout_inventory_threshold": 2,
        "eligible_sectors": ["services", "technology"],
        **entrepreneurship_overrides,
    }
    config = {
        "engine_semantics_version": 7,
        "entrepreneurship": entrepreneurship,
        "firms": {"target_headcount": 3, "pay_interval_ticks": 30},
        "participant_mode": {"enabled": True},
    }
    economy = Economy(store, config, random.Random(101), random.Random(202))
    economy.ensure_system_accounts()
    bank_id = make_bank(economy, reserves=10_000_000)
    return economy, config, bank_id


def _citizen(
    economy, bank_id, *, name="Ari Founder", cash=500_000,
    risk_tolerance=0.9, arrived_tick=10, **overrides,
):
    return make_agent(
        economy, bank_id, name=name, cash=cash, occupation="designer",
        health="healthy", retired=0, dependents=0,
        risk_tolerance=risk_tolerance, arrived_tick=arrived_tick,
        cadence_json="{}", **overrides,
    )


def test_seeded_arrival_builds_company_hires_produces_sells_and_pays(store):
    economy, config, bank_id = _economy(store)
    founder_id, founder_account = _citizen(economy, bank_id)
    lawyer_id, _ = make_agent(
        economy, bank_id, name="Lee Counsel", occupation="lawyer",
        role="lawyer", health="healthy", cash=50_000,
    )
    worker_id, worker_account = make_agent(
        economy, bank_id, name="Wren Worker", occupation="worker",
        health="healthy", retired=0, cash=50_000,
    )
    buyer_id, _ = make_agent(
        economy, bank_id, name="Casey Customer", occupation="buyer",
        health="healthy", retired=0, cash=50_000,
    )
    builder = ContextBuilder(economy, Memory(store, config), config)
    founder = store.query_one("SELECT * FROM agents WHERE id=?", (founder_id,))

    assert "entrepreneurship_opportunity" not in builder.build(founder, 10)
    context = builder.build(founder, 11)
    assert context["entrepreneurship_opportunity"] == builder.build(founder, 11)[
        "entrepreneurship_opportunity"]
    opportunity = context["entrepreneurship_opportunity"]
    action = opportunity["action"]
    assert action["lawyer_agent_id"] == lawyer_id
    assert 100_000 <= action["opening_capital"] <= 400_000
    assert opportunity["capital"]["cash_cents"] - action["opening_capital"] >= 100_000
    assert set(action["business_idea"]) == {
        "mission", "customer_problem", "offering"}

    system, prompt = builder.render_prompt(context)
    assert "business_idea:{mission,customer_problem,offering}" in system
    assert "ENTREPRENEURSHIP OPPORTUNITY" in prompt
    assert str(lawyer_id) in prompt
    decision = citizen_decision(context)
    assert decision["actions"] == [action]

    opening_founder_cash = economy.ledger.balance(founder_account)
    executor = ActionExecutor(economy)
    founded = executor.execute_action(11, founder_id, action)
    assert founded["ok"], founded
    firm_id = int(founded["firm_id"])
    assert economy.ledger.balance(founder_account) == (
        opening_founder_cash - action["opening_capital"])

    firm = store.query_one("SELECT * FROM firms WHERE id=?", (firm_id,))
    product = load_json(firm["product_json"], {})
    assert product["business_idea"] == action["business_idea"]
    event = store.query_one(
        "SELECT payload_json FROM events WHERE kind='company_founded' "
        "AND subject_id=?", (firm_id,))
    event_payload = json.loads(event["payload_json"])
    assert event_payload["business_idea"] == action["business_idea"]
    assert event_payload["opening_capital_cents"] == action["opening_capital"]
    proposal = store.query_one(
        "SELECT payload_json FROM action_proposals WHERE action_type='found_company' "
        "ORDER BY id DESC LIMIT 1")
    assert json.loads(proposal["payload_json"])["business_idea"] == action["business_idea"]

    founder_context = builder.build(founder, 12)
    assert founder_context["purpose"] == "founder"
    assert founder_context["my_firm"]["business_idea"] == action["business_idea"]
    duplicate = executor.execute_action(12, founder_id, {
        **action, "name": "Duplicate Company",
    })
    assert not duplicate["ok"]
    assert "already controls" in duplicate["reason"]

    posted = executor.execute_action(12, founder_id, {
        "type": "post_job", "firm_id": firm_id, "title": "Maker", "wage": 10_000,
    })
    assert posted["ok"], posted
    applied = executor.execute_action(13, worker_id, {
        "type": "apply_job", "job_id": posted["job_id"],
    })
    assert applied["ok"], applied
    offered = executor.execute_action(14, founder_id, {
        "type": "make_job_offer", "application_id": applied["application_id"],
        "wage": 10_000,
    })
    assert offered["ok"], offered
    hired = executor.execute_action(15, worker_id, {
        "type": "accept_job_offer", "offer_id": offered["offer_id"],
    })
    assert hired["ok"], hired
    assert int(store.scalar(
        "SELECT COUNT(*) FROM employments WHERE agent_id=? AND status='active'",
        (worker_id,), default=0)) == 1

    economy.firms.produce(16)
    assert int(store.scalar(
        "SELECT inventory FROM firms WHERE id=?", (firm_id,), default=0)) > 0
    sold = executor.execute_action(17, buyer_id, {
        "type": "buy_goods", "firm_id": firm_id, "qty": 1,
    })
    assert sold["ok"], sold
    worker_cash = economy.ledger.balance(worker_account)
    economy.firms.process_payroll(45)
    assert economy.ledger.balance(worker_account) > worker_cash
    assert store.query_one(
        "SELECT 1 FROM events WHERE kind='wage_paid' "
        "AND json_extract(payload_json,'$.firm_id')=?", (firm_id,))

    metrics = Metrics(economy, semantics_version=7).snapshot(45)
    assert metrics["entrepreneurial_firms_founded"] == 1.0
    assert metrics["entrepreneurial_firms_active"] == 1.0
    assert metrics["entrepreneurial_employment"] == 1.0
    assert metrics["entrepreneurial_revenue_30d"] == sold["total_cents"] / 100.0
    ok, diagnostic = economy.ledger.reconcile()
    assert ok, diagnostic


@pytest.mark.parametrize("business_idea", [
    {"mission": "M", "customer_problem": "P"},
    {"mission": "M", "customer_problem": "P", "offering": "O", "extra": "x"},
    {"mission": "M", "customer_problem": 7, "offering": "O"},
    {"mission": "M" * 241, "customer_problem": "P", "offering": "O"},
])
def test_invalid_business_idea_is_rejected_atomically(store, business_idea):
    economy, _, bank_id = _economy(store)
    founder_id, founder_account = _citizen(economy, bank_id)
    lawyer_id, _ = make_agent(
        economy, bank_id, name="Lawyer", occupation="lawyer", role="lawyer")
    opening_cash = economy.ledger.balance(founder_account)

    result = ActionExecutor(economy).execute_action(11, founder_id, {
        "type": "found_company", "name": "Invalid Idea Inc", "sector": "services",
        "lawyer_agent_id": lawyer_id, "opening_capital": 100_000,
        "business_idea": business_idea,
    })

    assert not result["ok"]
    assert int(store.scalar("SELECT COUNT(*) FROM firms", default=0)) == 0
    assert economy.ledger.balance(founder_account) == opening_cash
    assert not store.query_one("SELECT 1 FROM events WHERE kind='company_founded'")


def test_eligibility_and_participant_payload_are_bounded(store):
    economy, config, bank_id = _economy(store)
    eligible_id, _ = _citizen(economy, bank_id)
    low_risk_id, _ = _citizen(
        economy, bank_id, name="Cautious Citizen", risk_tolerance=0.2)
    poor_id, _ = _citizen(
        economy, bank_id, name="Cash Poor", cash=150_000)
    lawyer_id, _ = make_agent(
        economy, bank_id, name="Available Lawyer", occupation="lawyer", role="lawyer")
    builder = ContextBuilder(economy, Memory(store, config), config)

    eligible = store.query_one("SELECT * FROM agents WHERE id=?", (eligible_id,))
    assert "entrepreneurship_opportunity" in builder.build(eligible, 11)
    for agent_id in (low_risk_id, poor_id):
        agent = store.query_one("SELECT * FROM agents WHERE id=?", (agent_id,))
        assert "entrepreneurship_opportunity" not in builder.build(agent, 11)

    service = ParticipantService(store, builder, config)
    catalog = {item["type"]: item for item in service.action_catalog(eligible_id)}
    founding = catalog["found_company"]
    idea_fields = {field["name"]: field for field in founding["fields"]
                   if field.get("action_path")}
    assert {name: field["action_path"] for name, field in idea_fields.items()} == {
        "mission": ["business_idea", "mission"],
        "customer_problem": ["business_idea", "customer_problem"],
        "offering": ["business_idea", "offering"],
    }
    normalized = service._normalize_action(eligible_id, {
        "type": "found_company", "name": "Participant Firm", "sector": "services",
        "lawyer_agent_id": lawyer_id, "opening_capital": 100_000,
        "business_idea": {
            "mission": "Serve local customers",
            "customer_problem": "Supply is limited",
            "offering": "Reliable services",
        },
    })
    assert normalized["business_idea"]["offering"] == "Reliable services"
    with pytest.raises(ParticipantError, match="unexpected business_idea fields"):
        service._normalize_action(eligible_id, {
            **normalized,
            "business_idea": {**normalized["business_idea"], "employees": ["fake"]},
        })

    store.update("agents", lawyer_id, alive=0)
    no_lawyer = store.query_one("SELECT * FROM agents WHERE id=?", (eligible_id,))
    assert "entrepreneurship_opportunity" not in builder.build(no_lawyer, 11)


def test_counterfactual_arms_apply_only_declared_entrepreneurship_overrides():
    scenario = Path(__file__).resolve().parents[1] / "scenarios" / "native-entrepreneurship.yaml"
    pack = load_scenario(scenario)
    base = pack.config()

    control = _arm_config(pack, "control", base)
    treatment = _arm_config(pack, "treatment", base)

    assert base["entrepreneurship"]["enabled"] is True
    assert base["entrepreneurship"]["new_arrivals_only"] is True
    assert control["entrepreneurship"]["enabled"] is False
    assert treatment["entrepreneurship"]["enabled"] is True
    assert treatment["entrepreneurship"]["new_arrivals_only"] is False
    assert control["seed"] == treatment["seed"] == base["seed"]


def test_configs_without_entrepreneurship_keep_legacy_context_and_event_shape(store):
    config = {"engine_semantics_version": 7}
    economy = Economy(store, config, random.Random(1), random.Random(2))
    economy.ensure_system_accounts()
    bank_id = make_bank(economy)
    founder_id, _ = make_agent(
        economy, bank_id, name="Legacy Founder", cash=300_000,
        health="healthy", risk_tolerance=0.99, arrived_tick=1,
    )
    lawyer_id, _ = make_agent(
        economy, bank_id, name="Legacy Lawyer", occupation="lawyer", role="lawyer")
    founder = store.query_one("SELECT * FROM agents WHERE id=?", (founder_id,))
    context = ContextBuilder(economy, Memory(store, config), config).build(founder, 2)
    assert "entrepreneurship_opportunity" not in context

    result = ActionExecutor(economy).execute_action(2, founder_id, {
        "type": "found_company", "name": "Legacy Firm", "sector": "services",
        "lawyer_agent_id": lawyer_id, "opening_capital": 100_000,
    })
    assert result["ok"], result
    payload = json.loads(store.scalar(
        "SELECT payload_json FROM events WHERE kind='company_founded' "
        "ORDER BY id DESC LIMIT 1"))
    assert payload == {
        "firm_id": result["firm_id"],
        "name": "Legacy Firm",
        "sector": "services",
        "founder_agent_id": founder_id,
    }
