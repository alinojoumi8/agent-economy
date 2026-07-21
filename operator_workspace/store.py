"""Separate SQLite store for local investigations and truth-inspection audit."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


class WorkspaceConflict(RuntimeError):
    """Optimistic version check failed."""


class WorkspaceNotFound(LookupError):
    """Requested observer-owned record does not exist."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS investigations (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    title TEXT NOT NULL,
    run_id TEXT NOT NULL,
    fork_id TEXT,
    pinned_tick INTEGER,
    query_json TEXT NOT NULL,
    layout_json TEXT NOT NULL,
    version INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS investigation_items (
    id TEXT PRIMARY KEY,
    investigation_id TEXT NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
    item_kind TEXT NOT NULL,
    stable_ref_json TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    label TEXT,
    color TEXT,
    sort_order INTEGER NOT NULL,
    version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS hypotheses (
    id TEXT PRIMARY KEY,
    investigation_id TEXT NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
    statement TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('open','supported','refuted','inconclusive')),
    version INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS saved_views (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    name TEXT NOT NULL,
    route TEXT NOT NULL,
    state_json TEXT NOT NULL,
    version INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS operator_audit (
    id TEXT PRIMARY KEY,
    occurred_at TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK(action IN (
        'truth_inspect','privileged_export','access_denied','investigation_write')),
    run_id TEXT,
    fork_id TEXT,
    stable_ref_json TEXT,
    policy_version INTEGER NOT NULL,
    outcome TEXT NOT NULL,
    previous_hash TEXT,
    entry_hash TEXT NOT NULL UNIQUE
);
CREATE TRIGGER IF NOT EXISTS operator_audit_no_update
BEFORE UPDATE ON operator_audit BEGIN
    SELECT RAISE(ABORT, 'operator audit is append-only');
END;
CREATE TRIGGER IF NOT EXISTS operator_audit_no_delete
BEFORE DELETE ON operator_audit BEGIN
    SELECT RAISE(ABORT, 'operator audit is append-only');
END;
"""


class OperatorWorkspace:
    def __init__(self, path: str | Path, *, world_path: str | Path | None = None):
        self.path = Path(path).resolve()
        if world_path is not None and self.path == Path(world_path).resolve():
            raise ValueError("operator workspace must be separate from world storage")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def create_investigation(
        self, *, owner_id: str, title: str, run_id: str, fork_id: str | None = None,
        pinned_tick: int | None = None, query: dict | None = None, layout: dict | None = None,
    ) -> dict:
        title = str(title).strip()
        if not title or len(title) > 160:
            raise ValueError("investigation title must contain 1 to 160 characters")
        record_id = str(uuid4())
        now = _now()
        self.conn.execute(
            "INSERT INTO investigations "
            "(id,owner_id,title,run_id,fork_id,pinned_tick,query_json,layout_json,version,"
            "created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,1,?,?)",
            (record_id, str(owner_id), title, str(run_id), fork_id, pinned_tick,
             _json(query or {}), _json(layout or {}), now, now),
        )
        self.append_audit(
            owner_id=owner_id, action="investigation_write", run_id=run_id,
            fork_id=fork_id, stable_ref={"kind": "investigation", "id": record_id},
            outcome="created")
        self.conn.commit()
        return self.get_investigation(record_id, owner_id=owner_id)

    def get_investigation(self, investigation_id: str, *, owner_id: str) -> dict:
        row = self.conn.execute(
            "SELECT * FROM investigations WHERE id=? AND owner_id=?",
            (str(investigation_id), str(owner_id))).fetchone()
        if row is None:
            raise WorkspaceNotFound("investigation not found")
        result = dict(row)
        result["query"] = json.loads(result.pop("query_json"))
        result["layout"] = json.loads(result.pop("layout_json"))
        result["items"] = [
            {**dict(item), "stable_ref": json.loads(item["stable_ref_json"])}
            for item in self.conn.execute(
                "SELECT * FROM investigation_items WHERE investigation_id=? "
                "ORDER BY sort_order,id", (str(investigation_id),))
        ]
        for item in result["items"]:
            item.pop("stable_ref_json", None)
        result["hypotheses"] = [dict(item) for item in self.conn.execute(
            "SELECT * FROM hypotheses WHERE investigation_id=? ORDER BY created_at,id",
            (str(investigation_id),))]
        return result

    def list_investigations(self, *, owner_id: str, run_id: str | None = None) -> list[dict]:
        if run_id is None:
            rows = self.conn.execute(
                "SELECT id FROM investigations WHERE owner_id=? ORDER BY updated_at DESC,id",
                (str(owner_id),))
        else:
            rows = self.conn.execute(
                "SELECT id FROM investigations WHERE owner_id=? AND run_id=? "
                "ORDER BY updated_at DESC,id", (str(owner_id), str(run_id)))
        return [self.get_investigation(row["id"], owner_id=owner_id) for row in rows]

    def update_investigation(
        self, investigation_id: str, *, owner_id: str, expected_version: int,
        title: str | None = None, pinned_tick: int | None = None,
        query: dict | None = None, layout: dict | None = None,
    ) -> dict:
        current = self.get_investigation(investigation_id, owner_id=owner_id)
        next_title = current["title"] if title is None else str(title).strip()
        if not next_title or len(next_title) > 160:
            raise ValueError("investigation title must contain 1 to 160 characters")
        cursor = self.conn.execute(
            "UPDATE investigations SET title=?,pinned_tick=?,query_json=?,layout_json=?,"
            "version=version+1,updated_at=? WHERE id=? AND owner_id=? AND version=?",
            (next_title, current["pinned_tick"] if pinned_tick is None else pinned_tick,
             _json(current["query"] if query is None else query),
             _json(current["layout"] if layout is None else layout), _now(),
             str(investigation_id), str(owner_id), int(expected_version)),
        )
        if cursor.rowcount != 1:
            self.conn.rollback()
            raise WorkspaceConflict("investigation version conflict")
        self.append_audit(
            owner_id=owner_id, action="investigation_write", run_id=current["run_id"],
            fork_id=current["fork_id"],
            stable_ref={"kind": "investigation", "id": investigation_id}, outcome="updated")
        self.conn.commit()
        return self.get_investigation(investigation_id, owner_id=owner_id)

    def add_item(
        self, investigation_id: str, *, owner_id: str, item_kind: str,
        stable_ref: dict, note: str = "", label: str | None = None,
        color: str | None = None,
    ) -> dict:
        investigation = self.get_investigation(investigation_id, owner_id=owner_id)
        item_id = str(uuid4())
        sort_order = int(self.conn.execute(
            "SELECT COALESCE(MAX(sort_order),-1)+1 FROM investigation_items "
            "WHERE investigation_id=?", (str(investigation_id),)).fetchone()[0])
        self.conn.execute(
            "INSERT INTO investigation_items "
            "(id,investigation_id,item_kind,stable_ref_json,note,label,color,sort_order,version) "
            "VALUES (?,?,?,?,?,?,?,?,1)",
            (item_id, str(investigation_id), str(item_kind), _json(stable_ref),
             str(note)[:4000], label, color, sort_order),
        )
        self.append_audit(
            owner_id=owner_id, action="investigation_write", run_id=investigation["run_id"],
            fork_id=investigation["fork_id"], stable_ref=stable_ref, outcome="item_added")
        self.conn.commit()
        return next(item for item in self.get_investigation(
            investigation_id, owner_id=owner_id)["items"] if item["id"] == item_id)

    def add_hypothesis(
        self, investigation_id: str, *, owner_id: str, statement: str,
        status: str = "open",
    ) -> dict:
        investigation = self.get_investigation(investigation_id, owner_id=owner_id)
        if status not in {"open", "supported", "refuted", "inconclusive"}:
            raise ValueError("invalid hypothesis status")
        statement = str(statement).strip()
        if not statement or len(statement) > 2000:
            raise ValueError("hypothesis statement must contain 1 to 2000 characters")
        hypothesis_id = str(uuid4())
        now = _now()
        self.conn.execute(
            "INSERT INTO hypotheses "
            "(id,investigation_id,statement,status,version,created_at,updated_at) "
            "VALUES (?,?,?,?,1,?,?)",
            (hypothesis_id, str(investigation_id), statement, status, now, now),
        )
        self.append_audit(
            owner_id=owner_id, action="investigation_write", run_id=investigation["run_id"],
            fork_id=investigation["fork_id"],
            stable_ref={"kind": "hypothesis", "id": hypothesis_id}, outcome="created")
        self.conn.commit()
        return dict(self.conn.execute(
            "SELECT * FROM hypotheses WHERE id=?", (hypothesis_id,)).fetchone())

    def append_audit(
        self, *, owner_id: str, action: str, outcome: str, run_id: str | None = None,
        fork_id: str | None = None, stable_ref: dict | None = None,
        policy_version: int = 1,
    ) -> str:
        previous = self.conn.execute(
            "SELECT entry_hash FROM operator_audit ORDER BY rowid DESC LIMIT 1").fetchone()
        previous_hash = str(previous["entry_hash"]) if previous else None
        audit_id = str(uuid4())
        occurred_at = _now()
        material = {
            "id": audit_id, "occurred_at": occurred_at, "owner_id": str(owner_id),
            "action": str(action), "run_id": run_id, "fork_id": fork_id,
            "stable_ref": stable_ref, "policy_version": int(policy_version),
            "outcome": str(outcome), "previous_hash": previous_hash,
        }
        entry_hash = hashlib.sha256(_json(material).encode("utf-8")).hexdigest()
        self.conn.execute(
            "INSERT INTO operator_audit "
            "(id,occurred_at,owner_id,action,run_id,fork_id,stable_ref_json,policy_version,"
            "outcome,previous_hash,entry_hash) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (audit_id, occurred_at, str(owner_id), str(action), run_id, fork_id,
             _json(stable_ref) if stable_ref is not None else None, int(policy_version),
             str(outcome), previous_hash, entry_hash),
        )
        return entry_hash

    def truth_audit(self, *, owner_id: str, run_id: str, fork_id: str | None = None):
        def audit(_principal, message_id: int, field, tick: int) -> bool:
            try:
                self.append_audit(
                    owner_id=owner_id, action="truth_inspect", run_id=run_id,
                    fork_id=fork_id,
                    stable_ref={
                        "kind": "message", "id": int(message_id),
                        "field": str(field.value), "tick": int(tick),
                    },
                    outcome="allowed",
                )
                self.conn.commit()
                return True
            except Exception:
                try:
                    self.conn.rollback()
                except Exception:
                    pass
                return False
        return audit

    def export(self, investigation_id: str, *, owner_id: str) -> tuple[dict, str]:
        record = self.get_investigation(investigation_id, owner_id=owner_id)
        payload = {
            "format": "world-os-investigation-v1",
            "investigation": record,
            "redaction_manifest": {
                "private_message_bodies": "not_copied",
                "operator_audit": "not_included",
            },
        }
        lines = [f"# {record['title']}", "", f"Run: `{record['run_id']}`", ""]
        if record["hypotheses"]:
            lines.extend(["## Hypotheses", ""])
            lines.extend(
                f"- [{item['status']}] {item['statement']}" for item in record["hypotheses"])
        if record["items"]:
            lines.extend(["", "## Evidence", ""])
            for item in record["items"]:
                lines.append(
                    f"- `{_json(item['stable_ref'])}` {item.get('note') or ''}".rstrip())
        return payload, "\n".join(lines) + "\n"
