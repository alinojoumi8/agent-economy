"""Oracle calibration (P1 R15): reliability curve + Murphy Brier decomposition.

Works over resolved predictions from one run or aggregated across every run
database in `data/runs/` (opened read-only), so calibration accumulates across
many predictions and many runs as the PRD asks.

Murphy decomposition over K probability bins:
    brier = reliability − resolution + uncertainty
    reliability = (1/N) Σ n_k (p̄_k − ō_k)²      (want small: forecasts match outcomes)
    resolution  = (1/N) Σ n_k (ō_k − ō)²         (want large: forecasts discriminate)
    uncertainty = ō (1 − ō)                      (property of the outcomes, not the analyst)
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

N_BINS = 10


def calibration_from_pairs(
        pairs: list[tuple[float, int]],
        clusters: list | None = None) -> dict:
    """pairs: (forecast probability, realized outcome 0/1) for resolved predictions.

    `clusters` optionally gives the independence unit for each pair (one entry
    per pair, typically the run id). Forecasts inside one run are not
    independent — a campaign run asks the same question at several checkpoints
    and the scenario config fixes the outcome, so every forecast in that run
    resolves the same way. Pooling them as if they were independent understates
    the standard error; measured on the V10 arms it was 3.3x too small (0.0351
    pooled vs 0.1165 clustered over 7 runs). When clusters are supplied the
    error is taken across cluster means instead.
    """
    n = len(pairs)
    if n == 0:
        return {"n": 0, "bins": [], "brier": None, "naive_brier": None,
                "reliability": None, "resolution": None, "uncertainty": None,
                "mean_forecast": None, "brier_se": None, "brier_ci95": None,
                "brier_se_basis": None, "brier_se_clusters": None}
    o_bar = sum(o for _, o in pairs) / n
    bins = []
    reliability = 0.0
    resolution = 0.0
    for k in range(N_BINS):
        lo, hi = k / N_BINS, (k + 1) / N_BINS
        members = [(p, o) for p, o in pairs if (lo <= p < hi) or (k == N_BINS - 1 and p == 1.0)]
        if not members:
            continue
        nk = len(members)
        p_bar = sum(p for p, _ in members) / nk
        o_k = sum(o for _, o in members) / nk
        reliability += nk * (p_bar - o_k) ** 2
        resolution += nk * (o_k - o_bar) ** 2
        bins.append({"bin": f"{lo:.1f}-{hi:.1f}", "n": nk,
                     "mean_forecast": round(p_bar, 4), "observed": round(o_k, 4)})
    reliability /= n
    resolution /= n
    uncertainty = o_bar * (1 - o_bar)
    errors = [(p - o) ** 2 for p, o in pairs]
    brier = sum(errors) / n
    naive = sum((0.5 - o) ** 2 for _, o in pairs) / n
    # Reported so a Brier near the naive baseline is read as the coin-flip it is
    # rather than as a result. Never consulted by any pass/fail decision.
    cluster_errors: dict = {}
    if clusters is not None:
        if len(clusters) != n:
            raise ValueError("clusters must have one entry per pair")
        for error, key in zip(errors, clusters):
            cluster_errors.setdefault(key, []).append(error)
    if len(cluster_errors) > 1:
        # The run is the independence unit, so the spread that matters is
        # between runs, not between forecasts sharing one run's outcome.
        means = [sum(v) / len(v) for v in cluster_errors.values()]
        m = len(means)
        centre = sum(means) / m
        variance = sum((value - centre) ** 2 for value in means) / (m - 1)
        brier_se = (variance / m) ** 0.5
        se_basis, se_clusters = "cluster", m
    elif n > 1:
        variance = sum((e - brier) ** 2 for e in errors) / (n - 1)
        brier_se = (variance / n) ** 0.5
        # Only honest for one cluster; across runs it reads ~3x too precise.
        se_basis, se_clusters = "pooled", len(cluster_errors) or None
    else:
        brier_se, se_basis, se_clusters = None, None, None
    ci95 = (None if brier_se is None else
            [round(brier - 1.96 * brier_se, 4), round(brier + 1.96 * brier_se, 4)])
    return {"n": n, "base_rate": round(o_bar, 4), "bins": bins,
            "brier": round(brier, 4), "naive_brier": round(naive, 4),
            "beats_naive": brier < naive,
            "mean_forecast": round(sum(p for p, _ in pairs) / n, 4),
            "brier_se": None if brier_se is None else round(brier_se, 4),
            "brier_ci95": ci95,
            "brier_se_basis": se_basis, "brier_se_clusters": se_clusters,
            "reliability": round(reliability, 4), "resolution": round(resolution, 4),
            "uncertainty": round(uncertainty, 4)}


def _resolved_pairs(conn) -> list[tuple[float, int]]:
    rows = conn.execute(
        "SELECT p, outcome FROM predictions WHERE status='resolved' "
        "AND p IS NOT NULL AND outcome IS NOT NULL").fetchall()
    return [(float(r[0]), int(r[1])) for r in rows]


def run_calibration(store) -> dict:
    """Calibration for the current run's store."""
    return calibration_from_pairs(_resolved_pairs(store.conn))


def aggregate_calibration(runs_dir: str = "data/runs") -> dict:
    """Calibration pooled across every run database found (read-only)."""
    pairs: list[tuple[float, int]] = []
    clusters: list[str] = []
    runs = 0
    for db in sorted(Path(runs_dir).glob("*.db")):
        try:
            conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            try:
                found = _resolved_pairs(conn)
                pairs.extend(found)
                # Each database is one run, and one run is one independence unit.
                clusters.extend([db.stem] * len(found))
                runs += 1
            finally:
                conn.close()
        except sqlite3.Error:
            continue
    out = calibration_from_pairs(pairs, clusters)
    out["runs"] = runs
    return out
