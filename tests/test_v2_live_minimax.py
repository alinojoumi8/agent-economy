from __future__ import annotations

from pathlib import Path

import pytest

from llm.readiness import validate_llm_config
from run_config import load_config


ROOT = Path(__file__).resolve().parents[1]


def test_v2_live_minimax_is_a_thousand_agent_fail_closed_profile(monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "sk-cp-test-only")
    config = load_config("runs/v2-live-minimax.yaml")

    report = validate_llm_config(config, raise_on_error=False)

    assert report["ready"], report["errors"]
    assert report["routed_providers"] == ["minimax"]
    assert report["route_contract"] == {
        "enforced": True,
        "provider": "minimax",
        "model": "MiniMax-M3",
        "scope": "all_gateway_routes",
    }
    assert config["engine_semantics_version"] == 7
    assert config["population"]["target_total"] == 1000
    assert config["living_world"]["core_agents"] == 100
    assert sum(
        region["population"] for region in config["living_world"]["regions"]
    ) == 1000
    assert config["budget"]["cap_usd"] == 150.0
    assert config["checkpoint_every"] == 1


def test_v2_live_minimax_allows_slow_m3_completions_before_failing_closed(monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "sk-cp-test-only")
    config = load_config("runs/v2-live-minimax.yaml")

    assert config["llm"]["providers"]["minimax"]["timeout_s"] == 600
    assert config["llm"]["provider_retries"] == 1


def test_v2_live_minimax_contract_rejects_any_route_drift(monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "sk-cp-test-only")
    config = load_config("runs/v2-live-minimax.yaml")
    config["llm"]["routes"]["memory"] = {
        "provider": "scripted", "model": "scripted",
    }

    report = validate_llm_config(config, raise_on_error=False)

    assert not report["ready"]
    assert any("violates llm.route_contract" in error for error in report["errors"])


@pytest.mark.parametrize(
    ("field", "value", "expected_error"),
    [
        ("provider", None, "llm.route_contract has no provider"),
        ("provider", "   ", "llm.route_contract has no provider"),
        ("model", None, "llm.route_contract has no model"),
        ("model", "", "llm.route_contract has no model"),
    ],
)
def test_route_contract_requires_non_empty_string_fields(
    field, value, expected_error,
):
    contract = {"provider": "scripted", "model": "scripted"}
    contract[field] = value
    config = {
        "llm": {
            "default_route": {"provider": "scripted", "model": "scripted"},
            "routes": {},
            "route_contract": contract,
        },
    }

    report = validate_llm_config(config, raise_on_error=False)

    assert not report["ready"]
    assert report["route_contract"]["enforced"] is False
    assert expected_error in report["errors"]


def test_v2_live_minimax_operator_docs_match_the_resolved_budget_cap():
    for relative_path in ("README.md", "docs/configuration.md"):
        text = (ROOT / relative_path).read_text(encoding="utf-8")
        profile_line = next(
            line for line in text.splitlines()
            if "`runs/v2-live-minimax.yaml`" in line
        )
        assert "$150 cap" in profile_line, relative_path
