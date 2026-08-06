import asyncio
import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agents.memory import Memory
from agents.numeric_grounding import (
    model_grounding_active,
    narrative_numbers_are_grounded,
    numeric_claims,
    sanitize_model_numeric_narrative,
)
from engine.store import Store
from run import activate_numeric_grounding_for_run, open_run
from server.app import create_app
from world.loop import World
from world.metrics import Metrics
from world.replay_verify import verify_replay


def _config(tmp_path, *, visibility="public_status", semantics=3):
    return {
        "seed": 17,
        "engine_semantics_version": semantics,
        "information": {"citizen_bank_visibility": visibility},
        "beliefs": {"audit_history": True, "enforce_reserved_ranges": True},
        "population": {"size": 12},
        "banks": {"count": 2},
        "firms": {"count": 3, "listed": 1},
        "behavior": {"act_every": 1, "run_threshold": 0.35},
        "budget": {"cap_usd": 200.0, "oracle_reserve_usd": 10.0,
                   "conversation_pairs": 0},
        "llm": {"default_route": {"provider": "scripted", "model": "scripted"},
                "routes": {}},
        "checkpoint_every": 0,
        "checkpoint_dir": str(tmp_path / "checkpoints"),
        "report_dir": str(tmp_path / "reports"),
        "outlets": [{"id": 1, "name": "A", "slant": "market"},
                    {"id": 2, "name": "B", "slant": "labor"}],
        "central_bank": {"target_inflation": 0.02, "neutral_rate_bps": 500},
    }


def _world(tmp_path, name="research.db", **kwargs):
    config = _config(tmp_path, **kwargs)
    store = Store(str(tmp_path / name))
    store.init_run_meta(name, config["seed"], config)
    world = World(store, config)
    world.initialize()
    return world


def test_numeric_claims_canonicalize_money_percent_commas_and_signs():
    assert numeric_claims(
        "Revenue was $3,000.00, up 7.50% from -2; +4 was unchanged."
    ) == {"$3000", "7.5%", "-2", "4"}
    assert numeric_claims("Malformed 12,34 is not a claim") == set()
    assert numeric_claims(
        "Scientific 1e-05, +2.5E+3, and $4e2 are complete claims."
    ) == {"0.00001", "2500", "$400"}


def test_numeric_redaction_governance_events_do_not_become_agent_memories(tmp_path):
    world = _world(tmp_path, "redaction-observation.db")
    try:
        agent_id = int(world.store.scalar(
            "SELECT id FROM agents WHERE alive=1 ORDER BY id LIMIT 1"))
        world.store.log_event(
            0, "model_numeric_narrative_redacted", {"reason": "ungrounded number"},
            subject_type="agent", subject_id=agent_id, importance=1.0,
        )
        world.store.log_event(
            0, "goods_sale", {"quantity": 1}, subject_type="agent",
            subject_id=agent_id, importance=1.0,
        )
        world.runtime.capture_event_observations(0)
        memories = [str(row["text"]) for row in world.store.query(
            "SELECT text FROM memories WHERE agent_id=? AND tick=0 ORDER BY id",
            (agent_id,),
        )]
        assert memories == ["I bought goods."]
    finally:
        world.close()


def test_public_narrative_accepts_only_exact_supplied_numeric_tokens():
    sources = {
        "headline_fact": "$3,000.00",
        "output": 30,
        "baseline": 20,
        "flags": [True, False],
    }

    assert narrative_numbers_are_grounded("Revenue was $3000.", sources)
    assert narrative_numbers_are_grounded(
        "Threshold was 1e-05.", {"threshold": 1e-5})
    assert not narrative_numbers_are_grounded(
        "Threshold was 1e-06.", {"threshold": 1e-5})
    assert not narrative_numbers_are_grounded("Output rose 75%.", sources)
    assert not narrative_numbers_are_grounded("There were 1 flags.", {"flag": True})
    assert sanitize_model_numeric_narrative(
        "Revenue was $3000.",
        grounding_enabled=True,
        fallback="Current engine facts are authoritative.",
        sources=sources,
    ) == "Revenue was $3000."
    assert sanitize_model_numeric_narrative(
        "Output rose 75%.",
        grounding_enabled=True,
        fallback="Current engine facts are authoritative.",
        sources=sources,
    ) == "Current engine facts are authoritative."
    assert sanitize_model_numeric_narrative(
        "Historical text remains unchanged at 75%.",
        grounding_enabled=False,
        fallback="fallback",
    ) == "Historical text remains unchanged at 75%."


