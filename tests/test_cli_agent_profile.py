from pathlib import Path

from llm.readiness import validate_llm_config
from run_config import load_config


ROOT = Path(__file__).resolve().parents[1]


def test_grok_codex_profile_is_live_isolated_and_provider_bounded():
    config = load_config(ROOT / "runs" / "hermes-grok-codex-live.yaml")
    llm = config["llm"]

    report = validate_llm_config(
        config, require_secrets=False, raise_on_error=False)

    assert report["ready"], report["errors"]
    assert llm["live_only"] is True
    assert set(llm["providers"]) == {"grok_cli", "codex_cli"}
    assert llm["max_in_flight"] == 2
    assert all(provider["concurrency"] == 1
               for provider in llm["providers"].values())
    assert [(cohort["name"], cohort["count"], cohort["primary"]["model"])
            for cohort in llm["citizen_model_cohorts"]] == [
        ("grok-4.5-low", 4, "grok-4.5"),
        ("codex-luna-5.6-low", 4, "gpt-5.6-luna"),
    ]
    assert all(provider["allow_agent_purposes"] is True
               for provider in llm["providers"].values())
    assert all("preflight" in provider["allowed_purposes"]
               for provider in llm["providers"].values())
    assert llm["providers"]["grok_cli"]["env"]["GROK_SANDBOX"] == "strict"
    assert llm["providers"]["codex_cli"]["env"]["CODEX_HOME"].endswith(
        r"\agent-economy\codex-cli-home")
    assert config["external_gateway"]["enabled"] is True
    assert config["external_gateway"]["public_join"]["enabled"] is True
    assert config["resource_guard"]["enabled"] is True


def test_minimax_grok_codex_profile_routes_all_three_live_providers():
    config = load_config(
        ROOT / "runs" / "hermes-minimax-grok-codex-live.yaml")
    llm = config["llm"]

    report = validate_llm_config(
        config, require_secrets=False, raise_on_error=False)

    assert report["ready"], report["errors"]
    assert llm["live_only"] is True
    assert set(llm["providers"]) == {"minimax", "grok_cli", "codex_cli"}
    assert llm["max_in_flight"] == 4
    assert llm["provider_retries"] == 1
    assert llm["providers"]["minimax"]["concurrency"] == 2
    assert llm["providers"]["minimax"]["timeout_s"] == 240
    assert llm["providers"]["minimax"]["request_defaults"][
        "max_completion_tokens"] == 16384
    assert llm["providers"]["grok_cli"]["concurrency"] == 1
    assert llm["providers"]["codex_cli"]["concurrency"] == 1
    assert llm["default_route"] == {
        "provider": "minimax", "model": "MiniMax-M3"}
    assert llm["providers"]["minimax"]["request_defaults"] == {
        "reasoning_split": True,
        "max_completion_tokens": 16384,
    }
    assert [
        (cohort["name"], cohort["count"], cohort["primary"]["provider"],
         cohort["primary"]["model"])
        for cohort in llm["citizen_model_cohorts"]
    ] == [
        ("minimax-m3", 3, "minimax", "MiniMax-M3"),
        ("grok-4.5-low", 3, "grok_cli", "grok-4.5"),
        ("codex-luna-5.6-low", 2, "codex_cli", "gpt-5.6-luna"),
    ]
    assert llm["citizen_model_cohorts"][0]["primary"]["timeout_s"] == 150
    assert llm["citizen_model_cohorts"][2]["fallback"]["timeout_s"] == 150
    assert config["budget"]["cap_usd"] == 25.0
    assert config["resource_guard"]["enabled"] is True


def test_minimax_only_profile_has_one_live_provider_and_no_fallback():
    config = load_config(
        ROOT / "runs" / "hermes-minimax-m3-only-live.yaml")
    llm = config["llm"]

    report = validate_llm_config(
        config, require_secrets=False, raise_on_error=False)

    assert report["ready"], report["errors"]
    assert llm["live_only"] is True
    assert set(llm["providers"]) == {"minimax"}
    assert llm["max_in_flight"] == 2
    assert llm["provider_retries"] == 1
    assert llm["default_route"] == {
        "provider": "minimax", "model": "MiniMax-M3"}
    assert llm["routes"] == {}
    assert llm["citizen_model_cohorts"] == [{
        "name": "minimax-m3-only",
        "count": 8,
        "primary": {
            "provider": "minimax",
            "model": "MiniMax-M3",
            "timeout_s": 240,
        },
    }]
    assert config["budget"]["cap_usd"] == 25.0
    assert config["checkpoint_every"] == 5
    assert config["resource_guard"]["enabled"] is True


def test_minimax_light_live_profile_bounds_calls_and_conversation_coverage():
    config = load_config(
        ROOT / "runs" / "hermes-minimax-m3-light-live.yaml")
    llm = config["llm"]

    report = validate_llm_config(
        config, require_secrets=False, raise_on_error=False)

    assert report["ready"], report["errors"]
    assert llm["live_only"] is True
    assert set(llm["providers"]) == {"minimax"}
    assert llm["default_route"] == {
        "provider": "minimax", "model": "MiniMax-M3"}
    assert config["population"]["size"] == 6
    assert config["firms"]["count"] == 2
    assert config["firms"]["listed"] == 0
    assert config["political_model"]["house_seats"] == 2
    assert config["political_model"]["senate_seats"] == 1
    assert config["behavior"]["act_every"] == 7
    assert config["behavior"]["institutional_act_every"] == 7
    assert config["conversations"] == {
        "turns": 2,
        "coverage_first": True,
        "recent_utterance_limit": 360,
        "similarity_jaccard_threshold": 0.65,
        "similarity_shingle_threshold": 0.65,
    }
    assert config["cognition"]["memory_rollup_every"] == 30
    assert config["budget"]["conversation_pairs"] == 1
    assert config["budget"]["cap_usd"] == 5.0
