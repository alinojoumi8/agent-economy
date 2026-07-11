from __future__ import annotations

import asyncio
import logging

import pytest

from engine.store import Store
from llm.adapters import AdapterHTTPError, AdapterResult
from llm.gateway import Gateway, GatewayInterrupted, LLMRequest
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
            "rate_limit_backoff_s": [0.05],
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
                    retry_after_s=0.05)
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

        await asyncio.sleep(0.06)
        world._pause_requested = False
        world.gateway.clear_interrupt()
        resumed = await world.step()
        assert resumed["tick"] == 1

    asyncio.run(exercise())
    assert store.tick == 1
    assert store.active_tick is None
