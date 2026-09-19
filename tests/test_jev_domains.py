"""Bounded domain choices are real alternatives, with deterministic authority."""
import ast
import asyncio
from copy import deepcopy
from pathlib import Path

import pytest

from agents.decision_candidates import compile_candidates
from agents.decision_domains import ACTION_DOMAIN, COMMONS_OPERATIONS, DOMAINS, validate_coverage
from agents.typed_policy import TypedDecisionPolicy
from engine.actions import VALID_TYPES
from llm.decision_config import POLICY_VERSION_V4, decision_policy
from tests.test_jev_candidates import observation
from tests.test_jev_gateway import configuration


def domain_config(*domains):
    config = configuration()
    config["llm"]["decision_policy"].update(version=POLICY_VERSION_V4, domains=list(domains),
        primary={"provider": "scripted", "model": "scripted"})
    return config


def test_every_registered_command_and_commons_operation_is_classified():
    validate_coverage(VALID_TYPES)
    assert len(ACTION_DOMAIN) == 110
    source = Path(__file__).resolve().parents[1] / "world/commons.py"
    method = next(n for n in ast.walk(ast.parse(source.read_text(encoding="utf-8")))
                  if isinstance(n, ast.FunctionDef) and n.name == "act")
    names = {value.value for node in ast.walk(method) if isinstance(node, ast.Compare)
             and isinstance(node.left, ast.Name) and node.left.id == "kind"
             for value in node.comparators if isinstance(value, ast.Constant)}
    assert names == COMMONS_OPERATIONS
    with pytest.raises(ValueError, match="coverage"):
        validate_coverage(VALID_TYPES | {"new_unreviewed_action"})


def test_v4_is_explicit_opt_in_and_old_versions_reject_new_fields():
    config = domain_config()
    assert TypedDecisionPolicy(None, config).prepare(observation(), 4) is None
    config["llm"]["decision_policy"]["domains"] = ["unknown"]
    with pytest.raises(ValueError, match="supported"):
        decision_policy(config)


def test_strategic_review_retains_the_existing_route():
    context = observation()
    policy = decision_policy(domain_config("consumption"))
    context["agent"]["id"] = context["tick"] % policy["strategic_review_interval_ticks"]
    assert compile_candidates(context, context["tick"], policy).unsupported_reason == "scheduled_strategic_review"
    config = configuration()
    config["llm"]["decision_policy"]["domains"] = ["consumption"]
    with pytest.raises(ValueError, match="known fields"):
        decision_policy(config)


def test_v4_menu_is_pure_bounded_and_preserves_complete_resource_bundles():
    context = observation()
    context["pending_job_ids"] = []
    original = deepcopy(context)
    menu = compile_candidates(context, 4, decision_policy(domain_config("consumption", "career")))
    assert context == original
    assert menu.metadata["domains"] == ["career", "consumption", "consumption+career"]
    assert len(menu.candidates) <= 64
    assert "private_balance_sheet" not in menu.evaluation_json
    assert "other_unneeded_private_content" not in menu.evaluation_json
    assert {a["type"] for a in menu.actions_for(menu.baseline_choice)} == {"buy_goods", "apply_job"}
    for choice in menu.candidates:
        assert sum(choice.get("requirements", {}).values()) <= 600


def test_founder_selects_prices_and_hiring_without_using_personal_cash():
    context = observation()
    context.update(purpose="founder", my_firm={"firm_id": 8, "price": 200, "cash": 6000,
        "currency_code": "CAD", "payroll": 5000, "employees": 1, "target_headcount": 2,
        "open_jobs": 1, "employee_roster": [], "executed_sales_units": 3},
        firm_applications=[{"application_id": 9, "agent_id": 10, "posted_wage": 1100}],
        decision_resources={"firm:8:CAD": {"available_cents": 1000}})
    menu = compile_candidates(context, 4, decision_policy(domain_config("founder_operations")))
    actions = [a for c in menu.candidates for a in c["actions"]]
    assert {a["price"] for a in actions if a["type"] == "set_price"} == {190, 200, 210}
    assert not any(a["type"] == "make_job_offer" for a in actions)
    context["decision_resources"]["firm:8:CAD"]["available_cents"] = 1500
    assert any(a["type"] == "make_job_offer" for c in compile_candidates(context, 4,
        decision_policy(domain_config("founder_operations"))).candidates for a in c["actions"])


