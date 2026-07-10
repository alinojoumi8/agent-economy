"""Executable acceptance evidence for the remaining PRD-v1 completion gates."""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agents.memory import Memory
from engine.ledger import ReconciliationError
from engine.store import Store, load_json
from llm.adapters import AdapterResult
from llm.gateway import Gateway, LLMRequest
from llm.readiness import validate_llm_config
from run import load_config, open_run
from server.app import create_app
from world.loop import World
from world.replay_verify import verify_replay


def _config(tmp_path: Path, **over) -> dict:
    cfg = {
        "seed": 42,
        "population": {"size": 10},
        "banks": {"count": 2},
        "firms": {"count": 3, "listed": 1},
        "behavior": {"act_every": 1, "run_threshold": 0.35},
        "budget": {"cap_usd": 200.0, "oracle_reserve_usd": 10.0,
                   "conversation_pairs": 0, "thresholds": [0.60, 0.80, 0.95]},
        "llm": {"provider_retries": 0,
                "default_route": {"provider": "scripted", "model": "scripted"},
                "routes": {}},
        "checkpoint_every": 0,
        "checkpoint_dir": str(tmp_path / "checkpoints"),
        "report_dir": str(tmp_path / "reports"),
        "outlets": [{"id": 1, "name": "A", "slant": "pro-market-sensational"},
                    {"id": 2, "name": "B", "slant": "cautious-pro-labor"}],
    }
    cfg.update(over)
    return cfg


def _world(tmp_path: Path, name: str = "acceptance.db", **over) -> World:
    cfg = _config(tmp_path, **over)
    store = Store(str(tmp_path / name))
    store.init_run_meta(name, int(cfg["seed"]), cfg)
    world = World(store, cfg)
    world.initialize()
    return world


def test_exact_replay_rebuilds_fresh_database_and_proves_every_table(tmp_path):
    cfg = _config(tmp_path)
    source_store, source_world, source_id = open_run(
        cfg, None, None, data_dir=tmp_path)
    asyncio.run(source_world.run(max_ticks=4))

    replay_store, replay_world, replay_id = open_run(
        {}, None, source_id, data_dir=tmp_path)
    assert replay_id != source_id
    assert replay_store.tick == 0
    assert replay_world.gateway.replay
    asyncio.run(replay_world.run(max_ticks=4))

    proof = verify_replay(source_store.path, replay_store.path)
    assert proof["exact"], proof["differences"]
    assert proof["source_tick"] == proof["replay_tick"] == 4
    assert proof["source_hash"] == proof["replay_hash"]
    assert {table["table"] for table in proof["tables"]} >= {
        "accounts", "agents", "events", "ledger_entries", "llm_calls", "metrics"}

    replay_store.execute("UPDATE accounts SET balance_cents=balance_cents+1 WHERE id=1")
    replay_store.commit()
    changed = verify_replay(source_store.path, replay_store.path)
    assert not changed["exact"]
    assert "accounts" in changed["differences"]


def test_resume_restores_persisted_run_status(tmp_path):
    cfg = _config(tmp_path)
    store, world, run_id = open_run(cfg, None, None, data_dir=tmp_path)
    world.status = "finished"
    store.set_meta(status="finished")
    store.commit()
    store.close()

    resumed_store, resumed_world, resumed_id = open_run(
        cfg, run_id, None, data_dir=tmp_path)
    try:
        assert resumed_id == run_id
        assert resumed_world.status == "finished"
        assert resumed_store.get_meta()["status"] == "finished"
    finally:
        resumed_store.close()


