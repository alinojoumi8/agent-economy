"""Canonical, table-by-table proof that a recorded run replayed exactly."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any


# Metadata and checkpoint paths are operational, not simulated world state.
EXCLUDED_TABLES = {
    "run_meta", "checkpoints", "acceptance_checkpoints",
    "participant_control", "participant_actions",
}
IGNORED_COLUMNS = {"created_at", "updated_at"}
LOGICAL_ROW_TABLES = {"beliefs", "llm_calls", "memories"}
SURROGATE_ID_COLUMNS = {
    **{table: {"id"} for table in LOGICAL_ROW_TABLES},
    # Operational participant events are intentionally filtered. Their rows
    # shift later event IDs without changing the deterministic event sequence.
    "events": {"id"},
}
IGNORED_EVENT_KINDS = {
    "report_generated", "report_failed",
    "participant_control_acquired", "participant_control_released",
    "participant_action_queued", "participant_action_replaced",
    "participant_action_executed", "participant_action_rejected", "participant_idle",
}
JSON_COLUMNS = {
    "participant_ids", "slant_tags", "source_event_ids",
}


def _connect(path: str | Path) -> sqlite3.Connection:
    resolved = Path(path).resolve()
    uri = f"file:{resolved.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name"
    ).fetchall()
    return [str(row[0]) for row in rows if str(row[0]) not in EXCLUDED_TABLES]


def _canonical_value(column: str, value: Any) -> Any:
    if value is None or isinstance(value, (int, float)):
        return value
    if isinstance(value, bytes):
        return value.hex()
    text = str(value)
    if column.endswith("_json") or column in JSON_COLUMNS:
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            pass
    return text


def _logical_llm_call_references(conn: sqlite3.Connection) -> dict[int, Any]:
    """Index local surrogate IDs by their deterministic LLM call contents."""
    all_columns = [
        str(column[1]) for column in conn.execute('PRAGMA table_info("llm_calls")')]
    if not all_columns:
        return {}
    ignored = IGNORED_COLUMNS | SURROGATE_ID_COLUMNS["llm_calls"]
    identity_columns = [column for column in all_columns if column not in ignored]
    return {
        int(row["id"]): {"llm_call": {
            column: _canonical_value(column, row[column])
            for column in identity_columns
        }}
        for row in conn.execute("SELECT * FROM llm_calls")
    }


def _table_digest(
        conn: sqlite3.Connection, table: str,
        llm_call_references: dict[int, Any]) -> tuple[int, str, bool]:
    all_columns = [str(row[1]) for row in conn.execute(f'PRAGMA table_info("{table}")')]
    ignored = IGNORED_COLUMNS | SURROGATE_ID_COLUMNS.get(table, set())
    columns = [column for column in all_columns if column not in ignored]
    where = ""
    params: tuple[Any, ...] = ()
    if table == "events":
        placeholders = ",".join("?" for _ in IGNORED_EVENT_KINDS)
        where = f" WHERE kind NOT IN ({placeholders})"
        params = tuple(sorted(IGNORED_EVENT_KINDS))
    order = " ORDER BY id" if "id" in all_columns else ""
    selected = ",".join(f'"{column}"' for column in columns)
    rows = conn.execute(f'SELECT {selected} FROM "{table}"{where}{order}', params).fetchall()
    records = []
    references_valid = True
    for row in rows:
        record = {}
        for column in columns:
            if column == "model_call_id":
                call_id = row[column]
                if call_id is None:
                    record[column] = None
                else:
                    key = int(call_id)
                    reference = llm_call_references.get(key)
                    record[column] = (
                        reference if reference is not None
                        else {"dangling_llm_call_id": key})
                    references_valid = references_valid and reference is not None
            else:
                record[column] = _canonical_value(column, row[column])
        records.append(json.dumps(
            record, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False).encode("utf-8"))
    if table in LOGICAL_ROW_TABLES:
        records.sort()
    digest = hashlib.sha256()
    for record in records:
        digest.update(record)
        digest.update(b"\n")
    return len(rows), digest.hexdigest(), references_valid


def verify_replay(source_path: str | Path, replay_path: str | Path) -> dict:
    """Compare every deterministic table and return a machine-readable proof."""
    source = _connect(source_path)
    replay = _connect(replay_path)
    try:
        source_tables = _tables(source)
        replay_tables = _tables(replay)
        names = sorted(set(source_tables) | set(replay_tables))
        results = []
        source_run = source.execute("SELECT run_id, tick FROM run_meta WHERE id=1").fetchone()
        replay_run = replay.execute("SELECT run_id, tick FROM run_meta WHERE id=1").fetchone()
        source_llm_call_references = _logical_llm_call_references(source)
        replay_llm_call_references = _logical_llm_call_references(replay)
        source_total = hashlib.sha256()
        replay_total = hashlib.sha256()
        for name in names:
            if name not in source_tables or name not in replay_tables:
                results.append({
                    "table": name, "exact": False,
                    "source_rows": None if name not in source_tables else 0,
                    "replay_rows": None if name not in replay_tables else 0,
                    "source_hash": None, "replay_hash": None,
                })
                continue
            source_rows, source_hash, source_references_valid = _table_digest(
                source, name, source_llm_call_references)
            replay_rows, replay_hash, replay_references_valid = _table_digest(
                replay, name, replay_llm_call_references)
            exact = (source_rows == replay_rows and source_hash == replay_hash
                     and source_references_valid and replay_references_valid)
            results.append({
                "table": name, "exact": exact,
                "source_rows": source_rows, "replay_rows": replay_rows,
                "source_hash": source_hash, "replay_hash": replay_hash,
            })
            source_total.update(f"{name}:{source_rows}:{source_hash}\n".encode())
            replay_total.update(f"{name}:{replay_rows}:{replay_hash}\n".encode())

        ticks_exact = int(source_run["tick"]) == int(replay_run["tick"])
        return {
            "exact": ticks_exact and all(item["exact"] for item in results),
            "source_run_id": str(source_run["run_id"]),
            "replay_run_id": str(replay_run["run_id"]),
            "source_tick": int(source_run["tick"]),
            "replay_tick": int(replay_run["tick"]),
            "source_hash": source_total.hexdigest(),
            "replay_hash": replay_total.hexdigest(),
            "tables": results,
            "differences": [item["table"] for item in results if not item["exact"]]
                           + ([] if ticks_exact else ["run_meta.tick"]),
        }
    finally:
        source.close()
        replay.close()
