from __future__ import annotations

import asyncio
import json
import logging
import time

import pytest

from engine.store import Store
from llm.adapters import AdapterHTTPError, AdapterResult, CLIAdapter
from llm.gateway import (
    Gateway,
    GatewayInterrupted,
    LLMRequest,
    PriorityProviderGate,
    RoutePlan,
    RouteTarget,
)
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


def test_grok_cli_adapter_uses_isolated_config_and_records_usage(monkeypatch, tmp_path):
    calls = []

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            return json.dumps({
                "text": '{"reasoning":"ok","actions":[{"type":"do_nothing"}]}',
                "thought": "must not be persisted",
                "sessionId": "grok-session",
                "modelUsage": {
                    "grok-4.5": {
                        "inputTokens": 959,
                        "cacheReadInputTokens": 300,
                        "outputTokens": 17,
                    },
                },
            }).encode(), b""

    async def create_process(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
    adapter = CLIAdapter({
        "command": "grok.exe",
        "args": [
            "--single", "{prompt}", "--model", "{model}",
            "--reasoning-effort", "low",
        ],
        "parser": "grok_json",
        "allow_agent_purposes": True,
        "allowed_purposes": ["decision"],
        "cwd": str(tmp_path),
        "env": {"GROK_SANDBOX": "strict"},
    })

    result = asyncio.run(adapter.complete(
        "grok-4.5", [{"role": "user", "content": "choose"}],
        purpose="decision"))

    assert json.loads(result.text)["actions"] == [{"type": "do_nothing"}]
    assert (result.in_tokens, result.out_tokens, result.cached_in_tokens) == (
        959, 17, 300)
    assert result.raw["sessionId"] == "grok-session"
    assert "thought" not in result.raw
    args, kwargs = calls[0]
    assert args[:4] == (
        "grok.exe", "--single", "[USER]\nchoose", "--model")
    assert args[4] == "grok-4.5"
    assert kwargs["cwd"] == str(tmp_path)
    assert kwargs["env"]["GROK_SANDBOX"] == "strict"


def test_codex_cli_adapter_streams_prompt_and_parses_jsonl(monkeypatch, tmp_path):
    calls = []
    inputs = []

    class FakeProcess:
        returncode = 0

        async def communicate(self, input_bytes=None):
            inputs.append(input_bytes)
            events = [
                {"type": "thread.started", "thread_id": "codex-thread"},
                {"type": "item.completed", "item": {
                    "type": "reasoning", "text": "must not be persisted",
                }},
                {"type": "item.completed", "item": {
                    "type": "agent_message",
                    "text": '{"reasoning":"ok","actions":[{"type":"do_nothing"}]}',
                }},
                {"type": "turn.completed", "usage": {
                    "input_tokens": 8682,
                    "cached_input_tokens": 7936,
                    "output_tokens": 9,
                }},
            ]
            return "\n".join(json.dumps(event) for event in events).encode(), b""

    async def create_process(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
    adapter = CLIAdapter({
        "command": "codex.exe",
        "args": [
            "--sandbox", "read-only", "exec", "--json", "--ephemeral",
            "--cd", str(tmp_path), "--model", "{model}", "-",
        ],
        "parser": "codex_jsonl",
        "stdin_prompt": True,
        "allow_agent_purposes": True,
        "allowed_purposes": ["decision"],
        "cwd": str(tmp_path),
        "env": {"CODEX_HOME": str(tmp_path / "codex-home")},
    })

    result = asyncio.run(adapter.complete(
        "gpt-5.6-luna", [{"role": "system", "content": "rules"},
                         {"role": "user", "content": "choose"}],
        purpose="decision"))

    assert json.loads(result.text)["actions"] == [{"type": "do_nothing"}]
    assert (result.in_tokens, result.out_tokens, result.cached_in_tokens) == (
        8682, 9, 7936)
    assert result.raw == {
        "event_count": 4,
        "thread_id": "codex-thread",
        "stderr": "",
    }
    assert inputs == [b"[SYSTEM]\nrules\n\n[USER]\nchoose"]
    args, kwargs = calls[0]
    assert args[0] == "codex.exe"
    assert "gpt-5.6-luna" in args
    assert kwargs["stdin"] == asyncio.subprocess.PIPE
    assert kwargs["env"]["CODEX_HOME"] == str(tmp_path / "codex-home")


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


def test_readiness_requires_explicit_cli_agent_purpose_opt_in():
    base_provider = {
        "kind": "cli",
        "command": "agent-cli",
    }
    config = {
        "llm": {
            "default_route": {"provider": "local-cli", "model": "agent"},
            "providers": {"local-cli": dict(base_provider)},
            "routes": {},
        },
    }

    rejected = validate_llm_config(
        config, require_secrets=False, raise_on_error=False)

    assert not rejected["ready"]
    assert "allow_agent_purposes" in " ".join(rejected["errors"])

    config["llm"]["providers"]["local-cli"].update({
        "allow_agent_purposes": True,
        "allowed_purposes": ["decision", "founder"],
    })
    accepted = validate_llm_config(
        config, require_secrets=False, raise_on_error=False)

    assert accepted["ready"], accepted["errors"]


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


def test_tiered_route_reserves_deadline_for_fallback(tmp_path):
    gateway = _gateway(tmp_path)
    gateway.logical_deadline_s = 1.0

    class SlowPrimary:
        def __init__(self):
            self.calls = 0

        async def complete(self, *args, **kwargs):
            self.calls += 1
            await asyncio.sleep(2.0)
            raise AssertionError("primary should be cancelled before logical deadline")

    class FastFallback:
        def __init__(self):
            self.calls = 0

        async def complete(self, *args, **kwargs):
            self.calls += 1
            return AdapterResult(
                text='{"reasoning":"fallback","actions":[{"type":"do_nothing"}]}',
                in_tokens=10, out_tokens=5)

    primary = SlowPrimary()
    fallback = FastFallback()
    gateway.adapters["mock"] = primary
    gateway.adapters["fallback"] = fallback
    gateway.provider_gates["fallback"] = PriorityProviderGate(1)
    plan = RoutePlan(
        assigned_tier="local",
        effective_tier="local",
        reason="test fallback deadline reservation",
        targets=(
            RouteTarget("mock", "metered", timeout_s=2.0, route_index=0),
            RouteTarget("fallback", "metered", timeout_s=0.25, route_index=1),
        ),
        tiered=True,
    )
    gateway.route_plan = lambda _req: plan

    started = time.monotonic()
    response = asyncio.run(gateway.complete(
        LLMRequest(role="citizen", purpose="decision", tick=3)))
    elapsed = time.monotonic() - started

    assert response.ok
    assert response.provider == "fallback"
    assert primary.calls == 1
    assert fallback.calls == 1
    assert elapsed < 1.0
    attempts = gateway.store.query(
        "SELECT route_index,outcome,fallback_used,llm_call_id "
        "FROM llm_attempts ORDER BY id")
    assert [
        (row["route_index"], row["outcome"], row["fallback_used"])
        for row in attempts
    ] == [(0, "timeout", 0), (1, "success", 1)]
    assert all(row["llm_call_id"] == response.call_id for row in attempts)


def test_route_plan_retries_transient_server_error_as_one_logical_call(tmp_path):
    gateway = _gateway(tmp_path)
    gateway.provider_retries = 1

    class TransientServerError:
        def __init__(self):
            self.calls = 0

        async def complete(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise AdapterHTTPError(
                    500, "https://provider.test/v1", "temporary server error")
            return AdapterResult(
                text='{"reasoning":"ok","actions":[{"type":"do_nothing"}]}',
                in_tokens=10,
                out_tokens=5,
            )

    adapter = TransientServerError()
    gateway.adapters["mock"] = adapter
    plan = RoutePlan(
        assigned_tier="local",
        effective_tier="local",
        reason="test transient server retry",
        targets=(
            RouteTarget(
                "mock", "metered", timeout_s=1.0, route_index=0),
        ),
        tiered=True,
    )
    gateway.route_plan = lambda _req: plan

    response = asyncio.run(gateway.complete(
        LLMRequest(role="legislator", purpose="decision", tick=4)))

    assert response.ok
    assert adapter.calls == 2
    assert gateway.store.scalar("SELECT COUNT(*) FROM llm_calls") == 1
    attempts = gateway.store.query(
        "SELECT route_index,outcome,llm_call_id "
        "FROM llm_attempts ORDER BY id")
    assert [
        (row["route_index"], row["outcome"]) for row in attempts
    ] == [(0, "provider_error"), (0, "success")]
    assert all(row["llm_call_id"] == response.call_id for row in attempts)


def test_route_plan_retries_provider_timeout_as_one_logical_call(tmp_path):
    gateway = _gateway(tmp_path)
    gateway.provider_retries = 1

    class TimeoutThenSucceed:
        def __init__(self):
            self.calls = 0

        async def complete(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                await asyncio.sleep(0.05)
            return AdapterResult(
                text='{"reasoning":"ok","actions":[{"type":"do_nothing"}]}',
                in_tokens=10,
                out_tokens=5,
            )

    adapter = TimeoutThenSucceed()
    gateway.adapters["mock"] = adapter
    plan = RoutePlan(
        assigned_tier="local",
        effective_tier="local",
        reason="test provider timeout retry",
        targets=(
            RouteTarget(
                "mock", "metered", timeout_s=0.01, route_index=0),
        ),
        tiered=True,
    )
    gateway.route_plan = lambda _req: plan

    response = asyncio.run(gateway.complete(
        LLMRequest(role="legislator", purpose="decision", tick=4)))

    assert response.ok
    assert adapter.calls == 2
    assert gateway.store.scalar("SELECT COUNT(*) FROM llm_calls") == 1
    attempts = gateway.store.query(
        "SELECT route_index,outcome,llm_call_id "
        "FROM llm_attempts ORDER BY id")
    assert [
        (row["route_index"], row["outcome"]) for row in attempts
    ] == [(0, "timeout"), (0, "success")]
    assert all(row["llm_call_id"] == response.call_id for row in attempts)


def test_tiered_contract_failure_uses_fallback_after_repair(tmp_path):
    gateway = _gateway(tmp_path)

    class InvalidPrimary:
        def __init__(self):
            self.calls = 0

        async def complete(self, *args, **kwargs):
            self.calls += 1
            return AdapterResult(
                text="not valid json",
                in_tokens=10,
                out_tokens=5,
                raw={"provider": "primary", "call": self.calls},
            )

    class ValidFallback:
        def __init__(self):
            self.calls = 0

        async def complete(self, *args, **kwargs):
            self.calls += 1
            return AdapterResult(
                text='{"reasoning":"fallback","actions":[{"type":"do_nothing"}]}',
                in_tokens=20,
                out_tokens=8,
                raw={"provider": "fallback", "call": self.calls},
            )

    primary = InvalidPrimary()
    fallback = ValidFallback()
    gateway.adapters["primary"] = primary
    gateway.adapters["fallback"] = fallback
    gateway.provider_gates["primary"] = PriorityProviderGate(1)
    gateway.provider_gates["fallback"] = PriorityProviderGate(1)
    gateway.pricing["primary-metered"] = {
        "in": 1.0, "out": 1.0, "cache": 0.1}
    gateway.pricing["fallback-metered"] = {
        "in": 2.0, "out": 3.0, "cache": 0.2}
    plan = RoutePlan(
        assigned_tier="local",
        effective_tier="local",
        reason="test contract fallback",
        targets=(
            RouteTarget(
                "primary", "primary-metered", timeout_s=1.0, route_index=0),
            RouteTarget(
                "fallback", "fallback-metered", timeout_s=1.0, route_index=1),
        ),
        tiered=True,
    )
    gateway.route_plan = lambda _req: plan

    response = asyncio.run(gateway.complete(
        LLMRequest(role="citizen", purpose="decision", tick=4)))

    assert response.ok
    assert response.provider == "fallback"
    assert primary.calls == 2
    assert fallback.calls == 1
    assert response.in_tokens == 40
    assert response.out_tokens == 18
    assert gateway.store.scalar("SELECT COUNT(*) FROM llm_calls") == 1
    call = gateway.store.query_one(
        "SELECT response_json,cost_usd FROM llm_calls WHERE id=?",
        (response.call_id,))
    payload = json.loads(call["response_json"])
    assert payload["raw"]["provider_calls"] == 3
    assert payload["raw"]["contract_fallback"]["failed"]["provider"] == "primary"
    assert payload["raw"]["contract_fallback"]["final"]["provider"] == "fallback"
    assert float(call["cost_usd"]) == pytest.approx(0.000094)
    attempts = gateway.store.query(
        "SELECT route_index,outcome,fallback_used,llm_call_id "
        "FROM llm_attempts ORDER BY id")
    assert [
        (row["route_index"], row["outcome"], row["fallback_used"])
        for row in attempts
    ] == [
        (0, "invalid_json", 0),
        (0, "invalid_json", 0),
        (1, "success", 1),
    ]
    assert all(row["llm_call_id"] == response.call_id for row in attempts)


def test_route_plan_retry_backoff_is_interruptible(tmp_path):
    gateway = _gateway(tmp_path)
    gateway.provider_retries = 1
    first_failure = asyncio.Event()

    class FailThenSucceed:
        def __init__(self):
            self.calls = 0

        async def complete(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                first_failure.set()
                raise AdapterHTTPError(
                    500, "https://provider.test/v1", "temporary server error")
            return AdapterResult(
                text='{"reasoning":"ok","actions":[{"type":"do_nothing"}]}',
                in_tokens=10,
                out_tokens=5,
            )

    adapter = FailThenSucceed()
    gateway.adapters["mock"] = adapter
    gateway.route_plan = lambda _req: RoutePlan(
        assigned_tier="local",
        effective_tier="local",
        reason="test interruptible transient retry",
        targets=(
            RouteTarget(
                "mock", "metered", timeout_s=1.0, route_index=0),
        ),
        tiered=True,
    )

    async def exercise():
        task = asyncio.create_task(gateway.complete(
            LLMRequest(role="legislator", purpose="decision", tick=4)))
        await first_failure.wait()
        gateway._interrupt_event.set()
        with pytest.raises(GatewayInterrupted):
            await asyncio.wait_for(task, timeout=0.1)

    asyncio.run(exercise())
    assert adapter.calls == 1


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
