"""Operational logs stay structured, bounded, and secret-safe."""
import asyncio
import json
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

import pytest

from engine.store import Store
from engine.actions import ActionExecutor
from llm.gateway import Gateway
from observability import (
    JsonFormatter,
    configure_logging,
    log_event,
    safe_fields,
)
import run as cli
from run_config import load_config
from world.loop import World


def test_safe_fields_redacts_credentials_and_bounds_text():
    fields = safe_fields({
        "api_key": "sk-secret",
        "nested": {"access_token": "token-value", "status": "ok"},
        "detail": "x" * 800,
        "error": "request failed with Bearer abc123 and api_key=visible-secret",
    })

    assert fields["api_key"] == "[REDACTED]"
    assert fields["nested"] == {"access_token": "[REDACTED]", "status": "ok"}
    assert len(fields["detail"]) == 500 and fields["detail"].endswith("...")
    assert fields["error"] == (
        "request failed with [REDACTED] and api_key=[REDACTED]")


def test_json_formatter_emits_stable_event_and_context():
    logger = logging.getLogger("agent_economy.test.formatter")
    record = logging.LogRecord(logger.name, logging.INFO, __file__, 1, "ignored", (), None)
    record.event_name = "test.completed"
    record.event_fields = {"run_id": "run-1", "tick": 3}

    payload = json.loads(JsonFormatter().format(record))

    assert payload["event"] == "test.completed"
    assert payload["level"] == "INFO"
    assert payload["logger"] == logger.name
    assert payload["run_id"] == "run-1" and payload["tick"] == 3
    assert payload["timestamp"].endswith("+00:00")


def test_log_event_attaches_testable_structured_fields(caplog):
    logger = logging.getLogger("agent_economy.test.emitter")
    caplog.set_level(logging.INFO, logger=logger.name)

    log_event(logger, logging.INFO, "operation.completed",
              run_id="run-2", authorization="Bearer secret")

    record = caplog.records[-1]
    assert record.event_name == "operation.completed"
    assert record.event_fields == {
        "run_id": "run-2", "authorization": "[REDACTED]",
    }


def test_configure_logging_writes_to_a_bounded_json_file(tmp_path, monkeypatch):
    path = tmp_path / "operations.jsonl.log"
    monkeypatch.setenv("AGENT_ECONOMY_LOG_FILE", str(path))
    root = logging.getLogger()
    existing_handlers = list(root.handlers)

    try:
        configure_logging("INFO")
        log_event(
            logging.getLogger("agent_economy.test.file"),
            logging.INFO, "file.test.completed", tick=7)
        added = [handler for handler in root.handlers
                 if handler not in existing_handlers]
        for handler in added:
            handler.flush()

        payload = json.loads(path.read_text(encoding="utf-8").strip())
        assert payload["event"] == "file.test.completed"
        assert payload["tick"] == 7
        rotating = next(
            handler for handler in added
            if isinstance(handler, RotatingFileHandler))
        assert rotating.maxBytes == 10 * 1024 * 1024
        assert rotating.backupCount == 5
    finally:
        for handler in list(root.handlers):
            if handler not in existing_handlers:
                root.removeHandler(handler)
                handler.close()


def test_cli_loads_dotenv_before_configuring_logging(monkeypatch):
    calls = []

    def load_environment():
        monkeypatch.setenv("AGENT_ECONOMY_LOG_LEVEL", "DEBUG")
        calls.append("dotenv")

    def configure_from_environment():
        calls.append(os.environ["AGENT_ECONOMY_LOG_LEVEL"])

    monkeypatch.setattr(cli, "load_dotenv", load_environment)
    monkeypatch.setattr(cli, "configure_logging", configure_from_environment)
    monkeypatch.setattr(sys, "argv", ["run.py", "--help"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    assert calls == ["dotenv", "DEBUG"]


def test_cli_live_profiles_require_explicit_inference_approval(monkeypatch):
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)
    monkeypatch.setattr(cli, "configure_logging", lambda: None)
    monkeypatch.setattr(sys, "argv", [
        "run.py", "--config", "runs/v2-live-hybrid.yaml", "--ticks", "1",
    ])

    with pytest.raises(SystemExit, match="--approve-live-inference"):
        cli.main()


def test_cli_live_approval_reaches_run_open(monkeypatch):
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)
    monkeypatch.setattr(cli, "configure_logging", lambda: None)
    monkeypatch.setattr(sys, "argv", [
        "run.py", "--config", "runs/v2-live-hybrid.yaml", "--ticks", "1",
        "--approve-live-inference",
    ])

    def authorized(*_args, **_kwargs):
        raise RuntimeError("authorized live run reached open_run")

    monkeypatch.setattr(cli, "open_run", authorized)
    with pytest.raises(RuntimeError, match="authorized live run"):
        cli.main()


