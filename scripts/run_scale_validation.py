#!/usr/bin/env python3
"""Run one maintained scale profile and emit a sanitized runtime receipt."""
from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterable, Mapping
from typing import Any

import psutil
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
RUNS_ROOT = (ROOT / "runs").resolve()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.checkpoint_manifest import finalize_sqlite_artifact
from llm.readiness import validate_llm_config
from reports.acceptance import uses_paid_providers
from run import open_run, provider_preflight, replay_headless
from run_config import load_config
from world.replay_verify import verify_replay


SCHEMA = "agent-economy-scale-validation-v1"
EXPECTED_POPULATION = {
    "agents": 308,
    "alive": 308,
    "citizen_kind": 272,
    "staff_kind": 36,
    "core": 100,
    "periphery": 208,
    "regions": {"ironvale": 69, "northstar": 184, "suncoast": 55},
}
SQLITE_SIDECARS = ("-wal", "-shm", "-journal")
_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_FORBIDDEN_KEYS = {
    "apikey",
    "authorization",
    "cookie",
    "cookies",
    "environment",
    "environ",
    "environmentdump",
    "privateproviderbody",
    "privatereasoning",
    "raw",
    "rawbody",
    "reasoningcontent",
    "responsebody",
    "setcookie",
}
_SQLITE_MAGIC = ("SQLite format 3\x00", "U1FMaXRlIGZvcm1hdCAz")


class ValidationInputError(ValueError):
    """The requested scale validation is not an allowed maintained run."""


class ReceiptSafetyError(ValueError):
    """A public receipt contains a secret or private artifact boundary."""


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_head() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _artifact_root(output_dir: Path, data_dir: Path) -> Path:
    common = Path(os.path.commonpath((output_dir, data_dir))).resolve()
    if common == Path(common.anchor):
        raise ValidationInputError(
            "output_dir and data_dir must share a narrow isolated parent")
    return common


def _artifact_id(path: Path, root: Path) -> str:
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise ValidationInputError(
            f"generated artifact escapes the isolated artifact root: {resolved.name}")
    return resolved.relative_to(root).as_posix()


def _paths_overlap(first: Path, second: Path) -> bool:
    return (
        first == second
        or first.is_relative_to(second)
        or second.is_relative_to(first)
    )


def _validate_profile(profile: Path) -> Path:
    resolved = profile.resolve()
    if not resolved.is_file() or not resolved.is_relative_to(RUNS_ROOT):
        raise ValidationInputError(
            "profile must be a maintained profile beneath runs/")
    return resolved


def prepare_validation_config(
    profile: Path,
    *,
    ticks: int,
    output_dir: Path,
    data_dir: Path,
    approve_live: bool,
) -> dict[str, Any]:
    """Load an authoritative maintained profile and rehome operational paths."""
    if isinstance(ticks, bool) or not isinstance(ticks, int) or ticks <= 0:
        raise ValidationInputError("ticks must be a positive integer")
    profile = _validate_profile(Path(profile))
    output_dir = Path(output_dir).resolve()
    data_dir = Path(data_dir).resolve()
    source_root = data_dir / "source"
    replay_root = data_dir / "replay"
    if any(
        _paths_overlap(output_dir, root)
        for root in (source_root, replay_root)
    ):
        raise ValidationInputError(
            "output_dir must not overlap source or replay run roots")

    config = load_config(profile)
    live = uses_paid_providers(config)
    if live and not approve_live:
        raise ValidationInputError(
            "live profile requires --approve-live-inference")
    if approve_live and not live:
        raise ValidationInputError(
            "--approve-live-inference is invalid for a provider-free profile")
    if live and ticks != 2:
        raise ValidationInputError("maintained paid canaries require exactly 2 ticks")
    acceptance = config.get("acceptance", {}) or {}
    scale_contract = acceptance.get("scale_economic_health", {}) or {}
    required_ticks = scale_contract.get("required_ticks")
    if required_ticks is not None and ticks != int(required_ticks):
        raise ValidationInputError(
            f"profile requires exactly {int(required_ticks)} ticks")

    prepared = deepcopy(config)
    prepared["checkpoint_dir"] = str(source_root / "checkpoints")
    prepared["report_dir"] = str(output_dir / "reports")
    return prepared


