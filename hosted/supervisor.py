"""Tenant-scoped supervision for hosted simulation runs.

The simulator remains a one-``World``/one-SQLite-file application.  This
module composes several of those applications behind a small control-plane
protocol without changing local mode or putting replay-sensitive state in the
hosted catalog.
"""

from __future__ import annotations

import asyncio
import copy
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence, runtime_checkable
from uuid import UUID, uuid4

from engine.schema import SCHEMA_VERSION
from engine.semantics import semantics_version
from hosted.artifacts import (
    ArtifactMetadata,
    ArtifactStore,
    publish_sqlite_snapshot,
    restore_sqlite_snapshot,
    validate_snapshot_artifact_key,
)
from run import open_run
from run_config import load_config
from server.app import create_app


_PROFILE_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
_RUN_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,159}$")
_SNAPSHOT_SEQUENCE_RE = re.compile(r"-s(?P<sequence>[0-9]{8})-[a-z]+\.sqlite3$")


class HostedRunError(RuntimeError):
    """Base class for hosted run lifecycle failures."""


class InvalidProfile(HostedRunError, ValueError):
    """The requested profile is not in the server-owned allowlist."""


class InvalidRunIdentifier(HostedRunError, ValueError):
    """A public run or tenant identifier was malformed."""


class RunCapacityExceeded(HostedRunError):
    """This supervisor has reached its configured in-memory run bound."""


class WriterLeaseUnavailable(HostedRunError):
    """Another process owns the run's writer lease."""


class WriterLeaseLost(HostedRunError):
    """The control-plane lease was lost while publishing a boundary."""


@runtime_checkable
class CatalogProtocol(Protocol):
    """The narrow catalog surface required by the supervisor.

    ``HostedCatalog`` implements this protocol.  Tests and embedders can use a
    transactionally equivalent in-memory implementation without importing
    PostgreSQL.
    """

    def create_run(self, tenant_id: Any, **kwargs: Any) -> Any: ...

    def get_run(self, tenant_id: Any, run_id: Any) -> Any | None: ...

    def list_runs(self, tenant_id: Any, *, limit: int = 100) -> Sequence[Any]: ...

    def list_active_runs(self) -> Sequence[Any]: ...

    def acquire_writer_lease(
        self, tenant_id: Any, run_id: Any, *, owner: str, ttl_seconds: int
    ) -> Any | None: ...

    def renew_writer_lease(
        self,
        tenant_id: Any,
        run_id: Any,
        *,
        owner: str,
        token: Any,
        ttl_seconds: int,
    ) -> bool: ...

    def release_writer_lease(
        self, tenant_id: Any, run_id: Any, *, token: Any
    ) -> bool: ...

    def update_snapshot_pointer(
        self,
        tenant_id: Any,
        run_id: Any,
        *,
        lease_token: Any,
        object_key: str,
        sha256: str,
        size_bytes: int,
    ) -> bool: ...

    def update_run_status(
        self,
        tenant_id: Any,
        run_id: Any,
        status: str,
        *,
        lease_token: Any | None = None,
    ) -> Any | None: ...


def _record_value(record: Any, name: str, default: Any = None) -> Any:
    if isinstance(record, Mapping):
        return record.get(name, default)
    return getattr(record, name, default)


def _public_run_id(value: Any) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise InvalidRunIdentifier("hosted run id must be a UUID") from exc


def _tenant_id(value: Any) -> str:
    # HostedCatalog uses UUID tenant ids.  Keeping the same invariant at the
    # filesystem boundary prevents aliases such as case variants or path-like
    # slugs from ever selecting a work directory.
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise InvalidRunIdentifier("hosted tenant id must be a UUID") from exc


def _owner_user_id(value: Any) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise InvalidRunIdentifier("hosted owner user id must be a UUID") from exc


def _run_key(value: Any) -> str:
    candidate = str(value)
    if _RUN_KEY_RE.fullmatch(candidate) is None:
        raise InvalidRunIdentifier("catalog run key is not a safe local identifier")
    return candidate


def _profile_slug(value: Any) -> str:
    candidate = str(value)
    if _PROFILE_SLUG_RE.fullmatch(candidate) is None:
        raise InvalidProfile("profile slug must be a lowercase allowlist identifier")
    return candidate


