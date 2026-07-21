"""Canonical projection lineage and deterministic envelopes."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from communications.policy import Principal
from engine.store import load_json


PROJECTION_VERSION = 1
POLICY_VERSION = 1


class ProjectionRequestError(ValueError):
    """Raised when a requested historical or fork lineage cannot be served."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def resolve_tick(store, requested: str | int | None) -> int:
    current = int(store.tick)
    if requested is None or requested == "live":
        return current
    try:
        tick = int(requested)
    except (TypeError, ValueError) as exc:
        raise ProjectionRequestError("tick must be live or a non-negative integer") from exc
    if tick < 0 or tick > current:
        raise ProjectionRequestError("requested tick is outside the available run history")
    return tick


def current_cursor(store, as_of_tick: int | None = None) -> int:
    if as_of_tick is None:
        as_of_tick = int(store.tick)
    return int(store.scalar(
        "SELECT COALESCE(MAX(cursor),0) FROM projection_commits WHERE tick<=?",
        (int(as_of_tick),), default=0) or 0)


def lineage(store) -> dict[str, Any]:
    meta = store.get_meta()
    return {
        "run_id": str(meta["run_id"]),
        "fork_id": str(meta["run_id"]) if meta["parent_run_id"] else None,
        "parent_run_id": str(meta["parent_run_id"]) if meta["parent_run_id"] else None,
        "fork_tick": int(meta["fork_tick"]) if meta["fork_tick"] is not None else None,
    }


def validate_fork(store, requested_fork_id: str | None) -> None:
    actual = lineage(store)["fork_id"]
    normalized = requested_fork_id or None
    if normalized != actual and requested_fork_id is not None:
        raise ProjectionRequestError("requested fork does not match the selected run lineage")


def semantics_version(store) -> int:
    meta = store.get_meta()
    config = load_json(meta["config_json"], {}) or {}
    return int(config.get("engine_semantics_version", 1))


def view_key(principal: Principal) -> str:
    material = {
        "principal_id": principal.principal_id,
        "agent_id": principal.agent_id,
        "operator_truth": principal.operator_truth,
        "disclosure_case_id": principal.disclosure_case_id,
        "policy_version": POLICY_VERSION,
    }
    return hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()[:24]


def build_envelope(
    store,
    principal: Principal,
    projection: str,
    data: Any,
    *,
    as_of_tick: int,
    event_cursor: int | None = None,
) -> dict[str, Any]:
    run_lineage = lineage(store)
    semantics = semantics_version(store)
    cursor = current_cursor(store, as_of_tick) if event_cursor is None else int(event_cursor)
    opaque_view = view_key(principal)
    identity = {
        "run_id": run_lineage["run_id"],
        "fork_id": run_lineage["fork_id"],
        "tick": int(as_of_tick),
        "semantics_version": semantics,
        "projection_version": PROJECTION_VERSION,
        "policy_version": POLICY_VERSION,
        "view_key": opaque_view,
        "event_cursor": cursor,
        "projection": projection,
        "data_hash": hashlib.sha256(canonical_json(data).encode("utf-8")).hexdigest(),
    }
    identity_hash = hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()[:16]
    return {
        "run_id": run_lineage["run_id"],
        "fork_id": run_lineage["fork_id"],
        "tick": int(as_of_tick),
        "semantics_version": semantics,
        "projection_version": PROJECTION_VERSION,
        "policy_version": POLICY_VERSION,
        "view_key": opaque_view,
        "snapshot_version": (
            f"s{semantics}-p{PROJECTION_VERSION}-t{int(as_of_tick)}-e{cursor}-{identity_hash}"
        ),
        "event_cursor": cursor,
        "projection": projection,
        "data": data,
    }