def _normalize_key(key: object) -> str:
    return "".join(character for character in str(key).lower() if character.isalnum())


def validate_receipt_safety(
    payload: object,
    *,
    secret_values: Iterable[str] = (),
) -> None:
    """Reject secret values, private provider material, DB bodies, and host paths."""
    secrets = tuple(
        value for value in (str(item) for item in secret_values)
        if len(value) >= 8
    )

    def visit(value: object, path: str) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                normalized = _normalize_key(key)
                if normalized in _FORBIDDEN_KEYS:
                    raise ReceiptSafetyError(
                        f"forbidden receipt field at {path}.{key}")
                visit(child, f"{path}.{key}")
            return
        if isinstance(value, (list, tuple)):
            for index, child in enumerate(value):
                visit(child, f"{path}[{index}]")
            return
        if isinstance(value, (bytes, bytearray, memoryview)):
            raise ReceiptSafetyError(f"binary body at {path}")
        if not isinstance(value, str):
            return
        lower = value.lower()
        if value.startswith("/"):
            raise ReceiptSafetyError(f"host-private absolute path at {path}")
        if "bearer " in lower:
            raise ReceiptSafetyError(f"Authorization value at {path}")
        if any(marker in value for marker in _SQLITE_MAGIC):
            raise ReceiptSafetyError(f"embedded SQLite body at {path}")
        if any(secret in value for secret in secrets):
            raise ReceiptSafetyError(f"credential value at {path}")

    visit(payload, "$receipt")


def _atomic_write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(
        payload,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
    ) + "\n").encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _database_files(path: Path) -> dict[str, int]:
    paths = {
        "main": path,
        "wal": Path(f"{path}-wal"),
        "shm": Path(f"{path}-shm"),
        "journal": Path(f"{path}-journal"),
    }
    sizes = {
        name: candidate.stat().st_size if candidate.exists() else 0
        for name, candidate in paths.items()
    }
    sizes["main_plus_wal"] = sizes["main"] + sizes["wal"]
    return sizes


def _database_snapshot(store: Any) -> dict[str, int]:
    page_count = int(store.scalar("PRAGMA page_count", default=0))
    page_size = int(store.scalar("PRAGMA page_size", default=0))
    freelist_count = int(store.scalar("PRAGMA freelist_count", default=0))
    return {
        **_database_files(Path(store.path)),
        "page_count": page_count,
        "page_size": page_size,
        "freelist_count": freelist_count,
        "logical_bytes": page_count * page_size,
        "logical_used_bytes": (page_count - freelist_count) * page_size,
    }


def _artifact_kind(path: Path, run_root: Path, role: str) -> str:
    if path.suffix == ".db":
        return f"{role}_database" if path.parent == run_root else "checkpoint_database"
    if path.name.endswith(".db.manifest.json"):
        return "checkpoint_manifest"
    return "artifact"


def _artifact_manifest(
    root: Path, artifact_root: Path, *, role: str,
) -> list[dict[str, object]]:
    root = root.resolve()
    rows: dict[str, dict[str, object]] = {}
    databases: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        artifact = _artifact_id(path, artifact_root)
        rows[artifact] = {
            "artifact": artifact,
            "kind": _artifact_kind(path, root, role),
            "present": True,
            "bytes": path.stat().st_size,
            "sha256": _sha256_file(path),
        }
        if path.suffix == ".db":
            databases.append(path)
    for database in databases:
        for suffix in SQLITE_SIDECARS:
            sidecar = Path(f"{database}{suffix}")
            artifact = _artifact_id(sidecar, artifact_root)
            rows.setdefault(artifact, {
                "artifact": artifact,
                "kind": "sqlite_sidecar",
                "present": False,
                "bytes": 0,
                "sha256": None,
            })
    return [rows[key] for key in sorted(rows)]


@contextmanager
def _read_only_tree(root: Path):
    """Make the complete source tree non-writable for the replay boundary."""
    root = root.resolve()
    paths = [root, *sorted(root.rglob("*"), key=lambda item: len(item.parts))]
    modes = {path: path.stat().st_mode & 0o777 for path in paths}
    try:
        for path in paths:
            path.chmod(0o500 if path.is_dir() else 0o400)
        yield
    finally:
        for path in paths:
            if path.is_dir():
                path.chmod(modes[path])
        for path in paths:
            if path.is_file():
                path.chmod(modes[path])


