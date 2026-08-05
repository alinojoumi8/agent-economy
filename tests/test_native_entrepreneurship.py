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
from engine.store import Store, load_json
from research.counterfactual import _arm_config
from research.scenarios import load_scenario
from run import activate_entrepreneurship_for_run
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


def test_enabled_profile_rejects_unsupplied_or_mutated_company_actions(store):
    economy, config, bank_id = _economy(store)
    founder_id, _ = _citizen(economy, bank_id)
    lawyer_id, _ = make_agent(
        economy, bank_id, name="Bounded Lawyer", occupation="lawyer", role="lawyer")
    founder = store.query_one("SELECT * FROM agents WHERE id=?", (founder_id,))
    builder = ContextBuilder(economy, Memory(store, config), config)

    unsupplied = ActionExecutor(economy).execute_action(10, founder_id, {
        "type": "found_company", "name": "News Inspired Inc", "sector": "tech",
        "lawyer_agent_id": lawyer_id,
    })
    assert not unsupplied["ok"]
    assert "supplied entrepreneurship opportunity" in unsupplied["reason"]

    context = builder.build(founder, 11)
    supplied = context["entrepreneurship_opportunity"]["action"]
    mutated = ActionExecutor(economy).execute_action(11, founder_id, {
        **supplied, "name": "Model Invented Name",
    })
    assert not mutated["ok"]
    assert "copy the supplied entrepreneurship action exactly" in mutated["reason"]
    assert int(store.scalar("SELECT COUNT(*) FROM firms", default=0)) == 0


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
        context = builder.build(agent, 11)
        assert "entrepreneurship_opportunity" not in context
        system, _ = builder.render_prompt(context)
        assert "found_company{name,sector,lawyer_agent_id}" not in system

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


def test_mid_run_activation_is_forward_only_and_spreads_established_reviews(store):
    economy, config, bank_id = _economy(
        store,
        new_arrivals_only=False,
        activation_tick=20,
        review_interval_ticks=6,
    )
    citizens = [
        _citizen(
            economy,
            bank_id,
            name=f"Established Founder {index}",
            arrived_tick=0,
        )[0]
        for index in range(6)
    ]
    make_agent(
        economy,
        bank_id,
        name="Activation Counsel",
        occupation="lawyer",
        role="lawyer",
        health="healthy",
    )
    builder = ContextBuilder(economy, Memory(store, config), config)

    review_ticks = []
    for agent_id in citizens:
        agent = store.query_one("SELECT * FROM agents WHERE id=?", (agent_id,))
        assert "entrepreneurship_opportunity" not in builder.build(agent, 19)
        due = [
            tick
            for tick in range(20, 27)
            if "entrepreneurship_opportunity" in builder.build(agent, tick)
        ]
        assert len(due) == 1
        review_ticks.append(due[0])

    assert len(set(review_ticks)) >= 3


def test_odd_entrepreneurship_review_interval_stays_on_agent_wake_parity(store):
    economy, config, bank_id = _economy(
        store,
        new_arrivals_only=False,
        activation_tick=20,
        review_interval_ticks=3,
    )
    agent_id, _ = _citizen(
        economy, bank_id, name="Parity Founder", arrived_tick=0,
    )
    make_agent(
        economy, bank_id, name="Parity Counsel", occupation="lawyer",
        role="lawyer", health="healthy",
    )
    builder = ContextBuilder(economy, Memory(store, config), config)
    agent = store.query_one("SELECT * FROM agents WHERE id=?", (agent_id,))

    due_on_wakes = [
        tick for tick in range(20, 41)
        if tick % 2 == agent_id % 2
        and "entrepreneurship_opportunity" in builder.build(agent, tick)
    ]

    assert len(due_on_wakes) >= 3
    assert {right - left for left, right in zip(due_on_wakes, due_on_wakes[1:])} == {4}


