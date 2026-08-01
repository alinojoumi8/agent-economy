"""Focused PRD R10 coverage for governed end-of-run LLM narratives."""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from engine.store import Store, load_json
from llm.adapters import AdapterResult
from reports.generate import ReportBoundaryError, generate_report_async
from server.app import create_app
from world.loop import World
from world.replay_verify import verify_replay


def _world(tmp_path: Path, name: str = "report.db", *, cap_usd: float = 10.0) -> World:
    config = {
        "seed": 17,
        "population": {"size": 4},
        "banks": {"count": 1},
        "firms": {"count": 1, "listed": 0},
        "budget": {
            "cap_usd": cap_usd,
            "oracle_reserve_usd": 1.0,
            "report_reserve_usd": 0.25,
            "conversation_pairs": 0,
            "thresholds": [0.60, 0.80, 0.95],
        },
        "llm": {
            "provider_retries": 0,
            "default_route": {"provider": "scripted", "model": "scripted"},
            "routes": {},
        },
        "checkpoint_every": 0,
        "participant_mode": {"enabled": True},
        "reports": {"narrative_max_tokens": 600, "narrative_timeout_s": 1.0},
        "checkpoint_dir": str(tmp_path / "checkpoints"),
        "report_dir": str(tmp_path / "reports"),
        "outlets": [{"id": 1, "name": "Public Wire", "slant": "neutral"}],
    }
    store = Store(str(tmp_path / name))
    store.init_run_meta(name, int(config["seed"]), config)
    world = World(store, config)
    world.initialize()
    return world


def _install_report_route(world: World, adapter, *, model: str = "report-model") -> None:
    world.gateway.routes["reporter"] = {"provider": "report-test", "model": model}
    world.gateway.adapters["report-test"] = adapter
    world.gateway.pricing[model] = {"in": 1.0, "out": 2.0, "cache": 0.1}


def test_llm_report_narrative_is_public_bounded_metered_and_provenanced(tmp_path):
    world = _world(tmp_path)

    class NarrativeAdapter:
        calls = 0
        context = None

        async def complete(self, _model, messages, *, purpose="", context=None, **_kwargs):
            self.calls += 1
            self.context = context
            assert purpose == "report_narrative"
            assert len(messages[-1]["content"]) < 20_000
            return AdapterResult(
                text=(
                    "<think>private report scratch work</think>"
                    '{"narrative":"Demand softened while employment remained broadly stable.\\n\\n'
                    'The injected shock was followed by a measurable institutional response."}'),
                in_tokens=120,
                out_tokens=55,
                raw={"reasoning_content": "private raw reasoning", "finish_reason": "stop"},
            )

    adapter = NarrativeAdapter()
    _install_report_route(world, adapter)
    report_path = Path(asyncio.run(generate_report_async(
        world.store, world, out_dir=str(tmp_path / "out"))))

    html = report_path.read_text(encoding="utf-8")
    markdown = report_path.with_suffix(".md").read_text(encoding="utf-8")
    call = world.store.query_one(
        "SELECT * FROM llm_calls WHERE purpose='report_narrative'")
    event = world.store.query_one(
        "SELECT payload_json FROM events WHERE kind='report_generated' ORDER BY id DESC LIMIT 1")
    provenance = load_json(event["payload_json"], {})["narrative"]
    persisted_response = json.loads(call["response_json"])

    assert adapter.calls == 1
    assert set(adapter.context) == {"summary"}
    assert "Demand softened" in html and "institutional response" in markdown
    assert "private report scratch work" not in html + markdown
    assert "private report scratch work" not in json.dumps(persisted_response)
    assert "private raw reasoning" not in json.dumps(persisted_response)
    assert float(call["cost_usd"]) > 0
    assert provenance == {
        "source": "llm",
        "fallback": False,
        "model_call_id": int(call["id"]),
        "provider": "report-test",
        "model": "report-model",
        "purpose": "report_narrative",
    }
    assert f"local call #{call['id']}" in html
    world.store.close()