@pytest.mark.parametrize(
    ("active_tick", "next_phase", "expected_activation"),
    [
        (None, "MORNING", 358),
        (358, "MORNING", 358),
        (358, "EXECUTION", 359),
    ],
)
def test_numeric_grounding_activation_uses_next_untouched_boundary(
        tmp_path, active_tick, next_phase, expected_activation):
    store = Store(str(tmp_path / f"numeric-{next_phase}-{active_tick}.db"))
    store.init_run_meta(
        "numeric",
        42,
        {"engine_semantics_version": 7, "beliefs": {"audit_history": True}},
    )
    store.set_meta(
        status="paused",
        tick=357,
        active_tick=active_tick,
        next_phase=next_phase,
    )
    store.commit()

    first = activate_numeric_grounding_for_run(store)
    second = activate_numeric_grounding_for_run(store)
    persisted = json.loads(store.get_meta()["config_json"])["beliefs"]

    assert first == second == {
        "model_grounding_from_tick": expected_activation,
        "model_max_reserved_step": 0.05,
    }
    assert persisted["audit_history"] is True
    assert model_grounding_active({"beliefs": persisted}, expected_activation)
    assert not model_grounding_active(
        {"beliefs": persisted}, expected_activation - 1)
    store.close()


def test_existing_numeric_grounding_boundary_is_normalized_and_persisted(tmp_path):
    store = Store(str(tmp_path / "existing-numeric-boundary.db"))
    store.init_run_meta(
        "existing-numeric-boundary",
        42,
        {"beliefs": {
            "audit_history": True,
            "model_grounding_from_tick": "-2",
            "model_max_reserved_step": "0.125",
        }},
    )
    store.set_meta(status="paused", tick=8, active_tick=None, next_phase="MORNING")
    store.commit()

    settings = activate_numeric_grounding_for_run(store)
    persisted = json.loads(store.get_meta()["config_json"])["beliefs"]

    assert settings == {
        "model_grounding_from_tick": 0,
        "model_max_reserved_step": 0.125,
    }
    assert persisted == {
        "audit_history": True,
        "model_grounding_from_tick": 0,
        "model_max_reserved_step": 0.125,
    }
    store.close()


def test_grounded_model_reserved_beliefs_require_baseline_and_bounded_step(tmp_path):
    store = Store(str(tmp_path / "grounded-beliefs.db"))
    config = {
        "beliefs": {
            "audit_history": True,
            "enforce_reserved_ranges": True,
            "model_grounding_from_tick": 5,
            "model_max_reserved_step": 0.05,
        },
    }
    store.init_run_meta("grounded-beliefs", 42, config)
    memory = Memory(store, config)
    memory.set_belief(1, "sentiment", 0.10, 4, source="direct")

    assert memory.set_belief(
        1,
        "sentiment",
        0.14,
        5,
        source="decision",
        source_llm_call_id=99,
    ) == pytest.approx(0.14)
    with pytest.raises(ValueError, match="step"):
        memory.set_belief(
            1,
            "sentiment",
            0.30,
            6,
            source="decision",
            source_llm_call_id=100,
        )
    with pytest.raises(ValueError, match="baseline"):
        memory.set_belief(
            1,
            "inflation_expectation",
            0.02,
            6,
            source="memory",
            source_llm_call_id=101,
        )

    assert memory.get_beliefs(1) == {"sentiment": pytest.approx(0.14)}
    reasons = {
        json.loads(row["payload_json"])["reason"]
        for row in store.query(
            "SELECT payload_json FROM events "
            "WHERE kind='belief_update_rejected' ORDER BY id"
        )
    }
    assert reasons == {"missing_model_baseline", "model_reserved_step_limit"}
    assert memory.set_belief(
        1, "sentiment", -0.8, 7, source="scripted_policy"
    ) == -0.8
    store.close()


