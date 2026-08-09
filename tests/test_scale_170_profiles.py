from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from llm.readiness import validate_llm_config
from run import open_run
from run_config import load_config


ROOT = Path(__file__).resolve().parents[1]
REHEARSAL = ROOT / "runs" / "scale-170-rehearsal.yaml"
MINIMAX = ROOT / "runs" / "scale-170-minimax-live.yaml"
DEEPSEEK = ROOT / "runs" / "scale-170-deepseek-live.yaml"
LIVE_PROFILE_CASES = [
    (MINIMAX, "MINIMAX_API_KEY", "minimax", "MiniMax-M3", 3, 100.0),
    (
        DEEPSEEK,
        "DEEPSEEK_API_KEY",
        "deepseek",
        "deepseek-v4-flash",
        6,
        25.0,
    ),
]


def test_scale_170_rehearsal_builds_exact_population_and_paid_core(tmp_path):
    config = load_config(REHEARSAL)

    assert config["engine_semantics_version"] == 7
    assert config["population"] == {
        "baseline_citizens_core": False,
        "size": 170,
    }
    assert config["living_world"]["core_agents"] == 100
    assert sum(
        int(region["population"])
        for region in config["living_world"]["regions"]
    ) == 208
    assert config["conversations"]["coverage_first"] is True
    assert config["budget"]["conversation_pairs"] == 17
    assert config["checkpoint_every"] == 7
    assert config["checkpoint_keep_last"] == 4
    assert config["llm"]["default_route"] == {
        "provider": "scripted",
        "model": "scripted",
    }

    store, world, _run_id = open_run(config, None, None, data_dir=tmp_path)
    try:
        assert store.scalar("SELECT COUNT(*) FROM agents") == 208
        assert store.scalar(
            "SELECT COUNT(*) FROM agents WHERE kind='citizen'"
        ) == 172
        assert store.scalar(
            "SELECT COUNT(*) FROM agents WHERE kind='staff'"
        ) == 36
        assert store.scalar(
            "SELECT COUNT(*) FROM agents WHERE population_tier='core'"
        ) == 100
        assert store.scalar(
            "SELECT COUNT(*) FROM agents WHERE population_tier='periphery'"
        ) == 108
        region_counts = {
            str(row["region_key"]): int(row["n"])
            for row in store.query(
                "SELECT r.region_key,COUNT(a.id) AS n FROM regions r "
                "LEFT JOIN agents a ON a.region_id=r.id "
                "GROUP BY r.id ORDER BY r.id"
            )
        }
        assert region_counts == {
            "northstar": 125,
            "ironvale": 46,
            "suncoast": 37,
        }
        ok, diagnostic = world.economy.ledger.reconcile()
        assert ok, diagnostic
    finally:
        store.close()


@pytest.mark.parametrize(
    ("profile", "key_name", "provider", "model", "concurrency", "cap_usd"),
    LIVE_PROFILE_CASES,
)
def test_scale_170_live_profiles_are_exact(
    monkeypatch, profile, key_name, provider, model, concurrency, cap_usd,
):
    monkeypatch.setenv(key_name, "test-key-only")
    config = load_config(profile)

    report = validate_llm_config(config, raise_on_error=False)

    assert report["ready"], report["errors"]
    assert report["warnings"] == []
    assert report["routed_providers"] == [provider]
    assert report["route_contract"] == {
        "enforced": True,
        "provider": provider,
        "model": model,
        "scope": "all_gateway_routes",
    }
    assert config["population"]["size"] == 170
    assert config["living_world"]["core_agents"] == 100
    assert config["llm"]["concurrency"] == concurrency
    assert config["budget"]["cap_usd"] == cap_usd
    assert config["conversations"]["coverage_first"] is True
    assert config["checkpoint_every"] == 7
    assert config["checkpoint_keep_last"] == 4
    assert {
        (route["provider"], route["model"])
        for route in config["llm"]["routes"].values()
    } == {(provider, model)}


@pytest.mark.parametrize(
    ("profile", "key_name"),
    [(case[0], case[1]) for case in LIVE_PROFILE_CASES],
)
def test_scale_170_live_profiles_fail_closed_without_credentials(
    monkeypatch, profile, key_name,
):
    monkeypatch.delenv(key_name, raising=False)

    report = validate_llm_config(load_config(profile), raise_on_error=False)

    assert not report["ready"]
    assert report["errors"]


def test_scale_170_profiles_enable_resource_guardrails():
    for profile in (REHEARSAL, MINIMAX, DEEPSEEK):
        guard = load_config(profile)["resource_guard"]
        assert guard["enabled"] is True
        assert guard["min_available_memory_gb"] == 8
        assert guard["consecutive_breaches"] == 3


def test_scale_170_deepseek_profile_identifies_the_documented_model_version():
    config = load_config(DEEPSEEK)

    assert config["llm"]["providers"]["deepseek"][
        "documented_model_version"
    ] == "DeepSeek-V4-Flash-0731"


def test_scale_170_minimax_disables_thinking_for_bounded_json_contracts():
    config = load_config(MINIMAX)

    defaults = config["llm"]["providers"]["minimax"]["request_defaults"]

    assert defaults["thinking"] == {"type": "disabled"}


def test_scale_170_rehearsal_banks_match_every_deposit_currency(tmp_path):
    config = load_config(REHEARSAL)
    store, world, _run_id = open_run(config, None, None, data_dir=tmp_path)
    try:
        mismatches = [dict(row) for row in store.query(
            "SELECT a.id AS account_id,a.currency_code,b.id AS bank_id,"
            "b.currency_code AS bank_currency,e.currency_code AS equity_currency "
            "FROM accounts a JOIN banks b ON b.id=a.bank_id "
            "JOIN accounts e ON e.id=b.equity_account_id "
            "WHERE a.kind='savings' AND (a.currency_code<>b.currency_code "
            "OR a.currency_code<>e.currency_code) ORDER BY a.id"
        )]
        assert mismatches == []

        asyncio.run(world.step())
        ok, diagnostic = world.economy.ledger.reconcile()
        assert ok, diagnostic
    finally:
        world.close()


def test_scale_170_seven_tick_conversation_budget_covers_every_agent(tmp_path):
    config = load_config(REHEARSAL)
    store, world, _run_id = open_run(config, None, None, data_dir=tmp_path)
    try:
        eligible = {
            int(row["id"])
            for row in store.query("SELECT id FROM agents WHERE alive=1")
        }
        covered: set[int] = set()
        pairs_per_tick = int(config["budget"]["conversation_pairs"])

        for tick in range(1, 8):
            pairs = world.conversations._sample_pairs(tick, pairs_per_tick)
            assert len(pairs) == pairs_per_tick
            for a_id, b_id in pairs:
                covered.update((a_id, b_id))
                store.insert(
                    "conversations",
                    tick=tick,
                    participant_ids=json.dumps([a_id, b_id]),
                    topic="coverage regression",
                )

        assert covered == eligible
    finally:
        world.close()
