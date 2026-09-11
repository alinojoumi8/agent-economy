"""Saved-world admission and actual independent continuation replay."""
from __future__ import annotations

import asyncio
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

import pytest

from research.artifacts import digest_json, file_sha256
from research.checkpoint_origins import (
    copy_checkpoint, inspect_checkpoint, open_continuation, verify_checkpoint,
)
from research.working_contracts import persisted_random_state
from research.price_catalog import draft_price_study
from research.studies import StudySpec, prepare_study, validate_study_inputs
from research.study_runner import run_study
from run import open_run
from tests.test_phase_working_attempts import phase_options
from world.replay_verify import canonical_state_receipt, verify_replay

LIMIT = 128 * 1024 * 1024


def source_world(tmp_path, *, seed=1, semantics=16):
    config = phase_options(tmp_path, semantics=semantics)["config"]
    config.update(seed=seed, checkpoint_every=0, checkpoint_dir=str(tmp_path / "checkpoints"),
                  report_dir=str(tmp_path / "reports"), speed_delay_s=0.0)
    store, world, _ = open_run(config, None, None, data_dir=tmp_path / "parents")
    path = Path(store.path)
    try:
        asyncio.run(world.run(max_ticks=2))
        assert store.tick == 2
    finally:
        world.close()
    return path, config


@pytest.mark.parametrize("semantics", [7, 16])
@pytest.mark.parametrize("kind", ["oil", "scandal"])
def test_two_saved_world_pairs_continue_and_replay_without_rewriting_history(tmp_path, semantics, kind):
    origins = []
    for seed in (1, 2):
        path, config = source_world(tmp_path / str(seed), seed=seed, semantics=semantics)
        original = path.read_bytes()
        receipt = inspect_checkpoint(path, max_bytes=LIMIT, config=config)
        origins.append(receipt["initial_state_sha256"])
        assert receipt["tick"] == 2 and receipt["recorded_inputs"]["count"] > 0
        for arm in ("control", "treatment"):
            interventions = [] if arm == "control" else [{"kind": kind, "trigger": "shock",
                "trigger_params": {"tick": 3}, "duration_ticks": 0, "label": f"study:{arm}:{kind}",
                "params": {"multiplier": 2.0} if kind == "oil" else
                    {"firm_id": 1, "description": "A declared negative firm disclosure"}}]
            child_config = copy.deepcopy(config)
            child_config["shocks"] = [*(config.get("shocks") or []), *interventions]
            child = tmp_path / str(seed) / arm / "source.db"
            store, world = open_continuation(path, receipt, child, run_id=f"s{seed}-{arm}",
                config=child_config, interventions=interventions, max_bytes=LIMIT)
            try:
                assert store.tick == 2 and store.get_meta()["fork_tick"] == 2
                assert digest_json(persisted_random_state(store.get_meta())) == receipt["prng_sha256"]
                asyncio.run(world.run(max_ticks=2))
                assert store.tick == 4
                assert store.scalar("SELECT COUNT(*) FROM shocks WHERE fired_tick=3") == len(interventions)
                if kind == "oil" and interventions:
                    assert store.scalar("SELECT COUNT(*) FROM events WHERE kind='shock_fired' AND tick=3") == 1
            finally:
                world.close()
            child_hash = file_sha256(child)
            replay_path = child.with_name("replay.db")
            replay_store, replay_world = open_continuation(path, receipt, replay_path,
                run_id=f"replay-s{seed}-{arm}", config=child_config, interventions=interventions,
                max_bytes=LIMIT, replay_source=child, replay_source_sha256=child_hash)
            try:
                asyncio.run(replay_world.run(max_ticks=2))
                assert replay_store.tick == 4
            finally:
                replay_world.close()
            proof = verify_replay(child, replay_path)
            assert proof["exact"], [table for table in proof["tables"] if not table["exact"]]
            assert file_sha256(child) == child_hash
            assert path.read_bytes() == original
            assert not any(Path(str(path) + suffix).exists() for suffix in ("-wal", "-shm", "-journal"))
            assert verify_checkpoint(path, receipt, max_bytes=LIMIT) == receipt
    assert origins[0] != origins[1]


