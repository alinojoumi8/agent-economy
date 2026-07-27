"""Persisted-evidence acceptance receipt for supply-recovery runs.

This evaluator deliberately accepts a :class:`~engine.store.Store` rather than a
live ``World``.  Every gate is reconstructed from stored rows and checkpoint
artifacts so it can be regenerated after the run has stopped.
"""
from __future__ import annotations

import json
import math
import re
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from engine.checkpoint_manifest import (
    CHECKPOINT_MANIFEST_VERSION,
    build_checkpoint_manifest,
    canonical_json_bytes,
    checkpoint_manifest_path,
    file_sha256,
)
from engine.ledger import Ledger
from engine.schema import SchemaCompatibilityError, assert_schema_compatible
from engine.store import Store, load_json
from reports.acceptance import resolve_run_db
from world.recovery import recovery_settings


_PROFILE_SETTINGS = {
    "enabled": True,
    "policy_version": "supply-recovery-v1",
    "activation_tick": 0,
    "wage_floor_cents": 15_000,
    "gross_margin_coverage_bps": 12_500,
    "cash_payroll_coverage_periods": 2,
    "max_hires_per_firm_per_period": 1,
    "demand_buffer_ticks": 5,
    "sales_observation_ticks": 30,
}
_THRESHOLDS = {
    "minimum_ticks": 1_000,
    "warmup_ticks": 60,
    "trailing_window_ticks": 60,
    "max_buy_goods_rejection_rate": 0.05,
    "max_unemployment_rebound": 0.10,
    # A finite bound accommodates a small end-tick queue while detecting an
    # unbounded labor backlog.  The profile has 12 initial goods firms.
    "max_pending_applications": 20,
    "max_pending_job_offers": 20,
    "max_open_jobs": 20,
}
_CHECK_NAMES = (
    "recovery_profile_persisted",
    "horizon_completed",
    "buy_goods_rejection_rate_within_5pct",
    "unemployment_rebound_within_10pp",
    "recovery_managed_insolvency_absent",
    "labor_backlog_bounded",
    "ledger_reconciled",
    "sqlite_integrity",
    "checkpoint_retention",
    "unit_economics_validated",
)
_COMPLETED_STATUSES = frozenset({"paused", "finished"})
_CHECKPOINT_MANIFEST_KIND = "world_checkpoint_v1"
_REQUIRED_RUN_META_FIELDS = frozenset({
    "run_id", "seed", "schema_version", "status", "tick", "active_tick", "config_json",
})
_ACTIVE_RECOVERY_FIRM_STATUSES = frozenset({"private", "listed"})
_TERMINAL_RECOVERY_FIRM_STATUSES = frozenset({"bankrupt", "acquired"})
_KNOWN_RECOVERY_FIRM_STATUSES = (
    _ACTIVE_RECOVERY_FIRM_STATUSES | _TERMINAL_RECOVERY_FIRM_STATUSES
)


def resolve_supply_recovery_db(run_or_path: str | Path) -> Path:
    """Resolve a direct database path or a run id exactly like acceptance does."""
    return resolve_run_db(run_or_path)


def evaluate_supply_recovery(store: Store) -> dict[str, Any]:
    """Evaluate the fixed supply-recovery contract from persisted evidence only.

    Missing rows, malformed payloads, or incomplete trailing windows fail their
    individual gates.  The returned object uses only JSON-compatible values and
    has no wall-clock fields, making repeated evaluation deterministic.
    """
    try:
        assert_schema_compatible(store.conn)
    except SchemaCompatibilityError:
        return _empty_receipt("run database schema is incompatible")
    except Exception as exc:  # pragma: no cover - defensive corrupted-store path
        return _empty_receipt(f"run metadata could not be read: {type(exc).__name__}")
    try:
        meta = store.get_meta()
    except Exception as exc:  # pragma: no cover - defensive corrupted-store path
        return _empty_receipt(f"run metadata could not be read: {type(exc).__name__}")
    if meta is None:
        return _empty_receipt("run metadata is missing")

    try:
        missing_meta_fields = sorted(_REQUIRED_RUN_META_FIELDS - set(meta.keys()))
    except Exception as exc:  # pragma: no cover - defensive corrupted-store path
        return _empty_receipt(f"run metadata could not be inspected: {type(exc).__name__}")
    if missing_meta_fields:
        return _empty_receipt(
            "run metadata is missing required fields: " + ", ".join(missing_meta_fields)
        )
    if _integer(meta["schema_version"]) is None:
        return _empty_receipt("run metadata has an invalid schema_version")

    config = load_json(meta["config_json"], {})
    if not isinstance(config, Mapping):
        config = {}
    completed_tick_raw = meta["tick"]
    tick = _strict_tick(completed_tick_raw)
    # A persisted active phase is not a completed horizon.  Do not coerce this
    # value: only SQL NULL means the controller had no in-flight tick.
    active_tick = meta["active_tick"]
    status = str(meta["status"] or "")
    run = {
        "run_id": str(meta["run_id"] or ""),
        "seed": _integer(meta["seed"]),
        "status": status,
        "tick": tick,
    }

    profile_ok, profile_evidence = _profile_is_persisted(config)
    horizon_ok, horizon_evidence = _horizon_evidence(
        tick, status, active_tick, completed_tick_raw=completed_tick_raw
    )
    purchases_ok, purchases_evidence = _buy_goods_evidence(store, tick)
    unemployment_ok, unemployment_evidence = _unemployment_evidence(store, tick)
    unit_ok, unit_economics, recovery_goods_firms, unit_evidence = _unit_economics_evidence(
        store,
        activation_tick=_PROFILE_SETTINGS["activation_tick"],
        completed_tick=tick,
    )
    insolvency_ok, insolvency_evidence = _insolvency_evidence(
        store,
        recovery_goods_firms,
        activation_tick=_PROFILE_SETTINGS["activation_tick"],
        completed_tick=tick,
    )
    backlog_ok, backlog_evidence = _labor_backlog_evidence(store)
    ledger_ok, ledger_evidence = _ledger_evidence(store)
    sqlite_ok, sqlite_evidence = _sqlite_evidence(store)
    checkpoints_ok, checkpoints_evidence = _checkpoint_evidence(
        store, run["run_id"], config
    )

    checks = {
        "recovery_profile_persisted": profile_ok,
        "horizon_completed": horizon_ok,
        "buy_goods_rejection_rate_within_5pct": purchases_ok,
        "unemployment_rebound_within_10pp": unemployment_ok,
        "recovery_managed_insolvency_absent": insolvency_ok,
        "labor_backlog_bounded": backlog_ok,
        "ledger_reconciled": ledger_ok,
        "sqlite_integrity": sqlite_ok,
        "checkpoint_retention": checkpoints_ok,
        "unit_economics_validated": unit_ok,
    }
    evidence = {
        "recovery_profile": profile_evidence,
        "horizon": horizon_evidence,
        "buy_goods_rejection": purchases_evidence,
        "unemployment": unemployment_evidence,
        "recovery_managed_insolvencies": insolvency_evidence,
        "labor_backlog": backlog_evidence,
        "ledger": ledger_evidence,
        "sqlite_integrity": sqlite_evidence,
        "checkpoints": checkpoints_evidence,
        "unit_economics": unit_evidence,
    }
    return {
        "schema_version": 1,
        "passed": all(checks.values()),
        "run": run,
        "thresholds": dict(_THRESHOLDS),
        "checks": checks,
        "evidence": evidence,
        "unit_economics": unit_economics,
    }


