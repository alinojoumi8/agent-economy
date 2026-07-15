"""Ordered, fail-closed PostgreSQL migrations for the hosted catalog."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from time import monotonic
from typing import Any, Callable, Iterator, Sequence


MIGRATION_FILE_RE = re.compile(r"^(?P<version>[0-9]{3})_(?P<name>[a-z0-9_]+)\.sql$")
DEFAULT_MIGRATIONS_DIR = Path(__file__).with_name("migrations")
TENANT_TABLES = (
    "tenants",
    "memberships",
    "sessions",
    "invitations",
    "runs",
    "audit_log",
    "auth_attempts",
)


class MigrationError(RuntimeError):
    """The database migration history or security posture is unsafe."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    checksum_sha256: str
    sql: str
    path: Path


@dataclass(frozen=True)
class MigrationReport:
    current_version: int
    applied_versions: tuple[int, ...]
    elapsed_seconds: float


@dataclass(frozen=True)
class CredentialRotationReport:
    administrator_role: str
    runtime_role: str
    supervisor_role: str


def load_migrations(directory: str | Path = DEFAULT_MIGRATIONS_DIR) -> tuple[Migration, ...]:
    root = Path(directory)
    if not root.is_dir():
        raise MigrationError(f"migration directory does not exist: {root}")
    migrations: list[Migration] = []
    unexpected = [path.name for path in root.iterdir() if path.is_file() and not MIGRATION_FILE_RE.fullmatch(path.name)]
    if unexpected:
        raise MigrationError(f"unexpected migration filenames: {', '.join(sorted(unexpected))}")
    for path in sorted(root.glob("*.sql")):
        match = MIGRATION_FILE_RE.fullmatch(path.name)
        if match is None:  # guarded above; keeps type checkers honest
            continue
        raw = path.read_bytes()
        # Git checkouts may materialize the same committed text with LF or
        # CRLF. Migration identity must be repository-content stable across
        # Windows/Linux, while every other byte remains exact and fail-closed.
        canonical = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        migrations.append(
            Migration(
                version=int(match.group("version")),
                name=match.group("name"),
                checksum_sha256=hashlib.sha256(canonical).hexdigest(),
                sql=canonical.decode("utf-8"),
                path=path,
            )
        )
    if not migrations:
        raise MigrationError("no hosted database migrations were found")
    versions = [item.version for item in migrations]
    expected = list(range(1, len(migrations) + 1))
    if versions != expected:
        raise MigrationError(f"migration versions must be contiguous from 001; found {versions}")
    return tuple(migrations)


def _execute(connection: Any, sql: Any, params: Sequence[Any] = ()) -> Any:
    if hasattr(connection, "execute"):
        return connection.execute(sql, tuple(params))
    cursor = connection.cursor()
    cursor.execute(sql, tuple(params))
    return cursor


@contextmanager
def _transaction(connection: Any) -> Iterator[None]:
    transaction = getattr(connection, "transaction", None)
    if callable(transaction):
        with transaction():
            yield
        return
    _execute(connection, "BEGIN")
    try:
        yield
    except BaseException:
        connection.rollback()
        raise
    else:
        connection.commit()


def _rows(cursor: Any) -> list[Any]:
    fetched = cursor.fetchall()
    return list(fetched)


def _column(row: Any, name: str, index: int) -> Any:
    if isinstance(row, dict):
        return row[name]
    try:
        return row[name]
    except (TypeError, KeyError, IndexError):
        return row[index]


def _validate_applied_history(rows: Sequence[Any], migrations: Sequence[Migration]) -> set[int]:
    by_version = {item.version: item for item in migrations}
    applied: set[int] = set()
    for row in rows:
        version = int(_column(row, "version", 0))
        name = str(_column(row, "name", 1))
        checksum = str(_column(row, "checksum_sha256", 2))
        expected = by_version.get(version)
        if expected is None:
            raise MigrationError(f"database contains unknown future migration version {version:03d}")
        if name != expected.name or checksum != expected.checksum_sha256:
            raise MigrationError(f"database migration {version:03d} does not exactly match this build")
        applied.add(version)
    ordered = sorted(applied)
    if ordered != list(range(1, len(ordered) + 1)):
        raise MigrationError(f"database migration history is not a contiguous prefix: {ordered}")
    return applied


