from __future__ import annotations

from pathlib import Path

from llm.readiness import validate_llm_config
from run_config import load_config


ROOT = Path(__file__).resolve().parents[1]


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
        "model": "deepseek-v4-flash",
        "scope": "all_gateway_routes",
    }
    assert deepseek["population"] == minimax["population"]
    assert deepseek["firms"] == minimax["firms"]
    assert deepseek["behavior"] == minimax["behavior"]
    assert deepseek["budget"] == minimax["budget"]
    assert deepseek["checkpoint_every"] == minimax["checkpoint_every"]
    assert deepseek["llm"]["default_route"] == {
        "provider": "deepseek", "model": "deepseek-v4-flash",
    }
    assert all(
        route == {"provider": "deepseek", "model": "deepseek-v4-flash"}
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
    assert config["llm"]["pricing"]["deepseek-v4-flash"] == {
        "in": 0.14, "out": 0.28, "cache": 0.0028,
    }
