from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
import yaml

from engine.storage_policy import StoragePolicy, StorageBudgetExceeded
from hosted.artifacts import FilesystemArtifactStore
from hosted.config import HostedRuntimeConfig
from hosted.litestream import LitestreamRecoveryError
from hosted.supervisor import HostedRunSupervisor
from fastapi.testclient import TestClient
from .test_hosted_supervisor import FakeCatalog, tiny_profile


def supervisor(tmp_path, **options):
    return HostedRunSupervisor(
        FakeCatalog(), FilesystemArtifactStore(tmp_path / "artifacts"),
        work_root=tmp_path / "runs", checkpoint_root=tmp_path / "checkpoints",
        profiles={"tiny": tiny_profile()},
        storage_policy=StoragePolicy(min_free_bytes=0),
        snapshot_keep_last=2, **options)


def test_hosted_rotation_keeps_catalog_pointer_and_pinned_snapshot(tmp_path):
    async def scenario():
        manager = supervisor(tmp_path)
        handle = await manager.create_run(uuid4(), uuid4(), "tiny", "Rotation")
        try:
            first = handle.catalog_record.snapshot_object_key
            pinned = manager.artifact_store._artifact_dir(first)
            (pinned / "pin.json").write_text('{"reason":"milestone"}')
            for _ in range(5):
                await manager.snapshot_boundary(handle, "pause")
            current = manager.catalog.get_run(handle.tenant_id, handle.public_run_id).snapshot_object_key
            directories = list(pinned.parent.glob("*.sqlite3"))
            assert len(directories) == 3
            assert pinned.is_dir()
            manager.artifact_store.head(current)
            assert Path(handle.world.config["checkpoint_dir"]).is_relative_to(tmp_path / "checkpoints")
            assert not Path(handle.world.config["checkpoint_dir"]).is_relative_to(tmp_path / "runs")
        finally:
            await manager.shutdown()
    asyncio.run(scenario())


def test_streaming_mode_disables_duplicate_tick_copies_and_fails_closed(tmp_path):
    class FailingBackup:
        def restore(self, *args, **kwargs):
            raise LitestreamRecoveryError("remote unavailable")
    async def scenario():
        manager = supervisor(tmp_path, streaming_backup=FailingBackup(), snapshot_interval_ticks=0)
        handle = await manager.create_run(uuid4(), uuid4(), "tiny", "Streaming")
        try:
            before = handle.catalog_record.snapshot_object_key
            assert handle.world.checkpoint_every == 0
            await handle.world.step()
            await asyncio.sleep(0.05)
            assert handle.catalog_record.snapshot_object_key == before
            # There is a valid old full snapshot. An unavailable stream must
            # not turn that into an unnoticed rollback.
            destination = tmp_path / "new-cache"
            with pytest.raises(LitestreamRecoveryError, match="remote unavailable"):
                manager._restore_record_snapshot(handle.catalog_record, handle.tenant_id,
                                                 handle.public_run_id, handle.world_run_id, destination)
            assert not (destination / f"{handle.world_run_id}.db").exists()
        finally:
            await manager.shutdown()
    asyncio.run(scenario())


def test_stopping_retains_writer_lease_until_snapshot_cleanup_finishes(tmp_path, monkeypatch):
    from hosted.snapshot_retention import prune_local_snapshots

    async def scenario():
        manager = supervisor(tmp_path)
        handle = await manager.create_run(uuid4(), uuid4(), "tiny", "Stop safely")
        observed = []

        def prune_with_lease(store, key, **kwargs):
            record = manager.catalog.get_run(handle.tenant_id, handle.public_run_id)
            observed.append((record.snapshot_object_key, record.writer_lease_token))
            return prune_local_snapshots(store, key, **kwargs)

        monkeypatch.setattr("hosted.supervisor.prune_local_snapshots", prune_with_lease)
        try:
            metadata = await manager.snapshot_boundary(handle, "stop")
            assert observed == [(metadata.key, handle.lease_token)]
            record = manager.catalog.get_run(handle.tenant_id, handle.public_run_id)
            assert record.status == "stopped" and record.writer_lease_token is None
            manager.artifact_store.head(record.snapshot_object_key)
        finally:
            await manager.shutdown()
    asyncio.run(scenario())


