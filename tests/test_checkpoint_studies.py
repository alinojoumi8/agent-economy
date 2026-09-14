"""Saved-state studies measure, recover and transport actual continuations."""
import copy
import json
from pathlib import Path
import sqlite3

import pytest

from research.artifacts import file_sha256
from research.attempts import verify_attempt
from research.checkpoint_origins import closed_checkpoint
from research.study_bundle import export_study_bundle, import_study_bundle
from research.study_results import load_study_result
from research.price_catalog import draft_checkpoint_price_study
from research.study_runner import run_study
from research.working_evidence import load_working_progress
from research.working_studies import validate_resume
from tests.test_checkpoint_origins import checkpoint_spec, source_world
from world.loop import World


@pytest.mark.parametrize("preset", ["G2", "F2"])
@pytest.mark.parametrize("policy", ["preserve_and_stop", "preserve_and_resume", "preserve_and_resume_phases"])
def test_saved_world_studies_execute_replay_recover_and_export(tmp_path, preset, policy):
    spec, config = checkpoint_spec(tmp_path, preset=preset, pause_policy=policy, inherited_cost=True)
    originals = {tmp_path / item.path: file_sha256(tmp_path / item.path) for item in spec.inputs}
    options = dict(spec=spec, config=config, input_root=tmp_path,
                   data_root=tmp_path / "data", out_dir=tmp_path / "out")
    roots = {key: options[key] for key in ("data_root", "out_dir")}
    if policy == "preserve_and_stop":
        result = run_study(**options)
    else:
        pause = {"pause_after_ticks": 1} if policy == "preserve_and_resume" else {"pause_after_phase": "MORNING"}
        paused = run_study(**options, **pause)
        assert paused["status"] == "paused", paused["results"]
        row = paused["results"][0]
        assert row["ticks"] == (3 if policy == "preserve_and_resume" else 2)
        assert row["origin_tick"] == 2 and row["origin_state_hash"]
        assert row["provider_calls"] == row["spend_usd"] == 0
        assert row["inherited_provider_calls"] == 1 and row["inherited_spend_usd"] == 7.5
        checked = load_working_progress(paused["artifacts"]["json"], **roots)
        assert checked["verification"]["status"] == "verified"
        archive = export_study_bundle(paused["artifacts"]["json"], tmp_path / "paused.zip", **roots)
        transported = import_study_bundle(archive["path"], tmp_path / "paused-copy")
        assert transported["study_verification"]["eligibility"] == "pending"
        result = run_study(**options, resume_batch=paused["batch"]["data_dir"])
    assert result["operations"]["stop_reason"] is None, result["results"]
    assert len(result["results"]) == 4
    assert result["summary"]["initial_state_key"] == "origin_state_hash"
    assert all(coverage["eligible"] == 2 for coverage in result["summary"]["coverage"].values()), result["results"]
    for row in result["results"]:
        assert row["ticks"] == row["expected_ticks"] == 5 and row["origin_tick"] == 2
        assert row["genesis_hash"] is None and "genesis_receipt" not in row
        assert len(row["outcome_observations"]) == 4
        assert all(point["tick"] >= 4 for outcome in row["outcome_observations"].values() for point in outcome["points"])
        assert row["provider_calls"] == row["spend_usd"] == 0
        assert row["inherited_provider_calls"] == 1 and row["inherited_spend_usd"] == 7.5
        assert verify_attempt(row, expected_ticks=5) == []
        replay = json.loads(Path(row["replay_receipt"]).read_text(encoding="utf-8"))
        assert replay["execution"] == "recorded_checkpoint_replay"
        assert replay["continuation_window"] == [3, 5] and replay["comparison"]["exact"]
        # Automatic replay pauses must never replace the source's recovery files.
        checkpoints = list((Path(row["attempt_claim"]).parent / "checkpoints").glob("*.db"))
        assert checkpoints
        for checkpoint in checkpoints:
            with closed_checkpoint(checkpoint, max_bytes=spec.operations.max_disk_bytes) as saved:
                assert "replay_source_path" not in json.loads(saved.get_meta()["config_json"])
        altered = copy.deepcopy(row)
        altered["origin_state_hash"] = "0" * 64
        assert verify_attempt(altered, expected_ticks=5)
    for seed in (1, 2):
        assert len({row["origin_state_hash"] for row in result["results"] if row["seed"] == seed}) == 1
    assert len({row["origin_state_hash"] for row in result["results"]}) == 2
    verified = load_study_result(result["artifacts"]["json"], **roots)
    assert verified["verification"]["status"] == "verified", verified["verification"]
    archive = export_study_bundle(result["artifacts"]["json"], tmp_path / "final.zip", **roots)
    transported = import_study_bundle(archive["path"], tmp_path / "final-copy")
    assert transported["study_verification"]["status"] == "verified"
    assert all(file_sha256(path) == digest for path, digest in originals.items())
    assert all(not Path(str(path) + suffix).exists() for path in originals for suffix in ("-wal", "-shm", "-journal"))
    assert not [path for path in Path(result["batch"]["data_dir"]).rglob("*")
                if path.name.endswith(("-wal", "-shm", "-journal"))]


def test_changed_owned_checkpoint_refuses_resume_before_any_writable_world(tmp_path, monkeypatch):
    spec, config = checkpoint_spec(tmp_path, pause_policy="preserve_and_resume")
    options = dict(spec=spec, config=config, input_root=tmp_path,
                   data_root=tmp_path / "data", out_dir=tmp_path / "out")
    paused = run_study(**options, pause_after_ticks=1)
    assert paused["status"] == "paused", paused["results"]
    claim = json.loads(Path(paused["results"][0]["attempt_claim"]).read_text(encoding="utf-8"))
    origin = Path(claim["checkpoint_origin"]["database"])
    with sqlite3.connect(origin) as connection:
        connection.execute("UPDATE llm_calls SET latency_ms=latency_ms+1 WHERE id=1")
    connection.close()
    before = {path: file_sha256(path) for path in Path(paused["batch"]["data_dir"]).rglob("*") if path.is_file()}

    def forbidden(*args, **kwargs):
        pytest.fail("changed origin must refuse before a writable World is constructed")

    monkeypatch.setattr(World, "__init__", forbidden)
    with pytest.raises(ValueError, match="saved study input changed"):
        validate_resume(paused["batch"]["data_dir"], **options)
    assert all(file_sha256(path) == digest for path, digest in before.items())


def test_checkpoint_price_draft_retains_sources_and_cannot_replace_their_seeds(tmp_path):
    spec, config = checkpoint_spec(tmp_path)
    paths = [tmp_path / item.path for item in spec.inputs]
    before = {path: file_sha256(path) for path in paths}
    for preset in ("G2", "F2"):
        draft = draft_checkpoint_price_study(config, preset, checkpoints=paths,
            input_root=tmp_path, horizon=5, intervention_tick=4, warmup_ticks=1)
        assert draft.origin.tick == 2 and draft.randomness.seeds == [1, 2]
        assert draft.model.resolved_config_sha256 == spec.model.resolved_config_sha256
        assert {item.receipt_sha256 for item in draft.origin.sources} == {item.receipt_sha256 for item in spec.origin.sources}
        assert len(draft.analysis.outcomes) == 4
        assert not (tmp_path / "data").exists()
    assert all(file_sha256(path) == digest for path, digest in before.items())
    with pytest.raises(ValueError):
        draft_checkpoint_price_study(config, "G2", checkpoints=[paths[0], paths[0]],
                                     input_root=tmp_path, horizon=5, intervention_tick=4)


def test_closed_source_reader_refuses_pending_wal_without_changing_it(tmp_path):
    from engine.store import open_read_only_connection, ReadOnlyReplaySnapshot

    path, _ = source_world(tmp_path)
    before = file_sha256(path)
    connection = open_read_only_connection(str(path), require_closed=True)
    connection.close()
    assert file_sha256(path) == before
    sidecar = Path(str(path) + "-wal")
    sidecar.write_bytes(b"uncommitted synthetic fixture")
    for reader in (open_read_only_connection, ReadOnlyReplaySnapshot):
        with pytest.raises(ValueError, match="without SQLite sidecars"):
            reader(str(path), require_closed=True)
    assert sidecar.read_bytes() == b"uncommitted synthetic fixture"
    assert file_sha256(path) == before
