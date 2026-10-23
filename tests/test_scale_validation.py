from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

from run_config import load_config
from scripts.run_scale_validation import (
    ReceiptSafetyError,
    ValidationInputError,
    main,
    prepare_validation_config,
    run_validation,
    validate_receipt_safety,
    verification_error_receipt,
)
from world.replay_storage import ReplayResourceLimitError


ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"
REHEARSAL = RUNS / "scale-270-rehearsal.yaml"
MINIMAX = RUNS / "scale-270-minimax-live.yaml"
BUFFER_FORMAL = RUNS / "acceptance/scale-270-recovery-buffer-1000.yaml"
LIFECYCLE_FORMAL = RUNS / "acceptance/scale-270-recovery-buffer-lifecycle-1000.yaml"


@pytest.mark.parametrize("ticks", (0, -1, True))
def test_prepare_validation_rejects_non_positive_ticks(tmp_path, ticks):
    with pytest.raises(ValidationInputError, match="ticks must be a positive integer"):
        prepare_validation_config(
            REHEARSAL,
            ticks=ticks,
            output_dir=tmp_path / "output",
            data_dir=tmp_path / "runs",
            approve_live=False,
        )


def test_prepare_validation_rejects_profile_outside_runs(tmp_path):
    outside = tmp_path / "copied-profile.yaml"
    outside.write_text(REHEARSAL.read_text(encoding="utf-8"), encoding="utf-8")

    with pytest.raises(ValidationInputError, match="maintained profile beneath runs"):
        prepare_validation_config(
            outside,
            ticks=1,
            output_dir=tmp_path / "output",
            data_dir=tmp_path / "runs",
            approve_live=False,
        )


def test_prepare_validation_enforces_live_approval_matrix(tmp_path):
    with pytest.raises(ValidationInputError, match="requires --approve-live-inference"):
        prepare_validation_config(
            MINIMAX,
            ticks=2,
            output_dir=tmp_path / "output",
            data_dir=tmp_path / "runs",
            approve_live=False,
        )

    with pytest.raises(ValidationInputError, match="invalid for a provider-free profile"):
        prepare_validation_config(
            REHEARSAL,
            ticks=1,
            output_dir=tmp_path / "output",
            data_dir=tmp_path / "runs",
            approve_live=True,
        )


@pytest.mark.parametrize("profile_path,ticks,checkpoint_every,keep_last", [
    (REHEARSAL, 1, 7, 4),
    (BUFFER_FORMAL, 1000, 100, 2),
    (LIFECYCLE_FORMAL, 1000, 100, 2),
])
def test_prepare_validation_preserves_profile_contract_and_rehomes_only_paths(
    tmp_path, profile_path, ticks, checkpoint_every, keep_last,
):
    source_root = tmp_path / "runs" / "source"
    prepared = prepare_validation_config(
        profile_path,
        ticks=ticks,
        output_dir=tmp_path / "output",
        data_dir=tmp_path / "runs",
        approve_live=False,
    )
    profile = load_config(profile_path)

    assert prepared["population"] == profile["population"]
    assert prepared["living_world"] == profile["living_world"]
    assert prepared["budget"] == profile["budget"]
    assert prepared["conversations"] == profile["conversations"]
    assert prepared["llm"] == profile["llm"]
    assert prepared["llm"]["default_route"] == {"provider": "scripted", "model": "scripted"}
    assert prepared["checkpoint_every"] == profile["checkpoint_every"] == checkpoint_every
    assert prepared["checkpoint_keep_last"] == profile["checkpoint_keep_last"] == keep_last
    assert prepared["checkpoint_dir"] == str(source_root / "checkpoints")
    assert prepared["report_dir"] == str(tmp_path / "output" / "reports")


@pytest.mark.parametrize("ticks", [120, 999, 1001])
def test_formal_buffer_profile_rejects_any_other_horizon(tmp_path, ticks):
    with pytest.raises(ValidationInputError, match="profile requires exactly 1000 ticks"):
        prepare_validation_config(
            BUFFER_FORMAL,
            ticks=ticks,
            output_dir=tmp_path / "output",
            data_dir=tmp_path / "runs",
            approve_live=False,
        )


