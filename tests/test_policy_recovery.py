"""Actual policy-world recovery under its original completion allowance."""
from __future__ import annotations

import json
import multiprocessing
from pathlib import Path
import shutil
import sqlite3
import threading

import pytest

from research.artifacts import file_sha256, publish_json
from research.attempts import verify_attempt
from research.policy_runner import _preflight
from research.policy_studies import policy_configurations, provider_budget_contract, study_cells, verify_budget_history
from research.provider_budget import BudgetLedgerError, ProviderBudget
from research.policy_recovery import open_allowance
from research.studies import StudySpec, prepare_study
from research.working_attempts import execute_working_attempt
from research.policy_results import load_policy_result
from research.study_runner import run_study
from research.working_studies import validate_resume
from research.study_results import StudyArtifactError
from tests.test_policy_studies import ROOT, base_policy_setup, policy_http_fixture


def working_setup(config, initial, tmp_path, policy):
    raw = initial.model_dump(mode="json")
    raw["operations"]["pause_policy"] = policy
    spec = StudySpec.model_validate(raw)
    batch = prepare_study(spec, config, input_root=ROOT, data_root=tmp_path / "data", out_dir=tmp_path / "reports")
    root = Path(batch["data_dir"])
    contract = provider_budget_contract(spec, config, manifest_sha256=batch["manifest_sha256"])
    publish_json(root / "provider-budget-contract.json", contract.model_dump(mode="json"))
    cell = next(item for item in study_cells(spec) if item["policy"] == "model_a")
    preflight = ProviderBudget.create(root / "provider-budget.db", contract, scope="preflight-model_a", binding_key="model_a")
    assert _preflight(policy_configurations(spec, config)["model_a"], preflight)["ready"]
    budget = ProviderBudget(preflight.path, contract, scope=cell["cell_key"], binding_key=cell["policy"])
    return spec, batch, cell, budget


@pytest.mark.parametrize("policy,controls", [
    ("preserve_and_resume", {"max_ticks": 1}),
    ("preserve_and_resume_phases", {"pause_after_phase": "MORNING"}),
])
def test_policy_world_resumes_original_budget_and_exact_recorded_inputs(tmp_path, policy, controls):
    with policy_http_fixture(base_policy_setup()) as (config, initial, posts):
        spec, batch, cell, budget = working_setup(config, initial, tmp_path, policy)
        arguments = dict(batch=batch, spec=spec, config=config, seed=cell["seed"], arm=cell["arm"],
                         policy_cell=cell, completion_guard=budget, input_root=ROOT)
        paused = execute_working_attempt(**arguments, **controls)
        assert paused["execution_status"] == "paused", paused
        assert paused["eligibility"]["status"] == "pending", paused
        prefix = paused["provider_budget_checkpoint"]
        assert prefix["usage"]["provider_calls"] == len(posts) > 1
        source_hash = file_sha256(Path(paused["source_database"]))
        verify_budget_history(paused, budget)
        assert file_sha256(Path(paused["source_database"])) == source_hash
        result = execute_working_attempt(**arguments, resume=True)
        assert result["eligibility"] == {"status": "eligible", "reasons": []}, result
        assert result["ticks"] == 3 and result["genesis_hash"] == paused["genesis_hash"]
        budget.verify_checkpoint(prefix)
        verify_budget_history(result, budget)
        assert budget.snapshot()["provider_calls"] == len(posts) > prefix["usage"]["provider_calls"]
        assert verify_attempt(result, expected_ticks=3) == []


def test_changed_reservation_history_refuses_before_resuming_world(tmp_path):
    with policy_http_fixture(base_policy_setup()) as (config, initial, posts):
        spec, batch, cell, budget = working_setup(config, initial, tmp_path, "preserve_and_resume")
        arguments = dict(batch=batch, spec=spec, config=config, seed=cell["seed"], arm=cell["arm"],
                         policy_cell=cell, completion_guard=budget, input_root=ROOT)
        paused = execute_working_attempt(**arguments, max_ticks=1)
        assert paused["eligibility"]["status"] == "pending"
        before, calls = file_sha256(Path(paused["source_database"])), len(posts)
        with sqlite3.connect(budget.path) as conn:
            conn.execute("UPDATE reservations SET input_tokens=input_tokens+1 WHERE scope=?", (cell["cell_key"],))
        with pytest.raises(BudgetLedgerError, match="history changed"):
            execute_working_attempt(**arguments, resume=True)
        assert len(posts) == calls and file_sha256(Path(paused["source_database"])) == before