@pytest.mark.parametrize("enforce_ranges", [True, False])
def test_grounded_model_belief_step_uses_raw_value_even_without_range_clamping(
        tmp_path, enforce_ranges):
    store = Store(str(tmp_path / f"raw-step-{enforce_ranges}.db"))
    config = {
        "beliefs": {
            "audit_history": True,
            "enforce_reserved_ranges": enforce_ranges,
            "model_grounding_from_tick": 1,
            "model_max_reserved_step": 0.05,
        },
    }
    store.init_run_meta("raw-step", 42, config)
    memory = Memory(store, config)
    memory.set_belief(1, "sentiment", 0.98, 0, source="direct")

    with pytest.raises(ValueError, match="step"):
        memory.set_belief(
            1, "sentiment", 2.0, 1, source="decision",
            source_llm_call_id=99,
        )

    assert memory.get_beliefs(1)["sentiment"] == pytest.approx(0.98)
    store.close()


def test_grounded_prompt_labels_authoritative_facts_and_stale_memories(tmp_path):
    world = _world(tmp_path, "grounded-prompt.db")
    world.config["beliefs"].update({
        "model_grounding_from_tick": 1,
        "model_max_reserved_step": 0.125,
    })
    world.runtime.mem.model_max_reserved_step = 0.125
    world.runtime.ctx.config = world.config
    citizen = world.store.query_one(
        "SELECT * FROM agents WHERE kind='citizen' AND role IS NULL ORDER BY id LIMIT 1"
    )
    world.runtime.mem.observe(
        int(citizen["id"]), 0, "A historical number was 987654321.")

    context = world.runtime.ctx.build(citizen, 1)
    system, prompt = world.runtime.ctx.render_prompt(context)

    assert "CURRENT ENGINE FACTS ARE AUTHORITATIVE" in system
    assert "model_max_reserved_step=0.125" in system
    assert "MEMORIES - HISTORICAL; NUMERIC VALUES MAY BE STALE" in prompt
    assert "cents (= " in prompt
    world.close()


def test_model_reasoning_is_grounded_publicly_while_raw_call_remains_auditable(
        tmp_path):
    world = _world(tmp_path, "grounded-reasoning.db")
    world.config["beliefs"].update({
        "model_grounding_from_tick": 1,
        "model_max_reserved_step": 0.05,
    })
    world.runtime.config = world.config
    world.runtime.ctx.config = world.config
    citizen = world.store.query_one(
        "SELECT * FROM agents WHERE kind='citizen' AND role IS NULL ORDER BY id LIMIT 1"
    )
    world.runtime.mem.observe(
        int(citizen["id"]), 0, "A stale memory claimed output rose 987654321%.",
    )
    raw = {
        "reasoning": "Output rose 987654321%.",
        "actions": [{"type": "do_nothing"}],
        "belief_updates": [],
    }
    call_id = world.store.insert(
        "llm_calls",
        tick=1,
        agent_id=int(citizen["id"]),
        role="citizen",
        provider="minimax",
        model="MiniMax-M3",
        purpose="decision",
        response_json=json.dumps(raw, sort_keys=True),
    )

    class GroundingGateway:
        async def complete(self, *_args, **_kwargs):
            return SimpleNamespace(parsed=dict(raw), call_id=call_id)

    world.runtime.gw = GroundingGateway()
    decision = asyncio.run(world.runtime._decide_one(1, citizen))

    assert decision["reasoning"] == (
        "I used the current structured engine facts to choose this action."
    )
    assert decision["envelope"]["reasoning"] == decision["reasoning"]
    assert "987654321%" in world.store.scalar(
        "SELECT response_json FROM llm_calls WHERE id=?", (call_id,))

    world.runtime.execute_decisions(1, [decision])
    proposal = world.store.query_one(
        "SELECT rationale_summary FROM action_proposals ORDER BY id DESC LIMIT 1"
    )
    assert proposal["rationale_summary"] == decision["reasoning"]
    assert not world.store.query_one(
        "SELECT 1 FROM memories WHERE text='Output rose 987654321%.'"
    )
    world.close()


