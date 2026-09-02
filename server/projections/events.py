"""Knowledge-safe event and cursor-backfill projections."""
from __future__ import annotations

from engine.store import load_json

from .activity import project_event_activity


def _safe_event(row) -> dict:
    return {
        "id": int(row["id"]),
        "tick": int(row["tick"]),
        "phase": str(row["phase"] or ""),
        "kind": str(row["kind"]),
        "subject_type": row["subject_type"],
        "subject_id": int(row["subject_id"]) if row["subject_id"] is not None else None,
        "importance": float(row["importance"]),
        "payload": load_json(row["payload_json"], {}) or {},
        "activity": project_event_activity(row, historical=True),
    }


def build_events(
    store,
    *,
    as_of_tick: int,
    after_id: int = 0,
    limit: int = 100,
    kinds: tuple[str, ...] = (),
) -> dict:
    limit = max(1, min(500, int(limit)))
    params: list[object] = [int(after_id), int(as_of_tick)]
    where = "id>? AND tick<=?"
    if kinds:
        marks = ",".join("?" for _ in kinds)
        where += f" AND kind IN ({marks})"
        params.extend(kinds)
    params.append(limit + 1)
    rows = store.query(
        f"SELECT * FROM events WHERE {where} ORDER BY id LIMIT ?", tuple(params))
    truncated = len(rows) > limit
    items = [_safe_event(row) for row in rows[:limit]]
    return {
        "items": items,
        "next_after_id": items[-1]["id"] if truncated and items else None,
        "truncated": truncated,
    }


def build_recent_events(
    store,
    *,
    as_of_tick: int,
    min_importance: float = 0.0,
    limit: int = 20,
) -> dict:
    """Return the newest committed events at or before ``as_of_tick``.

    Items are returned in ascending id order so callers can render them as a
    timeline; the window itself always ends at the latest matching event.
    """
    limit = max(1, min(500, int(limit)))
    rows = store.query(
        "SELECT * FROM events WHERE tick<=? AND importance>=? ORDER BY id DESC LIMIT ?",
        (int(as_of_tick), float(min_importance), limit),
    )
    return {"items": [_safe_event(row) for row in reversed(list(rows))]}


def build_backfill(store, *, after_cursor: int, limit: int = 100) -> dict:
    limit = max(1, min(500, int(limit)))
    # ``current_cursor`` only counts commits of completed ticks, so a backfill
    # must not hand out commits from the tick that is still in progress.
    rows = store.query(
        "SELECT cursor,tick,phase,domains_json FROM projection_commits "
        "WHERE cursor>? AND tick<=? ORDER BY cursor LIMIT ?",
        (int(after_cursor), int(store.tick), limit + 1),
    )
    truncated = len(rows) > limit
    commits = []
    previous = int(after_cursor)
    for row in rows[:limit]:
        cursor = int(row["cursor"])
        commits.append({
            "previous_event_cursor": previous,
            "event_cursor": cursor,
            "tick": int(row["tick"]),
            "phase": str(row["phase"]),
            "domains": load_json(row["domains_json"], []) or [],
        })
        previous = cursor
    return {
        "commits": commits,
        "next_cursor": commits[-1]["event_cursor"] if truncated and commits else None,
        "truncated": truncated,
    }
