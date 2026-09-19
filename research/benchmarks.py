"""Run and verify equal-priority G1/F1 induced-value policy benchmarks offline."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sqlite3
import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from engine.market_benchmarks import CASES, FIXTURE_VERSION, POLICIES, MarketCase, MarketFixture
from engine.ledger import Ledger
from engine.store import Store
from research.analysis import paired_summary
from research.artifacts import code_identity, create_batch, digest_json, file_sha256, publish_bytes, publish_json
from research.attempts import execution_exclusions
from world.replay_verify import canonical_state_receipt, verify_replay


METRICS = {
    "gains_from_trade_cents": ("cents", "Sum of buyer reservation minus seller opportunity cost for executed units."),
    "efficiency_ratio": ("ratio", "Realized surplus / maximum feasible positive surplus; null when the benchmark is zero."),
    "volume_units": ("units", "Executed units before redemption; no resale is permitted."),
    "executed_price_cents": ("cents/unit", "Execution notional / executed units; null with no trades."),
    "interval_distance_cents": ("cents/unit", "VWAP distance outside the declared competitive price interval; zero inside."),
    "redemption_price_error_cents": ("cents/share", "Absolute VWAP distance from funded redemption; equity only."),
    "non_trading": ("indicator", "One if the entire market executes no trade; zero otherwise."),
    "unfilled_buyers": ("people", "Assigned one-unit buyers who acquire no unit; repeated submissions are not new demand."),
}


class BenchmarkSpec(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    contract: Literal["induced-market-study-v1"] = "induced-market-study-v1"
    key: str = Field(default="dual-price-benchmarks", pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,100}$")
    seeds: list[int] = Field(default_factory=lambda: [1, 2, 3], min_length=1, max_length=20)
    sessions: int = Field(default=4, ge=1, le=5)
    arrival: Literal["seeded", "value_order"] = "seeded"
    max_wall_seconds: int = Field(default=300, ge=1, le=3600)
    minimum_pairs: int = Field(default=3, ge=2, le=20)

    @model_validator(mode="after")
    def assignments(self):
        if len(set(self.seeds)) != len(self.seeds) or any(not 0 <= s < 2**31 for s in self.seeds):
            raise ValueError("seeds must be unique nonnegative 31-bit integers")
        return self


def feasible_allocation(case: MarketCase) -> dict:
    """Unit-demand, unit-supply surplus bound with fully funded buyers.

    Weakly profitable marginal units are excluded from the chosen quantity.
    Other zero-surplus allocations may also be optimal.
    """
    buyers, sellers = sorted(case.buyer_values, reverse=True), sorted(case.seller_costs)
    gains = [value - cost for value, cost in zip(buyers, sellers) if value > cost]
    quantity = len(gains)
    lower = max(sellers[quantity - 1] if quantity else 0,
                buyers[quantity] if quantity < len(buyers) else 0)
    upper = min(buyers[quantity - 1] if quantity else sellers[0],
                sellers[quantity] if quantity < len(sellers) else buyers[quantity - 1])
    return {"maximum_surplus_cents": sum(gains), "positive_surplus_quantity": quantity,
            "competitive_price_interval_cents": [lower, upper], "currency": "USD",
            "assumptions": "homogeneous unit; one unit per actor; cash >= reservation; transferable utility; no fees"}


def measure_market(store: Store, case: MarketCase) -> dict:
    """Reconstruct allocations from production sale/trade rows, never quotes."""
    buyers = {int(r["id"]): int(r["name"].split("-")[1])
              for r in store.query("SELECT id,name FROM agents WHERE name LIKE 'buyer-%'")}
    sellers = {int(r["id"]): int(r["name"].split("-")[1])
               for r in store.query("SELECT id,name FROM agents WHERE name LIKE 'seller-%'")}
    events = [dict(row) for row in store.query("SELECT * FROM events ORDER BY id")]
    executions = []
    if case.domain == "goods":
        firms = {int(r["id"]): sellers[int(r["founder_agent_id"])] for r in store.query("SELECT * FROM firms")}
        for event in events:
            if event["kind"] == "goods_sale":
                sale = json.loads(event["payload_json"])
                if sale["total_cents"] != sale["qty"] * sale["unit_price_cents"]:
                    raise ValueError("invalid benchmark sale notional")
                executions.append({"buyer": buyers[sale["buyer_id"]], "seller": firms[sale["firm_id"]],
                    "qty": sale["qty"], "price_cents": sale["unit_price_cents"], "session": event["tick"],
                    "evidence": {"table": "events", "id": event["id"]}})
    else:
        for trade in store.query("SELECT * FROM trades ORDER BY id"):
            executions.append({"buyer": buyers[int(trade["buyer_id"])], "seller": sellers[int(trade["seller_id"])],
                "qty": int(trade["qty"]), "price_cents": int(trade["price_cents"]), "session": int(trade["tick"]),
                "evidence": {"table": "trades", "id": int(trade["id"])}})
    if (any(e["qty"] != 1 or e["price_cents"] <= 0 for e in executions)
            or len({e["buyer"] for e in executions}) != len(executions)
            or len({e["seller"] for e in executions}) != len(executions)):
        raise ValueError("unit-demand or endowed supply invariant failed")
    if any(not case.seller_costs[e["seller"]] <= e["price_cents"] <= case.buyer_values[e["buyer"]]
           for e in executions):
        raise ValueError("execution violates private reservation bounds")
    benchmark = feasible_allocation(case)
    volume = len(executions)
    surplus = sum(case.buyer_values[e["buyer"]] - case.seller_costs[e["seller"]] for e in executions)
    maximum = benchmark["maximum_surplus_cents"]
    if not 0 <= surplus <= maximum:
        raise ValueError("realized surplus is outside its feasible bound")
    price = sum(e["price_cents"] for e in executions) / volume if volume else None
    lower, upper = benchmark["competitive_price_interval_cents"]
    books = [json.loads(e["payload_json"]) | {"session": e["tick"]}
             for e in events if e["kind"] == "benchmark_book"]
    stock_ok = (int(store.scalar("SELECT COALESCE(SUM(inventory),0) FROM firms")) + volume == len(case.seller_costs)
                if case.domain == "goods" else
                store.scalar("SELECT COALESCE(SUM(qty),0) FROM shares") == 0
                and store.scalar("SELECT SUM(shares_outstanding) FROM firms") == 0
                and store.scalar("SELECT balance_cents FROM accounts WHERE kind='benchmark_redemption'") == 0
                and len([e for e in events if e["kind"] == "benchmark_redemption"]) == 1)
    return {"case": case.key, "domain": case.domain, "currency": "USD", "benchmark": benchmark,
            "executions": executions, "books_before_expiry": books,
            "stock_reconciled": stock_ok,
            "price_missing_reason": None if volume else "no_execution",
            "last_trade_session": executions[-1]["session"] if volume else None,
            "metrics": {"gains_from_trade_cents": surplus,
                "efficiency_ratio": surplus / maximum if maximum else None,
                "volume_units": volume, "executed_price_cents": price,
                "interval_distance_cents": max(lower - price, price - upper, 0) if price is not None else None,
                "redemption_price_error_cents": abs(price - case.redemption_cents)
                    if price is not None and case.redemption_cents is not None else None,
                "non_trading": int(volume == 0), "unfilled_buyers": len(buyers) - volume}}


def _execute(path: Path, case: MarketCase, policy: str, seed: int, spec: BenchmarkSpec) -> dict:
    path.touch(exist_ok=False)
    store = Store(str(path))
    try:
        store.init_run_meta(f"{case.key}-{policy}-{seed}", seed, {
            "engine_semantics_version": 14, "market_fixture_version": FIXTURE_VERSION,
            "case": asdict(case), "policy": policy, "benchmark_spec": spec.model_dump(mode="json")})
        fixture = MarketFixture(store, case)
        genesis = canonical_state_receipt(store.conn)
        fixture.run(policy=policy, seed=seed, sessions=spec.sessions, arrival=spec.arrival)
        observation = measure_market(store, case)
        state = canonical_state_receipt(store.conn)
        return {"genesis_hash": genesis["sha256"], "source_state_hash": state["sha256"],
                "reconciled": fixture.ledger.reconcile()[0] and observation["stock_reconciled"],
                "database_integrity": store.scalar("PRAGMA quick_check") == "ok"
                    and not store.query("PRAGMA foreign_key_check") and state["references_valid"]
                    and genesis["references_valid"],
                "observation": observation, "metrics": observation["metrics"]}
    finally:
        store.close()


def verify_benchmark(row: dict, *, manifest_sha256: str, sessions: int) -> list[str]:
    """Check bound files, recompute prices/surplus and redo the canonical comparison."""
    reasons = execution_exclusions(row, expected_ticks=sessions)
    try:
        for key in ("claim", "source_database", "replay_database", "receipt"):
            if file_sha256(row[key]) != row[key + "_sha256"]:
                reasons.append(key + "_changed")
        for key in ("source_database", "replay_database"):
            wal = Path(row[key] + "-wal")
            if wal.exists() and wal.stat().st_size:
                reasons.append(key + "_changed")
        claim = json.loads(Path(row["claim"]).read_text(encoding="utf-8"))
        receipt = json.loads(Path(row["receipt"]).read_text(encoding="utf-8"))
        if (claim["manifest_sha256"] != manifest_sha256 or claim["case"] != row["case"]
                or claim["policy"] != row["arm"] or claim["seed"] != row["seed"]
                or claim["sessions"] != sessions):
            reasons.append("assignment_mismatch")
        if digest_json(receipt["row"]) != digest_json({k: row[k] for k in receipt["row"]}):
            reasons.append("receipt_mismatch")
        if receipt["execution"] != "deterministic_mechanics_rerun":
            reasons.append("wrong_reexecution_contract")
        comparison = verify_replay(row["source_database"], row["replay_database"])
        if not comparison["exact"] or comparison != receipt["comparison"]:
            reasons.append("canonical_reexecution_mismatch")
        store = Store(row["source_database"], create=False, read_only=True)
        try:
            actual = measure_market(store, CASES[row["case"]])
            if digest_json(actual) != digest_json(row["observation"]):
                reasons.append("measurement_mismatch")
            meta = store.get_meta()
            config = json.loads(meta["config_json"])
            if (int(meta["tick"]) != sessions or meta["active_tick"] is not None
                    or config["policy"] != row["arm"] or int(meta["seed"]) != row["seed"]
                    or digest_json(config["case"]) != digest_json(asdict(CASES[row["case"]]))):
                reasons.append("source_contract_mismatch")
            if (not Ledger(store).reconcile()[0] or not actual["stock_reconciled"]
                    or canonical_state_receipt(store.conn)["sha256"] != row["source_state_hash"]):
                reasons.append("source_state_mismatch")
        finally:
            store.close()
    except (OSError, KeyError, ValueError, TypeError, sqlite3.Error):
        reasons.append("missing_or_invalid_receipt")
    return sorted(set(reasons))


def run_benchmarks(spec: BenchmarkSpec, *, data_root: Path, out_dir: Path) -> dict:
    spec = BenchmarkSpec.model_validate(spec.model_dump())
    batch = create_batch(spec.key, {"kind": "induced_market_benchmark", "study": spec.model_dump(mode="json"),
        "fixture_version": FIXTURE_VERSION, "cases": {k: asdict(v) for k, v in CASES.items()},
        "policies": list(POLICIES), "metric_version": "induced-market-metrics-v1", "metrics": METRICS,
        "randomness": "sha256-keyed-by-case-seed-session-actor-purpose-v1",
        "information": "own reservation, remaining unit and own unfilled-session count; goods buyers see all current asks"},
        data_root=data_root, out_dir=out_dir)
    rows, started, stopped = [], time.monotonic(), None
    for case in CASES.values():
        for seed in spec.seeds:
            for policy_index, policy in enumerate(POLICIES):
                if time.monotonic() - started >= spec.max_wall_seconds:
                    stopped = "wall_time_guard"
                row = {"case": case.key, "arm": policy, "seed": seed, "expected_ticks": spec.sessions,
                    "ticks": 0, "execution_status": "planned", "final_boundary": False,
                    "reconciled": False, "database_integrity": False, "external_agent_influenced": False,
                    "metrics": {}, "eligibility": {"status": "ineligible", "reasons": [stopped] if stopped else []}}
                rows.append(row)
                if stopped:
                    continue
                attempt = Path(batch["data_dir"]) / f"{case.key}-p{policy_index}-s{seed}"
                attempt.mkdir(exist_ok=False)
                claim = publish_json(attempt / "claim.json", {"manifest_sha256": batch["manifest_sha256"],
                    "case": case.key, "policy": policy, "seed": seed, "sessions": spec.sessions})
                row.update(claim=str(claim), claim_sha256=file_sha256(claim), execution_status="running")
                try:
                    source, replay = attempt / "source.db", attempt / "replay.db"
                    result = _execute(source, case, policy, seed, spec)
                    repeated = _execute(replay, case, policy, seed, spec)
                    comparison = verify_replay(source, replay)
                    row.update(result, execution_status="completed", ticks=spec.sessions, final_boundary=True,
                        source_database=str(source), source_database_sha256=file_sha256(source),
                        replay_database=str(replay), replay_database_sha256=file_sha256(replay))
                    receipt = publish_json(attempt / "receipt.json", {
                        "execution": "deterministic_mechanics_rerun",
                        "row": {k: v for k, v in row.items() if k != "eligibility"},
                        "repeated_observation_matches": digest_json(result) == digest_json(repeated),
                        "comparison": comparison})
                    row.update(receipt=str(receipt), receipt_sha256=file_sha256(receipt))
                    reasons = verify_benchmark(row, manifest_sha256=batch["manifest_sha256"], sessions=spec.sessions)
                    if digest_json(result) != digest_json(repeated):
                        reasons.append("reexecution_observation_mismatch")
                    row["eligibility"] = {"status": "ineligible" if reasons else "eligible", "reasons": reasons}
                except Exception as exc:
                    row.update(execution_status="failed", error_type=type(exc).__name__,
                        eligibility={"status": "ineligible", "reasons": ["execution_failed"]})
                publish_json(attempt / "result.json", row)
    unchanged = code_identity() == batch["manifest"]["code"]
    if not unchanged:
        for row in rows:
            row["eligibility"] = {"status": "ineligible", "reasons": ["source_code_changed_during_campaign"]}
    summaries = {case: paired_summary([r for r in rows if r["case"] == case], POLICIES[0],
        expected_arms=list(POLICIES), expected_seeds=spec.seeds, expected_ticks=spec.sessions,
        expected_metrics=list(METRICS), minimum_pairs=spec.minimum_pairs) for case in CASES}
    for summary in summaries.values():
        summary["analysis_kind"] = "induced_market_policy_exploratory"
        for arms in summary["metrics"].values():
            for outcome in arms.values():
                effect = outcome.get("paired_effect")
                if effect and effect["interval_method"]:
                    effect["interval_method"] = "paired_market_assignment_percentile_bootstrap"
    payload = {"contract": "induced-market-result-v1", "batch": batch, "results": rows, "summaries": summaries,
        "operations": {"provider_calls": 0, "provider_spend_usd": 0, "code_unchanged": unchanged,
            "elapsed_seconds": round(time.monotonic() - started, 3), "stop_reason": stopped},
        "artifacts": {"json": str(Path(batch["report_dir"]) / "results.json"),
                      "markdown": str(Path(batch["report_dir"]) / "findings.md")}}
    publish_json(payload["artifacts"]["json"], payload)
    publish_bytes(payload["artifacts"]["markdown"], benchmark_markdown(payload).encode("utf-8"))
    return payload


def benchmark_markdown(payload: dict) -> str:
    lines = ["# Goods and equity policy benchmarks", "",
        "Exploratory induced-value markets. Each assignment is an isolated endowed market, not a daily World run.",
        "A fresh deterministic mechanics rerun is compared across canonical tables; this is not recorded LLM replay.",
        "No external provider calls or spend. Both price domains use the same seeds and policies.", "",
        "| Case | Policy | Assigned / completed / eligible | Mean surplus (cents) | Mean efficiency |",
        "|---|---|---|---:|---:|"]
    for case, summary in payload["summaries"].items():
        for policy, counts in summary["coverage"].items():
            lines.append(f"| {case} | {policy} | {counts['assigned']} / {counts['completed']} / {counts['eligible']} | "
                f"{summary['metrics']['gains_from_trade_cents'][policy]['mean']} | "
                f"{summary['metrics']['efficiency_ratio'][policy]['mean']} |")
    lines += ["", "## Paired policy differences", "", "Differences are treatment minus reservation-bound baseline.", "",
              "| Case | Outcome | Policy | Difference | 95% descriptive bootstrap interval | Usable pairs | Status |",
              "|---|---|---|---:|---|---:|---|"]
    for case, summary in payload["summaries"].items():
        for metric, arms in summary["metrics"].items():
            for policy, outcome in arms.items():
                effect = outcome.get("paired_effect")
                if effect:
                    lines.append(f"| {case} | {metric} | {policy} | {effect['mean_difference']} | "
                        f"{effect['ci95_bootstrap']} | {effect['n_pairs']} | {effect['status']} |")
    lines += ["", "## Limitations", "",
        "- Values and costs are imposed experimental assumptions. They do not establish real-economy fair value.",
        "- G1 starts with goods inventory; seller cost is opportunity cost, not a fabricated production payment.",
        "- F1 has fixed float, no resale, and funded terminal redemption. Private reservation differences include utility or liquidity preferences; surplus differs from cash profit.",
        "- Posted-price shopping and a session auction need not deliver a competitive-equilibrium price. Distance is descriptive, not a matching-correctness verdict.",
        "- Policy noise and arrival use independent stable keys. Daily-world RNG, LLM cognition and empirical validation are outside this fixture.",
        "- The wall-time guard is checked between bounded assignments, not an OS timeout. No real-time market latency claims.",
        "", "## Exclusions and operations", "", "```json", json.dumps({
            "exclusions": {k: s["exclusions"] for k, s in payload["summaries"].items()},
            "operations": payload["operations"]}, indent=2), "```", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", nargs="+", type=int, default=[1, 2, 3])
    parser.add_argument("--sessions", type=int, default=4)
    parser.add_argument("--data-root", type=Path, default=Path("data/studies"))
    parser.add_argument("--out-dir", type=Path, default=Path("reports/out"))
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    try:
        spec = BenchmarkSpec(seeds=args.seeds, sessions=args.sessions)
        if args.validate_only:
            print(json.dumps({"status": "valid", "assigned_markets": 2 * len(POLICIES) * len(spec.seeds),
                              "provider_calls": 0, "executed": False}))
            return 0
        result = run_benchmarks(spec, data_root=args.data_root, out_dir=args.out_dir)
        print(json.dumps({"artifacts": result["artifacts"],
                          "coverage": {k: v["coverage"] for k, v in result["summaries"].items()}}))
        return int(any(r["eligibility"]["status"] != "eligible" for r in result["results"]))
    except (ValueError, OSError) as exc:
        print(json.dumps({"status": "invalid", "error_type": type(exc).__name__}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
