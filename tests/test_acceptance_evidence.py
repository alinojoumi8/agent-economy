import asyncio
import json

import pytest

from agents.policies import oracle_answer
from acceptance.campaigns import (
    _open_world,
    _run_long_campaign,
    _run_rumor_campaign,
    run_campaign,
)
from acceptance.evidence import (
    calibration_evidence,
    causal_phenomena_evidence,
    long_run_evidence,
    oracle_evidence,
)
from engine.store import Store


def _campaign_config():
    return {
        "seed": 1,
        "population": {"size": 14},
        "banks": {"count": 2, "initial_reserve_ratio": 0.6,
                  "reserve_requirement_bps": 1000},
        "firms": {"count": 3, "listed": 1, "target_headcount": 2,
                  "pay_interval_ticks": 30},
        "budget": {"cap_usd": 200.0, "oracle_reserve_usd": 10.0,
                   "conversation_pairs": 2, "thresholds": [0.6, 0.8, 0.95]},
        "oracle": {"default_horizon_ticks": 30},
        "llm": {"default_route": {"provider": "scripted", "model": "scripted"},
                "routes": {}},
        "checkpoint_every": 1,
        "outlets": [{"id": 1, "name": "A", "slant": "pro-market-sensational"},
                    {"id": 2, "name": "B", "slant": "cautious-pro-labor"}],
    }


def test_scripted_oracle_supports_every_acceptance_question():
    context = {
        "tick": 1, "default_horizon": 30, "min_reserve_ratio": 0.6,
        "min_bank_trust": 0.6,
        "metrics": {"index_change_10": 0.0, "unemployment": 0.05,
                    "cpi": 100.0, "policy_rate": 500.0, "sentiment": 0.0,
                    "epidemic_multiplier": 1.0},
        "banks": [{"id": 1, "deposits_cents": 100_000}],
    }
    questions = [
        "bank run within 30 ticks", "any bank fails within 30 ticks",
        "market index falls within 30 ticks", "unemployment exceeds within 30 ticks",
        "CPI exceeds 110 within 30 ticks", "any firm goes bankrupt within 30 ticks",
        "policy_rate above 800 basis points within 30 ticks",
        "sentiment below -0.2 within 30 ticks",
        "bank_deposits:1 below half its current level within 30 ticks",
        "epidemic_multiplier above 1 within 30 ticks",
    ]
    answers = [oracle_answer({**context, "question": question}) for question in questions]
    assert all("resolution_rule" in answer for answer in answers)
    assert {answer["resolution_rule"]["type"] for answer in answers} == {
        "bank_run", "bank_failure", "index_drop", "unemployment_above",
        "cpi_above", "firm_bankruptcy", "metric_above", "metric_below",
    }


def test_oracle_long_run_and_calibration_evidence_are_machine_readable(tmp_path):
    store = Store(str(tmp_path / "acceptance.db"))
    store.init_run_meta("acceptance", 42, {"budget": {"cap_usd": 200.0}})
    store.set_meta(tick=365, status="paused")

    for index in range(10):
        outcome = 1 if index < 5 else 0
        probability = 0.9 if outcome else 0.1
        store.insert(
            "predictions", asked_tick=1, question=f"q{index}", p=probability,
            resolution_rule_json='{"type":"bank_failure"}', deadline_tick=31,
            resolved_tick=31, outcome=outcome, brier=(probability - outcome) ** 2,
            status="resolved")
        store.insert(
            "llm_calls", tick=1, provider="kimi", model="kimi-k2.6",
            purpose="oracle", latency_ms=10_000 + index * 100,
            cost_usd=0.01)

    oracle = oracle_evidence(store, expected_questions=10)
    assert oracle["passes"]
    assert oracle["p90_s"] < 60

    long_run = long_run_evidence(store, required_llm_calls=[
        {"provider": "kimi", "model": "kimi-k2.6", "purpose": "oracle",
         "min_calls": 10},
    ])
    assert long_run["passes"]
    assert long_run["ledger"]["grand_sum_cents"] == 0
    assert long_run["required_llm_calls"][0]["observed_calls"] == 10

    calibration = calibration_evidence(store)
    assert calibration["passes"]
    assert calibration["beats_naive"]

    store.log_event(10, "commodity_shock", {"old": 1.0, "new": 2.0})
    store.log_event(11, "price_set", {
        "firm_id": 1, "old_cents": 300, "new_cents": 500})
    store.log_event(20, "policy_rate_set", {
        "old_bps": 500, "new_bps": 900, "via": "shock"})
    store.log_event(21, "loan_originated", {
        "loan_id": 1, "rate_bps": 1300, "bank_id": 1})
    phenomena = causal_phenomena_evidence(store)
    assert phenomena["passes"]
    store.close()