def test_native_company_formation_is_capped_per_tick_after_activation(store):
    economy, _, bank_id = _economy(
        store,
        new_arrivals_only=False,
        activation_tick=20,
        maximum_formations_per_tick=1,
    )
    first_id, _ = _citizen(economy, bank_id, name="First Founder", arrived_tick=0)
    second_id, _ = _citizen(economy, bank_id, name="Second Founder", arrived_tick=0)
    lawyer_id, _ = make_agent(
        economy,
        bank_id,
        name="Capacity Counsel",
        occupation="lawyer",
        role="lawyer",
        health="healthy",
    )
    actions = {
        first_id: {
            "type": "found_company",
            "name": "First Native Startup",
            "sector": "technology",
            "lawyer_agent_id": lawyer_id,
            "opening_capital": 100_000,
            "business_idea": {
                "mission": "Serve the first market",
                "customer_problem": "Capacity is scarce",
                "offering": "A bounded first service",
            },
        },
        second_id: {
            "type": "found_company",
            "name": "Second Native Startup",
            "sector": "technology",
            "lawyer_agent_id": lawyer_id,
            "opening_capital": 100_000,
            "business_idea": {
                "mission": "Serve the second market",
                "customer_problem": "Capacity remains scarce",
                "offering": "A bounded second service",
            },
        },
    }
    economy._entrepreneurship_authorizations = {
        (20, founder_id): json.loads(json.dumps(action, sort_keys=True))
        for founder_id, action in actions.items()
    }
    executor = ActionExecutor(economy)

    first = executor.execute_action(20, first_id, actions[first_id])
    second = executor.execute_action(20, second_id, actions[second_id])

    assert first["ok"], first
    assert second == {
        "ok": False,
        "reason": "daily entrepreneurship capacity reached",
    }
    assert int(store.scalar("SELECT COUNT(*) FROM firms", default=0)) == 1


def test_pre_activation_native_formation_keeps_historical_execution_shape(store):
    economy, _, bank_id = _economy(
        store,
        new_arrivals_only=False,
        activation_tick=20,
    )
    founder_id, _ = _citizen(economy, bank_id, arrived_tick=0)
    lawyer_id, _ = make_agent(
        economy,
        bank_id,
        name="Replay Counsel",
        occupation="lawyer",
        role="lawyer",
        health="healthy",
    )

    result = ActionExecutor(economy).execute_action(19, founder_id, {
        "type": "found_company",
        "name": "Historical Startup",
        "sector": "technology",
        "lawyer_agent_id": lawyer_id,
        "opening_capital": 100_000,
        "business_idea": {
            "mission": "Preserve history",
            "customer_problem": "Replays must remain exact",
            "offering": "Stable activation boundaries",
        },
    })

    assert result["ok"], result
    assert store.query_one(
        "SELECT 1 FROM events WHERE tick=19 AND kind='company_founded'"
    )


def test_native_startup_ip_requires_a_closed_funding_round(store):
    economy, config, bank_id = _economy(
        store,
        new_arrivals_only=False,
        activation_tick=1,
    )
    founder_id, _ = _citizen(economy, bank_id, arrived_tick=0)
    firm_id = economy.firms.found_firm(
        1,
        founder_id,
        "Funded Inventions",
        "technology",
        product={
            "product": "Bounded invention",
            "business_idea": {
                "mission": "Build grounded inventions",
                "customer_problem": "Ideas need accountable capital",
                "offering": "A financed invention",
            },
        },
        opening_capital_cents=100_000,
        business_idea={
            "mission": "Build grounded inventions",
            "customer_problem": "Ideas need accountable capital",
            "offering": "A financed invention",
        },
    )
    economy.vc.pitch(2, founder_id, firm_id, 250_000, "pre-seed")
    founder = store.query_one("SELECT * FROM agents WHERE id=?", (founder_id,))
    builder = ContextBuilder(economy, Memory(store, config), config)

    pending = builder.build(founder, 2)
    assert not any(
        action["type"] == "register_ip"
        for action in pending.get("startup_work", {}).get("eligible_actions", [])
    )
    premature = ActionExecutor(economy).execute_action(2, founder_id, {
        "type": "register_ip",
        "firm_id": firm_id,
        "creator_agent_id": founder_id,
        "asset_type": "trade_secret",
        "title": "Bounded invention",
        "scope": "Financed product",
        "valuation_cents": 0,
        "metadata": {"source": "declared_firm_product"},
    })
    assert premature == {
        "ok": False,
        "reason": "native startup IP requires a closed funding round",
    }

    store.insert(
        "funding_rounds",
        tick=3,
        firm_id=firm_id,
        term_sheet_id=1,
        investor_agent_id=founder_id,
        round_type="preferred_equity",
        amount_cents=250_000,
        currency_code="USD",
        shares_issued=1,
        pre_money_cents=1_000_000,
        post_money_cents=1_250_000,
        transaction_id=1,
        status="closed",
    )
    funded = builder.build(founder, 3)
    assert funded["startup_work"]["eligible_actions"][0]["type"] == "register_ip"


def test_entrepreneurship_metrics_start_at_the_activation_boundary(store):
    economy, _, _ = _economy(store, activation_tick=20)

    before = Metrics(economy, semantics_version=7).snapshot(19)
    active = Metrics(economy, semantics_version=7).snapshot(20)

    assert "entrepreneurial_firms_founded" not in before
    assert active["entrepreneurial_firms_founded"] == 0.0


