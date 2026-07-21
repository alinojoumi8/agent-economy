"""Paired-seed counterfactual runner with bootstrap intervals and causal traces."""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import random
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from engine.store import Store, load_json
from research.datasets import ingest_manifest
from research.scenarios import ScenarioPack, load_scenario
from run_config import deep_merge
from world.loop import World


def _event_hash(store: Store, *, through_tick: int | None = None) -> str:
    sql = "SELECT tick,phase,kind,payload_json,subject_type,subject_id FROM events"
    params: tuple[Any, ...] = ()
    if through_tick is not None:
        sql += " WHERE tick<=?"
        params = (through_tick,)
    sql += " ORDER BY id"
    payload = [dict(row) for row in store.query(sql, params)]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _bootstrap_interval(values: list[float], *, samples: int = 2000,
                        seed: int = 8675309) -> tuple[float, float]:
    if not values:
        return (0.0, 0.0)
    rng = random.Random(seed)
    means = sorted(statistics.fmean(rng.choice(values) for _ in values) for _ in range(samples))
    return means[max(0, int(samples * 0.025) - 1)], means[min(samples - 1, int(samples * 0.975))]


def paired_summary(results: list[dict[str, Any]], baseline_arm: str,
                   *, bootstrap_samples: int = 2000) -> dict[str, Any]:
    by_arm_seed = {(str(row["arm"]), int(row["seed"])): row for row in results}
    arms = sorted({str(row["arm"]) for row in results})
    seeds = sorted({int(row["seed"]) for row in results})
    metrics = sorted({key for row in results for key in row.get("metrics", {})})
    output: dict[str, Any] = {"baseline_arm": baseline_arm, "paired_seeds": seeds,
                              "arms": arms, "metrics": {}}
    for metric in metrics:
        metric_result = {}
        for arm in arms:
            values = [by_arm_seed[(arm, seed)]["metrics"].get(metric)
                      for seed in seeds if (arm, seed) in by_arm_seed]
            clean = [float(value) for value in values if value is not None]
            metric_result[arm] = {
                "n": len(clean), "mean": statistics.fmean(clean) if clean else None,
                "median": statistics.median(clean) if clean else None,
                "min": min(clean) if clean else None, "max": max(clean) if clean else None,
            }
            if arm == baseline_arm:
                continue
            differences = []
            for seed in seeds:
                treatment = by_arm_seed.get((arm, seed), {}).get("metrics", {}).get(metric)
                control = by_arm_seed.get((baseline_arm, seed), {}).get("metrics", {}).get(metric)
                if treatment is not None and control is not None:
                    differences.append(float(treatment) - float(control))
            lo, hi = _bootstrap_interval(differences, samples=bootstrap_samples,
                                         seed=seed_from(metric, arm))
            mean = statistics.fmean(differences) if differences else 0.0
            sd = statistics.pstdev(differences) if len(differences) > 1 else 0.0
            metric_result[arm]["paired_effect"] = {
                "mean_difference": mean, "ci95_bootstrap": [lo, hi],
                "standardized_effect": mean / sd if sd > 0 else 0.0,
                "differences": differences,
            }
        output["metrics"][metric] = metric_result
    return output


def seed_from(*parts: str) -> int:
    return int(hashlib.sha256("|".join(parts).encode()).hexdigest()[:8], 16)


def _causal_trace(store: Store) -> list[dict[str, Any]]:
    treatment = store.query("SELECT id,tick,kind,payload_json FROM events WHERE kind IN "
                            "('shock_fired','policy_rule_change','epidemic_started') ORDER BY id")
    trace = []
    for source in treatment:
        outcomes = [dict(row) for row in store.query(
            "SELECT id,tick,kind,subject_type,subject_id,importance FROM events "
            "WHERE id>? AND tick BETWEEN ? AND ? AND importance>=2 ORDER BY id LIMIT 50",
            (source["id"], source["tick"], int(source["tick"]) + 30))]
        trace.append({"source_event_id": int(source["id"]), "tick": int(source["tick"]),
                      "kind": source["kind"], "payload": load_json(source["payload_json"], {}),
                      "downstream_events": outcomes})
    return trace


def _arm_config(
    pack: ScenarioPack, arm: str, effective_config: dict[str, Any],
) -> dict[str, Any]:
    overrides = pack.arms[arm].get("config_overrides", {})
    if not isinstance(overrides, dict):
        raise ValueError(f"scenario arm {arm} config_overrides must be an object")
    return deep_merge(json.loads(json.dumps(effective_config)), overrides)