def test_memory_summaries_ground_numbers_in_the_exact_model_sources(tmp_path):
    world = _world(tmp_path, "summary-grounding.db")
    world.config["beliefs"].update({"model_grounding_from_tick": 1})
    world.runtime.config = world.config
    agent_id = int(world.store.scalar(
        "SELECT id FROM agents WHERE kind='citizen' ORDER BY id LIMIT 1"
    ))
    world.runtime.mem.observe(
        agent_id, 1, "Demand changed without a measured figure.", importance=4.7,
    )

    class SummaryGateway:
        async def complete(self, request, **_kwargs):
            if request.user.startswith("["):
                return SimpleNamespace(
                    parsed={"summary": "The prior model summary said 777.", "importance": 2},
                    call_id=2,
                )
            return SimpleNamespace(
                parsed={
                    "summary": (
                        "Observation importance was "
                        f"{request.context['observations'][0]['importance']}."
                    ),
                    "importance": 2,
                    "belief_updates": [],
                },
                call_id=1,
            )

    world.runtime.gw = SummaryGateway()
    daily = asyncio.run(world.runtime._compress_one(1, agent_id))
    assert daily[0] == "I reviewed today's recorded observations."
    world.runtime.mem.write_summary(agent_id, 1, "A prior model summary said 777.", 2)
    weekly = asyncio.run(world.runtime._rollup_week(1, agent_id, 1))
    assert weekly[0] == "The prior model summary said 777."
    world.close()


def test_bank_information_is_role_scoped_and_legacy_default_is_full(tmp_path):
    world = _world(tmp_path)
    citizen = world.store.query_one(
        "SELECT * FROM agents WHERE kind='citizen' AND role IS NULL ORDER BY id LIMIT 1")
    citizen_banks = world.runtime.ctx.build(citizen, 1)["banks"]
    assert citizen_banks and all("reserve_ratio" not in bank for bank in citizen_banks)

    officers = world.store.query(
        "SELECT * FROM agents WHERE role='credit_officer' ORDER BY id")
    assert len(officers) == 2
    for officer in officers:
        officer_banks = world.runtime.ctx.build(officer, 1)["banks"]
        private_ids = [
            bank["id"] for bank in officer_banks if "reserve_ratio" in bank]
        assert private_ids == [int(officer["employer_id"])]

    governor = world.store.query_one(
        "SELECT * FROM agents WHERE role='central_banker' LIMIT 1")
    assert all(
        "reserve_ratio" in bank
        for bank in world.runtime.ctx.build(governor, 1)["banks"])
    world.store.close()

    legacy = _world(tmp_path, "legacy-info.db", visibility="full_balance_sheet", semantics=2)
    citizen = legacy.store.query_one(
        "SELECT * FROM agents WHERE kind='citizen' AND role IS NULL ORDER BY id LIMIT 1")
    assert all(
        "reserve_ratio" in bank
        for bank in legacy.runtime.ctx.build(citizen, 1)["banks"])
    legacy.store.close()


def test_semantics_7_public_bank_view_exposes_coarse_confidence_not_reserves(tmp_path):
    world = _world(tmp_path, "bank-confidence.db", semantics=7)
    citizen = world.store.query_one(
        "SELECT * FROM agents WHERE kind='citizen' AND role IS NULL ORDER BY id LIMIT 1")
    banks = world.runtime.ctx.build(citizen, 1)["banks"]
    assert banks
    assert all(bank["confidence_signal"] in {
        "failed", "critical", "strained", "stable", "strong"
    } for bank in banks)
    assert all("reserve_ratio" not in bank for bank in banks)
    world.store.close()