def test_report_narrative_uses_explicit_offline_and_replay_fallbacks(tmp_path):
    offline = _world(tmp_path, "offline.db")
    offline_path = Path(asyncio.run(generate_report_async(
        offline.store, offline, out_dir=str(tmp_path / "offline"))))
    offline_event = offline.store.query_one(
        "SELECT payload_json FROM events WHERE kind='report_generated' ORDER BY id DESC LIMIT 1")
    offline_provenance = load_json(offline_event["payload_json"], {})["narrative"]

    assert "The run covered" in offline_path.read_text(encoding="utf-8")
    assert offline_provenance == {
        "source": "engine", "fallback": True, "reason": "offline_scripted"}
    assert offline.store.scalar("SELECT COUNT(*) FROM llm_calls") == 0
    offline.store.close()

    replay = _world(tmp_path, "replay.db")

    class ForbiddenAdapter:
        calls = 0

        async def complete(self, *_args, **_kwargs):
            self.calls += 1
            raise AssertionError("replay dispatched a provider")

    forbidden = ForbiddenAdapter()
    _install_report_route(replay, forbidden)
    replay.gateway.replay = True
    replay_path = Path(asyncio.run(generate_report_async(
        replay.store, replay, out_dir=str(tmp_path / "replay"))))
    replay_event = replay.store.query_one(
        "SELECT payload_json FROM events WHERE kind='report_generated' ORDER BY id DESC LIMIT 1")
    replay_provenance = load_json(replay_event["payload_json"], {})["narrative"]

    assert forbidden.calls == 0
    assert "The run covered" in replay_path.read_text(encoding="utf-8")
    assert replay_provenance == {
        "source": "engine", "fallback": True, "reason": "replay"}
    assert replay.store.scalar("SELECT COUNT(*) FROM llm_calls") == 0
    replay.store.close()


def test_report_narrative_falls_back_on_provider_or_budget_failure(tmp_path):
    failed = _world(tmp_path, "failed.db")

    class FailedAdapter:
        calls = 0

        async def complete(self, *_args, **_kwargs):
            self.calls += 1
            raise RuntimeError("provider unavailable")

    failing = FailedAdapter()
    _install_report_route(failed, failing)
    failed_path = Path(asyncio.run(generate_report_async(
        failed.store, failed, out_dir=str(tmp_path / "failed"))))
    failed_event = failed.store.query_one(
        "SELECT payload_json FROM events WHERE kind='report_generated' ORDER BY id DESC LIMIT 1")
    failed_provenance = load_json(failed_event["payload_json"], {})["narrative"]

    assert failing.calls == 1
    assert "The run covered" in failed_path.read_text(encoding="utf-8")
    assert failed_provenance["source"] == "engine"
    assert failed_provenance["reason"] == "provider_failure:ProviderUnavailable"
    assert failed.store.scalar(
        "SELECT COUNT(*) FROM events WHERE kind='provider_failure'", default=0) == 0
    failed.store.close()

    budgeted = _world(tmp_path, "budgeted.db", cap_usd=0.000001)

    class BudgetGuardAdapter:
        calls = 0

        async def complete(self, *_args, **_kwargs):
            self.calls += 1
            raise AssertionError("budget rejection must happen before dispatch")

    guarded = BudgetGuardAdapter()
    _install_report_route(budgeted, guarded)
    budgeted_path = Path(asyncio.run(generate_report_async(
        budgeted.store, budgeted, out_dir=str(tmp_path / "budgeted"))))
    budgeted_event = budgeted.store.query_one(
        "SELECT payload_json FROM events WHERE kind='report_generated' ORDER BY id DESC LIMIT 1")
    budgeted_provenance = load_json(budgeted_event["payload_json"], {})["narrative"]

    assert guarded.calls == 0
    assert "The run covered" in budgeted_path.read_text(encoding="utf-8")
    assert budgeted_provenance["reason"] == "provider_failure:BudgetExceeded"
    assert budgeted.store.scalar("SELECT COUNT(*) FROM llm_calls") == 0
    budgeted.store.close()


def test_report_narrative_calls_are_operational_for_exact_replay(tmp_path):
    source = Store(str(tmp_path / "source.db"))
    replay = Store(str(tmp_path / "replayed.db"))
    source.init_run_meta("source", 1, {})
    replay.init_run_meta("replayed", 1, {})
    source.insert(
        "llm_calls", tick=0, role="reporter", provider="report-test",
        model="report-model", purpose="report_narrative", cache_key="report",
        request_json="{}", response_json='{"text":"{\\"narrative\\":\\"public\\"}"}',
        in_tokens=10, out_tokens=5, cached=0, cost_usd=0.001, latency_ms=10)
    source.log_event(0, "report_generated", {
        "path": "source.html",
        "narrative": {"source": "llm", "model_call_id": 1},
    })
    source.commit()
    replay.commit()

    proof = verify_replay(source.path, replay.path)

    assert proof["exact"], proof["differences"]
    source.close()
    replay.close()


