from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
from pathlib import Path

import pytest

from engine.checkpoint_manifest import finalize_sqlite_artifact
from llm.readiness import validate_llm_config
from run import open_run
from run import replay_headless
from run_config import load_config
from world.replay_verify import verify_replay


ROOT = Path(__file__).resolve().parents[1]
REHEARSAL = ROOT / "runs" / "scale-270-rehearsal.yaml"
MINIMAX = ROOT / "runs" / "scale-270-minimax-live.yaml"
DEEPSEEK = ROOT / "runs" / "scale-270-deepseek-live.yaml"
SCALE_170_MINIMAX = ROOT / "runs" / "scale-170-minimax-live.yaml"
SCALE_170_DEEPSEEK = ROOT / "runs" / "scale-170-deepseek-live.yaml"
SQLITE_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")
EXPECTED_LIVE_PURPOSES = (
    "central_banker",
    "citizen",
    "competition_regulator",
    "conversation",
    "credit_officer",
    "decision",
    "editor",
    "exchange",
    "executive",
    "founder",
    "gov_official",
    "labor_regulator",
    "lawyer",
    "legislator_house",
    "legislator_senate",
    "lobbyist",
    "memory",
    "newsroom",
    "oracle",
    "regulator",
    "reporter",
    "vc_partner",
)
LIVE_CASES = (
    (
        MINIMAX,
        SCALE_170_MINIMAX,
        "MINIMAX_API_KEY",
        "minimax",
        "MiniMax-M3",
        3,
        0.50,
    ),
    (
        DEEPSEEK,
        SCALE_170_DEEPSEEK,
        "DEEPSEEK_API_KEY",
        "deepseek",
        "deepseek-v4-flash",
        6,
        0.20,
    ),
)


def _region_counts(store) -> dict[str, int]:
    return {
        str(row["region_key"]): int(row["n"])
        for row in store.query(
            "SELECT r.region_key,COUNT(a.id) AS n FROM regions r "
            "LEFT JOIN agents a ON a.region_id=r.id "
            "GROUP BY r.id ORDER BY r.id"
        )
    }


def _artifact_manifest(root: Path) -> tuple[tuple[object, ...], ...]:
    root = root.resolve()
    entries: dict[str, tuple[object, ...]] = {}
    databases: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        body = path.read_bytes()
        entries[relative] = (
            relative, True, len(body), hashlib.sha256(body).hexdigest(),
        )
        if path.suffix == ".db":
            databases.append(path)
    for database in databases:
        for suffix in SQLITE_SIDECAR_SUFFIXES:
            sidecar = Path(f"{database}{suffix}")
            relative = sidecar.relative_to(root).as_posix()
            entries.setdefault(relative, (relative, False, 0, None))
    return tuple(entries[key] for key in sorted(entries))