@pytest.mark.parametrize(
    "payload",
    (
        {"api_key": "credential-canary"},
        {"headers": {"Authorization": "Bearer credential-canary"}},
        {"cookies": {"session": "credential-canary"}},
        {"reasoning_content": "private chain"},
        {"raw": {"provider_body": "private response"}},
        {"environment": {"PATH": "/private/bin"}},
        {"payload": "SQLite format 3\x00database-body"},
        {"payload": "U1FMaXRlIGZvcm1hdCAzAGRhdGFiYXNlLWJvZHk="},
        {"innocent_name": "credential-canary"},
    ),
)
def test_receipt_safety_rejects_secrets_private_bodies_and_databases(payload):
    with pytest.raises(ReceiptSafetyError):
        validate_receipt_safety(
            payload, secret_values=("credential-canary",))


@pytest.mark.parametrize(
    "payload",
    (
        {
            "schema": "agent-economy-scale-validation-v1",
            "profile_path": "runs/scale-270-rehearsal.yaml",
            "providers": {"pairs": [{"provider": "scripted", "model": "scripted"}]},
        },
        {
            "schema": "agent-economy-scale-economic-health-v1",
            "checks": {"ledger_reconciles": True},
        },
        {
            "schema": "agent-economy-scale-ab-v1",
            "arms": {"baseline": "receipt-a.json", "recovery": "receipt-b.json"},
        },
        {
            "schema": "agent-economy-scale-browser-v1",
            "browser": {"name": "Google Chrome", "console_errors": []},
        },
    ),
)
def test_receipt_safety_accepts_sanitized_receipt_shapes(payload):
    validate_receipt_safety(payload, secret_values=("credential-canary",))


@pytest.mark.parametrize("profile", [REHEARSAL, LIFECYCLE_FORMAL])
def test_one_tick_provider_free_validation_is_isolated_and_exact(tmp_path, profile, monkeypatch):
    if profile == LIFECYCLE_FORMAL:
        # Exercise v3 receipt wiring with a bounded fixture, not a formal run.
        fixture_config = load_config(profile)
        fixture_config["acceptance"]["min_ticks"] = 1
        fixture_config["acceptance"]["scale_economic_health"]["required_ticks"] = 1
        monkeypatch.setattr("scripts.run_scale_validation.load_config", lambda path: fixture_config)
    output_dir = tmp_path / "output"
    data_dir = tmp_path / "runs"

    receipt = run_validation(
        profile,
        ticks=1,
        label="one-tick-rehearsal",
        output_dir=output_dir,
        data_dir=data_dir,
        approve_live=False,
    )

    receipt_path = tmp_path / receipt["artifacts"]["runtime_receipt"]
    serialized = receipt_path.read_text(encoding="utf-8")
    persisted = json.loads(serialized)
    assert persisted == receipt
    assert receipt["schema"] == "agent-economy-scale-validation-v1"
    assert receipt["passed"] is True
    assert receipt["source"]["tick"] == 1
    assert receipt["source"]["status"] == "finished"
    assert receipt["population"] == {
        "agents": 308,
        "alive": 308,
        "citizen_kind": 272,
        "staff_kind": 36,
        "core": 100,
        "periphery": 208,
        "regions": {"ironvale": 69, "northstar": 184, "suncoast": 55},
    }
    assert receipt["communications"]["conversations"] == 25
    assert receipt["communications"]["messages"] == 75
    assert receipt["communications"]["empty_messages"] == 0
    assert receipt["providers"]["cost_usd"] == 0.0
    assert {
        (row["provider"], row["model"])
        for row in receipt["providers"]["pairs"]
    } == {("scripted", "scripted")}
    assert receipt["runtime"]["checkpoints"]
    for checkpoint in receipt["runtime"]["checkpoints"]:
        phases = checkpoint["phases_s"]
        assert {"prepare", "write", "record", "retention"} <= phases.keys()
        assert all(value >= 0 for value in phases.values())
        # Retention is nested within catalog recording; do not sum both.
        assert phases["retention"] <= phases["record"]
        writer_phases = ("write_backup", "write_finalize", "write_manifest")
        assert set(writer_phases) <= phases.keys()
        assert sum(phases[key] for key in writer_phases) <= phases["write"] + 0.000003
        measured = sum(phases[key] for key in ("prepare", "write", "record"))
        assert measured <= checkpoint["duration_s"] + 0.000003
    assert receipt["replay"]["proof"]["exact"] is True
    assert receipt["replay"]["proof"]["differences"] == []
    if profile == LIFECYCLE_FORMAL:
        assert receipt["population_evidence"]["contract"] == "stable-lifecycle-v1"
        assert receipt["population_evidence"]["initial"] == receipt["population"]
    assert next(
        row for row in receipt["replay"]["artifact_manifest"]
        if row["artifact"] == receipt["replay"]["database"]
    )["kind"] == "replay_database"
    assert receipt["source"]["artifact_manifest_before_replay"] == (
        receipt["source"]["artifact_manifest_after_replay"])

    assert str(ROOT) not in serialized
    assert str(tmp_path) not in serialized
    validate_receipt_safety(receipt)
    artifact_ids = {
        receipt["artifacts"]["runtime_receipt"],
        receipt["source"]["database"],
        receipt["replay"]["database"],
        *(
            row["artifact"]
            for row in receipt["source"]["artifact_manifest_before_replay"]
            if row["present"]
        ),
        *(
            row["artifact"]
            for row in receipt["replay"]["artifact_manifest"]
            if row["present"]
        ),
    }
    assert all((tmp_path / artifact).is_file() for artifact in artifact_ids)
    assert all((tmp_path / artifact).resolve().is_relative_to(tmp_path) for artifact in artifact_ids)
    assert any(artifact.endswith(".manifest.json") for artifact in artifact_ids)


