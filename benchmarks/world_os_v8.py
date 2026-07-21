"""Executable, versioned performance receipt for World OS semantics 8.

The workload uses the production command facade, delivery phase, authorized
inbox projection, causal projection, and snapshot builders. Provider latency is
intentionally excluded and is recorded by the separate provider smoke receipt.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import psutil

from communications.delivery import CommunicationDelivery
from communications.policy import Principal
from communications.projections import AgentKnowledgeProjection
from engine.actions import ActionExecutor
from engine.store import Store
from research.hashing import canonical_hashes
from server.projections.causal import build_causal_projection
from server.projections.snapshot import build_snapshot


RECEIPT_SCHEMA = "world-os-v8-benchmark-receipt-v1"


def nearest_rank(values: list[float], percentile: float) -> float:
    """Return the declared nearest-rank percentile for a non-empty sample."""
    if not values:
        raise ValueError("percentile sample must not be empty")
    if not 0 < float(percentile) <= 100:
        raise ValueError("percentile must be in (0, 100]")
    ordered = sorted(float(value) for value in values)
    rank = max(1, math.ceil((float(percentile) / 100.0) * len(ordered)))
    return ordered[rank - 1]


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def process_tree_rss_bytes(process: psutil.Process | None = None) -> int:
    """Sample resident bytes for this process and every live child."""
    root = process or psutil.Process(os.getpid())
    processes = [root, *root.children(recursive=True)]
    total = 0
    for item in processes:
        try:
            total += int(item.memory_info().rss)
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
    return total


def machine_receipt() -> dict[str, Any]:
    return {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        "processor_signature": platform.processor(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "sqlite": sqlite3.sqlite_version,
        "physical_cores": psutil.cpu_count(logical=False),
        "logical_cores": psutil.cpu_count(logical=True),
        "memory_bytes": int(psutil.virtual_memory().total),
        "pid": os.getpid(),
    }


def machine_class_matches(expected: dict[str, Any], actual: dict[str, Any]) -> bool:
    compared = (
        "platform",
        "processor_signature",
        "python",
        "sqlite",
        "physical_cores",
        "logical_cores",
        "memory_bytes",
    )
    return all(actual.get(key) == expected.get(key) for key in compared)


def _new_workload(path: Path, *, strategic_agents: int, periphery_agents: int, seed: int):
    config = {
        "engine_semantics_version": 8,
        "communications": {"autonomous_scripted_enabled": False},
    }
    store = Store(str(path))
    store.init_run_meta("world-os-v8-benchmark", int(seed), config)
    rows = []
    for index in range(int(strategic_agents) + int(periphery_agents)):
        tier = "core" if index < int(strategic_agents) else "periphery"
        rows.append((
            f"Benchmark Agent {index + 1}", "citizen", "analyst", "analyst",
            35, "healthy", 1, 0, tier,
        ))
    store.executemany(
        "INSERT INTO agents "
        "(name,kind,occupation,role,age,health,alive,arrived_tick,population_tier) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        rows,
    )
    store.commit()
    economy = SimpleNamespace(store=store, config=config)
    return (
        store,
        ActionExecutor(economy),
        CommunicationDelivery(store, config),
        AgentKnowledgeProjection(store, config),
        list(range(1, int(strategic_agents) + 1)),
        list(range(int(strategic_agents) + 1, int(strategic_agents) + int(periphery_agents) + 1)),
    )


def _send_direct(
    executor: ActionExecutor,
    *,
    tick: int,
    sender: int,
    recipient: int,
    body_characters: int,
) -> int:
    body = f"Tick {tick} operational coordination. ".ljust(int(body_characters), "x")
    result = executor.execute_action(
        int(tick),
        int(sender),
        {
            "type": "send_message",
            "audience": {"kind": "direct", "agent_ids": [int(recipient)]},
            "subject": f"Coordination tick {tick}",
            "body": body,
        },
        phase="EXECUTION",
    )
    if not result.get("ok"):
        raise RuntimeError(f"benchmark communication rejected: {result}")
    return int(result["message_id"])


def _finalize_tick(store: Store, tick: int) -> None:
    store.set_meta(tick=int(tick), status="running", phase="FINALIZE", active_tick=None)
    store.execute(
        "INSERT OR IGNORE INTO projection_commits (tick,phase,domains_json) "
        "VALUES (?,'FINALIZE','[\"summary\",\"events\",\"communications\",\"causal\"]')",
        (int(tick),),
    )
    store.commit()


def _run_tick(
    *,
    store: Store,
    executor: ActionExecutor,
    delivery: CommunicationDelivery,
    inbox: AgentKnowledgeProjection,
    strategic_ids: list[int],
    periphery_ids: list[int],
    tick: int,
    strategic_senders: int,
    periphery_wakes: int,
    body_characters: int,
) -> None:
    delivery.deliver_due(int(tick))
    for agent_id in strategic_ids:
        inbox.build(agent_id, int(tick))
    waking = [
        periphery_ids[(int(tick) * int(periphery_wakes) + offset) % len(periphery_ids)]
        for offset in range(int(periphery_wakes))
    ] if periphery_ids else []
    for agent_id in waking:
        inbox.build(agent_id, int(tick))

    all_ids = [*strategic_ids, *periphery_ids]
    senders = [
        strategic_ids[(int(tick) * int(strategic_senders) + offset) % len(strategic_ids)]
        for offset in range(int(strategic_senders))
    ]
    for sender in [*senders, *waking]:
        recipient = all_ids[int(sender) % len(all_ids)]
        _send_direct(
            executor,
            tick=int(tick),
            sender=int(sender),
            recipient=int(recipient),
            body_characters=int(body_characters),
        )
    _finalize_tick(store, int(tick))


def _footprint_bytes(directory: Path) -> int:
    return sum(path.stat().st_size for path in directory.rglob("*") if path.is_file())


def _timed(callable_) -> float:
    started = time.perf_counter()
    callable_()
    return time.perf_counter() - started


def _query_plans(store: Store, *, tick: int, recipient: int) -> dict[str, list[str]]:
    statements = {
        "due_messages": (
            "SELECT id FROM comm_messages WHERE status='queued' AND deliver_at_tick<=? "
            "ORDER BY deliver_at_tick,created_tick,id",
            (int(tick),),
        ),
        "authorized_inbox": (
            "SELECT d.id FROM comm_deliveries d JOIN comm_messages m ON m.id=d.message_id "
            "WHERE d.recipient_agent_id=? AND d.delivery_status='delivered' "
            "AND d.delivery_tick<=? ORDER BY d.delivery_tick,d.id LIMIT 50",
            (int(recipient), int(tick)),
        ),
        "thread_messages": (
            "SELECT id FROM comm_messages WHERE thread_id=? AND created_tick<=? ORDER BY id",
            (1, int(tick)),
        ),
    }
    return {
        name: [str(row["detail"]) for row in store.query(f"EXPLAIN QUERY PLAN {sql}", params)]
        for name, (sql, params) in statements.items()
    }


def run_interactive_repetition(manifest: dict[str, Any], repetition: int) -> dict[str, Any]:
    workload = manifest["interactive"]
    communication = manifest["communication"]
    with tempfile.TemporaryDirectory(prefix=f"world-os-v8-interactive-{repetition}-") as raw:
        root = Path(raw)
        store, executor, delivery, inbox, strategic, periphery = _new_workload(
            root / "world.db",
            strategic_agents=int(workload["agents"]),
            periphery_agents=0,
            seed=int(manifest["seed"]),
        )
        samples = []
        peak_rss = process_tree_rss_bytes()
        try:
            for tick in range(1, int(workload["ticks_per_repetition"]) + 1):
                samples.append(_timed(lambda tick=tick: _run_tick(
                    store=store,
                    executor=executor,
                    delivery=delivery,
                    inbox=inbox,
                    strategic_ids=strategic,
                    periphery_ids=periphery,
                    tick=tick,
                    strategic_senders=len(strategic),
                    periphery_wakes=0,
                    body_characters=int(communication["body_characters"]),
                )))
                peak_rss = max(peak_rss, process_tree_rss_bytes())
            return {
                "tick_seconds": samples,
                "peak_process_tree_rss_bytes": peak_rss,
                "run_footprint_bytes": _footprint_bytes(root),
            }
        finally:
            store.close()


def run_scale_repetition(manifest: dict[str, Any], repetition: int) -> dict[str, Any]:
    workload = manifest["scale"]
    projections = manifest["projections"]
    communication = manifest["communication"]
    with tempfile.TemporaryDirectory(prefix=f"world-os-v8-scale-{repetition}-") as raw:
        root = Path(raw)
        store, executor, delivery, inbox, strategic, periphery = _new_workload(
            root / "world.db",
            strategic_agents=int(workload["strategic_agents"]),
            periphery_agents=int(workload["periphery_agents"]),
            seed=int(manifest["seed"]),
        )
        principal = Principal("benchmark", agent_id=strategic[0])
        freshness = []
        peak_rss = process_tree_rss_bytes()
        started = time.perf_counter()
        try:
            first_sample_tick = (
                int(workload["ticks"]) - int(projections["freshness_samples"]) + 1
            )
            for tick in range(1, int(workload["ticks"]) + 1):
                _run_tick(
                    store=store,
                    executor=executor,
                    delivery=delivery,
                    inbox=inbox,
                    strategic_ids=strategic,
                    periphery_ids=periphery,
                    tick=tick,
                    strategic_senders=int(workload["strategic_senders_per_tick"]),
                    periphery_wakes=int(workload["periphery_wakes_per_tick"]),
                    body_characters=int(communication["body_characters"]),
                )
                if tick >= first_sample_tick:
                    freshness.append(_timed(lambda tick=tick: build_snapshot(
                        store,
                        principal,
                        as_of_tick=tick,
                        domains=("summary", "events", "communications"),
                    )))
                peak_rss = max(peak_rss, process_tree_rss_bytes())
            elapsed = time.perf_counter() - started

            final_tick = int(workload["ticks"])
            snapshot_call = lambda: build_snapshot(
                store,
                principal,
                as_of_tick=final_tick,
                domains=("summary", "alerts", "communications", "events"),
            )
            inbox_call = lambda: inbox.build(strategic[0], final_tick)
            first_message = store.query_one(
                "SELECT id,sender_agent_id FROM comm_messages ORDER BY id LIMIT 1")
            causal_principal = Principal(
                f"agent:{int(first_message['sender_agent_id'])}",
                agent_id=int(first_message["sender_agent_id"]),
            )
            causal_call = lambda: build_causal_projection(
                store,
                causal_principal,
                "message",
                int(first_message["id"]),
                as_of_tick=final_tick,
                depth=int(projections["causal_depth"]),
            )
            snapshot_call()
            inbox_call()
            causal_call()
            route_seconds = [
                _timed(snapshot_call) for _ in range(int(projections["route_samples"]))
            ]
            inbox_seconds = [
                _timed(inbox_call) for _ in range(int(projections["route_samples"]))
            ]
            causal_seconds = [
                _timed(causal_call) for _ in range(int(projections["route_samples"]))
            ]
            counts = {
                table: int(store.scalar(f"SELECT COUNT(*) FROM {table}", default=0))
                for table in (
                    "agents", "action_proposals", "comm_messages", "comm_deliveries",
                    "comm_disclosures", "memories", "causal_links", "events",
                )
            }
            return {
                "run_seconds": elapsed,
                "peak_process_tree_rss_bytes": peak_rss,
                "run_footprint_bytes": _footprint_bytes(root),
                "projection_freshness_seconds": freshness,
                "route_bootstrap_seconds": route_seconds,
                "inbox_seconds": inbox_seconds,
                "causal_seconds": causal_seconds,
                "canonical_hashes": canonical_hashes(store),
                "counts": counts,
                "query_plans": _query_plans(
                    store, tick=final_tick, recipient=strategic[0]),
            }
        finally:
            store.close()


def evaluate_gates(
    measurements: dict[str, float],
    budgets: dict[str, float],
    *,
    canonical_hashes_equal: bool,
    machine_match: bool,
) -> dict[str, dict[str, Any]]:
    mapping = {
        "interactive_tick_p95": (
            measurements["interactive_tick_p95_seconds"],
            budgets["interactive_tick_p95_seconds"],
        ),
        "interactive_tick_p99": (
            measurements["interactive_tick_p99_seconds"],
            budgets["interactive_tick_p99_seconds"],
        ),
        "scale_run": (
            measurements["scale_run_max_seconds"], budgets["scale_run_seconds"]),
        "peak_process_tree_rss": (
            measurements["peak_process_tree_rss_bytes"],
            budgets["peak_process_tree_rss_bytes"],
        ),
        "run_footprint": (
            measurements["run_footprint_bytes"], budgets["run_footprint_bytes"]),
        "projection_freshness_p95": (
            measurements["projection_freshness_p95_seconds"],
            budgets["projection_freshness_p95_seconds"],
        ),
        "route_bootstrap_p95": (
            measurements["route_bootstrap_p95_seconds"],
            budgets["route_bootstrap_p95_seconds"],
        ),
        "inbox_p95": (
            measurements["inbox_p95_seconds"], budgets["inbox_p95_seconds"],
        ),
        "causal_p95": (
            measurements["causal_p95_seconds"], budgets["causal_p95_seconds"],
        ),
    }
    gates = {
        name: {"actual": actual, "limit": limit, "passed": actual <= limit}
        for name, (actual, limit) in mapping.items()
    }
    gates["canonical_hashes_equal"] = {
        "actual": canonical_hashes_equal,
        "limit": True,
        "passed": canonical_hashes_equal,
    }
    gates["machine_class_match"] = {
        "actual": machine_match,
        "limit": True,
        "passed": machine_match,
    }
    return gates


def run_standard(manifest_path: str | Path, output_path: str | Path) -> dict[str, Any]:
    manifest_path = Path(manifest_path).resolve()
    output_path = Path(output_path).resolve()
    root = manifest_path.parent.parent
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    actual_machine = machine_receipt()

    interactive_runs = [
        run_interactive_repetition(manifest, repetition)
        for repetition in range(1, int(manifest["interactive"]["repetitions"]) + 1)
    ]
    scale_runs = [
        run_scale_repetition(manifest, repetition)
        for repetition in range(1, int(manifest["scale"]["repetitions"]) + 1)
    ]

    interactive_samples = [
        value for run in interactive_runs for value in run["tick_seconds"]
    ]
    freshness_samples = [
        value for run in scale_runs for value in run["projection_freshness_seconds"]
    ]
    route_samples = [
        value for run in scale_runs for value in run["route_bootstrap_seconds"]
    ]
    inbox_samples = [value for run in scale_runs for value in run["inbox_seconds"]]
    causal_samples = [value for run in scale_runs for value in run["causal_seconds"]]
    measurements = {
        "interactive_tick_p95_seconds": nearest_rank(interactive_samples, 95),
        "interactive_tick_p99_seconds": nearest_rank(interactive_samples, 99),
        "scale_run_max_seconds": max(float(run["run_seconds"]) for run in scale_runs),
        "scale_run_p95_seconds": nearest_rank(
            [float(run["run_seconds"]) for run in scale_runs], 95),
        "peak_process_tree_rss_bytes": max(
            int(run["peak_process_tree_rss_bytes"])
            for run in [*interactive_runs, *scale_runs]
        ),
        "run_footprint_bytes": max(
            int(run["run_footprint_bytes"])
            for run in [*interactive_runs, *scale_runs]
        ),
        "projection_freshness_p95_seconds": nearest_rank(freshness_samples, 95),
        "route_bootstrap_p95_seconds": nearest_rank(route_samples, 95),
        "inbox_p95_seconds": nearest_rank(inbox_samples, 95),
        "causal_p95_seconds": nearest_rank(causal_samples, 95),
    }
    hash_receipts = [
        json.dumps(run["canonical_hashes"], sort_keys=True, separators=(",", ":"))
        for run in scale_runs
    ]
    hashes_equal = len(set(hash_receipts)) == 1
    match = machine_class_matches(manifest["machine_class"], actual_machine)
    gates = evaluate_gates(
        measurements,
        manifest["budgets"],
        canonical_hashes_equal=hashes_equal,
        machine_match=match,
    )
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "manifest_sha256": sha256_file(manifest_path),
        "machine": actual_machine,
        "dependency_sha256": {
            relative: sha256_file(root / relative)
            for relative in manifest["dependencies"]
        },
        "fixture_sha256": {
            relative: sha256_file(root / relative)
            for relative in manifest["fixtures"]
        },
        "raw_samples": {
            "interactive_runs": interactive_runs,
            "scale_runs": scale_runs,
        },
        "measurements": measurements,
        "query_plans": scale_runs[-1]["query_plans"],
        "gates": gates,
        "status": "passed" if all(gate["passed"] for gate in gates.values()) else "failed",
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt
