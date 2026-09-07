"""Working research state can advance; finalized evidence cannot be rewritten."""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3

import pytest

from research.artifacts import digest_json, file_sha256
from research.attempts import execute_attempt, verify_attempt
from research.process_lock import ProcessLockBusy, process_lock
from research.studies import StudySpec, prepare_study
from research.study_runner import run_study
from research.working_attempts import execute_working_attempt
from tests.test_research_attempt_integrity import _config
from tests.test_study_protocol import protocol
from world.replay_verify import verify_replay
from world.loop import World


def _prepare(protocol, tmp_path, *, horizon=3):
    config = _config()
    raw = copy.deepcopy(protocol)
    raw["operations"]["pause_policy"] = "preserve_and_resume"
    raw["operations"]["max_wall_seconds"] = 120
    raw["model"]["resolved_config_sha256"] = digest_json(config)
    raw["time"].update(horizon=horizon, measurement_end=horizon)
    spec = StudySpec.model_validate(raw)
    batch = prepare_study(spec, config, input_root=tmp_path,
                          data_root=tmp_path / "data", out_dir=tmp_path / "out")
    return {"spec": spec, "config": config, "batch": batch,
            "input_root": tmp_path, "seed": 1, "arm": "base"}


def _bytes(root):
    return {str(path.relative_to(root)): file_sha256(path)
            for path in root.rglob("*") if path.is_file()}


def test_pause_at_three_resume_to_thirty_matches_uninterrupted_world(protocol, tmp_path, monkeypatch):
    class FixedGatewayClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 6, tzinfo=timezone.utc).astimezone(tz)

    # Separate fresh executions naturally have different recorded latency_ms.
    # Hold only the gateway's observational clock fixed for this comparison;
    # retain the production replay contract, all decisions and budget clocks.
    monkeypatch.setattr("llm.gateway.datetime", FixedGatewayClock)
    options = _prepare(protocol, tmp_path, horizon=30)
    first = execute_working_attempt(**options, max_ticks=3)
    attempt = Path(first["attempt_claim"]).parent
    assert first["ticks"] == 3 and first["execution_status"] == "paused"
    assert first["eligibility"]["status"] == "pending"
    assert "incomplete_horizon" in verify_attempt(first, expected_ticks=30)
    assert not (attempt / "source-receipt.json").exists()
    assert not (attempt / "result.json").exists()
    immutable = {p: file_sha256(p) for p in attempt.glob("*.json")}
    completed = execute_working_attempt(**options, resume=True)
    assert completed["ticks"] == 30
    assert completed["eligibility"] == {"status": "eligible", "reasons": []}, completed
    assert verify_attempt(completed, expected_ticks=30) == []
    assert completed["genesis_hash"] == first["genesis_hash"]
    assert completed["active_wall_seconds"] > first["active_wall_seconds"]
    assert all(file_sha256(p) == digest for p, digest in immutable.items())
    baseline = execute_working_attempt(**_prepare(protocol, tmp_path, horizon=30))
    assert baseline["eligibility"]["status"] == "eligible", baseline
    proof = verify_replay(Path(completed["source_database"]), Path(baseline["source_database"]))
    assert proof["exact"], proof
    assert completed["prng_state_sha256"] == baseline["prng_state_sha256"]
    assert completed["metrics"] == baseline["metrics"]
    assert completed["provider_calls"] == baseline["provider_calls"] == 0
    assert completed["spend_usd"] == baseline["spend_usd"] == 0
    before = _bytes(tmp_path)
    with pytest.raises(ValueError, match="finalized"):
        execute_working_attempt(**options, resume=True)
    assert _bytes(tmp_path) == before