@pytest.mark.parametrize("mutation", ["tick", "phase", "random", "ledger", "config", "input"])
def test_changed_checkpoint_refuses_before_child_allocation(tmp_path, mutation):
    path, config = source_world(tmp_path)
    receipt = inspect_checkpoint(path, max_bytes=LIMIT)
    with sqlite3.connect(path) as conn:
        if mutation == "tick":
            conn.execute("UPDATE run_meta SET tick=tick+1")
        elif mutation == "phase":
            conn.execute("UPDATE run_meta SET active_tick=tick+1,next_phase='MORNING'")
        elif mutation == "random":
            conn.execute("UPDATE run_meta SET lifecycle_prng_state='[]'")
        elif mutation == "ledger":
            conn.execute("UPDATE accounts SET balance_cents=balance_cents+1 WHERE id=1")
        elif mutation == "config":
            changed = copy.deepcopy(config)
            changed["seed"] = 4
            conn.execute("UPDATE run_meta SET config_json=?", (json.dumps(changed),))
        else:
            conn.execute("UPDATE llm_calls SET latency_ms=latency_ms+1 WHERE id=1")
    conn.close()
    changed_bytes = path.read_bytes()
    child = tmp_path / "forbidden" / "child.db"
    with pytest.raises(ValueError):
        copy_checkpoint(path, receipt, child, max_bytes=LIMIT)
    assert not child.parent.exists()
    assert path.read_bytes() == changed_bytes


def test_checkpoint_limits_sidecars_and_existing_children_are_not_overridden(tmp_path):
    path, config = source_world(tmp_path)
    receipt = inspect_checkpoint(path, max_bytes=LIMIT)
    with pytest.raises(ValueError, match="size limit"):
        inspect_checkpoint(path, max_bytes=path.stat().st_size - 1)
    with pytest.raises(ValueError, match="configuration"):
        inspect_checkpoint(path, max_bytes=LIMIT, config={**config, "seed": 99})
    sidecar = Path(str(path) + "-wal")
    sidecar.write_bytes(b"active")
    with pytest.raises(ValueError, match="sidecars"):
        inspect_checkpoint(path, max_bytes=LIMIT)
    # Only this test's own synthetic sidecar is removed, never a real source WAL.
    sidecar.unlink()
    child = copy_checkpoint(path, receipt, tmp_path / "child.db", max_bytes=LIMIT)
    original = child.read_bytes()
    with pytest.raises(FileExistsError):
        copy_checkpoint(path, receipt, child, max_bytes=LIMIT)
    assert child.read_bytes() == original


def test_continuation_refuses_undeclared_configuration_before_copy(tmp_path):
    path, config = source_world(tmp_path)
    receipt = inspect_checkpoint(path, max_bytes=LIMIT)
    child = tmp_path / "forbidden" / "child.db"
    with pytest.raises(ValueError, match="declared interventions"):
        open_continuation(path, receipt, child, run_id="child",
            config={**config, "seed": 2, "shocks": []}, interventions=[], max_bytes=LIMIT)
    assert not child.parent.exists()


