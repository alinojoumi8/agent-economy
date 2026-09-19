"""Typed evaluations reuse accounting while requiring exact recorded evidence."""
import asyncio
import json
from pathlib import Path
import sqlite3

import httpx
import pytest

from engine.store import Store
from llm.completion_guard import BudgetExceeded
from llm.gateway import Gateway, LLMRequest, ProviderUnavailable
from llm.readiness import ProviderConfigurationError, validate_llm_config
from tests.test_jev_contract import evaluation, response, transport


def configuration():
    return {"engine_semantics_version": 16, "budget": {"cap_usd": 5, "oracle_reserve_usd": 0},
            "llm": {"default_route": {"provider": "scripted", "model": "scripted"},
                    "provider_retries": 0, "providers": {"jev": {
                        "kind": "openrouter_decisions", "api_key_env": "TEST_JEV_KEY"}},
                    "decision_policy": {"version": "bounded-economic-choice-v1", "primary": {
                        "provider": "jev", "model": "typesafe/jev-1.13"}}}}


def request(**updates):
    return LLMRequest(**({"role": "citizen", "purpose": "decision", "tick": 1} | updates))


def test_advisory_calls_use_explicit_reserve_without_changing_world_cadence(store, monkeypatch):
    monkeypatch.setenv("TEST_JEV_KEY", "private-fixture-value")
    config = configuration()
    config["budget"].update(cap_usd=1, helper_reserve_usd=.8)
    body = response()
    calls = []
    transport(monkeypatch, lambda req: calls.append(req) or httpx.Response(200, json=body))
    gateway = Gateway(store, config)
    try:
        first = asyncio.run(gateway.evaluate(request(purpose="hermes_selection"), evaluation()))
        repeat = asyncio.run(gateway.evaluate(request(purpose="hermes_selection"), evaluation()))
        assert first.call_id == repeat.call_id and len(calls) == 1
        assert gateway.governor.total_spend() == body["usage"]["cost"]
        assert gateway.governor.world_spend() == 0
        assert gateway.governor.level() == 0
        assert gateway.governor._helper_spend_usd == body["usage"]["cost"]
        assert not gateway.governor.can_spend(.8, "commons_selection")
        assert not store.query("SELECT 1 FROM events WHERE kind LIKE 'governor%'")
    finally:
        gateway.close()
    restarted = Gateway(store, config)
    try:
        assert restarted.governor.total_spend() == body["usage"]["cost"]
        assert restarted.governor.world_spend() == pytest.approx(0)
        assert restarted.governor.level() == 0
    finally:
        restarted.close()
    config["budget"]["helper_reserve_usd"] = 0
    gateway = Gateway(store, config)
    try:
        with pytest.raises(BudgetExceeded):
            asyncio.run(gateway.evaluate(request(purpose="commons_selection"), evaluation()))
    finally:
        gateway.close()


def test_openrouter_rejects_other_models_but_keeps_recorded_replay_and_direct_providers(store, monkeypatch):
    from llm.readiness import openrouter_route_error

    monkeypatch.setenv("OPENROUTER_API_KEY", "private-fixture-value")
    config = {"llm": {"providers": {"old_router": {
        "kind": "openai_compat", "base_url": "https://openrouter.ai/api/v1",
        "api_key_env": "OPENROUTER_API_KEY"}},
        "default_route": {"provider": "old_router", "model": "openai/gpt-4.1-mini"}}}
    with pytest.raises(ProviderConfigurationError, match="restricted to Jev"):
        Gateway(store, config)
    config["replay"] = True
    config["replay_source_path"] = store.path
    gateway = Gateway(store, config)
    try:
        with pytest.raises(ProviderConfigurationError, match="restricted to Jev"):
            asyncio.run(gateway._dispatch_completion("old_router", gateway.adapters["old_router"],
                        "openai/gpt-4.1-mini", []))
    finally:
        gateway.close()
    assert openrouter_route_error({"kind": "openai_compat", "base_url": "https://api.deepseek.com"},
                                  "deepseek-flash") is None
    assert openrouter_route_error({"kind": "openai_compat", "base_url": "https://api.minimax.io/v1"},
                                  "MiniMax-M3") is None


def test_zero_helper_reserve_blocks_even_a_zero_cost_estimate(store, monkeypatch):
    monkeypatch.setenv("TEST_JEV_KEY", "private-fixture-value")
    gateway = Gateway(store, configuration())
    monkeypatch.setattr(gateway, "_estimate_cost", lambda *args: 0.0)
    try:
        with pytest.raises(BudgetExceeded):
            asyncio.run(gateway.evaluate(request(purpose="hermes_selection"), evaluation()))
        assert gateway._live_dispatch_count == 0
        assert not store.query("SELECT * FROM llm_calls")
    finally:
        gateway.close()