@pytest.mark.parametrize("error_type", [
    ReplayResourceLimitError, sqlite3.OperationalError, OSError, MemoryError, ValueError,
])
def test_verifier_failure_preserves_runtime_and_immutability_receipts(tmp_path, monkeypatch, error_type):
    def fail_verification(*args, **kwargs):
        raise error_type("private /home/test/world.db Bearer fixture-token")

    monkeypatch.setattr("scripts.run_scale_validation.verify_replay", fail_verification)
    receipt = run_validation(REHEARSAL, ticks=1, label="verifier-failure",
                             output_dir=tmp_path / "output", data_dir=tmp_path / "runs",
                             approve_live=False)
    assert json.loads((tmp_path / receipt["artifacts"]["runtime_receipt"]).read_text()) == receipt
    assert not receipt["passed"] and not receipt["checks"]["exact_replay"]
    assert receipt["replay"]["proof"] is None
    assert receipt["replay"]["verification_error"] == {
        "type": error_type.__name__, "message": "replay verification failed"}
    assert receipt["checks"]["source_immutable_during_replay"]
    assert receipt["runtime"]["memory"]["peak_rss_mb"] > 0
    assert receipt["runtime"]["source_wall_s"] > 0
    assert receipt["replay"]["wall_s"] > 0
    validate_receipt_safety(receipt)


@pytest.mark.parametrize("error", [
    OSError(28, "private directory", "/home/test/private/world.db"),
    PermissionError(13, "Bearer fixture-token", r"C:\Users\private\world.db"),
    ValueError("/home/test/private/world.db"),
    RuntimeError("fixture-token " * 10000),
    type("/private/Bearer fixture-token", (Exception,), {})("secret"),
])
def test_verifier_error_receipts_omit_private_exception_material(error):
    receipt = verification_error_receipt(error)
    encoded = json.dumps(receipt)
    assert len(encoded) < 250
    assert all(value not in encoded for value in ("/home", "C:", "private", "fixture-token"))
    validate_receipt_safety(receipt, secret_values=("fixture-token",))
    if isinstance(error, OSError):
        assert receipt["errno"] == error.errno


def test_verifier_error_receipt_preserves_known_resource_failure_reason():
    assert verification_error_receipt(ReplayResourceLimitError("replay verification time limit exceeded")) == {
        "type": "ReplayResourceLimitError", "message": "replay verification time limit exceeded"}


@pytest.mark.parametrize("acceptance", [None, {"scale_economic_health": None}])
def test_null_optional_acceptance_retains_legacy_population_checks(tmp_path, monkeypatch, acceptance):
    config = load_config(REHEARSAL)
    config["acceptance"] = acceptance
    monkeypatch.setattr("scripts.run_scale_validation.load_config", lambda _path: config)
    receipt = run_validation(REHEARSAL, ticks=1, label="null-acceptance",
                             output_dir=tmp_path / "output", data_dir=tmp_path / "runs",
                             approve_live=False)
    assert receipt["passed"] and receipt["checks"]["population_exact"]
    assert receipt["replay"]["proof"]["exact"]
    assert receipt["providers"]["cost_usd"] == 0
    assert json.loads((tmp_path / receipt["artifacts"]["runtime_receipt"]).read_text()) == receipt