@pytest.mark.parametrize(
    ("active_tick", "next_phase", "expected_activation"),
    [
        (None, "MORNING", 358),
        (358, "MORNING", 358),
        (358, "EXECUTION", 359),
    ],
)
def test_paused_run_activation_uses_the_next_untouched_decision_boundary(
    tmp_path, active_tick, next_phase, expected_activation,
):
    path = tmp_path / "existing.db"
    store = Store(str(path))
    store.init_run_meta(
        "existing",
        42,
        {"engine_semantics_version": 7, "firms": {"count": 12}},
    )
    store.set_meta(
        status="paused",
        tick=357,
        active_tick=active_tick,
        next_phase=next_phase,
    )
    store.commit()

    settings = activate_entrepreneurship_for_run(store)
    persisted = json.loads(store.get_meta()["config_json"])

    assert settings == persisted["entrepreneurship"]
    assert settings["enabled"] is True
    assert settings["activation_tick"] == expected_activation
    assert settings["new_arrivals_only"] is False
    assert settings["maximum_formations_per_tick"] == 2
    assert persisted["firms"] == {"count": 12}
    assert not store.query_one("SELECT 1 FROM events")
    assert activate_entrepreneurship_for_run(store) == settings
    store.close()


def test_entrepreneurship_activation_rejects_running_and_derived_runs(tmp_path):
    running = Store(str(tmp_path / "running.db"))
    running.init_run_meta("running", 42, {"engine_semantics_version": 7})
    running.set_meta(status="running", tick=3)
    running.commit()
    with pytest.raises(RuntimeError, match="paused run"):
        activate_entrepreneurship_for_run(running)
    running.close()

    forked = Store(str(tmp_path / "forked.db"))
    forked.init_run_meta(
        "forked",
        42,
        {"engine_semantics_version": 7},
        parent_run_id="source",
        fork_tick=3,
    )
    forked.set_meta(status="paused", tick=3)
    forked.commit()
    with pytest.raises(RuntimeError, match="original run"):
        activate_entrepreneurship_for_run(forked)
    forked.close()


