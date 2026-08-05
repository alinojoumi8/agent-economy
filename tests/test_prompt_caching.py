from __future__ import annotations

import asyncio

import yaml

from llm.adapters import AnthropicAdapter, OpenAICompatAdapter
from llm.readiness import validate_llm_config


class _Response:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def test_readiness_validates_adapter_specific_prompt_cache_modes():
    config = {
        "llm": {
            "providers": {
                "automatic": {
                    "kind": "openai_compat", "base_url": "https://example.test/v1",
                    "api_key_env": "AUTO_KEY", "prompt_cache_mode": "provider_automatic",
                },
                "explicit": {
                    "kind": "anthropic", "api_key_env": "ANTHROPIC_KEY",
                    "prompt_cache_mode": "anthropic_ephemeral",
                },
            },
            "default_route": {"provider": "automatic", "model": "m"},
            "routes": {"oracle": {"provider": "explicit", "model": "a"}},
        }
    }
    ready = validate_llm_config(
        config, environ={"AUTO_KEY": "present", "ANTHROPIC_KEY": "present"},
        raise_on_error=False)
    assert ready["ready"]
    assert {row["prompt_cache_mode"] for row in ready["providers"]} == {
        "provider_automatic", "anthropic_ephemeral"}

    config["llm"]["providers"]["automatic"]["prompt_cache_mode"] = \
        "anthropic_ephemeral"
    invalid = validate_llm_config(
        config, environ={"AUTO_KEY": "present", "ANTHROPIC_KEY": "present"},
        raise_on_error=False)
    assert not invalid["ready"]
    assert any("does not support prompt_cache_mode" in error
               for error in invalid["errors"])


def test_unquoted_yaml_off_normalizes_to_supported_cache_mode():
    config = yaml.safe_load("""
llm:
  providers:
    local:
      kind: openai_compat
      base_url: https://example.test/v1
      api_key_env: LOCAL_KEY
      prompt_cache_mode: off
  default_route: {provider: local, model: model}
""")
    assert config["llm"]["providers"]["local"]["prompt_cache_mode"] is False
    report = validate_llm_config(
        config, environ={"LOCAL_KEY": "present"}, raise_on_error=False)
    assert report["ready"], report["errors"]
    assert report["providers"][0]["prompt_cache_mode"] == "off"
    adapter = OpenAICompatAdapter(config["llm"]["providers"]["local"])
    assert adapter.prompt_cache_mode == "off"


def test_openai_cache_modes_control_wire_key_and_preserve_usage(monkeypatch):
    import httpx

    bodies: list[dict] = []

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, endpoint, *, headers, json):
            bodies.append(json)
            return _Response({
                "choices": [{"message": {"content": "{}"}}],
                "usage": {
                    "prompt_tokens": 700, "completion_tokens": 2,
                    "prompt_tokens_details": {"cached_tokens": 512},
                },
            })

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    messages = [{"role": "system", "content": "stable"},
                {"role": "user", "content": "dynamic"}]

    keyed = OpenAICompatAdapter({
        "base_url": "https://example.test/v1", "prompt_cache_mode": "openai_key",
    })
    result = asyncio.run(keyed.complete("model", messages, cache_key="logical-key"))
    assert bodies[-1]["prompt_cache_key"] == "logical-key"
    assert result.cached_in_tokens == 512

    automatic = OpenAICompatAdapter({
        "base_url": "https://example.test/v1",
        "prompt_cache_mode": "provider_automatic",
    })
    asyncio.run(automatic.complete("model", messages, cache_key="logical-key"))
    assert "prompt_cache_key" not in bodies[-1]


def test_openai_call_token_limit_overrides_provider_request_default(monkeypatch):
    import httpx

    bodies: list[dict] = []

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, endpoint, *, headers, json):
            bodies.append(json)
            return _Response({
                "choices": [{"message": {"content": "{}"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2},
            })

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    adapter = OpenAICompatAdapter({
        "base_url": "https://example.test/v1",
        "max_tokens_field": "max_completion_tokens",
        "request_defaults": {
            "reasoning_split": True,
            "max_completion_tokens": 4096,
        },
    })

    asyncio.run(adapter.complete(
        "MiniMax-M3", [{"role": "user", "content": "JSON"}], max_tokens=900))

    assert bodies[-1]["reasoning_split"] is True
    assert bodies[-1]["max_completion_tokens"] == 900


def test_anthropic_ephemeral_marks_only_the_shared_system_prefix(monkeypatch):
    import httpx

    bodies: list[dict] = []

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, endpoint, *, headers, json):
            bodies.append(json)
            return _Response({
                "content": [{"type": "text", "text": "{}"}],
                "usage": {
                    "input_tokens": 11, "cache_creation_input_tokens": 600,
                    "cache_read_input_tokens": 0, "output_tokens": 2,
                },
            })

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    adapter = AnthropicAdapter({
        "prompt_cache_mode": "anthropic_ephemeral",
        "api_key_env": "MISSING_IS_FINE_FOR_WIRE_TEST",
    })
    result = asyncio.run(adapter.complete("model", [
        {"role": "system", "content": "shared rules"},
        {"role": "user", "content": "private state"},
    ]))

    assert bodies[-1]["system"] == [{
        "type": "text", "text": "shared rules",
        "cache_control": {"type": "ephemeral"},
    }]
    assert bodies[-1]["messages"] == [
        {"role": "user", "content": "private state"}]
    assert result.in_tokens == 611
    assert result.cached_in_tokens == 0