def test_readiness_protects_text_routes_and_historical_semantics(monkeypatch):
    monkeypatch.setenv("TEST_JEV_KEY", "private-fixture-value")
    config = configuration()
    assert validate_llm_config(config)["ready"]
    config["llm"]["default_route"] = config["llm"]["decision_policy"]["primary"]
    with pytest.raises(ProviderConfigurationError, match="prose"):
        validate_llm_config(config)
    config = configuration()
    config["engine_semantics_version"] = 7
    with pytest.raises(ProviderConfigurationError, match="Semantics 16"):
        validate_llm_config(config)


def test_gateway_prices_reported_cost_and_reuses_durable_call(store, monkeypatch):
    monkeypatch.setenv("TEST_JEV_KEY", "private-fixture-value")
    calls = []
    body = response()
    body["usage"]["cost"] = .00123  # Deliberately differs from a tariff estimate.
    transport(monkeypatch, lambda req: calls.append(req) or httpx.Response(200, json=body))
    gateway = Gateway(store, configuration())
    first = asyncio.run(gateway.evaluate(request(), evaluation()))
    second = asyncio.run(gateway.evaluate(request(), evaluation()))
    assert len(calls) == 1
    assert first.call_id == second.call_id
    assert first.cost_usd == second.cost_usd == .00123
    assert gateway.governor.total_spend() == .00123
    record = store.query_one("SELECT * FROM llm_calls")
    recorded_request = json.loads(record["request_json"])
    assert recorded_request["evaluation"] == evaluation()
    assert recorded_request["contract"] == "agent-economy-decisions-v1"
    assert "private-fixture-value" not in record["request_json"] + record["response_json"]
    assert gateway._typed_reserved_usd == 0


def test_invalid_answer_is_billed_once_without_chat_repair(store, monkeypatch):
    monkeypatch.setenv("TEST_JEV_KEY", "private-fixture-value")
    calls = []
    body = response()
    body["answers"]["action"]["choice"] = "invented"
    transport(monkeypatch, lambda req: calls.append(req) or httpx.Response(200, json=body))
    gateway = Gateway(store, configuration())
    with pytest.raises(ProviderUnavailable, match="absent"):
        asyncio.run(gateway.evaluate(request(), evaluation()))
    with pytest.raises(ProviderUnavailable):
        asyncio.run(gateway.evaluate(request(), evaluation()))
    assert len(calls) == 1
    assert store.scalar("SELECT COUNT(*) FROM llm_calls") == 1
    assert gateway.governor.total_spend() == pytest.approx(body["usage"]["cost"])


def test_typed_cache_binds_menu_and_route(store, monkeypatch):
    monkeypatch.setenv("TEST_JEV_KEY", "private-fixture-value")
    calls = []
    transport(monkeypatch, lambda req: calls.append(req) or httpx.Response(200, json=response()))
    gateway = Gateway(store, configuration())
    asyncio.run(gateway.evaluate(request(), evaluation()))
    changed = evaluation()
    changed["questions"]["action"]["criteria"]["buy"]["cost_cents"] = 600
    asyncio.run(gateway.evaluate(request(), changed))
    assert len(calls) == 2
    assert store.scalar("SELECT COUNT(DISTINCT cache_key) FROM llm_calls") == 2


def test_recorded_choice_does_not_need_another_budget_reservation(store, monkeypatch):
    monkeypatch.setenv("TEST_JEV_KEY", "fixture-secret")
    calls = []
    transport(monkeypatch, lambda req: calls.append(req) or httpx.Response(200, json=response()))
    gateway = Gateway(store, configuration())
    first = asyncio.run(gateway.evaluate(request(), evaluation()))
    monkeypatch.setattr(gateway.governor, "can_spend", lambda *args: False)
    assert asyncio.run(gateway.evaluate(request(), evaluation())).call_id == first.call_id
    assert len(calls) == 1


def test_prose_call_on_same_provider_does_not_set_typed_model_identity(store, monkeypatch):
    monkeypatch.setenv("TEST_JEV_KEY", "fixture-secret")
    store.insert("llm_calls", tick=0, provider="jev", model="typesafe/jev-1.13", role="preflight",
        purpose="preflight", cache_key="prose-smoke", request_json='{}',
        response_json='{"text":"{\\"ok\\":true}"}', in_tokens=1, out_tokens=1, cost_usd=0, cached=0, latency_ms=0)
    transport(monkeypatch, lambda req: httpx.Response(200, json=response()))
    gateway = Gateway(store, configuration())
    assert asyncio.run(gateway.evaluate(request(), evaluation())).ok


