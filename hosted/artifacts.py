"""Immutable artifact storage and consistent SQLite run snapshots.

Artifact keys are intentionally narrow: callers may only address a snapshot
inside a tenant and run namespace.  Both filesystem and S3 implementations
validate that logical key before performing any I/O.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol, runtime_checkable

from engine.schema import SCHEMA_VERSION


_IDENTIFIER_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9_-]{0,126}[A-Za-z0-9])?")
_SNAPSHOT_KEY_RE = re.compile(
    r"tenants/(?P<tenant>[A-Za-z0-9][A-Za-z0-9_-]{0,127})/"
    r"runs/(?P<run>[A-Za-z0-9][A-Za-z0-9_-]{0,127})/"
    r"snapshots/(?P<snapshot>[A-Za-z0-9][A-Za-z0-9_-]{0,127})\.sqlite3"
)
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_COPY_CHUNK_BYTES = 1024 * 1024


class ArtifactError(RuntimeError):
    """Base class for durable-artifact failures."""


class InvalidArtifactKey(ArtifactError, ValueError):
    """The requested key is outside the tenant/run snapshot namespace."""


class ArtifactNotFound(ArtifactError, FileNotFoundError):
    """The requested artifact does not exist or was never fully committed."""


class ArtifactConflict(ArtifactError, FileExistsError):
    """An immutable artifact already exists at the requested key."""


class ArtifactIntegrityError(ArtifactError):
    """Stored bytes do not match their durable integrity metadata."""


class SnapshotError(ArtifactError):
    """A database could not be safely snapshotted or restored."""


@dataclass(frozen=True)
class ArtifactMetadata:
    key: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class SQLiteSnapshot:
    path: Path
    sha256: str
    size_bytes: int
    schema_version: int


def _validate_identifier(value: str, label: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER_RE.fullmatch(value) is None:
        raise InvalidArtifactKey(
            f"{label} must be 1-128 ASCII letters, digits, underscores, or hyphens"
        )
    return value


def snapshot_artifact_key(tenant_id: str, run_id: str, snapshot_id: str) -> str:
    """Return the only artifact-key shape accepted by hosted storage."""
    tenant = _validate_identifier(tenant_id, "tenant_id")
    run = _validate_identifier(run_id, "run_id")
    snapshot = _validate_identifier(snapshot_id, "snapshot_id")
    return f"tenants/{tenant}/runs/{run}/snapshots/{snapshot}.sqlite3"


def validate_snapshot_artifact_key(key: str) -> str:
    match = _SNAPSHOT_KEY_RE.fullmatch(key) if isinstance(key, str) else None
    if match is None:
        raise InvalidArtifactKey(
            "artifact key must be tenants/<tenant>/runs/<run>/snapshots/<snapshot>.sqlite3"
        )
    _validate_identifier(match.group("tenant"), "tenant_id")
    _validate_identifier(match.group("run"), "run_id")
    _validate_identifier(match.group("snapshot"), "snapshot_id")
    return key


def _validate_sha256(value: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ArtifactIntegrityError("expected SHA-256 must be 64 lowercase hex characters")
    return value


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(_COPY_CHUNK_BYTES):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _copy_and_hash(source: BinaryIO, destination: BinaryIO) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    while chunk := source.read(_COPY_CHUNK_BYTES):
        destination.write(chunk)
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size


def _remove_sqlite_temporary_files(path: Path, *, include_database: bool = True) -> None:
    names = [path, Path(f"{path}-wal"), Path(f"{path}-shm")]
    for candidate in names if include_database else names[1:]:
        candidate.unlink(missing_ok=True)


@runtime_checkable
class ArtifactStore(Protocol):
    """Minimal immutable-object contract used by hosted run snapshots."""

    def put_file(
        self, key: str, source: str | os.PathLike[str], *, expected_sha256: str | None = None
    ) -> ArtifactMetadata: ...

    def get_file(
        self,
        key: str,
        destination: str | os.PathLike[str],
        *,
        expected_sha256: str | None = None,
    ) -> ArtifactMetadata: ...

    def head(self, key: str) -> ArtifactMetadata: ...

    def delete(self, key: str) -> None: ...


class FilesystemArtifactStore:
    """An immutable local artifact store suitable for development and tests.

    Each logical key is represented by a directory containing a payload,
    integrity metadata, and a completion marker.  The marker is written last,
    so interrupted uploads are never returned as valid artifacts.
    """

    _PAYLOAD_NAME = "payload"
    _METADATA_NAME = "metadata.json"
    _COMPLETE_NAME = ".complete"

    def __init__(self, root: str | os.PathLike[str]):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        if not self.root.is_dir():
            raise ArtifactError(f"artifact root is not a directory: {self.root}")

    def _artifact_dir(self, key: str, *, create_parent: bool = False) -> Path:
        valid_key = validate_snapshot_artifact_key(key)
        path = self.root.joinpath(*valid_key.split("/"))
        if create_parent:
            # Check the deepest existing ancestor before mkdir follows any
            # operator-created symlink.  Recheck after creation to close the
            # normal (non-adversarial) configuration race as well.
            existing = path.parent
            while not existing.exists() and existing != self.root:
                existing = existing.parent
            try:
                existing.resolve().relative_to(self.root)
            except ValueError as exc:
                raise InvalidArtifactKey("artifact path escapes configured root") from exc
            path.parent.mkdir(parents=True, exist_ok=True)
        resolved_parent = path.parent.resolve()
        try:
            resolved_parent.relative_to(self.root)
        except ValueError as exc:
            raise InvalidArtifactKey("artifact path escapes configured root") from exc
        if path.is_symlink():
            raise InvalidArtifactKey("artifact path may not be a symbolic link")
        if path.exists():
            try:
                path.resolve().relative_to(self.root)
            except ValueError as exc:
                raise InvalidArtifactKey("artifact path escapes configured root") from exc
        return path

    @staticmethod
    def _write_metadata(path: Path, metadata: ArtifactMetadata) -> None:
        payload = json.dumps(
            {
                "version": 1,
                "key": metadata.key,
                "sha256": metadata.sha256,
                "size_bytes": metadata.size_bytes,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        with path.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())

    def put_file(
        self, key: str, source: str | os.PathLike[str], *, expected_sha256: str | None = None
    ) -> ArtifactMetadata:
        valid_key = validate_snapshot_artifact_key(key)
        expected = _validate_sha256(expected_sha256) if expected_sha256 is not None else None
        source_path = Path(source)
        if not source_path.is_file():
            raise ArtifactNotFound(f"upload source is not a file: {source_path}")
        artifact_dir = self._artifact_dir(valid_key, create_parent=True)
        if artifact_dir.exists():
            raise ArtifactConflict(f"immutable artifact already exists: {valid_key}")

        staging = Path(tempfile.mkdtemp(prefix=".upload-", dir=artifact_dir.parent))
        claimed = False
        try:
            payload_path = staging / self._PAYLOAD_NAME
            with source_path.open("rb") as incoming, payload_path.open("xb") as outgoing:
                digest, size = _copy_and_hash(incoming, outgoing)
                outgoing.flush()
                os.fsync(outgoing.fileno())
            if expected is not None and digest != expected:
                raise ArtifactIntegrityError(
                    f"upload SHA-256 mismatch: expected {expected}, got {digest}"
                )
            metadata = ArtifactMetadata(valid_key, digest, size)
            self._write_metadata(staging / self._METADATA_NAME, metadata)

            try:
                artifact_dir.mkdir()
                claimed = True
            except FileExistsError as exc:
                raise ArtifactConflict(
                    f"immutable artifact already exists: {valid_key}"
                ) from exc
            os.replace(payload_path, artifact_dir / self._PAYLOAD_NAME)
            os.replace(staging / self._METADATA_NAME, artifact_dir / self._METADATA_NAME)
            with (artifact_dir / self._COMPLETE_NAME).open("xb") as marker:
                marker.write(b"1")
                marker.flush()
                os.fsync(marker.fileno())
            return metadata
        except BaseException:
            if claimed:
                shutil.rmtree(artifact_dir, ignore_errors=True)
            raise
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def _read_metadata(self, key: str) -> tuple[ArtifactMetadata, Path]:
        valid_key = validate_snapshot_artifact_key(key)
        artifact_dir = self._artifact_dir(valid_key)
        complete_path = artifact_dir / self._COMPLETE_NAME
        if not artifact_dir.is_dir() or not complete_path.is_file():
            raise ArtifactNotFound(f"artifact not found: {valid_key}")
        payload_path = artifact_dir / self._PAYLOAD_NAME
        metadata_path = artifact_dir / self._METADATA_NAME
        if (
            complete_path.is_symlink()
            or payload_path.is_symlink()
            or metadata_path.is_symlink()
        ):
            raise ArtifactIntegrityError(f"artifact contains a symbolic link: {valid_key}")
        try:
            raw = json.loads(metadata_path.read_text(encoding="utf-8"))
            raw_size = raw["size_bytes"]
            if isinstance(raw_size, bool) or not isinstance(raw_size, int):
                raise ValueError("size_bytes must be an integer")
            metadata = ArtifactMetadata(
                key=str(raw["key"]),
                sha256=_validate_sha256(raw["sha256"]),
                size_bytes=raw_size,
            )
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ArtifactIntegrityError(f"invalid artifact metadata: {valid_key}") from exc
        if metadata.key != valid_key or metadata.size_bytes < 0:
            raise ArtifactIntegrityError(f"artifact metadata does not match key: {valid_key}")
        if not payload_path.is_file():
            raise ArtifactIntegrityError(f"artifact payload is missing: {valid_key}")
        digest, size = _hash_file(payload_path)
        if digest != metadata.sha256 or size != metadata.size_bytes:
            raise ArtifactIntegrityError(f"artifact payload failed integrity check: {valid_key}")
        return metadata, payload_path

    def head(self, key: str) -> ArtifactMetadata:
        metadata, _ = self._read_metadata(key)
        return metadata

    def get_file(
        self,
        key: str,
        destination: str | os.PathLike[str],
        *,
        expected_sha256: str | None = None,
    ) -> ArtifactMetadata:
        expected = _validate_sha256(expected_sha256) if expected_sha256 is not None else None
        metadata, payload_path = self._read_metadata(key)
        if expected is not None and metadata.sha256 != expected:
            raise ArtifactIntegrityError(
                f"artifact SHA-256 mismatch: expected {expected}, got {metadata.sha256}"
            )
        destination_path = Path(destination)
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{destination_path.name}.", suffix=".download", dir=destination_path.parent
        )
        temporary = Path(temporary_name)
        try:
            with payload_path.open("rb") as incoming, os.fdopen(fd, "wb") as outgoing:
                digest, size = _copy_and_hash(incoming, outgoing)
                outgoing.flush()
                os.fsync(outgoing.fileno())
            if digest != metadata.sha256 or size != metadata.size_bytes:
                raise ArtifactIntegrityError(f"artifact changed while reading: {metadata.key}")
            os.replace(temporary, destination_path)
            return metadata
        finally:
            temporary.unlink(missing_ok=True)

    def delete(self, key: str) -> None:
        valid_key = validate_snapshot_artifact_key(key)
        artifact_dir = self._artifact_dir(valid_key)
        if not artifact_dir.exists():
            raise ArtifactNotFound(f"artifact not found: {valid_key}")
        if not artifact_dir.is_dir():
            raise ArtifactIntegrityError(f"artifact path is not a directory: {valid_key}")
        shutil.rmtree(artifact_dir)


class S3ArtifactStore:
    """S3-backed immutable artifacts without a mandatory boto3 dependency."""

    def __init__(
        self,
        bucket: str,
        *,
        prefix: str = "",
        client=None,
        client_options: dict | None = None,
    ):
        if not bucket or not isinstance(bucket, str):
            raise ValueError("bucket is required")
        normalized_prefix = prefix.strip("/")
        if ".." in normalized_prefix.split("/") or "\\" in normalized_prefix:
            raise ValueError("invalid S3 prefix")
        self.bucket = bucket
        self.prefix = normalized_prefix
        self._client_instance = client
        self._client_options = dict(client_options or {})

    @property
    def _client(self):
        if self._client_instance is None:
            try:
                import boto3  # type: ignore[import-not-found]
            except ImportError as exc:
                raise ArtifactError(
                    "S3 artifact storage requires the optional boto3 package"
                ) from exc
            self._client_instance = boto3.client("s3", **self._client_options)
        return self._client_instance

    def _object_key(self, key: str) -> str:
        valid_key = validate_snapshot_artifact_key(key)
        return f"{self.prefix}/{valid_key}" if self.prefix else valid_key

    @staticmethod
    def _error_code(exc: BaseException) -> str:
        response = getattr(exc, "response", {})
        if not isinstance(response, dict):
            return ""
        error = response.get("Error", {})
        return str(error.get("Code", "")) if isinstance(error, dict) else ""

    def put_file(
        self, key: str, source: str | os.PathLike[str], *, expected_sha256: str | None = None
    ) -> ArtifactMetadata:
        valid_key = validate_snapshot_artifact_key(key)
        expected = _validate_sha256(expected_sha256) if expected_sha256 is not None else None
        source_path = Path(source)
        if not source_path.is_file():
            raise ArtifactNotFound(f"upload source is not a file: {source_path}")
        digest, size = _hash_file(source_path)
        if expected is not None and digest != expected:
            raise ArtifactIntegrityError(
                f"upload SHA-256 mismatch: expected {expected}, got {digest}"
            )
        metadata = ArtifactMetadata(valid_key, digest, size)
        try:
            with source_path.open("rb") as body:
                self._client.put_object(
                    Bucket=self.bucket,
                    Key=self._object_key(valid_key),
                    Body=body,
                    ContentLength=size,
                    ChecksumSHA256=base64.b64encode(bytes.fromhex(digest)).decode("ascii"),
                    Metadata={"sha256": digest, "size_bytes": str(size)},
                    IfNoneMatch="*",
                )
        except Exception as exc:
            if self._error_code(exc) in {"PreconditionFailed", "ConditionalRequestConflict", "412"}:
                raise ArtifactConflict(
                    f"immutable artifact already exists: {valid_key}"
                ) from exc
            raise ArtifactError(f"failed to upload artifact: {valid_key}") from exc
        return metadata

    def head(self, key: str) -> ArtifactMetadata:
        valid_key = validate_snapshot_artifact_key(key)
        try:
            response = self._client.head_object(
                Bucket=self.bucket, Key=self._object_key(valid_key)
            )
        except Exception as exc:
            if self._error_code(exc) in {"404", "NoSuchKey", "NotFound"}:
                raise ArtifactNotFound(f"artifact not found: {valid_key}") from exc
            raise ArtifactError(f"failed to inspect artifact: {valid_key}") from exc
        try:
            stored = response["Metadata"]
            digest = _validate_sha256(stored["sha256"])
            size = int(stored["size_bytes"])
            content_length = int(response["ContentLength"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ArtifactIntegrityError(f"invalid S3 artifact metadata: {valid_key}") from exc
        if size < 0 or size != content_length:
            raise ArtifactIntegrityError(f"S3 artifact size mismatch: {valid_key}")
        return ArtifactMetadata(valid_key, digest, size)

    def get_file(
        self,
        key: str,
        destination: str | os.PathLike[str],
        *,
        expected_sha256: str | None = None,
    ) -> ArtifactMetadata:
        expected = _validate_sha256(expected_sha256) if expected_sha256 is not None else None
        metadata = self.head(key)
        if expected is not None and metadata.sha256 != expected:
            raise ArtifactIntegrityError(
                f"artifact SHA-256 mismatch: expected {expected}, got {metadata.sha256}"
            )
        body = None
        try:
            response = self._client.get_object(
                Bucket=self.bucket, Key=self._object_key(metadata.key)
            )
            body = response["Body"]
        except Exception as exc:
            if self._error_code(exc) in {"404", "NoSuchKey", "NotFound"}:
                raise ArtifactNotFound(f"artifact not found: {metadata.key}") from exc
            raise ArtifactError(f"failed to download artifact: {metadata.key}") from exc

        destination_path = Path(destination)
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{destination_path.name}.", suffix=".download", dir=destination_path.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "wb") as outgoing:
                digest, size = _copy_and_hash(body, outgoing)
                outgoing.flush()
                os.fsync(outgoing.fileno())
            if digest != metadata.sha256 or size != metadata.size_bytes:
                raise ArtifactIntegrityError(f"downloaded artifact is corrupt: {metadata.key}")
            os.replace(temporary, destination_path)
            return metadata
        finally:
            close = getattr(body, "close", None)
            if callable(close):
                close()
            temporary.unlink(missing_ok=True)

    def delete(self, key: str) -> None:
        valid_key = validate_snapshot_artifact_key(key)
        self.head(valid_key)
        try:
            self._client.delete_object(Bucket=self.bucket, Key=self._object_key(valid_key))
        except Exception as exc:
            raise ArtifactError(f"failed to delete artifact: {valid_key}") from exc


def _verify_sqlite_database(path: Path, expected_schema_version: int) -> int:
    if not path.is_file():
        raise SnapshotError(f"SQLite snapshot is missing: {path}")
    try:
        uri = f"{path.resolve().as_uri()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, isolation_level=None)
        try:
            check_rows = connection.execute("PRAGMA quick_check").fetchall()
            if check_rows != [("ok",)]:
                detail = "; ".join(str(row[0]) for row in check_rows)
                raise SnapshotError(f"SQLite quick_check failed: {detail or 'no result'}")
            row = connection.execute(
                "SELECT schema_version FROM run_meta WHERE id=1"
            ).fetchone()
            if row is None:
                raise SnapshotError("SQLite snapshot has no run_meta schema marker")
            raw_version = row[0]
            if isinstance(raw_version, bool) or not isinstance(raw_version, int):
                raise SnapshotError(
                    f"SQLite snapshot has invalid schema version {raw_version!r}"
                )
            if raw_version != expected_schema_version:
                raise SnapshotError(
                    f"SQLite snapshot schema v{raw_version} does not match expected "
                    f"v{expected_schema_version}"
                )
            return raw_version
        finally:
            connection.close()
    except SnapshotError:
        raise
    except sqlite3.Error as exc:
        raise SnapshotError(f"invalid SQLite snapshot: {path}") from exc


def create_sqlite_snapshot(
    source_database: str | os.PathLike[str],
    destination: str | os.PathLike[str],
    *,
    expected_schema_version: int = SCHEMA_VERSION,
) -> SQLiteSnapshot:
    """Create a transactionally consistent, verified SQLite backup.

    The destination is replaced only after backup, quick-check, and schema
    verification all succeed.  A prior destination therefore survives any
    failed snapshot attempt unchanged.
    """
    source_path = Path(source_database)
    destination_path = Path(destination)
    if source_path.resolve() == destination_path.resolve():
        raise SnapshotError("snapshot destination must differ from source database")
    if not source_path.is_file():
        raise SnapshotError(f"source SQLite database is missing: {source_path}")
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination_path.name}.", suffix=".snapshot", dir=destination_path.parent
    )
    os.close(fd)
    temporary = Path(temporary_name)
    temporary.unlink(missing_ok=True)
    try:
        source_uri = f"{source_path.resolve().as_uri()}?mode=ro"
        source = None
        target = None
        try:
            source = sqlite3.connect(source_uri, uri=True, isolation_level=None)
            target = sqlite3.connect(str(temporary), isolation_level=None)
            source.execute("PRAGMA busy_timeout = 5000")
            source.backup(target)
            # Backups of WAL-mode databases retain that persistent mode.  A
            # hosted artifact must be one self-contained file, so normalize
            # the verified copy before hashing and publication.
            target.execute("PRAGMA journal_mode = DELETE")
        finally:
            if target is not None:
                target.close()
            if source is not None:
                source.close()
        version = _verify_sqlite_database(temporary, expected_schema_version)
        digest, size = _hash_file(temporary)
        # Windows' fsync wrapper requires a writable descriptor even though the
        # backup is already complete at this point.
        with temporary.open("r+b") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, destination_path)
        return SQLiteSnapshot(destination_path, digest, size, version)
    except SnapshotError:
        raise
    except (OSError, sqlite3.Error) as exc:
        raise SnapshotError(f"failed to create SQLite snapshot: {source_path}") from exc
    finally:
        _remove_sqlite_temporary_files(temporary)


def publish_sqlite_snapshot(
    source_database: str | os.PathLike[str],
    artifact_store: ArtifactStore,
    *,
    tenant_id: str,
    run_id: str,
    snapshot_id: str,
    staging_directory: str | os.PathLike[str] | None = None,
    expected_schema_version: int = SCHEMA_VERSION,
) -> ArtifactMetadata:
    """Back up, verify, and immutably publish one run database."""
    key = snapshot_artifact_key(tenant_id, run_id, snapshot_id)
    staging_root = Path(staging_directory) if staging_directory is not None else None
    if staging_root is not None:
        staging_root.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(suffix=".sqlite3", dir=staging_root)
    os.close(fd)
    staged = Path(name)
    staged.unlink(missing_ok=True)
    try:
        snapshot = create_sqlite_snapshot(
            source_database,
            staged,
            expected_schema_version=expected_schema_version,
        )
        return artifact_store.put_file(
            key, snapshot.path, expected_sha256=snapshot.sha256
        )
    finally:
        _remove_sqlite_temporary_files(staged)


def restore_sqlite_snapshot(
    artifact_store: ArtifactStore,
    *,
    tenant_id: str,
    run_id: str,
    snapshot_id: str,
    destination: str | os.PathLike[str],
    expected_sha256: str,
    expected_schema_version: int = SCHEMA_VERSION,
) -> SQLiteSnapshot:
    """Restore a verified artifact without exposing partial or corrupt state."""
    key = snapshot_artifact_key(tenant_id, run_id, snapshot_id)
    expected = _validate_sha256(expected_sha256)
    destination_path = Path(destination)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination_path.name}.", suffix=".restore", dir=destination_path.parent
    )
    os.close(fd)
    temporary = Path(temporary_name)
    temporary.unlink(missing_ok=True)
    try:
        metadata = artifact_store.get_file(key, temporary, expected_sha256=expected)
        if metadata.key != key:
            raise ArtifactIntegrityError(
                f"restore artifact key mismatch: expected {key}, got {metadata.key}"
            )
        if (
            isinstance(metadata.size_bytes, bool)
            or not isinstance(metadata.size_bytes, int)
            or metadata.size_bytes < 0
        ):
            raise ArtifactIntegrityError("restore artifact has invalid size metadata")
        if metadata.sha256 != expected:
            raise ArtifactIntegrityError(
                f"restore SHA-256 mismatch: expected {expected}, got {metadata.sha256}"
            )
        digest, size = _hash_file(temporary)
        if digest != expected or size != metadata.size_bytes:
            raise ArtifactIntegrityError("downloaded SQLite snapshot failed integrity check")
        version = _verify_sqlite_database(temporary, expected_schema_version)
        os.replace(temporary, destination_path)
        return SQLiteSnapshot(destination_path, digest, size, version)
    finally:
        _remove_sqlite_temporary_files(temporary)
