"""Typed, tenant-scoped access to the R22 PostgreSQL control plane."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import re
from typing import Any, Callable, Iterator, Mapping, Sequence
from uuid import UUID, uuid4

from .migrations import _transaction


# set_config(..., true) is PostgreSQL's parameter-safe equivalent of
# ``SET LOCAL app.tenant_id = '<uuid>'`` and lasts only for this transaction.
TENANT_CONTEXT_SQL = "SELECT set_config('app.tenant_id', %s, true)"
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_RUN_STATUSES = {"created", "starting", "running", "paused", "snapshot_failed", "stopped", "failed", "archived"}
_ACTIVE_RUN_STATUSES = {"starting", "running", "paused", "snapshot_failed"}


class CatalogError(RuntimeError):
    pass


class CatalogConflict(CatalogError):
    pass


@dataclass(frozen=True)
class TenantRecord:
    id: UUID
    slug: str
    display_name: str
    status: str


@dataclass(frozen=True)
class UserRecord:
    id: UUID
    email_normalized: str
    display_name: str
    password_hash: str
    disabled_at: datetime | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class MembershipRecord:
    tenant_id: UUID
    user_id: UUID
    role: str
    status: str


@dataclass(frozen=True)
class SessionRecord:
    id: UUID
    tenant_id: UUID
    user_id: UUID
    token_hash: str
    csrf_secret_hash: str
    expires_at: datetime
    revoked_at: datetime | None
    created_at: datetime | None = None


@dataclass(frozen=True)
class InvitationRecord:
    id: UUID
    tenant_id: UUID
    email_normalized: str
    role: str
    token_hash: str
    invited_by_user_id: UUID
    expires_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime | None = None


@dataclass(frozen=True)
class LoginThrottleReservation:
    """One atomically serialized login attempt across both throttle scopes."""

    tenant_active: bool
    account_failures: tuple[datetime, ...] = ()
    client_account_failures: tuple[datetime, ...] = ()
    reserved: bool = False


@dataclass(frozen=True)
class RunRecord:
    id: UUID
    tenant_id: UUID
    owner_user_id: UUID
    run_key: str
    display_name: str
    status: str
    schema_version: int
    engine_semantics_version: int
    catalog: Mapping[str, Any]
    snapshot_object_key: str | None
    snapshot_sha256: str | None
    snapshot_size_bytes: int | None
    writer_lease_owner: str | None
    writer_lease_token: UUID | None
    writer_lease_expires_at: datetime | None


def _uuid(value: UUID | str, *, label: str) -> UUID:
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"{label} must be a UUID") from exc


def _hash(value: str, *, label: str) -> str:
    normalized = str(value).lower()
    if not _HASH_RE.fullmatch(normalized):
        raise ValueError(f"{label} must be a lowercase SHA-256 hex digest")
    return normalized


def _advisory_lock_key(value: str) -> int:
    """Map a validated digest to PostgreSQL's signed 64-bit advisory key."""

    unsigned = int(value[:16], 16)
    return unsigned - (1 << 64) if unsigned >= (1 << 63) else unsigned


def _scope_advisory_lock_key(namespace: str, *values: object) -> int:
    digest = hashlib.sha256(
        "\x00".join((namespace, *(str(value) for value in values))).encode("utf-8")
    ).hexdigest()
    return _advisory_lock_key(digest)


def _email(value: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) > 320 or normalized.count("@") != 1:
        raise ValueError("invalid normalized email address")
    return normalized


def _role(value: str) -> str:
    if value not in {"observer", "admin"}:
        raise ValueError("membership role must be observer or admin")
    return value


def _row_value(row: Any, name: str, index: int | None = None) -> Any:
    if isinstance(row, Mapping):
        return row[name]
    try:
        return row[name]
    except (TypeError, KeyError, IndexError):
        if index is None:
            raise CatalogError("catalog connection must return mapping rows")
        return row[index]


def _optional_row_value(row: Any, name: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(name, default)
    try:
        return row[name]
    except (TypeError, KeyError, IndexError):
        return default


def _one(cursor: Any) -> Any | None:
    return cursor.fetchone()


def _json_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, Mapping):
        raise CatalogError("catalog_json must decode to an object")
    return dict(value)


def _run(row: Any) -> RunRecord:
    lease_token = _row_value(row, "writer_lease_token")
    return RunRecord(
        id=_uuid(_row_value(row, "id"), label="run id"),
        tenant_id=_uuid(_row_value(row, "tenant_id"), label="tenant id"),
        owner_user_id=_uuid(_row_value(row, "owner_user_id"), label="owner user id"),
        run_key=str(_row_value(row, "run_key")),
        display_name=str(_row_value(row, "display_name")),
        status=str(_row_value(row, "status")),
        schema_version=int(_row_value(row, "schema_version")),
        engine_semantics_version=int(_row_value(row, "engine_semantics_version")),
        catalog=_json_mapping(_row_value(row, "catalog_json")),
        snapshot_object_key=_row_value(row, "snapshot_object_key"),
        snapshot_sha256=_row_value(row, "snapshot_sha256"),
        snapshot_size_bytes=_row_value(row, "snapshot_size_bytes"),
        writer_lease_owner=_row_value(row, "writer_lease_owner"),
        writer_lease_token=_uuid(lease_token, label="writer lease token") if lease_token else None,
        writer_lease_expires_at=_row_value(row, "writer_lease_expires_at"),
    )


def _session(row: Any) -> SessionRecord:
    return SessionRecord(
        id=_uuid(_row_value(row, "id"), label="session id"),
        tenant_id=_uuid(_row_value(row, "tenant_id"), label="tenant id"),
        user_id=_uuid(_row_value(row, "user_id"), label="user id"),
        token_hash=str(_row_value(row, "token_hash")),
        csrf_secret_hash=str(_row_value(row, "csrf_secret_hash")),
        expires_at=_row_value(row, "expires_at"),
        revoked_at=_row_value(row, "revoked_at"),
        created_at=_optional_row_value(row, "created_at"),
    )


def _invitation(row: Any) -> InvitationRecord:
    return InvitationRecord(
        id=_uuid(_row_value(row, "id"), label="invitation id"),
        tenant_id=_uuid(_row_value(row, "tenant_id"), label="tenant id"),
        email_normalized=str(_row_value(row, "email_normalized")),
        role=str(_row_value(row, "role")),
        token_hash=str(_row_value(row, "token_hash")),
        invited_by_user_id=_uuid(_row_value(row, "invited_by_user_id"), label="inviter user id"),
        expires_at=_row_value(row, "expires_at"),
        accepted_at=_row_value(row, "accepted_at"),
        revoked_at=_row_value(row, "revoked_at"),
        created_at=_optional_row_value(row, "created_at"),
    )


