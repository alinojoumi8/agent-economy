"""Fail-closed guards for persisted engine and database compatibility."""
from __future__ import annotations

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
