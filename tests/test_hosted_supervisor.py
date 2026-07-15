from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from hosted.artifacts import FilesystemArtifactStore
from hosted.supervisor import (
    HostedRunSupervisor,
    InvalidProfile,
    RunCapacityExceeded,
    WriterLeaseLost,
    WriterLeaseUnavailable,
)


@dataclass(frozen=True)
class FakeRun:
    id: UUID
    tenant_id: UUID
    owner_user_id: UUID
    run_key: str
    display_name: str
    status: str
    schema_version: int
    engine_semantics_version: int
    catalog: dict[str, Any]
    snapshot_object_key: str | None = None
    snapshot_sha256: str | None = None
    snapshot_size_bytes: int | None = None
    writer_lease_owner: str | None = None
    writer_lease_token: UUID | None = None


class FakeCatalog:
    def __init__(self) -> None:
        self.runs: dict[UUID, FakeRun] = {}
        self._lease_counter = 0

    def create_run(self, tenant_id, **kwargs):
        run_id = UUID(str(kwargs["run_id"]))
        record = FakeRun(
            id=run_id,
            tenant_id=UUID(str(tenant_id)),
            owner_user_id=UUID(str(kwargs["owner_user_id"])),
            run_key=str(kwargs["run_key"]),
            display_name=str(kwargs["display_name"]),
            status="created",
            schema_version=int(kwargs["schema_version"]),
            engine_semantics_version=int(kwargs["engine_semantics_version"]),
            catalog=dict(kwargs.get("catalog") or {}),
        )
        self.runs[run_id] = record
        return record

    def get_run(self, tenant_id, run_id):
        record = self.runs.get(UUID(str(run_id)))
        if record is None or record.tenant_id != UUID(str(tenant_id)):
            return None
        return record

    def list_runs(self, tenant_id, *, limit=100):
        tenant = UUID(str(tenant_id))
        return tuple(r for r in self.runs.values() if r.tenant_id == tenant)[:limit]

    def list_active_runs(self):
        return tuple(
            record for record in self.runs.values()
            if record.status in {"starting", "running", "paused"}
        )

    def acquire_writer_lease(self, tenant_id, run_id, *, owner, ttl_seconds):
        record = self.get_run(tenant_id, run_id)
        if record is None or record.writer_lease_token is not None:
            return None
        self._lease_counter += 1
        token = UUID(int=self._lease_counter)
        self.runs[record.id] = replace(
            record, writer_lease_owner=owner, writer_lease_token=token)
        return token

    def renew_writer_lease(
        self, tenant_id, run_id, *, owner, token, ttl_seconds
    ):
        record = self.get_run(tenant_id, run_id)
        return bool(
            record
            and record.writer_lease_owner == owner
            and record.writer_lease_token == UUID(str(token))
        )

    def release_writer_lease(self, tenant_id, run_id, *, token):
        record = self.get_run(tenant_id, run_id)
        if record is None or record.writer_lease_token != UUID(str(token)):
            return False
        self.runs[record.id] = replace(
            record, writer_lease_owner=None, writer_lease_token=None)
        return True

    def update_snapshot_pointer(
        self,
        tenant_id,
        run_id,
        *,
        lease_token,
        object_key,
        sha256,
        size_bytes,
    ):
        record = self.get_run(tenant_id, run_id)
        if record is None or record.writer_lease_token != UUID(str(lease_token)):
            return False
        self.runs[record.id] = replace(
            record,
            snapshot_object_key=object_key,
            snapshot_sha256=sha256,
            snapshot_size_bytes=size_bytes,
        )
        return True

    def update_run_status(
        self, tenant_id, run_id, status, *, lease_token=None
    ):
        record = self.get_run(tenant_id, run_id)
        if record is None:
            return None
        if lease_token is not None and record.writer_lease_token != UUID(str(lease_token)):
            return None
        terminal = status in {"stopped", "failed", "archived"}
        updated = replace(
            record,
            status=status,
            writer_lease_owner=None if terminal else record.writer_lease_owner,
            writer_lease_token=None if terminal else record.writer_lease_token,
        )
        self.runs[record.id] = updated
        return updated


def tiny_profile() -> dict[str, Any]:
    return {
        "seed": 19,
        "engine_semantics_version": 7,
        "population": {"size": 4},
        "banks": {"count": 1},
        "firms": {"count": 1, "listed": 0, "target_headcount": 1},
        "behavior": {"act_every": 1000, "run_threshold": 0.35},
        "budget": {
            "cap_usd": 10.0,
            "oracle_reserve_usd": 1.0,
            "report_reserve_usd": 0.0,
            "conversation_pairs": 0,
            "thresholds": [0.6, 0.8, 0.95],
        },
        "llm": {
            "default_route": {"provider": "scripted", "model": "scripted"},
            "routes": {},
        },
        "checkpoint_every": 0,
        "outlets": [],
    }


def make_supervisor(tmp_path: Path, catalog: FakeCatalog, **kwargs) -> HostedRunSupervisor:
    return HostedRunSupervisor(
        catalog,
        FilesystemArtifactStore(tmp_path / "artifacts"),
        work_root=tmp_path / "work",
        profiles={"tiny": tiny_profile()},
        instance_id=kwargs.pop("instance_id", "test-supervisor"),
        snapshot_interval_ticks=kwargs.pop("snapshot_interval_ticks", 1),
        **kwargs,
    )


