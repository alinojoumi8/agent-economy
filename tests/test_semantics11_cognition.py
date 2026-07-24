"""Provider-free checks for Semantics 11 cognition world state.

These tests instantiate live route configuration but never dispatch inference.
Live adapter behavior is covered by the paid acceptance rehearsal.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from engine.actions import ActionExecutor
from engine.cognition import SKILL_KEYS
from engine.store import Store
from llm.gateway import Gateway, LLMRequest
from llm.readiness import validate_llm_config
from reports.cognition_acceptance import build_cognition_acceptance_report
from run_config import load_config
from server.app import create_app
from world.loop import World
from world.replay_verify import verify_replay


ROOT = Path(__file__).resolve().parents[1]


def test_desktop_profile_bounds_local_resource_use():
    config = load_config(ROOT / "runs" / "evolving-live.yaml")

    assert config["llm"]["max_in_flight"] == 10
    assert config["llm"]["providers"]["ollama"]["concurrency"] == 2
    assert config["llm"]["tier_routes"]["local"]["primary"]["model"] == (
        "agent-economy-qwen3.5:9b-16k")
    assert config["checkpoint_every"] == 5
    assert config["resource_guard"]["enabled"] is True
    modelfile = (
        ROOT / "deploy" / "ollama" / "Modelfile.qwen3.5-9b-16k"
    ).read_text(encoding="utf-8")
    assert "FROM qwen3.5:9b" in modelfile
    assert "PARAMETER num_ctx 16384" in modelfile


@pytest.fixture
def cognition_world(tmp_path, monkeypatch):
    # Construction validates routed credentials before creating adapters. These
    # sentinel values are never used: this module deliberately makes zero LLM
    # calls and tests only deterministic world state and route selection.
    monkeypatch.setenv("DEEPSEEK_API_KEY", "provider-free-routing-test")
    monkeypatch.setenv("MINIMAX_API_KEY", "provider-free-routing-test")
    monkeypatch.setenv("KIMI_API_KEY", "provider-free-routing-test")
    config = load_config(ROOT / "runs" / "evolving-live.yaml")
    config["checkpoint_every"] = 0
    store = Store(str(tmp_path / "semantics11.db"))
    store.init_run_meta("semantics11", int(config["seed"]), config)
    world = World(store, config)
    world.initialize()
    try:
        yield store, world
    finally:
        world.close()


def _citizen(store: Store, tier: str) -> int:
    row = store.query_one(
        "SELECT id FROM agents WHERE alive=1 AND kind='citizen' "
        "AND role IS NULL AND model_tier=? ORDER BY id LIMIT 1",
        (tier,),
    )
    assert row is not None
    return int(row["id"])


def _skill(store: Store, agent_id: int, skill_key: str) -> tuple[int, int]:
    row = store.query_one(
        "SELECT xp,level FROM agent_skills WHERE agent_id=? AND skill_key=?",
        (agent_id, skill_key),
    )
    assert row is not None
    return int(row["xp"]), int(row["level"])


def test_exact_seed_distribution_and_authoritative_skill_rows(cognition_world):
    store, world = cognition_world
    assert world.config["entrepreneurship"]["enabled"] is True
    assert world.config["entrepreneurship"]["new_arrivals_only"] is False
    distribution = {
        str(row["model_tier"]): int(row["n"])
        for row in store.query(
            "SELECT model_tier,COUNT(*) n FROM agents "
            "WHERE alive=1 AND kind='citizen' AND role IS NULL GROUP BY model_tier"
        )
    }

    assert store.scalar(
        "SELECT COUNT(*) FROM agents WHERE alive=1", default=0
    ) == 100
    assert store.scalar(
        "SELECT COUNT(*) FROM agents WHERE alive=1 AND kind='citizen' "
        "AND role IS NULL", default=0
    ) == 65
    assert distribution == {"local": 33, "flash": 26, "premium": 6}
    assert store.scalar("SELECT COUNT(*) FROM agent_skills", default=0) == 800
    assert store.scalar(
        "SELECT COUNT(*) FROM agent_skills WHERE skill_key='household_finance' "
        "AND level>=1", default=0
    ) == 100
    assert store.scalar(
        "SELECT COUNT(*) FROM compute_subscriptions WHERE status='active'",
        default=0,
    ) == 100
    assert world.economy.ledger.reconcile()[0]


def test_prompt_advertises_study_only_on_the_agents_career_day(cognition_world):
    store, world = cognition_world
    agent_id = _citizen(store, "local")
    agent = store.query_one("SELECT * FROM agents WHERE id=?", (agent_id,))
    assert agent is not None
    cadence = json.loads(agent["cadence_json"] or "{}")
    career_every = int(cadence.get("career", 30))
    career_tick = agent_id % career_every
    ordinary_tick = career_tick + 1

    ordinary_context = world.runtime.ctx.build(agent, ordinary_tick)
    ordinary_system, ordinary_user = world.runtime.ctx.render_prompt(ordinary_context)
    assert not ordinary_context["study_skill_options"]
    assert "study_skill{skill_key}" not in ordinary_system
    assert 'never use "study" or "skill"' not in ordinary_system
    assert "[STUDY OPTIONS" not in ordinary_user

    career_context = world.runtime.ctx.build(agent, career_tick)
    career_system, career_user = world.runtime.ctx.render_prompt(career_context)
    assert career_context["study_skill_options"]
    assert "study_skill{skill_key}" in career_system
    assert 'never use "study" or "skill"' in career_system
    assert "[STUDY OPTIONS" in career_user
    assert 'Never include braces or\nthe field list in type' in career_system


def test_prompt_advertises_sponsorship_only_when_an_employee_is_eligible(
        cognition_world):
    store, world = cognition_world
    founder = store.query_one(
        "SELECT a.* FROM agents a JOIN firms f ON f.founder_agent_id=a.id "
        "WHERE f.status<>'bankrupt' AND EXISTS (SELECT 1 FROM employments e "
        "WHERE e.firm_id=f.id AND e.status='active') ORDER BY f.id LIMIT 1"
    )
    assert founder is not None

    locked_context = world.runtime.ctx.build(founder, 1)
    locked_system, locked_user = world.runtime.ctx.render_prompt(locked_context)
    assert locked_context["compute_sponsorship"] is None
    assert "set_compute_sponsorship{tier,max_seats,firm_id}" not in locked_system
    assert "[FOUNDER COMPUTE SPONSORSHIP" not in locked_user

    renewal_context = world.runtime.ctx.build(founder, 6)
    renewal_system, renewal_user = world.runtime.ctx.render_prompt(renewal_context)
    assert renewal_context["compute_sponsorship"]["actions"]
    assert "set_compute_sponsorship{tier,max_seats,firm_id}" in renewal_system
    assert "[FOUNDER COMPUTE SPONSORSHIP" in renewal_user


def test_compute_purchase_is_paid_n_plus_one_and_expires(cognition_world):
    store, world = cognition_world
    cognition = world.economy.cognition
    executor = ActionExecutor(world.economy)
    agent_id = _citizen(store, "local")
    checking = world.economy.ledger.agent_checking_id(agent_id)
    assert checking is not None
    before_cash = world.economy.ledger.balance(checking)

    locked = executor.execute_action(0, agent_id, {
        "type": "buy_compute_plan", "tier": "flash",
    })
    assert not locked["ok"]
    assert _skill(store, agent_id, "household_finance") == (10, 1)

    purchased = executor.execute_action(6, agent_id, {
        "type": "buy_compute_plan", "tier": "flash",
    })
    assert purchased["ok"]
    assert purchased["effective_tick"] == 7
    assert cognition.current_tier(agent_id) == "local"
    assert world.economy.ledger.balance(checking) == before_cash - 5_000
    assert _skill(store, agent_id, "household_finance") == (12, 1)

    cognition.run_nightly(7)
    assert cognition.current_tier(agent_id) == "flash"
    active = cognition.current_subscription(agent_id, 7)
    assert active is not None
    assert int(active["expiry_tick"]) == 14
    assert str(active["payer_type"]) == "agent"

    cognition.run_nightly(14)
    assert cognition.current_tier(agent_id) == "local"
    free = cognition.current_subscription(agent_id, 14)
    assert free is not None
    assert str(free["payer_type"]) == "free"
    assert int(free["expiry_tick"]) == 21
    off_boundary = executor.execute_action(14, agent_id, {
        "type": "buy_compute_plan", "tier": "flash",
    })
    assert not off_boundary["ok"]
    assert world.economy.ledger.reconcile()[0]


def test_skill_xp_only_follows_accepted_actions_and_study(cognition_world):
    store, world = cognition_world
    executor = ActionExecutor(world.economy)
    agent_id = _citizen(store, "local")

    media_before = _skill(store, agent_id, "media")
    rejected = executor.execute_action(1, agent_id, {
        "type": "say_public", "text": "",
    })
    assert not rejected["ok"]
    assert _skill(store, agent_id, "media") == media_before

    idle = executor.execute_action(1, agent_id, {"type": "do_nothing"})
    assert idle["ok"]
    assert _skill(store, agent_id, "media") == media_before

    ordinary = executor.execute_action(1, agent_id, {
        "type": "say_public", "text": "A committed public statement.",
    })
    assert ordinary["ok"]
    assert _skill(store, agent_id, "media")[0] == media_before[0] + 2

    lawyer = store.query_one(
        "SELECT id FROM agents WHERE alive=1 AND lower(occupation)='lawyer' "
        "ORDER BY id LIMIT 1"
    )
    assert lawyer is not None
    founder_id = None
    founding_tick = None
    founding_action = None
    for candidate in store.query(
            "SELECT a.* FROM agents a LEFT JOIN firms f ON f.founder_agent_id=a.id "
            "AND f.status<>'bankrupt' WHERE a.alive=1 AND a.kind='citizen' "
            "AND a.role IS NULL AND f.id IS NULL ORDER BY a.id"):
        for candidate_tick in (1, 2):
            candidate_context = world.runtime.ctx.build(candidate, candidate_tick)
            opportunity = candidate_context.get("entrepreneurship_opportunity")
            if opportunity:
                founder_id = int(candidate["id"])
                founding_tick = candidate_tick
                founding_action = opportunity["action"]
                break
        if founding_action:
            break
    assert founder_id is not None
    assert founding_tick is not None
    assert founding_action is not None
    entrepreneurship_before = _skill(store, founder_id, "entrepreneurship")[0]
    complex_result = executor.execute_action(
        founding_tick, founder_id, founding_action)
    assert complex_result["ok"]
    assert _skill(store, founder_id, "entrepreneurship")[0] == (
        entrepreneurship_before + 4
    )

    cadence = store.query_one(
        "SELECT cadence_json FROM agents WHERE id=?", (agent_id,)
    )
    assert cadence is not None
    career_every = int(json.loads(cadence["cadence_json"] or "{}").get("career", 30))
    career_tick = agent_id % career_every
    finance_before = _skill(store, agent_id, "finance")[0]
    studied = executor.execute_action(career_tick, agent_id, {
        "type": "study_skill", "skill_key": "finance",
    })
    assert studied["ok"]
    assert studied["xp_delta"] == 10
    assert _skill(store, agent_id, "finance")[0] == finance_before + 10
    assert store.scalar(
        "SELECT COUNT(*) FROM agent_skill_history WHERE agent_id=? "
        "AND skill_key='finance' AND source LIKE 'study:%' AND xp_delta=10",
        (agent_id,), default=0,
    ) == 1
    study_source = str(store.scalar(
        "SELECT source FROM agent_skill_history WHERE agent_id=? "
        "AND skill_key='finance' AND source LIKE 'study:%' ORDER BY id DESC LIMIT 1",
        (agent_id,), default=""))
    proposal_id = int(study_source.rsplit(":", 1)[1])
    proposal = store.query_one(
        "SELECT actor_id,action_type,validation_status FROM action_proposals WHERE id=?",
        (proposal_id,))
    assert proposal is not None
    assert dict(proposal) == {
        "actor_id": agent_id,
        "action_type": "study_skill",
        "validation_status": "accepted",
    }
    assert set(SKILL_KEYS) == {
        "household_finance", "labor", "commerce", "entrepreneurship",
        "finance", "law", "media", "governance",
    }
    assert world.economy.ledger.reconcile()[0]


def test_employer_sponsorship_bills_firm_and_changes_at_n_plus_one(cognition_world):
    store, world = cognition_world
    executor = ActionExecutor(world.economy)
    firm = store.query_one(
        "SELECT f.id,f.founder_agent_id,f.account_id FROM firms f "
        "WHERE f.status<>'bankrupt' AND f.founder_agent_id IS NOT NULL "
        "AND EXISTS (SELECT 1 FROM employments e WHERE e.firm_id=f.id "
        "AND e.status='active') ORDER BY f.id LIMIT 1"
    )
    assert firm is not None
    founder_id = int(firm["founder_agent_id"])
    firm_account = int(firm["account_id"])
    before = world.economy.ledger.balance(firm_account)

    result = executor.execute_action(6, founder_id, {
        "type": "set_compute_sponsorship",
        "tier": "flash",
        "max_seats": 2,
        "firm_id": int(firm["id"]),
    })
    assert result["ok"]
    assert result["effective_tick"] == 7
    assert 1 <= len(result["agent_ids"]) <= 2
    assert world.economy.ledger.balance(firm_account) == (
        before - 5_000 * len(result["agent_ids"])
    )
    for employee_id in result["agent_ids"]:
        pending = store.query_one(
            "SELECT payer_type,payer_id,status,effective_tick FROM compute_subscriptions "
            "WHERE agent_id=? AND status='pending' ORDER BY id DESC LIMIT 1",
            (employee_id,),
        )
        assert pending is not None
        assert dict(pending) == {
            "payer_type": "firm", "payer_id": int(firm["id"]),
            "status": "pending", "effective_tick": 7,
        }

    world.economy.cognition.run_nightly(7)
    assert all(
        world.economy.cognition.current_tier(employee_id) == "flash"
        for employee_id in result["agent_ids"]
    )
    assert world.economy.ledger.reconcile()[0]


def test_population_rebalancing_does_not_change_compute_plan(cognition_world):
    store, world = cognition_world
    before = {
        int(row["id"]): str(row["model_tier"])
        for row in store.query("SELECT id,model_tier FROM agents WHERE alive=1")
    }
    world.economy.regions.enabled = True
    world.economy.regions.core_target = 10
    world.economy.regions.rebalance_tiers(30)
    after = {
        int(row["id"]): str(row["model_tier"])
        for row in store.query("SELECT id,model_tier FROM agents WHERE alive=1")
    }
    assert after == before
    assert store.scalar(
        "SELECT COUNT(*) FROM agents WHERE alive=1 AND population_tier='core'",
        default=0,
    ) == 10


def test_population_tier_changes_wake_cadence_not_compute_tier(cognition_world):
    store, world = cognition_world
    row = store.query_one(
        "SELECT a.id FROM agents a WHERE a.alive=1 AND a.kind='citizen' "
        "AND a.role IS NULL "
        "AND EXISTS (SELECT 1 FROM employments e WHERE e.agent_id=a.id "
        "AND e.status='active') "
        "AND NOT EXISTS (SELECT 1 FROM shares s WHERE s.holder_type='agent' "
        "AND s.holder_id=a.id AND s.qty>0) ORDER BY a.id LIMIT 1"
    )
    assert row is not None
    agent_id = int(row["id"])
    original_tier = world.economy.cognition.current_tier(agent_id)
    store.execute(
        "UPDATE agents SET cadence_json=?,retired=0,health='healthy' WHERE id=?",
        ('{"act":1,"portfolio":997,"career":991}', agent_id),
    )
    tick = 201 if agent_id % 2 == 0 else 200

    store.update("agents", agent_id, population_tier="core")
    core_ids = {
        int(agent["id"]) for agent in world.runtime.scheduler.scheduled_agents(tick)
    }
    store.update("agents", agent_id, population_tier="periphery")
    periphery_ids = {
        int(agent["id"]) for agent in world.runtime.scheduler.scheduled_agents(tick)
    }

    assert agent_id in core_ids
    assert agent_id not in periphery_ids
    assert world.economy.cognition.current_tier(agent_id) == original_tier


def test_route_plans_follow_tier_role_and_background_policy(cognition_world):
    store, world = cognition_world
    gateway: Gateway = world.gateway
    selected_ids = {
        agent_id
        for cohort in gateway.citizen_model_assignment_status()
        for agent_id in cohort["agent_ids"]
    }

    def ordinary_citizen(tier: str) -> int:
        return next(
            int(row["id"])
            for row in store.query(
                "SELECT id FROM agents WHERE alive=1 AND kind='citizen' "
                "AND role IS NULL AND model_tier=? ORDER BY id", (tier,))
            if int(row["id"]) not in selected_ids
        )

    local_id = ordinary_citizen("local")
    premium_id = ordinary_citizen("premium")

    local = gateway.route_plan(LLMRequest(
        role="citizen", purpose="decision", agent_id=local_id,
    ))
    assert local.assigned_tier == "local"
    assert [(t.provider, t.model) for t in local.targets] == [
        ("ollama", "agent-economy-qwen3.5:9b-16k"),
        ("deepseek", "deepseek-v4-flash"),
    ]

    premium_background = gateway.route_plan(LLMRequest(
        role="citizen", purpose="memory", agent_id=premium_id,
    ))
    assert premium_background.assigned_tier == "premium"
    assert premium_background.effective_tier == "flash"
    assert premium_background.targets[0].provider == "deepseek"

    founder = gateway.route_plan(LLMRequest(
        role="founder", purpose="decision", agent_id=premium_id,
    ))
    assert founder.targets[0].provider == "kimi"
    assert founder.targets[1].provider == "deepseek"
    assert gateway._request_priority(LLMRequest(
        role="central_banker", purpose="decision",
    )) < gateway._request_priority(LLMRequest(
        role="citizen", purpose="conversation",
    ))


def test_cloud_cohorts_assign_exactly_five_each_and_preserve_other_routes(
        cognition_world):
    store, world = cognition_world
    gateway: Gateway = world.gateway
    status = gateway.citizen_model_assignment_status()

    assert [(row["model"], row["assigned_count"]) for row in status] == [
        ("glm-5.1:cloud", 5),
        ("gemma4:cloud", 5),
        ("nemotron-3-super:cloud", 5),
    ]
    selected = {
        agent_id: row["model"]
        for row in status
        for agent_id in row["agent_ids"]
    }
    assert len(selected) == 15
    expected_regular = {
        "local": ("ollama", "agent-economy-qwen3.5:9b-16k"),
        "flash": ("deepseek", "deepseek-v4-flash"),
        "premium": ("kimi", "kimi-for-coding"),
    }
    for row in store.query(
            "SELECT id,model_tier FROM agents WHERE alive=1 AND kind='citizen' "
            "ORDER BY id"):
        agent_id = int(row["id"])
        plan = gateway.route_plan(LLMRequest(
            role="citizen", purpose="decision", agent_id=agent_id))
        primary = (plan.targets[0].provider, plan.targets[0].model)
        if agent_id in selected:
            assert primary == ("ollama_cloud", selected[agent_id])
            assert plan.targets[1].provider == "deepseek"
            assert "deterministic citizen model cohort" in plan.reason
        else:
            assert primary == expected_regular[str(row["model_tier"])]

    # The identity override remains in force when a selected citizen acts in a
    # specialized role, while the compute subscription itself remains intact.
    selected_id = min(selected)
    founder_plan = gateway.route_plan(LLMRequest(
        role="founder", purpose="decision", agent_id=selected_id))
    assert founder_plan.targets[0].provider == "ollama_cloud"
    assert gateway.provider_gates["ollama_cloud"].capacity == 3
    cloud_readiness = next(
        row for row in gateway.readiness()["providers"]
        if row["name"] == "ollama_cloud")
    assert set(cloud_readiness["models"]) == {
        "glm-5.1:cloud", "gemma4:cloud", "nemotron-3-super:cloud",
    }


def test_cloud_cohort_config_rejects_invalid_counts(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "provider-free-routing-test")
    monkeypatch.setenv("MINIMAX_API_KEY", "provider-free-routing-test")
    monkeypatch.setenv("KIMI_API_KEY", "provider-free-routing-test")
    config = deepcopy(load_config(ROOT / "runs" / "evolving-live.yaml"))
    config["llm"]["citizen_model_cohorts"][0]["count"] = 0

    report = validate_llm_config(config, raise_on_error=False)

    assert not report["ready"]
    assert "count must be a positive integer" in " ".join(report["errors"])


def test_runtime_and_agent_cognition_api_projection(cognition_world):
    store, world = cognition_world
    agent_id = _citizen(store, "premium")
    with TestClient(create_app(world)) as client:
        runtime_response = client.get("/api/llm/runtime")
        detail_response = client.get(f"/api/agents/{agent_id}")

    assert runtime_response.status_code == 200
    runtime = runtime_response.json()
    assert runtime["global"] == {
        "capacity": 10,
        "in_flight": 0,
        "queue_depth": 0,
        "peak_in_flight": 0,
        "peak_queue_depth": 0,
        "logical_deadline_s": 240.0,
    }
    assert runtime["simulated_days"] == {
        "samples": 0, "p50_wall_ms": None, "p95_wall_ms": None,
    }
    assert {
        lane["provider"]: lane["capacity"] for lane in runtime["providers"]
    } == {
        "deepseek": 6, "kimi": 2, "minimax": 2,
        "ollama": 2, "ollama_cloud": 3,
    }
    assert [row["assigned_count"] for row in runtime["citizen_model_cohorts"]] == [
        5, 5, 5,
    ]

    assert detail_response.status_code == 200
    detail = detail_response.json()
    cognition = detail["cognition"]
    assert cognition["compute_plan"]["tier"] == "premium"
    assert cognition["compute_plan"]["expiry_tick"] == 7
    assert cognition["latest_route"] is None
    assert detail["execution"]["state"] == "awaiting_live"
    assert detail["execution"]["latest_receipt"] is None
    assert len(cognition["skills"]) == 8
    assert cognition["skill_history"]
    assert cognition["subscription_history"]


def test_agent_execution_projection_requires_a_durable_call_receipt(cognition_world):
    store, world = cognition_world
    agent_id = _citizen(store, "premium")
    call_id = store.insert(
        "llm_calls",
        tick=3,
        agent_id=agent_id,
        role="citizen",
        provider="kimi",
        model="kimi-for-coding",
        purpose="decision",
        cache_key="execution-projection-test",
        request_json="{}",
        response_json="{}",
        created_at="2026-07-23T12:00:00+00:00",
    )
    store.commit()

    with TestClient(create_app(world)) as client:
        rows = client.get("/api/agents").json()
        detail = client.get(f"/api/agents/{agent_id}").json()

    listed = next(row for row in rows if row["id"] == agent_id)
    assert listed["execution"]["state"] == "live"
    assert listed["execution"]["provider"] == "kimi"
    assert listed["execution"]["latest_receipt"] == {
        "kind": "llm_call",
        "id": call_id,
        "status": "recorded",
        "tick": 3,
    }
    assert detail["execution"] == listed["execution"]


def test_completed_tick_runtime_stats_are_operational_and_queryable(cognition_world):
    store, world = cognition_world
    world._record_runtime_tick(1, {"wall_s": 2.5, "decisions": 17})

    row = store.query_one("SELECT * FROM runtime_tick_stats WHERE tick=1")
    assert row is not None
    assert float(row["wall_ms"]) == 2500.0
    assert int(row["decisions"]) == 17
    assert int(row["llm_attempts"]) == 0
    runtime = world.gateway.runtime_status()
    assert runtime["simulated_days"] == {
        "samples": 1, "p50_wall_ms": 2500.0, "p95_wall_ms": 2500.0,
    }


def test_cognition_receipt_reads_persisted_state_without_inference(cognition_world):
    store, _world = cognition_world
    report = build_cognition_acceptance_report(store.path)
    checks = {check["id"]: check for check in report["checks"]}

    assert checks["versions"]["passed"]
    assert checks["initial_distribution"]["passed"]
    assert checks["skill_history"]["passed"]
    assert not checks["live_provenance"]["passed"]
    assert not checks["fault_probe"]["passed"]
    assert not checks["exact_replay"]["passed"]


def test_operational_attempt_and_timing_rows_are_excluded_from_exact_replay(tmp_path):
    source = Store(str(tmp_path / "source.db"))
    replay = Store(str(tmp_path / "replay.db"))
    try:
        config = {"engine_semantics_version": 11}
        source.init_run_meta("source", 11, config)
        replay.init_run_meta("replay", 11, config)
        source.insert(
            "llm_attempts", request_key="operational", llm_call_id=None,
            tick=1, phase="LLM", agent_id=None, role="citizen", purpose="decision",
            assigned_tier="local", route_reason="test", route_index=0,
            provider="ollama", model="qwen3.5:9b", queue_wait_ms=1.0,
            provider_latency_ms=2.0, active_at_start=0, queued_at_start=0,
            global_active_at_start=0, global_queued_at_start=0,
            provider_peak_observed=1, global_peak_observed=1,
            outcome="success", error_type=None, error_message=None,
            rate_limited=0, fallback_used=0)
        source.execute(
            "INSERT INTO runtime_tick_stats("
            "tick,wall_ms,decisions,llm_attempts,llm_successes,llm_failures,"
            "fallbacks,rate_limits,peak_live_in_flight,peak_queue_depth) "
            "VALUES (1,1000,1,1,1,0,0,0,1,0)")
        source.commit()
        replay.commit()

        proof = verify_replay(source.path, replay.path)
        assert proof["exact"] is True
        assert proof["differences"] == []
    finally:
        source.close()
        replay.close()
