from __future__ import annotations

import base64
import hashlib
import io
import sqlite3
from pathlib import Path

import pytest

from engine.schema import SCHEMA_VERSION
from engine.store import Store
from hosted.artifacts import (
    ArtifactConflict,
    ArtifactError,
    ArtifactIntegrityError,
    ArtifactNotFound,
    FilesystemArtifactStore,
    InvalidArtifactKey,
    S3ArtifactStore,
    SnapshotError,
    create_sqlite_snapshot,
    publish_sqlite_snapshot,
    restore_sqlite_snapshot,
    snapshot_artifact_key,
)


class _FakeS3Error(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class _FakeS3Client:
    def __init__(self):
        self.objects: dict[tuple[str, str], tuple[bytes, dict[str, str]]] = {}

    def put_object(self, **request):
        identity = (request["Bucket"], request["Key"])
        if identity in self.objects:
            raise _FakeS3Error("PreconditionFailed")
        payload = request["Body"].read()
        expected_checksum = base64.b64encode(hashlib.sha256(payload).digest()).decode("ascii")
        assert request["IfNoneMatch"] == "*"
        assert request["ChecksumSHA256"] == expected_checksum
        self.objects[identity] = (payload, request["Metadata"])

    def head_object(self, **request):
        identity = (request["Bucket"], request["Key"])
        if identity not in self.objects:
            raise _FakeS3Error("NoSuchKey")
        payload, metadata = self.objects[identity]
        return {"ContentLength": len(payload), "Metadata": metadata}

    def get_object(self, **request):
        identity = (request["Bucket"], request["Key"])
        if identity not in self.objects:
            raise _FakeS3Error("NoSuchKey")
        payload, _ = self.objects[identity]
        return {"Body": io.BytesIO(payload)}

    def delete_object(self, **request):
        self.objects.pop((request["Bucket"], request["Key"]))


def _run_database(path: Path) -> Store:
    store = Store(str(path))
    store.init_run_meta("hosted-test", 91, {"profile": "hosted-test"})
    store.execute(
        "INSERT INTO agents (name, kind, occupation, age) VALUES (?, ?, ?, ?)",
        ("Ada", "citizen", "engineer", 36),
    )
    return store


def _agent_rows(path: Path) -> list[tuple]:
    connection = sqlite3.connect(path)
    try:
        return connection.execute(
            "SELECT id, name, kind, occupation, age FROM agents ORDER BY id"
        ).fetchall()
    finally:
        connection.close()


def test_filesystem_artifact_round_trip_and_delete(tmp_path: Path) -> None:
    artifact_store = FilesystemArtifactStore(tmp_path / "artifacts")
    source = tmp_path / "source.bin"
    source.write_bytes(b"durable snapshot bytes")
    key = snapshot_artifact_key("tenant-a", "run-17", "checkpoint-5")

    metadata = artifact_store.put_file(key, source)

    assert metadata.sha256 == hashlib.sha256(source.read_bytes()).hexdigest()
    assert metadata.size_bytes == source.stat().st_size
    assert artifact_store.head(key) == metadata
    downloaded = tmp_path / "downloaded.sqlite3"
    assert artifact_store.get_file(
        key, downloaded, expected_sha256=metadata.sha256
    ) == metadata
    assert downloaded.read_bytes() == source.read_bytes()

    artifact_store.delete(key)
    with pytest.raises(ArtifactNotFound):
        artifact_store.head(key)


@pytest.mark.parametrize(
    "key",
    [
        "../escape.sqlite3",
        "tenants/t/runs/r/snapshots/../../escape.sqlite3",
        "tenants/t/runs/r/snapshots/x.sqlite3/extra",
        "tenants/t\\evil/runs/r/snapshots/x.sqlite3",
        "/tenants/t/runs/r/snapshots/x.sqlite3",
        "tenants/t/runs/r/exports/x.sqlite3",
    ],
)
def test_filesystem_store_rejects_traversal_and_non_snapshot_keys(
    tmp_path: Path, key: str
) -> None:
    artifact_store = FilesystemArtifactStore(tmp_path / "artifacts")
    source = tmp_path / "source.bin"
    source.write_bytes(b"x")

    with pytest.raises(InvalidArtifactKey):
        artifact_store.put_file(key, source)
    assert list((tmp_path / "artifacts").rglob("payload")) == []


def test_filesystem_store_does_not_follow_namespace_symlinks(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    artifact_store = FilesystemArtifactStore(root)
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (root / "tenants").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("creating directory symlinks is not permitted on this platform")
    source = tmp_path / "source.bin"
    source.write_bytes(b"x")

    with pytest.raises(InvalidArtifactKey):
        artifact_store.put_file(
            snapshot_artifact_key("tenant", "run", "snapshot"), source
        )

    assert list(outside.iterdir()) == []


def test_filesystem_artifacts_are_immutable(tmp_path: Path) -> None:
    artifact_store = FilesystemArtifactStore(tmp_path / "artifacts")
    first = tmp_path / "first.bin"
    second = tmp_path / "second.bin"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    key = snapshot_artifact_key("tenant", "run", "snap")
    original = artifact_store.put_file(key, first)

    with pytest.raises(ArtifactConflict):
        artifact_store.put_file(key, second)

    downloaded = tmp_path / "result.bin"
    artifact_store.get_file(key, downloaded, expected_sha256=original.sha256)
    assert downloaded.read_bytes() == b"first"


def test_filesystem_artifact_corruption_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    artifact_store = FilesystemArtifactStore(root)
    source = tmp_path / "source.bin"
    source.write_bytes(b"original")
    key = snapshot_artifact_key("tenant", "run", "snap")
    artifact_store.put_file(key, source)
    (root.joinpath(*key.split("/")) / "payload").write_bytes(b"tampered")

    with pytest.raises(ArtifactIntegrityError):
        artifact_store.head(key)
    destination = tmp_path / "must-not-exist.bin"
    with pytest.raises(ArtifactIntegrityError):
        artifact_store.get_file(key, destination)
    assert not destination.exists()


def test_s3_artifact_store_uses_conditional_immutable_objects(tmp_path: Path) -> None:
    client = _FakeS3Client()
    artifact_store = S3ArtifactStore("hosted-runs", prefix="prod", client=client)
    source = tmp_path / "source.bin"
    source.write_bytes(b"s3 snapshot")
    key = snapshot_artifact_key("tenant", "run", "snapshot")

    metadata = artifact_store.put_file(key, source)
    assert artifact_store.head(key) == metadata
    destination = tmp_path / "download.bin"
    artifact_store.get_file(key, destination, expected_sha256=metadata.sha256)
    assert destination.read_bytes() == b"s3 snapshot"
    with pytest.raises(ArtifactConflict):
        artifact_store.put_file(key, source)

    artifact_store.delete(key)
    with pytest.raises(ArtifactNotFound):
        artifact_store.head(key)


def test_create_snapshot_uses_consistent_backup_and_preserves_table_content(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "live.db"
    store = _run_database(source_path)
    destination = tmp_path / "snapshot.db"
    try:
        snapshot = create_sqlite_snapshot(source_path, destination)
        store.execute(
            "INSERT INTO agents (name, kind, occupation, age) VALUES (?, ?, ?, ?)",
            ("Grace", "citizen", "scientist", 40),
        )
    finally:
        store.close()

    assert snapshot.schema_version == SCHEMA_VERSION
    assert snapshot.sha256 == hashlib.sha256(destination.read_bytes()).hexdigest()
    assert _agent_rows(destination) == [(1, "Ada", "citizen", "engineer", 36)]
    connection = sqlite3.connect(destination)
    try:
        assert connection.execute("PRAGMA quick_check").fetchone() == ("ok",)
    finally:
        connection.close()


def test_failed_snapshot_does_not_replace_existing_destination(tmp_path: Path) -> None:
    source = tmp_path / "invalid.db"
    source.write_bytes(b"not sqlite")
    destination = tmp_path / "existing.db"
    destination.write_bytes(b"keep me")

    with pytest.raises(SnapshotError):
        create_sqlite_snapshot(source, destination)

    assert destination.read_bytes() == b"keep me"


def test_publish_failure_cleans_staging_file(tmp_path: Path) -> None:
    source_path = tmp_path / "live.db"
    store = _run_database(source_path)
    staging = tmp_path / "staging"

    class FailingStore:
        def put_file(self, key, source, *, expected_sha256=None):
            assert Path(source).is_file()
            raise ArtifactError("injected upload failure")

    try:
        with pytest.raises(ArtifactError, match="injected upload failure"):
            publish_sqlite_snapshot(
                source_path,
                FailingStore(),
                tenant_id="tenant",
                run_id="run",
                snapshot_id="snap",
                staging_directory=staging,
            )
    finally:
        store.close()

    assert list(staging.iterdir()) == []


def test_publish_and_restore_verified_sqlite_snapshot(tmp_path: Path) -> None:
    source_path = tmp_path / "live.db"
    store = _run_database(source_path)
    artifact_store = FilesystemArtifactStore(tmp_path / "artifacts")
    try:
        metadata = publish_sqlite_snapshot(
            source_path,
            artifact_store,
            tenant_id="tenant-a",
            run_id="run-a",
            snapshot_id="checkpoint-1",
        )
    finally:
        store.close()

    restored = tmp_path / "restored.db"
    result = restore_sqlite_snapshot(
        artifact_store,
        tenant_id="tenant-a",
        run_id="run-a",
        snapshot_id="checkpoint-1",
        destination=restored,
        expected_sha256=metadata.sha256,
    )

    assert result.sha256 == metadata.sha256
    assert result.schema_version == SCHEMA_VERSION
    assert _agent_rows(restored) == [(1, "Ada", "citizen", "engineer", 36)]


def test_restore_missing_or_wrong_hash_leaves_destination_untouched(tmp_path: Path) -> None:
    artifact_store = FilesystemArtifactStore(tmp_path / "artifacts")
    destination = tmp_path / "restored.db"
    destination.write_bytes(b"existing destination")

    with pytest.raises(ArtifactNotFound):
        restore_sqlite_snapshot(
            artifact_store,
            tenant_id="tenant",
            run_id="run",
            snapshot_id="missing",
            destination=destination,
            expected_sha256="0" * 64,
        )
    assert destination.read_bytes() == b"existing destination"

    source_path = tmp_path / "live.db"
    store = _run_database(source_path)
    try:
        publish_sqlite_snapshot(
            source_path,
            artifact_store,
            tenant_id="tenant",
            run_id="run",
            snapshot_id="present",
        )
    finally:
        store.close()
    with pytest.raises(ArtifactIntegrityError):
        restore_sqlite_snapshot(
            artifact_store,
            tenant_id="tenant",
            run_id="run",
            snapshot_id="present",
            destination=destination,
            expected_sha256="f" * 64,
        )
    assert destination.read_bytes() == b"existing destination"


def test_restore_rejects_wrong_schema_before_replace(tmp_path: Path) -> None:
    source_path = tmp_path / "live.db"
    store = _run_database(source_path)
    artifact_store = FilesystemArtifactStore(tmp_path / "artifacts")
    try:
        metadata = publish_sqlite_snapshot(
            source_path,
            artifact_store,
            tenant_id="tenant",
            run_id="run",
            snapshot_id="schema",
        )
    finally:
        store.close()
    destination = tmp_path / "restored.db"
    destination.write_bytes(b"preserve")

    with pytest.raises(SnapshotError, match="does not match expected"):
        restore_sqlite_snapshot(
            artifact_store,
            tenant_id="tenant",
            run_id="run",
            snapshot_id="schema",
            destination=destination,
            expected_sha256=metadata.sha256,
            expected_schema_version=SCHEMA_VERSION + 1,
        )

    assert destination.read_bytes() == b"preserve"
