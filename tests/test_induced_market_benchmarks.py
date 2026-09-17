import copy
import itertools
import json
import random
from pathlib import Path

import pytest
from pydantic import ValidationError

from engine.market_benchmarks import CASES, POLICIES, MarketCase, policy_quote
from engine.store import Store
from research.artifacts import file_sha256
from research.benchmarks import (
    BenchmarkSpec, _execute, feasible_allocation, measure_market, run_benchmarks, verify_benchmark,
)


@pytest.mark.parametrize("case,surplus,price,interval", [
    ("G1", 160, 30, [80, 90]), ("F1", 60, 85, [90, 110])])
def test_known_allocation_prices_and_funded_redemption(tmp_path, case, surplus, price, interval):
    path = tmp_path / "source.db"
    result = _execute(path, CASES[case], POLICIES[0], 1,
                      BenchmarkSpec(seeds=[1], sessions=1, arrival="value_order"))
    assert result["reconciled"] and result["database_integrity"]
    assert result["metrics"]["gains_from_trade_cents"] == surplus
    assert result["metrics"]["efficiency_ratio"] == 1
    assert result["metrics"]["executed_price_cents"] == price
    assert result["metrics"]["volume_units"] == 2
    assert result["observation"]["benchmark"]["competitive_price_interval_cents"] == interval
    store = Store(str(path), create=False, read_only=True)
    try:
        assert measure_market(store, CASES[case]) == result["observation"]
        if case == "F1":
            assert store.scalar("SELECT SUM(qty) FROM shares") is None
            assert store.scalar("SELECT SUM(shares_outstanding) FROM firms") == 0
            assert store.scalar("SELECT balance_cents FROM accounts WHERE kind='benchmark_redemption'") == 0
            # Every unit redeems, including the original sellers who never sold.
            assert store.scalar("SELECT COUNT(*) FROM transactions WHERE kind='benchmark_redemption'") == 4
        else:
            assert store.scalar("SELECT SUM(inventory) FROM firms") == 2
    finally:
        store.close()


def test_surplus_oracle_agrees_with_exhaustive_feasible_allocations():
    rng = random.Random(14)
    for _ in range(24):
        values = tuple(rng.randint(1, 30) for _ in range(rng.randint(1, 4)))
        costs = tuple(rng.randint(1, 30) for _ in range(rng.randint(1, 4)))
        possible = [0]
        for count in range(1, min(len(values), len(costs)) + 1):
            for chosen_buyers in itertools.combinations(values, count):
                for chosen_sellers in itertools.permutations(costs, count):
                    possible.append(sum(v - c for v, c in zip(chosen_buyers, chosen_sellers)))
        oracle = feasible_allocation(MarketCase("oracle", "goods", values, costs))
        assert oracle["maximum_surplus_cents"] == max(possible)
        lower, upper = oracle["competitive_price_interval_cents"]
        assert lower <= upper


@pytest.mark.parametrize("domain", ["goods", "equities"])
def test_illiquid_market_reports_null_price_and_preserves_endowments(tmp_path, domain):
    case = MarketCase("illiquid", domain, (20, 30), (90, 100), 75 if domain == "equities" else None)
    result = _execute(tmp_path / "source.db", case, POLICIES[0], 1, BenchmarkSpec(sessions=2))
    assert result["reconciled"]
    assert result["metrics"]["volume_units"] == 0
    assert result["metrics"]["executed_price_cents"] is None
    assert result["metrics"]["interval_distance_cents"] is None
    assert result["metrics"]["efficiency_ratio"] is None
    assert result["metrics"]["non_trading"] == 1
    assert result["observation"]["price_missing_reason"] == "no_execution"
    if domain == "equities":
        assert result["observation"]["books_before_expiry"][-1] == {
            "session": 2, "best_bid_cents": 30, "best_ask_cents": 90,
            "bid_quantity": 2, "ask_quantity": 2}


def test_each_policy_respects_private_reservation_bounds():
    for policy in POLICIES:
        for session, reservation, draw in itertools.product(range(5), (1, 20, 120), (0, 71, 2**64)):
            assert 1 <= policy_quote(policy, side="buy", reservation=reservation,
                unfilled_sessions=session, draw=draw) <= reservation
            assert policy_quote(policy, side="sell", reservation=reservation,
                unfilled_sessions=session, draw=draw) >= reservation