class _MemorySampler:
    def __init__(self) -> None:
        self.process = psutil.Process()
        self.samples: list[dict[str, object]] = []
        self.stage = "startup"
        self.started = time.perf_counter()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._sample, daemon=True)

    def _take_sample(self) -> None:
        memory = psutil.virtual_memory()
        self.samples.append({
            "elapsed_s": round(time.perf_counter() - self.started, 4),
            "stage": self.stage,
            "rss_mb": self.process.memory_info().rss / (1024 ** 2),
            "available_memory_gb": memory.available / (1024 ** 3),
            "system_memory_percent": float(memory.percent),
        })

    def _sample(self) -> None:
        while not self._stop.is_set():
            self._take_sample()
            self._stop.wait(0.05)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> dict[str, object]:
        self._stop.set()
        self._thread.join(timeout=2.0)
        if not self.samples:
            self._take_sample()
        by_stage: dict[str, dict[str, object]] = {}
        for stage in sorted({str(row["stage"]) for row in self.samples}):
            rows = [row for row in self.samples if row["stage"] == stage]
            by_stage[stage] = {
                "samples": len(rows),
                "peak_rss_mb": round(max(float(row["rss_mb"]) for row in rows), 2),
                "min_available_memory_gb": round(
                    min(float(row["available_memory_gb"]) for row in rows), 2),
                "max_system_memory_percent": round(
                    max(float(row["system_memory_percent"]) for row in rows), 2),
            }
        return {
            "sample_interval_s": 0.05,
            "samples": len(self.samples),
            "peak_rss_mb": round(
                max(float(row["rss_mb"]) for row in self.samples), 2),
            "min_available_memory_gb": round(
                min(float(row["available_memory_gb"]) for row in self.samples), 2),
            "max_system_memory_percent": round(
                max(float(row["system_memory_percent"]) for row in self.samples), 2),
            "by_stage": by_stage,
        }


def _inspect_population(store: Any) -> dict[str, object]:
    return {
        "agents": int(store.scalar("SELECT COUNT(*) FROM agents", default=0)),
        "alive": int(store.scalar(
            "SELECT COUNT(*) FROM agents WHERE alive=1", default=0)),
        "citizen_kind": int(store.scalar(
            "SELECT COUNT(*) FROM agents WHERE kind='citizen'", default=0)),
        "staff_kind": int(store.scalar(
            "SELECT COUNT(*) FROM agents WHERE kind='staff'", default=0)),
        "core": int(store.scalar(
            "SELECT COUNT(*) FROM agents WHERE population_tier='core'", default=0)),
        "periphery": int(store.scalar(
            "SELECT COUNT(*) FROM agents WHERE population_tier='periphery'", default=0)),
        "regions": {
            str(row["region_key"]): int(row["n"])
            for row in store.query(
                "SELECT r.region_key,COUNT(a.id) n FROM regions r "
                "LEFT JOIN agents a ON a.region_id=r.id "
                "GROUP BY r.id ORDER BY r.region_key")
        },
    }


def _inspect_communications(store: Any) -> dict[str, object]:
    conversations = [dict(row) for row in store.query(
        "SELECT id,tick,participant_ids FROM conversations ORDER BY id")]
    participants = {
        int(row["id"]): {int(value) for value in json.loads(row["participant_ids"])}
        for row in conversations
    }
    messages = [dict(row) for row in store.query(
        "SELECT conv_id,agent_id,text FROM messages ORDER BY id")]
    counts: dict[int, int] = {}
    invalid_memberships = 0
    empty_messages = 0
    unique_participants: set[int] = set()
    for member_ids in participants.values():
        unique_participants.update(member_ids)
    for message in messages:
        conversation_id = int(message["conv_id"])
        counts[conversation_id] = counts.get(conversation_id, 0) + 1
        if int(message["agent_id"]) not in participants.get(conversation_id, set()):
            invalid_memberships += 1
        if not str(message["text"]).strip():
            empty_messages += 1
    return {
        "conversations": len(conversations),
        "messages": len(messages),
        "unique_participants": len(unique_participants),
        "invalid_message_memberships": invalid_memberships,
        "empty_messages": empty_messages,
        "message_count_per_conversation": sorted(set(counts.values())),
    }