@pytest.mark.parametrize("change", ["config", "code", "manifest", "context", "source", "genesis", "phase", "prng", "schema", "claim", "segment"])
def test_incompatible_resume_preserves_every_artifact(protocol, tmp_path, change, monkeypatch):
    options = _prepare(protocol, tmp_path)
    paused = execute_working_attempt(**options, max_ticks=1)
    directory = Path(paused["attempt_claim"]).parent
    if change == "config":
        options["config"]["population"]["size"] += 1
    elif change == "code":
        monkeypatch.setattr("research.working_attempts.code_identity", lambda: {"git_commit": "changed"})
    elif change == "manifest":
        options["batch"]["manifest"]["study"]["title"] = "changed"
    elif change == "context":
        Path(options["batch"]["data_dir"], "context", "model-description.md").write_text("changed")
    elif change in {"source", "phase", "prng", "schema"}:
        with sqlite3.connect(paused["source_database"]) as conn:
            statements = {"source": "UPDATE accounts SET balance_cents=balance_cents+1 WHERE id=1",
                          "phase": "UPDATE run_meta SET active_tick=2,next_phase='MORNING' WHERE id=1",
                          "prng": "UPDATE run_meta SET prng_state='changed' WHERE id=1",
                          "schema": "UPDATE run_meta SET schema_version=schema_version-1 WHERE id=1"}
            conn.execute(statements[change])
        conn.close()
        if change != "source":
            # Bind the edited DB as if it were a newly captured pause, forcing
            # the read-only phase/PRNG/schema checks beyond the byte hash gate.
            pause_path = directory / "segment-000001-pause.json"
            record = json.loads(pause_path.read_text())
            record["row"]["source_database_sha256"] = file_sha256(paused["source_database"])
            pause_path.write_text(json.dumps(record))
    elif change == "genesis":
        Path(paused["genesis_receipt"]).write_text("{}")
    elif change == "claim":
        Path(paused["attempt_claim"]).write_text("{}")
    else:
        (directory / "segment-000001-start.json").write_text("{}")
    before = _bytes(tmp_path)
    with pytest.raises((ValueError, KeyError)):
        execute_working_attempt(**options, resume=True)
    assert _bytes(tmp_path) == before


def test_one_writer_and_crash_markers_prevent_duplicate_work(protocol, tmp_path):
    options = _prepare(protocol, tmp_path)
    paused = execute_working_attempt(**options, max_ticks=1)
    data = Path(options["batch"]["data_dir"])
    before = _bytes(tmp_path)
    with process_lock(data / "working.lock"):
        with pytest.raises(ProcessLockBusy):
            execute_working_attempt(**options, resume=True)
    assert _bytes(tmp_path) == before
    directory = Path(paused["attempt_claim"]).parent
    (directory / "segment-000002-start.json").write_text("{}")
    before = _bytes(tmp_path)
    with pytest.raises(ValueError, match="unfinished segment"):
        execute_working_attempt(**options, resume=True)
    assert _bytes(tmp_path) == before


def test_resuming_cannot_reset_consumed_active_time(protocol, tmp_path, monkeypatch):
    options = _prepare(protocol, tmp_path)
    paused = execute_working_attempt(**options, max_ticks=1)
    # Advance the clock only by the *remaining* budget. A fresh per-invocation
    # limit would incorrectly admit this segment; cumulative accounting refuses.
    remaining = options["spec"].operations.max_wall_seconds - paused["active_wall_seconds"]
    clock = iter([1000.0, 1000.0 + remaining + .01])
    monkeypatch.setattr("research.working_attempts.time.monotonic", lambda: next(clock, 1000.0 + remaining + .01))
    before = _bytes(tmp_path)
    with pytest.raises(ValueError, match="cumulative budget"):
        execute_working_attempt(**options, resume=True)
    assert _bytes(tmp_path) == before


def test_final_receipt_detects_altered_pause_lineage(protocol, tmp_path):
    options = _prepare(protocol, tmp_path)
    paused = execute_working_attempt(**options, max_ticks=1)
    complete = execute_working_attempt(**options, resume=True)
    assert verify_attempt(complete, expected_ticks=3) == []
    pause = Path(paused["attempt_claim"]).parent / "segment-000001-pause.json"
    changed = json.loads(pause.read_text())
    changed["row"]["ticks"] = 2
    pause.write_text(json.dumps(changed))
    assert "working_history_invalid" in verify_attempt(complete, expected_ticks=3)


