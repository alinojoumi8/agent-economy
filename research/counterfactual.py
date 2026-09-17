"""Paired-seed counterfactual runner with bootstrap intervals and causal traces."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from engine.store import Store, load_json
from research.analysis import paired_summary, seed_from, _bootstrap_interval
from research.artifacts import create_batch, publish_bytes, publish_json, safe_key
from research.attempts import execute_attempt, verify_attempt
from research.scenarios import ScenarioPack, load_scenario
from run_config import deep_merge


def _event_hash(store: Store, *, through_tick: int | None = None) -> str:
    sql = "SELECT tick,phase,kind,payload_json,subject_type,subject_id FROM events"
    params: tuple[Any, ...] = ()
    if through_tick is not None:
        sql += " WHERE tick<=?"
        params = (through_tick,)
    sql += " ORDER BY id"
    payload = [dict(row) for row in store.query(sql, params)]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


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
    def initialize(store: Store) -> None:
        store.insert("scenario_packs", scenario_key=pack.key, version=pack.version,
                     title=pack.title, manifest_path=pack.path,
                     manifest_checksum=pack.checksum_sha256, limitations=pack.limitations,
                     metadata_json=json.dumps({"arm": arm}, sort_keys=True))

    def collect(store: Store) -> dict:
        return {"metrics": {name: store.metric_latest(name, None) for name in pack.metrics},
                "causal_trace": _causal_trace(store)}

    return execute_attempt(
        run_id=f"{pack.key}-s{seed}-{arm}", seed=seed, arm=arm, config=config,
        ticks=ticks, data_dir=data_dir, initialize=initialize, collect=collect)


def run_counterfactual(scenario_path: str | Path | ScenarioPack, *, seeds: int | list[int] = 20,
                       ticks: int | None = None, out_dir: str | Path = "reports/out",
                       data_root: str | Path = "data/counterfactuals",
                       effective_config: dict[str, Any] | None = None) -> dict[str, Any]:
    pack = (scenario_path if isinstance(scenario_path, ScenarioPack)
            else load_scenario(scenario_path))
    resolved_config = (pack.config() if effective_config is None
                       else effective_config)
    paired_seeds = list(range(1, seeds + 1)) if isinstance(seeds, int) else [int(s) for s in seeds]
    horizon = int(pack.ticks if ticks is None else ticks)
    if horizon < 1 or not paired_seeds or len(set(paired_seeds)) != len(paired_seeds):
        raise ValueError("counterfactual requires a positive horizon and unique nonempty seeds")
    for arm in pack.arms:
        safe_key(arm)
    batch = create_batch(pack.key, {
        "runner": "counterfactual-v2", "scenario_sha256": pack.checksum_sha256,
        "paired_seeds": paired_seeds, "ticks": horizon, "arms": pack.arms,
        "common_shocks": pack.common_shocks, "config": resolved_config,
        "metrics": pack.metrics, "minimum_pairs": 2,
    }, data_root=data_root, out_dir=out_dir)
    data_dir = Path(batch["data_dir"])
    results = [_run_arm(pack, seed, arm, data_dir, horizon, resolved_config)
               for seed in paired_seeds for arm in pack.arms]
    influenced = [
        str(row.get("run_id", "")) for row in results
        if bool(row.get("external_agent_influenced", False))
    ]
    for row in results:
        if row.get("eligibility", {}).get("status") == "eligible":
            reasons = verify_attempt(row, expected_ticks=horizon)
            if reasons:
                row["eligibility"] = {"status": "ineligible", "reasons": reasons}
    baseline = "control" if "control" in pack.arms else next(iter(pack.arms))
    summary = paired_summary(results, baseline, expected_ticks=horizon,
                             expected_arms=list(pack.arms), expected_seeds=paired_seeds,
                             expected_metrics=list(pack.metrics))
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
        "batch": batch, "results": results, "summary": summary, "limitations": pack.limitations,
        "created_at": created,
    }
    target_dir = Path(batch["report_dir"])
    json_path = target_dir / f"counterfactual_{pack.key}.json"
    md_path = target_dir / f"counterfactual_{pack.key}.md"
    payload["artifacts"] = {"json": str(json_path), "markdown": str(md_path)}
    publish_json(json_path, payload)
    publish_bytes(md_path, _markdown_report(payload).encode("utf-8"))
    if influenced:
        raise RuntimeError(
            "external-agent-influenced runs cannot be used as branch-causal "
            f"evidence: {', '.join(influenced)}; attempts retained at {target_dir}")
    return payload


def _markdown_report(payload: dict[str, Any]) -> str:
    lines = [f"# {payload['scenario']['title']}", "", payload["limitations"], "",
             f"Paired seeds: {len(payload['design']['paired_seeds'])}; ticks: {payload['design']['ticks']}", "",
             "Effects use eligible complete-horizon pairs only. All assigned attempts are retained.", "",
             "| Metric | Arm | Mean | Paired effect | 95% bootstrap interval | Usable pairs | Status |",
             "|---|---:|---:|---:|---:|---:|---|"]
    baseline = payload["summary"]["baseline_arm"]
    for metric, arms in payload["summary"]["metrics"].items():
        for arm, values in arms.items():
            effect = values.get("paired_effect")
            lines.append(f"| {metric} | {arm} | {values['mean']} | "
                         f"{effect['mean_difference'] if effect else ('baseline' if arm == baseline else '')} | "
                         f"{effect['ci95_bootstrap'] if effect else ''} | "
                         f"{effect['n_pairs'] if effect else ''} | {effect['status'] if effect else 'baseline'} |")
    lines.extend(["", "## Attempt coverage", "", "```json",
                  json.dumps({"coverage": payload["summary"]["coverage"],
                              "exclusions": payload["summary"]["exclusions"]}, indent=2), "```"])
    lines.extend(["", "## Validity boundary", "",
                  "Effects are model-conditional and exploratory. Common initial state is checked separately from the declared shock schedule. Legacy shared RNG streams can diverge after treatment changes draw counts. These results do not identify real-world causal effects."])
    return "\n".join(lines)