def test_reserved_beliefs_are_normalized_and_provenance_is_exposed(tmp_path):
    world = _world(tmp_path, "beliefs.db")
    agent_id = int(world.store.scalar(
        "SELECT id FROM agents WHERE kind='citizen' ORDER BY id LIMIT 1"))
    memory = Memory(world.store, world.config)

    assert memory.set_belief(
        agent_id, "trust:bank:1", 1.4, 3,
        source="decision", source_llm_call_id=99) == 1.0
    assert memory.set_belief(
        agent_id, "inflation_expectation", -2.0, 3,
        source="memory", source_llm_call_id=100) == -0.05
    with pytest.raises(ValueError, match="finite"):
        memory.set_belief(agent_id, "sentiment", math.nan, 3, source="decision")

    normalized = world.store.query_one(
        "SELECT payload_json FROM events WHERE kind='belief_update_normalized' "
        "AND subject_id=? ORDER BY id LIMIT 1", (agent_id,))
    payload = json.loads(normalized["payload_json"])
    assert payload["raw_value"] == 1.4 and payload["new_value"] == 1.0
    assert payload["source_llm_call_id"] == 99

    with TestClient(create_app(world)) as client:
        detail = client.get(f"/api/agents/{agent_id}").json()
    assert detail["belief_history"]
    assert {item["kind"] for item in detail["belief_history"]} >= {
        "belief_updated", "belief_update_normalized", "belief_update_rejected"}
    world.store.close()


def test_v3_macro_metrics_separate_output_income_and_time_windows(tmp_path):
    world = _world(tmp_path, "metrics-v3.db")
    world.store.log_event(1, "goods_sale", {"total_cents": 12_300})
    world.store.log_event(1, "wage_paid", {"wage_cents": 45_600})
    snapshot = world.metrics.snapshot(1)
    assert snapshot["gdp_proxy"] == 123.0
    assert snapshot["labor_income"] == 456.0
    assert snapshot["gdp_proxy_30d"] == 123.0
    assert "inflation_30d" not in snapshot and "cpi_yoy" not in snapshot
    assert world.store.metric_at_or_before("cpi", 0, default=0.0) == pytest.approx(100.0)
    assert world.runtime.ctx.inflation_signal() == pytest.approx(0.02)

    for tick in range(2, 30):
        world.metrics.snapshot(tick)
    firm = world.store.query_one(
        "SELECT id, product_json FROM firms WHERE founded_tick=0 "
        "AND sector NOT IN ('health','insurance') ORDER BY id LIMIT 1")
    product = json.loads(firm["product_json"])
    product["unit_price_cents"] = int(product["unit_price_cents"] * 1.1)
    world.store.update("firms", int(firm["id"]), product_json=json.dumps(product))
    day_30 = world.metrics.snapshot(30)
    assert "inflation_30d" in day_30 and "cpi_yoy" not in day_30
    assert -0.5 <= world.runtime.ctx.inflation_signal() <= 0.5

    day_365 = world.metrics.snapshot(365)
    assert day_365["cpi_yoy"] == pytest.approx(day_365["cpi"] / 100.0 - 1.0)
    world.store.close()


def test_v2_gdp_and_visibility_remain_replay_compatible(tmp_path):
    world = _world(
        tmp_path, "metrics-v2.db", visibility="full_balance_sheet", semantics=2)
    world.store.log_event(1, "goods_sale", {"total_cents": 12_300})
    world.store.log_event(1, "wage_paid", {"wage_cents": 45_600})
    assert Metrics(world.economy, semantics_version=2)._gdp_proxy(1) == 579.0
    world.store.close()


def test_v3_exact_replay_includes_belief_provenance_events(tmp_path):
    config = _config(tmp_path)
    config["shocks"] = [{
        "kind": "rumor", "trigger": "shock", "trigger_params": {"tick": 1},
        "params": {"bank_id": 1, "n_agents": 6},
    }]
    runs_dir = tmp_path / "runs"
    source_store, source_world, source_id = open_run(
        config, None, None, data_dir=runs_dir)
    asyncio.run(source_world.run(max_ticks=2))
    source_belief_events = int(source_store.scalar(
        "SELECT COUNT(*) FROM events WHERE kind='belief_updated'", default=0))
    assert source_belief_events > 0

    replay_store, replay_world, _ = open_run(
        {}, None, source_id, data_dir=runs_dir)
    asyncio.run(replay_world.run(max_ticks=2))
    replay_belief_events = int(replay_store.scalar(
        "SELECT COUNT(*) FROM events WHERE kind='belief_updated'", default=0))
    proof = verify_replay(source_store.path, replay_store.path)

    assert replay_belief_events == source_belief_events
    assert proof["exact"], proof["differences"]
    source_store.close()
    replay_world.close()


