from __future__ import annotations

import asyncio
import logging

import pytest

from engine.store import Store
from llm.adapters import AdapterHTTPError, AdapterResult
from llm.gateway import Gateway, GatewayInterrupted, LLMRequest


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


def test_rate_limits_retry_until_success_as_one_logical_call(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="agent_economy.llm")
    gateway = _gateway(tmp_path)

    class RateLimitedTwice:
        def __init__(self):
            self.calls = 0

        async def complete(self, *args, **kwargs):
            self.calls += 1
            if self.calls <= 2:
                raise AdapterHTTPError(
                    429, "https://provider.test/v1", "plan throughput reached")
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
