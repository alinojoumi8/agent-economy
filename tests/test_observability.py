"""Operational logs stay structured, bounded, and secret-safe."""
import asyncio
import json
import logging
import os
import sys

import pytest

from engine.store import Store
from engine.actions import ActionExecutor
from llm.gateway import Gateway
from observability import JsonFormatter, log_event, safe_fields
import run as cli
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
    assert "world.checkpoint.created" in events
    assert "world.run.finished" in events
    finished = next(record for record in caplog.records
                    if getattr(record, "event_name", "") == "world.run.finished")
    assert finished.event_fields["start_tick"] == 0
    assert finished.event_fields["end_tick"] == 1
    assert finished.event_fields["status"] == "paused"
    store.close()


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
