from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from engine.store import ReadOnlyReplaySnapshot, open_read_only_connection
from run import open_run

from .recorded_replay_fixture import SOURCE_RUN_ID, restore_recorded_source


def _source_state(path: Path) -> tuple[str, int, tuple[tuple[str, str], ...]]:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    conn = open_read_only_connection(str(path))
    try:
        version = int(conn.execute(
            "SELECT schema_version FROM run_meta WHERE id=1").fetchone()[0])
        schema = tuple(
            (str(row[0]), str(row[1]))
            for row in conn.execute(
                "SELECT type,name FROM sqlite_master "
                "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name")
        )
        return digest, version, schema
    finally:
        conn.close()


def test_replay_source_is_not_initialized_migrated_or_left_open(tmp_path):
    source_path = restore_recorded_source(tmp_path / f"{SOURCE_RUN_ID}.db")

    # Model a recorded older source. Opening it through the normal Store path
    # would run schema initialization, restore this table, and advance the
    # schema marker before replay had even started.
    setup = sqlite3.connect(source_path)
    try:
        setup.execute("DROP TABLE participant_actions")
        setup.execute("UPDATE run_meta SET schema_version=10 WHERE id=1")
        setup.commit()
        setup.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        setup.close()

    before = _source_state(source_path)
    assert before[1] == 10
    assert ("table", "participant_actions") not in before[2]

    replay_store, replay_world, _ = open_run(
        {}, None, SOURCE_RUN_ID, data_dir=tmp_path)
    gateway = replay_world.gateway
    try:
        assert gateway.replay_conn is not None
        assert _source_state(source_path) == before
    finally:
        replay_world.close()

    assert gateway.replay_conn is None
    replay_world.close()  # teardown is deliberately idempotent

    # Windows refuses both operations while SQLite still owns the source file.
    moved = source_path.with_suffix(".moved")
    source_path.replace(moved)
    moved.replace(source_path)
    assert replay_store._closed


def test_read_only_replay_connection_sees_committed_wal_rows(tmp_path):
    source_path = tmp_path / "active-source.db"
    writer = sqlite3.connect(source_path)
    try:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("CREATE TABLE recorded_calls (id INTEGER PRIMARY KEY, text TEXT)")
        writer.commit()
        writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")

        writer.execute("INSERT INTO recorded_calls(text) VALUES ('committed in wal')")
        writer.commit()
        assert source_path.with_name(source_path.name + "-wal").stat().st_size > 0

        reader = open_read_only_connection(str(source_path))
        try:
            row = reader.execute(
                "SELECT text FROM recorded_calls WHERE id=1").fetchone()
            assert row is not None and row[0] == "committed in wal"
        finally:
            reader.close()
    finally:
        writer.close()


def test_private_replay_snapshot_releases_and_freezes_source(tmp_path):
    source_path = tmp_path / "recorded-source.db"
    writer = sqlite3.connect(source_path)
    try:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("CREATE TABLE recorded_calls (id INTEGER PRIMARY KEY, text TEXT)")
        writer.execute("INSERT INTO recorded_calls(text) VALUES ('recorded')")
        writer.commit()
        writer.close()

        snapshot = ReadOnlyReplaySnapshot(str(source_path))
        try:
            assert snapshot.conn is not None
            assert snapshot.conn.execute(
                "SELECT text FROM recorded_calls WHERE id=1").fetchone()[0] == "recorded"

            # The source can be rotated while the private replay connection is
            # still live, and later source writes cannot change replay input.
            moved = source_path.with_suffix(".moved")
            source_path.replace(moved)
            moved.replace(source_path)
            later_writer = sqlite3.connect(source_path)
            try:
                later_writer.execute(
                    "INSERT INTO recorded_calls(text) VALUES ('later')")
                later_writer.commit()
            finally:
                later_writer.close()
            assert snapshot.conn.execute(
                "SELECT COUNT(*) FROM recorded_calls").fetchone()[0] == 1
        finally:
            private_path = snapshot.path
            snapshot.close()
            snapshot.close()
        assert private_path is not None and not private_path.exists()
    finally:
        writer.close()
