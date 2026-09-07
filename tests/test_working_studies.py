"""Supervision retains scientific identity, assignments and cumulative limits."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from research.artifacts import digest_json, file_sha256
from research.attempts import verify_attempt
from research.process_lock import ProcessLockBusy, process_lock
from research.studies import StudySpec
from research.study_bundle import export_study_bundle, import_study_bundle
from research.study_results import StudyArtifactError, load_study_result
from research.study_runner import run_study
from research.working_studies import validate_resume
from tests.test_research_attempt_integrity import _config
from tests.test_study_protocol import protocol
from tests.test_working_attempts import _bytes


def _options(protocol, tmp_path):
    raw, config = copy.deepcopy(protocol), _config()
    raw["operations"].update(pause_policy="preserve_and_resume", max_wall_seconds=120)
    raw["randomness"]["seeds"] = [1]
    raw["model"]["resolved_config_sha256"] = digest_json(config)
    return dict(spec=StudySpec.model_validate(raw), config=config, input_root=tmp_path,
                data_root=tmp_path / "data", out_dir=tmp_path / "out")


def test_supervised_pause_resume_verifies_both_domains_and_portable_history(protocol, tmp_path):
    options = _options(protocol, tmp_path)
    paused = run_study(**options, pause_after_ticks=1)
    data, report = Path(paused["batch"]["data_dir"]), Path(paused["batch"]["report_dir"])
    assert paused["status"] == "paused"
    assert [row["execution_status"] for row in paused["results"]] == ["paused", "planned"]
    assert all(row["eligibility"]["status"] == "pending" for row in paused["results"])
    assert paused["summary"]["coverage"]["base"]["eligible"] == 0
    assert not (report / "results.json").exists() and not (report / "publication.json").exists()
    before = _bytes(tmp_path)
    state = validate_resume(data, **options)
    assert state["active_wall_seconds"] > paused["results"][0]["active_wall_seconds"]
    assert _bytes(tmp_path) == before
    saved = {path: file_sha256(path) for root in (data, report) for path in root.rglob("*.json")}
    completed = run_study(**options, resume_batch=data)
    assert completed["status"] == "finalized" and completed["operations"]["stop_reason"] is None
    assert all(row["eligibility"] == {"status": "eligible", "reasons": []} for row in completed["results"]), completed
    assert completed["operations"]["elapsed_seconds"] > state["active_wall_seconds"]
    assert set(completed["summary"]["metrics"]) == {"posted_index", "equity_price"}
    assert all(file_sha256(path) == digest for path, digest in saved.items())
    assert all(verify_attempt(row, expected_ticks=3) == [] for row in completed["results"])
    loaded = load_study_result(completed["artifacts"]["json"], data_root=options["data_root"], out_dir=options["out_dir"])
    assert loaded["verification"]["status"] == "verified", loaded["verification"]
    bundle = export_study_bundle(completed["artifacts"]["json"], tmp_path / "bundle.zip",
                                 data_root=options["data_root"], out_dir=options["out_dir"])
    imported = import_study_bundle(bundle["path"], tmp_path / "imported")
    assert imported["status"] == "verified"
    assert imported["study_verification"]["status"] == "verified"
    before = _bytes(tmp_path)
    with pytest.raises(ValueError, match="published studies"):
        run_study(**options, resume_batch=data)
    assert _bytes(tmp_path) == before


def test_resume_keeps_completed_cell_bytes_and_remaining_assignment(protocol, tmp_path):
    options = _options(protocol, tmp_path)
    first = run_study(**options, pause_after_ticks=1)
    data = Path(first["batch"]["data_dir"])
    second = run_study(**options, resume_batch=data, pause_after_ticks=2)
    assert [row["ticks"] for row in second["results"]] == [3, 2]
    assert [row["execution_status"] for row in second["results"]] == ["completed", "paused"]
    finished = Path(second["results"][0]["attempt_claim"]).parent
    before = _bytes(finished)
    final = run_study(**options, resume_batch=data)
    assert final["results"][0] == second["results"][0]
    assert _bytes(finished) == before
    assert all(row["eligibility"]["status"] == "eligible" for row in final["results"])
    assert len(list((data / "supervision").glob("*-start.json"))) == 3


@pytest.mark.parametrize("change", ["code", "config", "worker", "progress", "time", "time_resealed", "unfinished", "source"])
def test_changed_or_unfinished_supervision_refuses_without_writes(protocol, tmp_path, monkeypatch, change):
    options = _options(protocol, tmp_path)
    result = run_study(**options, pause_after_ticks=1)
    data, report = Path(result["batch"]["data_dir"]), Path(result["batch"]["report_dir"])
    if change == "code":
        monkeypatch.setattr("research.working_attempts.code_identity", lambda: {"git_commit": "changed"})
    elif change == "config":
        options["config"]["population"]["size"] += 1
    elif change == "worker":
        next((data / "supervision").glob("*-worker-*.json")).write_text("{}")
    elif change == "progress":
        (report / "progress-000001.json").write_text("{}")
    elif change == "source":
        with Path(result["results"][0]["source_database"]).open("ab") as output:
            output.write(b"changed")
    elif change == "unfinished":
        (data / "supervision" / "invocation-000002-start.json").write_text("{}")
    else:
        path = data / "supervision" / "invocation-000001-end.json"
        end = json.loads(path.read_text())
        end["active_wall_seconds"] = end["active_wall_seconds"] - .01 if change == "time" else 0
        path.write_text(json.dumps(end))
        if change == "time_resealed":
            seal = data / "supervision" / "invocation-000001-seal.json"
            seal.write_text(json.dumps({"end_sha256": file_sha256(path)}))
    before = _bytes(tmp_path)
    with pytest.raises((ValueError, KeyError)):
        run_study(**options, resume_batch=data)
    assert _bytes(tmp_path) == before


def test_concurrent_supervisor_cannot_claim_a_paused_batch(protocol, tmp_path):
    options = _options(protocol, tmp_path)
    result = run_study(**options, pause_after_ticks=1)
    data = Path(result["batch"]["data_dir"])
    before = _bytes(tmp_path)
    with process_lock(data / "supervisor.lock"):
        with pytest.raises(ProcessLockBusy):
            run_study(**options, resume_batch=data)
    assert _bytes(tmp_path) == before


def test_resume_validation_and_execution_share_the_original_wall_budget(protocol, tmp_path, monkeypatch):
    options = _options(protocol, tmp_path)
    result = run_study(**options, pause_after_ticks=1)
    data = Path(result["batch"]["data_dir"])
    source = Path(result["results"][0]["source_database"])
    original_source = file_sha256(source)
    databases = {path: file_sha256(path) for path in data.rglob("*.db")}
    before = validate_resume(data, **options)["active_wall_seconds"]
    calls = iter([0.0])
    monkeypatch.setattr("research.working_studies.time", SimpleNamespace(monotonic=lambda: next(calls, 120.0)))
    final = run_study(**options, resume_batch=data)
    assert final["status"] == "finalized"
    assert final["operations"]["stop_reason"] == "wall_time_budget_exhausted"
    assert final["operations"]["elapsed_seconds"] == before + 120.0
    assert all(row["eligibility"]["status"] == "ineligible" for row in final["results"])
    assert file_sha256(source) == original_source
    assert {path: file_sha256(path) for path in data.rglob("*.db")} == databases


def test_hard_deadline_stops_the_owned_worker_and_keeps_assignments(protocol, tmp_path):
    options = _options(protocol, tmp_path)
    raw = options["spec"].model_dump(mode="json")
    raw["operations"]["max_wall_seconds"] = 3
    raw["time"].update(horizon=10000, measurement_end=10000)
    options["spec"] = StudySpec.model_validate(raw)
    result = run_study(**options)
    assert result["operations"]["stop_reason"] == "wall_time_budget_exhausted"
    assert result["status"] == "finalized"
    assert all(row["eligibility"]["status"] == "ineligible" for row in result["results"])
    assert result["results"][1]["execution_status"] == "planned"
    assert not list(Path(result["batch"]["data_dir"]).rglob("replay-receipt.json"))
    import multiprocessing
    assert not [child for child in multiprocessing.active_children() if child.name.startswith("working-study-")]


@pytest.mark.parametrize("change", ["supervisor", "cell_result"])
def test_finalized_supervision_requires_its_publication_seal(protocol, tmp_path, change):
    options = _options(protocol, tmp_path)
    result = run_study(**options)
    data = Path(result["batch"]["data_dir"])
    if change == "supervisor":
        end = data / "supervision" / "invocation-000001-end.json"
        end.write_text("{}")
        with pytest.raises(StudyArtifactError):
            load_study_result(result["artifacts"]["json"], data_root=options["data_root"], out_dir=options["out_dir"])
    else:
        path = Path(result["results"][0]["attempt_claim"]).parent / "result.json"
        modified = json.loads(path.read_text())
        modified["finalization_wall_seconds"] = 0
        path.write_text(json.dumps(modified))
        loaded = load_study_result(result["artifacts"]["json"], data_root=options["data_root"], out_dir=options["out_dir"])
        assert loaded["verification"]["status"] == "degraded"
        assert "finalized_working_result_changed" in loaded["results"][0]["eligibility"]["reasons"]
        assert loaded["results"][1]["eligibility"]["status"] == "eligible"


def test_cli_pauses_validates_existing_batch_and_resumes(protocol, tmp_path, monkeypatch, capsys):
    from research.study_runner import main
    options = _options(protocol, tmp_path)
    monkeypatch.setattr("research.study_runner.load_study", lambda _: options["spec"])
    monkeypatch.setattr("research.study_runner.load_config", lambda _: options["config"])
    argv = ["study-runner", "study.yaml", "--config", "config.yaml", "--input-root", str(tmp_path),
            "--data-root", str(options["data_root"]), "--out-dir", str(options["out_dir"])]
    monkeypatch.setattr("sys.argv", [*argv, "--pause-after-ticks", "1"])
    assert main() == 1  # An intentional pause is still an incomplete study.
    paused = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert paused["status"] == "paused"
    before = _bytes(tmp_path)
    monkeypatch.setattr("sys.argv", [*argv, "--resume-batch", paused["batch"], "--validate-only"])
    assert main() == 0
    assert json.loads(capsys.readouterr().out)["executed"] is False
    assert _bytes(tmp_path) == before
    monkeypatch.setattr("sys.argv", [*argv, "--resume-batch", paused["batch"]])
    assert main() == 0
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["status"] == "finalized"


def _orphan_supervisor(options, marker, guard):
    from research.artifacts import publish_json

    def progress(event):
        if event["stage"] == "prepared":
            publish_json(marker, event["batch"])

    run_study(**options, progress=progress, worker_guard_path=guard)


def test_supervisor_death_stops_working_child_and_cannot_reset_budget(protocol, tmp_path):
    import multiprocessing
    import time
    options = _options(protocol, tmp_path)
    raw = options["spec"].model_dump(mode="json")
    raw["time"].update(horizon=10000, measurement_end=10000)
    options["spec"] = StudySpec.model_validate(raw)
    marker, guard = tmp_path / "batch.json", tmp_path / "worker.lock"
    supervisor = multiprocessing.get_context("spawn").Process(target=_orphan_supervisor, args=(options, marker, guard))
    supervisor.start()
    try:
        deadline, active = time.monotonic() + 30, False
        while time.monotonic() < deadline and supervisor.is_alive():
            try:
                with process_lock(guard):
                    pass
            except ProcessLockBusy:
                active = True
                break
            time.sleep(.02)
        assert active, "working child did not acquire its ownership guard"
        supervisor.kill()
        supervisor.join(timeout=10)
        stopped, deadline = False, time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                with process_lock(guard):
                    stopped = True
                    break
            except ProcessLockBusy:
                time.sleep(.02)
        assert stopped, "orphaned working child retained its ownership guard"
        batch = json.loads(marker.read_text())
        before = _bytes(tmp_path)
        with pytest.raises(ValueError, match="unfinished"):
            run_study(**options, resume_batch=batch["data_dir"])
        assert _bytes(tmp_path) == before
        assert not Path(batch["report_dir"], "publication.json").exists()
    finally:
        if supervisor.is_alive():
            supervisor.kill()
            supervisor.join(timeout=10)
        supervisor.close()
