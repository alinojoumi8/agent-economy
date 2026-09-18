"""Back up, validate, and schedule prospective geography on a stopped local run.

Usage: python scripts/enable_frontier.py --run-id ID [--apply]
The default makes a private validation copy; --apply schedules the next tick.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.store import Store
from engine.frontier import snapshot_at
from world.loop import World
from server.projections.workspaces import build_world_workspace


def fingerprint(db, table):
    digest = hashlib.sha256()
    # Callers supply fixed internal table names only.
    for row in db.execute(f'SELECT * FROM "{table}" ORDER BY rowid'):
        digest.update(json.dumps(tuple(row), separators=(",", ":"), default=str).encode())
    return digest.hexdigest()


def enable(run_id, *, apply=False, root=ROOT):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
        raise ValueError("invalid run ID")
    path = root / "data/runs" / f"{run_id}.db"
    if not path.is_file():
        raise ValueError("saved world does not exist")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder = root / "data/backups" / f"frontier-{run_id}-{stamp}"
    folder.mkdir(parents=True)
    backup = folder / "before.db"
    with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as source:
        source.row_factory = sqlite3.Row
        meta = source.execute("SELECT * FROM run_meta WHERE id=1").fetchone()
        if meta["run_id"] != run_id or meta["active_tick"] is not None or meta["status"] != "paused":
            raise ValueError("pause at a completed tick before scheduling geography")
        cfg = json.loads(meta["config_json"])
        if cfg.get("frontier"):
            raise ValueError("world already has a frontier configuration")
        if cfg.get("engine_semantics_version") != 11:
            raise ValueError("this upgrade supports semantics 11 only")
        with sqlite3.connect(backup) as out:
            source.backup(out)
        before = {table: fingerprint(source, table) for table in ("agents", "events", "memories", "ledger_entries")}
        source_config = meta["config_json"]
        tick = int(meta["tick"])
    cfg["frontier"] = {"version": 1, "activation_tick": tick + 1}
    rehearsal = folder / "validation.db"
    with sqlite3.connect(backup) as source, sqlite3.connect(rehearsal) as out:
        source.backup(out)
    store = Store(str(rehearsal), create=False)
    world = World(store, cfg)
    try:
        world.economy.frontier.run_nightly(tick + 1)
        assert all(a["region_id"] is None for a in build_world_workspace(store, as_of_tick=tick)["agents"])
        assert build_world_workspace(store, as_of_tick=tick)["regions"] == []
        assert store.scalar("SELECT COUNT(*) FROM agents WHERE alive=1 AND region_id IS NULL") == 0
        assert len(snapshot_at(store, tick+1)["sites"]) == 9
        assert world.economy.ledger.reconcile()[0]
        assert fingerprint(store.conn, "ledger_entries") == before["ledger_entries"]
        assert fingerprint(store.conn, "memories") == before["memories"]
        store.commit()
    finally:
        world.close()
    if apply:
        store = Store(str(path), create=False)
        try:
            store.conn.execute("BEGIN IMMEDIATE")
            fresh = store.get_meta()
            if (fresh["tick"] != tick or fresh["active_tick"] is not None
                    or fresh["status"] != "paused" or fresh["config_json"] != source_config
                    or any(fingerprint(store.conn, table) != value for table, value in before.items())):
                raise ValueError("world changed during validation; nothing was activated")
            store.set_meta(config_json=json.dumps(cfg, sort_keys=True))
            store.commit()
        finally:
            store.close()
    result = {"run_id": run_id, "previous_tick": tick, "activation_tick": tick+1,
              "applied": apply, "backup": str(backup), "backup_sha256": hashlib.sha256(backup.read_bytes()).hexdigest(),
              "validation_copy": str(rehearsal), "preserved": before}
    (folder / "verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(enable(args.run_id, apply=args.apply), indent=2))
