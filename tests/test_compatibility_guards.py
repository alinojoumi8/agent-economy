"""Fail-closed guards for persisted engine and database compatibility."""
from __future__ import annotations

import json
import sqlite3

import pytest

import run as run_module
from engine.schema import SCHEMA_VERSION, SchemaCompatibilityError
from engine.semantics import (
    CURRENT_ENGINE_SEMANTICS_VERSION,
    UnsupportedEngineSemantics,
)
from engine.store import Store
from run import fork_run, open_run
from run_config import load_config


def _stored_run(path, run_id: str, semantics: int) -> None:
    store = Store(str(path))
    store.init_run_meta(
        run_id, 42, {"engine_semantics_version": semantics})
    store.close()


@pytest.mark.parametrize("version", range(1, CURRENT_ENGINE_SEMANTICS_VERSION + 1))
def test_resume_accepts_every_supported_persisted_semantics(tmp_path, version):
    run_id = f"supported-{version}"
    _stored_run(tmp_path / f"{run_id}.db", run_id, version)

    store, world, reopened_id = open_run({}, run_id, None, data_dir=tmp_path)
    try:
        assert reopened_id == run_id
        assert world.engine_semantics_version == version
    finally:
        store.close()


def test_resume_hydrates_terminal_status_and_existing_report(tmp_path):
    run_id = "finished-observatory"
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    report_path = report_dir / f"run_{run_id}_t12.html"
    report_path.write_text("finished", encoding="utf-8")
    store = Store(str(tmp_path / f"{run_id}.db"))
    store.init_run_meta(run_id, 42, {
        "engine_semantics_version": CURRENT_ENGINE_SEMANTICS_VERSION,
        "report_dir": str(report_dir),
    })
    store.set_meta(status="finished", tick=12)
    store.close()

    resumed_store, world, _ = open_run({}, run_id, None, data_dir=tmp_path)
    try:
        assert world.status == "finished"
        assert world.last_report_path == str(report_path)
        assert resumed_store.get_meta()["status"] == "finished"
    finally:
        world.close()


def test_resume_converts_stale_running_marker_to_paused(tmp_path):
    run_id = "interrupted-observatory"
    _stored_run(
        tmp_path / f"{run_id}.db", run_id,
        CURRENT_ENGINE_SEMANTICS_VERSION)
    store = Store(str(tmp_path / f"{run_id}.db"))
    store.set_meta(status="running")
    store.close()

    resumed_store, world, _ = open_run({}, run_id, None, data_dir=tmp_path)
    try:
        assert world.status == "paused"
        assert resumed_store.get_meta()["status"] == "paused"
    finally:
        world.close()


@pytest.mark.parametrize(
    ("persisted_status", "expected_status"),
    [("paused", "paused"), ("running", "paused")],
)
def test_resume_restores_persisted_status_and_fails_safe_running_state(
        tmp_path, persisted_status, expected_status):
    run_id = f"status-{persisted_status}"
    _stored_run(
        tmp_path / f"{run_id}.db",
        run_id,
        CURRENT_ENGINE_SEMANTICS_VERSION,
    )
    persisted = Store(str(tmp_path / f"{run_id}.db"))
    persisted.set_meta(status=persisted_status)
    persisted.commit()
    persisted.close()

    store, world, _ = open_run({}, run_id, None, data_dir=tmp_path)
    try:
        assert world.status == expected_status
        assert store.get_meta()["status"] == expected_status
    finally:
        store.close()


