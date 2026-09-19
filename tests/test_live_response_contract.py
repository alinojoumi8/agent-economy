import asyncio
import json

import pytest

from llm.adapters import AdapterResult
from llm.completion_guard import BudgetExceeded
from llm.gateway import Gateway, LLMRequest, ProviderUnavailable
from llm.readiness import ProviderConfigurationError, validate_llm_config


def configuration():
    return {"engine_semantics_version": 16, "budget": {"cap_usd": 5, "oracle_reserve_usd": 0}, "llm": {
        "response_contract": "required-json-v2", "provider_retries": 0,
        "providers": {"network": {"kind": "openai_compat", "base_url": "https://invalid.example",
            "api_key_env": "RESPONSE_TEST_KEY", "minimum_output_tokens": 8192}},
        "pricing": {"model": {"in": 1, "out": 1}},
        "default_route": {"provider": "network", "model": "model"}}}


@pytest.mark.parametrize("valid", [True, False])
def test_live_contract_is_sent_on_first_call_and_survives_resume(store, monkeypatch, valid):
    monkeypatch.setenv("RESPONSE_TEST_KEY", "test-only")
    gateway = Gateway(store, configuration())
    calls = []
    schema = '{"summary":"text","importance":1.0,"belief_updates":[]}'

    class Adapter:
        async def complete(self, model, messages, **kwargs):
            calls.append(kwargs)
            assert schema in messages[0]["content"]
            assert kwargs["max_tokens"] >= 8192
            return AdapterResult(text=schema if valid else '{"wrong":true}',
                in_tokens=10, out_tokens=10, raw={})

    gateway.adapters["network"] = Adapter()
    request = LLMRequest(role="citizen", purpose="memory", system="Summarize.", user="Facts", max_tokens=100)
    try:
        for _ in range(2):
            if valid:
                assert asyncio.run(gateway.complete(request, schema_hint=schema)).ok
            else:
                with pytest.raises(ProviderUnavailable, match="JSON|contract"):
                    asyncio.run(gateway.complete(request, schema_hint=schema))
        assert len(calls) == (1 if valid else 2)
        assert store.scalar("SELECT COUNT(*) FROM llm_calls") == 1
        stored = json.loads(store.scalar("SELECT request_json FROM llm_calls"))
        assert schema in stored["system"]
        assert request.max_tokens == 100 and request.system == "Summarize."
    finally:
        gateway.close()


@pytest.mark.parametrize("edit", ["old_semantics", "unknown_contract", "bad_floor"])
def test_response_contract_rejects_invalid_configuration(edit):
    config = configuration()
    if edit == "old_semantics": config["engine_semantics_version"] = 11
    if edit == "unknown_contract": config["llm"]["response_contract"] = "typo"
    if edit == "bad_floor": config["llm"]["providers"]["network"]["minimum_output_tokens"] = True
    with pytest.raises(ProviderConfigurationError):
        validate_llm_config(config, require_secrets=False)


def test_output_floor_is_included_in_budget_check_before_dispatch(store, monkeypatch):
    monkeypatch.setenv("RESPONSE_TEST_KEY", "test-only")
    config = configuration()
    config["budget"]["cap_usd"] = .001
    gateway = Gateway(store, config)
    try:
        with pytest.raises(BudgetExceeded):
            asyncio.run(gateway.complete(LLMRequest(role="citizen", purpose="memory", max_tokens=1)))
        assert gateway._live_dispatch_count == 0
        assert store.scalar("SELECT COUNT(*) FROM llm_calls") == 0
    finally:
        gateway.close()