def test_legacy_runner_refuses_working_policy_before_creating_artifacts(protocol, tmp_path):
    options = _prepare(protocol, tmp_path)
    before = _bytes(tmp_path)
    with pytest.raises(ValueError, match="resumable attempt executor"):
        run_study(options["spec"], options["config"], input_root=tmp_path,
                  data_root=tmp_path / "other-data", out_dir=tmp_path / "other-out")
    assert _bytes(tmp_path) == before


def test_hard_linked_source_cannot_become_a_working_database(protocol, tmp_path):
    options = _prepare(protocol, tmp_path)
    paused = execute_working_attempt(**options, max_ticks=1)
    os.link(paused["source_database"], tmp_path / "outside.db")
    before = _bytes(tmp_path)
    with pytest.raises(ValueError, match="hard links"):
        execute_working_attempt(**options, resume=True)
    assert _bytes(tmp_path) == before


def test_finalized_legacy_pause_is_never_reopened(protocol, tmp_path, monkeypatch):
    options = _prepare(protocol, tmp_path)
    original = World.run

    async def one_day(self, max_ticks=None):
        await original(self, max_ticks=1)

    monkeypatch.setattr(World, "run", one_day)
    paused = execute_attempt(run_id="legacy", seed=1, arm="base", config=options["config"],
                             ticks=3, data_dir=Path(options["batch"]["data_dir"]), collect=lambda _: {})
    assert paused["execution_status"] == "paused"
    before = _bytes(tmp_path)
    with pytest.raises(ValueError, match="finalized"):
        execute_working_attempt(**options, resume=True)
    assert _bytes(tmp_path) == before


def test_multiple_pauses_keep_contiguous_provenance_and_exact_replay(protocol, tmp_path):
    options = _prepare(protocol, tmp_path)
    first = execute_working_attempt(**options, max_ticks=1)
    second = execute_working_attempt(**options, max_ticks=1, resume=True)
    final = execute_working_attempt(**options, max_ticks=1, resume=True)
    assert [row["ticks"] for row in (first, second, final)] == [1, 2, 3]
    assert first["active_wall_seconds"] < second["active_wall_seconds"] < final["active_wall_seconds"]
    assert len(final["working_history"]) == 5
    assert verify_attempt(final, expected_ticks=3) == []


def test_failed_segment_retains_completed_day_and_cannot_resume(protocol, tmp_path, monkeypatch):
    options = _prepare(protocol, tmp_path)
    original = World.run

    async def fail_after_day(self, max_ticks=None):
        await original(self, max_ticks=1)
        raise RuntimeError("private execution detail")

    monkeypatch.setattr(World, "run", fail_after_day)
    row = execute_working_attempt(**options)
    assert row["ticks"] == 1 and row["execution_status"] == "failed"
    assert row["eligibility"]["status"] == "ineligible"
    assert "private execution detail" not in json.dumps(row)
    before = _bytes(tmp_path)
    with pytest.raises(ValueError, match="finalized"):
        execute_working_attempt(**options, resume=True)
    assert _bytes(tmp_path) == before


def test_other_cells_use_sealed_budget_records(protocol, tmp_path):
    options = _prepare(protocol, tmp_path)
    complete = execute_working_attempt(**options)
    assert complete["eligibility"]["status"] == "eligible"
    treatment = execute_working_attempt(**{**options, "arm": "cost"}, max_ticks=1)
    assert treatment["execution_status"] == "paused"
    path = Path(complete["attempt_claim"]).parent / "result.json"
    changed = json.loads(path.read_text())
    changed["finalization_wall_seconds"] = 0
    path.write_text(json.dumps(changed))
    before = _bytes(tmp_path)
    with pytest.raises(ValueError, match="finalized working result changed"):
        execute_working_attempt(**{**options, "arm": "cost"}, resume=True)
    assert _bytes(tmp_path) == before