def test_resume_profile_can_only_tighten_operational_resource_limits(
        tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek")
    monkeypatch.setenv("KIMI_API_KEY", "test-kimi")
    monkeypatch.setenv("MINIMAX_API_KEY", "test-minimax")
    run_id = "resource-safe-resume"
    stored_config = load_config("runs/evolving-live.yaml")
    stored_config["llm"]["max_in_flight"] = 10
    stored_config["llm"]["concurrency"] = 10
    stored_config["llm"]["logical_deadline_s"] = 240
    stored_config["llm"]["providers"]["ollama"]["concurrency"] = 2
    stored_config["llm"]["providers"]["ollama"]["timeout_s"] = 30
    stored_config["llm"]["citizen_model_cohorts"][0]["primary"]["timeout_s"] = 30
    stored_config["resource_guard"].update({
        "sample_interval_s": 5,
        "max_cpu_percent": 95,
        "max_memory_percent": 90,
        "min_available_memory_gb": 4,
        "max_swap_percent": 90,
        "consecutive_breaches": 3,
    })
    persisted = Store(str(tmp_path / f"{run_id}.db"))
    persisted.init_run_meta(run_id, 42, stored_config)
    persisted.close()

    selected_config = load_config("runs/evolving-live.yaml")
    selected_config["llm"]["provider_retries"] = 1
    store, world, _ = open_run(
        selected_config, run_id, None, data_dir=tmp_path)
    try:
        assert world.config["llm"]["max_in_flight"] == 6
        assert world.config["llm"]["concurrency"] == 6
        assert world.config["llm"]["logical_deadline_s"] == 900
        assert world.config["llm"]["provider_retries"] == 1
        assert world.config["llm"]["providers"]["ollama"]["concurrency"] == 1
        assert world.config["llm"]["providers"]["ollama"]["timeout_s"] == 90
        assert (
            world.config["llm"]["citizen_model_cohorts"][0]["primary"]["timeout_s"]
            == 120
        )
        assert world.config["resource_guard"]["max_memory_percent"] == 70
        assert world.config["resource_guard"]["min_available_memory_gb"] == 20
        assert world.config["resource_guard"]["max_swap_percent"] == 50

        # Provider identity and the canonical persisted run configuration stay
        # authoritative; the tightened limits are runtime-only.
        persisted_config = json.loads(store.get_meta()["config_json"])
        assert persisted_config["llm"]["max_in_flight"] == 10
        assert persisted_config["llm"]["logical_deadline_s"] == 240
        assert persisted_config["llm"]["provider_retries"] == 0
        assert persisted_config["llm"]["providers"]["ollama"]["concurrency"] == 2
        assert persisted_config["llm"]["providers"]["ollama"]["timeout_s"] == 30
        assert (
            persisted_config["llm"]["citizen_model_cohorts"][0]["primary"]["timeout_s"]
            == 30
        )
        assert (
            world.config["llm"]["providers"]["deepseek"]["base_url"]
            == persisted_config["llm"]["providers"]["deepseek"]["base_url"]
        )
        assert (
            world.config["llm"]["tier_routes"]
            == persisted_config["llm"]["tier_routes"]
        )
    finally:
        world.close()


def test_resume_can_adopt_explicit_local_citizenship_without_rewriting_run_config(
        tmp_path):
    run_id = "local-citizenship-resume"
    stored_config = {
        "engine_semantics_version": CURRENT_ENGINE_SEMANTICS_VERSION,
    }
    persisted = Store(str(tmp_path / f"{run_id}.db"))
    persisted.init_run_meta(run_id, 42, stored_config)
    persisted.close()

    selected_config = {
        "external_gateway": {
            "public_join": {
                "enabled": True,
                "world_slug": "local-sandbox",
                "passport_db_path": str(tmp_path / "passports.db"),
            },
        },
    }
    store, world, _ = open_run(
        selected_config, run_id, None, data_dir=tmp_path)
    try:
        assert world.config["external_gateway"]["public_join"] == (
            selected_config["external_gateway"]["public_join"])
        persisted_config = json.loads(store.get_meta()["config_json"])
        assert "external_gateway" not in persisted_config
    finally:
        world.close()


def test_evolving_live_profile_enables_the_local_passport_pages():
    config = load_config("runs/evolving-live.yaml")

    assert config["external_gateway"]["enabled"] is True
    assert config["external_gateway"]["public_join"] == {
        "enabled": True,
        "world_slug": "local-sandbox",
        "world_name": "Agent Economy Live World",
        "tenant_id": "local:local-sandbox",
        "seat_limit": 5,
        "max_passports_per_owner": 3,
        "local_claim_enabled": True,
        "passport_db_path": "data/control-plane/agent-passports.db",
        "claim_hours": 24,
    }


@pytest.mark.parametrize(
    "version", [-1, 0, CURRENT_ENGINE_SEMANTICS_VERSION + 1, 999])
def test_fresh_run_rejects_unsupported_semantics_before_creating_database(
        tmp_path, version):
    with pytest.raises(UnsupportedEngineSemantics, match="engine_semantics_version"):
        open_run(
            {"engine_semantics_version": version}, None, None,
            data_dir=tmp_path)

    assert list(tmp_path.glob("*.db")) == []


def test_resume_and_replay_reject_unsupported_stored_semantics(tmp_path):
    run_id = "unsupported-stored"
    source_path = tmp_path / f"{run_id}.db"
    _stored_run(source_path, run_id, CURRENT_ENGINE_SEMANTICS_VERSION + 1)

    supported = rf"supports 1-{CURRENT_ENGINE_SEMANTICS_VERSION}"
    with pytest.raises(UnsupportedEngineSemantics, match=supported):
        open_run({}, run_id, None, data_dir=tmp_path)
    with pytest.raises(UnsupportedEngineSemantics, match=supported):
        open_run({}, None, run_id, data_dir=tmp_path)

    assert sorted(tmp_path.glob("*.db")) == [source_path]


@pytest.mark.parametrize(
    ("stored_version", "upgrade_version"),
    [
        (CURRENT_ENGINE_SEMANTICS_VERSION + 1, None),
        (CURRENT_ENGINE_SEMANTICS_VERSION, CURRENT_ENGINE_SEMANTICS_VERSION + 1),
    ],
)
def test_fork_rejects_unsupported_stored_or_upgrade_semantics_and_removes_copy(
        tmp_path, monkeypatch, stored_version, upgrade_version):
    source = tmp_path / "checkpoint.db"
    _stored_run(source, "parent", stored_version)
    monkeypatch.setattr(run_module, "new_run_id", lambda: "rejected-fork")

    with pytest.raises(SystemExit, match="engine_semantics_version"):
        fork_run(
            str(source), data_dir=tmp_path,
            upgrade_semantics=upgrade_version)

    assert not (tmp_path / "rejected-fork.db").exists()


def test_store_rejects_future_schema_before_running_migrations(tmp_path):
    path = tmp_path / "future.db"
    store = Store(str(path))
    store.init_run_meta(
        "future", 42,
        {"engine_semantics_version": CURRENT_ENGINE_SEMANTICS_VERSION})
    # PERFORMANCE_SQL rebuilds this cache on every compatible Store open. The
    # sentinel proves a future database is rejected before that first write.
    store.execute(
        "INSERT INTO account_ledger_totals(account_id,total_cents) VALUES (?,?)",
        (987_654, 321))
    store.set_meta(schema_version=SCHEMA_VERSION + 1)
    store.close()

    with pytest.raises(SchemaCompatibilityError, match="newer than this binary"):
        Store(str(path))

    conn = sqlite3.connect(path)
    try:
        assert conn.execute(
            "SELECT schema_version FROM run_meta WHERE id=1").fetchone()[0] == (
                SCHEMA_VERSION + 1)
        assert conn.execute(
            "SELECT total_cents FROM account_ledger_totals WHERE account_id=987654"
        ).fetchone()[0] == 321
    finally:
        conn.close()

    # A failed constructor must not retain a Windows file lock.
    path.unlink()


def test_store_still_upgrades_an_older_supported_schema_marker(tmp_path):
    path = tmp_path / "older.db"
    store = Store(str(path))
    store.init_run_meta(
        "older", 42,
        {"engine_semantics_version": CURRENT_ENGINE_SEMANTICS_VERSION})
    store.set_meta(schema_version=SCHEMA_VERSION - 1)
    store.close()

    reopened = Store(str(path))
    try:
        assert int(reopened.get_meta()["schema_version"]) == SCHEMA_VERSION
    finally:
        reopened.close()


@pytest.mark.parametrize("invalid_version", [11.5, "not-a-version"])
def test_store_rejects_malformed_schema_markers(tmp_path, invalid_version):
    path = tmp_path / "malformed.db"
    store = Store(str(path))
    store.init_run_meta(
        "malformed", 42,
        {"engine_semantics_version": CURRENT_ENGINE_SEMANTICS_VERSION})
    store.set_meta(schema_version=invalid_version)
    store.close()

    with pytest.raises(SchemaCompatibilityError, match="invalid schema_version"):
        Store(str(path))
