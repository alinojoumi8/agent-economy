"""Independent v2 storage evidence; historical v1 report verdicts are untouched."""
from pathlib import Path
import re
import sqlite3

from engine.checkpoint_formats import checkpoint_database, checkpoint_path
from engine.incremental_checkpoint import read_incremental


def checkpoint_evidence(store, run_id, config):
    from reports.supply_recovery import _logical_checkpoint_directory
    keep = config.get("checkpoint_keep_last")
    configured = config.get("checkpoint_dir")
    if type(keep) is not int or keep < 1 or not isinstance(configured, str) or not configured:
        return False, {"current_rows": [], "error": "invalid checkpoint retention configuration"}
    rows = store.query("SELECT id,tick,path FROM checkpoints ORDER BY tick,id")
    directory = Path(configured)
    if not directory.is_absolute():
        candidates = set()
        if ".." not in directory.parts:
            for row in rows:
                if type(row["tick"]) is int:
                    path = Path(row["path"])
                    if (path.is_absolute() and path.name == checkpoint_path(
                            path.parent, run_id, row["tick"], config).name):
                        candidates.add(path.parent)
        if len(candidates) != 1:
            return False, {"current_rows": [], "error": "ambiguous checkpoint directory"}
        directory = candidates.pop()
    directory = directory.absolute()
    current, excluded, expected = [], [], set()
    for row in rows:
        tick = row["tick"]
        if type(tick) is not int or tick < 0:
            excluded.append({"checkpoint_id": row["id"], "reason": "invalid_tick"})
            continue
        path = checkpoint_path(directory, run_id, tick, config)
        if row["path"] != str(path):
            excluded.append({"checkpoint_id": row["id"], "reason": "outside_current_run_scope"})
            continue
        errors = []
        sqlite_evidence = {}
        try:
            root, _, _, digest = read_incremental(path)
            state = root["evidence"]["state"]
            if state["run_id"] != run_id or type(state["tick"]) is not int or state["tick"] != tick:
                errors.append("manifest_state_binding_mismatch")
            with checkpoint_database(path) as materialized:
                db = sqlite3.connect(materialized.as_uri() + "?mode=ro&immutable=1", uri=True)
                try:
                    integrity = [r[0] for r in db.execute("PRAGMA integrity_check")]
                    foreign = list(db.execute("PRAGMA foreign_key_check"))
                    sqlite_evidence = {"integrity_check": integrity,
                                       "foreign_key_violation_count": len(foreign),
                                       "journal_mode": db.execute("PRAGMA journal_mode").fetchone()[0]}
                    if integrity != ["ok"] or foreign:
                        errors.append("sqlite_integrity_failed")
                finally:
                    db.close()
            # Descriptor replacement during independent verification is fatal.
            if read_incremental(path)[3] != digest:
                errors.append("checkpoint_changed_during_verification")
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
            errors.append(f"checkpoint_verification_failed:{type(exc).__name__}")
        current.append({"checkpoint_id": row["id"], "tick": tick,
                        "artifact": path.name, "manifest": path.name,
                        "database_exists": path.is_file(), "manifest_exists": path.is_file(),
                        "storage_format": "incremental-v2", "manifest_valid": not errors,
                        "manifest_validation_errors": errors, "sqlite_artifact": sqlite_evidence})
        expected.add(path)
    pattern = re.compile(rf"^{re.escape(run_id)}_t[0-9]+\.icp\.json$")
    actual = {p for p in directory.iterdir() if pattern.fullmatch(p.name)} if directory.is_dir() else set()
    matches = actual == expected
    passed = bool(current and not excluded and matches and len(current) <= keep
                  and all(r["manifest_valid"] for r in current))
    return passed, {"storage_format": "incremental-v2", "configured_keep_last": keep,
                    "configured_checkpoint_dir": _logical_checkpoint_directory(configured), "current_rows": current,
                    "current_row_count": len(current), "current_database_artifact_count": len(actual),
                    "current_manifest_artifact_count": len(actual),
                    "artifacts_match_current_rows": matches, "excluded_rows": excluded}
