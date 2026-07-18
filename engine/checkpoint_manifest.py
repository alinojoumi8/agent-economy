"""Crash-safe runtime manifests for SQLite world checkpoints."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Any


CHECKPOINT_MANIFEST_VERSION = 1


class SQLiteArtifactError(RuntimeError):
    """A SQLite file could not be reduced to one finalized database artifact."""


def finalize_sqlite_artifact(path: str | Path) -> Path:
    """Checkpoint WAL state and leave one immutable-manifest-ready DB file.

    This is safe only after every writer has released the database.  A
    non-empty sidecar after checkpointing remains fatal because deleting it
    could discard committed evidence.
    """
    database = Path(path).resolve()
    if not database.is_file():
        raise SQLiteArtifactError(f"run database not found: {database}")
    connection = sqlite3.connect(str(database), isolation_level=None)
    try:
        connection.execute("PRAGMA busy_timeout = 5000")
        checkpoint = connection.execute(
            "PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if checkpoint is None or int(checkpoint[0]) != 0:
            raise SQLiteArtifactError(
                f"could not checkpoint SQLite WAL for {database}")
        mode = str(connection.execute(
            "PRAGMA journal_mode = DELETE").fetchone()[0]).lower()
        if mode != "delete":
            raise SQLiteArtifactError(
                f"could not finalize SQLite journal mode for {database}")
    except sqlite3.Error as exc:
        raise SQLiteArtifactError(
            f"could not finalize SQLite artifact {database}: {exc}") from exc
    finally:
        connection.close()
    for sidecar in (Path(f"{database}-wal"), Path(f"{database}-shm")):
        if sidecar.exists():
            if sidecar.stat().st_size:
                raise SQLiteArtifactError(
                    f"non-empty SQLite sidecar remains after finalization: {sidecar}")
            sidecar.unlink()
    return database


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(
        value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        + "\n").encode("utf-8")


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def checkpoint_manifest_path(database_path: str | Path) -> Path:
    database = Path(database_path).resolve()
    return Path(f"{database}.manifest.json")


def sqlite_schema_evidence(connection: sqlite3.Connection) -> dict:
    rows = [dict(row) for row in connection.execute(
        "SELECT type,name,tbl_name,COALESCE(sql,'') AS sql "
        "FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' "
        "ORDER BY type,name,tbl_name"
    ).fetchall()]
    return {
        "objects": len(rows),
        "tables": sum(1 for row in rows if row["type"] == "table"),
        "sha256": canonical_sha256(rows),
    }


def _json_value(raw: Any) -> Any:
    if not isinstance(raw, str):
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def checkpoint_state_binding(connection: sqlite3.Connection) -> dict:
    meta = connection.execute("SELECT * FROM run_meta WHERE id=1").fetchone()
    if meta is None:
        raise ValueError("checkpoint has no run_meta row")
    config = _json_value(meta["config_json"])
    phase_state = _json_value(meta["phase_state_json"])
    prng_state = _json_value(meta["prng_state"])
    lifecycle_prng_state = _json_value(meta["lifecycle_prng_state"])
    governor = _json_value(meta["governor_json"])
    return {
        "run_id": str(meta["run_id"]),
        "seed": int(meta["seed"]),
        "schema_version": int(meta["schema_version"]),
        "config_sha256": canonical_sha256(config),
        "tick": int(meta["tick"]),
        "status": str(meta["status"]),
        "phase": meta["phase"],
        "active_tick": meta["active_tick"],
        "next_phase": meta["next_phase"],
        "phase_state_sha256": canonical_sha256(phase_state),
        "prng_state_sha256": canonical_sha256(prng_state),
        "lifecycle_prng_state_sha256": canonical_sha256(
            lifecycle_prng_state),
        "governor_sha256": canonical_sha256(governor),
        "participant_influenced": int(meta["participant_influenced"] or 0),
        "parent_run_id": meta["parent_run_id"],
        "fork_tick": meta["fork_tick"],
    }


def _table_count(connection: sqlite3.Connection, table: str) -> int:
    return int(connection.execute(
        f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])


def checkpoint_core_evidence(
        connection: sqlite3.Connection, *, checkpoint_tick: int) -> dict:
    core_tables = (
        "agents", "firms", "banks", "accounts", "transactions",
        "ledger_entries", "metrics", "events",
    )
    counts = {table: _table_count(connection, table) for table in core_tables}
    genesis_rows = connection.execute(
        "SELECT tick,payload_json FROM events WHERE kind='genesis' ORDER BY id"
    ).fetchall()
    genesis_payloads = [
        _json_value(row["payload_json"]) for row in genesis_rows]
    metric_bounds = connection.execute(
        "SELECT MIN(tick),MAX(tick),"
        "SUM(CASE WHEN tick>? THEN 1 ELSE 0 END) FROM metrics",
        (checkpoint_tick,)).fetchone()
    event_bounds = connection.execute(
        "SELECT MIN(tick),MAX(tick),"
        "SUM(CASE WHEN tick>? THEN 1 ELSE 0 END) FROM events",
        (checkpoint_tick,)).fetchone()
    account_mismatches = int(connection.execute(
        "SELECT COUNT(*) FROM ("
        "SELECT a.id FROM accounts a LEFT JOIN ("
        "SELECT account_id,SUM(delta_cents) AS total FROM ledger_entries "
        "GROUP BY account_id) e ON e.account_id=a.id "
        "WHERE a.balance_cents!=COALESCE(e.total,0))"
    ).fetchone()[0])
    currency_imbalances = int(connection.execute(
        "SELECT COUNT(*) FROM ("
        "SELECT le.txn_id,COALESCE(a.currency_code,'USD') AS currency_code "
        "FROM ledger_entries le JOIN accounts a ON a.id=le.account_id "
        "GROUP BY le.txn_id,COALESCE(a.currency_code,'USD') "
        "HAVING SUM(le.delta_cents)!=0)"
    ).fetchone()[0])
    foreign_key_violations = len(connection.execute(
        "PRAGMA foreign_key_check").fetchall())
    return {
        "counts": counts,
        "genesis_events": len(genesis_rows),
        "genesis_ticks": [int(row["tick"]) for row in genesis_rows],
        "genesis_payloads": genesis_payloads,
        "metric_bounds": {
            "minimum": metric_bounds[0], "maximum": metric_bounds[1],
            "after_checkpoint": int(metric_bounds[2] or 0),
        },
        "event_bounds": {
            "minimum": event_bounds[0], "maximum": event_bounds[1],
            "after_checkpoint": int(event_bounds[2] or 0),
        },
        "ledger": {
            "account_mismatches": account_mismatches,
            "currency_imbalances": currency_imbalances,
            "foreign_key_violations": foreign_key_violations,
        },
    }


def build_checkpoint_manifest(database_path: str | Path) -> dict:
    database = Path(database_path).resolve()
    before_hash = file_sha256(database)
    connection = sqlite3.connect(
        f"{database.as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        quick_check = str(connection.execute(
            "PRAGMA quick_check").fetchone()[0])
        schema = sqlite_schema_evidence(connection)
        state = checkpoint_state_binding(connection)
        core = checkpoint_core_evidence(
            connection, checkpoint_tick=int(state["tick"]))
    finally:
        connection.close()
    after_hash = file_sha256(database)
    if before_hash != after_hash:
        raise RuntimeError("checkpoint changed while its manifest was built")
    return {
        "schema_version": CHECKPOINT_MANIFEST_VERSION,
        "kind": "world_checkpoint_v1",
        "database": str(database),
        "database_sha256": before_hash,
        "quick_check": quick_check,
        "schema": schema,
        "state": state,
        "state_sha256": canonical_sha256(state),
        "core": core,
        "core_sha256": canonical_sha256(core),
    }


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_checkpoint_manifest(database_path: str | Path) -> Path:
    """Persist one canonical manifest beside an already closed checkpoint."""
    database = Path(database_path).resolve()
    target = checkpoint_manifest_path(database)
    encoded = canonical_json_bytes(build_checkpoint_manifest(database))
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        _fsync_directory(target.parent)
    finally:
        temporary.unlink(missing_ok=True)
    return target
