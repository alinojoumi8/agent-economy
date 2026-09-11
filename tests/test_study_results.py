import copy
import json
from pathlib import Path
import shutil

import pytest

from engine.store import Store
from research.artifacts import digest_json, file_sha256
from research.studies import StudySpec
from research.study_runner import run_study
from research.study_results import StudyArtifactError, StudyLocation, load_study_result
from research.attempts import verify_attempt
from tests.test_research_attempt_integrity import _config
from tests.test_study_protocol import protocol as protocol_fixture


@pytest.fixture(scope="module")
def study_snapshot(tmp_path_factory):
    root = tmp_path_factory.mktemp("study")
    protocol = protocol_fixture.__wrapped__()
    config = _config()
    protocol["model"]["resolved_config_sha256"] = digest_json(config)
    protocol["randomness"]["seeds"] = [1]
    payload = run_study(StudySpec.model_validate(protocol), config, input_root=root,
                        data_root=root / "d", out_dir=root / "o")
    assert all(row["eligibility"]["status"] == "eligible" for row in payload["results"])
    return root, payload


@pytest.fixture
def copied_study(study_snapshot, tmp_path):
    source, payload = study_snapshot
    shutil.copytree(source / "d", tmp_path / "d")
    shutil.copytree(source / "o", tmp_path / "o")
    result = tmp_path / "o" / Path(payload["artifacts"]["json"]).relative_to(source / "o")
    return result, {"data_root": tmp_path / "d", "out_dir": tmp_path / "o"}


def _remove_publication(result):
    # Fixtures model pre-publication receipts; source runs are never removed.
    (result.parent / "publication.json").unlink()


def test_loader_relocates_without_rewriting_original_receipts(study_snapshot, copied_study):
    result, roots = copied_study
    original = file_sha256(study_snapshot[1]["artifacts"]["json"])
    loaded = load_study_result(result, **roots, expected_sha256=original)
    assert loaded["verification"]["status"] == "verified", loaded["verification"]
    assert loaded["verification"]["publication"] == "verified"
    assert loaded["verification"]["declared_context"] == "verified"
    assert loaded["verification"]["operations"]["provider_calls"] == 0
    assert loaded["summary"] == study_snapshot[1]["summary"]
    assert all(row["eligibility"]["status"] == "eligible" for row in loaded["results"])
    assert file_sha256(result) == original
    assert file_sha256(study_snapshot[1]["artifacts"]["json"]) == original


def test_published_report_or_external_hash_change_is_refused(copied_study):
    result, roots = copied_study
    with pytest.raises(StudyArtifactError, match="externally bound"):
        load_study_result(result, **roots, expected_sha256="0" * 64)
    payload = json.loads(result.read_text())
    payload["summary"]["coverage"]["base"]["eligible"] = 500
    result.write_text(json.dumps(payload))
    with pytest.raises(StudyArtifactError, match="report was modified"):
        load_study_result(result, **roots)


def test_legacy_summary_is_recomputed_instead_of_trusted(copied_study):
    result, roots = copied_study
    _remove_publication(result)
    payload = json.loads(result.read_text())
    payload["summary"]["coverage"]["base"]["eligible"] = 500
    result.write_text(json.dumps(payload))
    loaded = load_study_result(result, **roots)
    assert loaded["verification"]["publication"] == "legacy_missing"
    assert loaded["verification"]["status"] == "degraded"
    assert loaded["summary"]["coverage"]["base"]["eligible"] == 1


def test_worker_guard_cannot_be_promoted_by_report_or_database_success(copied_study):
    result, roots = copied_study
    payload = json.loads(result.read_text())
    cell = digest_json({"seed": 1, "arm": "base"})[:12]
    data = roots["data_root"] / Path(payload["batch"]["data_dir"]).parts[-2] / Path(payload["batch"]["data_dir"]).name
    worker = data / f"worker-{cell}.json"
    row = json.loads(worker.read_text())
    row["eligibility"] = {"status": "ineligible", "reasons": ["source_changed_during_attempt"]}
    worker.write_text(json.dumps(row))
    loaded = load_study_result(result, **roots)
    assert loaded["summary"]["coverage"]["base"]["eligible"] == 0
    assert "source_changed_during_attempt" in loaded["results"][0]["eligibility"]["reasons"]
    effect = loaded["summary"]["metrics"]["posted_index"]["cost"]["paired_effect"]
    assert effect["mean_difference"] is None and effect["n_pairs"] == 0


