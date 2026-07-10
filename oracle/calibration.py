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


def calibration_from_pairs(pairs: list[tuple[float, int]]) -> dict:
    """pairs: (forecast probability, realized outcome 0/1) for resolved predictions."""
    n = len(pairs)
    if n == 0:
        return {"n": 0, "bins": [], "brier": None, "naive_brier": None,
                "reliability": None, "resolution": None, "uncertainty": None}
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
    brier = sum((p - o) ** 2 for p, o in pairs) / n
    naive = sum((0.5 - o) ** 2 for _, o in pairs) / n
    return {"n": n, "base_rate": round(o_bar, 4), "bins": bins,
            "brier": round(brier, 4), "naive_brier": round(naive, 4),
            "beats_naive": brier < naive,
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
    runs = 0
    for db in sorted(Path(runs_dir).glob("*.db")):
        try:
            conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            try:
                pairs.extend(_resolved_pairs(conn))
                runs += 1
            finally:
                conn.close()
        except sqlite3.Error:
            continue
    out = calibration_from_pairs(pairs)
    out["runs"] = runs
    return out