@pytest.mark.parametrize("semantics", [7, 16])
def test_scheduled_treatment_does_not_leak_before_its_declared_tick(tmp_path, semantics, monkeypatch):
    class FixedGatewayClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 7, tzinfo=timezone.utc).astimezone(tz)

    # Call-reference receipts retain the recorder's timestamp. Hold only that
    # observational clock fixed when comparing separately executed branches.
    monkeypatch.setattr("llm.gateway.datetime", FixedGatewayClock)
    path, config = source_world(tmp_path, semantics=semantics)
    receipt = inspect_checkpoint(path, max_bytes=LIMIT)
    before_treatment = []
    for arm in ("control", "treatment"):
        interventions = [] if arm == "control" else [{"kind": "scandal", "trigger": "shock",
            "trigger_params": {"tick": 4}, "params": {"firm_id": 1, "description": "FUTURE_SECRET"},
            "duration_ticks": 0, "label": "future-treatment"}]
        store, world = open_continuation(path, receipt, tmp_path / arm / "source.db", run_id=arm,
            config={**config, "shocks": interventions}, interventions=interventions, max_bytes=LIMIT)
        try:
            asyncio.run(world.run(max_ticks=1))
            assert store.tick == 3
            assert not store.scalar("SELECT COUNT(*) FROM events WHERE payload_json LIKE '%FUTURE_SECRET%'")
            assert not store.scalar("SELECT COUNT(*) FROM llm_calls WHERE request_json LIKE '%FUTURE_SECRET%'")
            before_treatment.append({
                "state": canonical_state_receipt(store.conn, excluded_protocol_tables=("shocks",))["sha256"],
                "random": digest_json(persisted_random_state(store.get_meta())),
            })
        finally:
            world.close()
    assert before_treatment[0] == before_treatment[1]


def test_interventions_before_origin_refuse_before_copy(tmp_path):
    path, config = source_world(tmp_path)
    receipt = inspect_checkpoint(path, max_bytes=LIMIT)
    intervention = {"kind": "oil", "trigger_params": {"tick": 2}, "params": {"multiplier": 2}}
    destination = tmp_path / "forbidden" / "child.db"
    with pytest.raises(ValueError, match="follow the admitted boundary"):
        open_continuation(path, receipt, destination, run_id="child",
            config={**config, "shocks": [intervention]}, interventions=[intervention], max_bytes=LIMIT)
    assert not destination.parent.exists()


def checkpoint_spec(tmp_path, *, preset="G2", pause_policy=None, inherited_cost=False):
    sources, inputs, baseline = [], [], None
    for seed in (1, 2):
        path, config = source_world(tmp_path / str(seed), seed=seed)
        if baseline is None:
            baseline = config
        if inherited_cost:
            with sqlite3.connect(path) as connection:
                connection.execute("UPDATE llm_calls SET provider='historical-provider',cost_usd=7.5 WHERE id=1")
            connection.close()
        receipt = inspect_checkpoint(path, max_bytes=LIMIT)
        key = f"origin-{seed}"
        inputs.append({"key": key, "path": path.relative_to(tmp_path).as_posix(),
            "sha256": receipt["database_sha256"], "role": "checkpoint",
            "vintage": "synthetic completed day 2", "transform_version": "identity"})
        sources.append({"seed": seed, "input_key": key, "receipt_sha256": digest_json(receipt)})
    raw = draft_price_study(baseline, preset, seeds=[1, 2], horizon=5, intervention_tick=4).model_dump(mode="json")
    raw.update(protocol_version="research-study-v2", inputs=inputs,
               origin={"kind": "verified_checkpoints", "tick": 2, "sources": sources})
    raw["randomness"].update(seed_role="checkpoint_origin_seed", pairing="verified_common_checkpoint")
    raw["analysis"]["treatment_unit"] = "checkpoint_world_pair"
    raw["time"]["warmup_ticks"] = 1
    raw["operations"]["max_wall_seconds"] = 240
    if pause_policy:
        raw["operations"]["pause_policy"] = pause_policy
    return StudySpec.model_validate(raw), baseline


def test_checkpoint_protocol_admits_and_privately_snapshots_both_origins(tmp_path):
    spec, config = checkpoint_spec(tmp_path)
    admitted = validate_study_inputs(spec, config, input_root=tmp_path)
    assert set(admitted["checkpoint_origins"]) == {"1", "2"}
    assert {item["tick"] for item in admitted["checkpoint_origins"].values()} == {2}
    batch = prepare_study(spec, config, input_root=tmp_path, data_root=tmp_path / "data", out_dir=tmp_path / "out")
    for item in spec.inputs:
        snapshot = Path(batch["data_dir"]) / "context" / "inputs" / f"{item.sha256}.blob"
        assert snapshot.read_bytes() == (tmp_path / item.path).read_bytes()
    assert batch["manifest"]["origin_contract"] == "admitted-state-with-recorded-continuation-v1"


