from __future__ import annotations

import asyncio
import json
import logging

import pytest

from engine.store import Store
from llm.adapters import AdapterHTTPError, AdapterResult, CLIAdapter
from llm.gateway import Gateway, GatewayInterrupted, LLMRequest
from llm.readiness import validate_llm_config
from world.loop import World


def _gateway(tmp_path, *, backoff=(0.01, 0.02, 0.03)) -> Gateway:
    config = {
        "seed": 42,
        "budget": {"cap_usd": None},
        "llm": {
            "default_route": {"provider": "mock", "model": "metered"},
            "routes": {},
            "pricing": {"metered": {"in": 1.0, "out": 1.0, "cache": 0.1}},
            "rate_limit_backoff_s": list(backoff),
            "provider_retries": 1,
        },
    }
    store = Store(str(tmp_path / "hardening.db"))
    store.init_run_meta("hardening", 42, config)
    return Gateway(store, config)


def test_cli_adapter_cancels_process_and_rejects_nonzero_exit(monkeypatch):
    processes = []

    class FakeProcess:
        def __init__(self, returncode=0, stdout=b"", stderr=b""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr
            self.block = False
            self.killed = False

        async def communicate(self):
            if self.block:
                await asyncio.Event().wait()
            return self.stdout, self.stderr

        def kill(self):
            self.killed = True
            self.returncode = -1

        async def wait(self):
            return self.returncode

    async def create_process(*args, **kwargs):
        return processes.pop(0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
    adapter = CLIAdapter("agent-cli")

    failed = FakeProcess(returncode=2, stderr=b"authentication failed")
    processes.append(failed)
    with pytest.raises(RuntimeError, match="exited with code 2"):
        asyncio.run(adapter.complete("model", [{"role": "user", "content": "hi"}],
                                     purpose="oracle"))

    blocked = FakeProcess()
    blocked.block = True
    processes.append(blocked)

    async def cancel_request():
        task = asyncio.create_task(adapter.complete(
            "model", [{"role": "user", "content": "hi"}], purpose="oracle"))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancel_request())
    assert blocked.killed


def test_cli_adapter_allows_oracle_workflow_but_blocks_swarm_purposes(monkeypatch):
    calls = []

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            return b'{"result":"{}"}', b""

    async def create_process(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
    adapter = CLIAdapter("agent-cli")

    for purpose in ("oracle_plan", "oracle"):
        result = asyncio.run(adapter.complete(
            "model", [{"role": "user", "content": "hi"}], purpose=purpose))
        assert result.text == "{}"

    for purpose in ("decision", "conversation", "news"):
        with pytest.raises(PermissionError, match=f"refused purpose='{purpose}'"):
            asyncio.run(adapter.complete(
                "model", [{"role": "user", "content": "hi"}], purpose=purpose))

    assert len(calls) == 2


def test_readiness_accepts_a_purpose_specific_oracle_plan_cli_route():
    config = {
        "llm": {
            "default_route": {"provider": "scripted", "model": "scripted"},
            "providers": {"local-cli": {"kind": "cli", "command": "agent-cli"}},
            "routes": {
                "oracle_plan": {"provider": "local-cli", "model": "planner"},
            },
        },
    }

    report = validate_llm_config(config, require_secrets=False, raise_on_error=False)

    assert report["ready"], report["errors"]


def test_oracle_role_routed_to_cli_can_plan_and_answer(tmp_path, monkeypatch):
    responses = [
        {"queries": [{
            "tool": "query_metrics",
            "args": {"names": ["gdp"], "from_tick": 0, "to_tick": 0, "limit": 1},
        }]},
        {
            "p": 0.65,
            "drivers": ["current output"],
            "confidence": "med",
            "resolution_rule": {
                "type": "metric_crossed", "metric": "gdp",
                "threshold": 0.0, "direction": "above",
            },
            "deadline_tick": 1,
            "reasoning": "Current conditions support the forecast.",
        },
    ]
    subprocess_calls = []

    class FakeProcess:
        returncode = 0

        def __init__(self, response):
            self.stdout = json.dumps({"result": json.dumps(response)}).encode()

        async def communicate(self):
            return self.stdout, b""

    async def create_process(*args, **kwargs):
        subprocess_calls.append((args, kwargs))
        return FakeProcess(responses.pop(0))

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
    config = {
        "seed": 42,
        "population": {"size": 10},
        "banks": {"count": 2},
        "firms": {"count": 3, "listed": 1},
        "budget": {"cap_usd": None, "conversation_pairs": 0},
        "llm": {
            "provider_retries": 0,
            "default_route": {"provider": "scripted", "model": "scripted"},
            "routes": {
                "oracle": {"provider": "claude-cli", "model": "claude"},
            },
            "providers": {
                "claude-cli": {"kind": "cli", "command": "agent-cli"},
            },
        },
        "checkpoint_every": 0,
        "outlets": [
            {"id": 1, "name": "A", "slant": "pro-market-sensational"},
            {"id": 2, "name": "B", "slant": "cautious-pro-labor"},
        ],
    }
    store = Store(str(tmp_path / "cli-oracle.db"))
    store.init_run_meta("cli-oracle", config["seed"], config)
    world = World(store, config)
    world.initialize()

    answer = asyncio.run(world.oracle.ask("Will GDP remain above zero next tick?"))

    assert answer["p"] == pytest.approx(0.65)
    assert not responses
    assert len(subprocess_calls) == 2
    assert [row["purpose"] for row in store.query(
        "SELECT purpose FROM llm_calls ORDER BY id")] == ["oracle_plan", "oracle"]
    assert all(call[0][0] == "agent-cli" for call in subprocess_calls)


@pytest.mark.parametrize("status_code", [429, 529])
def test_provider_throttling_retries_until_success_as_one_logical_call(
        tmp_path, caplog, status_code):
    caplog.set_level(logging.INFO, logger="agent_economy.llm")
    gateway = _gateway(tmp_path)

    class RateLimitedTwice:
        def __init__(self):
            self.calls = 0

        async def complete(self, *args, **kwargs):
            self.calls += 1
            if self.calls <= 2:
                raise AdapterHTTPError(
                    status_code, "https://provider.test/v1",
                    "plan throughput reached" if status_code == 429
                    else "provider cluster overloaded")
            return AdapterResult(
                text='{"reasoning":"ok","actions":[{"type":"do_nothing"}]}',
                in_tokens=100, out_tokens=10)

    adapter = RateLimitedTwice()
    gateway.adapters["mock"] = adapter
    response = asyncio.run(gateway.complete(
        LLMRequest(role="citizen", purpose="decision", tick=3)))

    assert response.ok
    assert adapter.calls == 3
    assert gateway.rate_limit_status() is None
    assert gateway.store.scalar("SELECT COUNT(*) FROM llm_calls") == 1
    assert gateway.governor.total_spend() == pytest.approx(response.cost_usd)
    names = [getattr(record, "event_name", "") for record in caplog.records]
    assert names.count("llm.rate_limit.waiting") == 2
    assert "llm.rate_limit.recovered" in names


def test_rate_limit_status_is_visible_and_wait_is_interruptible(tmp_path):
    gateway = _gateway(tmp_path, backoff=(30,))
    first_call = asyncio.Event()

    class AlwaysLimited:
        async def complete(self, *args, **kwargs):
            first_call.set()
            raise AdapterHTTPError(
                429, "https://provider.test/v1", "wait", retry_after_s=30)

    gateway.adapters["mock"] = AlwaysLimited()

    async def exercise():
        task = asyncio.create_task(gateway.complete(
            LLMRequest(role="citizen", purpose="decision", tick=4)))
        await first_call.wait()
        await asyncio.sleep(0)
        status = gateway.rate_limit_status()
        assert status
        assert status["provider"] == "mock"
        assert status["attempts"] == 1
        assert status["cooldown_remaining_s"] > 0
        gateway.interrupt_pending()
        with pytest.raises(GatewayInterrupted):
            await task

    asyncio.run(exercise())
    assert gateway.store.scalar("SELECT COUNT(*) FROM llm_calls") == 0


def test_world_pause_during_cooldown_resumes_active_phase(tmp_path):
    config = {
        "seed": 42,
        "population": {"size": 10},
        "banks": {"count": 2},
        "firms": {"count": 3, "listed": 1},
        "behavior": {"act_every": 1},
        "budget": {"cap_usd": None, "conversation_pairs": 0},
        "llm": {
            "default_route": {"provider": "scripted", "model": "scripted"},
            "routes": {}, "provider_retries": 0,
            "rate_limit_backoff_s": [30],
        },
        "checkpoint_every": 0,
        "checkpoint_dir": str(tmp_path / "checkpoints"),
        "report_dir": str(tmp_path / "reports"),
    }
    store = Store(str(tmp_path / "world-cooldown.db"))
    store.init_run_meta("world-cooldown", 42, config)
    world = World(store, config)
    world.initialize()
    delegate = world.gateway.adapters["scripted"]
    limited = asyncio.Event()

    class LimitOnce:
        def __init__(self):
            self.did_limit = False

        async def complete(self, *args, **kwargs):
            if not self.did_limit:
                self.did_limit = True
                limited.set()
                raise AdapterHTTPError(
                    429, "https://provider.test/v1", "short cooldown",
                    retry_after_s=30)
            return await delegate.complete(*args, **kwargs)

    world.gateway.adapters["scripted"] = LimitOnce()

    async def exercise():
        task = asyncio.create_task(world.step())
        await limited.wait()
        await asyncio.sleep(0)
        world.request_pause()
        paused = await task
        assert paused["interrupted"] == "pause"
        assert store.tick == 0
        assert store.active_tick == 1
        assert store.next_phase == "MORNING"

        # Advance the synthetic provider clock without making this test depend
        # on scheduler speed. The long cooldown above guarantees pause wins the
        # race even on slow Windows CI runners.
        world.gateway._rate_limits["scripted"]["retry_at_epoch"] = 0
        world._pause_requested = False
        world.gateway.clear_interrupt()
        resumed = await world.step()
        assert resumed["tick"] == 1

    asyncio.run(exercise())
    assert store.tick == 1
    assert store.active_tick is None
