import asyncio
import json
import math
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agents.memory import Memory
from engine.store import Store
from run import open_run
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
    replay_store.close()


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