def options(config, initial, tmp_path, pause_policy="preserve_and_resume"):
    raw = initial.model_dump(mode="json")
    raw["operations"].update(pause_policy=pause_policy, max_wall_seconds=240)
    # Run the live treatment first so every supervised pause exercises real
    # completion history; the scripted policy remains the analysis baseline.
    raw["arms"].reverse()
    return dict(spec=StudySpec.model_validate(raw), config=config, input_root=ROOT,
        data_root=tmp_path / "data", out_dir=tmp_path / "reports")


@pytest.mark.parametrize("pause_policy,controls", [
    ("preserve_and_resume", {"pause_after_ticks": 1}),
    ("preserve_and_resume_phases", {"pause_after_phase": "MORNING"}),
])
def test_supervised_policy_resume_preserves_allowance_and_verifies_both_prices(tmp_path, pause_policy, controls):
    with policy_http_fixture(base_policy_setup(), draws=["draw1", "draw2"]) as (config, initial, posts):
        args = options(config, initial, tmp_path, pause_policy)
        paused = run_study(**args, **controls, approve_live_inference=True)
        assert paused["status"] == "paused", paused
        assert paused["contract"] == "policy-working-progress-v1"
        assert paused["results"][0]["policy"] == "model_a"
        assert paused["results"][0]["provider_usage"]["provider_calls"] > 0
        assert all(row["eligibility"]["status"] == "pending" for row in paused["results"])
        data = Path(paused["batch"]["data_dir"])
        before = {path: file_sha256(path) for path in data.rglob("*.db")}
        calls = len(posts)
        validate_resume(data, **args)
        assert len(posts) == calls
        assert all(file_sha256(path) == digest for path, digest in before.items())
        saved = {path: file_sha256(path) for root in (data, Path(paused["batch"]["report_dir"])) for path in root.rglob("*.json")}
        final = run_study(**args, resume_batch=data, approve_live_inference=True)
        assert final["status"] == "finalized", final
        assert all(row["eligibility"]["status"] == "eligible" for row in final["results"]), final
        assert all(file_sha256(path) == digest for path, digest in saved.items())
        assert final["operations"]["provider_calls"] == len(posts) > calls
        assert final["provider_budget"]["usage"]["sealed"] is True
        for domain in ("goods_price", "equity_price"):
            assert final["summary"]["metrics"][domain]["model_a"]["paired_effect"]["n_pairs"] == 2
        before = {path: file_sha256(path) for path in data.rglob("*.db")}
        loaded = load_policy_result(final["artifacts"]["json"], data_root=args["data_root"], out_dir=args["out_dir"])
        assert loaded["verification"]["status"] == "verified", loaded["verification"]
        assert len(posts) == final["operations"]["provider_calls"]
        assert all(file_sha256(path) == digest for path, digest in before.items())


@pytest.mark.parametrize("change", ["missing", "changed", "sealed", "untracked_dispatch", "caps", "source", "unfinished"])
def test_supervised_resume_rejects_changed_evidence_before_calls(tmp_path, change):
    with policy_http_fixture(base_policy_setup()) as (config, initial, posts):
        args = options(config, initial, tmp_path)
        paused = run_study(**args, pause_after_ticks=1, approve_live_inference=True)
        data = Path(paused["batch"]["data_dir"])
        budget = open_allowance(paused["batch"])
        if change == "missing":
            budget.path.rename(data / "retained-allowance.db")
        elif change == "changed":
            with sqlite3.connect(budget.path) as conn:
                conn.execute("UPDATE reservations SET input_tokens=input_tokens+1")
        elif change == "sealed":
            budget.seal()
        elif change == "untracked_dispatch":
            admitted = ProviderBudget(budget.path, budget.contract, scope=paused["results"][0]["cell_key"], binding_key="model_a")
            admitted._reserve("fixture", "model-a", [{"role": "user", "content": "unexpected fixture"}],
                {"purpose": "decision", "max_tokens": 10})
        elif change == "caps":
            raw = args["spec"].model_dump(mode="json")
            raw["operations"]["max_provider_calls"] += 1
            args["spec"] = StudySpec.model_validate(raw)
        elif change == "source":
            with Path(paused["results"][0]["source_database"]).open("ab") as stream:
                stream.write(b"changed fixture")
        else:
            publish_json(data / "supervision/invocation-000002-start.json", {})
        before = {path: file_sha256(path) for path in tmp_path.rglob("*") if path.is_file()}
        calls = len(posts)
        with pytest.raises((ValueError, BudgetLedgerError)):
            run_study(**args, resume_batch=data, approve_live_inference=True)
        assert len(posts) == calls
        assert {path: file_sha256(path) for path in tmp_path.rglob("*") if path.is_file()} == before


