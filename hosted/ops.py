"""Fail-closed hosted bootstrap, snapshot, restore, and readiness operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import socket
import tempfile
from typing import Any, Iterable, Mapping
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from engine.schema import SCHEMA_VERSION

from .artifacts import (
    ArtifactMetadata,
    InvalidArtifactKey,
    SQLiteSnapshot,
    publish_sqlite_snapshot,
    restore_sqlite_snapshot,
    validate_snapshot_artifact_key,
)
from .config import HostedConfig, artifact_readiness_check
from .security import hash_password, parse_display_name, parse_email, parse_password


_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")
_RUN_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,159}$")


class HostedOperationError(RuntimeError):
    pass


@dataclass(frozen=True)
class BootstrapResult:
    tenant_id: UUID
    user_id: UUID
    created: bool


@dataclass(frozen=True)
class SnapshotResult:
    tenant_id: UUID
    run_id: UUID
    metadata: ArtifactMetadata


@dataclass(frozen=True)
class ReadinessReport:
    ready: bool
    checks: Mapping[str, bool]


def _uuid(value: Any, label: str) -> UUID:
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise HostedOperationError(f"{label} must be a UUID") from exc


def _value(record: Any, name: str, default: Any = None) -> Any:
    if isinstance(record, Mapping):
        return record.get(name, default)
    return getattr(record, name, default)


def _safe_child(root: Path, *parts: str) -> Path:
    base = root.resolve(strict=False)
    candidate = base.joinpath(*parts).resolve(strict=False)
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise HostedOperationError("hosted path escapes configured runtime directory") from exc
    return candidate


def run_database_path(config: HostedConfig, record: Any) -> Path:
    tenant = _uuid(_value(record, "tenant_id"), "tenant id")
    run_id = _uuid(_value(record, "id"), "run id")
    run_key = str(_value(record, "run_key", ""))
    if _RUN_KEY_RE.fullmatch(run_key) is None:
        raise HostedOperationError("catalog run key is not a safe filesystem identifier")
    return _safe_child(
        config.runtime.run_directory,
        "tenants",
        str(tenant),
        "runs",
        str(run_id),
        "data",
        f"{run_key}.db",
    )


def bootstrap_initial_tenant(
    catalog: Any,
    *,
    tenant_slug: str,
    tenant_name: str,
    admin_email: str,
    admin_name: str,
    password: str,
) -> BootstrapResult:
    slug = str(tenant_slug).strip().lower()
    if _SLUG_RE.fullmatch(slug) is None:
        raise ValueError("tenant slug must be 3-64 lowercase letters, digits, or hyphens")
    display_tenant = str(tenant_name).strip()
    if not (1 <= len(display_tenant) <= 200):
        raise ValueError("tenant name must be 1 to 200 characters")
    email = parse_email(admin_email)
    name = parse_display_name(admin_name)
    secret = parse_password(password)
    tenant_id = uuid5(NAMESPACE_URL, f"agent-economy-hosted:tenant:{slug}")
    user_id = uuid5(NAMESPACE_URL, f"agent-economy-hosted:user:{email}")

    existing = catalog.get_membership(tenant_id, user_id)
    if existing is not None:
        user = catalog.get_user_by_id(user_id)
        if (
            user is None
            or str(_value(user, "email_normalized", "")) != email
            or str(_value(existing, "role", "")) != "admin"
            or str(_value(existing, "status", "")) != "active"
        ):
            raise HostedOperationError("existing bootstrap identity does not match requested admin")
        return BootstrapResult(tenant_id, user_id, False)

    catalog.create_tenant_with_admin(
        slug=slug,
        tenant_name=display_tenant,
        email=email,
        user_name=name,
        password_hash=hash_password(secret),
        tenant_id=tenant_id,
        user_id=user_id,
    )
    return BootstrapResult(tenant_id, user_id, True)


class HostedOperations:
    def __init__(
        self,
        config: HostedConfig,
        catalog: Any,
        artifact_store: Any,
        *,
        lease_owner: str | None = None,
    ) -> None:
        self.config = config
        self.catalog = catalog
        self.artifact_store = artifact_store
        owner = lease_owner or f"ops-{socket.gethostname()}-{os.getpid()}"
        if not owner or len(owner) > 200:
            raise ValueError("operations lease owner must be 1 to 200 characters")
        self.lease_owner = owner
        self.config.runtime.snapshot_directory.mkdir(parents=True, exist_ok=True)

    def snapshot_run(self, tenant_id: UUID | str, run_id: UUID | str) -> SnapshotResult:
        tenant = _uuid(tenant_id, "tenant id")
        run = _uuid(run_id, "run id")
        record = self.catalog.get_run(tenant, run)
        if record is None:
            raise HostedOperationError("run was not found in the requested tenant")
        source = run_database_path(self.config, record)
        if not source.is_file():
            raise HostedOperationError("run has no local SQLite database to snapshot")
        token = self.catalog.acquire_writer_lease(
            tenant,
            run,
            owner=self.lease_owner,
            ttl_seconds=self.config.runtime.writer_lease_seconds,
        )
        if token is None:
            raise HostedOperationError("run writer lease is held by another process")
        try:
            stamp = datetime.now(timezone.utc).strftime("d%Y%m%dT%H%M%S%fZ")
            snapshot_id = f"{stamp}-{uuid4().hex[:12]}"
            metadata = publish_sqlite_snapshot(
                source,
                self.artifact_store,
                tenant_id=str(tenant),
                run_id=str(run),
                snapshot_id=snapshot_id,
                staging_directory=self.config.runtime.snapshot_directory,
                expected_schema_version=int(_value(record, "schema_version", SCHEMA_VERSION)),
            )
            updated = self.catalog.update_snapshot_pointer(
                tenant,
                run,
                lease_token=token,
                object_key=metadata.key,
                sha256=metadata.sha256,
                size_bytes=metadata.size_bytes,
            )
            if not updated:
                raise HostedOperationError("writer lease was lost before snapshot pointer update")
            return SnapshotResult(tenant, run, metadata)
        finally:
            self.catalog.release_writer_lease(tenant, run, token=token)

    def snapshot_all(self) -> tuple[SnapshotResult, ...]:
        results: list[SnapshotResult] = []
        for record in self.catalog.list_active_runs():
            results.append(
                self.snapshot_run(_value(record, "tenant_id"), _value(record, "id"))
            )
        return tuple(results)

    def _pointer(self, tenant_id: UUID | str, run_id: UUID | str) -> tuple[Any, UUID, UUID, str, str]:
        tenant = _uuid(tenant_id, "tenant id")
        run = _uuid(run_id, "run id")
        record = self.catalog.get_run(tenant, run)
        if record is None:
            raise HostedOperationError("run was not found in the requested tenant")
        try:
            key = validate_snapshot_artifact_key(str(_value(record, "snapshot_object_key", "")))
        except InvalidArtifactKey as exc:
            raise HostedOperationError("catalog snapshot pointer is missing or invalid") from exc
        expected_prefix = f"tenants/{tenant}/runs/{run}/snapshots/"
        if not key.startswith(expected_prefix):
            raise HostedOperationError("catalog snapshot pointer escapes the requested tenant/run")
        digest = str(_value(record, "snapshot_sha256", ""))
        return record, tenant, run, Path(key).stem, digest

    def verify_snapshot(self, tenant_id: UUID | str, run_id: UUID | str) -> SQLiteSnapshot:
        record, tenant, run, snapshot_id, digest = self._pointer(tenant_id, run_id)
        fd, name = tempfile.mkstemp(
            prefix="verify-", suffix=".sqlite3", dir=self.config.runtime.snapshot_directory
        )
        os.close(fd)
        temporary = Path(name)
        temporary.unlink(missing_ok=True)
        try:
            return restore_sqlite_snapshot(
                self.artifact_store,
                tenant_id=str(tenant),
                run_id=str(run),
                snapshot_id=snapshot_id,
                destination=temporary,
                expected_sha256=digest,
                expected_schema_version=int(_value(record, "schema_version", SCHEMA_VERSION)),
            )
        finally:
            temporary.unlink(missing_ok=True)

    def restore_snapshot(
        self,
        tenant_id: UUID | str,
        run_id: UUID | str,
        *,
        destination: str | Path | None = None,
        replace: bool = False,
    ) -> SQLiteSnapshot:
        tenant = _uuid(tenant_id, "tenant id")
        run = _uuid(run_id, "run id")
        initial_record = self.catalog.get_run(tenant, run)
        if initial_record is None:
            raise HostedOperationError("run was not found in the requested tenant")
        expected_destination = run_database_path(self.config, initial_record)
        target = expected_destination if destination is None else Path(destination).resolve(strict=False)
        run_root = self.config.runtime.run_directory.resolve(strict=False)
        try:
            target.relative_to(run_root)
        except ValueError as exc:
            raise HostedOperationError("restore destination must remain inside run_directory") from exc
        if target != expected_destination:
            raise HostedOperationError("restore destination must be the catalog run database path")
        record, tenant, run, snapshot_id, digest = self._pointer(tenant, run)
        expected_destination = run_database_path(self.config, record)
        status = str(_value(record, "status", ""))
        if status not in {"paused", "stopped", "failed", "archived"}:
            raise HostedOperationError("run must be paused or terminal before restore")

        # Download and fully verify before taking the writer lease.  A large
        # object must never consume most of a fixed lease and then publish after
        # another writer has legitimately acquired it.
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, staged_name = tempfile.mkstemp(
            prefix=".r-", suffix=".db", dir=target.parent
        )
        os.close(fd)
        staged = Path(staged_name)
        staged.unlink(missing_ok=True)
        token = None
        try:
            verified = restore_sqlite_snapshot(
                self.artifact_store,
                tenant_id=str(tenant),
                run_id=str(run),
                snapshot_id=snapshot_id,
                destination=staged,
                expected_sha256=digest,
                expected_schema_version=int(_value(record, "schema_version", SCHEMA_VERSION)),
            )
            token = self.catalog.acquire_writer_lease(
                tenant,
                run,
                owner=self.lease_owner,
                ttl_seconds=self.config.runtime.writer_lease_seconds,
            )
            if token is None:
                raise HostedOperationError("run writer lease is held by another process")

            # Re-read every publication precondition under the lease.  In
            # particular, a snapshot pointer or run status may have changed
            # while the artifact was downloading.
            current, _, _, current_snapshot_id, current_digest = self._pointer(tenant, run)
            if (
                current_snapshot_id != snapshot_id
                or current_digest != digest
                or str(_value(current, "status", ""))
                not in {"paused", "stopped", "failed", "archived"}
                or run_database_path(self.config, current) != target
            ):
                raise HostedOperationError("run changed while snapshot restore was staged")
            renewed = self.catalog.renew_writer_lease(
                tenant,
                run,
                owner=self.lease_owner,
                token=token,
                ttl_seconds=self.config.runtime.writer_lease_seconds,
            )
            if not renewed:
                raise HostedOperationError("run writer lease expired before restore publication")

            resolved_parent = target.parent.resolve(strict=True)
            try:
                resolved_parent.relative_to(self.config.runtime.run_directory.resolve(strict=True))
            except ValueError as exc:
                raise HostedOperationError(
                    "restore destination escaped the run directory before publication"
                ) from exc
            if resolved_parent != expected_destination.parent.resolve(strict=True):
                raise HostedOperationError("restore destination changed before publication")
            if replace:
                os.replace(staged, target)
            else:
                try:
                    # Hard-link publication is atomic create-if-absent on the
                    # same filesystem, closing the exists()/replace TOCTOU.
                    os.link(staged, target)
                except FileExistsError as exc:
                    raise HostedOperationError(
                        "restore destination already exists; explicit replace is required"
                    ) from exc
                staged.unlink()
            return SQLiteSnapshot(
                target,
                verified.sha256,
                verified.size_bytes,
                verified.schema_version,
            )
        finally:
            staged.unlink(missing_ok=True)
            if token is not None:
                self.catalog.release_writer_lease(tenant, run, token=token)


def check_readiness(
    config: HostedConfig,
    *,
    catalog: Any,
    artifact_store: Any,
    supervisor: Any | None = None,
) -> ReadinessReport:
    checks: dict[str, bool] = {}
    try:
        probe = getattr(catalog, "ready", None) or getattr(catalog, "ping", None)
        checks["catalog"] = bool(probe and probe())
    except Exception:
        checks["catalog"] = False
    try:
        checks["artifacts"] = bool(artifact_readiness_check(artifact_store))
    except Exception:
        checks["artifacts"] = False
    try:
        config.runtime.run_directory.mkdir(parents=True, exist_ok=True)
        config.runtime.snapshot_directory.mkdir(parents=True, exist_ok=True)
        checks["runtime"] = all(
            path.is_dir() and os.access(path, os.R_OK | os.W_OK)
            for path in (config.runtime.run_directory, config.runtime.snapshot_directory)
        )
    except OSError:
        checks["runtime"] = False
    if supervisor is not None:
        try:
            probe = getattr(supervisor, "ready", None) or getattr(supervisor, "check_readiness", None)
            checks["supervisor"] = bool(probe and probe())
        except Exception:
            checks["supervisor"] = False
    return ReadinessReport(bool(checks) and all(checks.values()), checks)


__all__ = [
    "BootstrapResult",
    "HostedOperationError",
    "HostedOperations",
    "ReadinessReport",
    "SnapshotResult",
    "bootstrap_initial_tenant",
    "check_readiness",
    "run_database_path",
]
