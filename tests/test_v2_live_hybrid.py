from __future__ import annotations

from run import open_run
from run_config import load_config
from llm.gateway import sanitize_provider_raw
from llm.readiness import validate_llm_config


def test_hybrid_live_profile_is_bounded_and_routes_by_risk(tmp_path, monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "sk-cp-test-only")
    monkeypatch.setenv("OLLAMA_API_KEY", "ollama")
    config = load_config("runs/v2-live-hybrid.yaml")

    report = validate_llm_config(config, raise_on_error=False)
    assert report["ready"], report["errors"]
    assert report["routed_providers"] == ["minimax", "ollama"]
    assert config["engine_semantics_version"] == 6
    assert config["population"]["target_total"] == 30
    assert config["living_world"]["core_agents"] == 4
    assert sum(region["population"] for region in config["living_world"]["regions"]) == 30
    assert config["budget"]["cap_usd"] == 0.25
    assert config["checkpoint_every"] == 1
    ollama_defaults = config["llm"]["providers"]["ollama"]["request_defaults"]
    assert ollama_defaults["reasoning_effort"] == "none"
    assert ollama_defaults["temperature"] == 0.0

    store, world, _ = open_run(config, None, None, data_dir=tmp_path)
    try:
        assert store.scalar("SELECT COUNT(*) FROM agents") == 30
        assert store.scalar(
            "SELECT COUNT(*) FROM agents WHERE population_tier='core'") == 4
        region_counts = {
            row["region_key"]: int(row["n"])
            for row in store.query(
                "SELECT r.region_key,COUNT(a.id) AS n FROM regions r "
                "LEFT JOIN agents a ON a.region_id=r.id GROUP BY r.id ORDER BY r.id")
        }
        assert region_counts == {"northstar": 24, "ironvale": 3, "suncoast": 3}
        assert world.gateway.route("lawyer", "decision") == ("minimax", "MiniMax-M3")
        assert world.gateway.route("citizen", "founder") == ("minimax", "MiniMax-M3")
        assert world.gateway.route("reporter", "newsroom") == ("ollama", "gemma4:12b")
        assert world.gateway.route("citizen", "conversation") == ("ollama", "gemma4:12b")
        ok, diagnostic = world.economy.ledger.reconcile()
        assert ok, diagnostic
    finally:
        store.close()


def test_provider_raw_private_reasoning_is_never_persisted():
    raw = {
        "choices": [{"message": {
            "content": '{"actions":[]}',
            "reasoning_content": "private chain",
            "reasoning_details": [{"thought": "private detail"}],
            "role": "assistant",
        }}],
        "usage": {"completion_tokens_details": {"reasoning_tokens": 42}},
        "provider_calls": 2,
        "repair": {"initial": {"thinking": "private trace"}},
    }

    sanitized = sanitize_provider_raw(raw)

    message = sanitized["choices"][0]["message"]
    assert message == {"content": '{"actions":[]}', "role": "assistant"}
    assert sanitized["usage"]["completion_tokens_details"]["reasoning_tokens"] == 42
    assert sanitized["provider_calls"] == 2
    assert sanitized["repair"]["initial"] == {}