def test_stock_choices_account_for_commitments_and_do_not_invent_market_prices():
    context = observation()
    context.update(portfolio_day=True, listed_firms=[{"firm_id": 4, "last_price": None,
        "name": "Visible Company", "cash": 800, "inventory": 50, "recent_revenue_7": 200,
        "book_value_per_share": 100, "currency_code": "CAD", "private_balance_sheet": "hidden"}],
        open_equity_orders=[{"firm_id": 4, "side": "sell", "qty_remaining": 2}],
        ipo_offerings=[{"offering_id": 9, "firm_id": 5, "firm_name": "Upcoming Company",
            "shares_offered": 100, "reserve_price": 50, "minimum_subscription_bps": 5000,
            "book_demand": 10, "currency_code": "CAD", "private_owner_note": "hidden"}],
        decision_resources={"agent:7:CAD": {"available_cents": 200}})
    context["state"]["shares"] = {"4": 3}
    menu = compile_candidates(context, 4, decision_policy(domain_config("investment")))
    orders = [a for c in menu.candidates for a in c["actions"] if a["type"] == "place_order"]
    market = menu.evaluation["state"]["investment_market"]
    assert market["listed_firms"][0]["recent_revenue_7"] == 200
    assert market["listed_firms"][0]["name"] == "Visible Company"
    assert market["ipo_offerings"][0]["book_demand"] == 10
    assert market["open_equity_orders"] == context["open_equity_orders"]
    assert "private_balance_sheet" not in menu.evaluation_json
    assert "private_owner_note" not in menu.evaluation_json
    assert orders and {a["side"] for a in orders} == {"buy", "sell"}
    assert all(a["qty"] <= 1 for a in orders if a["side"] == "sell")
    assert all(a["qty"] * a["limit_price"] <= 200 for a in orders if a["side"] == "buy")
    assert context["listed_firms"][0]["last_price"] is None
    context["listed_firms"][0]["book_value_per_share"] = 0
    menu = compile_candidates(context, 4, decision_policy(domain_config("investment")))
    assert not any(a["type"] == "place_order" for c in menu.candidates for a in c["actions"])


def test_study_and_civic_actions_do_not_mix_with_shopping():
    context = observation()
    context["study_skill_options"] = [{"skill_key": "finance", "price_cents": 100,
                                      "action": {"type": "study_skill", "skill_key": "finance"}}]
    policy = decision_policy(domain_config("consumption", "learning_compute", "entrepreneurship"))
    menu = compile_candidates(context, 4, policy)
    assert all(len(c["actions"]) == 1 for c in menu.candidates if any(a["type"] == "study_skill" for a in c["actions"]))
    context["civic_required_action"] = {"type": "attend_civic_appointment", "appointment_id": 3}
    actions = [a for c in compile_candidates(context, 4, policy).candidates for a in c["actions"]]
    assert [a["type"] for a in actions] == ["attend_civic_appointment"]


def test_unrepresented_judgment_and_menu_overflow_keep_existing_route():
    context = observation()
    context["institutional_work"] = {"eligible_actions": [{"type": "issue_legal_decision", "matter_id": 5}]}
    policy = decision_policy(domain_config("consumption"))
    assert compile_candidates(context, 4, policy).unsupported_reason
    context.pop("institutional_work")
    policy["max_candidates"] = 3
    assert compile_candidates(context, 4, policy).unsupported_reason == "menu_capacity_exceeded"


def test_political_and_household_choices_keep_no_and_independent_consent():
    context = observation()
    context["institutional_work"] = {"bills": [{"id": 3, "policy_changes": {"tax_rate_bps": 1500}}],
        "eligible_actions": [{"type": "committee_vote", "bill_id": 3, "vote": vote} for vote in ("yes", "no", "abstain")]}
    context["household_decisions"] = {"pending": [{"id": 4}], "eligible_actions": [
        {"type": "respond_household", "household_decision_id": 4, "decision": decision} for decision in ("accept", "reject")]}
    menu = compile_candidates(context, 4, decision_policy(domain_config("politics", "household_time")))
    actions = [a for c in menu.candidates for a in c["actions"]]
    assert {a["vote"] for a in actions if a["type"] == "committee_vote"} == {"yes", "no", "abstain"}
    assert {a["decision"] for a in actions if a["type"] == "respond_household"} == {"accept", "reject"}


def test_score_rubrics_obey_live_contract_but_legacy_replay_can_read_old_shapes():
    from llm.decisions import validate_evaluation
    request = {"state": "fixture", "questions": {"score": {"type": "score", "instructions": "Rate relevance", "criteria": [str(i) for i in range(11)]}}}
    with pytest.raises(ValueError, match="10"):
        validate_evaluation(request)
    assert validate_evaluation(request, legacy_score_rubric=True) == request


