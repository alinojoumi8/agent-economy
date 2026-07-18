"""Exhaustive migration-registry and schema-12 verification branches."""
from __future__ import annotations

import hashlib
import sqlite3

import pytest

from engine.migrations import registry
from engine.migrations.registry import Migration, MigrationError
from engine.migrations.v012_communications import REQUIRED_TABLES, verify
from engine.store import Store


class _Cursor(list):
    def fetchone(self):
        return self[0]


class _AdoptionFailureConnection:
    def __init__(self, *, transactional: bool):
        self.transactional = transactional
        self.in_transaction = False
        self.rolled_back = False

    def execute(self, sql, params=()):
        if sql.startswith("SELECT version,name"):
            return _Cursor()
        if sql == "BEGIN IMMEDIATE":
            self.in_transaction = self.transactional
            return _Cursor()
        if sql.startswith("INSERT INTO schema_migrations"):
            raise RuntimeError("adoption failed")
        if sql == "ROLLBACK":
            self.rolled_back = True
            self.in_transaction = False
        return _Cursor()


class _MigrationFailureConnection:
    in_transaction = False

    def execute(self, sql, params=()):
        if sql.startswith("SELECT version,name"):
            return _Cursor([(
                11, "legacy_schema_v11",
                hashlib.sha256(b"legacy-schema-v11\n").hexdigest(), 11,
                "adopted_legacy")])
        return _Cursor()

    def executescript(self, _sql):
        raise RuntimeError("apply failed before transaction")


class _VerifyConnection:
    def __init__(self, *, missing=(), foreign_keys=(), audiences=0, outcomes=0):
        self.tables = set(REQUIRED_TABLES) - set(missing)
        self.foreign_keys = list(foreign_keys)
        self.audiences = audiences
        self.outcomes = outcomes

    def execute(self, sql):
        if "FROM sqlite_master" in sql:
            return _Cursor([(name,) for name in sorted(self.tables)])
        if sql == "PRAGMA foreign_key_check":
            return _Cursor(self.foreign_keys)
        if "FROM comm_messages m WHERE" in sql:
            return _Cursor([(self.audiences,)])
        if "FROM comm_deliveries d WHERE" in sql:
            return _Cursor([(self.outcomes,)])
        raise AssertionError(sql)


def test_migration_normalization_and_invalid_legacy_history():
    assert registry._normalize_sql("SELECT 1;\r\n") == "SELECT 1;\n"
    assert registry._normalize_sql("SELECT\r1") == "SELECT\n1\n"
    assert len(registry.migration_checksum("SELECT 1")) == 64
    with pytest.raises(MigrationError, match="unknown legacy migration history"):
        registry._validate_history(
            [(10, "wrong", "x" * 64, 0, "adopted_legacy")],
            registry.registered_migrations())


@pytest.mark.parametrize("transactional", [True, False])
def test_legacy_adoption_failure_rolls_back_only_an_active_transaction(transactional):
    conn = _AdoptionFailureConnection(transactional=transactional)
    with pytest.raises(RuntimeError, match="adoption failed"):
        registry.apply_migrations(conn, source_schema=None, target_schema=11)
    assert conn.rolled_back is transactional


def test_application_failure_without_active_transaction_is_wrapped():
    with pytest.raises(MigrationError, match="failed applying migration v12"):
        registry.apply_migrations(
            _MigrationFailureConnection(), source_schema=11, target_schema=12)


def test_noop_migration_covers_optional_verify_paths(tmp_path, monkeypatch):
    store = Store(str(tmp_path / "optional-verify.db"))
    migration = Migration.create(13, "optional_verify", "CREATE TABLE optional_verify(id INTEGER);")
    monkeypatch.setattr(
        registry, "_MIGRATIONS", (*registry.registered_migrations(), migration))
    try:
        assert registry.apply_migrations(
            store.conn, source_schema=12, target_schema=13) == (13,)
        assert store.scalar(
            "SELECT COUNT(*) FROM sqlite_master WHERE name='optional_verify'") == 1
    finally:
        store.close()


def test_empty_registry_can_adopt_unknown_source_schema():
    conn = sqlite3.connect(":memory:")
    try:
        assert registry.apply_migrations(
            conn, source_schema=None, target_schema=11) == ()
        assert conn.execute(
            "SELECT source_schema FROM schema_migrations WHERE version=11").fetchone()[0] == 11
    finally:
        conn.close()


@pytest.mark.parametrize(
    "connection,match",
    [
        (_VerifyConnection(missing={"comm_messages"}), "missing tables"),
        (_VerifyConnection(foreign_keys=[("child", 1, "parent", 0)]), "foreign-key"),
        (_VerifyConnection(audiences=1), "audience invariant"),
        (_VerifyConnection(outcomes=1), "delivery provenance"),
    ],
)
def test_schema_twelve_verifier_fails_closed_for_each_invariant(connection, match):
    with pytest.raises(RuntimeError, match=match):
        verify(connection)


def test_schema_twelve_verifier_accepts_complete_consistent_shape():
    verify(_VerifyConnection())
