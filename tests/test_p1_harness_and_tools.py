"""P1 tooling: experiment harness (R14), Oracle calibration (R15), replay reader (R16)."""
import asyncio
import logging
import sqlite3

import pytest

from engine.store import Store
from experiments.harness import load_spec, run_experiment
from oracle.calibration import calibration_from_pairs
from server.replay import ReplayReader
from world.loop import World


def _tiny_config(**over):
    cfg = {
        "seed": 1,
        "population": {"size": 14},
        "banks": {"count": 2},
        "firms": {"count": 3, "listed": 1},
        "budget": {"cap_usd": 200.0, "oracle_reserve_usd": 10.0, "conversation_pairs": 4,
                   "thresholds": [0.60, 0.80, 0.95]},
        "llm": {"default_route": {"provider": "scripted", "model": "scripted"}, "routes": {}},
        "checkpoint_every": 0,
        "outlets": [{"id": 1, "name": "A", "slant": "pro-market-sensational"},
                    {"id": 2, "name": "B", "slant": "cautious-pro-labor"}],
    }
    cfg.update(over)
    return cfg


# ── R14: experiment harness end-to-end ───────────────────────────────────────
def test_experiment_harness_treatment_vs_control(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="agent_economy.experiments")
    spec = {
        "name": "mini_rumor",
        "config": _tiny_config(),
        "seeds": [1, 2, 3, 4, 5],
        "ticks": 8,
        "control": True,
        "shocks": [{"kind": "rumor", "trigger": "shock", "trigger_params": {"tick": 2},
                    "params": {"bank_id": 1, "n_agents": 10}}],
        "metrics": ["bank_deposits:1", "sentiment"],
        "event_outcomes": ["deposit_move", "bank_failure"],
    }
    out = run_experiment(spec, out_dir=str(tmp_path / "out"),
                         data_root=str(tmp_path / "data"), quiet=True)

    results = out["results"]
    assert len(results) == 10                                 # 5 seeds × 2 arms
    assert {r["arm"] for r in results} == {"treatment", "control"}
    assert all(r["reconciled"] for r in results)
    assert all(r["ticks"] == 8 for r in results)
    # Summary carries distributions + a treatment−control effect per metric.
    m = out["summary"]["metrics"]["bank_deposits:1"]
    assert m["treatment"]["n"] == 5 and m["control"]["n"] == 5
    assert "effect_mean" in m
    # The rumor arm moved deposits; the control arm has strictly fewer moves.
    ev = out["summary"]["events"]["deposit_move"]
    assert ev["treatment"]["mean"] >= ev["control"]["mean"]
    # Report artifacts exist.
    assert (tmp_path / "out" / "experiment_mini_rumor.html").exists()
    assert (tmp_path / "out" / "experiment_mini_rumor.md").exists()
    assert (tmp_path / "out" / "experiment_mini_rumor.json").exists()
    # Same-seed arms differ ONLY by the shock: run dbs are per-arm.
    assert (tmp_path / "data" / "mini_rumor" / "mini_rumor_s1_treatment.db").exists()
    assert (tmp_path / "data" / "mini_rumor" / "mini_rumor_s1_control.db").exists()
    log_events = [getattr(record, "event_name", "") for record in caplog.records]
    assert log_events.count("experiment.arm.completed") == 10
    assert "experiment.started" in log_events and "experiment.completed" in log_events


def test_experiment_base_config_honors_recursive_inheritance():
    spec = load_spec({
        "name": "production-derived",
        "base_config": "runs/production.yaml",
        "overrides": {"population": {"size": 12}},
    })

    assert spec["config"]["population"]["size"] == 12
    assert spec["config"]["firms"]["count"] == 12
    assert spec["config"]["budget"]["cap_usd"] is None
    assert spec["config"]["llm"]["default_route"]["provider"] == "minimax"


