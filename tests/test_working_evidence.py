"""Paused evidence remains readable and portable without granting resume rights."""
import json
from pathlib import Path

import pytest

from research.artifacts import file_sha256
from research.process_lock import ProcessLockBusy, process_lock
from research.study_bundle import export_study_bundle, import_study_bundle
from research.study_library import StudyLibrary
from research.study_results import StudyArtifactError
from research.study_runner import run_study
from research.studies import prepare_study
from research.working_evidence import load_working_progress
from research.working_studies import validate_resume
from tests.test_study_protocol import protocol
from tests.test_working_studies import _options
from tests.test_working_attempts import _bytes


def test_working_evidence_survives_code_change_export_and_later_source_resume(protocol, tmp_path, monkeypatch):
    options = _options(protocol, tmp_path)
    paused = run_study(**options, pause_after_ticks=1)
    path, data = Path(paused["artifacts"]["json"]), Path(paused["batch"]["data_dir"])
    roots = {key: options[key] for key in ("data_root", "out_dir")}
    library = StudyLibrary(**roots, export_root=tmp_path / "exports")
    item = library.public_catalog()["items"][0]
    assert item["kind"] == "working"
    view = library.verify(item["id"], item["result_sha256"])
    assert view["state"] == "paused" and view["export_available"]
    assert not view["comparison_available"]
    assert not ({"summary", "metrics", "outcomes", "measurements"} & view.keys())
    assert [row["ticks"] for row in view["attempts"]] == [1, 0]
    before = _bytes(tmp_path)
    with monkeypatch.context() as changed:
        changed.setattr("research.working_attempts.code_identity", lambda: {"git_commit": "new-checkout"})
        read = load_working_progress(path, **roots)
        assert read["verification"]["status"] == "verified"
        assert read["verification"]["eligibility"] == "pending"
        assert read["verification"]["operations"]["provider_calls"] == 0
        with pytest.raises(ValueError, match="code changed"):
            validate_resume(data, **options)
        assert _bytes(tmp_path) == before
        bundle = export_study_bundle(path, tmp_path / "working.zip", **roots)
    finished = run_study(**options, resume_batch=data)
    assert finished["status"] == "finalized"
    current = library.public_catalog()["items"][0]
    assert current["id"] == item["id"] and current["kind"] == "finalized"
    imported = import_study_bundle(bundle["path"], tmp_path / "copy")
    assert imported["status"] == imported["study_verification"]["status"] == "verified"
    assert imported["study_verification"]["publication"] == "working"
    assert imported["study_verification"]["eligibility"] == "pending"
    frozen = load_working_progress(imported["result_path"], data_root=tmp_path / "copy/data", out_dir=tmp_path / "copy/reports")
    assert [row["ticks"] for row in frozen["results"]] == [1, 0]
    with pytest.raises(StudyArtifactError):
        load_working_progress(path, **roots)


@pytest.mark.parametrize("owner", ["supervisor.lock", "working.lock"])
def test_working_export_cannot_copy_an_owned_checkpoint(protocol, tmp_path, owner):
    options = _options(protocol, tmp_path)
    paused = run_study(**options, pause_after_ticks=1)
    before = _bytes(tmp_path)
    with process_lock(Path(paused["batch"]["data_dir"]) / owner):
        library = StudyLibrary(data_root=options["data_root"], out_dir=options["out_dir"], export_root=tmp_path / "exports")
        item = library.public_catalog()["items"][0]
        view = library.verify(item["id"], item["result_sha256"])
        assert view["state"] == "running" and not view["export_available"]
        assert all(row["eligibility"]["status"] == "pending" for row in view["attempts"])
        with pytest.raises(ProcessLockBusy):
            export_study_bundle(paused["artifacts"]["json"], tmp_path / "blocked.zip",
                                data_root=options["data_root"], out_dir=options["out_dir"])
    assert _bytes(tmp_path) == before


def test_prepared_working_batch_is_discoverable_without_claiming_a_saved_checkpoint(protocol, tmp_path):
    options = _options(protocol, tmp_path)
    prepare_study(**options)
    library = StudyLibrary(data_root=options["data_root"], out_dir=options["out_dir"], export_root=tmp_path / "exports")
    before = _bytes(tmp_path)
    item = library.public_catalog()["items"][0]
    assert item["kind"] == "working"
    view = library.verify(item["id"], item["result_sha256"])
    assert view["state"] == "checkpoint_unavailable" and not view["export_available"]
    assert len(view["attempts"]) == 2
    assert all(row["execution_status"] == "planned" and row["eligibility"]["status"] == "pending" for row in view["attempts"])
    with pytest.raises(StudyArtifactError):
        library.export(item["id"], item["result_sha256"], view["verification_sha256"])
    assert _bytes(tmp_path) == before


def test_resealed_pause_claim_cannot_change_observations_without_source_evidence(protocol, tmp_path):
    options = _options(protocol, tmp_path)
    paused = run_study(**options, pause_after_ticks=1)
    data, report = Path(paused["batch"]["data_dir"]), Path(paused["artifacts"]["json"])
    row = paused["results"][0]
    row["metrics"]["posted_index"] = 123.0
    pause_path = Path(row["attempt_claim"]).parent / "segment-000001-pause.json"
    pause = json.loads(pause_path.read_text())
    pause["row"] = row
    pause_path.write_text(json.dumps(pause))
    worker = next((data / "supervision").glob("*-worker-*.json"))
    worker.write_text(json.dumps(row))
    report.write_text(json.dumps(paused))
    end_path = data / "supervision/invocation-000001-end.json"
    end = json.loads(end_path.read_text())
    end["workers"][0]["sha256"], end["report"]["sha256"] = file_sha256(worker), file_sha256(report)
    end_path.write_text(json.dumps(end))
    (data / "supervision/invocation-000001-seal.json").write_text(json.dumps({"end_sha256": file_sha256(end_path)}))
    before = _bytes(tmp_path)
    with pytest.raises(StudyArtifactError) as failure:
        load_working_progress(report, data_root=options["data_root"], out_dir=options["out_dir"])
    assert "observations" in str(failure.value.__cause__)
    assert _bytes(tmp_path) == before