def test_cli_live_preflight_does_not_require_run_approval(monkeypatch):
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)
    monkeypatch.setattr(cli, "configure_logging", lambda: None)
    monkeypatch.setattr(sys, "argv", [
        "run.py", "--config", "runs/v2-live-hybrid.yaml", "--preflight",
    ])

    async def ready(_config, *, live=False):
        return {"ready": True, "live_ready": True, "errors": []}

    monkeypatch.setattr(cli, "provider_preflight", ready)
    cli.main()


def test_cli_live_replay_does_not_require_run_approval(monkeypatch):
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)
    monkeypatch.setattr(cli, "configure_logging", lambda: None)
    monkeypatch.setattr(sys, "argv", [
        "run.py", "--config", "runs/v2-live-hybrid.yaml", "--replay", "saved-live",
    ])

    def replay_opened(*_args, **_kwargs):
        raise RuntimeError("live replay reached open_run")

    monkeypatch.setattr(cli, "open_run", replay_opened)
    with pytest.raises(RuntimeError, match="live replay"):
        cli.main()


def test_cli_resume_checks_authoritative_persisted_provider_config(monkeypatch):
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)
    monkeypatch.setattr(cli, "configure_logging", lambda: None)
    monkeypatch.setattr(sys, "argv", [
        "run.py", "--config", "runs/base.yaml", "--resume", "saved-live",
    ])

    class FakeStore:
        closed = False

        def close(self):
            self.closed = True

    fake_store = FakeStore()
    live_config = cli.load_config("runs/v2-live-hybrid.yaml")
    fake_world = type("FakeWorld", (), {"config": live_config})()
    monkeypatch.setattr(
        cli, "open_run", lambda *_args, **_kwargs: (fake_store, fake_world, "saved-live"))

    with pytest.raises(SystemExit, match="--approve-live-inference"):
        cli.main()
    assert fake_store.closed


def test_cli_scripted_resume_ignores_non_authoritative_live_cli_config(monkeypatch):
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)
    monkeypatch.setattr(cli, "configure_logging", lambda: None)
    monkeypatch.setattr(sys, "argv", [
        "run.py", "--config", "runs/v2-live-hybrid.yaml", "--resume", "saved-scripted",
    ])

    class FakeStore:
        tick = 7

        @staticmethod
        def get_meta():
            return {"seed": 42}

    scripted_config = cli.load_config("runs/base.yaml")
    fake_world = type("FakeWorld", (), {"config": scripted_config})()
    monkeypatch.setattr(
        cli, "open_run", lambda *_args, **_kwargs: (FakeStore(), fake_world, "saved-scripted"))

    def stop_after_authoritative_check(_logger, _level, event, **_fields):
        if event == "run.opened":
            raise RuntimeError("scripted resume passed provider authorization")

    monkeypatch.setattr(cli, "operational_log", stop_after_authoritative_check)
    with pytest.raises(RuntimeError, match="scripted resume passed"):
        cli.main()


def test_provider_preflight_emits_a_summary_without_secrets(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="agent_economy.llm")
    config = {
        "llm": {
            "default_route": {"provider": "scripted", "model": "scripted"},
            "routes": {},
        },
        "budget": {"cap_usd": 1.0},
    }
    store = Store(str(tmp_path / "preflight.db"))
    store.init_run_meta("preflight-test", 1, config)

    report = asyncio.run(Gateway(store, config).preflight(live=False))

    assert report["ready"]
    completed = next(record for record in caplog.records
                     if getattr(record, "event_name", "") == "llm.preflight.completed")
    assert completed.event_fields["ready"] is True
    assert completed.event_fields["live_checked"] is False
    assert not any("key" in key for key in completed.event_fields)
    store.close()


