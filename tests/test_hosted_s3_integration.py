from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest

from engine.store import Store
from hosted.artifacts import (
    ArtifactConflict,
    ArtifactError,
    S3ArtifactStore,
    publish_sqlite_snapshot,
    restore_sqlite_snapshot,
)
from hosted.config import artifact_readiness_check


ENDPOINT = os.environ.get("AGENT_ECONOMY_TEST_S3_ENDPOINT", "")
ACCESS_KEY = os.environ.get("AGENT_ECONOMY_TEST_S3_ACCESS_KEY", "")
SECRET_KEY = os.environ.get("AGENT_ECONOMY_TEST_S3_SECRET_KEY", "")
BUCKET = os.environ.get("AGENT_ECONOMY_TEST_S3_BUCKET", "agent-economy-test")
SCOPED_ACCESS_KEY = os.environ.get("AGENT_ECONOMY_TEST_S3_SCOPED_ACCESS_KEY", "")
SCOPED_SECRET_KEY = os.environ.get("AGENT_ECONOMY_TEST_S3_SCOPED_SECRET_KEY", "")

pytestmark = pytest.mark.skipif(
    not (ENDPOINT and ACCESS_KEY and SECRET_KEY),
    reason="hosted S3 integration endpoint is not configured",
)


def _client(*, access_key: str = ACCESS_KEY, secret_key: str = SECRET_KEY):
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=ENDPOINT,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="us-east-1",
        config=Config(s3={"addressing_style": "path"}),
    )


def test_minio_snapshot_is_immutable_and_restores_exact_sqlite(tmp_path: Path) -> None:
    client = _client()
    try:
        client.head_bucket(Bucket=BUCKET)
    except Exception:
        client.create_bucket(Bucket=BUCKET)

    namespace = uuid4().hex
    artifacts = S3ArtifactStore(BUCKET, prefix=namespace, client=client)
    tenant_id = f"tenant-{uuid4()}"
    run_id = f"run-{uuid4()}"
    snapshot_id = "tick-000005"
    database = tmp_path / "source.db"
    store = Store(str(database))
    store.init_run_meta(run_id, 42, {"engine_semantics_version": 7})
    store.log_event(1, "integration_probe", {"ok": True})
    store.commit()
    store.close()

    metadata = publish_sqlite_snapshot(
        database,
        artifacts,
        tenant_id=tenant_id,
        run_id=run_id,
        snapshot_id=snapshot_id,
        staging_directory=tmp_path / "staging",
    )
    try:
        assert artifacts.head(metadata.key) == metadata
        with pytest.raises(ArtifactConflict):
            publish_sqlite_snapshot(
                database,
                artifacts,
                tenant_id=tenant_id,
                run_id=run_id,
                snapshot_id=snapshot_id,
                staging_directory=tmp_path / "staging-duplicate",
            )

        restored = tmp_path / "restored.db"
        result = restore_sqlite_snapshot(
            artifacts,
            tenant_id=tenant_id,
            run_id=run_id,
            snapshot_id=snapshot_id,
            destination=restored,
            expected_sha256=metadata.sha256,
        )
        assert result.sha256 == metadata.sha256
        reopened = Store(str(restored), create=False, read_only=True)
        try:
            row = reopened.query_one(
                "SELECT kind,payload_json FROM events WHERE kind='integration_probe'"
            )
            assert row is not None and row["kind"] == "integration_probe"
        finally:
            reopened.close()
    finally:
        artifacts.delete(metadata.key)


def test_scoped_runtime_identity_can_restore_but_cannot_delete(tmp_path: Path) -> None:
    if not (SCOPED_ACCESS_KEY and SCOPED_SECRET_KEY):
        pytest.skip("scoped hosted S3 integration credentials are not configured")

    root_client = _client()
    try:
        root_client.head_bucket(Bucket=BUCKET)
    except Exception:
        root_client.create_bucket(Bucket=BUCKET)
    scoped_client = _client(
        access_key=SCOPED_ACCESS_KEY,
        secret_key=SCOPED_SECRET_KEY,
    )
    artifacts = S3ArtifactStore(BUCKET, prefix="v1", client=scoped_client)
    cleanup = S3ArtifactStore(BUCKET, prefix="v1", client=root_client)
    assert artifact_readiness_check(artifacts) is True

    database = tmp_path / "scoped-source.db"
    store = Store(str(database))
    store.init_run_meta(f"run-{uuid4()}", 42, {"engine_semantics_version": 7})
    store.log_event(1, "scoped_integration_probe", {"ok": True})
    store.commit()
    store.close()
    tenant_id = f"tenant-{uuid4()}"
    run_id = f"run-{uuid4()}"
    snapshot_id = "tick-000001"
    metadata = publish_sqlite_snapshot(
        database,
        artifacts,
        tenant_id=tenant_id,
        run_id=run_id,
        snapshot_id=snapshot_id,
        staging_directory=tmp_path / "scoped-staging",
    )
    try:
        restored = tmp_path / "scoped-restored.db"
        result = restore_sqlite_snapshot(
            artifacts,
            tenant_id=tenant_id,
            run_id=run_id,
            snapshot_id=snapshot_id,
            destination=restored,
            expected_sha256=metadata.sha256,
        )
        assert result.sha256 == metadata.sha256
        with pytest.raises(ArtifactError):
            artifacts.delete(metadata.key)
        assert artifacts.head(metadata.key).sha256 == metadata.sha256
    finally:
        cleanup.delete(metadata.key)