def test_exact_replay_needs_no_key_and_rejects_menu_drift(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_JEV_KEY", "private-fixture-value")
    transport(monkeypatch, lambda req: httpx.Response(200, json=response()))
    config = configuration()
    source = Store(str(tmp_path / "source.db"))
    try:
        source.init_run_meta("source", 1, config)
        gateway = Gateway(source, config)
        first = asyncio.run(gateway.evaluate(request(), evaluation()))
    finally:
        gateway.close()
        source.close()
    monkeypatch.delenv("TEST_JEV_KEY")
    config.update(replay=True, replay_source_path=str(tmp_path / "source.db"))
    replay = Store(str(tmp_path / "replay.db"))
    replay.init_run_meta("replay", 1, config)
    gateway = Gateway(replay, config)
    try:
        changed = evaluation()
        changed["state"]["cash_cents"] += 1
        with pytest.raises(ProviderUnavailable, match="missing"):
            asyncio.run(gateway.evaluate(request(), changed))
        recorded = asyncio.run(gateway.evaluate(request(), evaluation()))
        assert recorded.parsed == first.parsed
        assert recorded.cost_usd == first.cost_usd
        assert gateway._live_dispatch_count == 0
        assert gateway._replay_compatibility_fallback_count == 0
    finally:
        gateway.close()
        replay.close()


def test_typed_budget_checks_request_size_before_dispatch(store, monkeypatch):
    monkeypatch.setenv("TEST_JEV_KEY", "private-fixture-value")
    config = configuration()
    config["budget"]["cap_usd"] = .0000001
    gateway = Gateway(store, config)
    with pytest.raises(BudgetExceeded):
        asyncio.run(gateway.evaluate(request(), evaluation()))
    assert gateway._live_dispatch_count == 0


def test_preflight_uses_accounted_typed_smoke_not_chat(store, monkeypatch):
    monkeypatch.setenv("TEST_JEV_KEY", "private-fixture-value")
    calls = []

    def handler(req):
        body = json.loads(req.content)
        calls.append(body)
        answer = response()
        answer["answers"] = {"check": {"type": "choice", "choice": "pass"}}
        return httpx.Response(200, json=answer)

    transport(monkeypatch, handler)
    gateway = Gateway(store, configuration())
    report = asyncio.run(gateway.preflight(live=True))
    assert report["live_ready"], report
    assert len(calls) == 1
    assert "messages" not in calls[0]
    assert store.scalar("SELECT COUNT(*) FROM llm_calls WHERE purpose='preflight'") == 1


@pytest.mark.parametrize("status", [200, 401])
def test_cli_typed_preflight_keeps_durable_receipts_and_allowance(tmp_path, monkeypatch, status):
    import run

    monkeypatch.setenv("TEST_JEV_KEY", "private-fixture-value")
    monkeypatch.setattr(run, "DATA_DIR", tmp_path / "runs")
    calls = []

    def handler(req):
        calls.append(json.loads(req.content))
        body = response()
        body["answers"] = {"check": {"type": "choice", "choice": "pass"}}
        return httpx.Response(status, json=body if status == 200 else {"error": "denied"})

    transport(monkeypatch, handler)
    report = asyncio.run(run.provider_preflight(configuration(), live=True))
    assert report["live_ready"] is (status == 200), report
    assert len(calls) == 1
    evidence = Path(report["preflight_evidence_path"])
    assert evidence.parent == tmp_path / "runs" / "preflight"
    assert report["preflight_run_id"] == evidence.stem
    with sqlite3.connect(evidence) as conn:
        assert conn.execute("SELECT COUNT(*) FROM llm_calls").fetchone()[0] == (status == 200)
    with sqlite3.connect(evidence.with_suffix(".jev-budget.db")) as conn:
        state, reserved = conn.execute("SELECT state,reserved_cost FROM reservations").fetchone()
    assert state == ("settled" if status == 200 else "unknown")
    assert reserved > 0
    assert evidence.with_suffix(".jev-budget.json").is_file()


def test_in_memory_store_requires_an_explicit_durable_typed_budget(monkeypatch):
    from llm.decision_budget import open_run_budget

    monkeypatch.setenv("TEST_JEV_KEY", "private-fixture-value")
    store = Store(":memory:")
    try:
        store.init_run_meta("preflight", 1, configuration())
        with pytest.raises(BudgetExceeded, match="file-backed store"):
            open_run_budget(store, configuration(), {})
    finally:
        store.close()
