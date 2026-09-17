"""Server-core and world-loop regressions from the 2026-09 review."""
from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import time

import pytest
from pydantic import ValidationError

from observability import scrub_error_text, scrub_paths
from reports.acceptance import configured_llm_routes, uses_paid_providers
from server.app import SpeedBody, _hosted_safe_document
from server.controller import WebSocketHub
from server.loop_watchdog import LoopWatchdog
from server.replay import ReplayReader
from server.static_export import export_static_replay
from tests.test_external_agent_gateway import _world as _external_world
from world.event_visibility import PUBLIC_REPORTABLE_EVENT_KINDS
from world.shocks import Shocks


@pytest.mark.parametrize("delay", [float("inf"), float("nan"), 5000, -1])
def test_speed_body_rejects_unbounded_or_non_finite_delays(delay):
    with pytest.raises(ValidationError):
        SpeedBody(delay_s=delay)


def test_speed_body_accepts_bounded_delays():
    assert SpeedBody(delay_s=2.5).delay_s == 2.5


def test_hosted_safe_document_strips_database_keys_and_path_values():
    document = {
        "run": {"run_id": "abc", "database": "C:\\runs\\abc.db", "seed": 7},
        "report_dir": "reports/out",
        "artifacts": [{"json": "/var/lib/agent-economy/runs/abc/acceptance.json"}],
        "link": "/api/v2/map",
        "detail": {"nested_path": "x", "ok": True},
    }
    safe = _hosted_safe_document(document)
    assert "database" not in safe["run"] and safe["run"]["seed"] == 7
    assert "report_dir" not in safe
    assert safe["artifacts"] == [{"json": "[redacted-path]"}]
    assert safe["link"] == "/api/v2/map"
    assert safe["detail"] == {"ok": True}


def test_scrub_error_text_hides_filesystem_paths_but_keeps_urls():
    error = OSError(
        28, "No space left on device",
        "C:\\Users\\someone\\data\\checkpoints\\run_t12.db")
    scrubbed = scrub_error_text(error)
    assert "run_t12.db" in scrubbed
    assert "Users" not in scrubbed and "checkpoints" not in scrubbed
    assert scrub_paths("open '/var/lib/agent-economy/runs/x.db' failed") == (
        "open '<path>/x.db' failed")
    assert scrub_paths("POST https://api.example.com/v1/chat failed") == (
        "POST https://api.example.com/v1/chat failed")


def test_paid_provider_gate_sees_every_route_group():
    scripted = {"llm": {"default_route": {"provider": "scripted", "model": "scripted"}}}
    assert not uses_paid_providers(scripted)
    cohorts = {"llm": {
        "default_route": {"provider": "scripted", "model": "scripted"},
        "citizen_model_cohorts": [
            {"name": "a", "count": 3,
             "primary": {"provider": "deepseek", "model": "deepseek-chat"}}],
    }}
    assert uses_paid_providers(cohorts)
    tiers = {"llm": {
        "default_route": {"provider": "scripted", "model": "scripted"},
        "tier_routes": {"premium": {"primary": {"provider": "minimax", "model": "m3"},
                                    "fallback": None}},
    }}
    assert uses_paid_providers(tiers)
    premium = {"llm": {
        "default_route": {"provider": "scripted", "model": "scripted"},
        "premium_routes": {"citizen": {"provider": "kimi", "model": "k2"}},
    }}
    assert uses_paid_providers(premium)
    assert len(configured_llm_routes(tiers)) == 2


def test_shock_scheduling_rejects_malformed_fields_and_stores_values_verbatim(economy):
    shocks = Shocks(economy, {})
    with pytest.raises(ValueError):
        shocks.schedule("rumor", "shock", {"tick": "soon"})
    with pytest.raises(ValueError):
        shocks.schedule("rumor", "shock", {"tick": 1e999})
    with pytest.raises(ValueError):
        shocks.schedule("rumor", "shock", {"tick": 3}, params={"bank_id": "x"})
    with pytest.raises(ValueError):
        shocks.schedule("oil", "conditional", {"metric": "cpi", "op": "==", "threshold": 1})
    with pytest.raises(ValueError):
        shocks.schedule("policy_rate", "shock", {"tick": 3}, params={"rate_bps": None})
    with pytest.raises(ValueError):
        shocks.schedule("rumor", "shock", {"tick": 3}, params={"audience": "everyone"})
    shock_id = shocks.schedule(
        "policy_rate", "shock", {"tick": 3}, params={"rate_bps": 500.0, "note": "kept"})
    row = economy.store.query_one("SELECT * FROM shocks WHERE id=?", (shock_id,))
    assert json.loads(row["trigger_json"]) == {"tick": 3}
    assert json.loads(row["params_json"]) == {"rate_bps": 500.0, "note": "kept"}


