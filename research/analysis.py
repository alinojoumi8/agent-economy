"""Pair-level inference with explicit eligibility and missingness."""
from __future__ import annotations

import hashlib
import math
import random
import statistics
from typing import Any

from research.attempts import execution_exclusions


def seed_from(*parts: str) -> int:
    return int(hashlib.sha256("|".join(parts).encode()).hexdigest()[:8], 16)


def _bootstrap_interval(values: list[float], *, samples: int = 2000,
                        seed: int = 8675309) -> tuple[float, float] | None:
    if samples < 1:
        raise ValueError("bootstrap_samples must be positive")
    if not values:
        return None
    rng = random.Random(seed)
    means = sorted(statistics.fmean(rng.choice(values) for _ in values) for _ in range(samples))
    return means[max(0, int(samples * 0.025) - 1)], means[min(samples - 1, int(samples * 0.975))]


def paired_summary(results: list[dict[str, Any]], baseline_arm: str,
                   *, bootstrap_samples: int = 2000, minimum_pairs: int = 2,
                   expected_ticks: int | None = None,
                   expected_arms: list[str] | None = None,
                   expected_seeds: list[int] | None = None,
                   expected_metrics: list[str] | None = None,
                   initial_state_key: str = "genesis_hash") -> dict[str, Any]:
    """Aggregate already verified attempts, resampling whole seed/world pairs.

    Receipt verification belongs to the runner/loader before this pure function.
    Execution, horizon, common initial state and finite outcomes are also
    enforced here. Missing/ineligible rows never become a zero effect.
    """
    if minimum_pairs < 2 or bootstrap_samples < 1:
        raise ValueError("minimum_pairs must be at least 2 and bootstrap_samples positive")
    if initial_state_key not in {"genesis_hash", "origin_state_hash"}:
        raise ValueError("unsupported common initial condition")
    by_arm_seed = {}
    for row in results:
        key = (str(row["arm"]), int(row["seed"]))
        if key in by_arm_seed:
            raise ValueError(f"duplicate attempt for arm/seed: {key}")
        by_arm_seed[key] = row
    arms = sorted(set(expected_arms or [str(row["arm"]) for row in results]) | {baseline_arm})
    seeds = sorted(set(expected_seeds if expected_seeds is not None else
                       [int(row["seed"]) for row in results]))
    if any(arm not in arms or seed not in seeds for arm, seed in by_arm_seed):
        raise ValueError("result outside the assigned arms/seeds")
    if expected_ticks is None:
        horizons = [row.get("expected_ticks", row.get("ticks")) for row in results]
        expected_ticks = max((v for v in horizons if isinstance(v, int)), default=None)
    metrics = sorted(set(expected_metrics) if expected_metrics is not None else
                     {key for row in results for key in row.get("metrics", {})})
    exclusions, coverage = {}, {}
    for arm in arms:
        counts = {"assigned": len(seeds), "started": 0, "completed": 0, "eligible": 0}
        for seed in seeds:
            row = by_arm_seed.get((arm, seed))
            if row is None:
                reasons = ["missing_attempt"]
            else:
                counts["started"] += int(row.get("execution_status") != "planned")
                counts["completed"] += int(row.get("execution_status") == "completed")
                reasons = execution_exclusions(row, expected_ticks=expected_ticks)
                eligibility = row.get("eligibility", {})
                if eligibility.get("status") != "eligible":
                    reasons += eligibility.get("reasons", []) or ["unverified_attempt"]
                counts["eligible"] += int(not reasons)
            exclusions[(arm, seed)] = sorted(set(reasons))
        coverage[arm] = counts
    output = {"baseline_arm": baseline_arm, "paired_seeds": seeds, "arms": arms,
              "metrics": {}, "coverage": coverage, "expected_ticks": expected_ticks,
              "minimum_pairs": minimum_pairs, "analysis_kind": "model_conditional_exploratory",
              "exclusions": [{"arm": arm, "seed": seed, "reasons": reasons}
                             for (arm, seed), reasons in exclusions.items() if reasons]}
    if initial_state_key != "genesis_hash":
        output["initial_state_key"] = initial_state_key

    def finite_value(arm: str, seed: int, metric: str) -> float | None:
        if exclusions[(arm, seed)]:
            return None
        value = by_arm_seed[(arm, seed)].get("metrics", {}).get(metric)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value) if math.isfinite(value) else None

    for metric in metrics:
        metric_result = {}
        for arm in arms:
            clean = [v for seed in seeds if (v := finite_value(arm, seed, metric)) is not None]
            metric_result[arm] = {
                "n": len(clean), "mean": statistics.fmean(clean) if clean else None,
                "median": statistics.median(clean) if clean else None,
                "std": statistics.stdev(clean) if len(clean) > 1 else None,
                "min": min(clean) if clean else None, "max": max(clean) if clean else None,
            }
            if arm == baseline_arm:
                continue
            differences, matched_seeds, pair_exclusions = [], [], []
            for seed in seeds:
                treatment = finite_value(arm, seed, metric)
                control = finite_value(baseline_arm, seed, metric)
                reasons = [f"treatment:{r}" for r in exclusions[(arm, seed)]]
                reasons += [f"baseline:{r}" for r in exclusions[(baseline_arm, seed)]]
                if treatment is None and not exclusions[(arm, seed)]:
                    reasons.append("treatment:missing_or_nonfinite_outcome")
                if control is None and not exclusions[(baseline_arm, seed)]:
                    reasons.append("baseline:missing_or_nonfinite_outcome")
                t_genesis = by_arm_seed.get((arm, seed), {}).get(initial_state_key)
                c_genesis = by_arm_seed.get((baseline_arm, seed), {}).get(initial_state_key)
                if not t_genesis or t_genesis != c_genesis:
                    reasons.append("common_initial_state_unverified")
                if reasons:
                    pair_exclusions.append({"seed": seed, "reasons": reasons})
                    continue
                difference = treatment - control
                if not math.isfinite(difference):
                    pair_exclusions.append({"seed": seed, "reasons": ["nonfinite_difference"]})
                    continue
                differences.append(difference)
                matched_seeds.append(seed)
            enough = len(differences) >= minimum_pairs
            interval = (_bootstrap_interval(differences, samples=bootstrap_samples,
                                             seed=seed_from(metric, arm)) if enough else None)
            mean = statistics.fmean(differences) if differences else None
            sd = statistics.stdev(differences) if len(differences) > 1 else None
            metric_result[arm]["paired_effect"] = {
                "mean_difference": mean, "ci95_bootstrap": list(interval) if interval else None,
                "standardized_effect": mean / sd if sd is not None and sd > 0 else None,
                "standardization": "paired_sample_standard_deviation",
                "differences": differences, "matched_seeds": matched_seeds,
                "n_pairs": len(differences), "assigned_pairs": len(seeds),
                "pair_exclusions": pair_exclusions,
                "status": "estimated" if enough else "insufficient_replication" if differences else "no_usable_pairs",
                "interval_method": "paired_world_percentile_bootstrap" if enough else None,
                "bootstrap_samples": bootstrap_samples if enough else 0,
            }
        output["metrics"][metric] = metric_result
    return output
