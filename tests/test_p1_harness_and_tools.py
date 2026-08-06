"""P1 tooling: experiment harness (R14), Oracle calibration (R15), replay reader (R16)."""
import asyncio
import json
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


def test_replay_reader_projects_public_event_payloads(tmp_path):
    store = Store(str(tmp_path / "public-events.db"))
    store.init_run_meta("public-events", 1, {})
    store.log_event(
        1,
        "production",
        {
            "firm_id": 4,
            "units": 7,
            "agent_id": 99,
            "private_reasoning": "replay-private-payload-canary",
        },
        phase="NIGHT_CLOSE",
        importance=1.0,
    )
    store.set_meta(status="paused", tick=1)
    store.commit()
    store.close()

    reader = ReplayReader(runs_dir=str(tmp_path))
    event = reader.tick_view("public-events", 1)["events"][0]

    assert event["payload"] == {"firm_id": 4, "units": 7}
    assert "replay-private-payload-canary" not in json.dumps(event)
    reader.close()


def test_replay_reader_uses_requested_tick_for_grounding_activation(tmp_path):
    config = {
        "seed": 1,
        "beliefs": {
            "model_grounding_from_tick": 2,
            "model_max_reserved_step": 0.05,
        },
    }
    store = Store(str(tmp_path / "numeric-news.db"))
    store.init_run_meta("numeric-news", 1, config)
    event_id = store.log_event(
        1,
        "production",
        {"firm_id": 1, "units": 4},
        phase="NIGHT_CLOSE",
        importance=1.0,
    )
    store.insert(
        "news_articles",
        tick=1,
        outlet_id=1,
        outlet_name="The Ledger",
        headline="Firm 1 reports a 987654321% output lead",
        body="The company says its lead reached 987654321%.",
        slant_tags='["market"]',
        source_event_ids=f"[{event_id}]",
        tone=0.2,
        truthful=1,
    )
    store.set_meta(
        status="paused", tick=1, active_tick=2, next_phase="MORNING")
    store.commit()
    store.close()

    reader = ReplayReader(runs_dir=str(tmp_path))
    article = reader.tick_view("numeric-news", 1)["news"][0]

    assert article["numeric_claims_redacted"] is False
    assert article["numeric_claims_redaction_reason"] is None
    assert "987654321" in article["headline"]
    reader.close()


def test_replay_reader_sanitizes_headline_independently_from_hidden_body(tmp_path):
    config = {
        "seed": 1,
        "beliefs": {"model_grounding_from_tick": 1},
    }
    store = Store(str(tmp_path / "separate-news-fields.db"))
    store.init_run_meta("separate-news-fields", 1, config)
    event_id = store.log_event(
        1,
        "production",
        {"firm_id": 1, "units": 4},
        phase="NIGHT_CLOSE",
        importance=1.0,
    )
    store.insert(
        "news_articles",
        tick=1,
        outlet_id=1,
        outlet_name="The Ledger",
        headline="Firm 1 reports 4 units",
        body="A hidden body invents 987654321 percent.",
        slant_tags='["market"]',
        source_event_ids=f"[{event_id}]",
        tone=0.2,
        truthful=1,
    )
    store.set_meta(status="paused", tick=1)
    store.commit()
    store.close()

    reader = ReplayReader(runs_dir=str(tmp_path))
    article = reader.tick_view("separate-news-fields", 1)["news"][0]

    assert article["headline"] == "Firm 1 reports 4 units"
    assert article["numeric_claims_redacted"] is False
    assert "body" not in article
    reader.close()


def test_replay_reader_bounds_malformed_legacy_news_values(tmp_path):
    config = {"seed": 1, "beliefs": {"model_grounding_from_tick": 1}}
    store = Store(str(tmp_path / "legacy-news.db"))
    store.init_run_meta("legacy-news", 1, config)
    event_id = store.log_event(
        1, "production", {"firm_id": 1, "units": 4},
        phase="NIGHT_CLOSE", importance=1.0,
    )
    article_id = store.insert(
        "news_articles", tick=1, outlet_id=1, outlet_name="Legacy",
        headline="Output rose 987654321 percent", body="legacy body",
        slant_tags="[]",
        source_event_ids=json.dumps([True, None, 1.5, {}, event_id]),
        tone="loud", truthful=1,
    )
    store.execute(
        "UPDATE news_articles SET outlet_name=NULL WHERE id=?", (article_id,))
    store.set_meta(status="paused", tick=1)
    store.commit()
    store.close()

    reader = ReplayReader(runs_dir=str(tmp_path))
    article = reader.tick_view("legacy-news", 1)["news"][0]

    assert article["headline"].startswith("News archived brief:")
    assert article["tone"] == 0.0
    reader.close()


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