class HostedCatalog:
    """Small transaction-oriented catalog; it never exposes an unscoped query API."""

    def __init__(
        self,
        dsn: str,
        *,
        connect: Callable[[str], Any] | None = None,
        pool: Any | None = None,
        expected_role: str | None = None,
        capability: str = "web",
        forbidden_role: str | None = None,
        connect_timeout_seconds: int = 10,
    ):
        if not dsn.strip():
            raise ValueError("catalog DSN must not be empty")
        if connect is not None and pool is not None:
            raise ValueError("catalog accepts either connect or pool, not both")
        if (
            isinstance(connect_timeout_seconds, bool)
            or not isinstance(connect_timeout_seconds, int)
            or not (1 <= connect_timeout_seconds <= 300)
        ):
            raise ValueError("catalog connect timeout must be between 1 and 300 seconds")
        if expected_role is not None and re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]{0,62}", expected_role
        ) is None:
            raise ValueError("expected database role must be a PostgreSQL identifier")
        if capability not in {"web", "supervisor"}:
            raise ValueError("catalog capability must be web or supervisor")
        if forbidden_role is not None and re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]{0,62}", forbidden_role
        ) is None:
            raise ValueError("forbidden database role must be a PostgreSQL identifier")
        self._dsn = dsn
        self.connect_timeout_seconds = connect_timeout_seconds
        self._connect = connect or (
            lambda value: self._default_connect(
                value, connect_timeout_seconds=self.connect_timeout_seconds
            )
        )
        self._pool = pool
        self.expected_role = expected_role
        self.capability = capability
        self.forbidden_role = forbidden_role

    @staticmethod
    def _default_connect(dsn: str, *, connect_timeout_seconds: int = 10) -> Any:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:  # pragma: no cover - deployment preflight path
            raise CatalogError(
                "hosted PostgreSQL support requires psycopg; install the hosted dependencies"
            ) from exc
        return psycopg.connect(
            dsn,
            connect_timeout=connect_timeout_seconds,
            row_factory=dict_row,
        )

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        if self._pool is not None:
            with self._pool.connection() as connection:
                yield connection
            return
        connection = self._connect(self._dsn)
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def tenant_transaction(self, tenant_id: UUID | str) -> Iterator[Any]:
        """Open one default-deny transaction scoped to exactly one tenant."""

        tenant = _uuid(tenant_id, label="tenant id")
        with self._connection() as connection:
            with _transaction(connection):
                connection.execute(TENANT_CONTEXT_SQL, (str(tenant),))
                yield connection

    def create_tenant_with_admin(
        self,
        *,
        slug: str,
        tenant_name: str,
        email: str,
        user_name: str,
        password_hash: str,
        tenant_id: UUID | None = None,
        user_id: UUID | None = None,
    ) -> tuple[TenantRecord, UserRecord, MembershipRecord]:
        tenant = tenant_id or uuid4()
        user = user_id or uuid4()
        normalized_slug = slug.strip().lower()
        normalized_email = _email(email)
        with self.tenant_transaction(tenant) as connection:
            tenant_row = _one(connection.execute(
                "INSERT INTO tenants (id, slug, display_name) VALUES (%s, %s, %s) "
                "RETURNING id, slug, display_name, status",
                (str(tenant), normalized_slug, tenant_name.strip()),
            ))
            user_row = _one(connection.execute(
                "INSERT INTO users (id, email_normalized, display_name, password_hash) "
                "VALUES (%s, %s, %s, %s) "
                "RETURNING id, email_normalized, display_name, password_hash, disabled_at, created_at",
                (str(user), normalized_email, user_name.strip(), password_hash),
            ))
            membership_row = _one(connection.execute(
                "INSERT INTO memberships (tenant_id, user_id, role) VALUES (%s, %s, 'admin') "
                "RETURNING tenant_id, user_id, role, status",
                (str(tenant), str(user)),
            ))
        if tenant_row is None or user_row is None or membership_row is None:
            raise CatalogError("tenant bootstrap did not return inserted records")
        return (
            TenantRecord(
                id=_uuid(_row_value(tenant_row, "id"), label="tenant id"),
                slug=str(_row_value(tenant_row, "slug")),
                display_name=str(_row_value(tenant_row, "display_name")),
                status=str(_row_value(tenant_row, "status")),
            ),
            UserRecord(
                id=_uuid(_row_value(user_row, "id"), label="user id"),
                email_normalized=str(_row_value(user_row, "email_normalized")),
                display_name=str(_row_value(user_row, "display_name")),
                password_hash=str(_row_value(user_row, "password_hash")),
                disabled_at=_row_value(user_row, "disabled_at"),
                created_at=_optional_row_value(user_row, "created_at"),
            ),
            MembershipRecord(
                tenant_id=_uuid(_row_value(membership_row, "tenant_id"), label="tenant id"),
                user_id=_uuid(_row_value(membership_row, "user_id"), label="user id"),
                role=str(_row_value(membership_row, "role")),
                status=str(_row_value(membership_row, "status")),
            ),
        )

    def get_tenant(self, tenant_id: UUID | str) -> TenantRecord | None:
        """Resolve one tenant through the same default-deny RLS scope."""

        tenant = _uuid(tenant_id, label="tenant id")
        with self.tenant_transaction(tenant) as connection:
            row = _one(connection.execute(
                "SELECT id, slug, display_name, status FROM tenants WHERE id = %s",
                (str(tenant),),
            ))
        if row is None:
            return None
        return TenantRecord(
            id=_uuid(_row_value(row, "id"), label="tenant id"),
            slug=str(_row_value(row, "slug")),
            display_name=str(_row_value(row, "display_name")),
            status=str(_row_value(row, "status")),
        )

    def find_user_by_email(self, email: str) -> UserRecord | None:
        """Lookup the global login identity; membership checks remain tenant-scoped."""

        with self._connection() as connection:
            with _transaction(connection):
                row = _one(connection.execute(
                    "SELECT id, email_normalized, display_name, password_hash, disabled_at, created_at "
                    "FROM users WHERE email_normalized = %s",
                    (_email(email),),
                ))
        if row is None:
            return None
        return UserRecord(
            id=_uuid(_row_value(row, "id"), label="user id"),
            email_normalized=str(_row_value(row, "email_normalized")),
            display_name=str(_row_value(row, "display_name")),
            password_hash=str(_row_value(row, "password_hash")),
            disabled_at=_row_value(row, "disabled_at"),
            created_at=_optional_row_value(row, "created_at"),
        )

    # Authentication adapters commonly use this spelling.
    get_user_by_email = find_user_by_email

    def get_user_by_id(self, user_id: UUID | str) -> UserRecord | None:
        user = _uuid(user_id, label="user id")
        with self._connection() as connection:
            with _transaction(connection):
                row = _one(connection.execute(
                    "SELECT id, email_normalized, display_name, password_hash, disabled_at, created_at "
                    "FROM users WHERE id = %s",
                    (str(user),),
                ))
        if row is None:
            return None
        return UserRecord(
            id=_uuid(_row_value(row, "id"), label="user id"),
            email_normalized=str(_row_value(row, "email_normalized")),
            display_name=str(_row_value(row, "display_name")),
            password_hash=str(_row_value(row, "password_hash")),
            disabled_at=_row_value(row, "disabled_at"),
            created_at=_optional_row_value(row, "created_at"),
        )

    def create_user(
        self,
        *,
        email: str,
        display_name: str,
        password_hash: str,
        user_id: UUID | None = None,
    ) -> UserRecord:
        user = user_id or uuid4()
        normalized_email = _email(email)
        if not display_name.strip() or not password_hash:
            raise ValueError("user display name and password hash must not be empty")
        with self._connection() as connection:
            with _transaction(connection):
                row = _one(connection.execute(
                    "INSERT INTO users (id, email_normalized, display_name, password_hash) "
                    "VALUES (%s, %s, %s, %s) "
                    "RETURNING id, email_normalized, display_name, password_hash, disabled_at, created_at",
                    (str(user), normalized_email, display_name.strip(), password_hash),
                ))
        if row is None:
            raise CatalogError("user insert returned no record")
        return UserRecord(
            id=_uuid(_row_value(row, "id"), label="user id"),
            email_normalized=str(_row_value(row, "email_normalized")),
            display_name=str(_row_value(row, "display_name")),
            password_hash=str(_row_value(row, "password_hash")),
            disabled_at=_row_value(row, "disabled_at"),
            created_at=_optional_row_value(row, "created_at"),
        )

    def get_membership(self, tenant_id: UUID | str, user_id: UUID | str) -> MembershipRecord | None:
        tenant = _uuid(tenant_id, label="tenant id")
        user = _uuid(user_id, label="user id")
        with self.tenant_transaction(tenant) as connection:
            row = _one(connection.execute(
                "SELECT tenant_id, user_id, role, status FROM memberships "
                "WHERE tenant_id = %s AND user_id = %s",
                (str(tenant), str(user)),
            ))
        if row is None:
            return None
        return MembershipRecord(
            tenant_id=_uuid(_row_value(row, "tenant_id"), label="tenant id"),
            user_id=_uuid(_row_value(row, "user_id"), label="user id"),
            role=str(_row_value(row, "role")),
            status=str(_row_value(row, "status")),
        )

    def create_membership(
        self, tenant_id: UUID | str, user_id: UUID | str, *, role: str
    ) -> MembershipRecord:
        tenant = _uuid(tenant_id, label="tenant id")
        user = _uuid(user_id, label="user id")
        membership_role = _role(role)
        with self.tenant_transaction(tenant) as connection:
            row = _one(connection.execute(
                "INSERT INTO memberships (tenant_id, user_id, role) VALUES (%s, %s, %s) "
                "RETURNING tenant_id, user_id, role, status",
                (str(tenant), str(user), membership_role),
            ))
        if row is None:
            raise CatalogError("membership insert returned no record")
        return MembershipRecord(
            tenant_id=_uuid(_row_value(row, "tenant_id"), label="tenant id"),
            user_id=_uuid(_row_value(row, "user_id"), label="user id"),
            role=str(_row_value(row, "role")),
            status=str(_row_value(row, "status")),
        )

    def list_members(self, tenant_id: UUID | str) -> tuple[MembershipRecord, ...]:
        tenant = _uuid(tenant_id, label="tenant id")
        with self.tenant_transaction(tenant) as connection:
            rows = connection.execute(
                "SELECT tenant_id, user_id, role, status FROM memberships "
                "WHERE tenant_id = %s ORDER BY created_at, user_id",
                (str(tenant),),
            ).fetchall()
        return tuple(
            MembershipRecord(
                tenant_id=_uuid(_row_value(row, "tenant_id"), label="tenant id"),
                user_id=_uuid(_row_value(row, "user_id"), label="user id"),
                role=str(_row_value(row, "role")),
                status=str(_row_value(row, "status")),
            )
            for row in rows
        )

    def update_membership(
        self,
        tenant_id: UUID | str,
        user_id: UUID | str,
        *,
        role: str,
        enabled: bool,
    ) -> MembershipRecord | None:
        tenant = _uuid(tenant_id, label="tenant id")
        user = _uuid(user_id, label="user id")
        membership_role = _role(role)
        status = "active" if enabled else "revoked"
        with self.tenant_transaction(tenant) as connection:
            row = _one(connection.execute(
                "UPDATE memberships SET role = %s, status = %s, updated_at = clock_timestamp() "
                "WHERE tenant_id = %s AND user_id = %s "
                "RETURNING tenant_id, user_id, role, status",
                (membership_role, status, str(tenant), str(user)),
            ))
            if row is not None:
                # An explicit membership decision supersedes every still-live
                # invitation addressed to that identity.  Losing active-admin
                # authority also revokes every invitation the user issued.
                connection.execute(
                    "UPDATE invitations AS i SET revoked_at = clock_timestamp() "
                    "WHERE i.tenant_id = %s AND i.accepted_at IS NULL "
                    "AND i.revoked_at IS NULL AND ("
                    " i.email_normalized = (SELECT u.email_normalized FROM users AS u WHERE u.id = %s)"
                    " OR (%s AND i.invited_by_user_id = %s))",
                    (
                        str(tenant),
                        str(user),
                        status != "active" or membership_role != "admin",
                        str(user),
                    ),
                )
        if row is None:
            return None
        return MembershipRecord(
            tenant_id=_uuid(_row_value(row, "tenant_id"), label="tenant id"),
            user_id=_uuid(_row_value(row, "user_id"), label="user id"),
            role=str(_row_value(row, "role")),
            status=str(_row_value(row, "status")),
        )

    def create_session(
        self,
        tenant_id: UUID | str,
        user_id: UUID | str,
        *,
        token_hash: str,
        csrf_secret_hash: str,
        expires_at: datetime,
        session_id: UUID | None = None,
    ) -> SessionRecord:
        tenant = _uuid(tenant_id, label="tenant id")
        user = _uuid(user_id, label="user id")
        session = session_id or uuid4()
        validated_token_hash = _hash(token_hash, label="session token hash")
        validated_csrf_hash = _hash(csrf_secret_hash, label="CSRF secret hash")
        with self.tenant_transaction(tenant) as connection:
            row = _one(connection.execute(
                "INSERT INTO sessions (id, tenant_id, user_id, token_hash, csrf_secret_hash, expires_at) "
                "SELECT %s, t.id, m.user_id, %s, %s, %s "
                "FROM tenants AS t JOIN memberships AS m "
                "ON m.tenant_id = t.id AND m.user_id = %s "
                "JOIN users AS u ON u.id = m.user_id "
                "WHERE t.id = %s AND t.status = 'active' "
                "AND m.status = 'active' AND m.role IN ('observer', 'admin') "
                "AND u.disabled_at IS NULL "
                "RETURNING id, tenant_id, user_id, token_hash, csrf_secret_hash, expires_at, revoked_at, created_at",
                (
                    str(session), validated_token_hash, validated_csrf_hash, expires_at,
                    str(user), str(tenant),
                ),
            ))
        if row is None:
            raise CatalogConflict("session requires an active tenant membership")
        return _session(row)

    def get_active_session(self, tenant_id: UUID | str, token_hash: str) -> SessionRecord | None:
        tenant = _uuid(tenant_id, label="tenant id")
        with self.tenant_transaction(tenant) as connection:
            row = _one(connection.execute(
                "SELECT s.id, s.tenant_id, s.user_id, s.token_hash, s.csrf_secret_hash, "
                "s.expires_at, s.revoked_at, s.created_at FROM sessions AS s "
                "JOIN tenants AS t ON t.id = s.tenant_id "
                "JOIN memberships AS m ON m.tenant_id = s.tenant_id AND m.user_id = s.user_id "
                "JOIN users AS u ON u.id = s.user_id "
                "WHERE s.tenant_id = %s AND s.token_hash = %s "
                "AND s.revoked_at IS NULL AND s.expires_at > clock_timestamp() "
                "AND t.status = 'active' AND m.status = 'active' "
                "AND m.role IN ('observer', 'admin') AND u.disabled_at IS NULL",
                (str(tenant), _hash(token_hash, label="session token hash")),
            ))
        if row is None:
            return None
        return _session(row)

    def lookup_session_by_hash(self, token_hash: str) -> SessionRecord | None:
        """Resolve an exact credential hash, then read the row under tenant RLS."""

        validated_hash = _hash(token_hash, label="session token hash")
        with self._connection() as connection:
            with _transaction(connection):
                row = _one(connection.execute(
                    "SELECT hosted_active_session_tenant(%s) AS tenant_id",
                    (validated_hash,),
                ))
        tenant_value = None if row is None else _row_value(row, "tenant_id", 0)
        if tenant_value is None:
            return None
        return self.get_active_session(
            _uuid(tenant_value, label="tenant id"), validated_hash
        )

    get_session_by_token_hash = lookup_session_by_hash

    def revoke_session(self, tenant_id: UUID | str, session_id: UUID | str) -> bool:
        tenant = _uuid(tenant_id, label="tenant id")
        session = _uuid(session_id, label="session id")
        with self.tenant_transaction(tenant) as connection:
            cursor = connection.execute(
                "UPDATE sessions SET revoked_at = clock_timestamp() "
                "WHERE tenant_id = %s AND id = %s AND revoked_at IS NULL",
                (str(tenant), str(session)),
            )
            return int(cursor.rowcount) == 1

    def revoke_session_by_hash(self, token_hash: str) -> bool:
        validated_hash = _hash(token_hash, label="session token hash")
        with self._connection() as connection:
            with _transaction(connection):
                row = _one(connection.execute(
                    "SELECT hosted_active_session_tenant(%s) AS tenant_id",
                    (validated_hash,),
                ))
        tenant_value = None if row is None else _row_value(row, "tenant_id", 0)
        if tenant_value is None:
            return False
        tenant = _uuid(tenant_value, label="tenant id")
        with self.tenant_transaction(tenant) as connection:
            cursor = connection.execute(
                "UPDATE sessions SET revoked_at = clock_timestamp() "
                "WHERE tenant_id = %s AND token_hash = %s AND revoked_at IS NULL",
                (str(tenant), validated_hash),
            )
            return int(cursor.rowcount) == 1

    def revoke_user_sessions(self, tenant_id: UUID | str, user_id: UUID | str) -> int:
        tenant = _uuid(tenant_id, label="tenant id")
        user = _uuid(user_id, label="user id")
        with self.tenant_transaction(tenant) as connection:
            cursor = connection.execute(
                "UPDATE sessions SET revoked_at = clock_timestamp() "
                "WHERE tenant_id = %s AND user_id = %s AND revoked_at IS NULL",
                (str(tenant), str(user)),
            )
            return int(cursor.rowcount)

    def create_invitation(
        self,
        tenant_id: UUID | str,
        *,
        email: str,
        role: str,
        token_hash: str,
        invited_by_user_id: UUID | str,
        expires_at: datetime,
        invitation_id: UUID | None = None,
    ) -> InvitationRecord:
        tenant = _uuid(tenant_id, label="tenant id")
        inviter = _uuid(invited_by_user_id, label="inviter user id")
        invitation = invitation_id or uuid4()
        normalized_email = _email(email)
        invitation_role = _role(role)
        validated_token_hash = _hash(token_hash, label="invitation token hash")
        with self.tenant_transaction(tenant) as connection:
            connection.execute(
                "SELECT pg_advisory_xact_lock(%s)",
                (_scope_advisory_lock_key("invitation", tenant, normalized_email),),
            )
            authorized = _one(connection.execute(
                "SELECT t.id FROM tenants AS t JOIN memberships AS inviter "
                "ON inviter.tenant_id = t.id AND inviter.user_id = %s "
                "JOIN users AS inviter_user ON inviter_user.id = inviter.user_id "
                "WHERE t.id = %s AND t.status = 'active' "
                "AND inviter.status = 'active' AND inviter.role = 'admin' "
                "AND inviter_user.disabled_at IS NULL "
                "FOR UPDATE OF inviter",
                (str(inviter), str(tenant)),
            ))
            if authorized is None:
                raise CatalogConflict("invitation requires an active tenant administrator")
            connection.execute(
                "UPDATE invitations SET revoked_at = clock_timestamp() "
                "WHERE tenant_id = %s AND email_normalized = %s "
                "AND accepted_at IS NULL AND revoked_at IS NULL",
                (str(tenant), normalized_email),
            )
            row = _one(connection.execute(
                "INSERT INTO invitations "
                "(id, tenant_id, email_normalized, role, token_hash, invited_by_user_id, expires_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) "
                "RETURNING id, tenant_id, email_normalized, role, token_hash, invited_by_user_id, "
                "expires_at, accepted_at, revoked_at, created_at",
                (
                    str(invitation), str(tenant), normalized_email, invitation_role,
                    validated_token_hash, str(inviter), expires_at,
                ),
            ))
        if row is None:
            raise CatalogError("invitation insert returned no record")
        return _invitation(row)

    def create_invitation_with_audit(
        self,
        tenant_id: UUID | str,
        *,
        email: str,
        role: str,
        token_hash: str,
        invited_by_user_id: UUID | str,
        expires_at: datetime,
        occurred_at: datetime,
        event: str,
        audit_details: Mapping[str, Any],
        invitation_id: UUID | None = None,
    ) -> InvitationRecord:
        """Persist an invitation and its issuance audit in one transaction."""

        tenant = _uuid(tenant_id, label="tenant id")
        inviter = _uuid(invited_by_user_id, label="inviter user id")
        invitation = invitation_id or uuid4()
        normalized_email = _email(email)
        invitation_role = _role(role)
        validated_token_hash = _hash(token_hash, label="invitation token hash")
        details_json = json.dumps(dict(audit_details), sort_keys=True, separators=(",", ":"))
        with self.tenant_transaction(tenant) as connection:
            connection.execute(
                "SELECT pg_advisory_xact_lock(%s)",
                (_scope_advisory_lock_key("invitation", tenant, normalized_email),),
            )
            authorized = _one(connection.execute(
                "SELECT t.id FROM tenants AS t JOIN memberships AS inviter "
                "ON inviter.tenant_id = t.id AND inviter.user_id = %s "
                "JOIN users AS inviter_user ON inviter_user.id = inviter.user_id "
                "WHERE t.id = %s AND t.status = 'active' "
                "AND inviter.status = 'active' AND inviter.role = 'admin' "
                "AND inviter_user.disabled_at IS NULL "
                "FOR UPDATE OF inviter",
                (str(inviter), str(tenant)),
            ))
            if authorized is None:
                raise CatalogConflict("invitation requires an active tenant administrator")
            connection.execute(
                "UPDATE invitations SET revoked_at = %s "
                "WHERE tenant_id = %s AND email_normalized = %s "
                "AND accepted_at IS NULL AND revoked_at IS NULL",
                (occurred_at, str(tenant), normalized_email),
            )
            row = _one(connection.execute(
                "WITH invited AS ("
                " INSERT INTO invitations"
                " (id, tenant_id, email_normalized, role, token_hash, invited_by_user_id, expires_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s)"
                " RETURNING id, tenant_id, email_normalized, role, token_hash, invited_by_user_id,"
                " expires_at, accepted_at, revoked_at, created_at"
                "), audited AS ("
                " INSERT INTO audit_log"
                " (tenant_id, actor_user_id, action, target_type, target_id, details_json, created_at)"
                " SELECT tenant_id, invited_by_user_id, %s, 'invitation', id::text, %s::jsonb, %s"
                " FROM invited RETURNING id"
                ") SELECT invited.* FROM invited CROSS JOIN audited",
                (
                    str(invitation), str(tenant), normalized_email, invitation_role,
                    validated_token_hash, str(inviter), expires_at,
                    event, details_json, occurred_at,
                ),
            ))
        if row is None:
            raise CatalogError("invitation and audit insert returned no record")
        return _invitation(row)

    def lookup_invitation_by_hash(self, token_hash: str) -> InvitationRecord | None:
        validated_hash = _hash(token_hash, label="invitation token hash")
        with self._connection() as connection:
            with _transaction(connection):
                row = _one(connection.execute(
                    "SELECT hosted_active_invitation_tenant(%s) AS tenant_id",
                    (validated_hash,),
                ))
        tenant_value = None if row is None else _row_value(row, "tenant_id", 0)
        if tenant_value is None:
            return None
        tenant = _uuid(tenant_value, label="tenant id")
        with self.tenant_transaction(tenant) as connection:
            invite_row = _one(connection.execute(
                "SELECT i.id, i.tenant_id, i.email_normalized, i.role, i.token_hash, "
                "i.invited_by_user_id, i.expires_at, i.accepted_at, i.revoked_at, i.created_at "
                "FROM invitations AS i JOIN tenants AS t ON t.id = i.tenant_id "
                "JOIN memberships AS inviter ON inviter.tenant_id = i.tenant_id "
                "AND inviter.user_id = i.invited_by_user_id "
                "JOIN users AS inviter_user ON inviter_user.id = i.invited_by_user_id "
                "WHERE i.tenant_id = %s AND i.token_hash = %s AND i.accepted_at IS NULL "
                "AND i.revoked_at IS NULL AND i.expires_at > clock_timestamp() "
                "AND t.status = 'active' AND inviter.status = 'active' AND inviter.role = 'admin' "
                "AND inviter_user.disabled_at IS NULL",
                (str(tenant), validated_hash),
            ))
        return None if invite_row is None else _invitation(invite_row)

    get_invite_by_token_hash = lookup_invitation_by_hash

    def consume_invitation(
        self,
        token_hash: str,
        *,
        user_id: UUID | str,
    ) -> MembershipRecord | None:
        """Atomically claim an unused invitation and activate its matching user."""

        validated_hash = _hash(token_hash, label="invitation token hash")
        user = _uuid(user_id, label="user id")
        with self._connection() as connection:
            with _transaction(connection):
                scope_row = _one(connection.execute(
                    "SELECT hosted_active_invitation_tenant(%s) AS tenant_id",
                    (validated_hash,),
                ))
        tenant_value = None if scope_row is None else _row_value(scope_row, "tenant_id", 0)
        if tenant_value is None:
            return None
        tenant = _uuid(tenant_value, label="tenant id")
        with self.tenant_transaction(tenant) as connection:
            row = _one(connection.execute(
                "WITH authorized AS ("
                " SELECT i.id FROM invitations AS i"
                " JOIN tenants AS t ON t.id = i.tenant_id"
                " JOIN memberships AS inviter ON inviter.tenant_id = i.tenant_id"
                " AND inviter.user_id = i.invited_by_user_id"
                " JOIN users AS inviter_user ON inviter_user.id = i.invited_by_user_id"
                " JOIN users AS u ON u.email_normalized = i.email_normalized"
                " WHERE i.tenant_id = %s AND i.token_hash = %s"
                " AND i.accepted_at IS NULL AND i.revoked_at IS NULL"
                " AND i.expires_at > clock_timestamp()"
                " AND t.status = 'active' AND inviter.status = 'active'"
                " AND inviter.role = 'admin' AND inviter_user.disabled_at IS NULL"
                " AND u.id = %s AND u.disabled_at IS NULL"
                " FOR UPDATE OF i, inviter"
                "), claimed AS ("
                " UPDATE invitations AS i SET accepted_at = clock_timestamp()"
                " FROM authorized AS allowed WHERE i.id = allowed.id"
                " RETURNING i.tenant_id, i.role"
                ") INSERT INTO memberships (tenant_id, user_id, role, status)"
                " SELECT tenant_id, %s, role, 'active' FROM claimed"
                " ON CONFLICT (tenant_id, user_id) DO UPDATE"
                " SET role = EXCLUDED.role, status = 'active', updated_at = clock_timestamp()"
                " RETURNING tenant_id, user_id, role, status",
                (str(tenant), validated_hash, str(user), str(user)),
            ))
        if row is None:
            return None
        return MembershipRecord(
            tenant_id=_uuid(_row_value(row, "tenant_id"), label="tenant id"),
            user_id=_uuid(_row_value(row, "user_id"), label="user id"),
            role=str(_row_value(row, "role")),
            status=str(_row_value(row, "status")),
        )

    redeem_invite = consume_invitation

    def redeem_invitation_with_user(
        self,
        token_hash: str,
        *,
        email: str,
        display_name: str,
        password_hash: str,
        redeemed_at: datetime,
        audit_event: str = "auth.registration.completed",
        audit_details: Mapping[str, Any] | None = None,
        user_id: UUID | None = None,
        expected_existing_user_id: UUID | str | None = None,
    ) -> tuple[UserRecord, MembershipRecord] | None:
        """Atomically claim one invite, create/reuse its user, and activate membership."""

        validated_hash = _hash(token_hash, label="invitation token hash")
        normalized_email = _email(email)
        user = user_id or uuid4()
        expected_existing = (
            _uuid(expected_existing_user_id, label="expected existing user id")
            if expected_existing_user_id is not None
            else None
        )
        expected_existing_value = (
            str(expected_existing) if expected_existing is not None else None
        )
        details_json = json.dumps(dict(audit_details or {}), sort_keys=True, separators=(",", ":"))
        with self._connection() as connection:
            with _transaction(connection):
                scope_row = _one(connection.execute(
                    "SELECT hosted_active_invitation_tenant(%s) AS tenant_id",
                    (validated_hash,),
                ))
        tenant_value = None if scope_row is None else _row_value(scope_row, "tenant_id", 0)
        if tenant_value is None:
            return None
        tenant = _uuid(tenant_value, label="tenant id")
        with self.tenant_transaction(tenant) as connection:
            row = _one(connection.execute(
                "WITH authorized AS ("
                " SELECT i.id, i.tenant_id, i.email_normalized, i.role,"
                " %s::uuid AS expected_existing_user_id"
                " FROM invitations AS i JOIN tenants AS t ON t.id = i.tenant_id"
                " JOIN memberships AS inviter ON inviter.tenant_id = i.tenant_id"
                " AND inviter.user_id = i.invited_by_user_id"
                " JOIN users AS inviter_user ON inviter_user.id = i.invited_by_user_id"
                " WHERE i.tenant_id = %s AND i.token_hash = %s"
                " AND i.email_normalized = %s"
                " AND i.accepted_at IS NULL AND i.revoked_at IS NULL"
                " AND i.expires_at > %s"
                " AND t.status = 'active' AND inviter.status = 'active'"
                " AND inviter.role = 'admin' AND inviter_user.disabled_at IS NULL"
                " AND ((%s::uuid IS NULL AND NOT EXISTS ("
                "   SELECT 1 FROM users AS existing"
                "   WHERE existing.email_normalized = i.email_normalized"
                " )) OR (%s::uuid IS NOT NULL AND EXISTS ("
                "   SELECT 1 FROM users AS existing"
                "   WHERE existing.email_normalized = i.email_normalized"
                "   AND existing.id = %s::uuid AND existing.disabled_at IS NULL"
                " )))"
                " FOR UPDATE OF i, inviter"
                "), existing_user AS ("
                " SELECT u.id, u.email_normalized, u.display_name, u.password_hash,"
                " u.disabled_at, u.created_at"
                " FROM authorized AS allowed JOIN users AS u"
                " ON u.id = allowed.expected_existing_user_id"
                " AND u.email_normalized = allowed.email_normalized"
                " WHERE allowed.expected_existing_user_id IS NOT NULL"
                " AND u.disabled_at IS NULL"
                "), inserted_user AS ("
                " INSERT INTO users (id, email_normalized, display_name, password_hash)"
                " SELECT %s, allowed.email_normalized, %s, %s FROM authorized AS allowed"
                " WHERE allowed.expected_existing_user_id IS NULL"
                " ON CONFLICT DO NOTHING"
                " RETURNING id, email_normalized, display_name, password_hash, disabled_at, created_at"
                "), resolved_user AS ("
                " SELECT id, email_normalized, display_name, password_hash, disabled_at, created_at"
                " FROM existing_user UNION ALL"
                " SELECT id, email_normalized, display_name, password_hash, disabled_at, created_at"
                " FROM inserted_user"
                "), claimed AS ("
                " UPDATE invitations AS i SET accepted_at = %s"
                " FROM authorized AS allowed CROSS JOIN resolved_user AS u"
                " WHERE i.id = allowed.id AND u.email_normalized = allowed.email_normalized"
                " RETURNING i.tenant_id, i.role"
                "), activated AS ("
                " INSERT INTO memberships (tenant_id, user_id, role, status)"
                " SELECT claimed.tenant_id, resolved_user.id, claimed.role, 'active'"
                " FROM claimed CROSS JOIN resolved_user"
                " ON CONFLICT (tenant_id, user_id) DO UPDATE"
                " SET role = EXCLUDED.role, status = 'active', updated_at = clock_timestamp()"
                " RETURNING tenant_id, user_id, role, status"
                "), audited AS ("
                " INSERT INTO audit_log"
                " (tenant_id, actor_user_id, action, target_type, target_id, details_json, created_at)"
                " SELECT a.tenant_id, a.user_id, %s, 'user', a.user_id::text, %s::jsonb, %s"
                " FROM activated AS a RETURNING id"
                ") SELECT u.id, u.email_normalized, u.display_name, u.password_hash,"
                " u.disabled_at, u.created_at, a.tenant_id AS membership_tenant_id,"
                " a.user_id AS membership_user_id, a.role AS membership_role,"
                " a.status AS membership_status"
                " FROM resolved_user AS u CROSS JOIN activated AS a CROSS JOIN audited",
                (
                    expected_existing_value,
                    str(tenant), validated_hash, normalized_email, redeemed_at,
                    expected_existing_value, expected_existing_value,
                    expected_existing_value,
                    str(user), display_name.strip(), password_hash,
                    redeemed_at,
                    audit_event, details_json, redeemed_at,
                ),
            ))
        if row is None:
            return None
        return (
            UserRecord(
                id=_uuid(_row_value(row, "id"), label="user id"),
                email_normalized=str(_row_value(row, "email_normalized")),
                display_name=str(_row_value(row, "display_name")),
                password_hash=str(_row_value(row, "password_hash")),
                disabled_at=_row_value(row, "disabled_at"),
                created_at=_row_value(row, "created_at"),
            ),
            MembershipRecord(
                tenant_id=_uuid(_row_value(row, "membership_tenant_id"), label="tenant id"),
                user_id=_uuid(_row_value(row, "membership_user_id"), label="user id"),
                role=str(_row_value(row, "membership_role")),
                status=str(_row_value(row, "membership_status")),
            ),
        )

    def revoke_invitation_by_hash(self, token_hash: str) -> bool:
        validated_hash = _hash(token_hash, label="invitation token hash")
        invitation = self.lookup_invitation_by_hash(validated_hash)
        if invitation is None:
            return False
        with self.tenant_transaction(invitation.tenant_id) as connection:
            cursor = connection.execute(
                "UPDATE invitations SET revoked_at = clock_timestamp() "
                "WHERE tenant_id = %s AND token_hash = %s AND accepted_at IS NULL "
                "AND revoked_at IS NULL",
                (str(invitation.tenant_id), validated_hash),
            )
            return int(cursor.rowcount) == 1

    def create_run(
        self,
        tenant_id: UUID | str,
        *,
        owner_user_id: UUID | str,
        run_key: str,
        display_name: str,
        schema_version: int,
        engine_semantics_version: int,
        catalog: Mapping[str, Any] | None = None,
        run_id: UUID | None = None,
    ) -> RunRecord:
        tenant = _uuid(tenant_id, label="tenant id")
        owner = _uuid(owner_user_id, label="owner user id")
        run = run_id or uuid4()
        if schema_version < 1 or engine_semantics_version < 1:
            raise ValueError("run schema and semantics versions must be positive")
        catalog_json = json.dumps(dict(catalog or {}), sort_keys=True, separators=(",", ":"))
        with self.tenant_transaction(tenant) as connection:
            row = _one(connection.execute(
                "INSERT INTO runs "
                "(id, tenant_id, owner_user_id, run_key, display_name, schema_version, "
                "engine_semantics_version, catalog_json) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb) RETURNING *",
                (
                    str(run), str(tenant), str(owner), run_key.strip(), display_name.strip(),
                    int(schema_version), int(engine_semantics_version), catalog_json,
                ),
            ))
        if row is None:
            raise CatalogError("run insert returned no record")
        return _run(row)

    def get_run(self, tenant_id: UUID | str, run_id: UUID | str) -> RunRecord | None:
        tenant = _uuid(tenant_id, label="tenant id")
        run = _uuid(run_id, label="run id")
        with self.tenant_transaction(tenant) as connection:
            row = _one(connection.execute(
                "SELECT * FROM runs WHERE tenant_id = %s AND id = %s",
                (str(tenant), str(run)),
            ))
        return None if row is None else _run(row)

    def list_runs(self, tenant_id: UUID | str, *, limit: int = 100) -> tuple[RunRecord, ...]:
        tenant = _uuid(tenant_id, label="tenant id")
        if not (1 <= limit <= 500):
            raise ValueError("run list limit must be between 1 and 500")
        with self.tenant_transaction(tenant) as connection:
            rows = connection.execute(
                "SELECT * FROM runs WHERE tenant_id = %s ORDER BY updated_at DESC, id LIMIT %s",
                (str(tenant), int(limit)),
            ).fetchall()
        return tuple(_run(row) for row in rows)

    def update_run_status(
        self,
        tenant_id: UUID | str,
        run_id: UUID | str,
        status: str,
        *,
        lease_token: UUID | str | None = None,
    ) -> RunRecord | None:
        tenant = _uuid(tenant_id, label="tenant id")
        run = _uuid(run_id, label="run id")
        if status not in _RUN_STATUSES:
            raise ValueError("invalid hosted run status")
        lease = _uuid(lease_token, label="writer lease token") if lease_token is not None else None
        terminal = status in {"stopped", "failed", "archived"}
        lease_clear = (
            ", writer_lease_owner = NULL, writer_lease_token = NULL, writer_lease_expires_at = NULL"
            if terminal
            else ""
        )
        lease_predicate = (
            " AND writer_lease_token = %s AND writer_lease_expires_at > clock_timestamp()"
            if lease is not None
            else ""
        )
        params: tuple[Any, ...] = (status, str(tenant), str(run))
        if lease is not None:
            params += (str(lease),)
        with self.tenant_transaction(tenant) as connection:
            row = _one(connection.execute(
                "UPDATE runs SET status = %s, updated_at = clock_timestamp()"
                + lease_clear
                + " WHERE tenant_id = %s AND id = %s"
                + lease_predicate
                + " RETURNING *",
                params,
            ))
        return None if row is None else _run(row)

    def transfer_run_owner(
        self,
        tenant_id: UUID | str,
        run_id: UUID | str,
        new_owner_user_id: UUID | str,
    ) -> RunRecord | None:
        tenant = _uuid(tenant_id, label="tenant id")
        run = _uuid(run_id, label="run id")
        new_owner = _uuid(new_owner_user_id, label="new owner user id")
        with self.tenant_transaction(tenant) as connection:
            row = _one(connection.execute(
                "SELECT * FROM hosted_transfer_run_owner(%s, %s, %s)",
                (str(tenant), str(run), str(new_owner)),
            ))
        return None if row is None else _run(row)

    def list_active_runs(self) -> tuple[RunRecord, ...]:
        """Restart-safe supervisor discovery with each full row read under RLS."""

        with self._connection() as connection:
            with _transaction(connection):
                scopes = connection.execute(
                    "SELECT tenant_id, run_id FROM hosted_active_run_scopes()"
                ).fetchall()
        active: list[RunRecord] = []
        for scope in scopes:
            tenant = _uuid(_row_value(scope, "tenant_id", 0), label="tenant id")
            run_id = _uuid(_row_value(scope, "run_id", 1), label="run id")
            record = self.get_run(tenant, run_id)
            if record is not None and record.status in _ACTIVE_RUN_STATUSES:
                active.append(record)
        return tuple(active)

    def acquire_writer_lease(
        self,
        tenant_id: UUID | str,
        run_id: UUID | str,
        *,
        owner: str,
        ttl_seconds: int = 60,
    ) -> UUID | None:
        tenant = _uuid(tenant_id, label="tenant id")
        run = _uuid(run_id, label="run id")
        if not owner.strip() or len(owner) > 200:
            raise ValueError("writer lease owner must be 1 to 200 characters")
        if not (5 <= ttl_seconds <= 3600):
            raise ValueError("writer lease TTL must be between 5 and 3600 seconds")
        token = uuid4()
        with self.tenant_transaction(tenant) as connection:
            row = _one(connection.execute(
                "UPDATE runs SET writer_lease_owner = %s, writer_lease_token = %s, "
                "writer_lease_expires_at = clock_timestamp() + (%s * interval '1 second'), "
                "updated_at = clock_timestamp() "
                "WHERE tenant_id = %s AND id = %s "
                "AND (writer_lease_token IS NULL OR writer_lease_expires_at <= clock_timestamp()) "
                "RETURNING writer_lease_token",
                (owner.strip(), str(token), int(ttl_seconds), str(tenant), str(run)),
            ))
        if row is None:
            return None
        return _uuid(_row_value(row, "writer_lease_token", 0), label="writer lease token")

    def renew_writer_lease(
        self,
        tenant_id: UUID | str,
        run_id: UUID | str,
        *,
        owner: str,
        token: UUID | str,
        ttl_seconds: int = 60,
    ) -> bool:
        tenant = _uuid(tenant_id, label="tenant id")
        run = _uuid(run_id, label="run id")
        lease = _uuid(token, label="writer lease token")
        if not (5 <= ttl_seconds <= 3600):
            raise ValueError("writer lease TTL must be between 5 and 3600 seconds")
        with self.tenant_transaction(tenant) as connection:
            cursor = connection.execute(
                "UPDATE runs SET writer_lease_expires_at = clock_timestamp() + (%s * interval '1 second'), "
                "updated_at = clock_timestamp() "
                "WHERE tenant_id = %s AND id = %s AND writer_lease_owner = %s "
                "AND writer_lease_token = %s AND writer_lease_expires_at > clock_timestamp()",
                (int(ttl_seconds), str(tenant), str(run), owner, str(lease)),
            )
            return int(cursor.rowcount) == 1

    def release_writer_lease(
        self, tenant_id: UUID | str, run_id: UUID | str, *, token: UUID | str
    ) -> bool:
        tenant = _uuid(tenant_id, label="tenant id")
        run = _uuid(run_id, label="run id")
        lease = _uuid(token, label="writer lease token")
        with self.tenant_transaction(tenant) as connection:
            cursor = connection.execute(
                "UPDATE runs SET writer_lease_owner = NULL, writer_lease_token = NULL, "
                "writer_lease_expires_at = NULL, updated_at = clock_timestamp() "
                "WHERE tenant_id = %s AND id = %s AND writer_lease_token = %s",
                (str(tenant), str(run), str(lease)),
            )
            return int(cursor.rowcount) == 1

    def update_snapshot_pointer(
        self,
        tenant_id: UUID | str,
        run_id: UUID | str,
        *,
        lease_token: UUID | str,
        object_key: str,
        sha256: str,
        size_bytes: int,
    ) -> bool:
        tenant = _uuid(tenant_id, label="tenant id")
        run = _uuid(run_id, label="run id")
        lease = _uuid(lease_token, label="writer lease token")
        if not object_key.strip() or len(object_key) > 1024:
            raise ValueError("snapshot object key must be 1 to 1024 characters")
        if size_bytes < 0:
            raise ValueError("snapshot size must not be negative")
        with self.tenant_transaction(tenant) as connection:
            cursor = connection.execute(
                "UPDATE runs SET snapshot_object_key = %s, snapshot_sha256 = %s, "
                "snapshot_size_bytes = %s, snapshot_updated_at = clock_timestamp(), "
                "updated_at = clock_timestamp() "
                "WHERE tenant_id = %s AND id = %s AND writer_lease_token = %s "
                "AND writer_lease_expires_at > clock_timestamp()",
                (
                    object_key.strip(), _hash(sha256, label="snapshot SHA-256"), int(size_bytes),
                    str(tenant), str(run), str(lease),
                ),
            )
            return int(cursor.rowcount) == 1

    def append_audit(
        self,
        tenant_id: UUID | str,
        *,
        action: str,
        target_type: str,
        actor_user_id: UUID | str | None = None,
        target_id: str | None = None,
        request_id: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> int:
        tenant = _uuid(tenant_id, label="tenant id")
        actor = _uuid(actor_user_id, label="actor user id") if actor_user_id is not None else None
        payload = json.dumps(dict(details or {}), sort_keys=True, separators=(",", ":"))
        with self.tenant_transaction(tenant) as connection:
            row = _one(connection.execute(
                "INSERT INTO audit_log "
                "(tenant_id, actor_user_id, action, target_type, target_id, request_id, details_json) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb) RETURNING id",
                (
                    str(tenant), str(actor) if actor else None, action, target_type,
                    target_id, request_id, payload,
                ),
            ))
        if row is None:
            raise CatalogError("audit insert returned no id")
        return int(_row_value(row, "id", 0))

    def record_auth_attempt(
        self,
        tenant_id: UUID | str,
        *,
        email_hash: str,
        outcome: str,
        user_id: UUID | str | None = None,
        remote_address_hash: str | None = None,
    ) -> int:
        allowed = {"success", "bad_credentials", "rate_limited", "locked", "expired", "revoked", "csrf_failed"}
        if outcome not in allowed:
            raise ValueError("invalid authentication outcome")
        tenant = _uuid(tenant_id, label="tenant id")
        user = _uuid(user_id, label="user id") if user_id is not None else None
        remote = _hash(remote_address_hash, label="remote address hash") if remote_address_hash else None
        with self.tenant_transaction(tenant) as connection:
            row = _one(connection.execute(
                "INSERT INTO auth_attempts "
                "(tenant_id, user_id, email_hash, outcome, remote_address_hash) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (
                    str(tenant), str(user) if user else None,
                    _hash(email_hash, label="email hash"), outcome, remote,
                ),
            ))
        if row is None:
            raise CatalogError("authentication attempt insert returned no id")
        return int(_row_value(row, "id", 0))

    def reserve_login_attempt(
        self,
        tenant_id: UUID | str,
        account_hash: str,
        client_account_hash: str,
        *,
        since: datetime,
        occurred_at: datetime,
        max_failures: int,
    ) -> LoginThrottleReservation:
        """Atomically check and pessimistically reserve both login scopes.

        The account-only advisory lock prevents source-address rotation from
        racing or partitioning the limit.  The account-plus-client lock retains
        the narrower discriminator for diagnostics and future policy tuning.
        A successful login immediately appends a success row, which clears this
        pessimistic failure reservation for subsequent queries.
        """

        tenant = _uuid(tenant_id, label="tenant id")
        account = _hash(account_hash, label="account throttle hash")
        client_account = _hash(
            client_account_hash, label="client-account throttle hash"
        )
        if (
            isinstance(max_failures, bool)
            or not isinstance(max_failures, int)
            or not (1 <= max_failures <= 20)
        ):
            raise ValueError("max_failures must be an integer from 1 to 20")

        with self.tenant_transaction(tenant) as connection:
            active = _one(connection.execute(
                "SELECT id FROM tenants WHERE id = %s AND status = 'active'",
                (str(tenant),),
            ))
            if active is None:
                return LoginThrottleReservation(False)

            for lock_key in sorted({
                _advisory_lock_key(account),
                _advisory_lock_key(client_account),
            }):
                connection.execute(
                    "SELECT pg_advisory_xact_lock(%s)",
                    (lock_key,),
                )

            rows = connection.execute(
                "SELECT attempted.created_at, attempted.remote_address_hash "
                "FROM auth_attempts AS attempted "
                "WHERE attempted.tenant_id = %s AND attempted.email_hash = %s "
                "AND attempted.outcome = 'bad_credentials' AND attempted.created_at > %s "
                "AND attempted.created_at > COALESCE(("
                " SELECT MAX(completed.created_at) FROM auth_attempts AS completed "
                " WHERE completed.tenant_id = %s AND completed.email_hash = %s "
                " AND completed.outcome = 'success'"
                "), '-infinity'::timestamptz) "
                "ORDER BY attempted.created_at, attempted.id",
                (str(tenant), account, since, str(tenant), account),
            ).fetchall()
            account_failures = tuple(
                _row_value(row, "created_at", 0) for row in rows
            )
            client_failures = tuple(
                _row_value(row, "created_at", 0)
                for row in rows
                if str(_row_value(row, "remote_address_hash", 1) or "").strip()
                == client_account
            )
            if (
                len(account_failures) >= max_failures
                or len(client_failures) >= max_failures
            ):
                return LoginThrottleReservation(
                    True,
                    account_failures,
                    client_failures,
                    False,
                )

            reserved = _one(connection.execute(
                "INSERT INTO auth_attempts "
                "(tenant_id, email_hash, outcome, remote_address_hash, created_at) "
                "VALUES (%s, %s, 'bad_credentials', %s, %s) RETURNING id",
                (str(tenant), account, client_account, occurred_at),
            ))
            if reserved is None:
                raise CatalogError("login throttle reservation returned no id")
            return LoginThrottleReservation(
                True,
                (*account_failures, occurred_at),
                (*client_failures, occurred_at),
                True,
            )

    def login_failures_since(
        self,
        tenant_id: UUID | str,
        throttle_hash: str,
        since: datetime,
    ) -> tuple[datetime, ...]:
        tenant = _uuid(tenant_id, label="tenant id")
        throttle = _hash(throttle_hash, label="login throttle hash")
        with self.tenant_transaction(tenant) as connection:
            rows = connection.execute(
                "SELECT failed.created_at FROM auth_attempts AS failed "
                "WHERE failed.tenant_id = %s AND failed.email_hash = %s "
                "AND failed.outcome = 'bad_credentials' AND failed.created_at > %s "
                "AND failed.created_at > COALESCE(("
                " SELECT MAX(cleared.created_at) FROM auth_attempts AS cleared "
                " WHERE cleared.tenant_id = failed.tenant_id "
                " AND cleared.email_hash = failed.email_hash AND cleared.outcome = 'success'"
                "), '-infinity'::timestamptz) ORDER BY failed.created_at",
                (str(tenant), throttle, since),
            ).fetchall()
        return tuple(_row_value(row, "created_at", 0) for row in rows)

    def record_login_attempt(
        self,
        tenant_id: UUID | str,
        account_hash: str,
        *,
        client_account_hash: str | None = None,
        succeeded: bool,
        occurred_at: datetime,
        user_id: UUID | str | None = None,
    ) -> int:
        tenant = _uuid(tenant_id, label="tenant id")
        account = _hash(account_hash, label="account throttle hash")
        client_account = (
            _hash(client_account_hash, label="client-account throttle hash")
            if client_account_hash is not None
            else None
        )
        user = _uuid(user_id, label="user id") if user_id is not None else None
        with self.tenant_transaction(tenant) as connection:
            row = _one(connection.execute(
                "INSERT INTO auth_attempts "
                "(tenant_id, user_id, email_hash, outcome, remote_address_hash, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (
                    str(tenant), str(user) if user else None, account,
                    "success" if succeeded else "bad_credentials", client_account,
                    occurred_at,
                ),
            ))
        if row is None:
            raise CatalogError("login attempt insert returned no id")
        return int(_row_value(row, "id", 0))

    def append_auth_audit(
        self,
        tenant_id: UUID | str,
        *,
        event: str,
        occurred_at: datetime,
        actor_user_id: UUID | str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> int:
        tenant = _uuid(tenant_id, label="tenant id")
        actor = _uuid(actor_user_id, label="actor user id") if actor_user_id is not None else None
        payload = json.dumps(dict(details or {}), sort_keys=True, separators=(",", ":"))
        with self.tenant_transaction(tenant) as connection:
            row = _one(connection.execute(
                "INSERT INTO audit_log "
                "(tenant_id, actor_user_id, action, target_type, details_json, created_at) "
                "VALUES (%s, %s, %s, 'auth', %s::jsonb, %s) RETURNING id",
                (str(tenant), str(actor) if actor else None, event, payload, occurred_at),
            ))
        if row is None:
            raise CatalogError("authentication audit insert returned no id")
        return int(_row_value(row, "id", 0))

    def ready(self) -> bool:
        with self._connection() as connection:
            with _transaction(connection):
                row = connection.execute("SELECT 1 AS ready").fetchone()
        return row is not None

    def assert_runtime_security(self) -> None:
        """Fail startup if the live DSN has broader or wrong-role authority."""

        if self.expected_role is None:
            raise CatalogError("expected database role is required for hosted startup")
        with self._connection() as connection:
            with _transaction(connection):
                row = _one(connection.execute(
                    "SELECT current_user AS current_user, r.rolsuper, r.rolbypassrls, "
                    "EXISTS (SELECT 1 FROM pg_catalog.pg_class AS c "
                    " JOIN pg_catalog.pg_namespace AS n ON n.oid=c.relnamespace "
                    " WHERE n.nspname=current_schema() "
                    " AND c.relname = ANY(%s) AND pg_get_userbyid(c.relowner)=current_user) "
                    " AS owns_tenant_table, "
                    "has_function_privilege(current_user, "
                    " 'hosted_active_run_scopes()', 'EXECUTE') AS can_enumerate_runs, "
                    "(has_function_privilege(current_user, "
                    " 'hosted_active_session_tenant(text)', 'EXECUTE') AND "
                    " has_function_privilege(current_user, "
                    " 'hosted_active_invitation_tenant(text)', 'EXECUTE')) AS can_lookup_auth, "
                    "has_function_privilege(current_user, "
                    " 'hosted_transfer_run_owner(uuid,uuid,uuid)', 'EXECUTE') "
                    "AS can_transfer_run_owners, "
                    "EXISTS (SELECT 1 FROM unnest(%s::text[]) AS table_name "
                    " WHERE has_table_privilege(current_user, table_name, 'DELETE') "
                    " OR has_table_privilege(current_user, table_name, 'TRUNCATE') "
                    " OR has_table_privilege(current_user, table_name, 'REFERENCES') "
                    " OR has_table_privilege(current_user, table_name, 'TRIGGER')) "
                    " AS has_forbidden_table_privilege, "
                    "(has_table_privilege(current_user, 'tenants', 'SELECT') AND "
                    " has_table_privilege(current_user, 'users', 'SELECT') AND "
                    " has_table_privilege(current_user, 'memberships', 'SELECT') AND "
                    " has_table_privilege(current_user, 'sessions', 'SELECT') AND "
                    " has_table_privilege(current_user, 'invitations', 'SELECT') AND "
                    " has_table_privilege(current_user, 'runs', 'SELECT') AND "
                    " has_table_privilege(current_user, 'users', 'INSERT') AND "
                    " has_table_privilege(current_user, 'memberships', 'INSERT') AND "
                    " has_table_privilege(current_user, 'memberships', 'UPDATE') AND "
                    " has_table_privilege(current_user, 'sessions', 'INSERT') AND "
                    " has_table_privilege(current_user, 'sessions', 'UPDATE') AND "
                    " has_table_privilege(current_user, 'invitations', 'INSERT') AND "
                    " has_table_privilege(current_user, 'invitations', 'UPDATE') AND "
                    " has_table_privilege(current_user, 'auth_attempts', 'SELECT') AND "
                    " has_table_privilege(current_user, 'auth_attempts', 'INSERT') AND "
                    " has_table_privilege(current_user, 'audit_log', 'INSERT')) "
                    " AS has_web_privileges, "
                    "(has_table_privilege(current_user, 'runs', 'SELECT') AND "
                    " has_table_privilege(current_user, 'runs', 'INSERT') AND "
                    " has_table_privilege(current_user, 'runs', 'UPDATE')) "
                    " AS has_supervisor_privileges "
                    ", CASE WHEN %s::text IS NULL THEN false "
                    "ELSE pg_has_role(current_user, %s::text, 'MEMBER') END AS has_peer_role "
                    ", (has_schema_privilege(current_user, current_schema(), 'CREATE') "
                    "OR has_database_privilege(current_user, current_database(), 'CREATE')) "
                    "AS has_create_privilege "
                    "FROM pg_catalog.pg_roles AS r WHERE r.rolname=current_user",
                    (
                        ["tenants", "memberships", "sessions", "invitations", "runs", "audit_log", "auth_attempts"],
                        ["tenants", "users", "memberships", "sessions", "invitations", "runs", "audit_log", "auth_attempts"],
                        self.forbidden_role,
                        self.forbidden_role,
                    ),
                ))
        if row is None:
            raise CatalogError("database runtime role could not be verified")
        current_user = str(_row_value(row, "current_user", 0))
        if current_user != self.expected_role:
            raise CatalogError("database DSN is not bound to the configured runtime role")
        if bool(_row_value(row, "rolsuper", 1)) or bool(_row_value(row, "rolbypassrls", 2)):
            raise CatalogError("database runtime role can bypass row security")
        if bool(_row_value(row, "owns_tenant_table", 3)):
            raise CatalogError("database runtime role owns a tenant table")
        can_enumerate = bool(_row_value(row, "can_enumerate_runs", 4))
        if can_enumerate != (self.capability == "supervisor"):
            raise CatalogError("database run-discovery privilege does not match process capability")
        can_lookup_auth = bool(_row_value(row, "can_lookup_auth", 5))
        if can_lookup_auth != (self.capability == "web"):
            raise CatalogError("database auth-lookup privilege does not match process capability")
        can_transfer = bool(_row_value(row, "can_transfer_run_owners", 6))
        if can_transfer != (self.capability == "web"):
            raise CatalogError("database run-transfer privilege does not match process capability")
        if bool(_row_value(row, "has_forbidden_table_privilege", 7)):
            raise CatalogError("database runtime role has forbidden destructive table privileges")
        required_key = (
            "has_web_privileges" if self.capability == "web" else "has_supervisor_privileges"
        )
        required_index = 8 if self.capability == "web" else 9
        if not bool(_row_value(row, required_key, required_index)):
            raise CatalogError("database runtime role is missing its exact required privileges")
        if bool(_row_value(row, "has_peer_role", 10)):
            raise CatalogError("database runtime role can assume the peer capability role")
        if bool(_row_value(row, "has_create_privilege", 11)):
            raise CatalogError("database runtime role has forbidden object-creation privileges")