def test_replay_missing_response_pauses_without_calling_a_provider(tmp_path):
    cfg = _config(tmp_path)
    source_store, source_world, source_id = open_run(
        cfg, None, None, data_dir=tmp_path)
    asyncio.run(source_world.run(max_ticks=1))
    source_store.execute("DELETE FROM llm_calls WHERE id=(SELECT MIN(id) FROM llm_calls)")
    source_store.commit()

    replay_store, replay_world, _ = open_run({}, None, source_id, data_dir=tmp_path)

    class MustNotRun:
        async def complete(self, *args, **kwargs):
            raise AssertionError("replay attempted a live provider call")

    replay_world.gateway.adapters["scripted"] = MustNotRun()
    result = asyncio.run(replay_world.step())
    assert result["paused"] == "provider"
    assert replay_store.scalar(
        "SELECT COUNT(*) FROM events WHERE kind='provider_pause'") == 1


def test_production_config_pins_minimax_m3_and_kimi_k26_platform():
    cfg = load_config("runs/production.yaml")
    assert cfg["population"]["size"] == 87
    assert cfg["banks"]["count"] == 2
    assert cfg["llm"]["default_route"] == {
        "provider": "minimax", "model": "MiniMax-M3"}
    assert cfg["llm"]["concurrency"] == 3
    assert cfg["llm"]["providers"]["minimax"]["timeout_s"] == 180
    assert cfg["llm"]["providers"]["minimax"]["request_defaults"] == {
        "reasoning_split": True, "max_completion_tokens": 4096}
    assert cfg["llm"]["routes"]["oracle"] == {
        "provider": "kimi", "model": "kimi-k2.6"}
    kimi = cfg["llm"]["providers"]["kimi"]
    assert kimi["base_url"] == "https://api.moonshot.ai/v1"
    assert kimi["api_key_env"] == "KIMI_API_KEY"
    assert kimi["timeout_s"] == 180
    assert kimi["max_tokens_field"] == "max_tokens"
    assert kimi["request_defaults"] == {
        "thinking": {"type": "enabled"}, "temperature": 1.0,
        "max_tokens": 4096}

    missing = validate_llm_config(cfg, environ={}, raise_on_error=False)
    assert not missing["ready"]
    assert any("MINIMAX_API_KEY" in error for error in missing["errors"])
    assert any("KIMI_API_KEY" in error for error in missing["errors"])

    ready = validate_llm_config(
        cfg, environ={"MINIMAX_API_KEY": "sk-cp-present",
                      "KIMI_API_KEY": "sk-platform-present"},
        raise_on_error=False)
    assert ready["ready"] and ready["mode"] == "network"
    assert {p["name"] for p in ready["providers"]} == {"minimax", "kimi"}
    assert all("api_key" not in p for p in ready["providers"])

    wrong_service = load_config("runs/production.yaml")
    wrong_service["llm"]["providers"]["kimi"]["base_url"] = \
        "https://api.kimi.com/coding/v1"
    mismatch = validate_llm_config(
        wrong_service,
        environ={"MINIMAX_API_KEY": "sk-cp-present",
                 "KIMI_API_KEY": "sk-platform-present"},
        raise_on_error=False)
    assert not mismatch["ready"]
    assert any("Kimi Code endpoint" in error or "routes kimi-k2.6" in error
               for error in mismatch["errors"])

    code_key_on_platform = validate_llm_config(
        cfg, environ={"MINIMAX_API_KEY": "sk-cp-present",
                      "KIMI_API_KEY": "sk-kimi-membership"},
        raise_on_error=False)
    assert not code_key_on_platform["ready"]
    assert any("Kimi Code key" in error for error in code_key_on_platform["errors"])

    wrong_minimax_service = load_config("runs/production.yaml")
    wrong_minimax_service["llm"]["providers"]["minimax"]["base_url"] = \
        "https://api.minimaxi.com/v1"
    minimax_mismatch = validate_llm_config(
        wrong_minimax_service,
        environ={"MINIMAX_API_KEY": "sk-cp-present",
                 "KIMI_API_KEY": "sk-platform-present"},
        raise_on_error=False)
    assert not minimax_mismatch["ready"]
    assert any("MiniMax Token Plan key" in error
               for error in minimax_mismatch["errors"])