def evaluate_supply_recovery_db(db_path: str | Path) -> dict[str, Any]:
    """Open a recorded store read-only and return its supply-recovery receipt."""
    database = Path(db_path).resolve()
    if not database.exists():
        raise FileNotFoundError("run database not found")
    # A finalized receipt must neither mutate its source nor silently ignore a
    # live WAL.  Immutable SQLite reads avoid creating -wal/-shm sidecars; an
    # existing sidecar therefore fails closed instead of yielding stale data.
    if any(Path(f"{database}{suffix}").exists() for suffix in ("-wal", "-shm")):
        return _empty_receipt("run database has non-finalized SQLite sidecars")
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(
            f"{database.as_uri()}?mode=ro&immutable=1",
            uri=True,
            isolation_level=None,
            cached_statements=0,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        assert_schema_compatible(connection)
    except SchemaCompatibilityError:
        if connection is not None:
            connection.close()
        return _empty_receipt("run database schema is incompatible")
    except (OSError, sqlite3.Error, ValueError):
        if connection is not None:
            connection.close()
        return _empty_receipt("run database could not be opened read-only")
    store = Store.__new__(Store)
    store.path = str(database)
    store.read_only = True
    store._closed = False
    store.conn = connection
    try:
        return evaluate_supply_recovery(store)
    finally:
        store.close()


def write_supply_recovery_receipt(
        db_path: str | Path, *, output: str | Path | None = None) -> dict[str, Any]:
    """Evaluate a recorded run and optionally write exactly JSON plus Markdown.

    ``output`` is an explicit filename stem (or either final extension).  No
    filesystem output is created when it is omitted.
    """
    receipt = evaluate_supply_recovery_db(db_path)
    if output is None:
        return receipt
    json_path, markdown_path = _receipt_paths(Path(output))
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    markdown_path.write_text(render_supply_recovery_markdown(receipt), encoding="utf-8")
    return {
        **receipt,
        "artifacts": {"json": json_path.name, "markdown": markdown_path.name},
    }


def render_supply_recovery_markdown(receipt: Mapping[str, Any]) -> str:
    """Render the deterministic human-readable companion to the JSON receipt."""
    run = receipt.get("run", {})
    outcome = "PASS" if receipt.get("passed") else "FAIL"
    lines = [
        f"# Supply-recovery acceptance — {run.get('run_id', '')}",
        "",
        f"Overall: **{outcome}**",
        "",
        "## Run",
        "",
        f"- Status: `{run.get('status')}`",
        f"- Completed tick: `{run.get('tick')}`",
        f"- Seed: `{run.get('seed')}`",
        "",
        "## Gates",
        "",
    ]
    for name, passed in receipt.get("checks", {}).items():
        marker = "x" if passed else " "
        lines.append(f"- [{marker}] `{name}`")

    lines += ["", "## Thresholds", ""]
    for name, value in receipt.get("thresholds", {}).items():
        lines.append(f"- `{name}`: `{value}`")

    lines += ["", "## Evidence", ""]
    for name, value in receipt.get("evidence", {}).items():
        lines.append(f"### {name.replace('_', ' ').title()}")
        lines.append("")
        lines.append(f"`{json.dumps(value, sort_keys=True)}`")
        lines.append("")

    lines += ["## Per-firm unit economics", ""]
    for firm in receipt.get("unit_economics", []):
        lines.append(
            f"- Firm `{firm.get('firm_id')}` ({firm.get('name', '')}): "
            f"**{'valid' if firm.get('validated') else 'invalid'}**"
        )
        for employment in firm.get("employment", []):
            lines.append(
                "  - Employment "
                f"`{employment.get('employment_id')}`: wage "
                f"`{employment.get('wage_cents')}`, ceiling "
                f"`{employment.get('safe_wage_ceiling_cents')}`"
            )
    return "\n".join(lines) + "\n"


def _profile_is_persisted(config: Mapping[str, Any]) -> tuple[bool, dict[str, Any]]:
    recovery = config.get("supply_recovery")
    acceptance = config.get("acceptance")
    llm = config.get("llm")
    recovery_mapping = recovery if isinstance(recovery, Mapping) else {}
    acceptance_mapping = acceptance if isinstance(acceptance, Mapping) else {}
    supply_acceptance = acceptance_mapping.get("supply_recovery")
    supply_mapping = supply_acceptance if isinstance(supply_acceptance, Mapping) else {}
    route = llm.get("default_route") if isinstance(llm, Mapping) else None
    routes = llm.get("routes") if isinstance(llm, Mapping) else None

    recovery_valid = False
    try:
        normalized = recovery_settings(config)
        recovery_valid = _exact_settings_match(normalized, _PROFILE_SETTINGS)
    except (TypeError, ValueError):
        normalized = None
    raw_recovery_matches = _exact_settings_match(recovery_mapping, _PROFILE_SETTINGS)
    raw_acceptance_matches = (
        _exact_value(
            acceptance_mapping.get("min_ticks"), _THRESHOLDS["minimum_ticks"]
        )
        and _exact_settings_match(
            supply_mapping,
            {name: value for name, value in _THRESHOLDS.items() if name != "minimum_ticks"},
        )
    )
    checkpoint_settings_match = (
        _exact_value(config.get("checkpoint_every"), 100)
        and _exact_value(config.get("checkpoint_keep_last"), 2)
    )
    scripted = (
        type(route) is dict
        and route == {"provider": "scripted", "model": "scripted"}
        and type(routes) is dict
        and routes == {}
    )
    passed = bool(
        recovery_valid
        and raw_recovery_matches
        and raw_acceptance_matches
        and checkpoint_settings_match
        and scripted
    )
    return passed, {
        "required_recovery_settings": dict(_PROFILE_SETTINGS),
        "observed_recovery_settings": dict(recovery_mapping),
        "observed_acceptance": {
            "min_ticks": acceptance_mapping.get("min_ticks"),
            "supply_recovery": dict(supply_mapping),
        },
        "required_checkpoint_settings": {
            "checkpoint_every": 100,
            "checkpoint_keep_last": 2,
        },
        "observed_checkpoint_settings": {
            "checkpoint_every": _json_scalar(config.get("checkpoint_every")),
            "checkpoint_keep_last": _json_scalar(config.get("checkpoint_keep_last")),
        },
        "checkpoint_settings_match": checkpoint_settings_match,
        "normalized_recovery_settings": normalized,
        "scripted_provider_free_route": scripted,
    }


def _horizon_evidence(
        tick: int | None, status: str, active_tick: Any, *,
        completed_tick_raw: Any) -> tuple[bool, dict[str, Any]]:
    passed = bool(
        tick is not None
        and tick >= _THRESHOLDS["minimum_ticks"]
        and status in _COMPLETED_STATUSES
        and active_tick is None
    )
    return passed, {
        "tick": tick,
        "invalid_completed_tick": (
            _json_scalar(completed_tick_raw) if tick is None else None
        ),
        "minimum_ticks": _THRESHOLDS["minimum_ticks"],
        "status": status,
        "active_tick": _json_scalar(active_tick),
        "completed_statuses": sorted(_COMPLETED_STATUSES),
        "headless_horizon_boundary": status == "paused" and active_tick is None,
    }


def _buy_goods_evidence(store: Store, tick: int | None) -> tuple[bool, dict[str, Any]]:
    window = _THRESHOLDS["trailing_window_ticks"]
    warmup = _THRESHOLDS["warmup_ticks"]
    first_window_end = warmup + window - 1
    if tick is None or tick < first_window_end:
        return False, {
            "warmup_ticks": warmup,
            "window_ticks": window,
            "windows_evaluated": 0,
            "latest_window": None,
            "worst_window": None,
            "error": "post-warmup rolling window is incomplete",
        }
    try:
        rows = store.query(
            "SELECT id,tick,validation_status FROM action_proposals "
            "WHERE action_type='buy_goods' ORDER BY tick,id",
        )
    except Exception as exc:  # pragma: no cover - defensive corrupted-store path
        return False, _query_error_evidence(exc, window_start=warmup, window_end=tick)

    counts_by_tick: dict[int, dict[str, int]] = {}
    malformed_rows = 0
    invalid_proposal_ticks: list[dict[str, Any]] = []
    for row in rows:
        proposal_tick_raw = row["tick"]
        proposal_tick = _strict_tick(proposal_tick_raw)
        if proposal_tick is None:
            malformed_rows += 1
            invalid_proposal_ticks.append({
                "proposal_id": _integer(row["id"]),
                "tick": _json_scalar(proposal_tick_raw),
            })
            continue
        if proposal_tick < warmup or proposal_tick > tick:
            continue
        counts = counts_by_tick.setdefault(
            proposal_tick, {"attempts": 0, "rejected": 0, "unresolved": 0}
        )
        status = row["validation_status"]
        if status == "accepted":
            counts["attempts"] += 1
        elif status == "rejected":
            counts["attempts"] += 1
            counts["rejected"] += 1
        else:
            counts["unresolved"] += 1

    windows: list[dict[str, Any]] = []
    for window_end in range(first_window_end, tick + 1):
        window_start = window_end - window + 1
        attempts = sum(
            counts_by_tick.get(candidate_tick, {}).get("attempts", 0)
            for candidate_tick in range(window_start, window_end + 1)
        )
        rejected = sum(
            counts_by_tick.get(candidate_tick, {}).get("rejected", 0)
            for candidate_tick in range(window_start, window_end + 1)
        )
        unresolved = sum(
            counts_by_tick.get(candidate_tick, {}).get("unresolved", 0)
            for candidate_tick in range(window_start, window_end + 1)
        )
        raw_rate = None if attempts == 0 else rejected / attempts
        rate = None if raw_rate is None else round(raw_rate, 6)
        passed = bool(
            attempts > 0
            and unresolved == 0
            and raw_rate is not None
            and raw_rate <= _THRESHOLDS["max_buy_goods_rejection_rate"]
        )
        windows.append({
            "start_tick": window_start,
            "end_tick": window_end,
            "attempts": attempts,
            "rejected": rejected,
            "unresolved": unresolved,
            "rate": rate,
            "raw_rate": raw_rate,
            "passed": passed,
        })
    worst_window = max(windows, key=_purchase_window_score)
    return bool(not malformed_rows and all(item["passed"] for item in windows)), {
        "warmup_ticks": warmup,
        "window_ticks": window,
        "windows_evaluated": len(windows),
        "latest_window": windows[-1],
        "worst_window": worst_window,
        "failed_window_count": sum(not item["passed"] for item in windows),
        "malformed_row_count": malformed_rows,
        "invalid_proposal_ticks": invalid_proposal_ticks,
        "every_window_requires_nonzero_completed_attempts": True,
        "maximum_rate": _THRESHOLDS["max_buy_goods_rejection_rate"],
    }


def _unemployment_evidence(store: Store, tick: int | None) -> tuple[bool, dict[str, Any]]:
    window = _THRESHOLDS["trailing_window_ticks"]
    warmup = _THRESHOLDS["warmup_ticks"]
    first_window_end = warmup + window - 1
    if tick is None or tick < first_window_end:
        return False, {
            "warmup_ticks": warmup,
            "window_ticks": window,
            "windows_evaluated": 0,
            "latest_window": None,
            "worst_window": None,
            "error": "post-warmup rolling windows are incomplete",
        }
    try:
        rows = store.query(
            "SELECT id,tick,value FROM metrics WHERE name='unemployment' ORDER BY tick,id",
        )
    except Exception as exc:  # pragma: no cover - defensive corrupted-store path
        return False, _query_error_evidence(exc, window_start=0, window_end=tick)

    values: dict[int, float] = {}
    invalid_ticks: set[int] = set()
    malformed_rows = 0
    invalid_metric_ticks: list[dict[str, Any]] = []
    for row in rows:
        metric_tick_raw = row["tick"]
        metric_tick = _strict_tick(metric_tick_raw)
        value = _ratio(row["value"])
        if metric_tick is None:
            malformed_rows += 1
            invalid_metric_ticks.append({
                "metric_id": _integer(row["id"]),
                "tick": _json_scalar(metric_tick_raw),
            })
            continue
        if metric_tick > tick:
            continue
        if value is None:
            invalid_ticks.add(metric_tick)
            values.pop(metric_tick, None)
        else:
            values[metric_tick] = value
            invalid_ticks.discard(metric_tick)

    windows: list[dict[str, Any]] = []
    for window_end in range(first_window_end, tick + 1):
        trailing_start = window_end - window + 1
        preceding_start = trailing_start - window
        required_ticks = range(preceding_start, window_end + 1)
        missing = [candidate_tick for candidate_tick in required_ticks if candidate_tick not in values]
        invalid = [candidate_tick for candidate_tick in required_ticks if candidate_tick in invalid_ticks]
        item: dict[str, Any] = {
            "preceding_window": [preceding_start, trailing_start - 1],
            "trailing_window": [trailing_start, window_end],
            "preceding_trough": None,
            "trailing_peak": None,
            "rebound": None,
            "missing_ticks": missing,
            "invalid_ticks": invalid,
            "passed": False,
        }
        if not missing and not invalid:
            preceding_trough = min(
                values[candidate_tick] for candidate_tick in range(preceding_start, trailing_start)
            )
            trailing_peak = max(
                values[candidate_tick] for candidate_tick in range(trailing_start, window_end + 1)
            )
            raw_rebound = trailing_peak - preceding_trough
            rebound = round(raw_rebound, 6)
            item.update({
                "preceding_trough": round(preceding_trough, 6),
                "trailing_peak": round(trailing_peak, 6),
                "rebound": rebound,
                "raw_rebound": raw_rebound,
                "passed": raw_rebound <= _THRESHOLDS["max_unemployment_rebound"],
            })
        windows.append(item)
    worst_window = max(windows, key=_unemployment_window_score)
    observed_rebounds = [item["rebound"] for item in windows if item["rebound"] is not None]
    observed_raw_rebounds = [
        item["raw_rebound"] for item in windows if item.get("raw_rebound") is not None
    ]
    return bool(not malformed_rows and all(item["passed"] for item in windows)), {
        "warmup_ticks": warmup,
        "window_ticks": window,
        "windows_evaluated": len(windows),
        "latest_window": windows[-1],
        "worst_window": worst_window,
        "maximum_observed_rebound": max(observed_rebounds) if observed_rebounds else None,
        "maximum_observed_raw_rebound": (
            max(observed_raw_rebounds) if observed_raw_rebounds else None
        ),
        "failed_window_count": sum(not item["passed"] for item in windows),
        "malformed_row_count": malformed_rows,
        "invalid_metric_ticks": invalid_metric_ticks,
        "maximum_rebound": _THRESHOLDS["max_unemployment_rebound"],
    }


def _purchase_window_score(window: Mapping[str, Any]) -> tuple[int, float, int, int]:
    if int(window["unresolved"]) > 0:
        return (
            3,
            float(window.get("raw_rate") or 0.0),
            int(window["unresolved"]),
            -int(window["end_tick"]),
        )
    if int(window["attempts"]) == 0:
        return (2, 0.0, 0, -int(window["end_tick"]))
    return (
        1 if not window["passed"] else 0,
        float(window.get("raw_rate") or 0.0),
        0,
        -int(window["end_tick"]),
    )


def _unemployment_window_score(window: Mapping[str, Any]) -> tuple[int, float, int]:
    if window["missing_ticks"] or window["invalid_ticks"]:
        return (2, 0.0, -int(window["trailing_window"][1]))
    return (
        1 if not window["passed"] else 0,
        float(window.get("raw_rebound") or 0.0),
        -int(window["trailing_window"][1]),
    )


def _unit_economics_evidence(
        store: Store, *, activation_tick: int, completed_tick: int | None) -> tuple[
            bool, list[dict[str, Any]], dict[int, dict[str, Any]], dict[str, Any]]:
    """Validate every producer evidenced by product data or persisted events."""
    if completed_tick is None:
        return False, [], {}, {"error": "completed run tick is missing or invalid"}
    try:
        firms = store.query(
            "SELECT id,name,status,sector,product_json,bankrupt_tick FROM firms ORDER BY id"
        )
        producer_rows = store.query(
            "SELECT id,tick,kind,subject_type,subject_id,payload_json FROM events "
            "WHERE kind IN ('production','goods_sale') ORDER BY tick,id",
        )
        employment_rows = store.query(
            "SELECT id,firm_id,wage_cents,pay_interval_ticks FROM employments "
            "WHERE status='active' ORDER BY firm_id,id"
        )
    except Exception as exc:  # pragma: no cover - defensive corrupted-store path
        return False, [], {}, _query_error_evidence(exc)

    latest_production: dict[int, dict[str, Any]] = {}
    evidenced_firm_ids: set[int] = set()
    evidenced_producer_events: list[dict[str, Any]] = []
    malformed_producer_events: list[dict[str, Any]] = []
    producer_identity_mismatches: list[dict[str, Any]] = []
    invalid_producer_subject_fallbacks: list[dict[str, Any]] = []
    producer_events_after_completed_horizon: list[dict[str, Any]] = []
    for row in producer_rows:
        payload = load_json(row["payload_json"], {})
        payload = payload if isinstance(payload, Mapping) else {}
        payload_has_firm_id = "firm_id" in payload
        payload_firm_id = (
            _strict_entity_id(payload.get("firm_id")) if payload_has_firm_id else None
        )
        subject_type = row["subject_type"]
        subject_id = row["subject_id"]
        subject_has_firm_id = subject_id is not None
        subject_is_firm = subject_type == "firm"
        subject_firm_id = (
            _strict_entity_id(subject_id) if subject_is_firm and subject_has_firm_id else None
        )
        firm_id = payload_firm_id if payload_has_firm_id else subject_firm_id
        event_tick_raw = row["tick"]
        event_tick = _strict_tick(event_tick_raw)
        event = {
            "event_id": _integer(row["id"]),
            "kind": str(row["kind"] or ""),
            "tick": _json_scalar(event_tick_raw),
            "firm_id": firm_id,
        }
        if not payload_has_firm_id and subject_has_firm_id and not subject_is_firm:
            invalid_producer_subject_fallbacks.append({
                "event_id": _integer(row["id"]),
                "kind": str(row["kind"] or ""),
                "reason": "subject_fallback_requires_firm_subject_type",
                "subject_id": _json_scalar(subject_id),
                "subject_type": _json_scalar(subject_type),
                "tick": _json_scalar(event_tick_raw),
            })
            malformed_producer_events.append(event)
            continue
        if (
                payload_has_firm_id
                and subject_is_firm
                and subject_has_firm_id
                and payload_firm_id is not None
                and subject_firm_id is not None
                and payload_firm_id != subject_firm_id):
            producer_identity_mismatches.append({
                "event_id": _integer(row["id"]),
                "kind": str(row["kind"] or ""),
                "payload_firm_id": payload_firm_id,
                "subject_id": subject_firm_id,
                "tick": _json_scalar(event_tick_raw),
            })
            continue
        if (
                firm_id is None
                or event_tick is None
                or (payload_has_firm_id and payload_firm_id is None)
                or (subject_is_firm and subject_has_firm_id and subject_firm_id is None)):
            malformed_producer_events.append(event)
            continue
        if event_tick > completed_tick:
            producer_events_after_completed_horizon.append(event)
            continue
        if event_tick < activation_tick:
            continue
        evidenced_firm_ids.add(firm_id)
        evidenced_producer_events.append(event)
        if row["kind"] != "production":
            continue
        unit_cost = _nonnegative_integer(payload.get("unit_cost_cents"))
        if unit_cost is None:
            malformed_producer_events.append(event)
            continue
        latest_production[firm_id] = {
            "event_id": _integer(row["id"]),
            "tick": event_tick,
            "unit_cost_cents": unit_cost,
        }

    employments: dict[int, list[Any]] = {}
    for row in employment_rows:
        firm_id = _integer(row["firm_id"])
        if firm_id is not None:
            employments.setdefault(firm_id, []).append(row)

    per_firm: list[dict[str, Any]] = []
    recovery_goods_firms: dict[int, dict[str, Any]] = {}
    excluded_historical_goods_firms: list[dict[str, Any]] = []
    known_firm_ids = {
        firm_id for row in firms if (firm_id := _strict_entity_id(row["id"])) is not None
    }
    orphan_producer_events = [
        event for event in evidenced_producer_events if event["firm_id"] not in known_firm_ids
    ]
    coverage_bps = _PROFILE_SETTINGS["gross_margin_coverage_bps"]
    wage_floor = _PROFILE_SETTINGS["wage_floor_cents"]
    for row in firms:
        firm_id = _strict_entity_id(row["id"])
        if firm_id is None:
            continue
        product = load_json(row["product_json"], {})
        product = product if isinstance(product, Mapping) else {}
        output_per_worker = _positive_integer(product.get("output_per_worker"))
        status = str(row["status"] or "")
        if output_per_worker is None and firm_id not in evidenced_firm_ids:
            continue
        bankrupt_tick = row["bankrupt_tick"]
        recovery_goods_firms[firm_id] = {
            "status": status,
            "bankrupt_tick": bankrupt_tick,
            "has_bankrupt_tick": bankrupt_tick is not None,
        }
        if status in {"bankrupt", "acquired"}:
            excluded_historical_goods_firms.append({"firm_id": firm_id, "status": status})
            continue

        price = _positive_integer(product.get("unit_price_cents"))
        production = latest_production.get(firm_id)
        errors: list[str] = []
        if output_per_worker is None:
            errors.append("missing_or_invalid_output_per_worker")
        if price is None:
            errors.append("missing_or_invalid_unit_price")
        if production is None:
            errors.append("missing_actual_production_cost")
        active_employments = employments.get(firm_id, [])
        if not active_employments:
            errors.append("missing_active_employment")

        employment_evidence: list[dict[str, Any]] = []
        wages_ok = True
        if price is not None and production is not None and output_per_worker is not None:
            unit_cost = int(production["unit_cost_cents"])
            for employment in active_employments:
                wage = _nonnegative_integer(employment["wage_cents"])
                interval = _positive_integer(employment["pay_interval_ticks"])
                ceiling = None
                if interval is not None:
                    margin = max(0, price - unit_cost)
                    ceiling = margin * output_per_worker * interval * 10_000 // coverage_bps
                within_floor = wage is not None and wage >= wage_floor
                within_ceiling = wage is not None and ceiling is not None and wage <= ceiling
                valid = bool(within_floor and within_ceiling)
                wages_ok = wages_ok and valid
                employment_evidence.append({
                    "employment_id": _integer(employment["id"]),
                    "wage_cents": wage,
                    "pay_interval_ticks": interval,
                    "wage_floor_cents": wage_floor,
                    "safe_wage_ceiling_cents": ceiling,
                    "within_floor": within_floor,
                    "within_ceiling": within_ceiling,
                    "validated": valid,
                })
        elif active_employments:
            wages_ok = False
            for employment in active_employments:
                employment_evidence.append({
                    "employment_id": _integer(employment["id"]),
                    "wage_cents": _nonnegative_integer(employment["wage_cents"]),
                    "pay_interval_ticks": _positive_integer(employment["pay_interval_ticks"]),
                    "wage_floor_cents": wage_floor,
                    "safe_wage_ceiling_cents": None,
                    "within_floor": False,
                    "within_ceiling": False,
                    "validated": False,
                })
        validated = bool(not errors and wages_ok and employment_evidence)
        per_firm.append({
            "firm_id": firm_id,
            "name": str(row["name"] or ""),
            "status": status,
            "sector": row["sector"],
            "product": {
                "unit_price_cents": price,
                "output_per_worker": output_per_worker,
                "stored_base_input_cost_cents": _nonnegative_integer(
                    product.get("base_input_cost_cents")
                ),
            },
            "production": production,
            "employment": employment_evidence,
            "validation_errors": errors,
            "validated": validated,
        })

    passed = bool(per_firm) and all(firm["validated"] for firm in per_firm)
    return bool(
        passed
        and not malformed_producer_events
        and not producer_identity_mismatches
        and not invalid_producer_subject_fallbacks
        and not producer_events_after_completed_horizon
        and not orphan_producer_events
    ), per_firm, recovery_goods_firms, {
        "active_recovery_managed_goods_firm_count": len(per_firm),
        "recovery_managed_goods_firm_count": len(recovery_goods_firms),
        "validated_firm_count": sum(firm["validated"] for firm in per_firm),
        "excluded_historical_goods_firms": excluded_historical_goods_firms,
        "malformed_producer_events": malformed_producer_events,
        "producer_identity_mismatches": producer_identity_mismatches,
        "invalid_producer_subject_fallbacks": invalid_producer_subject_fallbacks,
        "producer_events_after_completed_horizon": producer_events_after_completed_horizon,
        "orphan_producer_events": orphan_producer_events,
        "requires_persisted_product_production_and_active_employment": True,
    }


def _insolvency_evidence(
        store: Store, recovery_goods_firms: Mapping[int, Mapping[str, Any]], *,
        activation_tick: int, completed_tick: int | None) -> tuple[bool, dict[str, Any]]:
    """Reconcile recovery-goods terminal state and event identities."""
    if completed_tick is None:
        return False, {"error": "completed run tick is missing or invalid"}
    try:
        rows = store.query(
            "SELECT id,tick,kind,subject_type,subject_id,payload_json FROM events "
            "WHERE kind IN ('bankruptcy','merger_closed') ORDER BY tick,id",
        )
        firm_rows = store.query("SELECT id,status,bankrupt_tick FROM firms ORDER BY id")
    except Exception as exc:  # pragma: no cover - defensive corrupted-store path
        return False, _query_error_evidence(exc)

    firm_states = {
        firm_id: {"status": str(row["status"] or ""), "bankrupt_tick": row["bankrupt_tick"]}
        for row in firm_rows
        if (firm_id := _strict_entity_id(row["id"])) is not None
    }
    known_firm_ids = set(firm_states)
    bankruptcies_by_firm: dict[int, list[dict[str, Any]]] = {}
    acquisitions_by_firm: dict[int, list[dict[str, Any]]] = {}
    terminal_events_by_firm: dict[int, list[dict[str, Any]]] = {}
    unparseable_bankruptcies: list[dict[str, Any]] = []
    unparseable_acquisitions: list[dict[str, Any]] = []
    orphan_terminal_events: list[dict[str, Any]] = []
    bankruptcy_identity_mismatches: list[dict[str, Any]] = []
    invalid_bankruptcy_subject_fallbacks: list[dict[str, Any]] = []
    invalid_merger_acquirers: list[dict[str, Any]] = []
    invalid_terminal_event_ticks: list[dict[str, Any]] = []
    terminal_events_after_completed_horizon: list[dict[str, Any]] = []
    merger_events: list[dict[str, Any]] = []
    for row in rows:
        payload = load_json(row["payload_json"], {})
        payload = payload if isinstance(payload, Mapping) else {}
        event_tick_raw = row["tick"]
        event_tick = _strict_tick(event_tick_raw)
        event_id = _integer(row["id"])
        if row["kind"] == "bankruptcy":
            payload_has_firm_id = "firm_id" in payload
            payload_firm_id = (
                _strict_entity_id(payload.get("firm_id")) if payload_has_firm_id else None
            )
            subject_type = row["subject_type"]
            subject_id = row["subject_id"]
            subject_is_present = subject_id is not None
            subject_is_firm = subject_type == "firm"
            subject_firm_id = (
                _strict_entity_id(subject_id) if subject_is_firm and subject_is_present else None
            )
            firm_id = _event_firm_id(payload, subject_type, subject_id)
            reason = payload.get("reason")
            identity_is_valid = True
            if not payload_has_firm_id and subject_is_present and not subject_is_firm:
                identity_is_valid = False
                invalid_bankruptcy_subject_fallbacks.append({
                    "event_id": event_id,
                    "reason": "subject_fallback_requires_firm_subject_type",
                    "subject_id": _json_scalar(subject_id),
                    "subject_type": _json_scalar(subject_type),
                    "tick": _json_scalar(event_tick_raw),
                })
            if (
                    payload_has_firm_id
                    and subject_is_firm
                    and subject_is_present
                    and payload_firm_id is not None):
                identity_reason = None
                if subject_firm_id is None:
                    identity_reason = "missing_or_invalid_bankruptcy_subject_firm_id"
                elif subject_firm_id not in known_firm_ids:
                    identity_reason = "unknown_bankruptcy_subject_firm_id"
                elif payload_firm_id != subject_firm_id:
                    identity_reason = "bankruptcy_subject_identity_mismatch"
                if identity_reason is not None:
                    identity_is_valid = False
                    bankruptcy_identity_mismatches.append({
                        "event_id": event_id,
                        "payload_firm_id": payload_firm_id,
                        "reason": identity_reason,
                        "subject_id": _json_scalar(subject_id),
                        "tick": _json_scalar(event_tick_raw),
                    })
            event = {
                "event_id": event_id,
                "kind": "bankruptcy",
                "tick": _json_scalar(event_tick_raw),
                "firm_id": firm_id,
                "reason": reason,
                "identity_is_valid": identity_is_valid,
            }
            if event_tick is None:
                invalid_terminal_event_ticks.append({
                    "event_id": event_id,
                    "kind": "bankruptcy",
                    "tick": _json_scalar(event_tick_raw),
                })
                unparseable_bankruptcies.append({
                    "event_id": event_id,
                    "tick": _json_scalar(event_tick_raw),
                    "firm_id": firm_id,
                })
                continue
            if firm_id is not None:
                if firm_id not in known_firm_ids:
                    orphan_terminal_events.append({
                        "event_id": event_id,
                        "firm_id": firm_id,
                        "kind": "bankruptcy",
                        "tick": _json_scalar(event_tick_raw),
                    })
            if event_tick > completed_tick:
                terminal_events_after_completed_horizon.append({
                    "event_id": event_id,
                    "firm_id": firm_id,
                    "kind": "bankruptcy",
                    "tick": event_tick,
                })
                continue
            if firm_id is not None:
                terminal_events_by_firm.setdefault(firm_id, []).append(event)
                bankruptcies_by_firm.setdefault(firm_id, []).append(event)
            if firm_id is None or not isinstance(reason, str) or not reason.strip():
                unparseable_bankruptcies.append({
                    "event_id": event_id,
                    "tick": _json_scalar(event_tick_raw),
                    "firm_id": firm_id,
                })
        else:
            firm_id = _strict_entity_id(payload.get("target_firm_id"))
            acquirer_raw = payload.get("acquirer_firm_id")
            acquirer_firm_id = _strict_entity_id(acquirer_raw)
            acquirer_is_valid = (
                acquirer_firm_id is not None and acquirer_firm_id in known_firm_ids
            )
            if not acquirer_is_valid:
                invalid_merger_acquirers.append({
                    "acquirer_firm_id": _json_scalar(acquirer_raw),
                    "event_id": event_id,
                    "reason": (
                        "missing_or_invalid_acquirer_firm_id"
                        if acquirer_firm_id is None
                        else "unknown_acquirer_firm_id"
                    ),
                    "tick": event_tick,
                })
            event = {
                "event_id": event_id,
                "kind": "merger_closed",
                "tick": _json_scalar(event_tick_raw),
                "firm_id": firm_id,
                "acquirer_firm_id": acquirer_firm_id,
                "acquirer_is_valid": acquirer_is_valid,
                "acquirer_is_viable": acquirer_is_valid,
            }
            if event_tick is None:
                invalid_terminal_event_ticks.append({
                    "event_id": event_id,
                    "kind": "merger_closed",
                    "tick": _json_scalar(event_tick_raw),
                })
                unparseable_acquisitions.append(event)
                continue
            if firm_id is not None:
                if firm_id not in known_firm_ids:
                    orphan_terminal_events.append({
                        "event_id": event_id,
                        "firm_id": firm_id,
                        "kind": "merger_closed",
                        "tick": _json_scalar(event_tick_raw),
                    })
            if acquirer_firm_id is not None and acquirer_firm_id not in known_firm_ids:
                orphan_terminal_events.append({
                    "event_id": event_id,
                    "firm_id": acquirer_firm_id,
                    "kind": "merger_closed",
                    "tick": _json_scalar(event_tick_raw),
                })
            if event_tick > completed_tick:
                terminal_events_after_completed_horizon.append({
                    "event_id": event_id,
                    "firm_id": firm_id,
                    "kind": "merger_closed",
                    "tick": event_tick,
                })
                continue
            if firm_id is not None:
                terminal_events_by_firm.setdefault(firm_id, []).append(event)
            merger_events.append(event)
            if firm_id is None:
                unparseable_acquisitions.append(event)
                continue
            acquisitions_by_firm.setdefault(firm_id, []).append(event)

    for event in merger_events:
        acquirer_firm_id = event["acquirer_firm_id"]
        if not event["acquirer_is_valid"]:
            continue
        if acquirer_firm_id == event["firm_id"]:
            event["acquirer_is_viable"] = False
            invalid_merger_acquirers.append({
                "acquirer_firm_id": acquirer_firm_id,
                "event_id": event["event_id"],
                "reason": "self_acquisition",
                "target_firm_id": event["firm_id"],
                "tick": event["tick"],
            })
            continue
        terminal_event = next(
            (
                candidate
                for candidate in terminal_events_by_firm.get(acquirer_firm_id, [])
                if _terminal_event_precedes(candidate, event)
            ),
            None,
        )
        if terminal_event is not None:
            event["acquirer_is_viable"] = False
            invalid_merger_acquirers.append({
                "acquirer_firm_id": acquirer_firm_id,
                "event_id": event["event_id"],
                "reason": "acquirer_terminal_before_merger",
                "terminal_event_id": terminal_event["event_id"],
                "terminal_kind": terminal_event["kind"],
                "terminal_tick": terminal_event["tick"],
                "tick": event["tick"],
            })
            continue
        state = firm_states[acquirer_firm_id]
        bankrupt_tick_raw = state["bankrupt_tick"]
        if (
                state["status"] in _ACTIVE_RECOVERY_FIRM_STATUSES
                or state["status"] == "acquired") and bankrupt_tick_raw is not None:
            event["acquirer_is_viable"] = False
            invalid_merger_acquirers.append({
                "acquirer_firm_id": acquirer_firm_id,
                "bankrupt_tick": _json_scalar(bankrupt_tick_raw),
                "event_id": event["event_id"],
                "reason": "acquirer_nonbankrupt_status_has_bankrupt_tick",
                "status": state["status"],
                "tick": event["tick"],
            })
            continue
        if state["status"] == "bankrupt":
            terminal_tick_raw = bankrupt_tick_raw
            terminal_tick = _strict_tick(terminal_tick_raw)
            if terminal_tick is None:
                event["acquirer_is_viable"] = False
                invalid_merger_acquirers.append({
                    "acquirer_firm_id": acquirer_firm_id,
                    "event_id": event["event_id"],
                    "reason": "acquirer_terminal_status_has_invalid_tick",
                    "terminal_kind": "bankruptcy",
                    "terminal_tick": _json_scalar(terminal_tick_raw),
                    "tick": event["tick"],
                })
            elif terminal_tick > completed_tick:
                event["acquirer_is_viable"] = False
                invalid_merger_acquirers.append({
                    "acquirer_firm_id": acquirer_firm_id,
                    "event_id": event["event_id"],
                    "reason": "acquirer_terminal_status_after_completed_horizon",
                    "terminal_kind": "bankruptcy",
                    "terminal_tick": terminal_tick,
                    "tick": event["tick"],
                })
            elif terminal_tick < event["tick"]:
                event["acquirer_is_viable"] = False
                invalid_merger_acquirers.append({
                    "acquirer_firm_id": acquirer_firm_id,
                    "event_id": event["event_id"],
                    "reason": "acquirer_terminal_before_merger",
                    "terminal_kind": "bankruptcy",
                    "terminal_tick": terminal_tick,
                    "tick": event["tick"],
                })
            elif terminal_tick == event["tick"] and not any(
                    candidate["kind"] == "bankruptcy"
                    and candidate["tick"] == terminal_tick
                    and candidate["identity_is_valid"]
                    and isinstance(candidate["reason"], str)
                    and candidate["reason"].strip()
                    and _terminal_event_follows(candidate, event)
                    for candidate in terminal_events_by_firm.get(acquirer_firm_id, [])):
                event["acquirer_is_viable"] = False
                invalid_merger_acquirers.append({
                    "acquirer_firm_id": acquirer_firm_id,
                    "event_id": event["event_id"],
                    "reason": "acquirer_terminal_status_has_unprovable_timing",
                    "terminal_kind": "bankruptcy",
                    "terminal_tick": terminal_tick,
                    "tick": event["tick"],
                })
        elif state["status"] == "acquired":
            acquisition_history = [
                candidate
                for candidate in terminal_events_by_firm.get(acquirer_firm_id, [])
                if candidate["kind"] == "merger_closed"
            ]
            if not acquisition_history:
                event["acquirer_is_viable"] = False
                invalid_merger_acquirers.append({
                    "acquirer_firm_id": acquirer_firm_id,
                    "event_id": event["event_id"],
                    "reason": "acquirer_terminal_status_has_unprovable_timing",
                    "terminal_kind": "merger_closed",
                    "terminal_tick": None,
                    "tick": event["tick"],
                })
        elif state["status"] not in _ACTIVE_RECOVERY_FIRM_STATUSES:
            event["acquirer_is_viable"] = False
            invalid_merger_acquirers.append({
                "acquirer_firm_id": acquirer_firm_id,
                "event_id": event["event_id"],
                "reason": "acquirer_not_operating_at_merger",
                "status": state["status"],
                "tick": event["tick"],
            })

    insolvencies: list[dict[str, Any]] = []
    for firm_id, events in bankruptcies_by_firm.items():
        if firm_id not in recovery_goods_firms:
            continue
        for event in events:
            reason = event["reason"]
            if isinstance(reason, str) and reason.strip().lower() == "insolvency":
                insolvencies.append({
                    "event_id": event["event_id"],
                    "tick": event["tick"],
                    "firm_id": firm_id,
                    "reason": reason,
                })

    state_mismatches: list[dict[str, Any]] = []
    permitted_departures: list[dict[str, Any]] = []
    for firm_id in sorted(recovery_goods_firms):
        state = recovery_goods_firms[firm_id]
        status = str(state.get("status") or "")
        bankrupt_tick_raw = state.get("bankrupt_tick")
        bankrupt_tick = _strict_tick(bankrupt_tick_raw)
        has_bankrupt_tick = bool(state.get("has_bankrupt_tick"))
        bankruptcy_events = bankruptcies_by_firm.get(firm_id, [])
        acquisition_events = acquisitions_by_firm.get(firm_id, [])
        if status not in _KNOWN_RECOVERY_FIRM_STATUSES:
            state_mismatches.append({
                "firm_id": firm_id,
                "reason": "unknown_recovery_goods_firm_status",
                "status": status,
                "tick": None,
            })
            for event in bankruptcy_events:
                state_mismatches.append({
                    "firm_id": firm_id,
                    "reason": "bankruptcy_event_requires_bankrupt_status",
                    "status": status,
                    "tick": event["tick"],
                })
            for event in acquisition_events:
                state_mismatches.append({
                    "firm_id": firm_id,
                    "reason": "acquisition_event_requires_acquired_status",
                    "status": status,
                    "tick": event["tick"],
                })
            continue
        if status in _ACTIVE_RECOVERY_FIRM_STATUSES:
            if has_bankrupt_tick:
                state_mismatches.append({
                    "firm_id": firm_id,
                    "reason": "nonterminal_status_has_bankrupt_tick",
                    "status": status,
                    "tick": _json_scalar(bankrupt_tick_raw),
                })
            for event in bankruptcy_events:
                state_mismatches.append({
                    "firm_id": firm_id,
                    "reason": "bankruptcy_event_requires_bankrupt_status",
                    "status": status,
                    "tick": event["tick"],
                })
            for event in acquisition_events:
                state_mismatches.append({
                    "firm_id": firm_id,
                    "reason": "acquisition_event_requires_acquired_status",
                    "status": status,
                    "tick": event["tick"],
                })
            continue
        if status == "bankrupt":
            if bankrupt_tick is None:
                state_mismatches.append({
                    "firm_id": firm_id,
                    "reason": "missing_or_invalid_bankruptcy_tick",
                    "status": status,
                    "tick": _json_scalar(bankrupt_tick_raw),
                })
            elif bankrupt_tick > completed_tick:
                state_mismatches.append({
                    "firm_id": firm_id,
                    "reason": "bankruptcy_tick_after_completed_horizon",
                    "status": status,
                    "tick": bankrupt_tick,
                })
            elif not bankruptcy_events:
                state_mismatches.append({
                    "firm_id": firm_id,
                    "reason": "missing_matching_bankruptcy_event",
                    "status": status,
                    "tick": bankrupt_tick,
                })
            elif bankrupt_tick is not None:
                matching_events: list[dict[str, Any]] = []
                all_events_match_state = True
                for event in bankruptcy_events:
                    if event["tick"] != bankrupt_tick:
                        all_events_match_state = False
                        state_mismatches.append({
                            "firm_id": firm_id,
                            "reason": "bankruptcy_event_tick_mismatch",
                            "status": status,
                            "tick": bankrupt_tick,
                        })
                        continue
                    if not isinstance(event["reason"], str) or not event["reason"].strip():
                        all_events_match_state = False
                        state_mismatches.append({
                            "firm_id": firm_id,
                            "reason": "missing_or_invalid_bankruptcy_reason",
                            "status": status,
                            "tick": bankrupt_tick,
                        })
                        continue
                    matching_events.append(event)
                if (
                        matching_events
                        and all_events_match_state
                        and all(event["identity_is_valid"] for event in matching_events)
                        and all(
                            str(event["reason"]).strip().lower() != "insolvency"
                            for event in matching_events
                        )):
                    permitted_departures.append({
                        "firm_id": firm_id,
                        "kind": "bankruptcy",
                        "status": status,
                        "tick": bankrupt_tick,
                    })
            for event in acquisition_events:
                state_mismatches.append({
                    "firm_id": firm_id,
                    "reason": "acquisition_event_requires_acquired_status",
                    "status": status,
                    "tick": event["tick"],
                })
        elif status == "acquired":
            if has_bankrupt_tick:
                state_mismatches.append({
                    "firm_id": firm_id,
                    "reason": "acquired_status_has_bankrupt_tick",
                    "status": status,
                    "tick": _json_scalar(bankrupt_tick_raw),
                })
            for event in bankruptcy_events:
                state_mismatches.append({
                    "firm_id": firm_id,
                    "reason": "bankruptcy_event_requires_bankrupt_status",
                    "status": status,
                    "tick": event["tick"],
                })
            if not acquisition_events:
                state_mismatches.append({
                    "firm_id": firm_id,
                    "reason": "missing_matching_acquisition_event",
                    "status": status,
                    "tick": None,
                })
                continue
            if (
                    not bankruptcy_events
                    and not has_bankrupt_tick
                    and all(event["acquirer_is_viable"] for event in acquisition_events)):
                permitted_departures.append({
                    "firm_id": firm_id,
                    "kind": "acquisition",
                    "status": status,
                    "tick": acquisition_events[0]["tick"],
                })

    return bool(
        not insolvencies
        and not unparseable_bankruptcies
        and not unparseable_acquisitions
        and not orphan_terminal_events
        and not bankruptcy_identity_mismatches
        and not invalid_bankruptcy_subject_fallbacks
        and not invalid_merger_acquirers
        and not invalid_terminal_event_ticks
        and not terminal_events_after_completed_horizon
        and not state_mismatches
    ), {
        "recovery_managed_goods_firm_ids": sorted(recovery_goods_firms),
        "recovery_managed_insolvencies": insolvencies,
        "unparseable_bankruptcies": unparseable_bankruptcies,
        "unparseable_acquisitions": unparseable_acquisitions,
        "orphan_terminal_events": orphan_terminal_events,
        "bankruptcy_identity_mismatches": bankruptcy_identity_mismatches,
        "invalid_bankruptcy_subject_fallbacks": invalid_bankruptcy_subject_fallbacks,
        "invalid_merger_acquirers": invalid_merger_acquirers,
        "invalid_terminal_event_ticks": invalid_terminal_event_ticks,
        "terminal_events_after_completed_horizon": terminal_events_after_completed_horizon,
        "state_mismatches": state_mismatches,
        "permitted_departures": permitted_departures,
    }


def _labor_backlog_evidence(store: Store) -> tuple[bool, dict[str, Any]]:
    try:
        open_jobs = int(store.scalar("SELECT COUNT(*) FROM jobs WHERE status='open'", default=0))
        pending_applications = int(store.scalar(
            "SELECT COUNT(*) FROM applications WHERE state='pending'", default=0))
        pending_job_offers = int(store.scalar(
            "SELECT COUNT(*) FROM job_offers WHERE status='pending'", default=0))
    except Exception as exc:  # pragma: no cover - defensive corrupted-store path
        return False, _query_error_evidence(exc)
    limits = {
        "open_jobs": _THRESHOLDS["max_open_jobs"],
        "pending_applications": _THRESHOLDS["max_pending_applications"],
        "pending_job_offers": _THRESHOLDS["max_pending_job_offers"],
    }
    observed = {
        "open_jobs": open_jobs,
        "pending_applications": pending_applications,
        "pending_job_offers": pending_job_offers,
    }
    return all(observed[name] <= limits[name] for name in limits), {
        **observed,
        "limits": limits,
        "bound_reason": "finite end-tick labor queue bound for the 12-firm profile",
    }


def _ledger_evidence(store: Store) -> tuple[bool, dict[str, Any]]:
    try:
        reconciled, diagnostics = Ledger(store).reconcile()
        return bool(reconciled), diagnostics
    except Exception as exc:  # pragma: no cover - defensive corrupted-store path
        return False, _query_error_evidence(exc)


def _sqlite_evidence(store: Store) -> tuple[bool, dict[str, Any]]:
    try:
        quick_rows = store.query("PRAGMA quick_check")
        integrity_rows = store.query("PRAGMA integrity_check")
        foreign_rows = store.query("PRAGMA foreign_key_check")
    except Exception as exc:  # pragma: no cover - defensive corrupted-store path
        return False, _query_error_evidence(exc)
    quick_check = [str(row[0]) for row in quick_rows]
    integrity_check = [str(row[0]) for row in integrity_rows]
    foreign_key_check = [
        {key: _json_scalar(row[key]) for key in row.keys()} for row in foreign_rows
    ]
    passed = quick_check == ["ok"] and integrity_check == ["ok"] and not foreign_key_check
    return passed, {
        "quick_check": quick_check,
        "integrity_check": integrity_check,
        "foreign_key_check": foreign_key_check,
    }


def _checkpoint_evidence(
        store: Store, run_id: str, config: Mapping[str, Any]) -> tuple[bool, dict[str, Any]]:
    """Validate retained canonical checkpoint artifacts without instantiating a World."""
    keep_last = config.get("checkpoint_keep_last")
    checkpoint_dir_value = config.get("checkpoint_dir")
    configured_dir = _logical_checkpoint_directory(checkpoint_dir_value)
    if (
            type(keep_last) is not int
            or keep_last <= 0
            or not isinstance(checkpoint_dir_value, str)
            or not checkpoint_dir_value.strip()):
        return False, {
            "configured_keep_last": _json_scalar(keep_last),
            "configured_checkpoint_dir": configured_dir,
            "error": "checkpoint retention configuration is missing or invalid",
        }
    try:
        rows = store.query("SELECT id,tick,path FROM checkpoints ORDER BY tick,id")
    except Exception as exc:  # pragma: no cover - defensive corrupted-store path
        return False, _query_error_evidence(exc)

    invalid_tick_rows = [
        {
            "checkpoint_id": _integer(row["id"]),
            "raw_tick": _json_scalar(row["tick"]),
            "reason": "invalid_tick",
        }
        for row in rows
        if _strict_tick(row["tick"]) is None
    ]
    checkpoint_dir = _checkpoint_directory_from_rows(
        rows, run_id=run_id, configured_value=checkpoint_dir_value)
    if checkpoint_dir is None:
        return False, {
            "configured_keep_last": keep_last,
            "configured_checkpoint_dir": configured_dir,
            "current_rows": [],
            "current_row_count": 0,
            "current_database_artifact_count": 0,
            "current_manifest_artifact_count": 0,
            "artifacts_match_current_rows": False,
            "excluded_rows": invalid_tick_rows,
            "error": "checkpoint directory cannot be reconstructed from persisted rows",
        }

    current_rows: list[dict[str, Any]] = []
    excluded_rows: list[dict[str, Any]] = list(invalid_tick_rows)
    expected_db_paths: set[Path] = set()
    expected_manifest_paths: set[Path] = set()
    for row in rows:
        tick_raw = row["tick"]
        tick = _strict_tick(tick_raw)
        row_id = _integer(row["id"])
        if tick is None:
            continue
        database = checkpoint_dir / f"{run_id}_t{tick}.db"
        manifest = checkpoint_manifest_path(database)
        if type(row["path"]) is not str or row["path"] != str(database):
            excluded_rows.append({
                "checkpoint_id": row_id,
                "tick": tick,
                "reason": "outside_current_run_scope",
            })
            continue
        try:
            safe_path = (
                database.parent == checkpoint_dir
                and not database.is_symlink()
                and not manifest.is_symlink()
                and database.resolve() == database
                and manifest.resolve() == manifest
                and database.is_relative_to(checkpoint_dir)
                and manifest.is_relative_to(checkpoint_dir)
            )
        except (OSError, RuntimeError, ValueError):
            safe_path = False
        if not safe_path:
            excluded_rows.append({
                "checkpoint_id": row_id,
                "tick": tick,
                "reason": "unsafe_artifact_path",
            })
            continue
        validation = _validate_checkpoint_artifact(
            database, manifest, run_id=run_id, tick=tick)
        current_rows.append({
            "checkpoint_id": row_id,
            "tick": tick,
            "artifact": database.name,
            "manifest": manifest.name,
            "database_exists": database.is_file(),
            "manifest_exists": manifest.is_file(),
            **validation,
        })
        expected_db_paths.add(database)
        expected_manifest_paths.add(manifest)

    db_files: set[Path] = set()
    manifest_files: set[Path] = set()
    if checkpoint_dir.is_dir():
        pattern = re.compile(rf"^{re.escape(run_id)}_t[0-9]+\.db$")
        manifest_pattern = re.compile(rf"^{re.escape(run_id)}_t[0-9]+\.db\.manifest\.json$")
        try:
            for path in checkpoint_dir.iterdir():
                if pattern.fullmatch(path.name):
                    db_files.add(path)
                elif manifest_pattern.fullmatch(path.name):
                    manifest_files.add(path)
        except OSError:
            pass

    artifacts_complete = all(
        row["database_exists"] and row["manifest_exists"] for row in current_rows
    )
    manifests_valid = all(row["manifest_valid"] for row in current_rows)
    artifacts_match_rows = db_files == expected_db_paths and manifest_files == expected_manifest_paths
    passed = bool(
        current_rows
        and not excluded_rows
        and len(current_rows) <= keep_last
        and len(db_files) <= keep_last
        and len(manifest_files) <= keep_last
        and artifacts_complete
        and manifests_valid
        and artifacts_match_rows
    )
    return passed, {
        "configured_keep_last": keep_last,
        "configured_checkpoint_dir": configured_dir,
        "current_rows": current_rows,
        "current_row_count": len(current_rows),
        "current_database_artifact_count": len(db_files),
        "current_manifest_artifact_count": len(manifest_files),
        "artifacts_match_current_rows": artifacts_match_rows,
        "excluded_rows": excluded_rows,
    }


def _checkpoint_directory_from_rows(
        rows: list[Any], *, run_id: str, configured_value: str) -> Path | None:
    configured = Path(configured_value)
    if configured.is_absolute():
        try:
            return configured.resolve()
        except (OSError, RuntimeError):
            return None

    candidates: set[Path] = set()
    for row in rows:
        tick = _strict_tick(row["tick"])
        raw_path = row["path"]
        if tick is None or type(raw_path) is not str:
            continue
        database = Path(raw_path)
        if not database.is_absolute() or database.name != f"{run_id}_t{tick}.db":
            continue
        try:
            resolved = database.resolve()
        except (OSError, RuntimeError):
            continue
        if str(database) != str(resolved):
            continue
        candidates.add(resolved.parent)
    return next(iter(candidates)) if len(candidates) == 1 else None


def _validate_checkpoint_artifact(
        database: Path, manifest: Path, *, run_id: str, tick: int) -> dict[str, Any]:
    """Check a finalized DB and its canonical runtime manifest by reading only."""
    errors: list[str] = []
    sqlite_evidence = _checkpoint_sqlite_integrity(database)
    if not database.is_file():
        errors.append("database_missing")
    if not manifest.is_file():
        errors.append("manifest_missing")
    if any(Path(f"{database}{suffix}").exists() for suffix in ("-wal", "-shm")):
        errors.append("sqlite_sidecar_present")
    if not sqlite_evidence["valid"]:
        errors.append("sqlite_integrity_failed")

    persisted: Any = None
    raw_manifest = b""
    if manifest.is_file():
        try:
            raw_manifest = manifest.read_bytes()
            persisted = json.loads(raw_manifest.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            errors.append("manifest_not_valid_json")
    if not isinstance(persisted, Mapping):
        if manifest.is_file() and "manifest_not_valid_json" not in errors:
            errors.append("manifest_not_an_object")
    else:
        try:
            canonical = canonical_json_bytes(persisted)
        except (TypeError, ValueError):
            errors.append("manifest_not_canonical")
        else:
            if raw_manifest != canonical:
                errors.append("manifest_not_canonical")
        if not _exact_value(
                persisted.get("schema_version"), CHECKPOINT_MANIFEST_VERSION):
            errors.append("manifest_schema_version_mismatch")
        if persisted.get("kind") != _CHECKPOINT_MANIFEST_KIND:
            errors.append("manifest_kind_mismatch")
        if persisted.get("database") != str(database):
            errors.append("manifest_database_binding_mismatch")
        try:
            database_hash = file_sha256(database) if database.is_file() else None
        except OSError:
            database_hash = None
        if not isinstance(database_hash, str) or persisted.get("database_sha256") != database_hash:
            errors.append("manifest_database_hash_mismatch")
        state = persisted.get("state")
        if (
                not isinstance(state, Mapping)
                or state.get("run_id") != run_id
                or not _exact_value(state.get("tick"), tick)):
            errors.append("manifest_state_binding_mismatch")
        if persisted.get("quick_check") != "ok":
            errors.append("manifest_quick_check_mismatch")

        # Rebuilding is safe only after the immutable integrity reader proved
        # this is a finalized DELETE-journal artifact with no sidecars.
        if sqlite_evidence["valid"] and not any(
                reason in errors for reason in ("database_missing", "sqlite_sidecar_present")):
            try:
                rebuilt = build_checkpoint_manifest(database)
            except (OSError, RuntimeError, ValueError, sqlite3.Error):
                errors.append("manifest_rebuild_failed")
            else:
                if dict(persisted) != rebuilt:
                    errors.append("manifest_does_not_match_artifact")

    return {
        "manifest_valid": not errors,
        "manifest_validation_errors": errors,
        "sqlite_artifact": {
            "quick_check": sqlite_evidence["quick_check"],
            "integrity_check": sqlite_evidence["integrity_check"],
            "foreign_key_violation_count": sqlite_evidence["foreign_key_violation_count"],
            "journal_mode": sqlite_evidence["journal_mode"],
        },
    }


def _checkpoint_sqlite_integrity(database: Path) -> dict[str, Any]:
    empty = {
        "valid": False,
        "quick_check": [],
        "integrity_check": [],
        "foreign_key_violation_count": 0,
        "journal_mode": None,
    }
    if not database.is_file():
        return empty
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(
            f"{database.as_uri()}?mode=ro&immutable=1", uri=True,
            isolation_level=None, cached_statements=0)
        quick_check = [str(row[0]) for row in connection.execute("PRAGMA quick_check")]
        integrity_check = [str(row[0]) for row in connection.execute("PRAGMA integrity_check")]
        foreign_key_violation_count = len(
            connection.execute("PRAGMA foreign_key_check").fetchall())
        journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        return {
            "valid": (
                quick_check == ["ok"]
                and integrity_check == ["ok"]
                and foreign_key_violation_count == 0
                and journal_mode == "delete"
            ),
            "quick_check": quick_check,
            "integrity_check": integrity_check,
            "foreign_key_violation_count": foreign_key_violation_count,
            "journal_mode": journal_mode,
        }
    except (OSError, sqlite3.Error, ValueError):
        return empty
    finally:
        if connection is not None:
            connection.close()


def _logical_checkpoint_directory(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    path = Path(value)
    if not path.is_absolute():
        return value
    return "<absolute>" if not path.name else f"<absolute>/{path.name}"


def _receipt_paths(output: Path) -> tuple[Path, Path]:
    suffix = output.suffix.lower()
    if suffix == ".json":
        return output, output.with_suffix(".md")
    if suffix == ".md":
        return output.with_suffix(".json"), output
    return output.with_name(output.name + ".json"), output.with_name(output.name + ".md")


def _empty_receipt(error: str) -> dict[str, Any]:
    checks = {name: False for name in _CHECK_NAMES}
    return {
        "schema_version": 1,
        "passed": False,
        "run": {"run_id": "", "seed": None, "status": "", "tick": None},
        "thresholds": dict(_THRESHOLDS),
        "checks": checks,
        "evidence": {"error": error},
        "unit_economics": [],
    }


def _query_error_evidence(exc: Exception, **context: Any) -> dict[str, Any]:
    return {**context, "error": type(exc).__name__}


def _integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        integer = int(value)
    except (TypeError, ValueError):
        return None
    return integer


def _exact_value(observed: Any, expected: Any) -> bool:
    """Compare persisted JSON values without Python's bool/int coercion."""
    return type(observed) is type(expected) and observed == expected


def _exact_settings_match(
        observed: Mapping[str, Any] | Any, expected: Mapping[str, Any]) -> bool:
    return (
        isinstance(observed, Mapping)
        and set(observed) == set(expected)
        and all(_exact_value(observed.get(name), value) for name, value in expected.items())
    )


def _event_firm_id(
        payload: Mapping[str, Any], subject_type: Any, subject_id: Any) -> int | None:
    if "firm_id" in payload:
        return _strict_entity_id(payload.get("firm_id"))
    return _strict_entity_id(subject_id) if subject_type == "firm" else None


def _terminal_event_precedes(
        terminal_event: Mapping[str, Any], merger_event: Mapping[str, Any]) -> bool:
    """Use persisted event order only for terminal-state timing."""
    terminal_tick = terminal_event["tick"]
    merger_tick = merger_event["tick"]
    if terminal_tick < merger_tick:
        return True
    if terminal_tick != merger_tick:
        return False
    terminal_id = _strict_entity_id(terminal_event.get("event_id"))
    merger_id = _strict_entity_id(merger_event.get("event_id"))
    return terminal_id is not None and merger_id is not None and terminal_id < merger_id


def _terminal_event_follows(
        terminal_event: Mapping[str, Any], merger_event: Mapping[str, Any]) -> bool:
    """Use persisted event order only for terminal-state timing."""
    terminal_tick = terminal_event["tick"]
    merger_tick = merger_event["tick"]
    if terminal_tick > merger_tick:
        return True
    if terminal_tick != merger_tick:
        return False
    terminal_id = _strict_entity_id(terminal_event.get("event_id"))
    merger_id = _strict_entity_id(merger_event.get("event_id"))
    return terminal_id is not None and merger_id is not None and terminal_id > merger_id


def _strict_entity_id(value: Any) -> int | None:
    return value if type(value) is int and value > 0 else None


def _strict_tick(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _nonnegative_integer(value: Any) -> int | None:
    integer = _integer(value)
    return integer if integer is not None and integer >= 0 else None


def _positive_integer(value: Any) -> int | None:
    integer = _integer(value)
    return integer if integer is not None and integer > 0 else None


def _ratio(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and 0.0 <= number <= 1.0 else None


def _json_scalar(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