def _inspect_providers(store: Any) -> dict[str, object]:
    pairs = [dict(row) for row in store.query(
        "SELECT provider,model,COUNT(*) calls,"
        "COALESCE(SUM(in_tokens),0) in_tokens,"
        "COALESCE(SUM(out_tokens),0) out_tokens,"
        "COALESCE(SUM(cached),0) cached_calls,"
        "COALESCE(SUM(cost_usd),0) cost_usd "
        "FROM llm_calls GROUP BY provider,model ORDER BY provider,model")]
    purposes = {
        str(row["purpose"]): int(row["calls"])
        for row in store.query(
            "SELECT purpose,COUNT(*) calls FROM llm_calls "
            "GROUP BY purpose ORDER BY purpose")
    }
    return {
        "calls": int(store.scalar("SELECT COUNT(*) FROM llm_calls", default=0)),
        "cost_usd": float(store.scalar(
            "SELECT COALESCE(SUM(cost_usd),0) FROM llm_calls", default=0.0)),
        "pairs": pairs,
        "purposes": purposes,
    }


def _read_only_integrity(path: Path) -> dict[str, object]:
    sidecars = [
        suffix for suffix in SQLITE_SIDECARS
        if Path(f"{path}{suffix}").exists()
    ]
    connection = sqlite3.connect(
        f"{path.as_uri()}?mode=ro&immutable=1", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only=ON")
        quick_check = [str(row[0]) for row in connection.execute("PRAGMA quick_check")]
        foreign_keys = [dict(row) for row in connection.execute(
            "PRAGMA foreign_key_check")]
        failure_events = {
            str(row["kind"]): int(row["events"])
            for row in connection.execute(
                "SELECT kind,COUNT(*) events FROM events WHERE kind IN "
                "('checkpoint_failed','checkpoint_prune_failed',"
                "'reconciliation_failure','budget_pause','provider_pause',"
                "'provider_failure') GROUP BY kind ORDER BY kind")
        }
    finally:
        connection.close()
    return {
        "quick_check": quick_check,
        "foreign_key_violations": foreign_keys,
        "failure_events": failure_events,
        "sqlite_sidecars": sidecars,
    }


def _normalized_config(config: Mapping[str, object], artifact_root: Path) -> dict:
    normalized = deepcopy(dict(config))
    for field in ("checkpoint_dir", "report_dir"):
        value = normalized.get(field)
        if isinstance(value, str):
            normalized[field] = _artifact_id(Path(value), artifact_root)
    return normalized


def _secret_values(config: Mapping[str, object]) -> tuple[str, ...]:
    providers = (config.get("llm", {}) or {}).get("providers", {}) or {}
    values = []
    for provider in providers.values():
        if not isinstance(provider, Mapping):
            continue
        environment_name = provider.get("api_key_env")
        if isinstance(environment_name, str):
            value = os.environ.get(environment_name, "")
            if value:
                values.append(value)
    return tuple(values)


def run_validation(
    profile: Path,
    ticks: int,
    label: str,
    output_dir: Path,
    data_dir: Path,
    approve_live: bool,
) -> dict[str, object]:
    """Run a maintained source plus exact split-root replay and write its receipt."""
    if not isinstance(label, str) or not _LABEL.fullmatch(label):
        raise ValidationInputError(
            "label must use 1-128 letters, numbers, dots, underscores, or hyphens")
    profile = _validate_profile(Path(profile))
    output_dir = Path(output_dir).resolve()
    data_dir = Path(data_dir).resolve()
    artifact_root = _artifact_root(output_dir, data_dir)
    source_root = data_dir / "source"
    replay_root = data_dir / "replay"
    config = prepare_validation_config(
        profile,
        ticks=ticks,
        output_dir=output_dir,
        data_dir=data_dir,
        approve_live=approve_live,
    )
    for root, label_name in ((source_root, "source"), (replay_root, "replay")):
        if root.exists() and any(root.iterdir()):
            raise ValidationInputError(
                f"{label_name} run root must be absent or empty")
        root.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    load_dotenv(ROOT / ".env")
    readiness = validate_llm_config(config, raise_on_error=False)
    if not readiness["ready"]:
        raise RuntimeError(
            "configuration is not ready: " + "; ".join(readiness["errors"]))
    live = uses_paid_providers(config)
    preflight: dict[str, object] = {
        "ready": True,
        "mode": readiness["mode"],
        "routed_providers": readiness["routed_providers"],
        "route_contract": readiness["route_contract"],
        "live_checked": False,
        "live_ready": not live,
    }
    if live:
        live_preflight = asyncio.run(provider_preflight(config, live=True))
        preflight.update({
            "live_checked": True,
            "live_ready": bool(live_preflight.get("live_ready")),
        })
        if not preflight["live_ready"]:
            raise RuntimeError("live provider preflight failed")

    profile_config = load_config(profile)
    normalized_config = _normalized_config(config, artifact_root)
    sampler = _MemorySampler()
    sampler.start()
    source_world = None
    source_store = None
    replay_world = None
    replay_store = None
    checkpoint_records: list[dict[str, object]] = []
    tick_records: list[dict[str, object]] = []
    source_path: Path | None = None
    replay_path: Path | None = None
    try:
        sampler.stage = "genesis"
        genesis_started = time.perf_counter()
        source_store, source_world, source_run_id = open_run(
            config, None, None, data_dir=source_root)
        source_path = Path(source_store.path).resolve()
        genesis_wall_s = time.perf_counter() - genesis_started
        genesis_database = _database_snapshot(source_store)
        original_checkpoint = source_world.checkpoint
        original_checkpoint_async = source_world.checkpoint_async

        def record_checkpoint(
            tick: int,
            reason: str,
            before: list[dict[str, object]],
            started: float,
            result: str | None,
        ) -> None:
            checkpoint_path = Path(result).resolve() if result else None
            manifest = Path(f"{checkpoint_path}.manifest.json") \
                if checkpoint_path else None
            checkpoint_records.append({
                "tick": int(tick),
                "reason": reason,
                "duration_s": round(time.perf_counter() - started, 6),
                "source_before": before,
                "source_after": _database_files(source_path),
                "artifact": (
                    _artifact_id(checkpoint_path, artifact_root)
                    if checkpoint_path else None),
                "bytes": (
                    checkpoint_path.stat().st_size if checkpoint_path else None),
                "manifest_artifact": (
                    _artifact_id(manifest, artifact_root)
                    if manifest and manifest.is_file() else None),
            })

        def measured_checkpoint(
            tick: int, reason: str = "interval",
        ) -> str | None:
            before = _database_files(source_path)
            started = time.perf_counter()
            result = original_checkpoint(tick, reason=reason)
            record_checkpoint(tick, reason, before, started, result)
            return result

        async def measured_checkpoint_async(
            tick: int, reason: str = "interval",
        ) -> str | None:
            before = _database_files(source_path)
            started = time.perf_counter()
            result = await original_checkpoint_async(tick, reason=reason)
            record_checkpoint(tick, reason, before, started, result)
            return result

        def record_tick(tick: int, summary: dict[str, object]) -> None:
            tick_records.append({
                "tick": int(tick),
                "wall_s": float(summary.get("wall_s", 0.0)),
                "rss_mb": round(
                    sampler.process.memory_info().rss / (1024 ** 2), 2),
                "database": _database_snapshot(source_store),
            })
            if tick >= ticks:
                source_world.request_stop()

        source_world.checkpoint = measured_checkpoint
        source_world.checkpoint_async = measured_checkpoint_async
        source_world.on_tick = record_tick
        sampler.stage = "source_run"
        source_started = time.perf_counter()
        asyncio.run(source_world.run(max_ticks=ticks))
        source_wall_s = time.perf_counter() - source_started
        source_meta = dict(source_store.get_meta())
        population = _inspect_population(source_store)
        communications = _inspect_communications(source_store)
        providers = _inspect_providers(source_store)
        ledger_ok, ledger_diagnostic = source_world.economy.ledger.reconcile()
        governor = source_world.gateway.governor.status()
        final_open_database = _database_snapshot(source_store)
        source_world.close()
        source_world = None
        source_store = None
        finalize_sqlite_artifact(source_path)
        source_hash_before = _sha256_file(source_path)
        source_manifest_before = _artifact_manifest(
            source_root, artifact_root, role="source")
        integrity = _read_only_integrity(source_path)

        sampler.stage = "replay"
        replay_started = time.perf_counter()
        with _read_only_tree(source_root):
            replay_store, replay_world, replay_run_id = open_run(
                {},
                None,
                source_run_id,
                data_dir=replay_root,
                replay_source_dir=source_root,
            )
            replay_path = Path(replay_store.path).resolve()
            asyncio.run(replay_headless(replay_world, ticks))
            replay_tracker = replay_world.gateway.replay_execution_stats()
            replay_world.close()
            replay_world = None
            replay_store = None
            finalize_sqlite_artifact(replay_path)
            replay_proof = verify_replay(source_path, replay_path)
        replay_wall_s = time.perf_counter() - replay_started
        source_hash_after = _sha256_file(source_path)
        source_manifest_after = _artifact_manifest(
            source_root, artifact_root, role="source")
        replay_manifest = _artifact_manifest(
            replay_root, artifact_root, role="replay")
    finally:
        if replay_world is not None:
            replay_world.close()
        elif replay_store is not None:
            replay_store.close()
        if source_world is not None:
            source_world.close()
        elif source_store is not None:
            source_store.close()
        sampler.stage = "finalize"
        memory = sampler.stop()

    assert source_path is not None and replay_path is not None
    conversation_pairs = int(config["budget"]["conversation_pairs"])
    conversation_turns = int(config["conversations"]["turns"])
    expected_provider = (
        config.get("llm", {}).get("route_contract")
        or config.get("llm", {}).get("default_route")
        or {"provider": "scripted", "model": "scripted"}
    )
    actual_pairs = {
        (str(row["provider"]), str(row["model"]))
        for row in providers["pairs"]
    }
    expected_pair = {
        (str(expected_provider["provider"]), str(expected_provider["model"]))
    }
    checks = {
        "target_tick_completed": (
            int(source_meta["tick"]) == ticks
            and source_meta["active_tick"] is None
            and str(source_meta["status"]) == "finished"
        ),
        "population_exact": population == EXPECTED_POPULATION,
        "communications_exact": (
            communications["conversations"] == ticks * conversation_pairs
            and communications["messages"]
            == ticks * conversation_pairs * conversation_turns
            and communications["invalid_message_memberships"] == 0
            and communications["empty_messages"] == 0
            and communications["message_count_per_conversation"]
            == [conversation_turns]
        ),
        "provider_model_exact": actual_pairs == expected_pair,
        "spend_contract": (
            (
                providers["cost_usd"] > 0
                and providers["cost_usd"] <= float(config["budget"]["cap_usd"])
                and float(governor["total_spend_usd"])
                <= float(config["budget"]["cap_usd"])
            ) if live else (
                providers["cost_usd"] == 0.0
                and float(governor["total_spend_usd"]) == 0.0
            )
        ),
        "ledger_reconciles": bool(ledger_ok),
        "sqlite_quick_check": integrity["quick_check"] == ["ok"],
        "foreign_keys_clean": integrity["foreign_key_violations"] == [],
        "no_sqlite_sidecars": integrity["sqlite_sidecars"] == [],
        "no_failure_events": integrity["failure_events"] == {},
        "checkpoint_succeeded": bool(checkpoint_records) and all(
            row["artifact"] and row["manifest_artifact"]
            for row in checkpoint_records
        ),
        "database_growth_measured": (
            final_open_database["logical_used_bytes"]
            > genesis_database["logical_used_bytes"]
        ),
        "exact_replay": (
            replay_proof["exact"] is True
            and replay_proof["differences"] == []
            and int(replay_proof["source_tick"]) == ticks
            and int(replay_proof["replay_tick"]) == ticks
            and replay_proof["source_hash"] == replay_proof["replay_hash"]
        ),
        "replay_no_live_dispatch": int(
            replay_tracker.get("live_dispatch_count", -1)) == 0,
        "source_immutable_during_replay": (
            source_hash_before == source_hash_after
            and source_manifest_before == source_manifest_after
        ),
        "memory_measured": (
            int(memory["samples"]) > 0 and float(memory["peak_rss_mb"]) > 0),
        "live_preflight": (
            bool(preflight["live_checked"] and preflight["live_ready"])
            if live else not preflight["live_checked"]),
    }
    receipt_name = f"{label}-{source_run_id}.runtime.json"
    receipt_path = output_dir / receipt_name
    receipt: dict[str, object] = {
        "schema": SCHEMA,
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "label": label,
        "profile_path": profile.relative_to(ROOT).as_posix(),
        "profile_sha256": _sha256_file(profile),
        "profile_config_sha256": _sha256_bytes(
            _canonical_json(profile_config).encode("utf-8")),
        "effective_config_sha256": _sha256_bytes(
            _canonical_json(normalized_config).encode("utf-8")),
        "effective_config": normalized_config,
        "source_commit": _git_head(),
        "configuration": {
            "ticks": ticks,
            "live": live,
            "hard_cap_usd": float(config["budget"]["cap_usd"]),
            "checkpoint_every": int(config["checkpoint_every"]),
            "checkpoint_keep_last": int(config["checkpoint_keep_last"]),
            "conversation_pairs": conversation_pairs,
            "conversation_turns": conversation_turns,
            "route_contract": config.get("llm", {}).get("route_contract"),
            "default_route": config.get("llm", {}).get("default_route"),
        },
        "preflight": preflight,
        "artifacts": {
            "runtime_receipt": _artifact_id(receipt_path, artifact_root),
        },
        "source": {
            "run_id": source_run_id,
            "database": _artifact_id(source_path, artifact_root),
            "status": str(source_meta["status"]),
            "tick": int(source_meta["tick"]),
            "active_tick": source_meta["active_tick"],
            "sha256_before_replay": source_hash_before,
            "sha256_after_replay": source_hash_after,
            "artifact_manifest_before_replay": source_manifest_before,
            "artifact_manifest_after_replay": source_manifest_after,
        },
        "replay": {
            "run_id": replay_run_id,
            "database": _artifact_id(replay_path, artifact_root),
            "wall_s": round(replay_wall_s, 6),
            "proof": replay_proof,
            "execution": replay_tracker,
            "artifact_manifest": replay_manifest,
        },
        "runtime": {
            "genesis_wall_s": round(genesis_wall_s, 6),
            "source_wall_s": round(source_wall_s, 6),
            "ticks": tick_records,
            "checkpoints": checkpoint_records,
            "memory": memory,
            "database": {
                "genesis": genesis_database,
                "final_open": final_open_database,
                "final_closed": _database_files(source_path),
                "logical_used_growth_bytes": (
                    int(final_open_database["logical_used_bytes"])
                    - int(genesis_database["logical_used_bytes"])),
            },
        },
        "population": population,
        "communications": communications,
        "providers": providers,
        "governor": governor,
        "integrity": {
            **integrity,
            "ledger_ok": bool(ledger_ok),
            "ledger_diagnostic": ledger_diagnostic,
        },
        "checks": checks,
        "passed": all(checks.values()),
    }
    validate_receipt_safety(receipt, secret_values=_secret_values(config))
    _atomic_write_json(receipt_path, receipt)
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one maintained scale profile and exact offline replay")
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--ticks", type=int, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument(
        "--approve-live-inference",
        action="store_true",
        help="explicitly authorize a maintained paid two-tick canary",
    )
    return parser


def main() -> None:
    parser = _parser()
    args = parser.parse_args()
    try:
        receipt = run_validation(
            args.profile,
            ticks=args.ticks,
            label=args.label,
            output_dir=args.output_dir,
            data_dir=args.data_dir,
            approve_live=args.approve_live_inference,
        )
    except ValidationInputError as exc:
        parser.error(str(exc))
    print(json.dumps({
        "receipt": receipt["artifacts"]["runtime_receipt"],
        "source_run_id": receipt["source"]["run_id"],
        "replay_run_id": receipt["replay"]["run_id"],
        "passed": receipt["passed"],
        "tick": receipt["source"]["tick"],
        "calls": receipt["providers"]["calls"],
        "spend_usd": receipt["providers"]["cost_usd"],
        "replay_exact": receipt["replay"]["proof"]["exact"],
    }, indent=2, sort_keys=True))
    if not receipt["passed"]:
        raise SystemExit(5)


if __name__ == "__main__":
    main()