def test_domain_world_runs_and_replays_without_network(tmp_path, monkeypatch):
    import hashlib
    import json
    import httpx
    from run import open_run, replay_headless
    from run_config import load_config
    from world.replay_verify import verify_replay

    async def forbidden(*args, **kwargs):
        raise AssertionError("provider network is disabled")
    monkeypatch.setattr(httpx.AsyncClient, "post", forbidden)
    root = Path(__file__).resolve().parents[1]
    config = load_config(root / "runs/jev-domains-offline.yaml")
    config.update(checkpoint_dir=str(tmp_path / "checkpoints"), report_dir=str(tmp_path / "reports"))
    store, world, run_id = open_run(config, None, None, data_dir=tmp_path)
    path = Path(store.path)
    try:
        async def steps():
            for _ in range(3):
                await world.step()
        asyncio.run(steps())
        receipts = [json.loads(r[0]) for r in store.query("SELECT payload_json FROM events WHERE kind='typed_decision'")]
        assert any(r["contract"] == POLICY_VERSION_V4 and "founder_operations" in r["domains"] for r in receipts)
        assert all(not r["calls"] for r in receipts if r["status"] == "selected")
        assert world.economy.ledger.reconcile()[0]
    finally:
        world.close()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    replay_store, replay_world, _ = open_run({}, None, run_id, data_dir=tmp_path)
    try:
        asyncio.run(replay_headless(replay_world, 3))
        assert replay_world.gateway._live_dispatch_count == 0
        proof = verify_replay(path, replay_store.path)
        assert proof["exact"], proof["differences"]
        assert replay_world.economy.ledger.reconcile()[0]
    finally:
        replay_world.close()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest


def test_real_founding_catalog_has_distinct_affordable_businesses_and_checkpointed_authority(store):
    import random
    from agents.memory import Memory
    from agents.prompts import ContextBuilder
    from engine.actions import ActionExecutor
    from engine.core import Economy
    from tests.test_native_entrepreneurship import _economy, _citizen
    from tests.conftest import make_agent
    from world.startup_authorizations import capture_startup_authorizations, restore_startup_authorizations
    old, config, bank = _economy(store)
    config.update(engine_semantics_version=16)
    config["llm"] = domain_config("entrepreneurship")["llm"]
    economy = Economy(store, config, random.Random(101), random.Random(202))
    citizen, account = _citizen(economy, bank)
    make_agent(economy, bank, name="Counsel", occupation="lawyer", role="lawyer", cash=50000)
    builder = ContextBuilder(economy, Memory(store, config), config)
    actor = store.query_one("SELECT * FROM agents WHERE id=?", (citizen,))
    context = builder.build(actor, 11)
    menu = compile_candidates(context, 11, decision_policy(config))
    options = [c["actions"][0] for c in menu.candidates if c["actions"]]
    assert len({a["sector"] for a in options}) >= 2
    assert len({a["opening_capital"] for a in options}) >= 2
    frame = capture_startup_authorizations(11, economy._startup_action_authorizations)
    economy._startup_action_authorizations = restore_startup_authorizations(11, frame)
    selected = options[-1]
    before = economy.ledger.balance(account)
    result = ActionExecutor(economy).execute_action(11, citizen, selected)
    assert result["ok"], result
    assert economy.ledger.balance(account) == before - selected["opening_capital"]
    assert economy.ledger.reconcile()[0]


@pytest.mark.parametrize("risk", [0.0, 1.0])
def test_native_context_preserves_risk_boundaries_in_model_observations(store, risk):
    import random
    from agents.memory import Memory
    from agents.prompts import ContextBuilder
    from engine.core import Economy
    from tests.test_native_entrepreneurship import _economy, _citizen

    _, config, bank = _economy(store)
    config.update(engine_semantics_version=16)
    config["llm"] = domain_config("consumption")["llm"]
    economy = Economy(store, config, random.Random(101), random.Random(202))
    citizen, _ = _citizen(economy, bank)
    store.update("agents", citizen, risk_tolerance=risk)
    actor = store.query_one("SELECT * FROM agents WHERE id=?", (citizen,))
    builder = ContextBuilder(economy, Memory(store, config), config)
    context = builder.build(actor, 11)
    menu = compile_candidates(context, 11, decision_policy(config))
    assert context["agent"]["risk_tolerance"] == risk
    assert menu.evaluation["state"]["actor"]["risk_tolerance"] == risk
