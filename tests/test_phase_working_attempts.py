"""Phase recovery retains inputs, economic state and immutable study evidence."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

import pytest

from engine.store import Store
from research.artifacts import file_sha256
from research.attempts import verify_attempt
from research.price_catalog import draft_price_study
from research.studies import StudySpec, prepare_study
from research.study_runner import run_study
from research.working_attempts import execute_working_attempt
from research.working_contracts import phase_position
from tests.test_research_attempt_integrity import _config
from tests.test_working_attempts import _bytes
from world.loop import World
from world.phases import phase_names_for_semantics
from world.replay_verify import canonical_state_receipt, verify_replay


def phase_options(tmp_path, *, semantics=16, preset="G2", seeds=(1,), horizon=3):
    config = _config()
    config["engine_semantics_version"] = semantics
    config["cognition"] = {"memory_rollup_every": 1}
    config["information"] = {"daily_news_required": True}
    spec = draft_price_study(config, preset, seeds=list(seeds), horizon=horizon, intervention_tick=2)
    raw = spec.model_dump(mode="json")
    raw["operations"].update(pause_policy="preserve_and_resume_phases", max_wall_seconds=180)
    return dict(spec=StudySpec.model_validate(raw), config=config, input_root=tmp_path,
                data_root=tmp_path / "data", out_dir=tmp_path / "out")


def attempt_options(tmp_path, **kwargs):
    options = phase_options(tmp_path, **kwargs)
    batch = prepare_study(**options)
    return dict(batch=batch, spec=options["spec"], config=options["config"],
                input_root=tmp_path, seed=1, arm="control")


@pytest.mark.parametrize("semantics", [7, 16])
def test_every_phase_can_pause_in_one_day_and_replay_like_uninterrupted(tmp_path, monkeypatch, semantics):
    class FixedGatewayClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 7, tzinfo=timezone.utc).astimezone(tz)

    monkeypatch.setattr("llm.gateway.datetime", FixedGatewayClock)
    options = attempt_options(tmp_path, semantics=semantics)
    phases, immutable, first = phase_names_for_semantics(semantics), {}, None
    for index, phase in enumerate(phases):
        row = execute_working_attempt(**options, pause_after_phase=phase, resume=index > 0)
        assert row["execution_status"] == "paused", row
        assert row["eligibility"]["status"] == "pending"
        position = row["position"]
        assert position["completed_tick"] == row["ticks"] == (1 if phase == "FINALIZE" else 0)
        assert position["active_tick"] == (None if phase == "FINALIZE" else 1)
        assert position["next_phase"] == phases[(index + 1) % len(phases)]
        if phase != "FINALIZE":
            assert set(row["metrics"].values()) == {None} and row["series"] == {}
            assert all(value["status"] == "partial_phase" for value in row["outcome_observations"].values())
        assert row["reconciled"] and row["database_integrity"]
        assert not (Path(row["attempt_claim"]).parent / "source-receipt.json").exists()
        assert all(file_sha256(path) == digest for path, digest in immutable.items())
        immutable.update({p: file_sha256(p) for p in Path(row["attempt_claim"]).parent.glob("*.json")})
        first = first or row
    completed = execute_working_attempt(**options, resume=True)
    assert completed["eligibility"] == {"status": "eligible", "reasons": []}, completed
    assert verify_attempt(completed, expected_ticks=3) == []
    assert completed["genesis_hash"] == first["genesis_hash"]
    assert completed["active_wall_seconds"] > row["active_wall_seconds"] > first["active_wall_seconds"]
    assert all(file_sha256(path) == digest for path, digest in immutable.items())
    baseline = execute_working_attempt(**attempt_options(tmp_path, semantics=semantics))
    assert baseline["eligibility"]["status"] == "eligible", baseline
    proof = verify_replay(Path(completed["source_database"]), Path(baseline["source_database"]))
    assert proof["exact"], proof
    assert completed["position"]["prng_sha256"] == baseline["position"]["prng_sha256"]
    assert completed["metrics"] == baseline["metrics"]


@pytest.mark.parametrize("phase", ["MORNING", "NEWSROOM", "EVENING", "MEMORY"])
@pytest.mark.parametrize("semantics", [7, 16])
def test_recorded_partial_provider_phase_resumes_without_duplicate_admission(tmp_path, monkeypatch, phase, semantics):
    options = attempt_options(tmp_path, semantics=semantics)
    original, failed, blocked, phase_calls = World.__init__, False, True, 0

    def initialize(self, *args, **kwargs):
        nonlocal failed, phase_calls
        original(self, *args, **kwargs)
        if self.gateway.replay:
            return
        delegate = self.gateway.adapters["scripted"]

        class PartialOutage:
            async def complete(_self, *a, **k):
                nonlocal failed, phase_calls
                if self.store.next_phase == phase and blocked:
                    phase_calls += 1
                    if phase_calls >= 2:
                        failed = True
                        raise RuntimeError("synthetic partial phase outage")
                return await delegate.complete(*a, **k)

        self.gateway.adapters["scripted"] = PartialOutage()

    monkeypatch.setattr(World, "__init__", initialize)
    paused = execute_working_attempt(**options)
    assert failed and paused["execution_status"] == "paused", paused
    assert paused["position"]["active_tick"] == paused["ticks"] + 1 and paused["position"]["next_phase"] == phase
    assert paused["position"]["recorded_inputs"]["count"] > 0
    assert paused["eligibility"]["status"] == "pending"
    repeated = execute_working_attempt(**options, resume=True)
    assert repeated["execution_status"] == "paused" and repeated["eligibility"]["status"] == "pending", repeated
    assert repeated["position"] == paused["position"]
    assert repeated["active_wall_seconds"] > paused["active_wall_seconds"]
    blocked = False
    before = {p: file_sha256(p) for p in Path(paused["attempt_claim"]).parent.glob("*.json")}
    final = execute_working_attempt(**options, resume=True)
    assert final["eligibility"] == {"status": "eligible", "reasons": []}, final
    assert verify_attempt(final, expected_ticks=3) == []
    assert all(file_sha256(path) == digest for path, digest in before.items())
    connection = sqlite3.connect(final["source_database"])
    try:
        assert connection.execute("SELECT COUNT(*)=COUNT(DISTINCT cache_key) FROM llm_calls").fetchone()[0]
        assert connection.execute("SELECT COUNT(*) FROM metrics WHERE tick=1 AND name='cpi'").fetchone()[0] == 1
    finally:
        connection.close()
    assert final["provider_calls"] == final["spend_usd"] == 0


@pytest.mark.parametrize("change", ["active_day", "phase", "decisions", "engine_rng", "lifecycle_rng", "inputs", "history_skip", "receipt_phase"])
def test_resealed_phase_database_refuses_changed_frontier_before_writable_open(tmp_path, monkeypatch, change):
    options = attempt_options(tmp_path)
    paused = execute_working_attempt(**options, pause_after_phase="MORNING")
    assert paused["execution_status"] == "paused", paused
    connection = sqlite3.connect(paused["source_database"])
    try:
        statements = {
            "active_day": "UPDATE run_meta SET active_tick=3",
            "phase": "UPDATE run_meta SET next_phase='UNKNOWN'",
            "decisions": "UPDATE run_meta SET phase_state_json='{}'",
            "engine_rng": "UPDATE run_meta SET prng_state='{}'",
            "lifecycle_rng": "UPDATE run_meta SET lifecycle_prng_state='[3,[],null]'",
            "inputs": "DELETE FROM llm_calls WHERE id=(SELECT MAX(id) FROM llm_calls)",
        }
        if change in statements:
            connection.execute(statements[change])
        connection.commit()
    finally:
        connection.close()
    pause_path = Path(paused["attempt_claim"]).parent / "segment-000001-pause.json"
    pause = json.loads(pause_path.read_text())
    pause["row"]["source_database_sha256"] = file_sha256(paused["source_database"])
    if change == "history_skip":
        pause["row"]["working_history"] = []
    elif change == "receipt_phase":
        pause["row"]["position"]["next_phase"] = "MARKET"
    pause_path.write_text(json.dumps(pause))
    before = _bytes(tmp_path)

    def forbidden_open(*args, **kwargs):
        pytest.fail("incompatible phase reached writable reopen")

    monkeypatch.setattr("run.open_run", forbidden_open)
    with pytest.raises(ValueError):
        execute_working_attempt(**options, resume=True)
    assert _bytes(tmp_path) == before


@pytest.mark.parametrize("controls", [{"pause_after_phase": "UNKNOWN"},
                                    {"pause_after_phase": "MORNING", "pause_after_ticks": 1}])
def test_invalid_phase_controls_create_no_study_artifacts(tmp_path, controls):
    options = phase_options(tmp_path)
    before = _bytes(tmp_path)
    with pytest.raises(ValueError):
        run_study(**options, **controls)
    assert _bytes(tmp_path) == before


def test_old_pause_policy_is_not_silently_promoted_to_phase_recovery(tmp_path):
    options = phase_options(tmp_path)
    raw = options["spec"].model_dump(mode="json")
    raw["operations"]["pause_policy"] = "preserve_and_resume"
    options["spec"] = StudySpec.model_validate(raw)
    before = _bytes(tmp_path)
    with pytest.raises(ValueError, match="preserve_and_resume_phases"):
        run_study(**options, pause_after_phase="MORNING")
    assert _bytes(tmp_path) == before


def test_later_resealed_frontier_cannot_rewrite_earlier_accepted_responses(tmp_path, monkeypatch):
    options = attempt_options(tmp_path)
    first = execute_working_attempt(**options, pause_after_phase="MORNING")
    second = execute_working_attempt(**options, resume=True, pause_after_phase="NEWSROOM")
    assert first["execution_status"] == second["execution_status"] == "paused"
    source = Path(second["source_database"])
    with sqlite3.connect(source) as connection:
        connection.execute("UPDATE llm_calls SET latency_ms=latency_ms+1 WHERE id=1")
    connection.close()
    connection = sqlite3.connect(f"{source.as_uri()}?mode=ro&immutable=1", uri=True)
    connection.execute("PRAGMA query_only=ON")
    store = Store.from_read_only_connection(source, connection)
    try:
        second["position"] = phase_position(store, 16, 3)
        second["source_state_hash"] = canonical_state_receipt(connection)["sha256"]
    finally:
        store.close()
    second["source_database_sha256"] = file_sha256(source)
    path = Path(second["attempt_claim"]).parent / "segment-000002-pause.json"
    receipt = json.loads(path.read_text())
    receipt["row"] = second
    path.write_text(json.dumps(receipt))
    before = _bytes(tmp_path)

    def forbidden_open(*args, **kwargs):
        pytest.fail("changed recorded inputs reached writable reopen")

    monkeypatch.setattr("run.open_run", forbidden_open)
    with pytest.raises(ValueError, match="recorded input history changed"):
        execute_working_attempt(**options, resume=True)
    assert _bytes(tmp_path) == before