def test_rumor_selector_targets_current_depositors_of_largest_bank(tmp_path):
    world = _world(tmp_path, "rumor-targeting.db")
    shock_id = world.shocks.schedule(
        "rumor", "shock", {"tick": 1}, params={
            "bank_selector": "largest_by_deposits",
            "audience": "current_depositors",
            "n_agents": 5,
        })
    world.shocks.evaluate(1)

    shock = world.store.query_one("SELECT params_json FROM shocks WHERE id=?", (shock_id,))
    # The persisted shock-firing event carries resolved parameters even though the
    # scheduled row remains the operator's original reproducible instruction.
    fired = world.store.query_one(
        "SELECT payload_json FROM events WHERE kind='shock_fired' "
        "AND json_extract(payload_json,'$.shock_id')=?", (shock_id,))
    params = json.loads(fired["payload_json"])["params"]
    bank_id = int(params["resolved_bank_id"])
    targets = params["target_agent_ids"]
    assert json.loads(shock["params_json"])["bank_selector"] == "largest_by_deposits"
    assert targets
    placeholders = ",".join("?" for _ in targets)
    rows = world.store.query(
        f"SELECT ac.bank_id FROM agents a JOIN accounts ac ON ac.id=a.checking_account_id "
        f"WHERE a.id IN ({placeholders})", targets)
    assert {int(row["bank_id"]) for row in rows} == {bank_id}
    world.store.close()


def test_acceptance_status_api_exposes_live_progress(tmp_path, monkeypatch):
    world = _world(tmp_path, "acceptance-api.db")
    config = json.loads(world.store.get_meta()["config_json"])
    config["acceptance"] = {
        "min_ticks": 30,
        "min_agents": 10,
        "max_agents": 20,
        "efficiency_target_usd": 25.0,
        "oracle_min_latency_samples": 1,
        "required_shocks": ["rumor"],
        "require_oracle_scoring": False,
        "require_experiment": False,
        "require_phenomena": False,
    }
    world.store.init_run_meta("acceptance-api", config["seed"], config)
    world.store.set_meta(status="paused", tick=3)
    world.store.commit()

    with TestClient(create_app(world)) as client:
        status = client.get("/api/acceptance/status")
        import reports.acceptance as acceptance_module
        monkeypatch.setattr(
            acceptance_module, "evaluate_acceptance",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("two-second status cache was not used")),
        )
        cached_status = client.get("/api/acceptance/status")
        receipt = status.json()
        receipt.pop("configured")
        receipt["checks"][0]["label"] = "Persisted completed receipt"
        report_dir = Path(config["report_dir"])
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "acceptance_acceptance-api.json").write_text(
            json.dumps(receipt), encoding="utf-8")
        persisted_status = client.get("/api/acceptance/status")
    assert status.status_code == 200
    assert cached_status.status_code == 200
    assert cached_status.json() == status.json()
    assert persisted_status.json()["checks"][0]["label"] == (
        "Persisted completed receipt")
    payload = status.json()
    assert payload["configured"] is True
    assert payload["progress"]["completed_ticks"] == 3
    assert payload["progress"]["required_ticks"] == 30
    assert payload["progress"]["efficiency_target_usd"] == 25.0
    checks = {check["id"]: check for check in payload["checks"]}
    assert checks["run_horizon"]["label"] == "Configured 30-tick run completed cleanly"
    assert checks["efficiency_target"]["label"] == (
        "Provider spend stayed within the $25 efficiency target")
    world.store.close()
