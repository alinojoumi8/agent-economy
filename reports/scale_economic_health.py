#!/usr/bin/env python3
"""Immutable economic-health evaluation for the maintained scale-270 lanes."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
from typing import Any

from engine.ledger import Ledger
from engine.schema import SchemaCompatibilityError, assert_schema_compatible
from engine.store import Store
from reports import supply_recovery
from run_config import load_config
from scripts.run_scale_validation import ReceiptSafetyError, validate_receipt_safety
from world.replay_verify import verify_replay


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "agent-economy-scale-economic-health-v1"
AB_SCHEMA = "agent-economy-scale-ab-v1"
RUNTIME_SCHEMA = "agent-economy-scale-validation-v1"
SQLITE_SIDECARS = ("-wal", "-shm", "-journal")
COMPLETED_STATUSES = {"finished", "paused"}
EXPECTED_POPULATION = {
    "agents": 308,
    "alive": 308,
    "citizen_kind": 272,
    "staff_kind": 36,
    "core": 100,
    "periphery": 208,
    "regions": {"ironvale": 69, "northstar": 184, "suncoast": 55},
}
PROFILE_CONTRACTS = {
    "runs/acceptance/scale-270-baseline-120.yaml": {
        "required_ticks": 120,
        "diagnostic": True,
        "recovery_enabled": False,
    },
    "runs/acceptance/scale-270-recovery-120.yaml": {
        "required_ticks": 120,
        "diagnostic": True,
        "recovery_enabled": True,
    },
    "runs/acceptance/scale-270-recovery-1000.yaml": {
        "required_ticks": 1000,
        "diagnostic": False,
        "recovery_enabled": True,
    },
}
CHECK_NAMES = (
    "runtime_receipt_safe",
    "identity_exact",
    "horizon_completed",
    "population_exact",
    "communications_exact",
    "provider_and_spend_exact",
    "purchase_windows_healthy",
    "unemployment_rebound_bounded",
    "unemployment_final_mean_not_worse",
    "production_and_inventory_healthy",
    "unit_economics_valid",
    "managed_insolvency_absent",
    "labor_backlog_bounded",
    "employment_currency_and_terms_valid",
    "ledger_reconciles",
    "sqlite_integrity",
    "checkpoints_valid",
    "exact_replay",
    "source_immutable",
    "resources_within_caps",
)
ECONOMIC_CHECKS = frozenset({
    "purchase_windows_healthy",
    "unemployment_rebound_bounded",
    "unemployment_final_mean_not_worse",
    "production_and_inventory_healthy",
    "unit_economics_valid",
    "managed_insolvency_absent",
    "labor_backlog_bounded",
    "employment_currency_and_terms_valid",
})
OPERATIONAL_CHECKS = frozenset(CHECK_NAMES) - ECONOMIC_CHECKS
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")


def _canonical_json(value: object) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    )


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_mapping(value: object) -> dict[str, Any] | None:
    return dict(value) if isinstance(value, Mapping) else None


def _load_json_mapping(raw: object) -> dict[str, Any] | None:
    if not isinstance(raw, str):
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return _json_mapping(value)


def _strict_int(value: object, *, minimum: int | None = None) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if minimum is not None and value < minimum:
        return None
    return value


def _finite_number(value: object, *, minimum: float | None = None) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or (minimum is not None and number < minimum):
        return None
    return number


def _percentile_95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return ordered[index]


def _sidecars(path: Path) -> list[str]:
    return [suffix for suffix in SQLITE_SIDECARS if Path(f"{path}{suffix}").exists()]


def _immutable_connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(
        f"{path.resolve().as_uri()}?mode=ro&immutable=1",
        uri=True,
        isolation_level=None,
        cached_statements=0,
    )
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        assert_schema_compatible(connection)
        return connection
    except BaseException:
        connection.close()
        raise


def _store_view(path: Path, connection: sqlite3.Connection) -> Store:
    store = Store.__new__(Store)
    store.path = str(path.resolve())
    store.read_only = True
    store._closed = False
    store.conn = connection
    return store


def _empty_receipt(error: str) -> dict[str, Any]:
    checks = {name: False for name in CHECK_NAMES}
    return {
        "schema": SCHEMA,
        "schema_version": 1,
        "outcome": "failed",
        "passed": False,
        "profile": {
            "path": None,
            "required_ticks": None,
            "diagnostic": False,
            "recovery_enabled": None,
            "policy_version": None,
            "profile_config_sha256": None,
            "effective_config_sha256": None,
            "source_commit": None,
        },
        "run": {
            "run_id": None,
            "replay_run_id": None,
            "seed": None,
            "engine_semantics_version": None,
            "status": None,
            "tick": None,
            "active_tick": None,
        },
        "thresholds": {},
        "checks": checks,
        "check_groups": {
            "economic": sorted(ECONOMIC_CHECKS),
            "operational": sorted(OPERATIONAL_CHECKS),
        },
        "population": {},
        "evidence": {"evaluation": {"error": error}},
        "runtime": {
            "effective_config_sha256": None,
            "effective_config": {},
            "source_sha256": None,
            "replay_proof": {},
        },
    }


def _read_runtime(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        raw = path.read_text(encoding="utf-8")
        value = json.loads(raw)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return None, "runtime receipt is missing or invalid JSON"
    if not isinstance(value, Mapping):
        return None, "runtime receipt root is not an object"
    return dict(value), None


def _semantic_config(config: Mapping[str, Any]) -> dict[str, Any]:
    normalized = deepcopy(dict(config))
    normalized.pop("checkpoint_dir", None)
    normalized.pop("report_dir", None)
    return normalized


def _thresholds(config: Mapping[str, Any]) -> dict[str, Any] | None:
    acceptance = _json_mapping(config.get("acceptance"))
    scale = _json_mapping(acceptance.get("scale_economic_health")) if acceptance else None
    if scale is None:
        return None
    expected_types = {
        "schema_version": int,
        "required_ticks": int,
        "warmup_ticks": int,
        "trailing_window_ticks": int,
        "max_buy_goods_rejection_rate": (int, float),
        "max_unemployment_rebound": (int, float),
        "max_pending_applications": int,
        "max_pending_job_offers": int,
        "max_open_jobs": int,
        "max_peak_rss_mb": (int, float),
        "min_available_memory_gb": (int, float),
        "max_database_growth_bytes_per_tick": int,
        "max_checkpoint_p95_seconds": (int, float),
    }
    if set(scale) != set(expected_types):
        return None
    for name, kind in expected_types.items():
        value = scale.get(name)
        if isinstance(value, bool) or not isinstance(value, kind):
            return None
    return dict(scale)


def _identity_evidence(
    runtime: Mapping[str, Any], source_meta: sqlite3.Row,
    replay_meta: sqlite3.Row, persisted_config: Mapping[str, Any],
) -> tuple[bool, dict[str, Any], dict[str, Any] | None, dict[str, Any] | None]:
    profile_path = runtime.get("profile_path")
    contract = PROFILE_CONTRACTS.get(profile_path) if isinstance(profile_path, str) else None
    expected_config: dict[str, Any] | None = None
    profile_file_hash: str | None = None
    if contract is not None:
        profile = (ROOT / str(profile_path)).resolve()
        try:
            if profile.is_file() and profile.is_relative_to((ROOT / "runs").resolve()):
                expected_config = load_config(profile)
                profile_file_hash = _file_hash(profile)
        except (OSError, RuntimeError, ValueError):
            expected_config = None

    effective_config = _json_mapping(runtime.get("effective_config"))
    effective_hash = runtime.get("effective_config_sha256")
    profile_config_hash = runtime.get("profile_config_sha256")
    source_section = _json_mapping(runtime.get("source")) or {}
    replay_section = _json_mapping(runtime.get("replay")) or {}
    configuration = _json_mapping(runtime.get("configuration")) or {}
    thresholds = _thresholds(persisted_config)
    required_ticks = contract.get("required_ticks") if contract else None
    source_commit = runtime.get("source_commit")
    checks = {
        "runtime_schema": (
            runtime.get("schema") == RUNTIME_SCHEMA
            and runtime.get("schema_version") == 1
        ),
        "known_profile": contract is not None and expected_config is not None,
        "profile_file_hash": profile_file_hash is not None
        and runtime.get("profile_sha256") == profile_file_hash,
        "profile_config_hash": expected_config is not None
        and profile_config_hash == _canonical_hash(expected_config),
        "effective_config_hash": effective_config is not None
        and effective_hash == _canonical_hash(effective_config),
        "persisted_config_matches_profile": expected_config is not None
        and _semantic_config(persisted_config) == _semantic_config(expected_config),
        "effective_config_matches_persisted": effective_config is not None
        and _semantic_config(effective_config) == _semantic_config(persisted_config),
        "threshold_contract": thresholds is not None
        and thresholds.get("required_ticks") == required_ticks,
        "source_identity": (
            source_section.get("run_id") == source_meta["run_id"]
            and source_section.get("status") == source_meta["status"]
            and source_section.get("tick") == source_meta["tick"]
            and source_section.get("active_tick") == source_meta["active_tick"]
        ),
        "replay_identity": replay_section.get("run_id") == replay_meta["run_id"],
        "seed": expected_config is not None
        and source_meta["seed"] == replay_meta["seed"] == expected_config.get("seed"),
        "semantics": expected_config is not None
        and persisted_config.get("engine_semantics_version")
        == expected_config.get("engine_semantics_version") == 7,
        "runtime_ticks": configuration.get("ticks") == required_ticks,
        "source_commit": isinstance(source_commit, str)
        and _COMMIT.fullmatch(source_commit) is not None,
    }
    return all(checks.values()), {
        "checks": checks,
        "profile_path": profile_path if isinstance(profile_path, str) else None,
        "source_run_id": str(source_meta["run_id"]),
        "replay_run_id": str(replay_meta["run_id"]),
        "profile_config_sha256": profile_config_hash,
        "effective_config_sha256": effective_hash,
        "source_commit": source_commit if isinstance(source_commit, str) else None,
    }, contract, thresholds


def _population_evidence(connection: sqlite3.Connection) -> tuple[bool, dict[str, Any]]:
    observed = {
        "agents": int(connection.execute("SELECT COUNT(*) FROM agents").fetchone()[0]),
        "alive": int(connection.execute(
            "SELECT COUNT(*) FROM agents WHERE alive=1").fetchone()[0]),
        "citizen_kind": int(connection.execute(
            "SELECT COUNT(*) FROM agents WHERE kind='citizen'").fetchone()[0]),
        "staff_kind": int(connection.execute(
            "SELECT COUNT(*) FROM agents WHERE kind='staff'").fetchone()[0]),
        "core": int(connection.execute(
            "SELECT COUNT(*) FROM agents WHERE population_tier='core'").fetchone()[0]),
        "periphery": int(connection.execute(
            "SELECT COUNT(*) FROM agents WHERE population_tier='periphery'").fetchone()[0]),
        "regions": {
            str(row["region_key"]): int(row["n"])
            for row in connection.execute(
                "SELECT r.region_key,COUNT(a.id) AS n FROM regions r "
                "LEFT JOIN agents a ON a.region_id=r.id "
                "GROUP BY r.id ORDER BY r.region_key")
        },
    }
    invalid_tiers = int(connection.execute(
        "SELECT COUNT(*) FROM agents WHERE population_tier NOT IN ('core','periphery')"
    ).fetchone()[0])
    missing_regions = int(connection.execute(
        "SELECT COUNT(*) FROM agents WHERE region_id IS NULL"
    ).fetchone()[0])
    return observed == EXPECTED_POPULATION and invalid_tiers == 0 and missing_regions == 0, {
        "expected": deepcopy(EXPECTED_POPULATION),
        "observed": observed,
        "invalid_tiers": invalid_tiers,
        "missing_regions": missing_regions,
    }


def _communications_evidence(
    connection: sqlite3.Connection, runtime: Mapping[str, Any], ticks: int,
    config: Mapping[str, Any],
) -> tuple[bool, dict[str, Any]]:
    rows = connection.execute(
        "SELECT id,participant_ids FROM conversations ORDER BY id").fetchall()
    participants: dict[int, set[int]] = {}
    malformed = 0
    for row in rows:
        try:
            values = json.loads(row["participant_ids"])
            member_ids = {int(value) for value in values}
            if len(values) != 2 or len(member_ids) != 2:
                raise ValueError
            participants[int(row["id"])] = member_ids
        except (TypeError, ValueError, json.JSONDecodeError):
            malformed += 1
    counts: dict[int, int] = {}
    invalid_memberships = 0
    empty_messages = 0
    for row in connection.execute(
            "SELECT conv_id,agent_id,text FROM messages ORDER BY id"):
        conversation_id = int(row["conv_id"])
        counts[conversation_id] = counts.get(conversation_id, 0) + 1
        invalid_memberships += int(
            int(row["agent_id"]) not in participants.get(conversation_id, set()))
        empty_messages += int(not str(row["text"] or "").strip())
    observed = {
        "conversations": len(rows),
        "messages": sum(counts.values()),
        "unique_participants": len(set().union(*participants.values())) if participants else 0,
        "invalid_message_memberships": invalid_memberships,
        "empty_messages": empty_messages,
        "message_count_per_conversation": sorted(set(counts.values())),
    }
    budget = _json_mapping(config.get("budget")) or {}
    conversations = _json_mapping(config.get("conversations")) or {}
    pairs = _strict_int(budget.get("conversation_pairs"), minimum=1)
    turns = _strict_int(conversations.get("turns"), minimum=1)
    expected_conversations = ticks * pairs if pairs is not None else None
    expected_messages = (
        expected_conversations * turns
        if expected_conversations is not None and turns is not None else None)
    runtime_observed = _json_mapping(runtime.get("communications"))
    passed = bool(
        malformed == 0
        and pairs is not None
        and turns is not None
        and observed["conversations"] == expected_conversations
        and observed["messages"] == expected_messages
        and observed["invalid_message_memberships"] == 0
        and observed["empty_messages"] == 0
        and observed["message_count_per_conversation"] == [turns]
        and runtime_observed == observed
    )
    return passed, {
        "observed": observed,
        "runtime_observed": runtime_observed,
        "expected_conversations": expected_conversations,
        "expected_messages": expected_messages,
        "malformed_conversations": malformed,
    }


def _provider_evidence(
    connection: sqlite3.Connection, runtime: Mapping[str, Any],
    config: Mapping[str, Any],
) -> tuple[bool, dict[str, Any]]:
    pairs = [dict(row) for row in connection.execute(
        "SELECT provider,model,COUNT(*) AS calls,"
        "COALESCE(SUM(in_tokens),0) AS in_tokens,"
        "COALESCE(SUM(out_tokens),0) AS out_tokens,"
        "COALESCE(SUM(cached),0) AS cached_calls,"
        "COALESCE(SUM(cost_usd),0) AS cost_usd "
        "FROM llm_calls GROUP BY provider,model ORDER BY provider,model")]
    calls = int(connection.execute("SELECT COUNT(*) FROM llm_calls").fetchone()[0])
    spend = float(connection.execute(
        "SELECT COALESCE(SUM(cost_usd),0) FROM llm_calls").fetchone()[0])
    purposes = {
        str(row["purpose"]): int(row["calls"])
        for row in connection.execute(
            "SELECT purpose,COUNT(*) AS calls FROM llm_calls "
            "GROUP BY purpose ORDER BY purpose")
    }
    observed = {"calls": calls, "cost_usd": spend, "pairs": pairs, "purposes": purposes}
    llm = _json_mapping(config.get("llm")) or {}
    route = _json_mapping(llm.get("route_contract")) or _json_mapping(llm.get("default_route"))
    expected_pair = (
        {(str(route.get("provider")), str(route.get("model")))} if route else set())
    observed_pairs = {(str(row["provider"]), str(row["model"])) for row in pairs}
    budget = _json_mapping(config.get("budget")) or {}
    cap = _finite_number(budget.get("cap_usd"), minimum=0)
    scripted = expected_pair == {("scripted", "scripted")}
    spend_ok = (
        spend == 0.0 if scripted
        else cap is not None and spend > 0.0 and spend <= cap
    )
    runtime_observed = _json_mapping(runtime.get("providers"))
    governor = _json_mapping(runtime.get("governor")) or {}
    governor_spend = _finite_number(governor.get("total_spend_usd"), minimum=0)
    return bool(
        calls > 0
        and expected_pair
        and observed_pairs == expected_pair
        and spend_ok
        and runtime_observed == observed
        and governor_spend == spend
    ), {
        "observed": observed,
        "runtime_observed": runtime_observed,
        "expected_pair": [list(item) for item in sorted(expected_pair)],
        "hard_cap_usd": cap,
        "scripted_provider_free": scripted,
        "governor_spend_usd": governor_spend,
    }


def _purchase_evidence(
    connection: sqlite3.Connection, ticks: int, thresholds: Mapping[str, Any],
) -> tuple[bool, dict[str, Any]]:
    warmup = int(thresholds["warmup_ticks"])
    window = int(thresholds["trailing_window_ticks"])
    maximum = float(thresholds["max_buy_goods_rejection_rate"])
    first_end = warmup + window - 1
    counts: dict[int, dict[str, int]] = {}
    malformed: list[dict[str, Any]] = []
    for row in connection.execute(
            "SELECT id,tick,validation_status FROM action_proposals "
            "WHERE action_type='buy_goods' ORDER BY tick,id"):
        tick = _strict_int(row["tick"], minimum=0)
        if tick is None:
            malformed.append({"proposal_id": row["id"], "tick": row["tick"]})
            continue
        if tick < warmup or tick > ticks:
            continue
        bucket = counts.setdefault(tick, {"attempts": 0, "rejected": 0, "unresolved": 0})
        status = row["validation_status"]
        if status in {"accepted", "rejected"}:
            bucket["attempts"] += 1
            bucket["rejected"] += int(status == "rejected")
        else:
            bucket["unresolved"] += 1
    windows: list[dict[str, Any]] = []
    for end in range(first_end, ticks + 1):
        start = end - window + 1
        attempts = sum(counts.get(tick, {}).get("attempts", 0) for tick in range(start, end + 1))
        rejected = sum(counts.get(tick, {}).get("rejected", 0) for tick in range(start, end + 1))
        unresolved = sum(counts.get(tick, {}).get("unresolved", 0) for tick in range(start, end + 1))
        rate = rejected / attempts if attempts else None
        passed = bool(attempts and unresolved == 0 and rate is not None and rate <= maximum)
        windows.append({
            "start_tick": start,
            "end_tick": end,
            "attempts": attempts,
            "rejected": rejected,
            "unresolved": unresolved,
            "rate": round(rate, 6) if rate is not None else None,
            "passed": passed,
        })
    passed = bool(windows and not malformed and all(row["passed"] for row in windows))
    worst = max(
        windows,
        key=lambda row: (
            not row["passed"], row["unresolved"], row["rate"] or 0.0,
            -row["end_tick"]),
    ) if windows else None
    return passed, {
        "warmup_ticks": warmup,
        "window_ticks": window,
        "maximum_rate": maximum,
        "windows_evaluated": len(windows),
        "latest_window": windows[-1] if windows else None,
        "worst_window": worst,
        "failed_window_count": sum(not row["passed"] for row in windows),
        "malformed_proposals": malformed,
    }


def _unemployment_evidence(
    connection: sqlite3.Connection, ticks: int, thresholds: Mapping[str, Any],
) -> tuple[bool, bool, dict[str, Any]]:
    window = int(thresholds["trailing_window_ticks"])
    maximum = float(thresholds["max_unemployment_rebound"])
    values: dict[int, float] = {}
    duplicates: list[int] = []
    invalid: list[dict[str, Any]] = []
    for row in connection.execute(
            "SELECT id,tick,value FROM metrics WHERE name='unemployment' ORDER BY tick,id"):
        tick = _strict_int(row["tick"], minimum=0)
        value = _finite_number(row["value"], minimum=0)
        if tick is None or value is None or value > 1.0:
            invalid.append({"metric_id": row["id"], "tick": row["tick"], "value": row["value"]})
            continue
        if tick in values:
            duplicates.append(tick)
        values[tick] = value
    required = list(range(1, ticks + 1))
    missing = [tick for tick in required if tick not in values]
    windows: list[dict[str, Any]] = []
    for end in range(window * 2, ticks + 1):
        preceding_ticks = range(end - 2 * window + 1, end - window + 1)
        trailing_ticks = range(end - window + 1, end + 1)
        required_ticks = [*preceding_ticks, *trailing_ticks]
        if any(tick not in values for tick in required_ticks):
            windows.append({
                "preceding_window": [end - 2 * window + 1, end - window],
                "trailing_window": [end - window + 1, end],
                "preceding_trough": None,
                "trailing_peak": None,
                "rebound": None,
                "passed": False,
            })
            continue
        trough = min(values[tick] for tick in preceding_ticks)
        peak = max(values[tick] for tick in trailing_ticks)
        rebound = peak - trough
        windows.append({
            "preceding_window": [end - 2 * window + 1, end - window],
            "trailing_window": [end - window + 1, end],
            "preceding_trough": round(trough, 6),
            "trailing_peak": round(peak, 6),
            "rebound": round(rebound, 6),
            "passed": rebound <= maximum,
        })
    first_values = [values[tick] for tick in range(1, window + 1) if tick in values]
    final_values = [values[tick] for tick in range(ticks - window + 1, ticks + 1) if tick in values]
    first_mean = sum(first_values) / window if len(first_values) == window else None
    final_mean = sum(final_values) / window if len(final_values) == window else None
    rebound_passed = bool(
        windows and not invalid and not duplicates and not missing
        and all(row["passed"] for row in windows))
    mean_passed = bool(
        first_mean is not None and final_mean is not None
        and final_mean <= first_mean)
    return rebound_passed, mean_passed, {
        "window_ticks": window,
        "maximum_rebound": maximum,
        "windows_evaluated": len(windows),
        "latest_window": windows[-1] if windows else None,
        "worst_window": max(
            windows,
            key=lambda row: (not row["passed"], row["rebound"] or 0.0, -row["trailing_window"][1]),
        ) if windows else None,
        "failed_window_count": sum(not row["passed"] for row in windows),
        "first_window_mean": round(first_mean, 6) if first_mean is not None else None,
        "final_window_mean": round(final_mean, 6) if final_mean is not None else None,
        "missing_ticks": missing,
        "duplicate_ticks": sorted(set(duplicates)),
        "invalid_rows": invalid,
    }


def _event_payload(raw: object) -> dict[str, Any]:
    return _load_json_mapping(raw) or {}


def _positive_event_int(value: object) -> int | None:
    return _strict_int(value, minimum=1)


def _production_inventory_evidence(
    connection: sqlite3.Connection, ticks: int, thresholds: Mapping[str, Any],
) -> tuple[bool, dict[str, Any]]:
    window = int(thresholds["trailing_window_ticks"])
    start = ticks - window + 1
    firms: dict[int, dict[str, Any]] = {}
    firm_rows = connection.execute(
        "SELECT id,name,status,inventory,product_json FROM firms ORDER BY id")
    known_firm_ids: set[int] = set()
    for row in firm_rows:
        known_firm_ids.add(int(row["id"]))
        product = _event_payload(row["product_json"])
        output = _strict_int(product.get("output_per_worker"), minimum=1)
        if row["status"] in {"private", "listed"} and output is not None:
            firms[int(row["id"])] = {
                "firm_id": int(row["id"]),
                "name": str(row["name"]),
                "terminal_inventory": _strict_int(row["inventory"], minimum=0),
                "production_units": 0,
                "accepted_sale_units": 0,
                "production_events": 0,
                "sale_events": 0,
                "malformed_events": [],
            }
    orphan_events: list[dict[str, Any]] = []
    for row in connection.execute(
            "SELECT id,tick,kind,subject_type,subject_id,payload_json FROM events "
            "WHERE kind IN ('production','goods_sale') AND tick BETWEEN ? AND ? "
            "ORDER BY tick,id", (start, ticks)):
        payload = _event_payload(row["payload_json"])
        firm_id = _strict_int(payload.get("firm_id"), minimum=1)
        if firm_id is None and row["subject_type"] == "firm":
            firm_id = _strict_int(row["subject_id"], minimum=1)
        if firm_id not in firms:
            if firm_id in known_firm_ids:
                continue
            orphan_events.append({
                "event_id": int(row["id"]), "kind": str(row["kind"]),
                "firm_id": firm_id, "tick": row["tick"],
            })
            continue
        evidence = firms[firm_id]
        field = "units" if row["kind"] == "production" else "qty"
        units = _positive_event_int(payload.get(field))
        if units is None:
            evidence["malformed_events"].append({
                "event_id": int(row["id"]), "kind": str(row["kind"]),
                "tick": row["tick"],
            })
            continue
        if row["kind"] == "production":
            evidence["production_events"] += 1
            evidence["production_units"] += units
        else:
            evidence["sale_events"] += 1
            evidence["accepted_sale_units"] += units
    rows = []
    for firm_id in sorted(firms):
        row = firms[firm_id]
        inventory_nonzero_evidenced = bool(
            row["terminal_inventory"] is not None
            and (row["terminal_inventory"] > 0 or row["production_units"] > 0))
        row["inventory_nonzero_evidenced"] = inventory_nonzero_evidenced
        row["passed"] = bool(
            row["production_events"] > 0
            and row["production_units"] >= row["accepted_sale_units"]
            and inventory_nonzero_evidenced
            and not row["malformed_events"]
        )
        rows.append(row)
    return bool(rows and not orphan_events and all(row["passed"] for row in rows)), {
        "final_window": [start, ticks],
        "active_goods_firms": rows,
        "orphan_goods_events": orphan_events,
    }


def _labor_evidence(
    connection: sqlite3.Connection, thresholds: Mapping[str, Any],
) -> tuple[bool, dict[str, Any]]:
    observed = {
        "open_jobs": int(connection.execute(
            "SELECT COUNT(*) FROM jobs WHERE status='open'").fetchone()[0]),
        "pending_applications": int(connection.execute(
            "SELECT COUNT(*) FROM applications WHERE state='pending'").fetchone()[0]),
        "pending_job_offers": int(connection.execute(
            "SELECT COUNT(*) FROM job_offers WHERE status='pending'").fetchone()[0]),
    }
    limits = {
        "open_jobs": int(thresholds["max_open_jobs"]),
        "pending_applications": int(thresholds["max_pending_applications"]),
        "pending_job_offers": int(thresholds["max_pending_job_offers"]),
    }
    return all(observed[name] <= limits[name] for name in limits), {
        **observed,
        "limits": limits,
    }


def _employment_evidence(connection: sqlite3.Connection) -> tuple[bool, dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in connection.execute(
            "SELECT e.id,e.agent_id,e.firm_id,e.wage_cents,e.pay_interval_ticks,"
            "f.currency_code AS firm_currency,a.currency_code AS employee_currency "
            "FROM employments e JOIN firms f ON f.id=e.firm_id "
            "JOIN agents g ON g.id=e.agent_id "
            "LEFT JOIN accounts a ON a.id=g.checking_account_id "
            "WHERE e.status='active' ORDER BY e.id"):
        wage = _strict_int(row["wage_cents"], minimum=1)
        interval = _strict_int(row["pay_interval_ticks"], minimum=1)
        firm_currency = str(row["firm_currency"] or "")
        employee_currency = str(row["employee_currency"] or "")
        valid = bool(
            wage is not None and interval is not None
            and firm_currency and employee_currency == firm_currency)
        rows.append({
            "employment_id": int(row["id"]),
            "agent_id": int(row["agent_id"]),
            "firm_id": int(row["firm_id"]),
            "wage_cents": wage,
            "pay_interval_ticks": interval,
            "firm_currency": firm_currency,
            "employee_currency": employee_currency or None,
            "passed": valid,
        })
    return bool(rows and all(row["passed"] for row in rows)), {
        "active_employments": rows,
        "active_employment_count": len(rows),
    }


def _sqlite_evidence(
    source: sqlite3.Connection, replay: sqlite3.Connection,
    source_sidecars: list[str], replay_sidecars: list[str],
) -> tuple[bool, dict[str, Any]]:
    evidence: dict[str, Any] = {
        "source_sidecars": source_sidecars,
        "replay_sidecars": replay_sidecars,
    }
    passed = not source_sidecars and not replay_sidecars
    for name, connection in (("source", source), ("replay", replay)):
        quick = [str(row[0]) for row in connection.execute("PRAGMA quick_check")]
        integrity = [str(row[0]) for row in connection.execute("PRAGMA integrity_check")]
        foreign = [dict(row) for row in connection.execute("PRAGMA foreign_key_check")]
        evidence[name] = {
            "quick_check": quick,
            "integrity_check": integrity,
            "foreign_key_violations": foreign,
        }
        passed = passed and quick == ["ok"] and integrity == ["ok"] and not foreign
    return bool(passed), evidence


def _ledger_evidence(store: Store) -> tuple[bool, dict[str, Any]]:
    try:
        return Ledger(store).reconcile()
    except (sqlite3.Error, TypeError, ValueError) as exc:
        return False, {"error": f"ledger reconciliation failed: {type(exc).__name__}"}


def _checkpoint_evidence(
    store: Store, runtime: Mapping[str, Any], run_id: str, ticks: int,
    config: Mapping[str, Any],
) -> tuple[bool, dict[str, Any]]:
    artifact_ok, artifact_evidence = supply_recovery._checkpoint_evidence(
        store, run_id, config)
    rows = artifact_evidence.get("current_rows", [])
    terminal_rows = [row for row in rows if row.get("tick") == ticks]
    runtime_section = _json_mapping(runtime.get("runtime")) or {}
    runtime_rows = runtime_section.get("checkpoints")
    runtime_rows = runtime_rows if isinstance(runtime_rows, list) else []
    runtime_terminal = [
        row for row in runtime_rows
        if isinstance(row, Mapping) and row.get("tick") == ticks
    ]
    durations = [
        value
        for row in runtime_rows if isinstance(row, Mapping)
        if (value := _finite_number(row.get("duration_s"), minimum=0)) is not None
    ]
    runtime_rows_valid = bool(
        runtime_rows
        and len(durations) == len(runtime_rows)
        and all(
            isinstance(row, Mapping)
            and isinstance(row.get("artifact"), str)
            and isinstance(row.get("manifest_artifact"), str)
            for row in runtime_rows
        )
    )
    keep_last = _strict_int(config.get("checkpoint_keep_last"), minimum=1)
    passed = bool(
        artifact_ok
        and keep_last is not None
        and len(rows) == keep_last
        and len(terminal_rows) == 1
        and len(runtime_terminal) >= 1
        and runtime_rows_valid
    )
    return passed, {
        **artifact_evidence,
        "terminal_tick": ticks,
        "terminal_catalog_rows": len(terminal_rows),
        "terminal_runtime_records": len(runtime_terminal),
        "runtime_record_count": len(runtime_rows),
        "runtime_records_valid": runtime_rows_valid,
        "required_retained_rows": keep_last,
        "checkpoint_p95_seconds": _percentile_95(durations),
    }


def _artifact_root(database: Path, artifact: object) -> Path | None:
    if not isinstance(artifact, str):
        return None
    logical = Path(artifact)
    if logical.is_absolute() or not logical.parts or ".." in logical.parts:
        return None
    candidate = database.resolve()
    for _ in logical.parts:
        candidate = candidate.parent
    try:
        return candidate if (candidate / logical).resolve() == database.resolve() else None
    except (OSError, RuntimeError, ValueError):
        return None


def _manifest_evidence(
    manifest: object, *, root: Path | None,
) -> tuple[bool, dict[str, Any]]:
    if root is None or not isinstance(manifest, list):
        return False, {"entries": 0, "error": "artifact root or manifest is invalid"}
    observed: list[dict[str, Any]] = []
    passed = True
    names: set[str] = set()
    for raw in manifest:
        if not isinstance(raw, Mapping):
            passed = False
            continue
        artifact = raw.get("artifact")
        if not isinstance(artifact, str) or artifact in names:
            passed = False
            continue
        names.add(artifact)
        logical = Path(artifact)
        if logical.is_absolute() or ".." in logical.parts:
            passed = False
            observed.append({"artifact": artifact, "valid": False})
            continue
        path = (root / logical).resolve()
        try:
            safe = path.is_relative_to(root.resolve())
        except (OSError, RuntimeError, ValueError):
            safe = False
        expected_present = raw.get("present") is True
        actual_present = path.is_file()
        size = path.stat().st_size if actual_present else 0
        digest = _file_hash(path) if actual_present else None
        valid = bool(
            safe
            and isinstance(raw.get("present"), bool)
            and expected_present == actual_present
            and raw.get("bytes") == size
            and raw.get("sha256") == digest
        )
        passed = passed and valid
        observed.append({
            "artifact": artifact,
            "present": actual_present,
            "bytes": size,
            "sha256": digest,
            "valid": valid,
        })
    return bool(passed and observed), {"entries": len(observed), "observed": observed}


def _replay_and_source_evidence(
    source_path: Path, replay_path: Path, runtime: Mapping[str, Any],
) -> tuple[bool, bool, dict[str, Any]]:
    source_section = _json_mapping(runtime.get("source")) or {}
    replay_section = _json_mapping(runtime.get("replay")) or {}
    source_hash = _file_hash(source_path)
    proof = verify_replay(source_path, replay_path)
    runtime_proof = _json_mapping(replay_section.get("proof"))
    source_before = source_section.get("artifact_manifest_before_replay")
    source_after = source_section.get("artifact_manifest_after_replay")
    replay_manifest = replay_section.get("artifact_manifest")
    source_root = _artifact_root(source_path, source_section.get("database"))
    replay_root = _artifact_root(replay_path, replay_section.get("database"))
    source_before_ok, source_before_evidence = _manifest_evidence(
        source_before, root=source_root)
    source_after_ok, source_after_evidence = _manifest_evidence(
        source_after, root=source_root)
    replay_manifest_ok, replay_manifest_evidence = _manifest_evidence(
        replay_manifest, root=replay_root)
    execution = _json_mapping(replay_section.get("execution")) or {}
    exact = bool(
        proof.get("exact") is True
        and proof.get("differences") == []
        and runtime_proof == proof
        and execution.get("live_dispatch_count") == 0
        and replay_manifest_ok
    )
    immutable = bool(
        source_section.get("sha256_before_replay") == source_hash
        and source_section.get("sha256_after_replay") == source_hash
        and source_before == source_after
        and source_before_ok
        and source_after_ok
    )
    return exact, immutable, {
        "current_source_sha256": source_hash,
        "runtime_source_sha256_before_replay": source_section.get("sha256_before_replay"),
        "runtime_source_sha256_after_replay": source_section.get("sha256_after_replay"),
        "proof": proof,
        "runtime_proof_matches": runtime_proof == proof,
        "source_manifest_before": source_before_evidence,
        "source_manifest_after": source_after_evidence,
        "replay_manifest": replay_manifest_evidence,
        "source_manifests_equal": source_before == source_after,
        "replay_live_dispatch_count": execution.get("live_dispatch_count"),
    }


def _resource_evidence(
    runtime: Mapping[str, Any], ticks: int, thresholds: Mapping[str, Any],
) -> tuple[bool, dict[str, Any]]:
    runtime_section = _json_mapping(runtime.get("runtime")) or {}
    memory = _json_mapping(runtime_section.get("memory")) or {}
    database = _json_mapping(runtime_section.get("database")) or {}
    checkpoints = runtime_section.get("checkpoints")
    checkpoints = checkpoints if isinstance(checkpoints, list) else []
    peak_rss = _finite_number(memory.get("peak_rss_mb"), minimum=0)
    available = _finite_number(memory.get("min_available_memory_gb"), minimum=0)
    growth = _strict_int(database.get("logical_used_growth_bytes"), minimum=0)
    durations = [
        value
        for row in checkpoints if isinstance(row, Mapping)
        if (value := _finite_number(row.get("duration_s"), minimum=0)) is not None
    ]
    p95 = _percentile_95(durations)
    growth_per_tick = growth / ticks if growth is not None and ticks > 0 else None
    limits = {
        "max_peak_rss_mb": float(thresholds["max_peak_rss_mb"]),
        "min_available_memory_gb": float(thresholds["min_available_memory_gb"]),
        "max_database_growth_bytes_per_tick": int(
            thresholds["max_database_growth_bytes_per_tick"]),
        "max_checkpoint_p95_seconds": float(thresholds["max_checkpoint_p95_seconds"]),
    }
    tick_rows = runtime_section.get("ticks")
    tick_rows = tick_rows if isinstance(tick_rows, list) else []
    tick_ids = [
        row.get("tick") for row in tick_rows if isinstance(row, Mapping)
    ]
    passed = bool(
        peak_rss is not None and peak_rss <= limits["max_peak_rss_mb"]
        and available is not None and available >= limits["min_available_memory_gb"]
        and growth_per_tick is not None
        and growth_per_tick <= limits["max_database_growth_bytes_per_tick"]
        and p95 is not None and p95 <= limits["max_checkpoint_p95_seconds"]
        and len(durations) == len(checkpoints)
        and tick_ids == list(range(1, ticks + 1))
    )
    return passed, {
        "peak_rss_mb": peak_rss,
        "min_available_memory_gb": available,
        "database_growth_bytes": growth,
        "database_growth_bytes_per_tick": (
            round(growth_per_tick, 6) if growth_per_tick is not None else None),
        "checkpoint_p95_seconds": p95,
        "checkpoint_samples": len(durations),
        "runtime_tick_records": len(tick_ids),
        "limits": limits,
    }


def _outcome(checks: Mapping[str, bool], *, diagnostic: bool) -> str:
    if all(checks.values()):
        return "passed"
    if diagnostic and all(checks[name] for name in OPERATIONAL_CHECKS):
        failed = {name for name in ECONOMIC_CHECKS if not checks[name]}
        if failed:
            return "diagnostic_economic_failure"
    return "failed"


def evaluate_scale_economic_health(
    source_db: str | Path,
    replay_db: str | Path,
    runtime_receipt: str | Path,
) -> dict[str, object]:
    """Evaluate finalized source/replay artifacts without ever opening a writer."""
    source_path = Path(source_db).resolve()
    replay_path = Path(replay_db).resolve()
    runtime_path = Path(runtime_receipt).resolve()
    runtime, runtime_error = _read_runtime(runtime_path)
    if runtime is None:
        return _empty_receipt(runtime_error or "runtime receipt could not be read")

    runtime_safe = True
    runtime_safety_error: str | None = None
    try:
        validate_receipt_safety(runtime)
    except ReceiptSafetyError as exc:
        runtime_safe = False
        runtime_safety_error = str(exc).split(" at ", 1)[0]

    source_sidecars = _sidecars(source_path)
    replay_sidecars = _sidecars(replay_path)
    if not source_path.is_file() or not replay_path.is_file():
        receipt = _empty_receipt("source or replay database is missing")
        receipt["checks"]["runtime_receipt_safe"] = runtime_safe
        receipt["evidence"]["runtime_receipt_safety"] = {
            "passed": runtime_safe, "error": runtime_safety_error}
        return receipt
    if source_sidecars or replay_sidecars:
        receipt = _empty_receipt("finalized SQLite artifact has sidecars")
        receipt["checks"]["runtime_receipt_safe"] = runtime_safe
        receipt["evidence"]["runtime_receipt_safety"] = {
            "passed": runtime_safe, "error": runtime_safety_error}
        receipt["evidence"]["sqlite_integrity"] = {
            "source_sidecars": source_sidecars,
            "replay_sidecars": replay_sidecars,
            "error": "immutable evaluation rejects SQLite sidecars",
        }
        return receipt

    source_connection: sqlite3.Connection | None = None
    replay_connection: sqlite3.Connection | None = None
    try:
        source_connection = _immutable_connection(source_path)
        replay_connection = _immutable_connection(replay_path)
        source_meta = source_connection.execute(
            "SELECT * FROM run_meta WHERE id=1").fetchone()
        replay_meta = replay_connection.execute(
            "SELECT * FROM run_meta WHERE id=1").fetchone()
        if source_meta is None or replay_meta is None:
            return _empty_receipt("source or replay run metadata is missing")
        persisted_config = _load_json_mapping(source_meta["config_json"])
        if persisted_config is None:
            return _empty_receipt("persisted source configuration is invalid")
        source_store = _store_view(source_path, source_connection)

        checks = {name: False for name in CHECK_NAMES}
        evidence: dict[str, Any] = {}
        checks["runtime_receipt_safe"] = runtime_safe
        evidence["runtime_receipt_safety"] = {
            "passed": runtime_safe,
            "error": runtime_safety_error,
        }

        identity_ok, identity, contract, thresholds = _identity_evidence(
            runtime, source_meta, replay_meta, persisted_config)
        checks["identity_exact"] = identity_ok
        evidence["identity"] = identity
        contract = contract or {
            "required_ticks": None, "diagnostic": False, "recovery_enabled": None}
        required_ticks = _strict_int(contract.get("required_ticks"), minimum=1)
        if thresholds is None or required_ticks is None:
            thresholds = {
                "schema_version": None,
                "required_ticks": required_ticks,
                "warmup_ticks": 60,
                "trailing_window_ticks": 60,
                "max_buy_goods_rejection_rate": 0.05,
                "max_unemployment_rebound": 0.10,
                "max_pending_applications": 20,
                "max_pending_job_offers": 20,
                "max_open_jobs": 20,
                "max_peak_rss_mb": 2048,
                "min_available_memory_gb": 8,
                "max_database_growth_bytes_per_tick": 8388608,
                "max_checkpoint_p95_seconds": 5.0,
            }
        evaluation_ticks = required_ticks or max(1, _strict_int(source_meta["tick"], minimum=1) or 1)

        checks["horizon_completed"] = bool(
            required_ticks is not None
            and _strict_int(source_meta["tick"], minimum=0) == required_ticks
            and _strict_int(replay_meta["tick"], minimum=0) == required_ticks
            and source_meta["status"] in COMPLETED_STATUSES
            and source_meta["active_tick"] is None
        )
        evidence["horizon"] = {
            "required_ticks": required_ticks,
            "source_tick": source_meta["tick"],
            "replay_tick": replay_meta["tick"],
            "source_status": source_meta["status"],
            "active_tick": source_meta["active_tick"],
            "completed_statuses": sorted(COMPLETED_STATUSES),
        }

        checks["population_exact"], evidence["population"] = _population_evidence(
            source_connection)
        checks["communications_exact"], evidence["communications"] = (
            _communications_evidence(
                source_connection, runtime, evaluation_ticks, persisted_config))
        checks["provider_and_spend_exact"], evidence["providers"] = _provider_evidence(
            source_connection, runtime, persisted_config)
        checks["purchase_windows_healthy"], evidence["purchase_windows"] = (
            _purchase_evidence(source_connection, evaluation_ticks, thresholds))
        (
            checks["unemployment_rebound_bounded"],
            checks["unemployment_final_mean_not_worse"],
            evidence["unemployment"],
        ) = _unemployment_evidence(source_connection, evaluation_ticks, thresholds)
        (
            checks["production_and_inventory_healthy"],
            evidence["production_and_inventory"],
        ) = _production_inventory_evidence(source_connection, evaluation_ticks, thresholds)

        activation_tick = 0
        recovery = _json_mapping(persisted_config.get("supply_recovery")) or {}
        if recovery.get("enabled") is True:
            activation_tick = _strict_int(recovery.get("activation_tick"), minimum=0) or 0
        (
            unit_ok,
            unit_economics,
            recovery_goods_firms,
            unit_summary,
        ) = supply_recovery._unit_economics_evidence(
            source_store,
            activation_tick=activation_tick,
            completed_tick=_strict_int(source_meta["tick"], minimum=0),
        )
        checks["unit_economics_valid"] = unit_ok
        evidence["unit_economics"] = {
            "firms": unit_economics,
            "summary": unit_summary,
        }
        checks["managed_insolvency_absent"], evidence["insolvency"] = (
            supply_recovery._insolvency_evidence(
                source_store,
                recovery_goods_firms,
                activation_tick=activation_tick,
                completed_tick=_strict_int(source_meta["tick"], minimum=0),
            ))
        checks["labor_backlog_bounded"], evidence["labor"] = _labor_evidence(
            source_connection, thresholds)
        (
            checks["employment_currency_and_terms_valid"],
            evidence["employment"],
        ) = _employment_evidence(source_connection)
        checks["ledger_reconciles"], evidence["ledger"] = _ledger_evidence(source_store)
        checks["sqlite_integrity"], evidence["sqlite_integrity"] = _sqlite_evidence(
            source_connection, replay_connection, source_sidecars, replay_sidecars)
        checks["checkpoints_valid"], evidence["checkpoints"] = _checkpoint_evidence(
            source_store, runtime, str(source_meta["run_id"]),
            evaluation_ticks, persisted_config)
        (
            checks["exact_replay"],
            checks["source_immutable"],
            evidence["replay"],
        ) = _replay_and_source_evidence(source_path, replay_path, runtime)
        checks["resources_within_caps"], evidence["resources"] = _resource_evidence(
            runtime, evaluation_ticks, thresholds)

        outcome = _outcome(checks, diagnostic=bool(contract.get("diagnostic")))
        policy_version = recovery.get("policy_version") if recovery.get("enabled") is True else None
        effective_config = _json_mapping(runtime.get("effective_config")) or {}
        result: dict[str, object] = {
            "schema": SCHEMA,
            "schema_version": 1,
            "outcome": outcome,
            "passed": outcome == "passed",
            "profile": {
                "path": runtime.get("profile_path") if isinstance(runtime.get("profile_path"), str) else None,
                "required_ticks": required_ticks,
                "diagnostic": bool(contract.get("diagnostic")),
                "recovery_enabled": contract.get("recovery_enabled"),
                "policy_version": policy_version,
                "profile_config_sha256": runtime.get("profile_config_sha256"),
                "effective_config_sha256": runtime.get("effective_config_sha256"),
                "source_commit": runtime.get("source_commit"),
            },
            "run": {
                "run_id": str(source_meta["run_id"]),
                "replay_run_id": str(replay_meta["run_id"]),
                "seed": int(source_meta["seed"]),
                "engine_semantics_version": persisted_config.get("engine_semantics_version"),
                "status": str(source_meta["status"]),
                "tick": _strict_int(source_meta["tick"], minimum=0),
                "active_tick": source_meta["active_tick"],
            },
            "thresholds": dict(thresholds),
            "checks": checks,
            "check_groups": {
                "economic": sorted(ECONOMIC_CHECKS),
                "operational": sorted(OPERATIONAL_CHECKS),
            },
            "population": evidence["population"]["observed"],
            "evidence": evidence,
            "runtime": {
                "effective_config_sha256": runtime.get("effective_config_sha256"),
                "effective_config": effective_config,
                "source_sha256": evidence["replay"]["current_source_sha256"],
                "replay_proof": evidence["replay"]["proof"],
            },
        }
        try:
            validate_receipt_safety(result)
        except ReceiptSafetyError:
            safe_failure = _empty_receipt(
                "derived economic-health receipt failed the public safety boundary")
            safe_failure["checks"]["runtime_receipt_safe"] = runtime_safe
            return safe_failure
        return result
    except SchemaCompatibilityError:
        return _empty_receipt("source or replay database schema is incompatible")
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        return _empty_receipt(
            f"immutable evaluation failed closed: {type(exc).__name__}")
    finally:
        if replay_connection is not None:
            replay_connection.close()
        if source_connection is not None:
            source_connection.close()


def _receipt_paths(output: Path) -> tuple[Path, Path]:
    if output.suffix in {".json", ".md"}:
        output = output.with_suffix("")
    return output.with_suffix(".json"), output.with_suffix(".md")


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_write_pair(
    json_path: Path, markdown_path: Path, receipt: Mapping[str, object],
    markdown: str,
) -> None:
    _atomic_write(
        json_path,
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
    )
    _atomic_write(markdown_path, markdown)


def render_scale_economic_health_markdown(receipt: Mapping[str, object]) -> str:
    """Render the deterministic Markdown companion to one scale receipt."""
    run = _json_mapping(receipt.get("run")) or {}
    profile = _json_mapping(receipt.get("profile")) or {}
    checks = _json_mapping(receipt.get("checks")) or {}
    lines = [
        f"# Scale-270 economic health — {run.get('run_id') or 'unknown run'}",
        "",
        f"Outcome: **{str(receipt.get('outcome', 'failed')).upper()}**",
        "",
        "## Identity",
        "",
        f"- Profile: `{profile.get('path')}`",
        f"- Completed tick: `{run.get('tick')}`",
        f"- Seed: `{run.get('seed')}`",
        f"- Source commit: `{profile.get('source_commit')}`",
        "",
        "## Gates",
        "",
    ]
    for name in CHECK_NAMES:
        lines.append(f"- [{'x' if checks.get(name) is True else ' '}] `{name}`")
    evidence = _json_mapping(receipt.get("evidence")) or {}
    unemployment = _json_mapping(evidence.get("unemployment")) or {}
    purchases = _json_mapping(evidence.get("purchase_windows")) or {}
    resources = _json_mapping(evidence.get("resources")) or {}
    lines += [
        "",
        "## Economic summary",
        "",
        f"- First-window unemployment mean: `{unemployment.get('first_window_mean')}`",
        f"- Final-window unemployment mean: `{unemployment.get('final_window_mean')}`",
        f"- Latest purchase window: `{json.dumps(purchases.get('latest_window'), sort_keys=True)}`",
        "",
        "## Resource summary",
        "",
        f"- Peak RSS MiB: `{resources.get('peak_rss_mb')}`",
        f"- Minimum available memory GiB: `{resources.get('min_available_memory_gb')}`",
        f"- Database growth bytes/tick: `{resources.get('database_growth_bytes_per_tick')}`",
        f"- Checkpoint p95 seconds: `{resources.get('checkpoint_p95_seconds')}`",
        "",
    ]
    return "\n".join(lines)


def write_scale_economic_health_receipt(
    source_db: str | Path,
    replay_db: str | Path,
    runtime_receipt: str | Path,
    *,
    output: str | Path,
) -> dict[str, object]:
    """Evaluate and atomically write canonical JSON and Markdown receipts."""
    receipt = evaluate_scale_economic_health(source_db, replay_db, runtime_receipt)
    json_path, markdown_path = _receipt_paths(Path(output))
    _atomic_write_pair(
        json_path, markdown_path, receipt,
        render_scale_economic_health_markdown(receipt),
    )
    return receipt


def _economic_summary(receipt: Mapping[str, object]) -> dict[str, Any]:
    evidence = _json_mapping(receipt.get("evidence")) or {}
    unemployment = _json_mapping(evidence.get("unemployment")) or {}
    purchases = _json_mapping(evidence.get("purchase_windows")) or {}
    production = _json_mapping(evidence.get("production_and_inventory")) or {}
    latest_purchase = _json_mapping(purchases.get("latest_window")) or {}
    firms = production.get("active_goods_firms")
    firms = firms if isinstance(firms, list) else []
    return {
        "first_unemployment_mean": unemployment.get("first_window_mean"),
        "final_unemployment_mean": unemployment.get("final_window_mean"),
        "latest_purchase_rejection_rate": latest_purchase.get("rate"),
        "final_window_production_units": sum(
            int(row.get("production_units", 0))
            for row in firms if isinstance(row, Mapping)),
        "final_window_sale_units": sum(
            int(row.get("accepted_sale_units", 0))
            for row in firms if isinstance(row, Mapping)),
    }


def _numeric_delta(recovery: object, baseline: object) -> float | None:
    recovery_value = _finite_number(recovery)
    baseline_value = _finite_number(baseline)
    if recovery_value is None or baseline_value is None:
        return None
    return round(recovery_value - baseline_value, 6)


def evaluate_scale_ab(
    baseline: Mapping[str, object],
    recovery: Mapping[str, object],
) -> dict[str, object]:
    """Compare canonical diagnostic arms, permitting only recovery policy drift."""
    baseline_checks = _json_mapping(baseline.get("checks")) or {}
    recovery_checks = _json_mapping(recovery.get("checks")) or {}
    baseline_runtime = _json_mapping(baseline.get("runtime")) or {}
    recovery_runtime = _json_mapping(recovery.get("runtime")) or {}
    baseline_config = _json_mapping(baseline_runtime.get("effective_config"))
    recovery_config = _json_mapping(recovery_runtime.get("effective_config"))
    baseline_policy = None
    recovery_policy = None
    configs_match = False
    expected_recovery_policy = load_config(
        ROOT / "runs/acceptance/scale-270-recovery-120.yaml"
    ).get("supply_recovery")
    if baseline_config is not None and recovery_config is not None:
        baseline_compare = deepcopy(baseline_config)
        recovery_compare = deepcopy(recovery_config)
        baseline_policy = baseline_compare.pop("supply_recovery", None)
        recovery_policy = recovery_compare.pop("supply_recovery", None)
        configs_match = bool(
            baseline_compare == recovery_compare
            and baseline_policy == {"enabled": False}
            and recovery_policy == expected_recovery_policy
        )
    baseline_operational = all(
        baseline_checks.get(name) is True for name in OPERATIONAL_CHECKS)
    recovery_operational = all(
        recovery_checks.get(name) is True for name in OPERATIONAL_CHECKS)
    recovery_economic = all(
        recovery_checks.get(name) is True for name in ECONOMIC_CHECKS)
    baseline_outcome_valid = bool(
        baseline.get("outcome") in {"passed", "diagnostic_economic_failure"}
        and baseline.get("passed") is (baseline.get("outcome") == "passed")
    )
    recovery_outcome_valid = bool(
        recovery.get("outcome") == "passed" and recovery.get("passed") is True)
    schemas_valid = (
        baseline.get("schema") == SCHEMA
        and recovery.get("schema") == SCHEMA
        and baseline.get("schema_version") == recovery.get("schema_version") == 1
    )
    checks = {
        "receipt_schemas_valid": schemas_valid,
        "configs_differ_only_by_recovery_policy": configs_match,
        "baseline_outcome_valid": baseline_outcome_valid,
        "baseline_operational": baseline_operational,
        "recovery_outcome_valid": recovery_outcome_valid,
        "recovery_operational": recovery_operational,
        "recovery_economic_health": recovery_economic,
    }
    baseline_summary = _economic_summary(baseline)
    recovery_summary = _economic_summary(recovery)
    deltas = {
        name: _numeric_delta(recovery_summary.get(name), baseline_summary.get(name))
        for name in sorted(set(baseline_summary) | set(recovery_summary))
    }
    return {
        "schema": AB_SCHEMA,
        "schema_version": 1,
        "outcome": "passed" if all(checks.values()) else "failed",
        "passed": all(checks.values()),
        "checks": checks,
        "arms": {
            "baseline": {
                "outcome": baseline.get("outcome"),
                "profile": (_json_mapping(baseline.get("profile")) or {}).get("path"),
                "run_id": (_json_mapping(baseline.get("run")) or {}).get("run_id"),
                "effective_config_sha256": baseline_runtime.get("effective_config_sha256"),
                "source_sha256": baseline_runtime.get("source_sha256"),
                "economic": baseline_summary,
                "failed_economic_checks": sorted(
                    name for name in ECONOMIC_CHECKS
                    if baseline_checks.get(name) is not True),
            },
            "recovery": {
                "outcome": recovery.get("outcome"),
                "profile": (_json_mapping(recovery.get("profile")) or {}).get("path"),
                "run_id": (_json_mapping(recovery.get("run")) or {}).get("run_id"),
                "effective_config_sha256": recovery_runtime.get("effective_config_sha256"),
                "source_sha256": recovery_runtime.get("source_sha256"),
                "economic": recovery_summary,
                "failed_economic_checks": sorted(
                    name for name in ECONOMIC_CHECKS
                    if recovery_checks.get(name) is not True),
            },
        },
        "policy_difference": {
            "baseline": baseline_policy,
            "recovery": recovery_policy,
        },
        "deltas_recovery_minus_baseline": deltas,
    }


def _render_scale_ab_markdown(receipt: Mapping[str, object]) -> str:
    checks = _json_mapping(receipt.get("checks")) or {}
    arms = _json_mapping(receipt.get("arms")) or {}
    lines = [
        "# Scale-270 economic-health A/B",
        "",
        f"Outcome: **{str(receipt.get('outcome', 'failed')).upper()}**",
        "",
        "## Gates",
        "",
    ]
    for name, passed in checks.items():
        lines.append(f"- [{'x' if passed is True else ' '}] `{name}`")
    lines += ["", "## Arms", ""]
    for name in ("baseline", "recovery"):
        arm = _json_mapping(arms.get(name)) or {}
        lines.append(
            f"- `{name}`: outcome `{arm.get('outcome')}`, run `{arm.get('run_id')}`")
    lines += ["", "## Recovery minus baseline", ""]
    deltas = _json_mapping(receipt.get("deltas_recovery_minus_baseline")) or {}
    for name, value in deltas.items():
        lines.append(f"- `{name}`: `{value}`")
    return "\n".join(lines) + "\n"


def write_scale_ab_receipt(
    baseline: Mapping[str, object],
    recovery: Mapping[str, object],
    *,
    output: str | Path,
) -> dict[str, object]:
    """Evaluate and atomically write one canonical A/B aggregate."""
    receipt = evaluate_scale_ab(baseline, recovery)
    json_path, markdown_path = _receipt_paths(Path(output))
    _atomic_write_pair(json_path, markdown_path, receipt, _render_scale_ab_markdown(receipt))
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate finalized scale-270 source and replay artifacts")
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--replay", required=True, type=Path)
    parser.add_argument("--runtime-receipt", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    receipt = write_scale_economic_health_receipt(
        args.source,
        args.replay,
        args.runtime_receipt,
        output=args.output,
    )
    print(json.dumps({
        "outcome": receipt["outcome"],
        "run_id": (_json_mapping(receipt.get("run")) or {}).get("run_id"),
        "tick": (_json_mapping(receipt.get("run")) or {}).get("tick"),
        "output": str(_receipt_paths(args.output)[0]),
    }, sort_keys=True))
    if receipt["outcome"] == "passed":
        return 0
    if receipt["outcome"] == "diagnostic_economic_failure":
        return 10
    return 5


if __name__ == "__main__":
    sys.exit(main())
