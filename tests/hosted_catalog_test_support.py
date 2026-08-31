from __future__ import annotations

from contextlib import contextmanager

from hosted.catalog import TENANT_CONTEXT_SQL


class Cursor:
    def __init__(self, *, rows=(), one=None, rowcount=0):
        self._rows = list(rows)
        self._one = one
        self.rowcount = rowcount

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._one


class CatalogConnection:
    def __init__(self, responses=()):
        self.responses = list(responses)
        self.calls = []
        self.closed = False
        self.commits = 0
        self.rollbacks = 0

    @contextmanager
    def transaction(self):
        try:
            yield
        except BaseException:
            self.rollbacks += 1
            raise
        else:
            self.commits += 1

    def execute(self, sql, params=()):
        self.calls.append((sql, tuple(params)))
        if sql == TENANT_CONTEXT_SQL:
            return Cursor()
        if self.responses:
            return self.responses.pop(0)
        return Cursor()

    def close(self):
        self.closed = True


class Connections:
    def __init__(self, *connections):
        self.connections = list(connections)
        self.opened = 0

    def __call__(self, _dsn):
        connection = self.connections[self.opened]
        self.opened += 1
        return connection


def run_row(tenant_id, run_id, owner_id, *, status="running"):
    return {
        "id": run_id,
        "tenant_id": tenant_id,
        "owner_user_id": owner_id,
        "run_key": "run-one",
        "display_name": "Run One",
        "status": status,
        "schema_version": 11,
        "engine_semantics_version": 7,
        "catalog_json": {},
        "snapshot_object_key": None,
        "snapshot_sha256": None,
        "snapshot_size_bytes": None,
        "writer_lease_owner": None,
        "writer_lease_token": None,
        "writer_lease_expires_at": None,
    }
