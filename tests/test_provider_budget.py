"""Operational spending evidence; all providers here are controlled fixtures."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import multiprocessing
import os
from pathlib import Path
import sqlite3
import threading

import pytest
from pydantic import ValidationError

from llm.adapters import AdapterResult
from engine.store import Store
from llm.gateway import BudgetExceeded, Gateway, LLMRequest, PriorityProviderGate, RoutePlan, RouteTarget
from research.provider_budget import (
    BudgetLedgerError, ProviderBudget, ProviderBudgetContract, TokenTariff,
    gateway_config_identity,
)


def config():
    return {"budget": {"cap_usd": None}, "llm": {
        "default_route": {"provider": "fixture", "model": "test-model"},
        "providers": {"fixture": {"kind": "openai_compat", "base_url": "http://127.0.0.1:1/v1", "auth": "none"}},
        "provider_retries": 1, "rate_limit_backoff_s": [.01],
    }}


def contract(cfg=None, **changes):
    return ProviderBudgetContract(
        protocol_version="research-provider-budget-v1", study_manifest_sha256="a" * 64,
        gateway_config_sha256=gateway_config_identity(cfg or config()),
        **({"max_provider_calls": 4, "max_tokens": 40_000, "max_spend_nano_usd": 400_000,
            "tariffs": (TokenTariff(provider="fixture", model="test-model", max_input_tokens=4096,
                max_output_tokens=1024, input_nano_usd_per_token=10, output_nano_usd_per_token=20),)} | changes))


class FixtureAdapter:
    def __init__(self, result=None):
        self.result = result or AdapterResult(text='{"ok":true}', in_tokens=10, out_tokens=5,
                                             reported_usage=(10, 5))
        self.calls = 0

    async def complete(self, *_args, **_kwargs):
        self.calls += 1
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


async def complete(budget, adapter, **kwargs):
    return await budget.complete("fixture", adapter, "test-model",
        [{"role": "user", "content": "private prompt must not be saved"}],
        purpose="decision", max_tokens=100, **kwargs)


def test_shared_budget_settles_reported_usage_but_never_refunds_a_call(tmp_path):
    policy = contract(max_provider_calls=2)
    budget = ProviderBudget.create(tmp_path / "budget.db", policy, scope="preflight")
    adapter = FixtureAdapter()
    asyncio.run(complete(budget, adapter))
    resumed = ProviderBudget(budget.path, policy, scope="arm-2")
    asyncio.run(complete(resumed, adapter))
    with pytest.raises(BudgetExceeded, match="provider_calls"):
        asyncio.run(complete(budget, adapter))
    totals = resumed.snapshot()
    assert totals["provider_calls"] == adapter.calls == 2
    assert totals["reported_tokens"] == totals["encumbered_tokens"] == 30
    assert totals["usage_cost_nano_usd"] == totals["encumbered_nano_usd"] == 400
    assert totals["unresolved_calls"] == totals["unknown_usage_calls"] == 0
    assert b"private prompt" not in budget.path.read_bytes()
    assert b'{"ok":true}' not in budget.path.read_bytes()


@pytest.mark.parametrize("limit,cap,reason", [
    ("max_tokens", 4195, "encumbered_tokens"),
    ("max_spend_nano_usd", 42959, "encumbered_nano_usd"),
])
def test_token_and_cost_reservation_happen_before_transport(tmp_path, limit, cap, reason):
    budget = ProviderBudget.create(tmp_path / "budget.db", contract(**{limit: cap}), scope="cell")
    adapter = FixtureAdapter()
    with pytest.raises(BudgetExceeded, match=reason):
        asyncio.run(complete(budget, adapter))
    assert adapter.calls == budget.snapshot()["provider_calls"] == 0


@pytest.mark.parametrize("failure", [TimeoutError("private provider detail"), asyncio.CancelledError()])
def test_failed_or_cancelled_transport_keeps_full_allowance(tmp_path, failure):
    budget = ProviderBudget.create(tmp_path / "budget.db", contract(max_tokens=4196), scope="cell")
    adapter = FixtureAdapter(failure)
    with pytest.raises(type(failure)):
        asyncio.run(complete(budget, adapter))
    totals = budget.snapshot()
    assert totals["unknown_usage_calls"] == 1
    assert totals["reported_tokens"] == totals["usage_cost_nano_usd"] == 0
    assert totals["encumbered_tokens"] == 4196
    assert totals["encumbered_nano_usd"] == 42960
    with pytest.raises(BudgetExceeded):
        asyncio.run(complete(budget, adapter))
    assert adapter.calls == 1
    assert b"private provider detail" not in budget.path.read_bytes()


def test_missing_usage_is_not_replaced_by_adapter_estimates(tmp_path):
    budget = ProviderBudget.create(tmp_path / "budget.db", contract(), scope="cell")
    result = AdapterResult(text="a private response", in_tokens=10, out_tokens=5)
    assert asyncio.run(complete(budget, FixtureAdapter(result))) is result
    totals = budget.snapshot()
    assert totals["unknown_usage_calls"] == 1
    assert totals["encumbered_tokens"] == 4196
    assert totals["reported_tokens"] == 0


@pytest.mark.parametrize("usage", [(4097, 1), (10, 101), (0, 101), (-1, 3), (True, 3), ("10", 3), (2**63, 1)])
def test_usage_breach_is_durable_and_blocks_other_cells(tmp_path, usage):
    policy = contract()
    budget = ProviderBudget.create(tmp_path / "budget.db", policy, scope="first")
    adapter = FixtureAdapter(AdapterResult(text="{}", reported_usage=usage))
    with pytest.raises(BudgetExceeded, match="reported usage"):
        asyncio.run(complete(budget, adapter))
    later = ProviderBudget(budget.path, policy, scope="second")
    with pytest.raises(BudgetExceeded, match="breached"):
        asyncio.run(complete(later, adapter))
    assert later.snapshot()["breached_calls"] == adapter.calls == 1
    assert later.snapshot()["encumbered_tokens"] >= 4196


def test_unknown_and_actual_zero_output_are_distinct(tmp_path):
    budget = ProviderBudget.create(tmp_path / "budget.db", contract(), scope="cell")
    asyncio.run(complete(budget, FixtureAdapter(AdapterResult(text="", reported_usage=(10, 0)))))
    asyncio.run(complete(budget, FixtureAdapter(AdapterResult(text="", reported_usage=(0, 0)))))
    assert budget.snapshot()["reported_tokens"] == 10
    assert budget.snapshot()["unknown_usage_calls"] == 1
    assert budget.snapshot()["encumbered_tokens"] == 4206


def test_simultaneous_extreme_breaches_remain_exact_and_readable(tmp_path):
    tariff = contract().tariffs[0].model_copy(update={
        "input_nano_usd_per_token": 1_000_000_000, "output_nano_usd_per_token": 1_000_000_000})
    policy = contract(tariffs=(tariff,), max_spend_nano_usd=1_000_000_000_000_000)
    budget = ProviderBudget.create(tmp_path / "budget.db", policy, scope="cell")

    async def run():
        class ConcurrentBreaches:
            entered = 0
            ready = asyncio.Event()

            async def complete(self, *_args, **_kwargs):
                self.entered += 1
                if self.entered == 3:
                    self.ready.set()
                await self.ready.wait()
                return AdapterResult(text="{}", reported_usage=(2**31 - 1, 2**31 - 1))

        adapter = ConcurrentBreaches()
        failures = await asyncio.gather(*(complete(budget, adapter) for _ in range(3)), return_exceptions=True)
        assert all(isinstance(item, BudgetExceeded) for item in failures)

    asyncio.run(run())
    totals = budget.snapshot()
    assert totals["breached_calls"] == 3
    assert totals["encumbered_nano_usd"] == totals["usage_cost_nano_usd"] == 6 * (2**31 - 1) * 1_000_000_000


def test_concurrent_independent_connections_cannot_overbook(tmp_path):
    policy = contract(max_provider_calls=3)
    path = tmp_path / "budget.db"
    ProviderBudget.create(path, policy, scope="create")
    barrier = threading.Barrier(8)

    def worker(index):
        budget = ProviderBudget(path, policy, scope=f"cell-{index}")
        barrier.wait(timeout=15)
        try:
            asyncio.run(complete(budget, FixtureAdapter(TimeoutError())))
        except TimeoutError:
            return "dispatched"
        except BudgetExceeded:
            return "blocked"

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(worker, range(8)))
    assert results.count("dispatched") == 3
    assert results.count("blocked") == 5
    totals = ProviderBudget(path, policy, scope="inspect").snapshot()
    assert totals["provider_calls"] == totals["unknown_usage_calls"] == 3


def _crash_in_transport(path, serialized):
    class AbruptExit:
        async def complete(self, *_args, **_kwargs):
            os._exit(73)

    policy = ProviderBudgetContract.model_validate_json(serialized)
    asyncio.run(complete(ProviderBudget(Path(path), policy, scope="crashed"), AbruptExit()))


def test_process_death_does_not_replenish_reservation(tmp_path):
    policy = contract(max_provider_calls=1)
    path = tmp_path / "budget.db"
    ProviderBudget.create(path, policy, scope="create")
    child = multiprocessing.get_context("spawn").Process(
        target=_crash_in_transport, args=(str(path), policy.model_dump_json()))
    child.start()
    try:
        child.join(timeout=20)
        assert child.exitcode == 73
    finally:
        if child.is_alive():
            child.terminate()
            child.join(timeout=10)
        child.close()
    budget = ProviderBudget(path, policy, scope="resumed")
    assert budget.snapshot()["unresolved_calls"] == 1
    with pytest.raises(BudgetExceeded):
        asyncio.run(complete(budget, FixtureAdapter()))


def test_existing_changed_or_missing_ledger_fails_closed(tmp_path):
    path = tmp_path / "budget.db"
    policy = contract()
    with pytest.raises(BudgetLedgerError):
        ProviderBudget(path, policy, scope="missing")
    assert not path.exists()
    budget = ProviderBudget.create(path, policy, scope="create")
    with pytest.raises(FileExistsError):
        ProviderBudget.create(path, policy, scope="reset")
    with pytest.raises(BudgetLedgerError, match="contract changed"):
        ProviderBudget(path, contract(max_provider_calls=100), scope="enlarged")
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("UPDATE budget_contract SET json='{}'")
        conn.commit()
    adapter = FixtureAdapter()
    with pytest.raises(BudgetLedgerError):
        asyncio.run(complete(budget, adapter))
    assert adapter.calls == 0


def test_corrupt_numeric_accounting_is_a_budget_stop(tmp_path):
    budget = ProviderBudget.create(tmp_path / "budget.db", contract(), scope="cell")
    adapter = FixtureAdapter(TimeoutError())
    with pytest.raises(TimeoutError):
        asyncio.run(complete(budget, adapter))
    # SQLite's dynamic types allow text through an INTEGER column's positive
    # comparison. An unreadable record must never become a retryable outage.
    with closing(sqlite3.connect(budget.path)) as conn:
        conn.execute("UPDATE reservations SET reserved_output='not-a-count'")
        conn.commit()
    with pytest.raises(BudgetLedgerError, match="accounting is unavailable"):
        asyncio.run(complete(budget, adapter))
    assert adapter.calls == 1


@pytest.mark.parametrize("change", [
    {"kind": "cli"}, {"request_defaults": {"model": "undeclared"}},
    {"request_defaults": {"n": 2}}, {"max_tokens_field": "unsupported_limit"},
])
def test_opaque_or_request_overriding_adapters_refuse_before_dispatch(tmp_path, change):
    cfg = config()
    cfg["llm"]["providers"]["fixture"].update(change)
    budget = ProviderBudget.create(tmp_path / "budget.db", contract(cfg), scope="cell")
    with pytest.raises(BudgetLedgerError):
        budget.validate_config(cfg)
    assert budget.snapshot()["provider_calls"] == 0


@pytest.mark.parametrize("name", ["scripted", "mock"])
def test_network_provider_cannot_hide_behind_an_offline_adapter_name(tmp_path, name):
    cfg = config()
    cfg["llm"]["providers"][name] = dict(cfg["llm"]["providers"]["fixture"])
    budget = ProviderBudget.create(tmp_path / "budget.db", contract(cfg), scope="cell")
    with pytest.raises(BudgetLedgerError, match="offline adapter names"):
        budget.validate_config(cfg)
    assert budget.snapshot()["provider_calls"] == 0


@pytest.mark.parametrize("field,value", [("max_provider_calls", True), ("max_tokens", 0), ("max_spend_nano_usd", -1)])
def test_budget_contract_rejects_ambiguous_or_unbounded_limits(field, value):
    with pytest.raises(ValidationError):
        contract(**{field: value})


@pytest.mark.parametrize("provider,model,messages,output", [
    ("undeclared", "test-model", [{"role": "user", "content": "hi"}], 100),
    ("fixture", "undeclared", [{"role": "user", "content": "hi"}], 100),
    ("fixture", "test-model", [{"role": "user", "content": "hi"}], 1025),
    ("fixture", "test-model", [{"role": "user", "content": "x" * 4096}], 100),
    ("fixture", "test-model", [{"role": "user", "content": [{"type": "image"}]}], 100),
])
def test_undeclared_routes_or_oversized_requests_never_dispatch(tmp_path, provider, model, messages, output):
    budget = ProviderBudget.create(tmp_path / "budget.db", contract(), scope="cell")
    adapter = FixtureAdapter()
    with pytest.raises(BudgetExceeded):
        asyncio.run(budget.complete(provider, adapter, model, messages, purpose="decision", max_tokens=output))
    assert adapter.calls == budget.snapshot()["provider_calls"] == 0


@contextmanager
def gateway_with_budget(tmp_path, *, cfg=None, calls=4):
    cfg = cfg or config()
    policy = contract(cfg, max_provider_calls=calls)
    if "fallback" in cfg["llm"]["providers"]:
        policy = policy.model_copy(update={"tariffs": (*policy.tariffs,
            policy.tariffs[0].model_copy(update={"provider": "fallback"}))})
    budget = ProviderBudget.create(tmp_path / "budget.db", policy, scope="gateway")
    store = Store(":memory:")
    store.init_run_meta("research-fixture", 42, cfg)
    gateway = Gateway(store, cfg, completion_guard=budget)
    try:
        yield gateway, budget
    finally:
        gateway.close()
        store.close()


def tiered_plan(gateway, *, fallback=False):
    targets = [RouteTarget("fixture", "test-model", timeout_s=2.0, route_index=0)]
    if fallback:
        targets.append(RouteTarget("fallback", "test-model", timeout_s=2.0, route_index=1))
        gateway.provider_gates["fallback"] = PriorityProviderGate(1)
    gateway.route_plan = lambda _req: RoutePlan(
        assigned_tier="local", effective_tier="local", reason="fixture",
        targets=tuple(targets), tiered=True)


@contextmanager
def local_provider(*, fail_second=False, usage=None):
    posts = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def respond(self, status, body):
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            assert self.path == "/v1/models"
            self.respond(200, {"data": [{"id": "test-model"}]})

        def do_POST(self):
            assert self.path == "/v1/chat/completions"
            posts.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            if fail_second and len(posts) == 2:
                self.respond(500, {"error": "fixture response interruption"})
                return
            self.respond(200, {"choices": [{"message": {"content": '{"ok":true}'}}], **(usage or {})})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .05}, daemon=True)
    thread.start()
    cfg = config()
    cfg["llm"]["providers"]["fixture"]["base_url"] = f"http://127.0.0.1:{server.server_port}/v1"
    try:
        yield cfg, posts
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize("tiered", [False, True])
def test_real_http_preflight_and_retry_share_one_budget(tmp_path, tiered):
    usage = {"usage": {"prompt_tokens": 10, "completion_tokens": 5}}
    with local_provider(fail_second=True, usage=usage) as (cfg, posts):
        with gateway_with_budget(tmp_path, cfg=cfg, calls=3) as (gateway, budget):
            assert asyncio.run(gateway.preflight(live=True))["live_ready"] is True
            if tiered:
                tiered_plan(gateway)
            response = asyncio.run(gateway.complete(LLMRequest(role="citizen", purpose="decision", tick=1)))
            assert response.ok
            with pytest.raises(BudgetExceeded, match="provider_calls"):
                asyncio.run(gateway.complete(LLMRequest(role="citizen", purpose="decision", tick=2)))
            totals = budget.snapshot()
            assert len(posts) == totals["provider_calls"] == 3
            assert [post["max_tokens"] for post in posts] == [256, 700, 700]
            assert totals["reported_tokens"] == 30  # Preflight + successful retry.
            assert totals["unknown_usage_calls"] == 1
            assert totals["encumbered_tokens"] == 30 + 4096 + 700
            assert gateway.store.scalar("SELECT COUNT(*) FROM llm_calls") == 1
            assert gateway.store.scalar("SELECT COUNT(*) FROM events WHERE kind='provider_failure'") == 0


@pytest.mark.parametrize("usage,reported,unknown", [
    ({}, 0, 1),
    ({"usage": {"prompt_tokens": 10}}, 0, 1),
    ({"usage": {"prompt_tokens": 10, "completion_tokens": 0}}, 10, 0),
])
def test_http_usage_provenance_survives_legacy_adapter_estimates(tmp_path, usage, reported, unknown):
    with local_provider(usage=usage) as (cfg, posts):
        with gateway_with_budget(tmp_path, cfg=cfg) as (gateway, budget):
            response = asyncio.run(gateway.complete(LLMRequest(role="citizen", purpose="decision", tick=1)))
            assert response.ok
            assert response.out_tokens > 0  # Historical estimation behavior remains.
            assert budget.snapshot()["reported_tokens"] == reported
            assert budget.snapshot()["unknown_usage_calls"] == unknown
            assert len(posts) == 1


@pytest.mark.parametrize("usage,expected", [
    ({"input_tokens": 10, "output_tokens": 4, "cache_read_input_tokens": 3, "cache_creation_input_tokens": 2}, (15, 4)),
    ({"input_tokens": 10}, None),
    ({"input_tokens": -10, "output_tokens": 4, "cache_read_input_tokens": 20}, (-1, -1)),
])
def test_anthropic_reported_usage_includes_cache_without_netting_invalid_counts(monkeypatch, usage, expected):
    import httpx
    from llm.adapters import AnthropicAdapter

    client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json={
        "content": [{"type": "text", "text": "{}"}], "usage": usage}))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client(transport=transport, **kwargs))
    result = asyncio.run(AnthropicAdapter().complete("fixture-model", [{"role": "user", "content": "hi"}]))
    assert result.reported_usage == expected


@pytest.mark.parametrize("calls", [1, 2, 3])
def test_exhaustion_during_repair_or_fallback_preserves_prior_responses(tmp_path, calls):
    cfg = config()
    cfg["llm"]["providers"]["fallback"] = dict(cfg["llm"]["providers"]["fixture"])
    with gateway_with_budget(tmp_path, cfg=cfg, calls=calls) as (gateway, budget):
        primary = FixtureAdapter(AdapterResult(text="invalid json", in_tokens=10, out_tokens=5, reported_usage=(10, 5)))
        fallback = FixtureAdapter(AdapterResult(text="invalid fallback json", in_tokens=10, out_tokens=5, reported_usage=(10, 5)))
        gateway.adapters.update(fixture=primary, fallback=fallback)
        tiered_plan(gateway, fallback=True)
        with pytest.raises(BudgetExceeded, match="provider_calls"):
            asyncio.run(gateway.complete(LLMRequest(role="citizen", purpose="decision", tick=1)))
        assert primary.calls + fallback.calls == budget.snapshot()["provider_calls"] == calls
        assert budget.snapshot()["reported_tokens"] == 15 * calls
        assert gateway.store.scalar("SELECT SUM(in_tokens+out_tokens) FROM llm_calls") == 15 * calls
        assert gateway.store.scalar("SELECT COUNT(*) FROM events WHERE kind='provider_failure'") == 0
        assert gateway.global_gate.active == 0
        assert all(gate.active == 0 for gate in gateway.provider_gates.values())


def test_preflight_denial_stops_before_another_completion(tmp_path):
    with gateway_with_budget(tmp_path, calls=1) as (gateway, budget):
        adapter = FixtureAdapter()

        async def healthcheck(_model):
            return {"ok": True, "model_available": True}

        adapter.healthcheck = healthcheck
        gateway.adapters["fixture"] = adapter
        assert asyncio.run(gateway.preflight(live=True))["live_ready"] is True
        with pytest.raises(BudgetExceeded):
            asyncio.run(gateway.preflight(live=True))
        assert adapter.calls == budget.snapshot()["provider_calls"] == 1


def test_config_drift_and_replay_do_not_consume_budget(tmp_path):
    with gateway_with_budget(tmp_path) as (gateway, budget):
        gateway.config["llm"]["providers"]["fixture"]["base_url"] = "http://127.0.0.1:2/v1"
        adapter = FixtureAdapter()
        gateway.adapters["fixture"] = adapter
        with pytest.raises(BudgetLedgerError, match="configuration differs"):
            asyncio.run(gateway.complete(LLMRequest(role="citizen", purpose="decision", tick=1)))
        with pytest.raises(ValueError, match="replay cannot attach"):
            Gateway(gateway.store, {**gateway.config, "replay": True}, completion_guard=budget)
        assert adapter.calls == budget.snapshot()["provider_calls"] == 0


@pytest.mark.parametrize("tiered", [False, True])
def test_gateway_cancellation_retains_reservation_and_releases_capacity(tmp_path, tiered):
    with gateway_with_budget(tmp_path) as (gateway, budget):
        if tiered:
            tiered_plan(gateway)

        async def run():
            started = asyncio.Event()

            class PendingAdapter:
                async def complete(self, *_args, **_kwargs):
                    started.set()
                    await asyncio.Event().wait()

            gateway.adapters["fixture"] = PendingAdapter()
            task = asyncio.create_task(gateway.complete(LLMRequest(role="citizen", purpose="decision", tick=1)))
            await asyncio.wait_for(started.wait(), timeout=2)
            assert budget.snapshot()["unresolved_calls"] == 1
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        asyncio.run(run())
        assert budget.snapshot()["unknown_usage_calls"] == 1
        assert gateway.global_gate.active == 0
        assert all(gate.active == 0 for gate in gateway.provider_gates.values())


@pytest.mark.parametrize("provider", ["scripted", "mock"])
def test_offline_adapters_need_no_live_reservations(tmp_path, provider):
    cfg = config()
    cfg["llm"]["default_route"] = {"provider": provider, "model": provider}
    with gateway_with_budget(tmp_path, cfg=cfg) as (gateway, budget):
        gateway.adapters[provider] = FixtureAdapter()
        assert asyncio.run(gateway.complete(LLMRequest(role="citizen", purpose="decision", tick=1))).ok
        assert budget.snapshot()["provider_calls"] == 0