@pytest.mark.parametrize("semantics_version", [7, 12])
def test_native_startup_advances_through_funding_ip_and_engine_priced_merger(
    store, semantics_version,
):
    economy, config, bank_id = _economy(
        store,
        new_arrivals_only=False,
        activation_tick=1,
        review_interval_ticks=2,
        eligible_sectors=["technology"],
        autonomous_preseed=True,
        preseed_pitch_delay_ticks=1,
        preseed_raise_cents=250_000,
        autonomous_mergers=True,
        minimum_merger_age_ticks=0,
        maximum_merger_cash_share_bps=4_000,
        merger_premium_bps=1_000,
    )
    config["engine_semantics_version"] = semantics_version
    economy.config["engine_semantics_version"] = semantics_version
    config["llm"] = {"institutional_role_purposes": True}
    economy.config["llm"] = config["llm"]
    founder_id, _ = _citizen(
        economy,
        bank_id,
        name="Nova Founder",
        arrived_tick=0,
        cash=800_000,
    )
    target_founder_id, _ = _citizen(
        economy,
        bank_id,
        name="Target Founder",
        arrived_tick=0,
        cash=300_000,
    )
    lawyer_id, _ = make_agent(
        economy,
        bank_id,
        name="Startup Counsel",
        occupation="lawyer",
        role="lawyer",
        health="healthy",
        cash=100_000,
    )
    vc_id, _ = make_agent(
        economy,
        bank_id,
        name="Seed Partner",
        kind="staff",
        occupation="venture capitalist",
        role="vc_partner",
        cash=2_000_000,
    )
    regulator_id, _ = make_agent(
        economy,
        bank_id,
        name="Competition Reviewer",
        kind="staff",
        occupation="regulator",
        role="competition_regulator",
        cash=100_000,
    )
    builder = ContextBuilder(economy, Memory(store, config), config)
    executor = ActionExecutor(economy)
    founder = store.query_one("SELECT * FROM agents WHERE id=?", (founder_id,))

    founding_context = next(
        context
        for tick in range(1, 4)
        if "entrepreneurship_opportunity" in (
            context := builder.build(founder, tick)
        )
    )
    founding_tick = int(founding_context["tick"])
    founded = executor.execute_action(
        founding_tick,
        founder_id,
        founding_context["entrepreneurship_opportunity"]["action"],
    )
    assert founded["ok"], founded
    startup_id = int(founded["firm_id"])
    target_id = economy.firms.found_firm(
        founding_tick,
        target_founder_id,
        "Target Technology",
        "technology",
        opening_capital_cents=100_000,
    )

    pitch_tick = founding_tick + 1
    pitch = builder.build(founder, pitch_tick)["startup_work"]["eligible_actions"][0]
    assert pitch == {
        "type": "pitch_vc",
        "firm_id": startup_id,
        "ask": 250_000,
        "summary": (
            "Build dependable technology capacity for customers in the local market."
        ),
    }
    assert executor.execute_action(pitch_tick, founder_id, pitch)["ok"]
    assert "startup_work" not in builder.build(founder, pitch_tick + 1)

    vc = store.query_one("SELECT * FROM agents WHERE id=?", (vc_id,))
    term_sheet_tick = pitch_tick + 1
    term_sheet = builder.build(
        vc, term_sheet_tick)["startup_work"]["eligible_actions"][0]
    assert term_sheet["type"] == "propose_term_sheet"
    proposed = executor.execute_action(term_sheet_tick, vc_id, term_sheet)
    assert proposed["ok"], proposed

    accept_tick = term_sheet_tick + 1
    accept = builder.build(founder, accept_tick)["startup_work"]["eligible_actions"][0]
    assert accept["type"] == "accept_term_sheet"
    assert executor.execute_action(accept_tick, founder_id, accept)["ok"]

    lawyer = store.query_one("SELECT * FROM agents WHERE id=?", (lawyer_id,))
    diligence_tick = accept_tick + 1
    diligence = builder.build(
        lawyer, diligence_tick)["startup_work"]["eligible_actions"][0]
    assert diligence["type"] == "run_due_diligence"
    assert executor.execute_action(diligence_tick, lawyer_id, diligence)["ok"]

    close_tick = diligence_tick + 1
    close_round = builder.build(
        vc, close_tick)["startup_work"]["eligible_actions"][0]
    assert close_round["type"] == "close_funding_round"
    assert executor.execute_action(close_tick, vc_id, close_round)["ok"]

    ip_tick = close_tick + 1
    register_ip = builder.build(
        founder, ip_tick)["startup_work"]["eligible_actions"][0]
    assert register_ip["type"] == "register_ip"
    assert executor.execute_action(ip_tick, founder_id, register_ip)["ok"]

    merger_tick = ip_tick + 1
    propose_merger = builder.build(
        founder, merger_tick)["startup_work"]["eligible_actions"][0]
    assert propose_merger["type"] == "propose_merger"
    assert propose_merger["target_firm_id"] == target_id
    mutated = executor.execute_action(merger_tick, founder_id, {
        **propose_merger,
        "price_cents": propose_merger["price_cents"] + 1,
    })
    assert mutated == {
        "ok": False,
        "reason": "startup action must copy a current supplied action exactly",
    }
    merger = executor.execute_action(
        merger_tick, founder_id, propose_merger)
    assert merger["ok"], merger

    target_founder = store.query_one(
        "SELECT * FROM agents WHERE id=?", (target_founder_id,))
    approve_tick = merger_tick + 1
    approve = builder.build(
        target_founder, approve_tick)["startup_work"]["eligible_actions"][0]
    assert approve["type"] == "approve_merger"
    assert executor.execute_action(
        approve_tick, target_founder_id, approve)["ok"]

    regulator = store.query_one(
        "SELECT * FROM agents WHERE id=?", (regulator_id,))
    review_tick = approve_tick + 1
    review = builder.build(
        regulator, review_tick)["institutional_work"]["eligible_actions"][0]
    assert review["type"] == "review_merger"
    reviewed = executor.execute_action(review_tick, regulator_id, review)
    assert reviewed["ok"], reviewed
    assert reviewed["outcome"] in {"approved", "approved_with_remedy"}

    merger_close_tick = review_tick + 1
    close_merger = builder.build(
        founder, merger_close_tick)["startup_work"]["eligible_actions"][0]
    assert close_merger["type"] == "close_merger"
    assert executor.execute_action(
        merger_close_tick, founder_id, close_merger)["ok"]

    assert int(store.scalar("SELECT COUNT(*) FROM term_sheets", default=0)) == 1
    assert int(store.scalar("SELECT COUNT(*) FROM funding_rounds", default=0)) == 1
    assert int(store.scalar("SELECT COUNT(*) FROM ip_assets", default=0)) == 1
    assert int(store.scalar("SELECT COUNT(*) FROM mergers", default=0)) == 1
    assert store.scalar(
        "SELECT status FROM firms WHERE id=?", (target_id,)) == "acquired"
    assert economy.ledger.reconcile()[0]


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