def test_genesis_manifest_serialization_keeps_its_original_fields(tmp_path):
    spec = phase_options(tmp_path)["spec"]
    raw = spec.model_dump(mode="json")
    assert "origin" not in raw
    assert StudySpec.model_validate(raw).model_dump(mode="json") == raw
    with pytest.raises(ValueError, match="explicit research-study-v2"):
        StudySpec.model_validate({**raw, "protocol_version": "research-study-v2"})


def test_checkpoint_declaration_and_copy_budget_refuse_before_batch_allocation(tmp_path):
    spec, config = checkpoint_spec(tmp_path)
    raw = spec.model_dump(mode="json")
    raw["origin"]["sources"][0]["receipt_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="differs from the study declaration"):
        prepare_study(StudySpec.model_validate(raw), config, input_root=tmp_path,
                      data_root=tmp_path / "bad-receipt", out_dir=tmp_path / "bad-out")
    assert not (tmp_path / "bad-receipt").exists()
    raw = spec.model_dump(mode="json")
    # Individual snapshots fit, but their independent arm/replay copies do not.
    raw["operations"]["max_disk_bytes"] = sum((tmp_path / item.path).stat().st_size for item in spec.inputs) * 2
    with pytest.raises(ValueError, match="independent arm/replay copies"):
        prepare_study(StudySpec.model_validate(raw), config, input_root=tmp_path,
                      data_root=tmp_path / "too-large", out_dir=tmp_path / "large-out")
    assert not (tmp_path / "too-large").exists()


@pytest.mark.parametrize("field", ["warmup", "pairing", "seeds", "input_kind", "holdout"])
def test_checkpoint_protocol_rejects_inconsistent_initial_conditions(tmp_path, field):
    spec, _ = checkpoint_spec(tmp_path)
    raw = spec.model_dump(mode="json")
    if field == "warmup":
        raw["time"]["warmup_ticks"] = 2
    elif field == "pairing":
        raw["randomness"]["pairing"] = "verified_common_genesis"
    elif field == "seeds":
        raw["origin"]["sources"][1]["seed"] = 1
    elif field == "input_kind":
        raw["inputs"][0]["role"] = "initialization"
    else:
        raw["inputs"].append({**raw["inputs"][0], "key": "holdout", "role": "holdout"})
    with pytest.raises(ValueError):
        StudySpec.model_validate(raw)


@pytest.mark.parametrize("flag", ["participant_influenced", "external_agent_influenced"])
def test_checkpoint_admission_refuses_undeclared_operator_or_external_influence(tmp_path, flag):
    path, _ = source_world(tmp_path)
    with sqlite3.connect(path) as connection:
        connection.execute(f"UPDATE run_meta SET {flag}=1")
    connection.close()
    before = file_sha256(path)
    with pytest.raises(ValueError, match="undeclared external influence"):
        inspect_checkpoint(path, max_bytes=LIMIT)
    assert file_sha256(path) == before


def test_oversized_checkpoint_refuses_before_hashing_its_contents(tmp_path, monkeypatch):
    spec, config = checkpoint_spec(tmp_path)
    raw = spec.model_dump(mode="json")
    raw["operations"]["max_disk_bytes"] = 1

    def forbidden(*args, **kwargs):
        pytest.fail("an oversized checkpoint must be rejected before reading its contents")

    monkeypatch.setattr("research.studies.file_sha256", forbidden)
    with pytest.raises(ValueError, match="admission size limit"):
        validate_study_inputs(StudySpec.model_validate(raw), config, input_root=tmp_path)