def test_report_api_awaits_the_governed_llm_narrative(tmp_path):
    world = _world(tmp_path, "api-report.db")

    class ApiNarrativeAdapter:
        calls = 0

        async def complete(self, _model, _messages, **_kwargs):
            self.calls += 1
            return AdapterResult(
                text='{"narrative":"The API used its governed report writer."}',
                in_tokens=20, out_tokens=10)

    adapter = ApiNarrativeAdapter()
    _install_report_route(world, adapter)
    # A completed Pause leaves the shared gateway interrupt set.  The
    # controller must serialize and clear it before starting the report call.
    world.request_pause()
    with TestClient(create_app(world)) as client:
        response = client.post("/api/report")
        repeated = client.post("/api/report")
        served = client.get(response.json()["url"])

    assert response.status_code == 200
    assert repeated.status_code == 200
    assert served.status_code == 200
    assert served.headers["content-type"].startswith("text/html")
    assert response.json()["url"] == repeated.json()["url"]
    assert adapter.calls == 1
    report_path = Path(response.json()["path"])
    assert "governed report writer" in report_path.read_text(encoding="utf-8")
    assert "governed report writer" in served.text
    assert world.last_report_path == repeated.json()["path"]
    assert world.store.scalar(
        "SELECT COUNT(*) FROM llm_calls WHERE purpose='report_narrative'", default=0) == 1
    world.store.close()


def test_report_narrative_timeout_is_bounded_and_operational(tmp_path):
    world = _world(tmp_path, "timeout.db")
    config = load_json(world.store.get_meta()["config_json"], {})
    config["reports"]["narrative_timeout_s"] = 0.02
    world.store.execute(
        "UPDATE run_meta SET config_json=?", (json.dumps(config),))
    world.store.commit()

    class HangingAdapter:
        calls = 0

        async def complete(self, *_args, **_kwargs):
            self.calls += 1
            await asyncio.Event().wait()

    adapter = HangingAdapter()
    _install_report_route(world, adapter)
    started = time.perf_counter()
    path = Path(asyncio.run(generate_report_async(
        world.store, world, out_dir=str(tmp_path / "timeout-out"))))
    elapsed = time.perf_counter() - started
    event = world.store.query_one(
        "SELECT payload_json FROM events WHERE kind='report_generated' ORDER BY id DESC LIMIT 1")
    provenance = load_json(event["payload_json"], {})["narrative"]

    assert elapsed < 0.5
    assert adapter.calls == 1
    assert provenance == {
        "source": "engine", "fallback": True, "reason": "provider_timeout"}
    assert "The run covered" in path.read_text(encoding="utf-8")
    assert world.store.scalar(
        "SELECT COUNT(*) FROM events WHERE kind='provider_failure'", default=0) == 0
    world.store.close()