@pytest.mark.parametrize("failure", ["smoke", "exhausted", "invalid_response"])
def test_recovery_failures_seal_allowance_and_exclude_incomplete_worlds(tmp_path, failure):
    with policy_http_fixture(base_policy_setup(), smoke_ok=failure != "smoke",
            max_calls=1 if failure == "exhausted" else 500, invalid_responses=failure == "invalid_response") as (config, initial, posts):
        args = options(config, initial, tmp_path)
        result = run_study(**args, approve_live_inference=True)
        assert result["status"] == "finalized"
        assert result["provider_budget"]["usage"]["sealed"] is True
        assert 1 <= len(posts) <= result["provider_budget"]["usage"]["provider_calls"]
        assert all(row["eligibility"]["status"] == "ineligible" for row in result["results"])
        loaded = load_policy_result(result["artifacts"]["json"], data_root=args["data_root"], out_dir=args["out_dir"])
        assert loaded["verification"]["status"] == "verified", loaded["verification"]
        for domain in ("goods_price", "equity_price"):
            assert loaded["summary"]["metrics"][domain]["model_a"]["paired_effect"]["n_pairs"] == 0
        calls = len(posts)
        with pytest.raises(ValueError, match="published studies"):
            run_study(**args, resume_batch=result["batch"]["data_dir"], approve_live_inference=True)
        assert len(posts) == calls


def test_completed_cells_are_immutable_across_repeated_policy_resume_and_relocation(tmp_path, monkeypatch):
    with policy_http_fixture(base_policy_setup()) as (config, initial, posts):
        args = options(config, initial, tmp_path)
        first = run_study(**args, pause_after_ticks=1, approve_live_inference=True)
        data = Path(first["batch"]["data_dir"])
        second = run_study(**args, resume_batch=data, pause_after_ticks=2, approve_live_inference=True)
        assert [row["execution_status"] for row in second["results"]][:2] == ["completed", "paused"]
        completed = Path(second["results"][0]["attempt_claim"]).parent
        hashes = {path: file_sha256(path) for path in completed.rglob("*") if path.is_file()}
        final = run_study(**args, resume_batch=data, approve_live_inference=True)
        assert final["results"][0] == second["results"][0]
        assert {path: file_sha256(path) for path in completed.rglob("*") if path.is_file()} == hashes
        assert final["operations"]["supervision"]["invocation"] == 3
        assert final["operations"]["provider_calls"] == len(posts)
        copied_data, copied_reports = tmp_path / "copied-data", tmp_path / "copied-reports"
        shutil.copytree(args["data_root"], copied_data)
        shutil.copytree(args["out_dir"], copied_reports)
        path = copied_reports / Path(final["artifacts"]["json"]).relative_to(args["out_dir"])
        monkeypatch.setattr("research.policy_studies.prompt_source_identity", lambda: "f" * 64)
        loaded = load_policy_result(path, data_root=copied_data, out_dir=copied_reports)
        assert loaded["verification"]["status"] == "verified", loaded["verification"]
        # Rewriting public summaries and their checksums cannot promote an
        # edited price past the closed supervised worker evidence.
        from tests.test_policy_studies import republish_test_report
        forged = json.loads(path.read_text())
        forged["results"][0]["metrics"]["goods_price"] = 1_000_000
        republish_test_report(path, forged)
        copied_batch = copied_data / data.relative_to(args["data_root"])
        end_path = copied_batch / "supervision/invocation-000003-end.json"
        end = json.loads(end_path.read_text())
        end["report"]["sha256"] = file_sha256(path)
        end_path.write_text(json.dumps(end), encoding="utf-8")
        (copied_batch / "supervision/invocation-000003-seal.json").write_text(
            json.dumps({"end_sha256": file_sha256(end_path)}), encoding="utf-8")
        with pytest.raises(StudyArtifactError):
            load_policy_result(path, data_root=copied_data, out_dir=copied_reports)