def _assert_runtime_role_safe(connection: Any, runtime_role: str) -> None:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", runtime_role):
        raise MigrationError("runtime role must be a PostgreSQL identifier")
    cursor = _execute(
        connection,
        "SELECT rolsuper, rolbypassrls FROM pg_catalog.pg_roles WHERE rolname = %s",
        (runtime_role,),
    )
    row = cursor.fetchone()
    if row is None:
        raise MigrationError(f"configured runtime role does not exist: {runtime_role}")
    superuser = bool(_column(row, "rolsuper", 0))
    bypass_rls = bool(_column(row, "rolbypassrls", 1))
    if superuser or bypass_rls:
        raise MigrationError(
            f"runtime role {runtime_role} must be NOSUPERUSER and NOBYPASSRLS"
        )


def _database_password(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not 16 <= len(value) <= 1024:
        raise MigrationError(f"{label} must contain between 16 and 1024 characters")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise MigrationError(f"{label} must not contain control characters")
    return value


def _scram_verifier(connection: Any, password: str, role: str) -> str:
    pg_connection = getattr(connection, "pgconn", None)
    encrypt = getattr(pg_connection, "encrypt_password", None)
    if not callable(encrypt):
        raise MigrationError("database driver cannot generate SCRAM password verifiers")
    try:
        encoded = encrypt(
            password.encode("utf-8"),
            role.encode("utf-8"),
            b"scram-sha-256",
        )
        verifier = bytes(encoded).decode("ascii")
    except Exception:
        raise MigrationError("database driver could not generate a SCRAM verifier") from None
    if not verifier.startswith("SCRAM-SHA-256$") or len(verifier) > 1024:
        raise MigrationError("database driver returned an invalid SCRAM verifier")
    return verifier


def _alter_role_password(connection: Any, role: str, password: str) -> None:
    try:
        from psycopg import sql
    except ImportError as exc:  # pragma: no cover - deployment preflight
        raise MigrationError("database password rotation requires psycopg") from exc
    verifier = _scram_verifier(connection, password, role)
    statement = sql.SQL("ALTER ROLE {} PASSWORD {}").format(
        sql.Identifier(role),
        sql.Literal(verifier),
    )
    _execute(connection, statement)


def _assert_rls_forced(connection: Any) -> None:
    cursor = _execute(
        connection,
        "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity "
        "FROM pg_catalog.pg_class AS c "
        "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
        "WHERE n.nspname = current_schema() AND c.relname = ANY(%s) "
        "ORDER BY c.relname",
        (list(TENANT_TABLES),),
    )
    rows = _rows(cursor)
    state = {
        str(_column(row, "relname", 0)): (
            bool(_column(row, "relrowsecurity", 1)),
            bool(_column(row, "relforcerowsecurity", 2)),
        )
        for row in rows
    }
    missing_or_unsafe = [name for name in TENANT_TABLES if state.get(name) != (True, True)]
    if missing_or_unsafe:
        raise MigrationError(
            "tenant tables must have enabled and forced row security: "
            + ", ".join(missing_or_unsafe)
        )


def _grant_runtime_access(
    connection: Any, runtime_role: str, supervisor_role: str
) -> None:
    # Roles have already passed the strict PostgreSQL-identifier check. Reset
    # grants first so a formerly broad web role cannot retain run discovery.
    quoted_role = f'"{runtime_role}"'
    quoted_supervisor = f'"{supervisor_role}"'
    _execute(connection, "REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    for role in (quoted_role, quoted_supervisor):
        _execute(connection, f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {role}")
        _execute(connection, f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {role}")
        _execute(
            connection,
            "REVOKE ALL ON FUNCTION hosted_active_session_tenant(text), "
            "hosted_active_invitation_tenant(text), hosted_active_run_scopes(), "
            "hosted_transfer_run_owner(uuid, uuid, uuid) "
            f"FROM {role}",
        )
        _execute(connection, f"GRANT USAGE ON SCHEMA public TO {role}")
    _execute(
        connection,
        "GRANT SELECT ON TABLE tenants, users, memberships, sessions, invitations, runs "
        f"TO {quoted_role}",
    )
    _execute(
        connection,
        "GRANT INSERT ON TABLE users "
        f"TO {quoted_role}",
    )
    _execute(
        connection,
        "GRANT INSERT, UPDATE ON TABLE memberships, sessions, invitations "
        f"TO {quoted_role}",
    )
    _execute(connection, f"GRANT SELECT, INSERT ON TABLE auth_attempts TO {quoted_role}")
    _execute(connection, f"GRANT INSERT ON TABLE audit_log TO {quoted_role}")
    # append_auth_audit uses INSERT ... RETURNING id. PostgreSQL requires a
    # SELECT privilege on every RETURNING column even when INSERT is granted.
    # Keep that privilege column-scoped so the web role cannot read audit rows.
    _execute(connection, f"GRANT SELECT (id) ON TABLE audit_log TO {quoted_role}")
    _execute(
        connection,
        "GRANT USAGE, SELECT ON SEQUENCE audit_log_id_seq, auth_attempts_id_seq "
        f"TO {quoted_role}",
    )
    _execute(
        connection,
        "GRANT EXECUTE ON FUNCTION hosted_active_session_tenant(text), "
        "hosted_active_invitation_tenant(text), "
        "hosted_transfer_run_owner(uuid, uuid, uuid) "
        f"TO {quoted_role}",
    )
    _execute(connection, f"GRANT SELECT, INSERT, UPDATE ON TABLE runs TO {quoted_supervisor}")
    _execute(
        connection,
        "GRANT EXECUTE ON FUNCTION hosted_active_run_scopes() "
        f"TO {quoted_supervisor}",
    )


def migrate_connection(
    connection: Any,
    *,
    runtime_role: str,
    supervisor_role: str = "agent_economy_supervisor",
    lock_key: int = 7_321_104_221,
    migrations_dir: str | Path = DEFAULT_MIGRATIONS_DIR,
) -> MigrationReport:
    """Apply all migrations atomically while holding a transaction advisory lock."""

    migrations = load_migrations(migrations_dir)
    started = monotonic()
    newly_applied: list[int] = []
    with _transaction(connection):
        _execute(connection, "SELECT pg_advisory_xact_lock(%s)", (int(lock_key),))
        _execute(
            connection,
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version integer PRIMARY KEY CHECK (version > 0), "
            "name text NOT NULL UNIQUE, "
            "checksum_sha256 character(64) NOT NULL, "
            "applied_at timestamptz NOT NULL DEFAULT clock_timestamp())",
        )
        history = _rows(
            _execute(
                connection,
                "SELECT version, name, checksum_sha256 FROM schema_migrations ORDER BY version",
            )
        )
        applied = _validate_applied_history(history, migrations)
        for migration in migrations:
            if migration.version in applied:
                continue
            _execute(connection, migration.sql)
            _execute(
                connection,
                "INSERT INTO schema_migrations (version, name, checksum_sha256) VALUES (%s, %s, %s)",
                (migration.version, migration.name, migration.checksum_sha256),
            )
            newly_applied.append(migration.version)
        _assert_runtime_role_safe(connection, runtime_role)
        _assert_runtime_role_safe(connection, supervisor_role)
        if runtime_role == supervisor_role:
            raise MigrationError("runtime and supervisor roles must be distinct")
        _assert_rls_forced(connection)
        _grant_runtime_access(connection, runtime_role, supervisor_role)
    return MigrationReport(
        current_version=migrations[-1].version,
        applied_versions=tuple(newly_applied),
        elapsed_seconds=monotonic() - started,
    )


def _default_connect(dsn: str, *, connect_timeout_seconds: int) -> Any:
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:  # pragma: no cover - exercised by deployment preflight
        raise MigrationError(
            "hosted PostgreSQL support requires psycopg; install the hosted dependencies"
        ) from exc
    return psycopg.connect(dsn, connect_timeout=connect_timeout_seconds, row_factory=dict_row)


def migrate(
    dsn: str,
    *,
    runtime_role: str,
    supervisor_role: str = "agent_economy_supervisor",
    lock_key: int = 7_321_104_221,
    connect_timeout_seconds: int = 10,
    migrations_dir: str | Path = DEFAULT_MIGRATIONS_DIR,
    connect: Callable[[str], Any] | None = None,
) -> MigrationReport:
    """Connect, apply hosted migrations, and close the migrator connection."""

    connection = (
        connect(dsn)
        if connect is not None
        else _default_connect(dsn, connect_timeout_seconds=connect_timeout_seconds)
    )
    try:
        return migrate_connection(
            connection,
            runtime_role=runtime_role,
            supervisor_role=supervisor_role,
            lock_key=lock_key,
            migrations_dir=migrations_dir,
        )
    finally:
        connection.close()


def rotate_database_passwords_connection(
    connection: Any,
    *,
    runtime_role: str,
    runtime_password: str,
    supervisor_role: str,
    supervisor_password: str,
    administrator_password: str,
) -> CredentialRotationReport:
    """Atomically rotate the three reference-deployment database identities."""

    runtime_secret = _database_password(runtime_password, label="runtime password")
    supervisor_secret = _database_password(
        supervisor_password, label="supervisor password"
    )
    administrator_secret = _database_password(
        administrator_password, label="administrator password"
    )
    if len({runtime_secret, supervisor_secret, administrator_secret}) != 3:
        raise MigrationError("database role passwords must be distinct")

    with _transaction(connection):
        _assert_runtime_role_safe(connection, runtime_role)
        _assert_runtime_role_safe(connection, supervisor_role)
        if runtime_role == supervisor_role:
            raise MigrationError("runtime and supervisor roles must be distinct")
        current = _execute(connection, "SELECT current_user").fetchone()
        if current is None:
            raise MigrationError("database administrator identity is unavailable")
        administrator_role = str(_column(current, "current_user", 0))
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", administrator_role):
            raise MigrationError("database administrator role is invalid")
        if administrator_role in {runtime_role, supervisor_role}:
            raise MigrationError("database administrator must be a distinct role")

        # libpq generates SCRAM verifiers locally. Only verifiers—not raw
        # passwords—enter the ALTER ROLE statements or potential SQL logging.
        _alter_role_password(connection, runtime_role, runtime_secret)
        _alter_role_password(connection, supervisor_role, supervisor_secret)
        _alter_role_password(connection, administrator_role, administrator_secret)
    return CredentialRotationReport(
        administrator_role=administrator_role,
        runtime_role=runtime_role,
        supervisor_role=supervisor_role,
    )


def rotate_database_passwords(
    dsn: str,
    *,
    runtime_role: str,
    runtime_password: str,
    supervisor_role: str,
    supervisor_password: str,
    administrator_password: str,
    connect_timeout_seconds: int = 10,
    connect: Callable[[str], Any] | None = None,
) -> CredentialRotationReport:
    """Connect with the current administrator credential and rotate roles."""

    connection = (
        connect(dsn)
        if connect is not None
        else _default_connect(dsn, connect_timeout_seconds=connect_timeout_seconds)
    )
    try:
        return rotate_database_passwords_connection(
            connection,
            runtime_role=runtime_role,
            runtime_password=runtime_password,
            supervisor_role=supervisor_role,
            supervisor_password=supervisor_password,
            administrator_password=administrator_password,
        )
    finally:
        connection.close()
