"""Cursor-safe ordinary-observer WebSocket messages."""
from __future__ import annotations

from communications.policy import Principal

from .envelope import (
    POLICY_VERSION,
    PROJECTION_VERSION,
    build_envelope,
    current_cursor,
    lineage,
    semantics_version,
    view_key,
)
from .events import build_backfill
from .snapshot import build_snapshot


ORDINARY_PRINCIPAL = Principal("ordinary-dashboard")


def hello_message(store, *, status: str) -> dict:
    run_lineage = lineage(store)
    cursor = current_cursor(store)
    return {
        "type": "hello",
        "run_id": run_lineage["run_id"],
        "fork_id": run_lineage["fork_id"],
        "tick": int(store.tick),
        "semantics_version": semantics_version(store),
        "projection_version": PROJECTION_VERSION,
        "policy_version": POLICY_VERSION,
        "view_key": view_key(ORDINARY_PRINCIPAL),
        "event_cursor": cursor,
        "status": str(status),
    }


def projection_delta_message(store, *, tick: int) -> dict:
    cursor = current_cursor(store, tick)
    previous = int(store.scalar(
        "SELECT COALESCE(MAX(cursor),0) FROM projection_commits WHERE cursor<?",
        (cursor,), default=0) or 0)
    data = build_snapshot(
        store, ORDINARY_PRINCIPAL, as_of_tick=int(tick),
        domains=("summary", "alerts", "communications", "events"))
    envelope = build_envelope(
        store, ORDINARY_PRINCIPAL, "world.snapshot", data,
        as_of_tick=int(tick), event_cursor=cursor)
    return {
        "type": "projection_delta",
        "domain": "observatory",
        **{key: envelope[key] for key in (
            "run_id", "fork_id", "tick", "semantics_version", "projection_version",
            "policy_version", "view_key", "snapshot_version", "event_cursor")},
        "previous_event_cursor": previous,
        "payload": data,
    }


def recovery_messages(store, *, after_cursor: int, limit: int = 250) -> list[dict]:
    current = current_cursor(store)
    if int(after_cursor) > current:
        return [{
            "type": "error", "code": "cursor_ahead",
            "event_cursor": current,
        }]
    if int(after_cursor) == current:
        return [{
            "type": "heartbeat", "tick": int(store.tick), "event_cursor": current,
        }]
    data = build_backfill(store, after_cursor=int(after_cursor), limit=limit)
    if data["truncated"]:
        return [{
            "type": "projection_invalidated", "reason": "backfill_truncated",
            "event_cursor": current,
        }]
    run_lineage = lineage(store)
    semantics = semantics_version(store)
    opaque_view = view_key(ORDINARY_PRINCIPAL)
    return [
        {
            "type": "projection_delta",
            "domain": "cursor_advance",
            "run_id": run_lineage["run_id"],
            "fork_id": run_lineage["fork_id"],
            "tick": commit["tick"],
            "semantics_version": semantics,
            "projection_version": PROJECTION_VERSION,
            "policy_version": POLICY_VERSION,
            "view_key": opaque_view,
            "snapshot_version": None,
            "previous_event_cursor": commit["previous_event_cursor"],
            "event_cursor": commit["event_cursor"],
            "payload": [],
        }
        for commit in data["commits"]
    ]