def test_kimi_code_compatibility_profile_uses_only_membership_aliases():
    cfg = load_config("runs/production-kimi-code.yaml")
    assert cfg["population"]["size"] == 87
    assert cfg["llm"]["providers"]["kimi"]["base_url"] == \
        "https://api.kimi.com/coding/v1"
    assert cfg["llm"]["providers"]["kimi"]["api_key_env"] == \
        "KIMI_API_KEY"
    assert cfg["llm"]["routes"]["oracle"] == {
        "provider": "kimi", "model": "kimi-for-coding"}
    ready = validate_llm_config(
        cfg, environ={"MINIMAX_API_KEY": "sk-cp-present",
                      "KIMI_API_KEY": "sk-kimi-membership"},
        raise_on_error=False)
    assert ready["ready"]


def test_gateway_retries_once_and_bills_provider_reported_cache_tokens(tmp_path):
    cfg = _config(tmp_path)
    cfg["llm"] = {
        "provider_retries": 1,
        "default_route": {"provider": "mock", "model": "metered-test"},
        "routes": {},
        "pricing": {"metered-test": {"in": 1.0, "out": 2.0, "cache": 0.1}},
    }
    store = Store(str(tmp_path / "cache.db"))
    store.init_run_meta("cache", 42, cfg)
    gateway = Gateway(store, cfg)

    class FailOnce:
        def __init__(self):
            self.calls = 0

        async def complete(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("temporary provider outage")
            return AdapterResult(
                text='{"reasoning":"ok","actions":[{"type":"do_nothing"}]}',
                in_tokens=100, out_tokens=10, cached_in_tokens=80,
                raw={"usage": "provider-reported"})

        async def healthcheck(self, model):
            return {"ok": True, "model": model, "live": True}

    adapter = FailOnce()
    gateway.adapters["mock"] = adapter
    response = asyncio.run(gateway.complete(
        LLMRequest(role="citizen", purpose="decision", system="stable", user="dynamic")))

    assert adapter.calls == 2
    assert response.cached
    assert response.cost_usd == pytest.approx(0.000048)
    row = store.query_one("SELECT * FROM llm_calls ORDER BY id DESC LIMIT 1")
    assert row["cached"] == 1
    assert load_json(row["response_json"], {})["cached_in_tokens"] == 80


def test_provider_failure_pauses_on_a_reconciled_checkpoint(tmp_path):
    world = _world(tmp_path, "provider.db")

    class AlwaysFail:
        async def complete(self, *args, **kwargs):
            raise RuntimeError("synthetic outage")

        async def healthcheck(self, model):
            return {"ok": False, "model": model, "live": True}

    world.gateway.adapters["scripted"] = AlwaysFail()
    summary = asyncio.run(world.step())

    assert summary["paused"] == "provider"
    assert summary["phase"] == "MORNING"
    assert world.status == "paused" and world.store.tick == 1
    assert world.store.get_meta()["status"] == "paused"
    assert world.store.scalar("SELECT COUNT(*) FROM events WHERE kind='provider_failure'") > 0
    assert world.store.scalar("SELECT COUNT(*) FROM events WHERE kind='provider_pause'") == 1
    checkpoint = world.store.query_one("SELECT path FROM checkpoints ORDER BY id DESC LIMIT 1")
    assert checkpoint and Path(checkpoint["path"]).exists()
    ok, diag = world.economy.ledger.reconcile()
    assert ok, diag


def test_active_reconciliation_failure_halts_and_checkpoints(tmp_path):
    world = _world(tmp_path, "halt.db")
    account = world.store.query_one("SELECT id FROM accounts ORDER BY id LIMIT 1")
    world.store.execute(
        "UPDATE accounts SET balance_cents=balance_cents+1 WHERE id=?", (int(account["id"]),))

    with pytest.raises(ReconciliationError):
        asyncio.run(world.step())

    assert world.status == "halted"
    assert world.store.get_meta()["status"] == "halted"
    assert world.store.scalar(
        "SELECT COUNT(*) FROM events WHERE kind='reconciliation_failure'") == 1
    assert list(tmp_path.glob("halt.halt_t1.json"))
    assert world.store.scalar("SELECT COUNT(*) FROM checkpoints WHERE tick=1") == 1


def test_interactive_stop_generates_complete_standalone_report(tmp_path):
    world = _world(tmp_path, "report.db")
    app = create_app(world)
    with TestClient(app) as client:
        speed = client.post("/api/run/speed", json={"delay_s": 1.0})
        assert speed.status_code == 200
        assert speed.json()["delay_s"] == 1.0
        assert client.get("/api/run/status").json()["speed_delay_s"] == 1.0
        response = client.post("/api/run/stop")
        assert response.status_code == 200
        first_body = response.json()
        finished_tick = world.store.tick
        assert client.post("/api/run/step").status_code == 200
        assert world.store.tick == finished_tick + 1
        assert world.status == "paused"
        assert world.last_report_path is None
        assert client.post("/api/shocks", json={
            "kind": "oil", "trigger_type": "shock", "params": {"multiplier": 2.0},
        }).status_code == 200
        response = client.post("/api/run/stop")
        assert response.status_code == 200
        body = response.json()

    assert body["status"] == "finished"
    assert first_body["report_path"] != body["report_path"]
    html_path = Path(body["report_path"])
    md_path = html_path.with_suffix(".md")
    assert html_path.exists() and md_path.exists()
    html = html_path.read_text(encoding="utf-8")
    for section in ("Narrative", "Timeline of key events", "Metrics", "Oracle scorecard",
                    "Cost summary", "Reproduction"):
        assert section in html
    assert world.store.scalar("SELECT COUNT(*) FROM events WHERE kind='report_generated'") == 2


def test_running_world_stop_finishes_with_report(tmp_path):
    world = _world(tmp_path, "running-stop.db", speed_delay_s=0.01)

    async def stop_after_first_tick():
        task = asyncio.create_task(world.run())
        while world.store.tick < 1:
            await asyncio.sleep(0.002)
        world.request_stop()
        await task

    asyncio.run(stop_after_first_tick())
    assert world.status == "finished"
    assert world.last_report_path and Path(world.last_report_path).exists()
    assert world.store.get_meta()["status"] == "finished"
    assert world.store.scalar("SELECT COUNT(*) FROM events WHERE kind='report_generated'") == 1


def test_weekly_memory_is_synthesized_before_daily_sources_are_demoted(tmp_path):
    store = Store(str(tmp_path / "memory.db"))
    store.init_run_meta("memory", 42, {})
    memory = Memory(store)
    for tick in range(1, 8):
        memory.write_summary(1, tick, f"day {tick}", importance=float(tick))
    memory.weekly_rollup(1, 7, "week one synthesis", importance=8.0)

    weekly = store.query_one(
        "SELECT * FROM memories WHERE agent_id=1 AND kind='weekly_summary'")
    assert weekly["text"] == "week one synthesis" and weekly["demoted"] == 0
    assert store.scalar(
        "SELECT COUNT(*) FROM memories WHERE agent_id=1 AND kind='summary' AND demoted=1") == 7


def test_two_year_lifecycle_run_settles_death_and_integrates_arrival(tmp_path):
    world = _world(
        tmp_path, "two-years.db",
        population={"size": 4},
        behavior={"act_every": 1000, "run_threshold": 0.35},
        lifecycle={"critical_death_per_tick": 1.0,
                   "critical_recovery_per_tick": 0.0,
                   "housing_cost_cents": 75_000,
                   "population_mode": "stable"},
        outlets=[{"id": 1, "name": "A", "slant": "neutral"}],
    )
    doomed = world.store.query_one(
        "SELECT id FROM agents WHERE kind='citizen' AND alive=1 ORDER BY id LIMIT 1")
    world.store.update("agents", int(doomed["id"]), health="critical")
    world.economy.lifecycle.schedule_arrival(0, 1)
    firm_id = int(world.store.scalar(
        "SELECT id FROM firms WHERE status<>'bankrupt' ORDER BY id LIMIT 1"))
    for idx in range(12):
        world.economy.labor.post_job(0, firm_id, f"arrival opening {idx}", 120_000 + idx)
    world.store.commit()

    async def run_two_years():
        for _ in range(730):
            result = await world.step()
            assert not result.get("paused"), result

    asyncio.run(run_two_years())

    assert world.store.scalar("SELECT COUNT(*) FROM events WHERE kind='death'") >= 1
    arrival = world.store.query_one(
        "SELECT subject_id AS agent_id, tick FROM events WHERE kind='arrival' ORDER BY id LIMIT 1")
    assert arrival is not None
    arrival_id, arrival_tick = int(arrival["agent_id"]), int(arrival["tick"])
    housing = world.store.query_one(
        "SELECT tick, payload_json FROM events WHERE kind='housing_cost' AND subject_id=?",
        (arrival_id,))
    assert housing and int(housing["tick"]) - arrival_tick <= 10
    application = world.store.query_one(
        "SELECT tick FROM applications WHERE agent_id=? ORDER BY id LIMIT 1", (arrival_id,))
    assert application and int(application["tick"]) - arrival_tick <= 10
    ok, diag = world.economy.ledger.reconcile()
    assert ok, diag


def test_websocket_payload_is_emitted_within_two_seconds(tmp_path):
    world = _world(tmp_path, "ws.db")
    app = create_app(world)
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            initial = ws.receive_json()
            assert initial["tick"] == 0
            response = client.post("/api/run/step")
            assert response.status_code == 200
            assert client.get("/api/run/status").json()["status"] == "paused"
            payload = ws.receive_json()
            assert payload["tick"] == 1
            assert int(time.time() * 1000) - payload["emitted_at_ms"] < 2_000


def test_react_dashboard_bundle_is_local_and_current():
    package = json.loads(Path("dashboard/package.json").read_text(encoding="utf-8"))
    assert {"react", "react-dom", "recharts"} <= package["dependencies"].keys()
    assert {"vite", "tailwindcss", "@tailwindcss/vite"} <= package["devDependencies"].keys()

    html = Path("server/static/index.html").read_text(encoding="utf-8")
    assert 'id="root"' in html
    assert 'src="/static/assets/' in html
    assert 'href="/static/assets/' in html
    assert "https://" not in html and "http://" not in html
    for relative in set(part.split('"')[0] for part in html.split("/static/")[1:]):
        assert (Path("server/static") / relative).is_file(), relative


def test_each_required_shock_has_a_logged_downstream_effect(tmp_path):
    async def fire(kind: str, params: dict, name: str) -> World:
        world = _world(tmp_path, name)
        world.shocks.schedule(kind, "shock", {"tick": 1}, params=params,
                              duration_ticks=3 if kind == "slant" else 0)
        await world.step()
        assert world.store.scalar(
            "SELECT COUNT(*) FROM events WHERE kind='shock_fired'") == 1
        return world

    policy = asyncio.run(fire("policy_rate", {"rate_bps": 875}, "policy.db"))
    assert policy.economy.policy_rate_bps() == 875

    oil = asyncio.run(fire("oil", {"multiplier": 1.8}, "oil.db"))
    assert oil.economy.firms.commodity_index() == pytest.approx(1.8)

    rumor = asyncio.run(fire("rumor", {"bank_id": 1, "n_agents": 6}, "rumor-shock.db"))
    rumor_event = rumor.store.query_one(
        "SELECT payload_json FROM events WHERE kind='rumor' ORDER BY id DESC LIMIT 1")
    targets = load_json(rumor_event["payload_json"], {})["target_agent_ids"]
    assert len(targets) == 6
    assert rumor.store.scalar(
        "SELECT COUNT(*) FROM memories WHERE tick=1 AND importance>=4") >= 6

    slant = asyncio.run(fire(
        "slant", {"outlet_id": 1, "directive": "Frame as alarming"}, "slant.db"))
    slanted = slant.store.query_one(
        "SELECT slant_tags FROM news_articles WHERE outlet_id=1 ORDER BY id DESC LIMIT 1")
    assert slanted and "directed" in load_json(slanted["slant_tags"], [])

    scandal = asyncio.run(fire(
        "scandal", {"firm_id": 1, "description": "Accounting investigation"}, "scandal.db"))
    assert scandal.store.scalar("SELECT COUNT(*) FROM news_articles WHERE tick=1") > 0


def test_company_lifecycle_runs_lawyer_to_revenue_to_bankruptcy(tmp_path):
    world = _world(tmp_path, "company.db")
    executor = world.runtime.executor
    citizens = world.store.query(
        "SELECT id FROM agents WHERE kind='citizen' AND alive=1 ORDER BY id LIMIT 4")
    founder, lawyer, worker, buyer = (int(row["id"]) for row in citizens)
    world.store.update("agents", lawyer, occupation="lawyer")

    founded = executor.execute_action(1, founder, {
        "type": "found_company", "lawyer_agent_id": lawyer,
        "name": "Acceptance Works", "sector": "manufacturing",
        "opening_capital": 100_000,
        "product": {"product": "widgets", "unit_price_cents": 2_000,
                    "base_input_cost_cents": 500, "output_per_worker": 5},
    })
    assert founded["ok"]
    firm_id = int(founded["firm_id"])

    applied = executor.execute_action(2, founder, {
        "type": "apply_loan", "bank_id": 1, "amount": 300_000,
        "purpose": "working capital", "as_firm": True, "firm_id": firm_id,
    })
    assert applied["ok"]
    officer = int(world.store.scalar(
        "SELECT id FROM agents WHERE role='credit_officer' ORDER BY id LIMIT 1"))
    approved = executor.execute_action(3, officer, {
        "type": "approve_loan", "application_id": applied["application_id"],
        "rate_bps": 900, "term_ticks": 360,
    })
    assert approved["ok"]

    posted = executor.execute_action(4, founder, {
        "type": "post_job", "firm_id": firm_id, "title": "widget maker",
        "wage": 90_000,
    })
    assert posted["ok"]
    job_id = int(posted["job_id"])
    application = executor.execute_action(
        5, worker, {"type": "apply_job", "job_id": job_id})
    assert application["ok"]
    hired = executor.execute_action(
        6, founder, {"type": "hire", "application_id": application["application_id"]})
    assert hired["ok"]

    world.economy.firms.produce(7)
    sale = executor.execute_action(
        8, buyer, {"type": "buy_goods", "firm_id": firm_id, "qty": 2})
    assert sale["ok"] and sale["total_cents"] > 0
    assert world.store.scalar(
        "SELECT COUNT(*) FROM events WHERE kind='goods_sale'", default=0) >= 1

    world.economy.firms.bankrupt_firm(9, firm_id, reason="acceptance lifecycle")
    firm = world.store.query_one("SELECT status FROM firms WHERE id=?", (firm_id,))
    assert firm["status"] == "bankrupt"
    assert world.store.scalar(
        "SELECT COUNT(*) FROM employments WHERE firm_id=? AND status='active'",
        (firm_id,), default=0) == 0
    for kind in ("company_founded", "loan_application", "loan_originated", "hired",
                 "goods_sale", "bankruptcy"):
        assert world.store.scalar(
            "SELECT COUNT(*) FROM events WHERE kind=?", (kind,), default=0) >= 1, kind
    ok, diag = world.economy.ledger.reconcile()
    assert ok, diag
