"""Scientific artifacts survive retries; inference fails closed on bad evidence."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sqlite3

import pytest

from engine.store import Store
from research.analysis import paired_summary
from research.artifacts import file_sha256, publish_bytes
from research.attempts import verify_attempt
from research.counterfactual import run_counterfactual
from research.scenarios import ScenarioPack
from world.loop import World
from world.replay_verify import canonical_state_receipt


def _config():
    return {
        "engine_semantics_version": 7, "seed": 1, "population": {"size": 14},
        "banks": {"count": 2}, "firms": {"count": 3, "listed": 1},
        "budget": {"cap_usd": 200.0, "oracle_reserve_usd": 10.0,
                   "conversation_pairs": 2, "thresholds": [0.60, 0.80, 0.95]},
        "llm": {"default_route": {"provider": "scripted", "model": "scripted"}, "routes": {}},
        "outlets": [{"id": 1, "name": "A", "slant": "pro-market-sensational"},
                    {"id": 2, "name": "B", "slant": "cautious-pro-labor"}],
    }


def _pack():
    return ScenarioPack(
        key="integrity", version="1", title="Integrity regression", ticks=2,
        base_config="runs/base.yaml", dataset_manifest="config/data-manifest.yaml",
        common_shocks=(), arms={"control": {}, "treatment": {}},
        metrics=("cpi",), limitations="Mechanical fixture, not empirical validation.",
        path="unused.yaml", checksum_sha256="test-fixture")


def _row(arm, seed, value, **changes):
    return {"arm": arm, "seed": seed, "metrics": {"price": value},
            "ticks": 30, "expected_ticks": 30, "execution_status": "completed",
            "final_boundary": True, "reconciled": True, "database_integrity": True,
            "genesis_hash": f"same-{seed}",
            "eligibility": {"status": "eligible", "reasons": []}, **changes}


def _effect(rows, **options):
    return paired_summary(rows, "control", bootstrap_samples=100, **options)["metrics"]["price"]["treatment"]["paired_effect"]


def test_incomplete_and_unreconciled_world_cannot_enter_paired_effect():
    rows = [_row("control", 1, 100),
            _row("treatment", 1, 130, ticks=3, reconciled=False)]
    effect = _effect(rows, expected_ticks=30)
    assert effect["mean_difference"] is None
    assert effect["ci95_bootstrap"] is None
    assert effect["n_pairs"] == 0
    reasons = effect["pair_exclusions"][0]["reasons"]
    assert "treatment:incomplete_horizon" in reasons
    assert "treatment:reconciliation_failed" in reasons


@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), True, "130"])
def test_missing_and_nonfinite_outcomes_are_unavailable(value):
    effect = _effect([_row("control", 1, 100), _row("treatment", 1, value)])
    assert effect["mean_difference"] is None
    assert effect["ci95_bootstrap"] is None
    assert effect["standardized_effect"] is None
    assert effect["status"] == "no_usable_pairs"


def test_single_pair_is_descriptive_and_zero_variance_standardization_undefined():
    rows = [_row("control", 1, 100), _row("treatment", 1, 130)]
    single = _effect(rows)
    assert single["mean_difference"] == 30
    assert single["ci95_bootstrap"] is None
    assert single["status"] == "insufficient_replication"
    rows += [_row("control", 2, 100), _row("treatment", 2, 130)]
    replicated = _effect(rows)
    assert replicated["ci95_bootstrap"] == [30, 30]
    assert replicated["standardized_effect"] is None
    assert replicated["n_pairs"] == 2


def test_missing_attempts_remain_in_assigned_coverage_and_duplicate_is_rejected():
    rows = [_row("control", 1, 100), _row("treatment", 2, 130)]
    result = paired_summary(rows, "control", expected_seeds=[1, 2, 3])
    assert result["coverage"]["control"] == {
        "assigned": 3, "started": 1, "completed": 1, "eligible": 1}
    assert len(result["exclusions"]) == 4
    assert result["metrics"]["price"]["treatment"]["paired_effect"]["n_pairs"] == 0
    with pytest.raises(ValueError, match="duplicate"):
        _effect(rows + [rows[0]])


def test_valid_economic_failure_is_an_outcome_but_unknown_initial_state_is_not_paired():
    rows = [_row("control", 1, 100), _row("treatment", 1, 0, bankruptcy=True)]
    assert _effect(rows)["mean_difference"] == -100
    rows[1]["genesis_hash"] = "different"
    assert _effect(rows)["mean_difference"] is None


def test_atomic_publication_cannot_replace_even_identical_artifacts(tmp_path):
    path = tmp_path / "receipt.json"
    publish_bytes(path, b"original")
    with pytest.raises(FileExistsError):
        publish_bytes(path, b"replacement")
    assert path.read_bytes() == b"original"
    assert list(tmp_path.iterdir()) == [path]


def test_repeated_counterfactual_preserves_every_source_and_report_byte(tmp_path):
    options = dict(seeds=[1], out_dir=tmp_path / "out", data_root=tmp_path / "data",
                   effective_config=_config())
    first = run_counterfactual(_pack(), **options)
    assert all(row["eligibility"]["status"] == "eligible" for row in first["results"]), first["results"]
    originals = {path: file_sha256(path) for path in tmp_path.rglob("*") if path.is_file()}
    second = run_counterfactual(_pack(), **options)
    assert first["batch"]["batch_id"] != second["batch"]["batch_id"]
    assert all(path.is_file() and file_sha256(path) == digest for path, digest in originals.items())
    assert all(row["eligibility"]["status"] == "eligible" for row in second["results"]), second["results"]
    assert first["results"][0]["genesis_hash"] == first["results"][1]["genesis_hash"]
    for row in first["results"]:
        assert verify_attempt(row, expected_ticks=2) == []
        receipt = json.loads(Path(row["replay_receipt"]).read_text())
        proof = receipt["comparison"]
        assert proof["exact"] and proof["source_hash"] == proof["replay_hash"]
        assert {table["table"] for table in proof["tables"]} >= {
            "agents", "accounts", "ledger_entries", "trades", "events", "llm_calls"}


def test_replay_and_source_tampering_are_detected_before_reanalysis(tmp_path):
    payload = run_counterfactual(_pack(), seeds=[1], out_dir=tmp_path / "out",
                                 data_root=tmp_path / "data", effective_config=_config())
    row = payload["results"][0]
    assert row["eligibility"]["status"] == "eligible", row
    forged = copy.deepcopy(row)
    forged["replay_hash"] = "invented-event-hash"
    assert "replay_mismatch" in verify_attempt(forged, expected_ticks=2)
    forged = copy.deepcopy(row)
    forged["config_sha256"] = "wrong-protocol"
    assert "attempt_contract_mismatch" in verify_attempt(forged, expected_ticks=2)
    with sqlite3.connect(row["source_database"]) as conn:
        conn.execute("UPDATE accounts SET balance_cents=balance_cents+1 WHERE id=1")
    reasons = verify_attempt(row, expected_ticks=2)
    assert "source_database_changed" in reasons
    assert "replay_mismatch" in reasons


def test_interruption_and_failure_remain_in_cohort_and_never_claim_replay(tmp_path, monkeypatch):
    async def interrupted(self, max_ticks=None):
        self.store.set_meta(status="paused")
    monkeypatch.setattr(World, "run", interrupted)
    paused = run_counterfactual(_pack(), seeds=[1], out_dir=tmp_path / "out",
                                data_root=tmp_path / "data", effective_config=_config())
    assert all(row["execution_status"] == "paused" for row in paused["results"])
    assert all(row["replay_hash"] is None for row in paused["results"])
    assert paused["summary"]["coverage"]["treatment"]["eligible"] == 0

    async def failed(self, max_ticks=None):
        raise RuntimeError("private provider detail must not enter the public result")
    monkeypatch.setattr(World, "run", failed)
    failed_result = run_counterfactual(_pack(), seeds=[1], out_dir=tmp_path / "out",
                                       data_root=tmp_path / "data", effective_config=_config())
    assert all(row["execution_status"] == "failed" for row in failed_result["results"])
    assert "private provider detail" not in json.dumps(failed_result)
    assert Path(failed_result["artifacts"]["json"]).is_file()
    effect = failed_result["summary"]["metrics"]["cpi"]["treatment"]["paired_effect"]
    assert effect["status"] == "no_usable_pairs" and effect["mean_difference"] is None
    assert all(Path(row["source_receipt"]).is_file() for row in failed_result["results"])


def test_genesis_hash_covers_state_beyond_events(tmp_path):
    store = Store(str(tmp_path / "source.db"))
    cfg = _config()
    store.init_run_meta("genesis", 1, cfg)
    world = World(store, cfg)
    try:
        world.initialize()
        before = canonical_state_receipt(store.conn)
        store.execute("UPDATE accounts SET balance_cents=balance_cents+1 WHERE id=1")
        after = canonical_state_receipt(store.conn)
        assert before["tables"]["events"] == after["tables"]["events"]
        assert before["sha256"] != after["sha256"]
    finally:
        world.close()