def test_tenant_limit_blocks_new_runs_and_pauses_before_next_tick(tmp_path):
    async def scenario():
        manager = supervisor(tmp_path)
        tenant = uuid4()
        handle = await manager.create_run(tenant, uuid4(), "tiny", "Limit")
        try:
            pointer = handle.catalog_record.snapshot_object_key
            manager.catalog.update_run_status(tenant, handle.public_run_id, "running",
                                              lease_token=handle.lease_token)
            manager.storage_policy = replace(manager.storage_policy, max_tenant_bytes=1)
            with pytest.raises(StorageBudgetExceeded):
                await manager.create_run(tenant, uuid4(), "tiny", "Rejected")
            tick = handle.world.store.tick
            summary = await handle.world.step()
            await manager.drain_snapshots(handle)
            assert summary["paused"] == "storage" and handle.world.store.tick == tick
            assert handle.world.last_pause_reason["kind"] == "tenant"
            assert handle.catalog_record.status == "paused"
            assert handle.catalog_record.snapshot_object_key == pointer
        finally:
            # Re-enable space for the test's ordinary close snapshot.
            manager.storage_policy = replace(manager.storage_policy, max_tenant_bytes=0)
            await manager.shutdown()
    asyncio.run(scenario())


def test_litestream_runtime_rejects_backup_copies_inside_live_watch_root(tmp_path):
    values = dict(run_directory=tmp_path / "runs", snapshot_directory=tmp_path / "staging",
                  checkpoint_directory=tmp_path / "checkpoints", storage_policy=StoragePolicy(),
                  recovery_mode="litestream", snapshot_interval_ticks=0,
                  litestream_config=tmp_path / "litestream.yml")
    assert HostedRuntimeConfig(**values).snapshot_interval_ticks == 0
    for name in ("checkpoint_directory", "snapshot_directory"):
        with pytest.raises(ValueError):
            HostedRuntimeConfig(**{**values, name: tmp_path / "runs" / "copies"})
    with pytest.raises(ValueError):
        HostedRuntimeConfig(run_directory=tmp_path / "runs", snapshot_directory=tmp_path / "staging",
                            snapshot_interval_ticks=0)


def test_hosted_write_admission_preserves_read_access_when_disk_is_full(tmp_path):
    from server.app import create_app
    from .test_storage_policy import world_with_policy
    world = world_with_policy(tmp_path)
    app = create_app(world, hosted_safe=True)
    try:
        with TestClient(app) as client:
            world.storage_policy = replace(world.storage_policy, max_run_bytes=1)
            response = client.post("/api/run/start")
            assert response.status_code == 507
            assert response.json() == {"error": "storage_capacity_reached"}
            assert client.get("/api/run/status").status_code == 200
            assert client.post("/api/run/pause").status_code != 507
    finally:
        world.close()


def test_hostinger_deployment_has_no_amazon_dependency_and_bounds_logs():
    root = Path(__file__).resolve().parents[1]
    raw = (root / "deploy/hostinger/compose.yaml").read_text()
    assert "AWS_" not in raw and "minio" not in raw and "s3:" not in raw
    compose = yaml.safe_load(raw)
    services = compose["services"]
    assert {"app", "litestream", "catalog-backup", "postgres", "caddy"} <= services.keys()
    assert services["app"]["depends_on"]["litestream"]["condition"] == "service_healthy"
    for service in services.values():
        assert service["logging"]["options"] == {"max-size": "10m", "max-file": "3"}
    assert services["litestream"]["volumes"] == services["app"]["volumes"]
    assert "ports" not in services["litestream"]
    assert "ports" not in services["postgres"]


def test_public_hosted_controls_report_capacity_after_authorization(monkeypatch):
    from hosted.app import create_hosted_app
    from .test_hosted_app import (
        FakeCatalog as AppCatalog, FakeAuth, FakeSupervisor, NOW,
        TENANT_A, RUN_A, login, csrf_headers,
    )
    catalog = AppCatalog()
    manager = FakeSupervisor(catalog)

    def reject(*args, **kwargs):
        raise StorageBudgetExceeded("tenant", 2, 1)

    monkeypatch.setattr(manager, "check_write_admission", reject, raising=False)
    monkeypatch.setattr(manager, "create_run", reject)
    app = create_hosted_app(catalog=catalog, auth=FakeAuth(catalog), supervisor=manager,
                            clock=lambda: NOW)
    url = f"/api/v2/tenants/{TENANT_A}/runs/{RUN_A}/control"
    with TestClient(app, base_url="https://testserver") as client:
        assert client.post(url, json={"action": "step"}).status_code == 403  # CSRF first
        login(client)
        for action in ("start", "step", "snapshot"):
            response = client.post(url, json={"action": action}, headers=csrf_headers(client))
            assert response.status_code == 507
            assert response.json() == {"detail": {"code": "storage_capacity_reached"}}
        response = client.post(f"/api/v2/tenants/{TENANT_A}/runs",
                               json={"profile_slug": "alpha", "display_name": "Full"},
                               headers=csrf_headers(client))
        assert response.status_code == 507
        assert client.post(url, json={"action": "pause"}, headers=csrf_headers(client)).status_code == 200
        assert client.get(f"/api/v2/tenants/{TENANT_A}/runs/{RUN_A}").status_code == 200
        login(client, observer=True)
        assert client.post(url, json={"action": "step"}, headers=csrf_headers(client)).status_code == 403