def test_two_tenant_runs_are_isolated_allowlisted_and_closed(tmp_path):
    async def scenario():
        catalog = FakeCatalog()
        supervisor = make_supervisor(tmp_path, catalog)
        tenant_a, tenant_b = uuid4(), uuid4()
        user_a, user_b = uuid4(), uuid4()

        run_a = await supervisor.create_run(tenant_a, user_a, "tiny", "A")
        run_b = await supervisor.create_run(tenant_b, user_b, "tiny", "B")

        assert UUID(run_a.public_run_id)
        assert UUID(run_b.public_run_id)
        assert run_a.public_run_id != run_b.public_run_id
        assert run_a.world is not run_b.world
        assert run_a.database_path != run_b.database_path
        assert (tmp_path / "work" / "tenants" / str(tenant_a)) in run_a.database_path.parents
        assert (tmp_path / "work" / "tenants" / str(tenant_b)) in run_b.database_path.parents
        assert await supervisor.get_handle(tenant_a, run_b.public_run_id) is None
        assert len(supervisor.list_runs(tenant_a)) == 1

        summaries = await asyncio.gather(
            run_a.controller.step(), run_b.controller.step())
        await asyncio.gather(
            supervisor.drain_snapshots(run_a),
            supervisor.drain_snapshots(run_b),
        )
        assert [summary["tick"] for summary in summaries] == [1, 1]
        assert run_a.world.store.tick == run_b.world.store.tick == 1
        with pytest.raises(InvalidProfile):
            await supervisor.create_run(tenant_a, user_a, "../base", "bad")

        await supervisor.shutdown()
        assert run_a.world.store._closed
        assert run_b.world.store._closed
        assert catalog.runs[UUID(run_a.public_run_id)].writer_lease_token is None
        assert catalog.runs[UUID(run_b.public_run_id)].writer_lease_token is None

    asyncio.run(scenario())


def test_concurrent_creates_reserve_capacity_before_opening_worlds(tmp_path):
    async def scenario():
        catalog = FakeCatalog()
        supervisor = make_supervisor(tmp_path, catalog, max_loaded_runs=1)
        tenant, owner = uuid4(), uuid4()

        results = await asyncio.gather(
            supervisor.create_run(tenant, owner, "tiny", "first"),
            supervisor.create_run(tenant, owner, "tiny", "second"),
            return_exceptions=True,
        )
        assert sum(not isinstance(item, BaseException) for item in results) == 1
        assert sum(isinstance(item, RunCapacityExceeded) for item in results) == 1
        assert len(supervisor.loaded_runs) == 1
        assert supervisor._pending_run_ids == set()
        await supervisor.shutdown()

    asyncio.run(scenario())


def test_tick_snapshot_cadence_is_bounded_but_pause_close_remain_durable(tmp_path):
    async def scenario():
        catalog = FakeCatalog()
        supervisor = make_supervisor(tmp_path, catalog, snapshot_interval_ticks=2)
        handle = await supervisor.create_run(uuid4(), uuid4(), "tiny", "Cadence")
        run_id = UUID(handle.public_run_id)
        initial_key = catalog.runs[run_id].snapshot_object_key

        await handle.controller.step()
        await supervisor.drain_snapshots(handle)
        assert catalog.runs[run_id].snapshot_object_key == initial_key

        await handle.controller.step()
        await supervisor.drain_snapshots(handle)
        assert catalog.runs[run_id].snapshot_object_key != initial_key
        assert "-tick.sqlite3" in str(catalog.runs[run_id].snapshot_object_key)

        await supervisor.close_run(handle)
        assert "-pause.sqlite3" in str(catalog.runs[run_id].snapshot_object_key)

    asyncio.run(scenario())


def test_shutdown_snapshot_drain_obeys_one_grace_deadline(tmp_path):
    async def scenario():
        catalog = FakeCatalog()
        supervisor = make_supervisor(tmp_path, catalog, shutdown_grace_seconds=1)
        handle = await supervisor.create_run(uuid4(), uuid4(), "tiny", "Bounded close")
        blocker = asyncio.create_task(asyncio.Event().wait())
        handle.snapshot_tasks.add(blocker)
        started = asyncio.get_running_loop().time()

        with pytest.raises(asyncio.TimeoutError):
            await supervisor.close_run(handle)

        assert asyncio.get_running_loop().time() - started < 1.5
        assert blocker.cancelled()
        assert handle.closed
        assert handle.world.store._closed

    asyncio.run(scenario())


