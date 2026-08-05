"""Observer workspace separation, conflicts, audit chaining, and export tests."""
from __future__ import annotations

import json
import sqlite3

import pytest

from operator_workspace import OperatorWorkspace, WorkspaceConflict, WorkspaceNotFound


def test_workspace_is_separate_versioned_audited_and_redacted(tmp_path):
    world_path = tmp_path / "world.db"
    world_path.touch()
    with pytest.raises(ValueError, match="separate"):
        OperatorWorkspace(world_path, world_path=world_path)

    workspace = OperatorWorkspace(tmp_path / "operator.db", world_path=world_path)
    created = workspace.create_investigation(
        owner_id="alice", title="Causal trace", run_id="run-1",
        query={"relation": "motivated"})
    assert created["version"] == 1
    updated = workspace.update_investigation(
        created["id"], owner_id="alice", expected_version=1,
        title="Causal trace v2", layout={"left": 320})
    assert updated["version"] == 2
    audit_count_before_conflict = workspace.conn.execute(
        "SELECT COUNT(*) FROM operator_audit").fetchone()[0]
    with pytest.raises(WorkspaceConflict, match="version conflict"):
        workspace.update_investigation(
            created["id"], owner_id="alice", expected_version=1, title="stale")
    current = workspace.get_investigation(created["id"], owner_id="alice")
    assert (current["title"], current["version"]) == ("Causal trace v2", 2)
    assert workspace.conn.execute(
        "SELECT COUNT(*) FROM operator_audit").fetchone()[0] == audit_count_before_conflict

    copied = workspace.create_investigation(
        owner_id=current["owner_id"], title="Local draft", run_id=current["run_id"],
        fork_id=current["fork_id"], pinned_tick=current["pinned_tick"],
        query=current["query"], layout=current["layout"],
    )
    assert copied["id"] != current["id"]
    assert copied["version"] == 1
    for field in ("owner_id", "run_id", "fork_id", "pinned_tick", "query", "layout"):
        assert copied[field] == current[field]
    assert copied["items"] == []
    assert copied["hypotheses"] == []
    with pytest.raises(WorkspaceNotFound):
        workspace.get_investigation(created["id"], owner_id="bob")

    item = workspace.add_item(
        created["id"], owner_id="alice", item_kind="message",
        stable_ref={"kind": "message", "id": 7}, note="No private body copied")
    assert item["stable_ref"] == {"kind": "message", "id": 7}
    hypothesis = workspace.add_hypothesis(
        created["id"], owner_id="alice", statement="The warning reduced demand")
    assert hypothesis["status"] == "open"
    with pytest.raises(ValueError, match="status"):
        workspace.add_hypothesis(
            created["id"], owner_id="alice", statement="bad", status="maybe")

    payload, markdown = workspace.export(created["id"], owner_id="alice")
    assert payload["redaction_manifest"]["private_message_bodies"] == "not_copied"
    assert "The warning reduced demand" in markdown
    assert "No private body copied" in markdown

    audits = workspace.conn.execute(
        "SELECT previous_hash,entry_hash,stable_ref_json FROM operator_audit ORDER BY rowid").fetchall()
    assert audits[0]["previous_hash"] is None
    for previous, current in zip(audits, audits[1:]):
        assert current["previous_hash"] == previous["entry_hash"]
    assert all("Private body" not in str(row["stable_ref_json"]) for row in audits)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        workspace.conn.execute(
            "UPDATE operator_audit SET outcome='changed' WHERE entry_hash=?",
            (audits[0]["entry_hash"],))
    workspace.conn.rollback()
    workspace.close()


def test_truth_audit_commits_before_authorization_and_fails_closed(tmp_path):
    workspace = OperatorWorkspace(tmp_path / "operator.db")
    audit = workspace.truth_audit(owner_id="alice", run_id="run-1")
    field = type("Field", (), {"value": "body"})()
    assert audit(None, 9, field, 4) is True
    row = workspace.conn.execute("SELECT * FROM operator_audit").fetchone()
    ref = json.loads(row["stable_ref_json"])
    assert ref == {"field": "body", "id": 9, "kind": "message", "tick": 4}
    workspace.close()
    assert audit(None, 9, field, 4) is False


