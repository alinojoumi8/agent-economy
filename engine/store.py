"""Run store: a thin, typed wrapper over one SQLite file per run.

Higher-level logic (ledger, markets, world loop) lives elsewhere; this class owns
connection setup, the append-only `events` spine, and small query helpers so the
rest of the code never writes raw SQL boilerplate.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from .schema import SCHEMA_VERSION, initialize_schema


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path: str, *, create: bool = True):
        self.path = path
        if create:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA synchronous = NORMAL")
        self.conn.execute("PRAGMA busy_timeout = 5000")
        initialize_schema(self.conn)

    # ── raw helpers ──────────────────────────────────────────────────────────
    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, tuple(params))

    def executemany(self, sql: str, seq: Iterable[Iterable[Any]]) -> sqlite3.Cursor:
        return self.conn.executemany(sql, [tuple(p) for p in seq])

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, tuple(params)).fetchall()

    def query_one(self, sql: str, params: Iterable[Any] = ()) -> Optional[sqlite3.Row]:
        return self.conn.execute(sql, tuple(params)).fetchone()

    def scalar(self, sql: str, params: Iterable[Any] = (), default=None):
        row = self.query_one(sql, params)
        if row is None:
            return default
        val = row[0]
        return default if val is None else val

    def insert(self, table: str, **cols) -> int:
        keys = list(cols.keys())
        placeholders = ",".join("?" for _ in keys)
        sql = f"INSERT INTO {table} ({','.join(keys)}) VALUES ({placeholders})"
        cur = self.conn.execute(sql, tuple(cols[k] for k in keys))
        return int(cur.lastrowid)

    def update(self, table: str, id_val: int, **cols) -> None:
        if not cols:
            return
        assigns = ",".join(f"{k}=?" for k in cols)
        params = list(cols.values()) + [id_val]
        self.conn.execute(f"UPDATE {table} SET {assigns} WHERE id=?", params)

    def commit(self) -> None:
        self.conn.commit()

    @contextmanager
    def savepoint(self, name: str):
        safe = "".join(ch for ch in name if ch.isalnum() or ch == "_")
        if not safe:
            raise ValueError("savepoint name must contain an alphanumeric character")
        self.conn.execute(f"SAVEPOINT {safe}")
        try:
            yield
        except BaseException:
            self.conn.execute(f"ROLLBACK TO {safe}")
            self.conn.execute(f"RELEASE {safe}")
            raise
        else:
            self.conn.execute(f"RELEASE {safe}")

    def close(self) -> None:
        try:
            self.conn.commit()
        finally:
            self.conn.close()

    # ── run metadata ─────────────────────────────────────────────────────────
    def init_run_meta(self, run_id: str, seed: int, config: dict,
                      parent_run_id: Optional[str] = None, fork_tick: Optional[int] = None) -> None:
        existing = self.query_one("SELECT id FROM run_meta WHERE id=1")
        now = _utcnow()
        if existing:
            self.conn.execute(
                "UPDATE run_meta SET run_id=?, seed=?, config_json=?, updated_at=? WHERE id=1",
                (run_id, seed, json.dumps(config), now),
            )
        else:
            self.conn.execute(
                "INSERT INTO run_meta (id, run_id, seed, schema_version, config_json, status, "
                "tick, created_at, updated_at, parent_run_id, fork_tick) "
                "VALUES (1,?,?,?,?, 'created', 0, ?, ?, ?, ?)",
                (run_id, seed, SCHEMA_VERSION, json.dumps(config), now, now, parent_run_id, fork_tick),
            )
        self.commit()

    def get_meta(self) -> sqlite3.Row:
        return self.query_one("SELECT * FROM run_meta WHERE id=1")

    def set_meta(self, **cols) -> None:
        cols["updated_at"] = _utcnow()
        assigns = ",".join(f"{k}=?" for k in cols)
        self.conn.execute(f"UPDATE run_meta SET {assigns} WHERE id=1", tuple(cols.values()))

    @property
    def tick(self) -> int:
        return int(self.scalar("SELECT tick FROM run_meta WHERE id=1", default=0))

    @property
    def active_tick(self) -> Optional[int]:
        value = self.scalar("SELECT active_tick FROM run_meta WHERE id=1", default=None)
        return int(value) if value is not None else None

    @property
    def next_phase(self) -> str:
        return str(self.scalar(
            "SELECT next_phase FROM run_meta WHERE id=1", default="NIGHT_CLOSE"))

    # ── events: the append-only spine ────────────────────────────────────────
    def log_event(self, tick: int, kind: str, payload: dict | None = None, *,
                  phase: str | None = None, subject_type: str | None = None,
                  subject_id: int | None = None, importance: float = 1.0) -> int:
        return self.insert(
            "events", tick=tick, phase=phase, kind=kind,
            subject_type=subject_type, subject_id=subject_id, importance=importance,
            payload_json=json.dumps(payload or {}), created_at=_utcnow(),
        )

    def events_for_tick(self, tick: int) -> list[sqlite3.Row]:
        return self.query("SELECT * FROM events WHERE tick=? ORDER BY id", (tick,))

    def recent_events(self, limit: int = 50, min_importance: float = 0.0) -> list[sqlite3.Row]:
        return self.query(
            "SELECT * FROM events WHERE importance >= ? ORDER BY id DESC LIMIT ?",
            (min_importance, limit),
        )

    # ── metrics ──────────────────────────────────────────────────────────────
    def record_metric(self, tick: int, name: str, value: float) -> None:
        self.insert("metrics", tick=tick, name=name, value=float(value))

    def metric_latest(self, name: str, default: float = 0.0) -> float:
        # id DESC tie-break: several writes can land on the same tick (e.g. the
        # night snapshot re-records policy_rate before EXECUTION moves it); the
        # newest row must win on every SQLite build, not just by plan accident.
        v = self.scalar(
            "SELECT value FROM metrics WHERE name=? ORDER BY tick DESC, id DESC LIMIT 1", (name,)
        )
        return float(v) if v is not None else default

    def metric_series(self, name: str) -> list[tuple[int, float]]:
        rows = self.query("SELECT tick, value FROM metrics WHERE name=? ORDER BY tick", (name,))
        return [(int(r["tick"]), float(r["value"])) for r in rows]

    def metric_at_or_before(self, name: str, tick: int, default: float = 0.0) -> float:
        v = self.scalar(
            "SELECT value FROM metrics WHERE name=? AND tick<=? ORDER BY tick DESC, id DESC LIMIT 1",
            (name, tick),
        )
        return float(v) if v is not None else default


def load_json(value, default=None):
    if value is None or value == "":
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default