def test_watchdog_reports_a_stall_while_it_is_still_ongoing():
    loop = asyncio.new_event_loop()
    try:
        watchdog = LoopWatchdog(
            loop, run_id="r", poll_s=0.01, stall_s=0.05, progress_s=0.0,
            capture_stacks=False)
        watchdog._beat = time.monotonic() - 5.0
        thread = threading.Thread(target=watchdog._watch, daemon=True)
        thread.start()
        deadline = time.monotonic() + 2.0
        while watchdog.ongoing is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert watchdog.ongoing is not None
        assert watchdog.status()["stalling"]["elapsed_s"] >= 5.0
        watchdog._beat = time.monotonic()
        deadline = time.monotonic() + 2.0
        while not watchdog.stalls and time.monotonic() < deadline:
            time.sleep(0.01)
        watchdog._stop.set()
        thread.join(timeout=1.0)
        assert len(watchdog.stalls) == 1
        assert watchdog.ongoing is None
    finally:
        loop.close()


def test_broadcast_isolates_a_stalled_client():
    class Healthy:
        def __init__(self) -> None:
            self.frames: list[str] = []

        async def send_text(self, text: str) -> None:
            self.frames.append(text)

    class Stalled:
        async def send_text(self, text: str) -> None:
            await asyncio.sleep(10)

    async def scenario() -> tuple[Healthy, Stalled, WebSocketHub]:
        hub = WebSocketHub()
        hub.send_timeout_s = 0.05
        healthy, stalled = Healthy(), Stalled()
        hub.clients.update({healthy, stalled})
        await hub.broadcast({"type": "tick", "tick": 3})
        return healthy, stalled, hub

    healthy, stalled, hub = asyncio.run(scenario())
    assert json.loads(healthy.frames[0]) == {"type": "tick", "tick": 3}
    assert stalled not in hub.clients and healthy in hub.clients


def test_static_export_omits_private_events_and_resume_state(economy, tmp_path):
    public_kind = sorted(PUBLIC_REPORTABLE_EVENT_KINDS)[0]
    economy.store.log_event(1, "belief_updated", {"note": "private-belief-413"}, importance=1.0)
    economy.store.log_event(1, public_kind, {"kind": "public"}, importance=1.0)
    economy.store.set_meta(prng_state=json.dumps({"engine": [1, 2, 3]}))
    economy.store.commit()
    target = export_static_replay(economy.store, tmp_path / "replay.html")
    document = target.read_text(encoding="utf-8")
    assert "private-belief-413" not in document
    assert "belief_updated" not in document
    assert '"prng_state"' not in document
    assert public_kind in document


def test_replay_reader_ignores_sidecar_databases(tmp_path):
    sidecar = sqlite3.connect(str(tmp_path / "operator-workspace.db"))
    sidecar.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY)")
    sidecar.commit()
    sidecar.close()
    reader = ReplayReader(str(tmp_path))
    try:
        assert reader.summary("operator-workspace") is None
        assert reader.metrics("operator-workspace") is None
        assert reader.list_runs() == []
    finally:
        reader.close()


def test_pause_wakes_the_world_out_of_its_speed_delay(tmp_path):
    world = _external_world(tmp_path)
    try:
        async def scenario() -> float:
            world._pause_requested = False
            world._stop_requested = False
            asyncio.get_running_loop().call_later(0.05, world.request_pause)
            started = time.monotonic()
            await world._sleep_between_ticks(5.0)
            return time.monotonic() - started

        assert asyncio.run(scenario()) < 2.0
    finally:
        world.close()


def test_failed_transactional_phase_restores_prng_state(tmp_path):
    world = _external_world(tmp_path)
    try:
        def exploding_night_close(tick: int) -> None:
            world.engine_prng.random()
            world.lifecycle_prng.random()
            raise RuntimeError("synthetic phase failure")

        world._phase_night_close = exploding_night_close  # type: ignore[method-assign]
        before = (world.engine_prng.getstate(), world.lifecycle_prng.getstate())
        with pytest.raises(RuntimeError, match="synthetic phase failure"):
            asyncio.run(world.step())
        assert (world.engine_prng.getstate(), world.lifecycle_prng.getstate()) == before
    finally:
        world.close()


def test_zero_ticks_runs_nothing(tmp_path):
    world = _external_world(tmp_path)
    try:
        start = world.store.tick
        asyncio.run(world.run(max_ticks=0))
        assert world.store.tick == start
        assert world.status == "paused"
    finally:
        world.close()