def _run_arm(pack: ScenarioPack, seed: int, arm: str, data_dir: Path, ticks: int,
             effective_config: dict[str, Any]) -> dict[str, Any]:
    config = _arm_config(pack, arm, effective_config)
    config.update({"seed": seed, "checkpoint_every": 0, "speed_delay_s": 0.0,
                   "dataset_manifest": pack.dataset_manifest,
                   "scenario": {"key": pack.key, "version": pack.version, "arm": arm}})
    config["shocks"] = list(pack.common_shocks) + list(pack.arms[arm].get("shocks", []))
    run_id = f"{pack.key}-s{seed}-{arm}"
    path = data_dir / f"{run_id}.db"
    if path.exists():
        path.unlink()
    store = Store(str(path))
    store.init_run_meta(run_id, seed, config)
    world = World(store, config)
    world.initialize()
    ingest_manifest(store, pack.dataset_manifest)
    store.insert("scenario_packs", scenario_key=pack.key, version=pack.version,
                 title=pack.title, manifest_path=pack.path,
                 manifest_checksum=pack.checksum_sha256, limitations=pack.limitations,
                 metadata_json=json.dumps({"arm": arm}, sort_keys=True))
    genesis_hash = _event_hash(store, through_tick=0)
    asyncio.run(world.run(max_ticks=ticks))
    ok, diagnostic = world.economy.ledger.reconcile()
    metrics = {name: store.metric_latest(name, None) for name in pack.metrics}
    external_agent_influenced = bool(
        store.get_meta()["external_agent_influenced"])
    result = {"run_id": run_id, "seed": seed, "arm": arm, "ticks": store.tick,
              "reconciled": ok, "reconciliation": diagnostic, "metrics": metrics,
              "genesis_hash": genesis_hash, "replay_hash": _event_hash(store),
              "causal_trace": _causal_trace(store),
              "external_agent_influenced": external_agent_influenced}
    store.close()
    return result


def run_counterfactual(scenario_path: str | Path | ScenarioPack, *, seeds: int | list[int] = 20,
                       ticks: int | None = None, out_dir: str | Path = "reports/out",
                       data_root: str | Path = "data/counterfactuals",
                       effective_config: dict[str, Any] | None = None) -> dict[str, Any]:
    pack = (scenario_path if isinstance(scenario_path, ScenarioPack)
            else load_scenario(scenario_path))
    resolved_config = (pack.config() if effective_config is None
                       else effective_config)
    paired_seeds = list(range(1, seeds + 1)) if isinstance(seeds, int) else [int(s) for s in seeds]
    horizon = int(ticks or pack.ticks)
    data_dir = Path(data_root) / pack.key
    data_dir.mkdir(parents=True, exist_ok=True)
    results = [_run_arm(pack, seed, arm, data_dir, horizon, resolved_config)
               for seed in paired_seeds for arm in pack.arms]
    influenced = [
        str(row.get("run_id", "")) for row in results
        if bool(row.get("external_agent_influenced", False))
    ]
    if influenced:
        raise RuntimeError(
            "external-agent-influenced runs cannot be used as branch-causal "
            f"evidence: {', '.join(influenced)}")
    for seed in paired_seeds:
        hashes = {row["genesis_hash"] for row in results if row["seed"] == seed}
        if len(hashes) != 1:
            raise RuntimeError(f"paired arms for seed {seed} did not fork identical genesis state")
    baseline = "control" if "control" in pack.arms else next(iter(pack.arms))
    summary = paired_summary(results, baseline)
    checkpoint_hash = hashlib.sha256(json.dumps(
        {seed: next(row["genesis_hash"] for row in results if row["seed"] == seed)
         for seed in paired_seeds}, sort_keys=True).encode()).hexdigest()
    created = datetime.now(timezone.utc).isoformat()
    payload = {
        "scenario": {"key": pack.key, "version": pack.version, "title": pack.title,
                     "manifest_checksum": pack.checksum_sha256,
                     "dataset_manifest": pack.dataset_manifest},
        "design": {"paired_seeds": paired_seeds, "ticks": horizon,
                   "declared_treatments": {arm: data.get("treatment_variables", {})
                                           for arm, data in pack.arms.items()},
                   "declared_config_overrides": {
                       arm: data.get("config_overrides", {})
                       for arm, data in pack.arms.items()},
                   "checkpoint_hash": checkpoint_hash},
        "results": results, "summary": summary, "limitations": pack.limitations,
        "created_at": created,
    }
    target_dir = Path(out_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    json_path = target_dir / f"counterfactual_{pack.key}.json"
    json_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    md_path = target_dir / f"counterfactual_{pack.key}.md"
    md_path.write_text(_markdown_report(payload), encoding="utf-8")
    payload["artifacts"] = {"json": str(json_path), "markdown": str(md_path)}
    return payload


def _markdown_report(payload: dict[str, Any]) -> str:
    lines = [f"# {payload['scenario']['title']}", "", payload["limitations"], "",
             f"Paired seeds: {len(payload['design']['paired_seeds'])}; ticks: {payload['design']['ticks']}", "",
             "| Metric | Arm | Mean | Paired effect | 95% bootstrap interval |", "|---|---:|---:|---:|---:|"]
    baseline = payload["summary"]["baseline_arm"]
    for metric, arms in payload["summary"]["metrics"].items():
        for arm, values in arms.items():
            effect = values.get("paired_effect")
            lines.append(f"| {metric} | {arm} | {values['mean']} | "
                         f"{effect['mean_difference'] if effect else ('baseline' if arm == baseline else '')} | "
                         f"{effect['ci95_bootstrap'] if effect else ''} |")
    lines.extend(["", "## Validity boundary", "",
                  "Effects are model-conditional. The paired design isolates declared treatment variables inside this simulation; it does not identify real-world causal effects."])
    return "\n".join(lines)
