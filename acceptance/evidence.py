"""Machine-readable PRD acceptance evidence derived only from run databases."""
from __future__ import annotations

import json
import math
from typing import Any

from engine.ledger import Ledger
from oracle.calibration import run_calibration


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lo = math.floor(position)
    hi = math.ceil(position)
    if lo == hi:
        return ordered[lo]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (position - lo)


def rumor_pilot_evidence(store, *, window_ticks: int = 10) -> dict[str, Any]:
    """Evaluate the exact R5 thresholds from persisted causal evidence."""
    row = store.query_one(
        "SELECT tick, payload_json FROM events WHERE kind='rumor' "
        "ORDER BY id DESC LIMIT 1")
    if not row:
        return {"available": False, "passes": False, "reason": "no rumor event"}

    payload = json.loads(row["payload_json"])
    required = {"baseline_trust", "baseline_outflow_cents", "baseline_window_ticks",
                "pre_deposits_cents", "target_agent_ids", "bank_id"}
    missing = sorted(required - set(payload))
    if missing:
        return {"available": False, "passes": False,
                "reason": "rumor event predates acceptance instrumentation",
                "missing": missing}

    tick = int(row["tick"])
    end_tick = tick + window_ticks - 1
    bank_id = int(payload["bank_id"])
    exposed = [int(agent_id) for agent_id in payload["target_agent_ids"]]
    baseline_trust = {int(key): float(value)
                      for key, value in payload["baseline_trust"].items()}

    dropped = 0
    for agent_id in exposed:
        value = store.scalar(
            "SELECT value FROM beliefs WHERE agent_id=? AND key=?",
            (agent_id, f"trust:bank:{bank_id}"), default=None)
        current = baseline_trust[agent_id] if value is None else float(value)
        if baseline_trust[agent_id] - current >= 0.2:
            dropped += 1
    trust_drop_fraction = dropped / len(exposed) if exposed else 0.0

    rumor_conversations: set[int] = set()
    for event in store.query(
            "SELECT payload_json FROM events WHERE kind='conversation' "
            "AND tick BETWEEN ? AND ?", (tick, end_tick)):
        conversation = json.loads(event["payload_json"])
        if bank_id in conversation.get("rumor_banks", []):
            rumor_conversations.add(int(conversation["conv_id"]))

    post_outflow = 0
    for event in store.query(
            "SELECT payload_json FROM events WHERE kind='deposit_move' "
            "AND tick BETWEEN ? AND ?", (tick, end_tick)):
        move = json.loads(event["payload_json"])
        if int(move.get("from_bank", -1)) == bank_id:
            post_outflow += int(move.get("amount_cents", 0))

    baseline_window = max(1, int(payload["baseline_window_ticks"]))
    normalized_baseline = float(payload["baseline_outflow_cents"]) \
        / baseline_window * window_ticks
    outflow_passes = post_outflow > 2.0 * normalized_baseline
    post_deposits = int(sum(
        int(row["balance_cents"])
        for row in store.query(
            "SELECT balance_cents FROM accounts WHERE bank_id=? "
            "AND kind IN ('checking','savings')", (bank_id,))))

    checks = {
        "rumor_conversations": len(rumor_conversations) >= 5,
        "trust_drop": trust_drop_fraction >= 0.25,
        "deposit_outflow": outflow_passes,
        "deposits_declined": post_deposits < int(payload["pre_deposits_cents"]),
    }
    return {
        "available": True,
        "passes": all(checks.values()),
        "bank_id": bank_id,
        "rumor_tick": tick,
        "window_end_tick": end_tick,
        "exposed_agents": len(exposed),
        "rumor_conversations": len(rumor_conversations),
        "trust_drop_agents": dropped,
        "trust_drop_fraction": round(trust_drop_fraction, 4),
        "baseline_outflow_cents_normalized": round(normalized_baseline, 2),
        "post_outflow_cents": post_outflow,
        "pre_deposits_cents": int(payload["pre_deposits_cents"]),
        "post_deposits_cents": post_deposits,
        "checks": checks,
    }