def test_failed_report_repair_persists_and_meters_the_initial_completion(tmp_path):
    world = _world(tmp_path, "repair-failure.db")

    class MalformedThenFailAdapter:
        calls = 0

        async def complete(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return AdapterResult(
                    text="malformed but billable", in_tokens=31, out_tokens=7,
                    raw={"finish_reason": "stop"})
            raise RuntimeError("repair provider unavailable")

    adapter = MalformedThenFailAdapter()
    _install_report_route(world, adapter)
    asyncio.run(generate_report_async(
        world.store, world, out_dir=str(tmp_path / "repair-failure")))
    call = world.store.query_one(
        "SELECT * FROM llm_calls WHERE purpose='report_narrative'")

    assert adapter.calls == 2
    assert call is not None
    assert int(call["in_tokens"]) == 31 and int(call["out_tokens"]) == 7
    assert float(call["cost_usd"]) > 0
    persisted = json.loads(call["response_json"])
    assert "malformed but billable" not in call["response_json"]
    assert persisted["text"] == (
        '{"actions":[{"type":"do_nothing"}],'
        '"reasoning":"unparseable output; no-op"}')

    # The invalid durable completion makes a retry deterministic and free.
    asyncio.run(generate_report_async(
        world.store, world, out_dir=str(tmp_path / "repair-failure-repeat")))
    assert adapter.calls == 2
    assert world.store.scalar(
        "SELECT COUNT(*) FROM llm_calls WHERE purpose='report_narrative'", default=0) == 1
    world.store.close()


def test_report_reserve_does_not_change_behavioral_governor_state(tmp_path):
    world = _world(tmp_path, "report-reserve.db")
    world.store.insert(
        "llm_calls", tick=0, role="citizen", provider="test", model="test",
        purpose="decision", cache_key="world-spend", request_json="{}",
        response_json="{}", in_tokens=1, out_tokens=1, cached=0,
        cost_usd=5.3, latency_ms=1)
    world.store.commit()
    before_level = world.gateway.governor.level()
    before_world_spend = world.gateway.governor.world_spend()

    class ReserveAdapter:
        async def complete(self, *_args, **_kwargs):
            return AdapterResult(
                text='{"narrative":"A bounded operational report."}',
                in_tokens=20, out_tokens=10)

    _install_report_route(world, ReserveAdapter())
    asyncio.run(generate_report_async(
        world.store, world, out_dir=str(tmp_path / "reserve-out")))

    assert before_level == 1
    assert world.gateway.governor.level() == before_level
    assert world.gateway.governor.world_spend() == before_world_spend
    assert world.gateway.governor.report_spend() > 0
    world.store.close()


def test_advancing_after_a_manual_report_invalidates_the_old_artifact(tmp_path):
    world = _world(tmp_path, "report-advance.db")

    class TickNarrativeAdapter:
        calls = 0
        report_calls = 0

        async def complete(self, _model, _messages, *, purpose="", **_kwargs):
            self.calls += 1
            if purpose != "report_narrative":
                return AdapterResult(
                    text='{"stories":[]}', in_tokens=5, out_tokens=2)
            self.report_calls += 1
            return AdapterResult(
                text=json.dumps({"narrative": f"Narrative call {self.report_calls}."}),
                in_tokens=20, out_tokens=10)

    adapter = TickNarrativeAdapter()
    _install_report_route(world, adapter)
    with TestClient(create_app(world)) as client:
        first = client.post("/api/report")
        assert first.status_code == 200
        first_path = first.json()["path"]

        citizen_id = int(world.store.scalar(
            "SELECT id FROM agents WHERE kind='citizen' AND alive=1 ORDER BY id LIMIT 1"))
        acquired = client.post("/api/participant/control", json={
            "agent_id": citizen_id, "expected_tick": 0,
        })
        assert acquired.status_code == 200
        rejected_step = client.post("/api/run/step")
        assert rejected_step.status_code == 409
        assert world.last_report_path == first_path
        released = client.post(
            "/api/participant/release", json={"expected_tick": 0})
        assert released.status_code == 200

        world.last_pause_reason = {"reason": "provider", "detail": "recovered"}
        stepped = client.post("/api/run/step")
        assert stepped.status_code == 200
        assert world.store.tick == 1
        assert world.last_report_path is None
        assert world.last_pause_reason is None

        stopped = client.post("/api/run/stop")
        assert stopped.status_code == 200
        assert stopped.json()["report_path"] != first_path

    assert adapter.report_calls == 2
    assert world.store.scalar(
        "SELECT COUNT(*) FROM llm_calls WHERE purpose='report_narrative'", default=0) == 2
    world.store.close()


def test_stop_defers_reporting_when_a_tick_is_only_partially_committed(tmp_path):
    world = _world(tmp_path, "partial-stop.db")
    world.store.set_meta(
        tick=0, active_tick=1, next_phase="MORNING", phase="MORNING",
        status="paused")
    world.store.log_event(
        1, "firm_scandal", {"firm_id": 1, "summary": "PARTIAL_ONLY"},
        phase="NIGHT_CLOSE", importance=3.0)
    world.store.commit()
    world.status = "paused"

    with TestClient(create_app(world)) as client:
        stopped = client.post("/api/run/stop")

    assert stopped.status_code == 200
    payload = stopped.json()
    assert payload["status"] == "finished"
    assert payload["report_path"] is None
    assert payload["report_deferred"] == {
        "reason": "report_deferred_partial_tick",
        "active_tick": 1,
        "phase": "MORNING",
        "detail": "finish the partial tick before generating an end-of-run report",
    }
    assert world.store.active_tick == 1
    assert world.store.scalar(
        "SELECT COUNT(*) FROM events WHERE kind='report_generated'", default=0) == 0
    with pytest.raises(ReportBoundaryError, match="tick 1 is partial"):
        asyncio.run(generate_report_async(
            world.store, world, out_dir=str(tmp_path / "must-not-exist")))
    assert not (tmp_path / "must-not-exist").exists()
    world.store.close()
