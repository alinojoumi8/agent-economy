"""Portable loader for the sanitized fd0adc5dc1 recorded-response fixture."""
from __future__ import annotations

import base64
import json
import sqlite3
import zlib
from pathlib import Path

from engine.store import Store


FIXTURE_PATH = Path(__file__).parent / "golden" / "fd0adc5dc1.sqlite.json.zlib.b64"
REPO_ROOT = Path(__file__).resolve().parents[1]


def load_recorded_fixture() -> dict:
    compressed = base64.b64decode(FIXTURE_PATH.read_text(encoding="ascii"))
    fixture = json.loads(zlib.decompress(compressed).decode("utf-8"))
    if fixture.get("source_run_id") != "fd0adc5dc1":
        raise ValueError("unexpected recorded replay fixture")
    return fixture


def restore_recorded_source(path: Path) -> Path:
    """Restore fixture rows without firing economic balance-cache triggers."""
    fixture = load_recorded_fixture()
    store = Store(str(path))
    conn = store.conn
    trigger_names = [str(row[0]) for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger'")]
    for name in trigger_names:
        conn.execute(f'DROP TRIGGER "{name}"')
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("BEGIN IMMEDIATE")
    try:
        for table, rows in fixture["tables"].items():
            conn.execute(f'DELETE FROM "{table}"')
            if not rows:
                continue
            columns = list(rows[0])
            quoted = ",".join(f'"{column}"' for column in columns)
            placeholders = ",".join("?" for _ in columns)
            conn.executemany(
                f'INSERT INTO "{table}" ({quoted}) VALUES ({placeholders})',
                [[_portable_value(table, column, row.get(column))
                  for column in columns] for row in rows])
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        store.close()

    # Reopening re-applies the checked-in idempotent schema and recreates the
    # triggers removed for the data-only restore.
    Store(str(path)).close()
    with sqlite3.connect(path) as check:
        if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("recorded replay fixture failed SQLite integrity check")
    return path


def _portable_value(table: str, column: str, value):
    """Rehydrate repository-relative fixture provenance for the host OS."""
    if (table == "dataset_manifests" and column == "snapshot_path"
            and isinstance(value, str) and value.startswith("repo://")):
        # Split on the fixture's canonical separator instead of trusting a
        # platform-specific absolute path from recorded data.
        candidate = REPO_ROOT.joinpath(*value.removeprefix("repo://").split("/")).resolve()
        if not candidate.is_relative_to(REPO_ROOT):
            raise ValueError("portable fixture path escapes repository root")
        return str(candidate)
    return value