@dataclass
class RunHandle:
    """One loaded tenant run and its independently scoped ASGI application."""

    tenant_id: str
    public_run_id: str
    owner_user_id: str
    profile_slug: str
    work_dir: Path
    data_dir: Path
    world_run_id: str
    world: Any
    app: Any
    controller: Any
    lease_token: Any
    catalog_record: Any
    snapshot_sequence: int = 0
    snapshot_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    snapshot_tasks: set[asyncio.Task[Any]] = field(default_factory=set)
    snapshot_errors: list[BaseException] = field(default_factory=list)
    snapshot_failed: bool = False
    observed_controller_task: asyncio.Task[Any] | None = None
    lease_task: asyncio.Task[Any] | None = None
    event_loop: asyncio.AbstractEventLoop | None = None
    lease_lost: bool = False
    closed: bool = False

    @property
    def database_path(self) -> Path:
        """Internal-only path used by snapshot code; never serialize this."""
        return Path(self.world.store.path)

    def status(self) -> dict[str, Any]:
        """Return a path-free status document safe for hosted APIs."""
        record = self.catalog_record
        return {
            "run_id": self.public_run_id,
            "tenant_id": self.tenant_id,
            "profile_slug": self.profile_slug,
            "status": str(_record_value(record, "status", self.world.status)),
            "tick": int(self.world.store.tick),
            "snapshot_failed": self.snapshot_failed,
            "snapshot": (
                {
                    "object_key": str(_record_value(record, "snapshot_object_key")),
                    "sha256": str(_record_value(record, "snapshot_sha256")),
                    "size_bytes": int(_record_value(record, "snapshot_size_bytes", 0)),
                }
                if _record_value(record, "snapshot_object_key")
                else None
            ),
        }


