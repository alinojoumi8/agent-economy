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
        meta = store.get_meta()
    except Exception as exc:  # pragma: no cover - defensive corrupted-store path
        return _empty_receipt(f"run metadata could not be read: {type(exc).__name__}")
    if meta is None:
        return _empty_receipt("run metadata is missing")

    config = load_json(meta["config_json"], {})
    if not isinstance(config, Mapping):
        config = {}
    tick = _integer(meta["tick"])
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
    horizon_ok, horizon_evidence = _horizon_evidence(tick, status, active_tick)
    purchases_ok, purchases_evidence = _buy_goods_evidence(store, tick)
    unemployment_ok, unemployment_evidence = _unemployment_evidence(store, tick)
    unit_ok, unit_economics, recovery_goods_firms, unit_evidence = _unit_economics_evidence(
        store, activation_tick=_PROFILE_SETTINGS["activation_tick"]
    )
    insolvency_ok, insolvency_evidence = _insolvency_evidence(
        store, recovery_goods_firms, activation_tick=_PROFILE_SETTINGS["activation_tick"]
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
        tick: int | None, status: str, active_tick: Any) -> tuple[bool, dict[str, Any]]:
    passed = bool(
        tick is not None
        and tick >= _THRESHOLDS["minimum_ticks"]
        and status in _COMPLETED_STATUSES
        and active_tick is None
    )
    return passed, {
        "tick": tick,
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
            "WHERE action_type='buy_goods' AND tick BETWEEN ? AND ? "
            "ORDER BY tick,id",
            (warmup, tick),
        )
    except Exception as exc:  # pragma: no cover - defensive corrupted-store path
        return False, _query_error_evidence(exc, window_start=warmup, window_end=tick)

    counts_by_tick: dict[int, dict[str, int]] = {}
    malformed_rows = 0
    for row in rows:
        proposal_tick = _integer(row["tick"])
        if proposal_tick is None:
            malformed_rows += 1
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
            "SELECT id,tick,value FROM metrics WHERE name='unemployment' "
            "AND tick BETWEEN ? AND ? ORDER BY tick,id",
            (0, tick),
        )
    except Exception as exc:  # pragma: no cover - defensive corrupted-store path
        return False, _query_error_evidence(exc, window_start=0, window_end=tick)

    values: dict[int, float] = {}
    invalid_ticks: set[int] = set()
    malformed_rows = 0
    for row in rows:
        metric_tick = _integer(row["tick"])
        value = _ratio(row["value"])
        if metric_tick is None:
            malformed_rows += 1
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
        store: Store, *, activation_tick: int) -> tuple[
            bool, list[dict[str, Any]], dict[int, dict[str, Any]], dict[str, Any]]:
    """Validate every producer evidenced by product data or persisted events."""
    try:
        firms = store.query(
            "SELECT id,name,status,sector,product_json,bankrupt_tick FROM firms ORDER BY id"
        )
        producer_rows = store.query(
            "SELECT id,tick,kind,subject_id,payload_json FROM events "
            "WHERE kind IN ('production','goods_sale') AND tick>=? ORDER BY tick,id",
            (activation_tick,),
        )
        employment_rows = store.query(
            "SELECT id,firm_id,wage_cents,pay_interval_ticks FROM employments "
            "WHERE status='active' ORDER BY firm_id,id"
        )
    except Exception as exc:  # pragma: no cover - defensive corrupted-store path
        return False, [], {}, _query_error_evidence(exc)

    latest_production: dict[int, dict[str, Any]] = {}
    evidenced_firm_ids: set[int] = set()
    malformed_producer_events: list[dict[str, Any]] = []
    for row in producer_rows:
        payload = load_json(row["payload_json"], {})
        payload = payload if isinstance(payload, Mapping) else {}
        firm_id = _event_firm_id(payload, row["subject_id"])
        event_tick = _integer(row["tick"])
        event = {
            "event_id": _integer(row["id"]),
            "kind": str(row["kind"] or ""),
            "tick": event_tick,
            "firm_id": firm_id,
        }
        if firm_id is None or event_tick is None:
            malformed_producer_events.append(event)
            continue
        evidenced_firm_ids.add(firm_id)
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
    coverage_bps = _PROFILE_SETTINGS["gross_margin_coverage_bps"]
    wage_floor = _PROFILE_SETTINGS["wage_floor_cents"]
    for row in firms:
        firm_id = _integer(row["id"])
        if firm_id is None:
            continue
        product = load_json(row["product_json"], {})
        product = product if isinstance(product, Mapping) else {}
        output_per_worker = _positive_integer(product.get("output_per_worker"))
        status = str(row["status"] or "")
        if output_per_worker is None and firm_id not in evidenced_firm_ids:
            continue
        recovery_goods_firms[firm_id] = {
            "status": status,
            "bankrupt_tick": _integer(row["bankrupt_tick"]),
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
    return bool(passed and not malformed_producer_events), per_firm, recovery_goods_firms, {
        "active_recovery_managed_goods_firm_count": len(per_firm),
        "recovery_managed_goods_firm_count": len(recovery_goods_firms),
        "validated_firm_count": sum(firm["validated"] for firm in per_firm),
        "excluded_historical_goods_firms": excluded_historical_goods_firms,
        "malformed_producer_events": malformed_producer_events,
        "requires_persisted_product_production_and_active_employment": True,
    }


def _insolvency_evidence(
        store: Store, recovery_goods_firms: Mapping[int, Mapping[str, Any]], *,
        activation_tick: int) -> tuple[bool, dict[str, Any]]:
    """Reconcile recovery-goods firm terminal state to a persisted exit event."""
    try:
        rows = store.query(
            "SELECT id,tick,kind,subject_id,payload_json FROM events "
            "WHERE kind IN ('bankruptcy','merger_closed') AND tick>=? ORDER BY tick,id",
            (activation_tick,),
        )
    except Exception as exc:  # pragma: no cover - defensive corrupted-store path
        return False, _query_error_evidence(exc)

    bankruptcies_by_firm: dict[int, list[dict[str, Any]]] = {}
    acquisitions_by_firm: dict[int, list[dict[str, Any]]] = {}
    unparseable_bankruptcies: list[dict[str, Any]] = []
    unparseable_acquisitions: list[dict[str, Any]] = []
    for row in rows:
        payload = load_json(row["payload_json"], {})
        payload = payload if isinstance(payload, Mapping) else {}
        event_tick = _integer(row["tick"])
        event_id = _integer(row["id"])
        if row["kind"] == "bankruptcy":
            firm_id = _event_firm_id(payload, row["subject_id"])
            reason = payload.get("reason")
            event = {"event_id": event_id, "tick": event_tick, "firm_id": firm_id, "reason": reason}
            if firm_id is not None:
                bankruptcies_by_firm.setdefault(firm_id, []).append(event)
            if firm_id is None or event_tick is None or not isinstance(reason, str) or not reason.strip():
                unparseable_bankruptcies.append({
                    "event_id": event_id,
                    "tick": event_tick,
                    "firm_id": firm_id,
                })
        else:
            firm_id = _integer(payload.get("target_firm_id"))
            event = {"event_id": event_id, "tick": event_tick, "firm_id": firm_id}
            if firm_id is not None:
                acquisitions_by_firm.setdefault(firm_id, []).append(event)
            if firm_id is None or event_tick is None:
                unparseable_acquisitions.append(event)

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
        if status == "bankrupt":
            bankrupt_tick = _integer(state.get("bankrupt_tick"))
            events = bankruptcies_by_firm.get(firm_id, [])
            if bankrupt_tick is None:
                state_mismatches.append({
                    "firm_id": firm_id,
                    "reason": "missing_or_invalid_bankruptcy_tick",
                    "status": status,
                    "tick": None,
                })
                continue
            if not events:
                state_mismatches.append({
                    "firm_id": firm_id,
                    "reason": "missing_matching_bankruptcy_event",
                    "status": status,
                    "tick": bankrupt_tick,
                })
                continue
            at_bankruptcy_tick = [event for event in events if event["tick"] == bankrupt_tick]
            if not at_bankruptcy_tick:
                state_mismatches.append({
                    "firm_id": firm_id,
                    "reason": "bankruptcy_event_tick_mismatch",
                    "status": status,
                    "tick": bankrupt_tick,
                })
                continue
            valid_events = [
                event for event in at_bankruptcy_tick
                if isinstance(event["reason"], str) and event["reason"].strip()
            ]
            if not valid_events:
                state_mismatches.append({
                    "firm_id": firm_id,
                    "reason": "missing_or_invalid_bankruptcy_reason",
                    "status": status,
                    "tick": bankrupt_tick,
                })
                continue
            reason = str(valid_events[0]["reason"])
            if reason.strip().lower() != "insolvency":
                permitted_departures.append({
                    "firm_id": firm_id,
                    "kind": "bankruptcy",
                    "status": status,
                    "tick": bankrupt_tick,
                })
        elif status == "acquired":
            events = acquisitions_by_firm.get(firm_id, [])
            if not events:
                state_mismatches.append({
                    "firm_id": firm_id,
                    "reason": "missing_matching_acquisition_event",
                    "status": status,
                    "tick": None,
                })
                continue
            permitted_departures.append({
                "firm_id": firm_id,
                "kind": "acquisition",
                "status": status,
                "tick": events[0]["tick"],
            })

    return bool(
        not insolvencies
        and not unparseable_bankruptcies
        and not unparseable_acquisitions
        and not state_mismatches
    ), {
        "recovery_managed_goods_firm_ids": sorted(recovery_goods_firms),
        "recovery_managed_insolvencies": insolvencies,
        "unparseable_bankruptcies": unparseable_bankruptcies,
        "unparseable_acquisitions": unparseable_acquisitions,
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
            "excluded_rows": [],
            "error": "checkpoint directory cannot be reconstructed from persisted rows",
        }

    current_rows: list[dict[str, Any]] = []
    excluded_rows: list[dict[str, Any]] = []
    expected_db_paths: set[Path] = set()
    expected_manifest_paths: set[Path] = set()
    for row in rows:
        tick = _integer(row["tick"])
        row_id = _integer(row["id"])
        if tick is None:
            excluded_rows.append({"checkpoint_id": row_id, "reason": "invalid_tick"})
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
        tick = _integer(row["tick"])
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
    return isinstance(observed, Mapping) and all(
        _exact_value(observed.get(name), value) for name, value in expected.items()
    )


def _event_firm_id(payload: Mapping[str, Any], subject_id: Any) -> int | None:
    firm_id = _integer(payload.get("firm_id"))
    return firm_id if firm_id is not None else _integer(subject_id)


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
