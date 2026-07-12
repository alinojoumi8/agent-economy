"""Replay viewer backend (P1 R16): re-watch any stored run tick-by-tick from its
events, news, conversations, and metrics — no LLM calls, no engine execution.

Every run database in `data/runs/` is browsable read-only while the live world
keeps running. (This is the *viewing* replay; `run.py --replay` is the separate
exact re-execution mode from stored LLM responses, TECH-SPEC §13.)
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections import OrderedDict
from pathlib import Path
from typing import Optional

HEADLINE_METRICS = ("gdp_proxy", "cpi", "unemployment", "index", "policy_rate",
                    "money_supply", "gini", "sentiment", "gov_balance", "insured_count",
                    "epidemic_multiplier")

_RUN_ID = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


def _load_json(v, default=None):
    if not v:
        return default
    try:
        return json.loads(v)
    except (json.JSONDecodeError, TypeError):
        return default


class ReplayReader:
    def __init__(self, runs_dir: str = "data/runs", *, max_connections: int = 8):
        if max_connections < 1:
            raise ValueError("max_connections must be at least 1")
        self.runs_dir = Path(runs_dir)
        self.max_connections = max_connections
        self._conns: OrderedDict[str, sqlite3.Connection] = OrderedDict()

    # ── connections (read-only, cached) ──────────────────────────────────────
    def _conn(self, run_id: str) -> Optional[sqlite3.Connection]:
        if not _RUN_ID.match(run_id or ""):
            return None
        if run_id in self._conns:
            conn = self._conns.pop(run_id)
            self._conns[run_id] = conn
            return conn
        path = self.runs_dir / f"{run_id}.db"
        if not path.exists():
            return None
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True,
                               check_same_thread=False)
        conn.row_factory = sqlite3.Row
        self._conns[run_id] = conn
        while len(self._conns) > self.max_connections:
            _, stale = self._conns.popitem(last=False)
            stale.close()
        return conn

    def close(self) -> None:
        while self._conns:
            _, conn = self._conns.popitem(last=False)
            conn.close()

    # ── catalogue ────────────────────────────────────────────────────────────
    def list_runs(self) -> list[dict]:
        out = []
        for db in sorted(self.runs_dir.glob("*.db")):
            run_id = db.stem
            conn = self._conn(run_id)
            if conn is None:
                continue
            try:
                meta = conn.execute(
                    "SELECT run_id, seed, status, tick, created_at FROM run_meta WHERE id=1"
                ).fetchone()
            except sqlite3.Error:
                continue
            if not meta:
                continue
            out.append({"run_id": meta["run_id"], "file": run_id, "seed": meta["seed"],
                        "status": meta["status"], "ticks": int(meta["tick"]),
                        "created_at": meta["created_at"]})
        return out

    def summary(self, run_id: str) -> Optional[dict]:
        conn = self._conn(run_id)
        if conn is None:
            return None
        meta = conn.execute("SELECT * FROM run_meta WHERE id=1").fetchone()
        agents = conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
        firms = conn.execute("SELECT COUNT(*) FROM firms").fetchone()[0]
        return {"run_id": meta["run_id"], "seed": meta["seed"], "status": meta["status"],
                "ticks": int(meta["tick"]), "agents": int(agents), "firms": int(firms)}

    # ── full metric series (the client truncates at the slider tick) ─────────
    def metrics(self, run_id: str, names: Optional[str] = None) -> Optional[dict]:
        conn = self._conn(run_id)
        if conn is None:
            return None
        wanted = [n.strip() for n in (names or ",".join(HEADLINE_METRICS)).split(",") if n.strip()]
        out = {}
        for name in wanted:
            rows = conn.execute(
                "SELECT tick, value FROM metrics WHERE name=? ORDER BY tick", (name,)).fetchall()
            if rows:
                out[name] = [{"tick": int(r["tick"]), "value": float(r["value"])} for r in rows]
        return out

    # ── one tick's world, as the dashboard panels expect it ─────────────────
    def tick_view(self, run_id: str, tick: int) -> Optional[dict]:
        conn = self._conn(run_id)
        if conn is None:
            return None
        events = [{"id": int(r["id"]), "tick": int(r["tick"]), "kind": r["kind"],
                   "phase": r["phase"], "importance": float(r["importance"]),
                   "payload": _load_json(r["payload_json"], {})}
                  for r in conn.execute(
                      "SELECT * FROM events WHERE tick=? AND kind NOT IN "
                      "('metrics_snapshot','action_rejected') ORDER BY id LIMIT 80", (tick,))]
        news = [{"headline": r["headline"], "outlet": r["outlet_name"],
                 "tone": float(r["tone"])}
                for r in conn.execute(
                    "SELECT * FROM news_articles WHERE tick=? ORDER BY id", (tick,))]
        convs = []
        for c in conn.execute(
                "SELECT * FROM conversations WHERE tick=? ORDER BY id LIMIT 6", (tick,)):
            msgs = conn.execute(
                "SELECT m.text, m.seq, a.name FROM messages m LEFT JOIN agents a "
                "ON a.id=m.agent_id WHERE m.conv_id=? ORDER BY m.seq", (int(c["id"]),)).fetchall()
            convs.append({"id": int(c["id"]),
                          "messages": [{"name": m["name"], "text": m["text"]} for m in msgs]})
        metrics = {}
        for name in HEADLINE_METRICS:
            row = conn.execute(
                "SELECT value FROM metrics WHERE name=? AND tick<=? ORDER BY tick DESC LIMIT 1",
                (name, tick)).fetchone()
            if row is not None:
                metrics[name] = float(row["value"])
        ticker = [{"firm_id": int(r["firm_id"]), "name": r["name"],
                   "price_cents": int(r["price_cents"])}
                  for r in conn.execute(
                      "SELECT t.firm_id AS firm_id, f.name AS name, t.price_cents AS price_cents "
                      "FROM trades t JOIN firms f ON f.id=t.firm_id "
                      "WHERE t.id IN (SELECT MAX(id) FROM trades WHERE tick<=? GROUP BY firm_id)",
                      (tick,))]
        return {"run_id": run_id, "tick": tick, "events": events, "news": news,
                "conversations": convs, "metrics": metrics, "ticker": ticker}
