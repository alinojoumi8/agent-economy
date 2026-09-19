import asyncio
from copy import deepcopy
import json

import httpx
import pytest

from llm.completion_guard import BudgetExceeded
from llm.gateway import Gateway, GatewayInterrupted, ProviderUnavailable
from tests.test_jev_gateway import configuration, request
from tests.test_jev_contract import evaluation, response, transport


@pytest.mark.parametrize("status", [401, 402, 403])
def test_auth_and_credit_failure_do_not_retry(store, monkeypatch, status):
    monkeypatch.setenv("TEST_JEV_KEY", "fixture-secret")
    calls = []
    transport(monkeypatch, lambda req: calls.append(req) or httpx.Response(status, text="fixture-secret"))
    config = configuration()
    config["llm"]["provider_retries"] = 2
    gateway = Gateway(store, config)
    with pytest.raises(ProviderUnavailable):
        asyncio.run(gateway.evaluate(request(), evaluation()))
    assert len(calls) == 1
    usage = gateway._typed_completion_guard.snapshot()
    assert usage["unknown_usage_calls"] == 1 and usage["encumbered_nano_usd"] > 0
    resumed = Gateway(store, config)
    with pytest.raises(ProviderUnavailable):
        asyncio.run(resumed.evaluate(request(tick=2), evaluation()))
    assert resumed._typed_completion_guard.snapshot()["provider_calls"] == 2


@pytest.mark.parametrize("status", [429, 529])
def test_accounted_rate_limit_retry(store, monkeypatch, status):
    monkeypatch.setenv("TEST_JEV_KEY", "fixture-secret")
    calls = []
    def handler(req):
        calls.append(req)
        return httpx.Response(status, headers={"Retry-After": "0"}) if len(calls) == 1 else httpx.Response(200, json=response())
    transport(monkeypatch, handler)
    config = configuration()
    config["llm"].update(provider_retries=1, rate_limit_backoff_s=[.01])
    gateway = Gateway(store, config)
    result = asyncio.run(gateway.evaluate(request(), evaluation()))
    assert result.parsed["answers"]["action"]["choice"] == "buy"
    assert len(calls) == 2
    usage = gateway._typed_completion_guard.snapshot()
    assert usage["provider_calls"] == 2 and usage["unknown_usage_calls"] == 1


def test_missing_original_ledger_and_usage_fail_closed(store, monkeypatch):
    monkeypatch.setenv("TEST_JEV_KEY", "fixture-secret")
    body = response()
    del body["usage"]
    transport(monkeypatch, lambda req: httpx.Response(200, json=body))
    config = configuration()
    gateway = Gateway(store, config)
    with pytest.raises(ProviderUnavailable):
        asyncio.run(gateway.evaluate(request(), evaluation()))
    assert gateway._typed_completion_guard.snapshot()["unknown_usage_calls"] == 1
    gateway._typed_completion_guard.path.unlink()
    resumed = Gateway(store, config)
    with pytest.raises(BudgetExceeded, match="missing"):
        asyncio.run(resumed.evaluate(request(tick=2), evaluation()))


def test_confident_wrong_model_is_billed_and_rejected(store, monkeypatch):
    monkeypatch.setenv("TEST_JEV_KEY", "fixture-secret")
    body = response()
    body["model"] = "typesafe/unknown-revision"
    transport(monkeypatch, lambda req: httpx.Response(200, json=body))
    gateway = Gateway(store, configuration())
    with pytest.raises(ProviderUnavailable, match="model"):
        asyncio.run(gateway.evaluate(request(), evaluation()))
    assert gateway._typed_completion_guard.snapshot()["provider_calls"] == 1
    assert gateway.governor.total_spend() > 0


def test_concurrent_reservations_and_cancellation_do_not_refund_unknown_work(store, monkeypatch):
    monkeypatch.setenv("TEST_JEV_KEY", "fixture-secret")
    config = configuration()
    config["budget"]["cap_usd"] = .0015
    gateway = Gateway(store, config)

    async def scenario():
        started = asyncio.Event()
        async def blocked(*args, **kwargs):
            started.set()
            await asyncio.Future()
        monkeypatch.setattr(gateway.adapters["jev"], "complete", blocked)
        first = asyncio.create_task(gateway.evaluate(request(), evaluation()))
        await asyncio.wait_for(started.wait(), 2)
        with pytest.raises(BudgetExceeded):
            await gateway.evaluate(request(tick=2), evaluation())
        first.cancel()
        result = await asyncio.gather(first, return_exceptions=True)
        assert isinstance(result[0], (asyncio.CancelledError, GatewayInterrupted))
    asyncio.run(scenario())
    usage = gateway._typed_completion_guard.snapshot()
    assert usage["provider_calls"] == 1
    assert usage["unknown_usage_calls"] == 1 and usage["encumbered_nano_usd"] > 0
    assert gateway._typed_reserved_usd == 0
