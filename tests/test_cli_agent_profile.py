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