def _set_source_tree_modes(root: Path, *, writable: bool) -> None:
    directory_mode = 0o700 if writable else 0o500
    file_mode = 0o600 if writable else 0o400
    directories = [root, *sorted(
        (path for path in root.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
    )]
    if writable:
        for directory in directories:
            directory.chmod(directory_mode)
    for path in root.rglob("*"):
        if path.is_file():
            path.chmod(file_mode)
    if not writable:
        for directory in reversed(directories):
            directory.chmod(directory_mode)


def test_scale_270_rehearsal_is_exact():
    """Catch drift in the maintained provider-free scale contract."""
    config = load_config(REHEARSAL)

    assert config["seed"] == 42
    assert config["engine_semantics_version"] == 7
    assert config["population"] == {
        "baseline_citizens_core": False,
        "size": 270,
    }
    assert {
        key: config["banks"][key]
        for key in ("count", "names")
    } == {
        "count": 3,
        "names": [
            "Northstar Bank",
            "Ironvale Industrial Bank",
            "Suncoast Exchange Bank",
        ],
    }
    assert {
        key: config["living_world"][key]
        for key in (
            "enabled",
            "core_agents",
            "promotion_interval_ticks",
            "require_trade_contract",
            "fx_market_maker_inventory",
            "regions",
        )
    } == {
        "enabled": True,
        "core_agents": 100,
        "promotion_interval_ticks": 30,
        "require_trade_contract": True,
        "fx_market_maker_inventory": 100_000_000,
        "regions": [
            {
                "key": "northstar",
                "name": "Northstar Federation",
                "currency": "NSD",
                "population": 182,
                "specialization": ["technology", "services", "finance"],
                "x": 0.25,
                "y": 0.35,
                "legal_ruleset": "northstar-us-inspired-1.0",
                "rate_ppm": 1_000_000,
            },
            {
                "key": "ironvale",
                "name": "Ironvale Union",
                "currency": "IVC",
                "population": 70,
                "specialization": ["manufacturing", "energy"],
                "x": 0.72,
                "y": 0.28,
                "legal_ruleset": "external-lite-1.0",
                "rate_ppm": 750_000,
            },
            {
                "key": "suncoast",
                "name": "Suncoast Republic",
                "currency": "SCD",
                "population": 56,
                "specialization": ["agriculture", "logistics", "tourism"],
                "x": 0.55,
                "y": 0.78,
                "legal_ruleset": "external-lite-1.0",
                "rate_ppm": 1_200_000,
            },
        ],
    }
    assert {
        key: config["conversations"][key]
        for key in (
            "turns",
            "coverage_first",
            "recent_utterance_limit",
            "similarity_jaccard_threshold",
            "similarity_shingle_threshold",
        )
    } == {
        "turns": 3,
        "coverage_first": True,
        "recent_utterance_limit": 360,
        "similarity_jaccard_threshold": 0.65,
        "similarity_shingle_threshold": 0.65,
    }
    assert {
        key: config["budget"][key]
        for key in (
            "cap_usd",
            "oracle_reserve_usd",
            "report_reserve_usd",
            "conversation_pairs",
        )
    } == {
        "cap_usd": 200.0,
        "oracle_reserve_usd": 10.0,
        "report_reserve_usd": 0.25,
        "conversation_pairs": 25,
    }
    assert config["checkpoint_every"] == 7
    assert config["checkpoint_keep_last"] == 4
    assert config["speed_delay_s"] == 0.0
    assert config["resource_guard"] == {
        "enabled": True,
        "sample_interval_s": 2,
        "max_cpu_percent": 95,
        "max_memory_percent": 85,
        "min_available_memory_gb": 8,
        "max_swap_percent": 80,
        "consecutive_breaches": 3,
    }
    assert config["llm"]["local_currency_action_surfaces"] is True
    assert config["llm"]["default_route"] == {
        "provider": "scripted",
        "model": "scripted",
    }
    assert config["llm"]["routes"] == {}
    assert config["llm"].get("providers", {}) == {}
    assert config["llm"].get("pricing", {}) == {}


def test_scale_270_rehearsal_builds_exact_population(tmp_path):
    """Catch allocator, tier, regional-bank, or Genesis count drift."""
    store, world, _ = open_run(
        load_config(REHEARSAL), None, None, data_dir=tmp_path,
    )
    try:
        assert store.scalar("SELECT COUNT(*) FROM agents") == 308
        assert store.scalar(
            "SELECT COUNT(*) FROM agents WHERE kind='citizen'",
        ) == 272
        assert store.scalar(
            "SELECT COUNT(*) FROM agents WHERE kind='staff'",
        ) == 36
        assert store.scalar(
            "SELECT COUNT(*) FROM agents WHERE population_tier='core'",
        ) == 100
        assert store.scalar(
            "SELECT COUNT(*) FROM agents WHERE population_tier='periphery'",
        ) == 208
        assert _region_counts(store) == {
            "northstar": 184,
            "ironvale": 69,
            "suncoast": 55,
        }
        assert store.query(
            "SELECT a.id FROM accounts a JOIN banks b ON b.id=a.bank_id "
            "JOIN accounts e ON e.id=b.equity_account_id "
            "WHERE a.kind='savings' AND (a.currency_code<>b.currency_code "
            "OR a.currency_code<>e.currency_code) ORDER BY a.id",
        ) == []
        ok, diagnostic = world.economy.ledger.reconcile()
        assert ok, diagnostic
    finally:
        world.close()


def test_scale_270_seven_tick_budget_covers_every_agent(tmp_path):
    """Catch a pair budget too small to cover all 308 living agents."""
    config = load_config(REHEARSAL)
    store, world, _ = open_run(config, None, None, data_dir=tmp_path)
    try:
        eligible = {
            int(row["id"])
            for row in store.query("SELECT id FROM agents WHERE alive=1")
        }
        covered: set[int] = set()

        for tick in range(1, 8):
            pairs = world.conversations._sample_pairs(
                tick, config["budget"]["conversation_pairs"],
            )
            assert len(pairs) == 25
            for first_id, second_id in pairs:
                assert first_id != second_id
                covered.update((first_id, second_id))
                store.insert(
                    "conversations",
                    tick=tick,
                    participant_ids=json.dumps([first_id, second_id]),
                    topic="scale-270 coverage regression",
                )

        assert covered == eligible
    finally:
        world.close()


def test_scale_270_replay_uses_distinct_read_only_source_root(
    tmp_path, monkeypatch,
):
    """Catch source writes or replay output created beside source evidence."""
    source_dir = tmp_path / "source"
    replay_dir = tmp_path / "replay"
    config = load_config(REHEARSAL)
    config["checkpoint_dir"] = str(source_dir / "checkpoints")
    config["report_dir"] = str(source_dir / "reports")
    source_store, source_world, source_run_id = open_run(
        config, None, None, data_dir=source_dir,
    )
    source_path = Path(source_store.path)
    try:
        asyncio.run(source_world.step())
        assert source_world.checkpoint(1, reason="replay regression")
    finally:
        source_world.close()
    finalize_sqlite_artifact(source_path)

    before = _artifact_manifest(source_dir)
    assert before
    assert not any(
        entry[1]
        for entry in before
        if str(entry[0]).endswith(SQLITE_SIDECAR_SUFFIXES)
    )
    _set_source_tree_modes(source_dir, writable=False)

    real_connect = sqlite3.connect

    def guarded_connect(database, *args, **kwargs):
        raw_database = os.fspath(database)
        if str(source_dir.resolve()) in raw_database:
            assert kwargs.get("uri") is True
            assert "mode=ro" in raw_database
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", guarded_connect)
    replay_world = None
    try:
        replay_store, replay_world, _ = open_run(
            {},
            None,
            source_run_id,
            data_dir=replay_dir,
            replay_source_dir=source_dir,
        )
        assert Path(replay_store.path).parent == replay_dir
        asyncio.run(replay_headless(replay_world, 1))
        proof = verify_replay(source_path, replay_store.path)
        assert proof["exact"], proof["differences"]
        assert proof["differences"] == []
        assert proof["source_tick"] == proof["replay_tick"] == 1
        assert proof["source_hash"] == proof["replay_hash"]
        replay_world.close()
        replay_world = None
        assert _artifact_manifest(source_dir) == before
    finally:
        if replay_world is not None:
            replay_world.close()
        _set_source_tree_modes(source_dir, writable=True)


def test_replay_source_and_output_roots_must_not_overlap(tmp_path):
    """Catch an output root capable of placing writes beneath the source."""
    source_dir = tmp_path / "source"
    source_dir.mkdir()

    with pytest.raises(ValueError, match="must not overlap"):
        open_run(
            {},
            None,
            "recorded-run",
            data_dir=source_dir / "replay-output",
            replay_source_dir=source_dir,
        )


def test_replay_run_id_must_not_escape_explicit_source_root(tmp_path):
    """Catch path traversal from an explicit immutable source root."""
    source_dir = tmp_path / "source"
    replay_dir = tmp_path / "replay"
    source_dir.mkdir()

    with pytest.raises(ValueError, match="escapes its source root"):
        open_run(
            {},
            None,
            "../outside",
            data_dir=replay_dir,
            replay_source_dir=source_dir,
        )


@pytest.mark.parametrize(
    (
        "profile",
        "reference_profile",
        "key_name",
        "provider",
        "model",
        "concurrency",
        "cap_usd",
    ),
    LIVE_CASES,
)
def test_scale_270_live_profiles_are_exact(
    monkeypatch,
    profile,
    reference_profile,
    key_name,
    provider,
    model,
    concurrency,
    cap_usd,
):
    """Catch route, provider, pricing, limit, or scale drift in paid canaries."""
    monkeypatch.setenv(key_name, "test-key-only")
    config = load_config(profile)
    reference = load_config(reference_profile)

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
    assert config["seed"] == 42
    assert config["engine_semantics_version"] == 7
    assert config["population"] == {
        "baseline_citizens_core": False,
        "size": 270,
    }
    assert config["living_world"]["core_agents"] == 100
    assert [
        region["population"] for region in config["living_world"]["regions"]
    ] == [182, 70, 56]
    assert config["conversations"]["turns"] == 3
    assert config["conversations"]["coverage_first"] is True
    assert config["budget"] == {
        **reference["budget"],
        "cap_usd": cap_usd,
        "oracle_reserve_usd": 0.0,
        "report_reserve_usd": 0.0,
        "conversation_pairs": 25,
    }
    assert config["checkpoint_every"] == 7
    assert config["checkpoint_keep_last"] == 4
    assert config["speed_delay_s"] == 0.0
    assert config["resource_guard"] == reference["resource_guard"]
    assert config["reports"]["narrative_max_tokens"] == 1600
    assert config["llm"] == reference["llm"]
    assert config["llm"]["concurrency"] == concurrency
    assert config["llm"]["providers"] == {
        provider: reference["llm"]["providers"][provider],
    }
    expected_route = {"provider": provider, "model": model}
    assert tuple(sorted(config["llm"]["routes"])) == EXPECTED_LIVE_PURPOSES
    assert config["llm"]["routes"] == {
        purpose: expected_route for purpose in EXPECTED_LIVE_PURPOSES
    }
    assert config["llm"]["pricing"] == reference["llm"]["pricing"]


@pytest.mark.parametrize(
    ("profile", "key_name"),
    [(case[0], case[2]) for case in LIVE_CASES],
)
def test_scale_270_live_profiles_fail_closed_without_credentials(
    monkeypatch, profile, key_name,
):
    """Catch a paid profile that can become ready without its own key."""
    monkeypatch.delenv(key_name, raising=False)

    report = validate_llm_config(
        load_config(profile), raise_on_error=False,
    )

    assert not report["ready"]
    assert report["errors"]
    assert any(key_name in error for error in report["errors"])
