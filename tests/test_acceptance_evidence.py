import asyncio

from acceptance.campaigns import _run_long_campaign, _run_rumor_campaign
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

    long_run = long_run_evidence(store)
    assert long_run["passes"]
    assert long_run["ledger"]["grand_sum_cents"] == 0

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


def test_rumor_campaign_measures_actual_rumor_conversations(tmp_path):
    spec = {
        "name": "rumor-campaign", "report_dir": str(tmp_path / "reports"),
        "rumor": {"seeds": [1], "ticks": 13, "shock_tick": 4,
                  "bank_id": 1, "n_agents": 10},
    }
    result = _run_rumor_campaign(spec, _campaign_config(), tmp_path / "data")
    assert result["passes"]
    assert result["seeds"][0]["rumor_conversations"] >= 5