def test_real_dual_campaign_pairs_policies_and_preserves_reexecution(tmp_path):
    spec = BenchmarkSpec(seeds=[7, 9], sessions=2)
    payload = run_benchmarks(spec, data_root=tmp_path / "d", out_dir=tmp_path / "o")
    assert len(payload["results"]) == 12
    for row in payload["results"]:
        assert row["eligibility"] == {"status": "eligible", "reasons": []}, row
        assert verify_benchmark(row, manifest_sha256=payload["batch"]["manifest_sha256"], sessions=2) == []
        assert verify_benchmark(row, manifest_sha256="0" * 64, sessions=2) == ["assignment_mismatch"]
    for case in CASES:
        selected = [r for r in payload["results"] if r["case"] == case and r["seed"] == 7]
        assert len({r["genesis_hash"] for r in selected}) == 1
        effect = payload["summaries"][case]["metrics"]["gains_from_trade_cents"][POLICIES[1]]["paired_effect"]
        assert effect["n_pairs"] == 2
        assert effect["ci95_bootstrap"] is None  # Declared minimum is three.
        assert effect["status"] == "insufficient_replication"
    assert payload["operations"]["provider_calls"] == 0
    assert payload["operations"]["code_unchanged"]
    assert "not recorded LLM replay" in Path(payload["artifacts"]["markdown"]).read_text()
    original = {r["source_database"]: file_sha256(r["source_database"]) for r in payload["results"]}
    second = run_benchmarks(BenchmarkSpec(seeds=[7], sessions=1), data_root=tmp_path / "d", out_dir=tmp_path / "o")
    assert payload["batch"]["data_dir"] != second["batch"]["data_dir"]
    assert original == {path: file_sha256(path) for path in original}


def test_changed_results_or_database_cannot_pass_verification(tmp_path):
    payload = run_benchmarks(BenchmarkSpec(seeds=[1], sessions=1), data_root=tmp_path / "d", out_dir=tmp_path / "o")
    row = payload["results"][0]
    kwargs = {"manifest_sha256": payload["batch"]["manifest_sha256"], "sessions": 1}
    altered = copy.deepcopy(row)
    altered["metrics"]["gains_from_trade_cents"] = 10_000
    assert "receipt_mismatch" in verify_benchmark(altered, **kwargs)
    source = Store(row["source_database"], create=False)
    try:
        source.execute("UPDATE firms SET inventory=99")
        assert "source_database_changed" in verify_benchmark(row, **kwargs)
    finally:
        source.close()
    assert "source_state_mismatch" in verify_benchmark(row, **kwargs)


def test_failed_execution_stays_assigned_and_preserves_partial_source(tmp_path, monkeypatch):
    from research import benchmarks
    original = benchmarks._execute
    failed = False
    def fail_once(path, *args, **kwargs):
        nonlocal failed
        if not failed:
            failed = True
            path.write_bytes(b"preserved partial artifact")
            raise RuntimeError("private diagnostic must not be published")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(benchmarks, "_execute", fail_once)
    payload = run_benchmarks(BenchmarkSpec(seeds=[1], sessions=1), data_root=tmp_path / "d", out_dir=tmp_path / "o")
    assert payload["results"][0]["execution_status"] == "failed"
    assert payload["summaries"]["G1"]["coverage"][POLICIES[0]] == {
        "assigned": 1, "started": 1, "completed": 0, "eligible": 0}
    effect = payload["summaries"]["G1"]["metrics"]["volume_units"][POLICIES[1]]["paired_effect"]
    assert effect["mean_difference"] is None
    assert "private diagnostic" not in json.dumps(payload)
    assert list((tmp_path / "d").rglob("source.db"))[0].exists()


@pytest.mark.parametrize("change", [
    {"seeds": [True]}, {"seeds": [1, 1]}, {"seeds": [-1]}, {"seeds": []},
    {"sessions": 0}, {"sessions": 6}, {"arrival": "secret_oracle"}, {"live": True}])
def test_invalid_protocol_rejected(change):
    with pytest.raises(ValidationError):
        BenchmarkSpec(**change)
