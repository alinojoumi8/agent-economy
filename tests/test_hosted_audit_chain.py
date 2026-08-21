from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import threading
import time
from uuid import uuid4

from hosted.audit_chain import (
    GENESIS_AUDIT_HASH,
    build_chained_audit_entry,
    verify_audit_chain,
)
from hosted.catalog import HostedCatalog, TENANT_CONTEXT_SQL


def _entry(tenant_id, sequence, previous, *, action="run.created"):
    return build_chained_audit_entry(
        tenant_id=str(tenant_id),
        tenant_sequence=sequence,
        previous_entry_hash=previous,
        actor_user_id=None,
        action=action,
        target_type="run",
        target_id=f"run-{sequence}",
        request_id=None,
        details={"safe": True, "sequence": sequence},
        created_at=datetime(
            2026, 8, 19, 12, 0, tzinfo=timezone.utc)
        + timedelta(seconds=sequence),
    )


def test_audit_chain_verifies_order_and_detects_tampering():
    tenant_id = uuid4()
    first = _entry(tenant_id, 1, GENESIS_AUDIT_HASH)
    second = _entry(tenant_id, 2, first["entry_hash"])

    valid = verify_audit_chain([first, second], tenant_id=str(tenant_id))
    assert valid.valid is True
    assert valid.chained_entries == 2
    assert valid.legacy_entries == 0
    assert valid.error is None

    reordered = verify_audit_chain(
        [second, first], tenant_id=str(tenant_id))
    assert reordered.valid is False
    assert "sequence" in str(reordered.error)

    tampered = deepcopy(second)
    tampered["details_json"]["safe"] = False
    modified = verify_audit_chain(
        [first, tampered], tenant_id=str(tenant_id))
    assert modified.valid is False
    assert "entry hash" in str(modified.error)


def test_audit_chain_is_tenant_isolated_and_reports_legacy_rows():
    tenant_a = uuid4()
    tenant_b = uuid4()
    a_first = _entry(tenant_a, 1, GENESIS_AUDIT_HASH)
    b_first = _entry(tenant_b, 1, GENESIS_AUDIT_HASH)
    legacy = {
        "tenant_id": str(tenant_a),
        "tenant_sequence": None,
        "previous_entry_hash": None,
        "entry_hash": None,
    }

    isolated = verify_audit_chain(
        [legacy, a_first], tenant_id=str(tenant_a))
    assert isolated.valid is True
    assert isolated.legacy_entries == 1
    assert isolated.chained_entries == 1

    mixed = verify_audit_chain(
        [a_first, b_first], tenant_id=str(tenant_a))
    assert mixed.valid is False
    assert "tenant" in str(mixed.error)


def test_audit_chain_rejects_a_partially_chained_row():
    tenant_id = uuid4()
    partial = _entry(tenant_id, 1, GENESIS_AUDIT_HASH)
    partial["entry_hash"] = None

    result = verify_audit_chain([partial], tenant_id=str(tenant_id))

    assert result.valid is False
    assert result.error == "partially chained audit row"


class _Cursor:
    def __init__(self, one=None):
        self._one = one

    def fetchone(self):
        return self._one


class _ConcurrentState:
    def __init__(self):
        self.lock = threading.Lock()
        self.entries = []
        self.connections = []


class _ConcurrentConnection:
    def __init__(self, state: _ConcurrentState):
        self.state = state
        self.calls = []
        self.tenant_id = None
        self._held = False
        state.connections.append(self)

    @contextmanager
    def transaction(self):
        try:
            yield
        finally:
            if self._held:
                self.state.lock.release()
                self._held = False

    def execute(self, sql, params=()):
        params = tuple(params)
        self.calls.append((sql, params))
        compact = " ".join(sql.split())
        if sql == TENANT_CONTEXT_SQL:
            self.tenant_id = params[0]
            return _Cursor()
        if "pg_advisory_xact_lock" in compact:
            self.state.lock.acquire()
            self._held = True
            return _Cursor()
        if compact.startswith(
            "SELECT tenant_sequence, entry_hash FROM audit_log"
        ):
            # Widen the would-be race. The advisory lock must keep both callers
            # from observing the same head.
            time.sleep(0.01)
            matching = [
                row for row in self.state.entries
                if row["tenant_id"] == self.tenant_id
            ]
            if not matching:
                return _Cursor()
            head = matching[-1]
            return _Cursor({
                "tenant_sequence": head["tenant_sequence"],
                "entry_hash": head["entry_hash"],
            })
        if compact.startswith("INSERT INTO audit_log"):
            (
                tenant_id,
                actor_user_id,
                action,
                target_type,
                target_id,
                request_id,
                details_json,
                created_at,
                sequence,
                previous_hash,
                entry_hash,
            ) = params
            row = {
                "id": len(self.state.entries) + 1,
                "tenant_id": tenant_id,
                "actor_user_id": actor_user_id,
                "action": action,
                "target_type": target_type,
                "target_id": target_id,
                "request_id": request_id,
                "details_json": __import__("json").loads(details_json),
                "created_at": created_at,
                "tenant_sequence": sequence,
                "previous_entry_hash": previous_hash,
                "entry_hash": entry_hash,
            }
            self.state.entries.append(row)
            return _Cursor({"id": row["id"]})
        return _Cursor()

    def close(self):
        pass


def test_catalog_serializes_concurrent_tenant_chain_inserts():
    tenant_id = uuid4()
    state = _ConcurrentState()

    def connect(_dsn):
        return _ConcurrentConnection(state)

    catalog = HostedCatalog("postgresql://example", connect=connect)
    barrier = threading.Barrier(2)

    def append(index):
        barrier.wait()
        return catalog.append_audit(
            tenant_id,
            action=f"run.event.{index}",
            target_type="run",
            target_id=f"run-{index}",
            details={"index": index},
        )

    threads = [
        threading.Thread(target=append, args=(index,))
        for index in (1, 2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()

    assert [row["tenant_sequence"] for row in state.entries] == [1, 2]
    assert state.entries[0]["previous_entry_hash"] == GENESIS_AUDIT_HASH
    assert (
        state.entries[1]["previous_entry_hash"]
        == state.entries[0]["entry_hash"]
    )
    assert verify_audit_chain(
        state.entries, tenant_id=str(tenant_id)).valid
    for connection in state.connections:
        sql = [" ".join(item[0].split()) for item in connection.calls]
        lock_index = next(
            index for index, item in enumerate(sql)
            if "pg_advisory_xact_lock" in item)
        head_index = next(
            index for index, item in enumerate(sql)
            if item.startswith(
                "SELECT tenant_sequence, entry_hash FROM audit_log"))
        insert_index = next(
            index for index, item in enumerate(sql)
            if item.startswith("INSERT INTO audit_log"))
        assert lock_index < head_index < insert_index
        assert "FOR UPDATE" not in sql[head_index]