def oracle_evidence(store, *, expected_questions: int, max_p90_s: float = 60.0) -> dict[str, Any]:
    predictions = store.query("SELECT * FROM predictions ORDER BY id")
    calls = store.query(
        "SELECT latency_ms FROM llm_calls WHERE purpose='oracle' ORDER BY id")
    latencies_s = [float(row["latency_ms"]) / 1000.0 for row in calls]
    p90 = _percentile(latencies_s, 0.90)
    structured = [row for row in predictions
                  if row["p"] is not None and row["resolution_rule_json"]
                  and row["deadline_tick"] is not None]
    resolved = [row for row in structured if row["status"] == "resolved"]
    checks = {
        "question_count": len(predictions) >= expected_questions,
        "structured_predictions": len(structured) >= expected_questions,
        "p90_latency": p90 is not None and p90 < max_p90_s,
        "automatic_resolution": len(resolved) >= expected_questions,
    }
    return {
        "passes": all(checks.values()),
        "questions": len(predictions),
        "structured": len(structured),
        "resolved": len(resolved),
        "insufficient": sum(1 for row in predictions
                            if row["status"] == "insufficient_data"),
        "p50_s": round(_percentile(latencies_s, 0.50), 3) if latencies_s else None,
        "p90_s": round(p90, 3) if p90 is not None else None,
        "max_p90_s": max_p90_s,
        "checks": checks,
    }


def long_run_evidence(store, *, target_ticks: int = 365,
                      max_spend_usd: float = 200.0) -> dict[str, Any]:
    meta = store.get_meta()
    spend = float(store.scalar(
        "SELECT COALESCE(SUM(cost_usd),0) FROM llm_calls", default=0.0))
    reconciled, diagnostics = Ledger(store).reconcile()
    provider_failures = int(store.scalar(
        "SELECT COUNT(*) FROM events WHERE kind IN "
        "('provider_failure','provider_pause','report_failed')", default=0))
    checks = {
        "target_ticks": int(meta["tick"]) >= target_ticks,
        "budget": spend <= max_spend_usd,
        "ledger": reconciled,
        "not_halted": str(meta["status"]) != "halted",
        "provider_failures": provider_failures == 0,
    }
    return {
        "passes": all(checks.values()),
        "run_id": str(meta["run_id"]),
        "tick": int(meta["tick"]),
        "target_ticks": target_ticks,
        "spend_usd": round(spend, 6),
        "max_spend_usd": max_spend_usd,
        "provider_failures": provider_failures,
        "ledger": diagnostics,
        "checks": checks,
    }


def calibration_evidence(store, *, minimum_predictions: int = 10) -> dict[str, Any]:
    result = run_calibration(store)
    result["minimum_predictions"] = minimum_predictions
    result["passes"] = result["n"] >= minimum_predictions and bool(result.get("beats_naive"))
    return result


def causal_phenomena_evidence(store) -> dict[str, Any]:
    """Prove oil→founder-price and policy-rate→loan-quote chains from events."""
    oil_event = store.query_one(
        "SELECT tick, payload_json FROM events WHERE kind='commodity_shock' "
        "ORDER BY id DESC LIMIT 1")
    oil_result: dict[str, Any] = {"passes": False, "reason": "no oil shock"}
    if oil_event:
        oil_tick = int(oil_event["tick"])
        repricing = None
        for row in store.query(
                "SELECT tick, payload_json FROM events WHERE kind='price_set' "
                "AND tick>? AND tick<=? ORDER BY tick,id", (oil_tick, oil_tick + 10)):
            payload = json.loads(row["payload_json"])
            if int(payload.get("new_cents", 0)) > int(payload.get("old_cents", 0)):
                repricing = {"tick": int(row["tick"]), **payload}
                break
        oil_result = {
            "passes": repricing is not None,
            "shock_tick": oil_tick,
            "shock": json.loads(oil_event["payload_json"]),
            "founder_repricing": repricing,
        }

    rate_event = None
    for row in store.query(
            "SELECT tick, payload_json FROM events WHERE kind='policy_rate_set' "
            "ORDER BY id DESC"):
        payload = json.loads(row["payload_json"])
        if payload.get("via") == "shock":
            rate_event = (row, payload)
            break
    rate_result: dict[str, Any] = {"passes": False, "reason": "no policy-rate shock"}
    if rate_event:
        row, shock = rate_event
        rate_tick = int(row["tick"])
        quoted = None
        for loan in store.query(
                "SELECT tick, payload_json FROM events WHERE kind='loan_originated' "
                "AND tick>? AND tick<=? ORDER BY tick,id", (rate_tick, rate_tick + 30)):
            payload = json.loads(loan["payload_json"])
            if int(payload.get("rate_bps", 0)) > int(shock.get("new_bps", 0)):
                quoted = {"tick": int(loan["tick"]), **payload}
                break
        rate_result = {
            "passes": quoted is not None,
            "shock_tick": rate_tick,
            "shock": shock,
            "loan_quote": quoted,
        }

    return {
        "passes": oil_result["passes"] and rate_result["passes"],
        "oil_to_founder_repricing": oil_result,
        "policy_rate_to_loan_quote": rate_result,
    }