def test_lifecycle_profile_changes_acceptance_only():
    old, new = load_config(BUFFER_FORMAL), load_config(LIFECYCLE_FORMAL)
    old_acceptance, new_acceptance = old.pop("acceptance"), new.pop("acceptance")
    assert old == new
    assert old_acceptance["scale_economic_health"].pop("schema_version") == 2
    assert new_acceptance["scale_economic_health"].pop("schema_version") == 3
    assert new_acceptance["scale_economic_health"].pop("population_contract") == "stable-lifecycle-v1"
    assert old_acceptance == new_acceptance


def test_lifecycle_formal_profile_still_requires_1000_ticks(tmp_path):
    with pytest.raises(ValidationInputError, match="requires exactly 1000 ticks"):
        prepare_validation_config(LIFECYCLE_FORMAL, ticks=1, output_dir=tmp_path / "output",
                                  data_dir=tmp_path / "runs", approve_live=False)


def test_cli_reports_the_persisted_runtime_artifact(monkeypatch, capsys, tmp_path):
    receipt = {
        "artifacts": {"runtime_receipt": "proofs/exact.runtime.json"},
        "source": {"run_id": "source-run", "tick": 2},
        "replay": {"run_id": "replay-run", "proof": {"exact": True}},
        "providers": {"calls": 4, "cost_usd": 0.25},
        "passed": True,
    }
    monkeypatch.setattr(
        "scripts.run_scale_validation.run_validation",
        lambda *args, **kwargs: receipt,
    )
    monkeypatch.setattr(sys, "argv", [
        "run_scale_validation.py",
        "--profile", str(REHEARSAL),
        "--ticks", "2",
        "--label", "exact",
        "--output-dir", str(tmp_path / "different-output"),
        "--data-dir", str(tmp_path / "runs"),
    ])

    main()

    result = json.loads(capsys.readouterr().out)
    assert result["receipt"] == str(
        (tmp_path / "different-output" / "exact.runtime.json").resolve())


def test_checkpoint_phase_measurement_restores_methods_after_error(tmp_path, store):
    from scripts.run_scale_validation import _checkpoint_phase_timings
    from world.loop import World

    # Use the actual static writer and inherited methods. No engine operation
    # except the isolated writer is needed to test instrumentation cleanup.
    world = World.__new__(World)
    failure = OSError("checkpoint preparation failed")

    def failed_prepare(tick):
        raise failure

    world._checkpoint_prepare = failed_prepare
    original_write = world._checkpoint_write
    with pytest.raises(OSError) as caught:
        with _checkpoint_phase_timings(world) as phases:
            world._checkpoint_prepare(1)

    assert caught.value is failure
    assert phases.keys() == {"prepare"}
    assert phases["prepare"] >= 0
    assert world.__dict__ == {"_checkpoint_prepare": failed_prepare}
    assert world._checkpoint_write is original_write

    # A later checkpoint must not retain measurements/wrappers from the failed
    # one, and the restored static writer still produces a real artifact.
    dest = tmp_path / "after-failure.db"
    with _checkpoint_phase_timings(world) as next_phases:
        result = world._checkpoint_write(store.path, dest)
    assert result is None
    assert next_phases.keys() == {
        "write", "write_backup", "write_finalize", "write_manifest"}
    assert dest.is_file()
    assert Path(f"{dest}.manifest.json").is_file()
    assert world.__dict__ == {"_checkpoint_prepare": failed_prepare}


@pytest.mark.parametrize("failed_phase", ("backup", "finalize", "manifest"))
def test_checkpoint_writer_phase_failure_is_recorded_and_preserved(
    tmp_path, store, monkeypatch, failed_phase,
):
    import sqlite3
    from scripts.run_scale_validation import _checkpoint_phase_timings
    from world.loop import World

    world = World.__new__(World)
    original_write = world._checkpoint_write
    failure = OSError("injected checkpoint failure")

    def fail(*args, **kwargs):
        raise failure

    source = store.path
    if failed_phase == "backup":
        source = str(tmp_path / "missing-parent" / "source.db")
        expected_error = sqlite3.OperationalError
    else:
        operation = (
            "finalize_sqlite_artifact" if failed_phase == "finalize"
            else "write_checkpoint_manifest")
        monkeypatch.setattr(f"world.loop.{operation}", fail)
        expected_error = OSError

    with pytest.raises(expected_error) as caught:
        with _checkpoint_phase_timings(world) as phases:
            world._checkpoint_write(source, tmp_path / "failed.db")

    if failed_phase != "backup":
        assert caught.value is failure
    ordered = ("write_backup", "write_finalize", "write_manifest")
    expected = ordered[:ordered.index(f"write_{failed_phase}") + 1]
    assert phases.keys() == {"write", *expected}
    assert all(value >= 0 for value in phases.values())
    assert sum(phases[key] for key in expected) <= phases["write"] + 0.000003
    assert world.__dict__ == {}
    assert world._checkpoint_write is original_write