def test_world_run_lifecycle_and_checkpoint_are_logged(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="agent_economy.world")
    config = {
        "seed": 3,
        "population": {"size": 14},
        "banks": {"count": 2},
        "firms": {"count": 3, "listed": 1},
        "budget": {"cap_usd": 10.0, "oracle_reserve_usd": 1.0,
                   "conversation_pairs": 2},
        "llm": {
            "default_route": {"provider": "scripted", "model": "scripted"},
            "routes": {},
        },
        "checkpoint_every": 0,
        "checkpoint_dir": str(tmp_path / "checkpoints"),
        "outlets": [
            {"id": 1, "name": "A", "slant": "pro-market-sensational"},
            {"id": 2, "name": "B", "slant": "cautious-pro-labor"},
        ],
    }
    store = Store(str(tmp_path / "world.db"))
    store.init_run_meta("world-test", config["seed"], config)
    world = World(store, config)
    world.initialize()

    asyncio.run(world.run(max_ticks=1))

    events = [getattr(record, "event_name", "") for record in caplog.records]
    assert "world.run.started" in events
    assert "world.phase.started" in events
    assert "world.phase.completed" in events
    assert "world.tick.completed" in events
    assert "world.checkpoint.created" in events
    assert "world.run.finished" in events
    finished = next(record for record in caplog.records
                    if getattr(record, "event_name", "") == "world.run.finished")
    assert finished.event_fields["start_tick"] == 0
    assert finished.event_fields["end_tick"] == 1
    assert finished.event_fields["status"] == "paused"
    store.close()


def test_resource_guard_pauses_after_a_sustained_limit(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="agent_economy.world")
    config = load_config("runs/base.yaml")
    config["resource_guard"] = {
        "enabled": True,
        "sample_interval_s": 0.1,
        "max_cpu_percent": 95,
        "max_memory_percent": 90,
        "min_available_memory_gb": 4,
        "consecutive_breaches": 1,
    }
    store = Store(str(tmp_path / "resource-guard.db"))
    store.init_run_meta("resource-guard", int(config["seed"]), config)
    world = World(store, config)
    world.status = "running"
    monkeypatch.setattr(world, "_resource_snapshot", lambda: {
        "system_cpu_percent": 99.0,
        "system_memory_percent": 50.0,
        "available_memory_gb": 8.0,
        "process_rss_mb": 500.0,
        "global_in_flight": 2,
        "global_queue_depth": 1,
        "provider_in_flight": {"scripted": 2},
        "provider_queue_depth": {"scripted": 1},
    })

    asyncio.run(world._monitor_resources())

    assert world._pause_requested
    assert world.last_pause_reason["reason"] == "resource_guard"
    assert world.last_pause_reason["breaches"] == ["system_cpu"]
    events = [getattr(record, "event_name", "") for record in caplog.records]
    assert "runtime.resource.sample" in events
    assert "runtime.resource.limit_reached" in events
    world.close()


def test_resource_guard_detects_pagefile_pressure(tmp_path):
    config = load_config("runs/base.yaml")
    store = Store(str(tmp_path / "swap-resource-guard.db"))
    store.init_run_meta("swap-resource-guard", int(config["seed"]), config)
    world = World(store, config)
    world.resource_guard = {"max_swap_percent": 50}
    try:
        assert world._resource_breaches({
            "system_cpu_percent": 10.0,
            "system_memory_percent": 40.0,
            "available_memory_gb": 32.0,
            "system_swap_percent": 50.0,
        }) == ["system_swap"]
    finally:
        world.close()


def test_unexpected_action_handler_failure_is_logged(economy, caplog):
    caplog.set_level(logging.INFO, logger="agent_economy.engine.actions")
    actor_id = economy.store.insert(
        "agents", name="Broken handler actor", kind="citizen",
        occupation="worker", age=30, alive=1,
    )
    executor = ActionExecutor(economy)

    def fail_handler(*_args):
        raise RuntimeError("synthetic engine defect")

    executor._do_say_public = fail_handler
    result = executor.execute_action(
        1, actor_id, {"type": "say_public", "text": "hello"})

    assert result["ok"] is False
    record = next(record for record in caplog.records
                  if getattr(record, "event_name", "") == "action.execution.failed")
    assert record.event_fields["actor_id"] == actor_id
    assert record.event_fields["action_type"] == "say_public"
    assert record.event_fields["error_type"] == "RuntimeError"