def test_first_artifact_failure_pauses_suppresses_storm_and_manual_retry_recovers(tmp_path):
    class FailingStore:
        def put_file(self, *_args, **_kwargs):
            raise RuntimeError("simulated artifact outage")

    async def scenario():
        catalog = FakeCatalog()
        supervisor = make_supervisor(tmp_path, catalog, snapshot_interval_ticks=1)
        handle = await supervisor.create_run(uuid4(), uuid4(), "tiny", "Artifact failure")
        healthy_store = supervisor.artifact_store
        supervisor.artifact_store = FailingStore()

        await handle.controller.step()
        with pytest.raises(RuntimeError, match="simulated artifact outage"):
            await supervisor.drain_snapshots(handle)

        assert handle.snapshot_failed
        assert handle.world._pause_requested
        assert catalog.runs[UUID(handle.public_run_id)].status == "snapshot_failed"
        assert not [task for task in handle.snapshot_tasks if not task.done()]

        supervisor.artifact_store = healthy_store
        recovered = await supervisor.snapshot_boundary(handle, "pause", manual=True)
        assert recovered.sha256
        assert not handle.snapshot_failed
        assert catalog.runs[UUID(handle.public_run_id)].status == "paused"
        await supervisor.shutdown()

    asyncio.run(scenario())


def test_snapshot_fails_closed_when_writer_lease_is_lost(tmp_path):
    async def scenario():
        catalog = FakeCatalog()
        supervisor = make_supervisor(tmp_path, catalog)
        handle = await supervisor.create_run(uuid4(), uuid4(), "tiny", "Lease loss")
        run_id = UUID(handle.public_run_id)
        record = catalog.runs[run_id]
        catalog.runs[run_id] = replace(
            record, writer_lease_owner=None, writer_lease_token=None)

        with pytest.raises(WriterLeaseLost):
            await supervisor.snapshot_boundary(handle, "tick")
        assert handle.world._pause_requested

        # Restore the fake lease only so shutdown can persist and close the
        # already-paused world; a real supervisor would reacquire after expiry.
        record = catalog.runs[run_id]
        catalog.runs[run_id] = replace(
            record,
            writer_lease_owner=supervisor.instance_id,
            writer_lease_token=handle.lease_token,
        )
        await supervisor.shutdown()
        assert handle.world.store._closed

    asyncio.run(scenario())


def test_completed_tick_pause_and_stop_publish_immutable_snapshots(tmp_path):
    async def scenario():
        catalog = FakeCatalog()
        supervisor = make_supervisor(tmp_path, catalog)
        tenant, owner = uuid4(), uuid4()
        handle = await supervisor.create_run(tenant, owner, "tiny", "Boundaries")
        first_key = catalog.runs[UUID(handle.public_run_id)].snapshot_object_key

        summary = await handle.controller.step()
        assert summary["tick"] == 1
        await supervisor.drain_snapshots(handle)
        tick_record = catalog.runs[UUID(handle.public_run_id)]
        assert tick_record.snapshot_object_key != first_key
        assert "-tick.sqlite3" in str(tick_record.snapshot_object_key)
        assert supervisor.artifact_store.head(tick_record.snapshot_object_key).sha256 == (
            tick_record.snapshot_sha256
        )

        supervisor.observe_control(handle, "/api/run/pause", "POST")
        await supervisor.drain_snapshots(handle)
        pause_record = catalog.runs[UUID(handle.public_run_id)]
        assert "-pause.sqlite3" in str(pause_record.snapshot_object_key)

        # Avoid invoking report generation in this lifecycle-focused test.
        handle.world.last_report_path = str(handle.work_dir / "reports" / "already-generated.html")
        result = await handle.controller.stop()
        assert result["status"] == "finished"
        supervisor.observe_control(handle, "/api/run/stop", "POST")
        await supervisor.drain_snapshots(handle)
        stopped = catalog.runs[UUID(handle.public_run_id)]
        assert stopped.status == "stopped"
        assert "-stop.sqlite3" in str(stopped.snapshot_object_key)

        await supervisor.shutdown()

    asyncio.run(scenario())


def test_one_writer_lease_and_restart_recovery_pauses_active_run(tmp_path):
    async def scenario():
        catalog = FakeCatalog()
        tenant, owner = uuid4(), uuid4()
        first = make_supervisor(tmp_path, catalog, instance_id="first")
        handle = await first.create_run(tenant, owner, "tiny", "Recover me")
        record = catalog.runs[UUID(handle.public_run_id)]
        catalog.runs[record.id] = replace(record, status="running")

        second = make_supervisor(tmp_path, catalog, instance_id="second")
        assert await second.recover_active_runs() == ()
        assert catalog.runs[record.id].status == "running"
        with pytest.raises(WriterLeaseUnavailable):
            await second.get_handle(tenant, handle.public_run_id)
        await second.shutdown()

        completed_tick = handle.world.store.tick
        await first.close_run(handle)
        record = catalog.runs[UUID(handle.public_run_id)]
        catalog.runs[record.id] = replace(record, status="running")

        restarted = make_supervisor(tmp_path, catalog, instance_id="restart")
        recovered = await restarted.recover_active_runs()
        assert len(recovered) == 1
        recovered_handle = recovered[0]
        assert recovered_handle.public_run_id == handle.public_run_id
        assert recovered_handle.world.status == "paused"
        assert catalog.runs[record.id].status == "paused"
        assert recovered_handle.world.store.tick == completed_tick

        await restarted.shutdown()
        await first.shutdown()

    asyncio.run(scenario())
