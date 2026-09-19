import asyncio
from copy import deepcopy
import json
from pathlib import Path

import httpx
import pytest

from research.decision_studies import execute, freeze, prepare, read_snapshots, summarize_frozen
from run import open_run
from run_config import load_config
from tests.test_jev_contract import transport
from tests.test_jev_runtime import typed_handler

ROOT = Path(__file__).resolve().parents[1]


def profiles():
    return {name: load_config(ROOT / "runs" / filename) for name, filename in (
        ("baseline", "jev-offline.yaml"), ("jev", "jev-live.yaml"))}


def test_prospective_pair_and_frozen_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "private-fixture-key")
    transport(monkeypatch, typed_handler)
    configs = profiles()
    root = tmp_path / "study"
    prepare(configs, root, seeds=(7,), ticks=2)
    result = asyncio.run(execute(root, approve_live=True))
    assert result["status"] == "complete", result["cells"]
    assert all(cell["replay_exact"] for cell in result["cells"])
    assert result["provider_accounting"]["provider_calls"] > 0
    assert result["provider_accounting"]["sealed"]
    baseline = result["cells"][0]
    frozen_path = tmp_path / "observations.json"
    freeze(root / baseline["key"] / (baseline["run_id"] + ".db"), frozen_path)
    snapshots = read_snapshots(frozen_path)
    assert snapshots["records"]
    assert all(r["label_choice"] is None for r in snapshots["records"])
    frozen_root = tmp_path / "frozen-study"
    prepare(configs, frozen_root, seeds=(9,), ticks=1, snapshots=frozen_path)
    frozen_result = asyncio.run(execute(frozen_root, approve_live=True))
    assert frozen_result["status"] == "complete", frozen_result
    assert len(frozen_result["frozen"]) == len(snapshots["records"]) * 2
    assert all(s["ece_against_labels"] is None for s in frozen_result["frozen_summary"].values())
    with pytest.raises(FileExistsError):
        asyncio.run(execute(root, approve_live=True))


def test_study_refuses_background_drift_and_missing_allowance(tmp_path, monkeypatch):
    configs = profiles()
    configs["jev"]["population"]["size"] += 1
    with pytest.raises(ValueError, match="differ"):
        prepare(configs, tmp_path / "bad")
    assert not (tmp_path / "bad").exists()
    root = tmp_path / "study"
    prepare(profiles(), root, seeds=(1,), ticks=1)
    with pytest.raises(ValueError, match="approve-live"):
        asyncio.run(execute(root))
    assert not (root / "execution-started.json").exists()
    (root / "budget-contract.json").unlink()
    with pytest.raises(ValueError, match="missing or changed"):
        asyncio.run(execute(root, approve_live=True))


def test_failed_provider_keeps_assignments_and_original_charges(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "private-fixture-key")
    transport(monkeypatch, lambda req: httpx.Response(402, json={"error": "quota"}))
    root = tmp_path / "study"
    prepare(profiles(), root, seeds=(1, 2), ticks=1)
    result = asyncio.run(execute(root, approve_live=True))
    assert result["status"] == "incomplete"
    assert len(result["cells"]) == 4
    assert [r["status"] for r in result["cells"]] == ["complete", "failed", "excluded", "excluded"]
    assert result["provider_accounting"]["unknown_usage_calls"] >= 1
    assert result["provider_accounting"]["provider_calls"] == result["provider_accounting"]["unknown_usage_calls"]
    assert result["provider_accounting"]["encumbered_nano_usd"] > 0


def test_calibration_requires_labels_and_reports_each_split():
    base = dict(arm="jev", status="complete", baseline_agreement=1, cost_usd=0,
                latency_ms=2, confidence=.8, label_agreement=1, selection_status="selected")
    summaries = summarize_frozen([{**base, "split": "calibration"},
                                 {**base, "split": "held_out", "label_agreement": None}])
    assert summaries["jev:calibration"]["ece_against_labels"] == pytest.approx(.2)
    assert summaries["jev:held_out"]["ece_against_labels"] is None
