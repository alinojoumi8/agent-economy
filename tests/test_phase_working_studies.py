"""Goods and equity studies preserve partial-day evidence through transport."""
from pathlib import Path

import pytest

from research.artifacts import file_sha256
from research.study_bundle import export_study_bundle, import_study_bundle
from research.study_library import StudyLibrary
from research.study_results import load_study_result
from research.study_runner import run_study
from research.working_evidence import load_working_progress
from research.working_studies import validate_resume
from tests.test_phase_working_attempts import phase_options
from tests.test_working_attempts import _bytes


@pytest.mark.parametrize("preset", ["G2", "F2"])
def test_phase_study_preserves_all_assignments_and_portable_pending_evidence(tmp_path, preset):
    options = phase_options(tmp_path, preset=preset, seeds=(1, 2))
    roots = {key: options[key] for key in ("data_root", "out_dir")}
    paused = run_study(**options, pause_after_phase="MARKET")
    assert paused["status"] == "paused", paused
    assert [row["ticks"] for row in paused["results"]] == [0, 0, 0, 0]
    assert [row["execution_status"] for row in paused["results"]] == ["paused", "planned", "planned", "planned"]
    assert all(row["eligibility"]["status"] == "pending" for row in paused["results"])
    data, path = Path(paused["batch"]["data_dir"]), Path(paused["artifacts"]["json"])
    library = StudyLibrary(**roots, export_root=tmp_path / "exports")
    item = library.public_catalog()["items"][0]
    before = _bytes(tmp_path)
    view = library.verify(item["id"], item["result_sha256"])
    assert view["state"] == "paused" and not view["comparison_available"] and view["export_available"]
    assert view["attempts"][0]["position"] == {"completed_tick": 0, "active_tick": 1, "next_phase": "NEWSROOM"}
    assert all("position" not in row for row in view["attempts"][1:])
    assert not ({"metrics", "summary", "measurements"} & view.keys())
    assert "recorded_inputs" not in str(view) and "phase_state_sha256" not in str(view)
    validated = validate_resume(data, **options)
    assert validated["active_wall_seconds"] > 0 and _bytes(tmp_path) == before
    bundle = export_study_bundle(path, tmp_path / "paused.zip", **roots)
    second = run_study(**options, resume_batch=data, pause_after_phase="MEMORY")
    assert second["status"] == "paused"
    assert second["results"][0]["ticks"] == 0
    assert second["results"][0]["position"]["next_phase"] == "FINALIZE"
    assert second["results"][0]["active_wall_seconds"] > paused["results"][0]["active_wall_seconds"]
    saved = {p: file_sha256(p) for root in (data, Path(second["batch"]["report_dir"])) for p in root.rglob("*.json")}
    final = run_study(**options, resume_batch=data)
    assert final["status"] == "finalized"
    assert all(row["eligibility"] == {"status": "eligible", "reasons": []} for row in final["results"]), final
    assert all(file_sha256(p) == digest for p, digest in saved.items())
    loaded = load_study_result(final["artifacts"]["json"], **roots)
    assert loaded["verification"]["status"] == "verified", loaded["verification"]
    assert set(final["summary"]["metrics"]) == {"goods_price", "goods_volume", "equity_price", "equity_volume"}
    current = library.public_catalog()["items"][0]
    assert current["id"] == item["id"] and current["kind"] == "finalized"
    imported = import_study_bundle(bundle["path"], tmp_path / "copy")
    frozen = load_working_progress(imported["result_path"], data_root=tmp_path / "copy/data", out_dir=tmp_path / "copy/reports")
    assert frozen["verification"]["status"] == "verified"
    assert frozen["verification"]["eligibility"] == "pending"
    assert frozen["results"][0]["position"] == paused["results"][0]["position"]
    final_bundle = export_study_bundle(final["artifacts"]["json"], tmp_path / "final.zip", **roots)
    assert import_study_bundle(final_bundle["path"], tmp_path / "final-copy")["study_verification"]["status"] == "verified"
