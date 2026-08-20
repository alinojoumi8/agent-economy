"""Versioned, bounded cache for derived observer snapshots.

The cache is deliberately outside canonical simulation state.  Identity binds
each value to its run/fork, projection contract, observer policy, event cursor,
and the writer connection's mutation count.  Any committed or rolled-back
write therefore makes an older entry unreachable without requiring mutation
hooks throughout the economic engine.
"""
from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass
from threading import RLock
from time import perf_counter
from typing import Callable

from communications.policy import Principal

from .envelope import (
    POLICY_VERSION,
    PROJECTION_VERSION,
    current_cursor,
    lineage,
    semantics_version,
    view_key,
)
from .snapshot import build_snapshot


SnapshotBuilder = Callable[..., dict]
DEFAULT_DOMAINS = ("alerts", "communications", "events", "summary")


@dataclass(frozen=True)
class SnapshotIdentity:
    run_id: str
    fork_id: str | None
    tick: int
    semantics_version: int
    projection_version: int
    policy_version: int
    view_key: str
    event_cursor: int
    domains: tuple[str, ...]
    store_revision: int


class ProjectionSnapshotCache:
    """Keep a small LRU of immutable, derived projection snapshots."""

    def __init__(
        self,
        *,
        max_entries: int = 64,
        builder: SnapshotBuilder = build_snapshot,
    ) -> None:
        self.max_entries = max(1, int(max_entries))
        self._builder = builder
        self._entries: OrderedDict[SnapshotIdentity, dict] = OrderedDict()
        self._lock = RLock()
        self._hits = 0
        self._misses = 0
        self._builds = 0
        self._discarded_builds = 0
        self._build_ms_total = 0.0
        self._last_build_ms = 0.0

    @staticmethod
    def _domains(domains: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(domains or DEFAULT_DOMAINS)))

    def _identity(
        self,
        store,
        principal: Principal,
        *,
        as_of_tick: int,
        domains: tuple[str, ...],
        event_cursor: int | None,
    ) -> SnapshotIdentity:
        run_lineage = lineage(store)
        cursor = (
            current_cursor(store, as_of_tick)
            if event_cursor is None
            else int(event_cursor)
        )
        return SnapshotIdentity(
            run_id=str(run_lineage["run_id"]),
            fork_id=(
                str(run_lineage["fork_id"])
                if run_lineage["fork_id"] is not None
                else None
            ),
            tick=int(as_of_tick),
            semantics_version=int(semantics_version(store)),
            projection_version=PROJECTION_VERSION,
            policy_version=POLICY_VERSION,
            view_key=view_key(principal),
            event_cursor=cursor,
            domains=self._domains(domains),
            store_revision=int(store.conn.total_changes),
        )

    def snapshot(
        self,
        store,
        principal: Principal,
        *,
        as_of_tick: int,
        domains: tuple[str, ...],
        event_cursor: int | None = None,
    ) -> dict:
        """Return a defensive copy, building only when identity is absent."""
        identity = self._identity(
            store,
            principal,
            as_of_tick=as_of_tick,
            domains=domains,
            event_cursor=event_cursor,
        )
        with self._lock:
            cached = self._entries.get(identity)
            if cached is not None:
                self._entries.move_to_end(identity)
                self._hits += 1
                return deepcopy(cached)
            self._misses += 1

        started = perf_counter()
        data = self._builder(
            store,
            principal,
            as_of_tick=int(as_of_tick),
            domains=identity.domains,
        )
        elapsed_ms = (perf_counter() - started) * 1000.0

        # A writer may advance while an HTTP miss is being assembled.  The
        # caller still receives the same best-effort cut it would have received
        # without a cache, but a mixed cut is never published for later reuse.
        stable = self._identity(
            store,
            principal,
            as_of_tick=as_of_tick,
            domains=identity.domains,
            event_cursor=identity.event_cursor,
        ) == identity
        with self._lock:
            self._builds += 1
            self._last_build_ms = elapsed_ms
            self._build_ms_total += elapsed_ms
            if stable:
                self._entries[identity] = deepcopy(data)
                self._entries.move_to_end(identity)
                while len(self._entries) > self.max_entries:
                    self._entries.popitem(last=False)
            else:
                self._discarded_builds += 1
        return data

    def clear(self) -> None:
        """Release cached projection bodies; safe to call repeatedly."""
        with self._lock:
            self._entries.clear()

    def stats(self) -> dict[str, int | float]:
        """Return content-free operational telemetry."""
        with self._lock:
            lookups = self._hits + self._misses
            return {
                "entries": len(self._entries),
                "max_entries": self.max_entries,
                "hits": self._hits,
                "misses": self._misses,
                "builds": self._builds,
                "discarded_builds": self._discarded_builds,
                "hit_ratio": round(self._hits / lookups, 4) if lookups else 0.0,
                "last_build_ms": round(self._last_build_ms, 3),
                "build_ms_total": round(self._build_ms_total, 3),
            }