def test_checkpoint_phase_measurement_preserves_custom_writer_signature():
    from scripts.run_scale_validation import _checkpoint_phase_timings
    from world.loop import World

    world = World.__new__(World)
    calls = []
    sentinel = object()

    def custom_writer(source, dest):
        calls.append((source, dest))
        return sentinel

    # An identically named positional-only argument is not an opt-in to the
    # diagnostic keyword either; ordinary overridden writers remain callable.
    def positional_writer(source, dest, phase_timings=None, /):
        assert phase_timings is None
        return custom_writer(source, dest)

    for writer in (custom_writer, positional_writer):
        world._checkpoint_write = writer
        with _checkpoint_phase_timings(world) as phases:
            assert world._checkpoint_write("source.db", "checkpoint.db") is sentinel
        assert phases.keys() == {"write"}
        assert world.__dict__ == {"_checkpoint_write": writer}
    assert calls == [("source.db", "checkpoint.db")] * 2


def test_memory_sampling_error_keeps_failed_receipt_and_source_anchors(tmp_path, monkeypatch):
    from scripts.run_scale_validation import _MemorySampler
    original = _MemorySampler.stop
    def incomplete(sampler):
        memory = original(sampler)
        assert memory['samples'] > 0 and memory['peak_rss_mb'] > 0
        memory['sampling_error'] = 'AccessDenied'
        return memory
    monkeypatch.setattr(_MemorySampler, 'stop', incomplete)
    receipt = run_validation(REHEARSAL, ticks=1, label='memory-failure',
                             output_dir=tmp_path / 'output', data_dir=tmp_path / 'runs',
                             approve_live=False)
    path = tmp_path / receipt['artifacts']['runtime_receipt']
    assert json.loads(path.read_text()) == receipt
    assert not receipt['passed'] and not receipt['checks']['memory_measured']
    assert receipt['checks']['exact_replay']
    assert receipt['checks']['source_immutable_during_replay']
    assert receipt['runtime']['memory']['sampling_error'] == 'AccessDenied'
    validate_receipt_safety(receipt)


@pytest.mark.parametrize("failure", ["import", "source"])
def test_incremental_prepare_rejects_unavailable_checkpoint_engine(tmp_path, monkeypatch, failure):
    import importlib
    from types import SimpleNamespace
    original = importlib.import_module
    def unavailable(name, *args, **kwargs):
        if name == 'engine.incremental_checkpoint':
            if failure == 'import':
                raise ModuleNotFoundError(name)
            return SimpleNamespace(__file__=str(tmp_path / 'removed' / 'incremental_checkpoint.py'))
        return original(name, *args, **kwargs)
    monkeypatch.setattr(importlib, 'import_module', unavailable)
    profile = RUNS / 'acceptance/scale-270-recovery-buffer-lifecycle-incremental-1000.yaml'
    with pytest.raises(ValidationInputError, match='incremental checkpoint engine is unavailable'):
        prepare_validation_config(profile, ticks=1000, output_dir=tmp_path / 'out',
                                  data_dir=tmp_path / 'runs', approve_live=False)
    assert not (tmp_path / 'runs').exists()


def test_legacy_prepare_does_not_require_incremental_engine(tmp_path, monkeypatch):
    import importlib
    original = importlib.import_module
    def unavailable(name, *args, **kwargs):
        if name == 'engine.incremental_checkpoint':
            raise ModuleNotFoundError(name)
        return original(name, *args, **kwargs)
    monkeypatch.setattr(importlib, 'import_module', unavailable)
    prepared = prepare_validation_config(REHEARSAL, ticks=1, output_dir=tmp_path / 'out',
                                         data_dir=tmp_path / 'runs', approve_live=False)
    assert prepared.get('checkpoint_format') != 'incremental-v2'


def test_incremental_prepare_accepts_restored_engine(tmp_path):
    profile = RUNS / 'acceptance/scale-270-recovery-buffer-lifecycle-incremental-1000.yaml'
    prepared = prepare_validation_config(profile, ticks=1000, output_dir=tmp_path / 'out',
                                         data_dir=tmp_path / 'runs', approve_live=False)
    assert prepared['checkpoint_format'] == 'incremental-v2'
    assert prepared['checkpoint_dir'] == str(tmp_path / 'runs/source/checkpoints')