def test_resumable_long_campaign_drives_oracle_and_shock_evidence(tmp_path):
    spec = {
        "name": "test-campaign",
        "report_dir": str(tmp_path / "reports"),
        "long_run": {
            "seed": 7, "ticks": 31, "max_spend_usd": 200.0,
            "checkpoint_every": 1, "oracle_tick": 1,
            "minimum_resolved_predictions": 2, "rate_probe_tick": 20,
            "shocks": [
                {"kind": "oil", "trigger": "shock",
                 "trigger_params": {"tick": 10}, "params": {"multiplier": 2.0}},
                {"kind": "policy_rate", "trigger": "shock",
                 "trigger_params": {"tick": 20}, "params": {"rate_bps": 900}},
            ],
            "oracle_questions": [
                "What is the probability of a bank run within 30 ticks?",
                "What is the probability that any bank fails within 30 ticks?",
            ],
        },
    }
    result = asyncio.run(_run_long_campaign(spec, _campaign_config(), tmp_path / "data"))
    assert result["long_run"]["tick"] == 31
    assert result["long_run"]["checks"]["ledger"]
    assert result["oracle"]["structured"] == 2
    assert result["oracle"]["resolved"] == 2
    assert result["causal_phenomena"]["oil_to_founder_repricing"]["passes"]
    assert result["causal_phenomena"]["policy_rate_to_loan_quote"]["passes"]

    # A second invocation reuses the completed database instead of replaying ticks.
    resumed = asyncio.run(_run_long_campaign(spec, _campaign_config(), tmp_path / "data"))
    assert resumed["long_run"]["tick"] == 31


def test_interrupted_campaign_recovers_from_last_durable_checkpoint(tmp_path):
    db = tmp_path / "acceptance.db"
    config = _campaign_config()
    config["checkpoint_dir"] = str(tmp_path / "checkpoints")
    store, world = _open_world(db, "acceptance-recovery", config, 1)
    checkpoint_path = world.checkpoint(0, reason="acceptance-test")
    assert checkpoint_path

    # Simulate a process dying after the database advanced beyond its checkpoint.
    store.set_meta(tick=3, status="running")
    store.log_event(3, "uncommitted_campaign_progress", {})
    store.commit()
    store.close()

    recovered_store, recovered_world = _open_world(
        db, "acceptance-recovery", config, 1)
    try:
        assert recovered_world.store.tick == 0
        assert recovered_store.get_meta()["status"] == "paused"
        recovery = recovered_store.query_one(
            "SELECT payload_json FROM events WHERE kind='acceptance_recovered'")
        assert recovery is not None
        assert '"interrupted_tick": 3' in recovery["payload_json"]
        assert recovered_store.query_one(
            "SELECT id FROM events WHERE kind='uncommitted_campaign_progress'") is None
    finally:
        recovered_store.close()


def test_campaign_refuses_to_resume_with_a_different_resolved_config(tmp_path):
    db = tmp_path / "acceptance.db"
    config = _campaign_config()
    store, _ = _open_world(db, "acceptance-config", config, 1)
    store.close()

    changed = json.loads(json.dumps(config))
    changed["llm"]["default_route"]["model"] = "different-model"
    with pytest.raises(RuntimeError, match="configuration mismatch"):
        _open_world(db, "acceptance-config", changed, 1)


def test_rumor_campaign_measures_actual_rumor_conversations(tmp_path):
    spec = {
        "name": "rumor-campaign", "report_dir": str(tmp_path / "reports"),
        "rumor": {"seeds": [1], "ticks": 13, "shock_tick": 4,
                  "bank_id": 1, "n_agents": 10},
    }
    result = _run_rumor_campaign(spec, _campaign_config(), tmp_path / "data")
    assert result["passes"]
    assert result["seeds"][0]["rumor_conversations"] >= 5


def test_report_phase_reuses_existing_evidence(tmp_path):
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    evidence = {"campaign": "report-test", "preflight": {"ready": True},
                "passes": True, "long": {"long_run": {"passes": True}}}
    (report_dir / "acceptance_report-test.json").write_text(
        json.dumps(evidence), encoding="utf-8")
    spec = tmp_path / "campaign.yaml"
    spec.write_text(
        "name: report-test\nbase_config: runs/base.yaml\n"
        f"data_root: {tmp_path / 'data'}\nreport_dir: {report_dir}\n",
        encoding="utf-8")

    rendered = run_campaign(spec, phase="report")
    assert rendered["passes"]
    assert (report_dir / "acceptance_report-test.md").exists()
    assert (report_dir / "acceptance_report-test.html").exists()


def test_separate_campaign_phases_merge_into_one_final_report(tmp_path, monkeypatch):
    report_dir = tmp_path / "reports"
    spec = tmp_path / "campaign.yaml"
    spec.write_text(
        "name: phase-test\nbase_config: runs/base.yaml\n"
        f"data_root: {tmp_path / 'data'}\nreport_dir: {report_dir}\n",
        encoding="utf-8")

    async def ready(*_args, **_kwargs):
        return {"ready": True, "live_ready": True}

    async def long(*_args, **_kwargs):
        return {"long_run": {"passes": True}, "oracle": {"passes": True},
                "calibration": {"passes": True},
                "causal_phenomena": {"passes": True}}

    monkeypatch.setattr("acceptance.campaigns.provider_preflight", ready)
    monkeypatch.setattr("acceptance.campaigns._run_long_campaign", long)
    monkeypatch.setattr("acceptance.campaigns._run_rumor_campaign",
                        lambda *_args, **_kwargs: {"passes": True})

    first = run_campaign(spec, phase="long")
    assert "long" in first and "rumor" not in first
    final = run_campaign(spec, phase="rumor")
    assert final["passes"]
    assert "long" in final and "rumor" in final
    persisted = json.loads(
        (report_dir / "acceptance_phase-test.json").read_text(encoding="utf-8"))
    assert "long" in persisted and "rumor" in persisted