def test_workspace_validation_listing_empty_export_and_delete_guard(tmp_path):
    workspace = OperatorWorkspace(tmp_path / "operator.db")
    try:
        for title in ("", "x" * 161):
            with pytest.raises(ValueError, match="title"):
                workspace.create_investigation(
                    owner_id="alice", title=title, run_id="run-1")
        first = workspace.create_investigation(
            owner_id="alice", title="First", run_id="run-1", pinned_tick=3)
        second = workspace.create_investigation(
            owner_id="alice", title="Second", run_id="run-2", fork_id="fork-2")
        assert {item["id"] for item in workspace.list_investigations(owner_id="alice")} == {
            first["id"], second["id"]}
        assert [item["id"] for item in workspace.list_investigations(
            owner_id="alice", run_id="run-1")] == [first["id"]]

        for title in ("", "x" * 161):
            with pytest.raises(ValueError, match="title"):
                workspace.update_investigation(
                    first["id"], owner_id="alice", expected_version=1, title=title)
        unchanged = workspace.update_investigation(
            first["id"], owner_id="alice", expected_version=1)
        assert unchanged["title"] == "First"
        assert unchanged["pinned_tick"] == 3

        for statement in ("", "x" * 2001):
            with pytest.raises(ValueError, match="statement"):
                workspace.add_hypothesis(
                    second["id"], owner_id="alice", statement=statement)
        payload, markdown = workspace.export(second["id"], owner_id="alice")
        assert payload["investigation"]["items"] == []
        assert "## Evidence" not in markdown
        assert "## Hypotheses" not in markdown

        audit_id = workspace.conn.execute(
            "SELECT id FROM operator_audit ORDER BY rowid LIMIT 1").fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            workspace.conn.execute("DELETE FROM operator_audit WHERE id=?", (audit_id,))
        workspace.conn.rollback()
    finally:
        workspace.close()


def test_export_is_owner_scoped_and_strips_private_reference_fields(tmp_path):
    canary = "PRIVATE-MESSAGE-CANARY-9f3c"
    workspace = OperatorWorkspace(tmp_path / "operator.db")
    try:
        created = workspace.create_investigation(
            owner_id="alice", title="Redacted trace", run_id="run-private",
            fork_id="fork-private", pinned_tick=8,
            query={"authority": "engine"}, layout={"left": 280},
        )
        workspace.add_item(
            created["id"], owner_id="alice", item_kind="message",
            stable_ref={
                "kind": "message", "id": 77, "tick": 8,
                "order_key": "message:77", "body_text": canary,
                "sensitive_external_action": {"secret": canary},
            },
            note="Stable reference only",
        )
        workspace.add_hypothesis(
            created["id"], owner_id="alice", statement="Delivery changed demand",
        )

        with pytest.raises(WorkspaceNotFound):
            workspace.export(created["id"], owner_id="bob")
        payload, markdown = workspace.export(created["id"], owner_id="alice")
        serialized = json.dumps(payload, sort_keys=True)
        assert payload["format"] == "world-os-investigation-v1"
        assert payload["redaction_manifest"] == {
            "private_message_bodies": "not_copied",
            "operator_audit": "not_included",
        }
        assert "operator_audit" not in payload["investigation"]
        assert payload["investigation"]["items"][0]["stable_ref"] == {
            "kind": "message", "id": 77, "tick": 8,
            "order_key": "message:77",
        }
        assert canary not in serialized
        assert canary not in markdown
        assert "# Redacted trace" in markdown
        assert "Run: `run-private`" in markdown
        assert "Delivery changed demand" in markdown
        assert '"kind":"message"' in markdown
    finally:
        workspace.close()


@pytest.mark.parametrize("identifier", ["", "x" * 201])
def test_workspace_rejects_unbounded_string_reference_identifiers(tmp_path, identifier):
    workspace = OperatorWorkspace(tmp_path / "operator.db")
    try:
        investigation = workspace.create_investigation(
            owner_id="alice", title="Bounded reference", run_id="run-1",
        )

        with pytest.raises(ValueError, match="bounded kind and id"):
            workspace.add_item(
                investigation["id"], owner_id="alice", item_kind="event",
                stable_ref={"kind": "event", "id": identifier},
            )

        assert workspace.conn.execute(
            "SELECT COUNT(*) FROM investigation_items"
        ).fetchone()[0] == 0
    finally:
        workspace.close()
