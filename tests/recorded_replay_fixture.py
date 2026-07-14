"""Portable loader for the sanitized fd0adc5dc1 recorded-response fixture."""
from __future__ import annotations

import base64
import copy
import json
import sqlite3
import zlib
from pathlib import Path

from engine.store import Store


FIXTURE_PATH = Path(__file__).parent / "golden" / "fd0adc5dc1.sqlite.json.zlib.b64"
REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_FORMAT_VERSION = 2
SOURCE_RUN_ID = "fd0adc5dc1"
SOURCE_REVISION = "unknown-not-recorded"
SOURCE_ENGINE_SEMANTICS_VERSION = 5
SOURCE_TICKS = 10
RESPONSE_JSON_ALLOWLIST = ("text", "cached_in_tokens")
SANITIZATION_METADATA = {
    "llm_response_json_allowlist": list(RESPONSE_JSON_ALLOWLIST),
    "raw_provider_envelopes_retained": False,
    "removed_fields": ["tables.llm_calls.response_json.raw"],
    "repository_paths": "repo://",
}


def sanitize_recorded_fixture(fixture: dict) -> dict:
    """Return the deterministic, public form of a recorded replay fixture."""
    if not isinstance(fixture, dict) or fixture.get("source_run_id") != SOURCE_RUN_ID:
        raise ValueError("unexpected recorded replay fixture")
    try:
        calls = fixture["tables"]["llm_calls"]
    except (KeyError, TypeError) as exc:
        raise ValueError("recorded replay fixture is missing llm_calls") from exc
    if not isinstance(calls, list):
        raise ValueError("recorded replay fixture llm_calls must be a list")

    sanitized = copy.deepcopy(fixture)
    for row in sanitized["tables"]["llm_calls"]:
        try:
            response = json.loads(row["response_json"])
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError("recorded replay fixture has invalid response_json") from exc
        if not isinstance(response, dict):
            raise ValueError("recorded replay fixture response_json must be an object")
        missing = [key for key in RESPONSE_JSON_ALLOWLIST if key not in response]
        if missing:
            raise ValueError(
                "recorded replay fixture response_json is missing " + ", ".join(missing))
        if not isinstance(response["text"], str):
            raise ValueError("recorded replay fixture response text must be a string")
        cached_in_tokens = response["cached_in_tokens"]
        if (not isinstance(cached_in_tokens, int) or isinstance(cached_in_tokens, bool)
                or cached_in_tokens < 0):
            raise ValueError(
                "recorded replay fixture cached_in_tokens must be a non-negative integer")
        public_response = {
            key: response[key] for key in RESPONSE_JSON_ALLOWLIST
        }
        row["response_json"] = json.dumps(
            public_response,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    sanitized.update({
        "fixture_format_version": FIXTURE_FORMAT_VERSION,
        "source_run_id": SOURCE_RUN_ID,
        "source_revision": SOURCE_REVISION,
        "source_engine_semantics_version": SOURCE_ENGINE_SEMANTICS_VERSION,
        "source_ticks": SOURCE_TICKS,
        "sanitization": copy.deepcopy(SANITIZATION_METADATA),
    })
    return sanitized


def encode_recorded_fixture(fixture: dict) -> str:
    """Encode a fixture deterministically after applying public sanitization."""
    payload = json.dumps(
        sanitize_recorded_fixture(fixture),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.b64encode(zlib.compress(payload, level=9)).decode("ascii") + "\n"


def load_recorded_fixture() -> dict:
    compressed = base64.b64decode(FIXTURE_PATH.read_text(encoding="ascii"))
    fixture = json.loads(zlib.decompress(compressed).decode("utf-8"))
    if fixture != sanitize_recorded_fixture(fixture):
        raise ValueError("recorded replay fixture is not in canonical public form")
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