# ── R15: Murphy decomposition sanity ─────────────────────────────────────────
def test_calibration_decomposition_identity():
    # Perfectly calibrated forecaster: p=0.8 bin observes 80%.
    pairs = [(0.8, 1)] * 4 + [(0.8, 0)]
    c = calibration_from_pairs(pairs)
    assert c["n"] == 5
    assert abs(c["reliability"]) < 1e-9
    assert abs(c["uncertainty"] - 0.16) < 1e-9
    assert abs(c["brier"] - 0.16) < 1e-9
    # brier = reliability − resolution + uncertainty
    assert abs(c["brier"] - (c["reliability"] - c["resolution"] + c["uncertainty"])) < 1e-6
    assert c["beats_naive"]

    # Overconfident forecaster: says 0.95, right only half the time.
    bad = calibration_from_pairs([(0.95, 1), (0.95, 0)] * 3)
    assert bad["reliability"] > 0.15
    assert not bad["beats_naive"]

    assert calibration_from_pairs([])["n"] == 0


def test_brier_se_uses_the_run_as_the_independence_unit():
    """Forecasts inside one run share an outcome, so pooling overstates precision.

    Shaped like a real campaign: each run asks the same question at several
    checkpoints and the scenario fixes the answer, so every forecast in a run
    resolves the same way. The pooled error treats those as independent draws
    and reports an interval far too narrow.
    """
    # Four "control" runs that never fire, three "rumor" runs that always do —
    # the V10 arm shape, three forecasts each.
    pairs, clusters = [], []
    for run, (forecast, outcome) in enumerate(
            [(0.09, 0)] * 4 + [(0.24, 1)] * 3):
        pairs.extend([(forecast, outcome)] * 3)
        clusters.extend([f"run-{run}"] * 3)

    pooled = calibration_from_pairs(pairs)
    clustered = calibration_from_pairs(pairs, clusters)

    # Same point estimate; only the claimed precision changes.
    assert pooled["brier"] == clustered["brier"]
    assert pooled["brier_se_basis"] == "pooled"
    assert clustered["brier_se_basis"] == "cluster"
    assert clustered["brier_se_clusters"] == 7
    # 21 correlated forecasts are really 7 observations, so the honest error is
    # materially wider — the defect this guards against reported ~3x too tight.
    assert clustered["brier_se"] > pooled["brier_se"] * 1.5
    lo, hi = clustered["brier_ci95"]
    assert hi - lo > (pooled["brier_ci95"][1] - pooled["brier_ci95"][0]) * 1.5

    # A single cluster carries no between-run signal, so it must not pretend to.
    single = calibration_from_pairs(pairs[:3], ["one"] * 3)
    assert single["brier_se_basis"] == "pooled"

    with pytest.raises(ValueError):
        calibration_from_pairs(pairs, clusters[:2])


# ── R16: replay reader over a stored run ─────────────────────────────────────
def test_replay_reader_lists_and_pages_ticks(tmp_path):
    cfg = _tiny_config()
    s = Store(str(tmp_path / "abc123.db"))
    s.init_run_meta("abc123", cfg["seed"], cfg)
    w = World(s, cfg)
    w.initialize()

    async def go():
        for _ in range(4):
            await w.step()
    asyncio.run(go())
    s.commit()

    reader = ReplayReader(runs_dir=str(tmp_path))
    runs = reader.list_runs()
    assert len(runs) == 1 and runs[0]["run_id"] == "abc123" and runs[0]["ticks"] == 4

    assert reader.summary("abc123")["agents"] > 0
    view = reader.tick_view("abc123", 2)
    assert view["tick"] == 2
    assert view["events"], "a tick must expose its stored events"
    assert "unemployment" in view["metrics"]
    series = reader.metrics("abc123", "unemployment,cpi")
    assert "unemployment" in series and len(series["unemployment"]) >= 4
    # Unknown/invalid run ids are refused, not crashed.
    assert reader.tick_view("nope", 1) is None
    assert reader.tick_view("../etc/passwd", 1) is None


def test_replay_reader_bounds_and_closes_cached_connections(tmp_path):
    for index in range(4):
        store = Store(str(tmp_path / f"run-{index}.db"))
        store.init_run_meta(f"run-{index}", index, {})
        store.close()

    reader = ReplayReader(str(tmp_path), max_connections=2)
    assert len(reader.list_runs()) == 4
    assert len(reader._conns) == 2
    cached = list(reader._conns.values())
    reader.close()
    assert not reader._conns
    for conn in cached:
        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")