def test_failed_resume_preflight_preserves_completed_policy_evidence(tmp_path):
    with policy_http_fixture(base_policy_setup()) as (config, initial, posts):
        args = options(config, initial, tmp_path)
        first = run_study(**args, pause_after_ticks=1, approve_live_inference=True)
        data = Path(first["batch"]["data_dir"])
        second = run_study(**args, resume_batch=data, pause_after_ticks=2, approve_live_inference=True)
        completed = second["results"][0]
        assert completed["eligibility"]["status"] == "eligible"
        calls = len(posts)
    # The loopback provider has closed. Resume must record its failed smoke,
    # retain earlier completed cells and exclude the remaining assignment.
    final = run_study(**args, resume_batch=data, approve_live_inference=True)
    assert final["operations"]["stop_reason"] == "live_preflight_failed", final
    assert final["results"][0] == completed
    assert len(posts) == calls
    loaded = load_policy_result(final["artifacts"]["json"], data_root=args["data_root"], out_dir=args["out_dir"])
    assert loaded["verification"]["status"] == "verified", loaded["verification"]
    assert loaded["results"][0]["eligibility"]["status"] == "eligible"
    assert all(row["eligibility"]["status"] == "ineligible" for row in loaded["results"][1:])


def test_working_live_launch_requires_approval_before_artifacts(tmp_path):
    config, spec = base_policy_setup()
    args = options(config, spec, tmp_path)
    with pytest.raises(ValueError, match="explicit approval"):
        run_study(**args)
    assert list(tmp_path.iterdir()) == []


def test_normal_interruption_seals_working_allowance(tmp_path):
    config, spec = base_policy_setup()
    args = options(config, spec, tmp_path)
    batches = []

    def interrupt(event):
        batches.append(event["batch"])
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        run_study(**args, progress=interrupt, approve_live_inference=True)
    budget = open_allowance(batches[0], read_only=True)
    assert budget.is_sealed() and budget.snapshot()["provider_calls"] == 0
    assert not (Path(batches[0]["report_dir"]) / "publication.json").exists()


def launch_working_fixture(args, guard):
    args["spec"] = StudySpec.model_validate(args["spec"])
    run_study(**args, worker_guard_path=Path(guard), approve_live_inference=True)


def test_hard_working_supervisor_death_keeps_unresolved_calls_and_refuses_resume(tmp_path):
    from research.process_lock import process_lock
    started, release = threading.Event(), threading.Event()
    guard = tmp_path / "owned-worker.lock"
    with policy_http_fixture(base_policy_setup(), hold_response=(started, release)) as (config, initial, posts):
        args = options(config, initial, tmp_path)
        supervisor = multiprocessing.get_context("spawn").Process(target=launch_working_fixture,
            args=({**args, "spec": args["spec"].model_dump(mode="json")}, str(guard)))
        supervisor.start()
        try:
            assert started.wait(timeout=30)
            supervisor.terminate()
            supervisor.join(timeout=5)
            assert not supervisor.is_alive()
            with process_lock(guard, wait_seconds=10):
                manifest = next(args["data_root"].glob("*/*/manifest.json"))
                batch = json.loads(manifest.read_text())
                batch["data_dir"] = str(manifest.parent)
                budget = open_allowance(batch, read_only=True)
                assert not budget.is_sealed()
                assert budget.snapshot()["provider_calls"] == budget.snapshot()["unresolved_calls"] == 1
                with pytest.raises(ValueError, match="unfinished or missing supervision"):
                    run_study(**args, resume_batch=manifest.parent, approve_live_inference=True)
                assert len(posts) == 1
        finally:
            release.set()
            if supervisor.is_alive():
                supervisor.terminate()
                supervisor.join(timeout=5)
            supervisor.close()