def test_mutated_source_excludes_only_affected_attempt(copied_study):
    result, roots = copied_study
    payload = json.loads(result.read_text())
    data = roots["data_root"] / Path(payload["batch"]["data_dir"]).parts[-2] / Path(payload["batch"]["data_dir"]).name
    locate = StudyLocation(data, result.parent, payload["batch"]["data_dir"], payload["batch"]["report_dir"])
    source = Store(str(locate.locate(payload["results"][0]["source_database"])), create=False)
    try:
        source.execute("UPDATE firms SET inventory=inventory+1")
    finally:
        source.close()
    loaded = load_study_result(result, **roots)
    assert loaded["verification"]["status"] == "degraded"
    assert loaded["summary"]["coverage"]["base"]["eligible"] == 0
    assert loaded["summary"]["coverage"]["cost"]["eligible"] == 1
    assert loaded["verification"]["operations"]["provider_calls"] is None


def test_malformed_worker_is_excluded_without_hiding_other_attempts(copied_study):
    result, roots = copied_study
    loaded = load_study_result(result, **roots)
    data = Path(loaded["verification"]["data_dir"])
    cell = digest_json({"seed": 1, "arm": "base"})[:12]
    (data / f"worker-{cell}.json").write_text('{"eligibility": 2}')
    loaded = load_study_result(result, **roots)
    assert loaded["summary"]["coverage"]["base"]["eligible"] == 0
    assert loaded["summary"]["coverage"]["cost"]["eligible"] == 1


def test_frozen_model_description_change_is_rejected(copied_study):
    result, roots = copied_study
    loaded = load_study_result(result, **roots)
    (Path(loaded["verification"]["data_dir"]) / "context/model-description.md").write_text("changed")
    with pytest.raises(StudyArtifactError, match="model description or declared input"):
        load_study_result(result, **roots)


def test_self_replay_is_not_independent_evidence(copied_study):
    result, roots = copied_study
    loaded = load_study_result(result, **roots)
    location = StudyLocation(Path(loaded["verification"]["data_dir"]), result.parent,
        loaded["batch"]["data_dir"], loaded["batch"]["report_dir"])
    row = copy.deepcopy(loaded["results"][0])
    replay_path = location.locate(row["replay_receipt"])
    replay = json.loads(replay_path.read_text())
    replay["replay_database"] = row["source_database"]
    replay["replay_database_sha256"] = row["source_database_sha256"]
    replay_path.write_text(json.dumps(replay))
    row["replay_receipt_sha256"] = file_sha256(replay_path)
    assert "replay_database_not_independent" in verify_attempt(row, expected_ticks=3, resolve_path=location.locate)


def test_unstarted_assignment_is_retained_without_claiming_complete_costs(copied_study):
    result, roots = copied_study
    _remove_publication(result)
    payload = json.loads(result.read_text())
    payload["results"].pop()
    result.write_text(json.dumps(payload))
    loaded = load_study_result(result, **roots)
    assert loaded["summary"]["coverage"]["cost"]["assigned"] == 1
    assert loaded["summary"]["coverage"]["cost"]["eligible"] == 0
    assert loaded["verification"]["operations"]["status"] == "partial"


def test_reported_cost_totals_are_independently_checked(copied_study):
    result, roots = copied_study
    _remove_publication(result)
    payload = json.loads(result.read_text())
    payload["operations"]["provider_calls"] = 500
    result.write_text(json.dumps(payload))
    loaded = load_study_result(result, **roots)
    assert loaded["verification"]["status"] == "degraded"
    assert loaded["verification"]["operations"]["provider_calls"] == 0


def test_unassigned_or_duplicate_cells_are_not_silently_counted(copied_study):
    result, roots = copied_study
    _remove_publication(result)
    payload = json.loads(result.read_text())
    payload["results"].append(copy.deepcopy(payload["results"][0]))
    result.write_text(json.dumps(payload))
    with pytest.raises(StudyArtifactError, match="duplicate or unexpected"):
        load_study_result(result, **roots)


def test_paths_are_confined_and_windows_receipts_can_be_mapped(tmp_path):
    data, report = tmp_path / "data", tmp_path / "reports"
    data.mkdir(); report.mkdir()
    location = StudyLocation(data, report, "C:/original/data/study", "C:/original/reports/study")
    assert location.locate("C:\\original\\data\\study\\cell\\source.db") == data / "cell" / "source.db"
    for unsafe in ("C:/private/credentials.json", "C:/original/data/study/../secrets.json", "relative.json"):
        with pytest.raises(StudyArtifactError):
            location.locate(unsafe)
    with pytest.raises(StudyArtifactError, match="report root"):
        load_study_result(tmp_path / "outside.json", data_root=data, out_dir=report)
