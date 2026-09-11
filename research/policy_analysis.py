"""World-level inference after complete paired model-replication blocks."""
from __future__ import annotations

import math
import statistics

from research.analysis import paired_summary
from research.attempts import execution_exclusions
from research.policy_studies import study_cells
from research.studies import StudySpec


def replicated_summary(results: list[dict], spec: StudySpec) -> dict:
    """Aggregate verified cells; never count model draws as independent worlds.

    As with paired_summary, the caller must independently verify receipts before
    supplying eligibility. These block summaries are analysis values, not new
    execution receipts or fictitious replayed worlds.
    """
    expected = {(item["arm"], item["seed"], item["model_replicate"]): item for item in study_cells(spec)}
    rows = {}
    for row in results:
        if type(row.get("seed")) is not int or any(not isinstance(row.get(key), str) for key in ("arm", "model_replicate", "policy")):
            raise ValueError("policy result has invalid assignment identifiers")
        key = (row["arm"], row["seed"], row["model_replicate"])
        if key not in expected or key in rows or row.get("policy") != expected[key]["policy"]:
            raise ValueError("policy result is duplicated or outside its prospective assignment")
        rows[key] = row
    metrics = [item.key for item in spec.analysis.outcomes]
    initial = "origin_state_hash" if spec.origin else "genesis_hash"
    blocks, block_rows, cell_exclusions = [], [], []
    for seed in spec.randomness.seeds:
        for arm in spec.arms:
            selected, reasons = [], []
            for replicate in spec.randomness.model_replicates:
                row = rows.get((arm.key, seed, replicate))
                excluded = ["missing_attempt"] if row is None else execution_exclusions(row, expected_ticks=spec.time.horizon)
                if row is not None and row.get("eligibility", {}).get("status") != "eligible":
                    excluded += row.get("eligibility", {}).get("reasons", []) or ["unverified_attempt"]
                if excluded:
                    cell_exclusions.append({"arm": arm.key, "seed": seed, "model_replicate": replicate,
                                            "reasons": sorted(set(excluded))})
                    reasons += [f"replicate:{replicate}:{reason}" for reason in excluded]
                if row is not None:
                    selected.append(row)
            hashes = {row.get(initial) for row in selected}
            if len(hashes) != 1 or None in hashes or "" in hashes:
                reasons.append("replicates_do_not_share_initial_world")
            complete = not reasons
            values, missing = {}, {}
            for metric in metrics:
                finite = []
                unavailable = []
                for replicate in spec.randomness.model_replicates:
                    row = rows.get((arm.key, seed, replicate), {})
                    value = row.get("metrics", {}).get(metric)
                    if type(value) in {int, float} and math.isfinite(value):
                        finite.append(value)
                    else:
                        unavailable.append(replicate)
                values[metric] = statistics.fmean(finite) if complete and not unavailable else None
                if unavailable:
                    missing[metric] = unavailable
            full = len(selected) == len(spec.randomness.model_replicates)
            block_rows.append({"arm": arm.key, "seed": seed,
                "execution_status": "completed" if full and all(row.get("execution_status") == "completed" for row in selected) else "failed" if selected else "planned",
                "ticks": spec.time.horizon if full and all(row.get("ticks") == spec.time.horizon for row in selected) else None,
                "expected_ticks": spec.time.horizon,
                "final_boundary": full and all(row.get("final_boundary") is True for row in selected),
                "reconciled": full and all(row.get("reconciled") is True for row in selected),
                "database_integrity": full and all(row.get("database_integrity") is True for row in selected),
                "external_agent_influenced": any(row.get("external_agent_influenced") for row in selected),
                "eligibility": {"status": "eligible" if complete else "ineligible", "reasons": sorted(set(reasons))},
                initial: next(iter(hashes)) if len(hashes) == 1 else None, "metrics": values})
            blocks.append({"arm": arm.key, "seed": seed, "policy": arm.policy,
                "assigned_replicates": len(spec.randomness.model_replicates),
                "started_replicates": sum(row.get("execution_status") != "planned" for row in selected),
                "status": "complete" if complete else "excluded", "reasons": sorted(set(reasons)),
                "missing_outcome_replicates": missing})
    baseline = next(arm.key for arm in spec.arms if arm.role == "baseline")
    summary = paired_summary(block_rows, baseline, bootstrap_samples=spec.analysis.bootstrap_samples,
        minimum_pairs=spec.analysis.minimum_pairs, expected_ticks=spec.time.horizon,
        expected_arms=[arm.key for arm in spec.arms], expected_seeds=spec.randomness.seeds,
        expected_metrics=metrics, initial_state_key=initial)
    summary["replication"] = {"contract": "complete-paired-block-mean-v1",
        "independent_worlds": len(spec.randomness.seeds), "model_replicates": list(spec.randomness.model_replicates),
        "assigned_cells": len(expected), "blocks": blocks, "cell_exclusions": cell_exclusions}
    summary["analysis_kind"] = "model_conditional_replicated_world_exploratory"
    return summary