class HostedRunSupervisor:
    """Bounded owner of tenant-isolated ``World`` instances.

    Profiles are passed as an explicit slug-to-file/config mapping.  No request
    value is ever joined onto a profile path.  Public run ids are UUIDs generated
    inside this class; the simulator's own run key remains an implementation
    detail used only to locate its tenant-scoped SQLite file.
    """

    def __init__(
        self,
        catalog: CatalogProtocol,
        artifact_store: ArtifactStore,
        *,
        work_root: str | Path,
        profiles: Mapping[str, str | Path | Mapping[str, Any]],
        instance_id: str = "hosted-supervisor",
        max_loaded_runs: int = 32,
        lease_ttl_seconds: int = 60,
        snapshot_interval_ticks: int = 5,
        shutdown_grace_seconds: int = 30,
        run_id_factory: Callable[[], UUID | str] = uuid4,
    ) -> None:
        if not isinstance(max_loaded_runs, int) or isinstance(max_loaded_runs, bool):
            raise ValueError("max_loaded_runs must be an integer")
        if not (1 <= max_loaded_runs <= 1000):
            raise ValueError("max_loaded_runs must be between 1 and 1000")
        if not (5 <= int(lease_ttl_seconds) <= 3600):
            raise ValueError("lease_ttl_seconds must be between 5 and 3600")
        if not (1 <= int(snapshot_interval_ticks) <= 1_000_000):
            raise ValueError("snapshot_interval_ticks must be between 1 and 1000000")
        if not (1 <= int(shutdown_grace_seconds) <= 3600):
            raise ValueError("shutdown_grace_seconds must be between 1 and 3600")
        if not instance_id.strip() or len(instance_id) > 200:
            raise ValueError("instance_id must be 1 to 200 characters")
        if not profiles:
            raise ValueError("at least one hosted profile must be allowlisted")

        normalized_profiles: dict[str, str | Path | Mapping[str, Any]] = {}
        for slug, source in profiles.items():
            normalized = _profile_slug(slug)
            if normalized in normalized_profiles:
                raise ValueError(f"duplicate hosted profile slug: {normalized}")
            if isinstance(source, Mapping):
                normalized_profiles[normalized] = copy.deepcopy(dict(source))
            else:
                path = Path(source).resolve()
                if not path.is_file():
                    raise ValueError(f"hosted profile does not exist: {path}")
                normalized_profiles[normalized] = path

        self.catalog = catalog
        self.artifact_store = artifact_store
        self.work_root = Path(work_root).resolve()
        self.work_root.mkdir(parents=True, exist_ok=True)
        self.profiles = normalized_profiles
        self.instance_id = instance_id.strip()
        self.max_loaded_runs = max_loaded_runs
        self.lease_ttl_seconds = int(lease_ttl_seconds)
        self.snapshot_interval_ticks = int(snapshot_interval_ticks)
        self.shutdown_grace_seconds = int(shutdown_grace_seconds)
        self._run_id_factory = run_id_factory
        self._handles: dict[str, RunHandle] = {}
        self._pending_run_ids: set[str] = set()
        self._handles_lock = asyncio.Lock()
        self._closing = False

    @property
    def loaded_runs(self) -> tuple[RunHandle, ...]:
        return tuple(self._handles[key] for key in sorted(self._handles))

    def ready(self) -> bool:
        """Bounded, path-free readiness check used by the hosted app."""
        catalog_probe = getattr(self.catalog, "ready", None)
        try:
            catalog_ready = bool(catalog_probe and catalog_probe())
        except Exception:
            catalog_ready = False
        return (
            not self._closing
            and catalog_ready
            and self.work_root.is_dir()
            and os.access(self.work_root, os.R_OK | os.W_OK)
        )

    def list_runs(self, tenant_id: Any, *, limit: int = 100) -> Sequence[Any]:
        return self.catalog.list_runs(_tenant_id(tenant_id), limit=limit)

    def _load_profile(self, slug: Any) -> tuple[str, dict[str, Any]]:
        normalized = _profile_slug(slug)
        source = self.profiles.get(normalized)
        if source is None:
            raise InvalidProfile(f"profile is not allowlisted: {normalized}")
        if isinstance(source, Mapping):
            config = copy.deepcopy(dict(source))
        else:
            config = load_config(str(source))
        if not isinstance(config, dict):
            raise InvalidProfile(f"profile must load to a mapping: {normalized}")
        return normalized, config

    def _run_directories(self, tenant_id: str, public_run_id: str) -> tuple[Path, Path]:
        work_dir = self.work_root / "tenants" / tenant_id / "runs" / public_run_id
        resolved = work_dir.resolve()
        try:
            resolved.relative_to(self.work_root)
        except ValueError as exc:  # defensive even though both ids are UUIDs
            raise InvalidRunIdentifier("hosted run directory escapes work root") from exc
        data_dir = resolved / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        return resolved, data_dir

    @staticmethod
    def _snapshot_sequence(record: Any) -> int:
        key = _record_value(record, "snapshot_object_key")
        if not key:
            return 0
        match = _SNAPSHOT_SEQUENCE_RE.search(str(key))
        return int(match.group("sequence")) if match else 0

    def _bounded_config(self, config: dict[str, Any], work_dir: Path) -> dict[str, Any]:
        bounded = copy.deepcopy(config)
        bounded["checkpoint_dir"] = str(work_dir / "checkpoints")
        bounded["report_dir"] = str(work_dir / "reports")
        # Hosted apps are addressed through the dispatcher; a profile cannot
        # opt a run into filesystem-serving behavior.
        bounded["hosted"] = True
        return bounded

    def _remove_failed_work_dir(self, work_dir: Path) -> None:
        resolved = work_dir.resolve()
        try:
            resolved.relative_to(self.work_root)
        except ValueError as exc:
            raise InvalidRunIdentifier("refusing to remove work outside hosted root") from exc
        shutil.rmtree(resolved, ignore_errors=True)

    async def create_run(
        self,
        tenant_id: Any,
        owner_user_id: Any,
        profile_slug: str,
        display_name: str,
    ) -> RunHandle:
        """Create one paused run from an allowlisted server-owned profile."""
        if self._closing:
            raise HostedRunError("supervisor is shutting down")
        tenant = _tenant_id(tenant_id)
        owner = _owner_user_id(owner_user_id)
        slug, config = self._load_profile(profile_slug)
        name = str(display_name).strip()
        if not (1 <= len(name) <= 240):
            raise ValueError("display_name must be 1 to 240 characters")

        async with self._handles_lock:
            if len(self._handles) + len(self._pending_run_ids) >= self.max_loaded_runs:
                raise RunCapacityExceeded("hosted loaded-run limit reached")
            public_id = _public_run_id(self._run_id_factory())
            if public_id in self._handles or public_id in self._pending_run_ids:
                raise HostedRunError("run id factory returned a duplicate UUID")
            self._pending_run_ids.add(public_id)
            work_dir, data_dir = self._run_directories(tenant, public_id)

        world = None
        record = None
        lease_token = None
        try:
            bounded = self._bounded_config(config, work_dir)
            _, world, world_run_id = await asyncio.to_thread(
                open_run, bounded, None, None, data_dir=data_dir
            )
            world.status = "paused"
            world.store.set_meta(status="paused")
            world.store.commit()
            meta = world.store.get_meta()
            record = await asyncio.to_thread(
                self.catalog.create_run,
                tenant,
                owner_user_id=owner,
                run_key=world_run_id,
                display_name=name,
                schema_version=int(meta["schema_version"]),
                engine_semantics_version=semantics_version(bounded, default=2),
                catalog={"profile_slug": slug},
                run_id=UUID(public_id),
            )
            lease_token = await asyncio.to_thread(
                self.catalog.acquire_writer_lease,
                tenant,
                public_id,
                owner=self.instance_id,
                ttl_seconds=self.lease_ttl_seconds,
            )
            if lease_token is None:
                raise WriterLeaseUnavailable(f"writer lease unavailable for run {public_id}")
            updated = await asyncio.to_thread(
                self.catalog.update_run_status,
                tenant,
                public_id,
                "paused",
                lease_token=lease_token,
            )
            if updated is None:
                raise WriterLeaseLost(f"writer lease lost while creating run {public_id}")
            record = updated
            handle = self._build_handle(
                tenant=tenant,
                public_id=public_id,
                owner=owner,
                slug=slug,
                work_dir=work_dir,
                data_dir=data_dir,
                world_run_id=world_run_id,
                world=world,
                lease_token=lease_token,
                record=record,
            )
            async with self._handles_lock:
                if len(self._handles) >= self.max_loaded_runs:
                    raise RunCapacityExceeded("hosted loaded-run limit reached")
                self._handles[public_id] = handle
            self.bind_event_loop(handle)
            self._start_lease_heartbeat(handle)
            await self.snapshot_boundary(handle, "pause")
            return handle
        except BaseException:
            if lease_token is not None:
                try:
                    await asyncio.to_thread(
                        self.catalog.release_writer_lease,
                        tenant,
                        public_id,
                        token=lease_token,
                    )
                except Exception:
                    pass
            if record is not None:
                try:
                    await asyncio.to_thread(
                        self.catalog.update_run_status,
                        tenant,
                        public_id,
                        "failed",
                        lease_token=None,
                    )
                except Exception:
                    pass
            if world is not None:
                world.close()
            async with self._handles_lock:
                self._handles.pop(public_id, None)
            self._remove_failed_work_dir(work_dir)
            raise
        finally:
            async with self._handles_lock:
                self._pending_run_ids.discard(public_id)

    def _build_handle(
        self,
        *,
        tenant: str,
        public_id: str,
        owner: str,
        slug: str,
        work_dir: Path,
        data_dir: Path,
        world_run_id: str,
        world: Any,
        lease_token: Any,
        record: Any,
    ) -> RunHandle:
        app = create_app(world, hosted_safe=True)
        controller = app.state.run_controller
        handle = RunHandle(
            tenant_id=tenant,
            public_run_id=public_id,
            owner_user_id=owner,
            profile_slug=slug,
            work_dir=work_dir,
            data_dir=data_dir,
            world_run_id=world_run_id,
            world=world,
            app=app,
            controller=controller,
            lease_token=lease_token,
            catalog_record=record,
            snapshot_sequence=self._snapshot_sequence(record),
        )
        controller_tick = world.on_tick

        def hosted_tick_boundary(tick: int, summary: dict[str, Any]) -> None:
            if controller_tick is not None:
                controller_tick(tick, summary)
            reason = "pause" if summary.get("paused") or summary.get("interrupted") else "tick"
            if reason != "tick" or int(tick) % self.snapshot_interval_ticks == 0:
                self._schedule_snapshot_threadsafe(handle, reason)

        world.on_tick = hosted_tick_boundary
        return handle

    async def get_handle(
        self, tenant_id: Any, run_id: Any, *, load: bool = True
    ) -> RunHandle | None:
        """Resolve within a tenant; foreign ids intentionally look missing."""
        tenant = _tenant_id(tenant_id)
        public_id = _public_run_id(run_id)
        handle = self._handles.get(public_id)
        if handle is not None:
            if handle.tenant_id != tenant or handle.closed:
                return None
            if handle.lease_lost:
                raise WriterLeaseLost(f"writer lease was lost for run {public_id}")
            return handle
        record = await asyncio.to_thread(self.catalog.get_run, tenant, public_id)
        if record is None or not load:
            return None
        return await self._open_record(record)

    async def _open_record(self, record: Any) -> RunHandle:
        tenant = _tenant_id(_record_value(record, "tenant_id"))
        public_id = _public_run_id(_record_value(record, "id"))
        owner = _owner_user_id(_record_value(record, "owner_user_id"))
        catalog_data = _record_value(record, "catalog", {}) or {}
        if not isinstance(catalog_data, Mapping):
            raise HostedRunError("run catalog metadata must be a mapping")
        slug = _profile_slug(catalog_data.get("profile_slug", ""))
        if slug not in self.profiles:
            raise InvalidProfile(f"stored profile is no longer allowlisted: {slug}")
        world_run_id = _run_key(_record_value(record, "run_key"))

        async with self._handles_lock:
            existing = self._handles.get(public_id)
            if existing is not None:
                return existing
            if public_id in self._pending_run_ids:
                raise WriterLeaseUnavailable(f"run {public_id} is already opening")
            if len(self._handles) + len(self._pending_run_ids) >= self.max_loaded_runs:
                raise RunCapacityExceeded("hosted loaded-run limit reached")
            self._pending_run_ids.add(public_id)
            work_dir, data_dir = self._run_directories(tenant, public_id)

        try:
            lease_token = await asyncio.to_thread(
                self.catalog.acquire_writer_lease,
                tenant,
                public_id,
                owner=self.instance_id,
                ttl_seconds=self.lease_ttl_seconds,
            )
        except BaseException:
            async with self._handles_lock:
                self._pending_run_ids.discard(public_id)
            raise
        if lease_token is None:
            async with self._handles_lock:
                self._pending_run_ids.discard(public_id)
            raise WriterLeaseUnavailable(f"writer lease unavailable for run {public_id}")

        world = None
        try:
            database = data_dir / f"{world_run_id}.db"
            if not database.is_file():
                await asyncio.to_thread(
                    self._restore_record_snapshot, record, tenant, public_id, world_run_id, data_dir
                )
            _, world, opened_run_id = await asyncio.to_thread(
                open_run, {}, world_run_id, None, data_dir=data_dir
            )
            if opened_run_id != world_run_id:
                raise HostedRunError("resumed simulator run key changed unexpectedly")
            world.status = "paused"
            world._pause_requested = False
            world._stop_requested = False
            world.store.set_meta(status="paused")
            world.store.commit()
            updated = await asyncio.to_thread(
                self.catalog.update_run_status,
                tenant,
                public_id,
                "paused",
                lease_token=lease_token,
            )
            if updated is None:
                raise WriterLeaseLost(f"writer lease lost while opening run {public_id}")
            handle = self._build_handle(
                tenant=tenant,
                public_id=public_id,
                owner=owner,
                slug=slug,
                work_dir=work_dir,
                data_dir=data_dir,
                world_run_id=world_run_id,
                world=world,
                lease_token=lease_token,
                record=updated,
            )
            async with self._handles_lock:
                existing = self._handles.get(public_id)
                if existing is not None:
                    world.close()
                    await asyncio.to_thread(
                        self.catalog.release_writer_lease,
                        tenant,
                        public_id,
                        token=lease_token,
                    )
                    self._pending_run_ids.discard(public_id)
                    return existing
                self._handles[public_id] = handle
                self._pending_run_ids.discard(public_id)
            self.bind_event_loop(handle)
            self._start_lease_heartbeat(handle)
            return handle
        except BaseException:
            if world is not None:
                world.close()
            try:
                await asyncio.to_thread(
                    self.catalog.release_writer_lease,
                    tenant,
                    public_id,
                    token=lease_token,
                )
            except Exception:
                pass
            async with self._handles_lock:
                self._pending_run_ids.discard(public_id)
            raise

    def _restore_record_snapshot(
        self,
        record: Any,
        tenant: str,
        public_id: str,
        world_run_id: str,
        data_dir: Path,
    ) -> None:
        key = _record_value(record, "snapshot_object_key")
        digest = _record_value(record, "snapshot_sha256")
        if not key or not digest:
            raise HostedRunError("run has no local database or durable snapshot")
        valid_key = validate_snapshot_artifact_key(str(key))
        expected_prefix = f"tenants/{tenant}/runs/{public_id}/snapshots/"
        if not valid_key.startswith(expected_prefix):
            raise HostedRunError("catalog snapshot pointer is outside this tenant/run scope")
        snapshot_id = Path(valid_key).stem
        restore_sqlite_snapshot(
            self.artifact_store,
            tenant_id=tenant,
            run_id=public_id,
            snapshot_id=snapshot_id,
            destination=data_dir / f"{world_run_id}.db",
            expected_sha256=str(digest),
            expected_schema_version=int(_record_value(record, "schema_version", SCHEMA_VERSION)),
        )

    async def recover_active_runs(self) -> tuple[RunHandle, ...]:
        """Convert pre-crash starting/running rows to paused and reload safely."""
        recovered: list[RunHandle] = []
        records = await asyncio.to_thread(self.catalog.list_active_runs)
        for record in records:
            if str(_record_value(record, "status")) not in {"starting", "running"}:
                continue
            try:
                # Acquire the writer lease before mutating durable status.
                # A healthy peer's running row must not be marked paused by a
                # second instance that cannot own it.
                recovered.append(await self._open_record(record))
            except WriterLeaseUnavailable:
                # A still-live peer owns the non-expired lease; leave both its
                # durable status and world untouched.
                continue
        return tuple(recovered)

    def bind_event_loop(self, handle: RunHandle) -> None:
        loop = asyncio.get_running_loop()
        handle.event_loop = loop
        handle.controller.loop = loop
        lease_task = handle.lease_task
        if lease_task is not None and lease_task.get_loop() is not loop:
            prior_loop = lease_task.get_loop()
            if not lease_task.done() and prior_loop.is_running():
                prior_loop.call_soon_threadsafe(lease_task.cancel)
            handle.lease_task = None
        self._start_lease_heartbeat(handle)

    def _schedule_snapshot_threadsafe(self, handle: RunHandle, reason: str) -> None:
        loop = handle.event_loop or handle.controller.loop
        if loop is None or not loop.is_running() or handle.closed or handle.snapshot_failed:
            return

        def schedule() -> None:
            if handle.closed or handle.snapshot_failed:
                return
            task = loop.create_task(self.snapshot_boundary(handle, reason))
            self._track_snapshot_task(handle, task)

        loop.call_soon_threadsafe(schedule)

    @staticmethod
    def _track_snapshot_task(handle: RunHandle, task: asyncio.Task[Any]) -> None:
        handle.snapshot_tasks.add(task)

        def completed(done: asyncio.Task[Any]) -> None:
            handle.snapshot_tasks.discard(done)
            if done.cancelled():
                return
            error = done.exception()
            if error is not None:
                handle.snapshot_errors.append(error)

        task.add_done_callback(completed)

    async def snapshot_boundary(
        self, handle: RunHandle, reason: str, *, manual: bool = False
    ) -> ArtifactMetadata:
        """Publish one immutable consistent snapshot and advance its pointer."""
        if reason not in {"tick", "pause", "stop"}:
            raise ValueError("snapshot reason must be tick, pause, or stop")
        if handle.closed:
            raise HostedRunError("cannot snapshot a closed run")
        if handle.lease_lost:
            raise WriterLeaseLost(
                f"writer lease was already lost for run {handle.public_run_id}"
            )
        if handle.snapshot_failed and not manual:
            raise HostedRunError("automatic snapshots are disabled after snapshot failure")
        async with handle.snapshot_lock:
            try:
                handle.snapshot_sequence += 1
                tick = int(handle.world.store.tick)
                snapshot_id = f"t{tick:012d}-s{handle.snapshot_sequence:08d}-{reason}"
                metadata = await asyncio.to_thread(
                    publish_sqlite_snapshot,
                    handle.database_path,
                    self.artifact_store,
                    tenant_id=handle.tenant_id,
                    run_id=handle.public_run_id,
                    snapshot_id=snapshot_id,
                    staging_directory=handle.work_dir / "snapshot-staging",
                    expected_schema_version=SCHEMA_VERSION,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                await self._record_snapshot_failure(handle)
                raise
            try:
                updated = await asyncio.to_thread(
                    self.catalog.update_snapshot_pointer,
                    handle.tenant_id,
                    handle.public_run_id,
                    lease_token=handle.lease_token,
                    object_key=metadata.key,
                    sha256=metadata.sha256,
                    size_bytes=metadata.size_bytes,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                await self._record_snapshot_failure(handle)
                raise
            if not updated:
                self._mark_lease_lost(handle)
                raise WriterLeaseLost(
                    f"writer lease lost while publishing run {handle.public_run_id}"
                )
            status = (
                "stopped"
                if reason == "stop" or handle.world.status == "finished"
                else "paused"
                if reason == "pause" or handle.world.status in {"paused", "halted"}
                else "running"
            )
            try:
                record = await asyncio.to_thread(
                    self.catalog.update_run_status,
                    handle.tenant_id,
                    handle.public_run_id,
                    status,
                    lease_token=handle.lease_token,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                await self._record_snapshot_failure(handle)
                raise
            if record is None:
                self._mark_lease_lost(handle)
                raise WriterLeaseLost(
                    f"writer lease lost while recording run {handle.public_run_id} status"
                )
            handle.catalog_record = record
            handle.snapshot_failed = False
            handle.snapshot_errors.clear()
            return metadata

    async def _record_snapshot_failure(self, handle: RunHandle) -> None:
        if handle.snapshot_failed or handle.closed:
            return
        handle.snapshot_failed = True
        handle.world.request_pause()
        current = asyncio.current_task()
        for task in tuple(handle.snapshot_tasks):
            if task is not current and not task.done():
                task.cancel()
        try:
            record = await asyncio.to_thread(
                self.catalog.update_run_status,
                handle.tenant_id,
                handle.public_run_id,
                "snapshot_failed",
                lease_token=handle.lease_token,
            )
        except Exception:
            self._mark_lease_lost(handle)
            return
        if record is None:
            self._mark_lease_lost(handle)
            return
        handle.catalog_record = record

    async def drain_snapshots(self, handle: RunHandle | None = None) -> None:
        handles = (handle,) if handle is not None else self.loaded_runs
        # Tick callbacks can enqueue from another thread with call_soon_threadsafe.
        # Give those callbacks one loop turn before deciding the queue is empty.
        await asyncio.sleep(0)
        while True:
            tasks = tuple(
                task
                for item in handles
                for task in tuple(item.snapshot_tasks)
                if not task.done()
            )
            if not tasks:
                if any(item.snapshot_errors for item in handles):
                    for item in handles:
                        if item.snapshot_errors:
                            raise item.snapshot_errors.pop(0)
                return
            await asyncio.gather(*tasks, return_exceptions=True)

    def observe_control(self, handle: RunHandle, inner_path: str, method: str) -> None:
        """Attach boundary persistence after a delegated control request."""
        if method.upper() != "POST":
            return
        if inner_path not in {"/api/run/start", "/api/run/pause", "/api/run/stop"}:
            return
        task = handle.controller.task
        if task is not None and not task.done():
            if handle.observed_controller_task is task:
                return
            handle.observed_controller_task = task

            async def after_world() -> None:
                try:
                    await asyncio.shield(task)
                finally:
                    current = asyncio.current_task()
                    pending = tuple(
                        snapshot
                        for snapshot in handle.snapshot_tasks
                        if snapshot is not current and not snapshot.done()
                    )
                    if pending:
                        await asyncio.gather(*pending, return_exceptions=True)
                    reason = "stop" if handle.world.status == "finished" else "pause"
                    await self.snapshot_boundary(handle, reason)

            watcher = asyncio.create_task(after_world())
            self._track_snapshot_task(handle, watcher)
            return
        reason = "stop" if inner_path == "/api/run/stop" else "pause"
        if inner_path != "/api/run/start":
            self._schedule_snapshot_threadsafe(handle, reason)

    def _start_lease_heartbeat(self, handle: RunHandle) -> None:
        if handle.lease_task is not None or handle.closed or handle.lease_lost:
            return

        async def heartbeat() -> None:
            interval = max(1.0, self.lease_ttl_seconds / 3)
            try:
                while not handle.closed:
                    await asyncio.sleep(interval)
                    renewed = await asyncio.to_thread(
                        self.catalog.renew_writer_lease,
                        handle.tenant_id,
                        handle.public_run_id,
                        owner=self.instance_id,
                        token=handle.lease_token,
                        ttl_seconds=self.lease_ttl_seconds,
                    )
                    if not renewed:
                        self._mark_lease_lost(handle)
                        return
            except asyncio.CancelledError:
                raise
            except Exception:
                # A failed heartbeat is indistinguishable from lease loss once
                # the TTL can expire.  Stop accepting controls immediately;
                # otherwise another supervisor may acquire the same run while
                # this world continues writing.
                self._mark_lease_lost(handle)

        handle.lease_task = asyncio.create_task(heartbeat())

    @staticmethod
    def _mark_lease_lost(handle: RunHandle) -> None:
        handle.lease_lost = True
        handle.world.request_pause()

    async def close_run(self, handle: RunHandle) -> None:
        if handle.closed:
            return
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.shutdown_grace_seconds

        def remaining() -> float:
            return max(0.001, deadline - loop.time())

        controller_task = handle.controller.task
        if controller_task is not None and not controller_task.done():
            handle.world.request_pause()
            try:
                await asyncio.wait_for(
                    asyncio.shield(controller_task), timeout=remaining()
                )
            except asyncio.TimeoutError:
                controller_task.cancel()
                await asyncio.gather(controller_task, return_exceptions=True)
        try:
            if not handle.lease_lost:
                await asyncio.wait_for(self.drain_snapshots(handle), timeout=remaining())
                terminal = str(_record_value(handle.catalog_record, "status", "")) == "stopped"
                if not handle.closed and not terminal:
                    await asyncio.wait_for(
                        self.snapshot_boundary(
                            handle,
                            "stop" if handle.world.status == "finished" else "pause",
                        ),
                        timeout=remaining(),
                    )
        finally:
            handle.closed = True
            current = asyncio.current_task()
            pending_snapshots = tuple(
                task
                for task in handle.snapshot_tasks
                if task is not current and not task.done()
            )
            for task in pending_snapshots:
                task.cancel()
            if pending_snapshots:
                await asyncio.gather(*pending_snapshots, return_exceptions=True)
            if handle.lease_task is not None:
                lease_task = handle.lease_task
                task_loop = lease_task.get_loop()
                if task_loop is asyncio.get_running_loop():
                    lease_task.cancel()
                    await asyncio.gather(lease_task, return_exceptions=True)
                elif not lease_task.done() and task_loop.is_running():
                    task_loop.call_soon_threadsafe(lease_task.cancel)
                handle.lease_task = None
            await asyncio.to_thread(
                self.catalog.release_writer_lease,
                handle.tenant_id,
                handle.public_run_id,
                token=handle.lease_token,
            )
            handle.world.close()
            async with self._handles_lock:
                self._handles.pop(handle.public_run_id, None)

    async def shutdown(self) -> None:
        if self._closing:
            return
        self._closing = True
        await asyncio.gather(
            *(self.close_run(handle) for handle in self.loaded_runs),
            return_exceptions=False,
        )


# Short alias for hosted factories and operators.
HostedSupervisor = HostedRunSupervisor
