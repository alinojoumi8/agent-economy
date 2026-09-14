from __future__ import annotations

from pathlib import Path

from llm.readiness import validate_llm_config
from llm.gateway import DEFAULT_PRICING
from run_config import load_config


ROOT = Path(__file__).resolve().parents[1]


def test_v41_demo_is_live_only_bounded_and_preserves_historical_pricing(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only")
    config = load_config(ROOT / "runs" / "deepseek-v41-demo.yaml")
    report = validate_llm_config(config, raise_on_error=False)
    assert report["ready"], report["errors"]
    assert report["routed_providers"] == ["deepseek"]
    assert config["llm"]["live_only"] is True
    assert config["llm"]["require_preflight_live"] is True
    assert config["budget"]["cap_usd"] == 2.0
    assert config["behavior"]["act_every"] == 3
    assert config["llm"]["pricing"]["deepseek-flash"] == DEFAULT_PRICING["deepseek-flash"]
    assert DEFAULT_PRICING["deepseek-v4-flash"] == {
        "in": 0.14, "out": 0.28, "cache": 0.0028,
    }


def test_live_deepseek_smoke_matches_minimax_mechanics_and_fails_closed(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only")
    deepseek = load_config(ROOT / "runs" / "live-smoke-deepseek.yaml")
    minimax = load_config(ROOT / "runs" / "live-smoke.yaml")

    report = validate_llm_config(deepseek, raise_on_error=False)

    assert report["ready"], report["errors"]
    assert report["routed_providers"] == ["deepseek"]
    assert report["route_contract"] == {
        "enforced": True,
        "provider": "deepseek",
        "model": "deepseek-flash",
        "scope": "all_gateway_routes",
    }
    assert deepseek["population"] == minimax["population"]
    assert deepseek["firms"] == minimax["firms"]
    assert deepseek["behavior"] == minimax["behavior"]
    assert deepseek["budget"] == minimax["budget"]
    assert deepseek["checkpoint_every"] == minimax["checkpoint_every"]
    assert deepseek["llm"]["default_route"] == {
        "provider": "deepseek", "model": "deepseek-flash",
    }
    assert all(
        route == {"provider": "deepseek", "model": "deepseek-flash"}
        for route in deepseek["llm"]["routes"].values()
    )


def test_live_deepseek_smoke_uses_official_non_thinking_json_route(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only")
    config = load_config(ROOT / "runs" / "live-smoke-deepseek.yaml")

    provider = config["llm"]["providers"]["deepseek"]

    assert provider == {
        "kind": "openai_compat",
        "base_url": "https://api.deepseek.com",
        "api_key_env": "DEEPSEEK_API_KEY",
        "concurrency": 6,
        "prompt_cache_mode": "provider_automatic",
        "timeout_s": 60,
        "healthcheck_path": "/models",
        "max_tokens_field": "max_tokens",
        "request_defaults": {
            "stream": False,
            "thinking": {"type": "disabled"},
        },
    }
    assert config["llm"]["pricing"]["deepseek-flash"] == {
        "in": 0.30, "out": 1.20, "cache": 0.006,
    }
