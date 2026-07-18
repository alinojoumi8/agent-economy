"""Transactional SQLite migration application with immutable checksums."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Callable, Iterable, Optional

from . import v012_communications


class MigrationError(RuntimeError):
    """Raised when migration history is missing, altered, or cannot apply atomically."""


def _normalize_sql(sql: str) -> str:
    return sql.replace("\r\n", "\n").replace("\r", "\n").strip() + "\n"


def migration_checksum(sql: str) -> str:
    return hashlib.sha256(_normalize_sql(sql).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str
    checksum_sha256: str
    verify: Optional[Callable] = None

    @classmethod
    def create(cls, version: int, name: str, sql: str, verify=None) -> "Migration":
        return cls(version, name, _normalize_sql(sql), migration_checksum(sql), verify)


_MIGRATIONS = (
    Migration.create(
        12, v012_communications.NAME, v012_communications.SQL,
        verify=v012_communications.verify),
)


def registered_migrations() -> tuple[Migration, ...]:
    return _MIGRATIONS


_LEDGER_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version         INTEGER PRIMARY KEY CHECK(version > 0),
    name            TEXT NOT NULL UNIQUE,
    checksum_sha256 TEXT NOT NULL CHECK(length(checksum_sha256)=64),
    source_schema   INTEGER NOT NULL CHECK(source_schema >= 0),
    status          TEXT NOT NULL CHECK(status IN ('applied','adopted_legacy')),
    applied_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""


def _history(conn) -> list[tuple[int, str, str, int, str]]:
    return [tuple(row) for row in conn.execute(
        "SELECT version,name,checksum_sha256,source_schema,status "
        "FROM schema_migrations ORDER BY version")]


def _validate_history(rows: Iterable[tuple], migrations: tuple[Migration, ...]) -> set[int]:
    known = {migration.version: migration for migration in migrations}
    applied: set[int] = set()
    for raw in rows:
        version, name, checksum, _source_schema, status = raw
        version = int(version)
        if status == "adopted_legacy":
            if version != 11 or name != "legacy_schema_v11":
                raise MigrationError(f"unknown legacy migration history v{version} {name!r}")
            applied.add(version)
            continue
        migration = known.get(version)
        if migration is None:
            raise MigrationError(f"unknown future migration history v{version} {name!r}")
        if name != migration.name or checksum != migration.checksum_sha256:
            raise MigrationError(f"migration checksum mismatch for v{version} {name!r}")
        applied.add(version)
    return applied


def apply_migrations(conn, *, source_schema: int | None, target_schema: int) -> tuple[int, ...]:
    """Verify history and apply registered migrations through ``target_schema``."""
    conn.execute(_LEDGER_SQL)
    migrations = tuple(m for m in _MIGRATIONS if m.version <= target_schema)
    rows = _history(conn)
    if not rows:
        source = 11 if source_schema is None else min(int(source_schema), 11)
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                "INSERT INTO schema_migrations "
                "(version,name,checksum_sha256,source_schema,status) VALUES (11,?,?,?,'adopted_legacy')",
                ("legacy_schema_v11", hashlib.sha256(b"legacy-schema-v11\n").hexdigest(), source),
            )
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        rows = _history(conn)
    applied = _validate_history(rows, migrations)
    newly_applied: list[int] = []
    for migration in migrations:
        if migration.version in applied:
            continue
        source = max(applied) if applied else (source_schema or 0)
        checksum = migration.checksum_sha256
        try:
            conn.executescript("BEGIN IMMEDIATE;\n" + migration.sql)
            if migration.verify is not None:
                migration.verify(conn)
            conn.execute(
                "INSERT INTO schema_migrations "
                "(version,name,checksum_sha256,source_schema,status) VALUES (?,?,?,?,?)",
                (migration.version, migration.name, checksum, int(source), "applied"),
            )
            conn.execute("COMMIT")
        except Exception as exc:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise MigrationError(
                f"failed applying migration v{migration.version} {migration.name}: {exc}") from exc
        applied.add(migration.version)
        newly_applied.append(migration.version)
    _validate_history(_history(conn), migrations)
    for migration in migrations:
        if migration.verify is not None:
            migration.verify(conn)
    return tuple(newly_applied)
