"""Policy changes from preserved worlds, with separate new-period evidence."""
from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path
import shutil
import sqlite3

import pytest

from research.artifacts import digest_json, file_sha256, publish_json
from research.attempts import verify_attempt
from research.attempt_origins import checkpoint_claim_fields
from research.checkpoint_origins import closed_checkpoint, open_continuation
from research.policy_results import load_policy_result
from research.policy_studies import draft_checkpoint_policy_comparison, provider_budget_contract, study_cells
from research.provider_budget import ProviderBudget
from research.studies import StudySpec, prepare_study
from research.study_runner import _arm_config, run_study
from research.working_studies import validate_resume
from run import open_run
from tests.test_policy_studies import base_policy_setup, policy_http_fixture


def sources_and_spec(config, initial, tmp_path, pause_policy, *, inherited_cost=True, replicates=2):
    sources = []
    for seed in (1, 2):
        original = {**config, "seed": seed, "checkpoint_every": 0, "speed_delay_s": 0.0,
            "checkpoint_dir": str(tmp_path / "initial-checkpoints"), "report_dir": str(tmp_path / "initial-reports")}
        store, world, _ = open_run(original, None, None, data_dir=tmp_path / "parents")
        try:
            asyncio.run(world.run(max_ticks=2))
            assert store.tick == 2
            sources.append(Path(store.path))
        finally:
            world.close()
        if inherited_cost:
            with sqlite3.connect(sources[-1]) as connection:
                connection.execute("UPDATE llm_calls SET provider='historical-fixture',cost_usd=7.5 WHERE id=1")
            connection.close()
    spec = draft_checkpoint_policy_comparison(config, checkpoints=sources, input_root=tmp_path,
        horizon=5, policies=list(initial.policy_design.policies), tariffs=list(initial.policy_design.tariffs),
        model_replicates=[f"draw{number+1}" for number in range(replicates)], max_provider_calls=initial.operations.max_provider_calls, max_tokens=100_000_000,
        max_spend_usd=2.0, max_wall_seconds=240, max_disk_bytes=128 * 1024 * 1024, pause_policy=pause_policy)
    # Exercise live calls before either cooperative pause. Baseline identity stays scripted.
    raw = spec.model_dump(mode="json")
    raw["arms"].reverse()
    return sources, type(spec).model_validate(raw)


@pytest.mark.parametrize("pause_policy,semantics", [
    ("preserve_and_stop", 7), ("preserve_and_resume", 7), ("preserve_and_resume_phases", 7),
    ("preserve_and_resume", 16), ("preserve_and_resume_phases", 16)])
def test_policy_origins_execute_recover_and_replay_both_domains(tmp_path, pause_policy, semantics):
    with policy_http_fixture(base_policy_setup()) as (config, initial, posts):
        config = {**config, "engine_semantics_version": semantics}
        sources, spec = sources_and_spec(config, initial, tmp_path, pause_policy)
        hashes = {path: file_sha256(path) for path in sources}
        options = dict(spec=spec, config=config, input_root=tmp_path,
            data_root=tmp_path / "data", out_dir=tmp_path / "reports")
        if pause_policy == "preserve_and_stop":
            final = run_study(**options, approve_live_inference=True)
        else:
            controls = {"pause_after_ticks": 1} if pause_policy == "preserve_and_resume" else {"pause_after_phase": "MORNING"}
            paused = run_study(**options, **controls, approve_live_inference=True)
            assert paused["status"] == "paused", paused
            assert paused["results"][0]["origin_tick"] == 2
            assert paused["results"][0]["provider_calls"] > 0
            calls = len(posts)
            validate_resume(paused["batch"]["data_dir"], **options)
            assert len(posts) == calls
            final = run_study(**options, resume_batch=paused["batch"]["data_dir"], approve_live_inference=True)
        assert len(final["results"]) == 8
        assert all(row["eligibility"] == {"status": "eligible", "reasons": []} for row in final["results"]), final
        assert final["summary"]["initial_state_key"] == "origin_state_hash"
        for domain in ("goods_price", "equity_price"):
            effect = final["summary"]["metrics"][domain]["model_a"]["paired_effect"]
            if semantics == 16 and domain == "goods_price":
                # This short modern fixture has no sales for the declared firm.
                # A valid execution cannot manufacture a measured price effect.
                assert effect["n_pairs"] == 0 and effect["mean_difference"] is None
                assert len(effect["pair_exclusions"]) == 2
            else:
                assert effect["n_pairs"] == 2
        for row in final["results"]:
            assert row["ticks"] == 5 and row["origin_tick"] == 2 and row["genesis_hash"] is None
            assert row["inherited_provider_calls"] == 1 and row["inherited_spend_usd"] == 7.5
            if row["policy"] == "scripted":
                assert row["provider_calls"] == row["spend_usd"] == row["provider_usage"]["provider_calls"] == 0
            else:
                assert 0 < row["provider_calls"] <= row["provider_usage"]["provider_calls"]
            assert row["spend_usd"] < .1
            if semantics == 16:
                assert row["metrics"]["goods_price"] is None and row["metrics"]["goods_volume"] == 0
                point = row["outcome_observations"]["goods_price"]["points"][0]
                assert point["reason"] == "no_execution_in_window" and point["quantity"] == 0
                with closed_checkpoint(row["source_database"], max_bytes=spec.operations.max_disk_bytes) as store:
                    assert store.scalar("SELECT COUNT(*) FROM events WHERE kind='goods_sale' AND tick>2 "
                        "AND json_extract(payload_json,'$.firm_id')=2") == 0
            assert all(point["tick"] >= spec.time.measurement_start > spec.origin.tick
                for observed in row["outcome_observations"].values() for point in observed["points"])
            assert verify_attempt(row, expected_ticks=5) == [], row
            replay = json.loads(Path(row["replay_receipt"]).read_text())
            assert replay["continuation_window"] == [3, 5]
            assert replay["protocol_version"] == 3 and replay["policy_transition_sha256"]
        loaded = load_policy_result(final["artifacts"]["json"], data_root=options["data_root"], out_dir=options["out_dir"])
        assert loaded["verification"]["status"] == "verified", loaded["verification"]
        assert len(posts) == final["operations"]["provider_calls"]
        assert all(file_sha256(path) == digest for path, digest in hashes.items())
        assert all(not Path(str(path) + suffix).exists() for path in hashes for suffix in ("-wal", "-shm", "-journal"))


@pytest.mark.parametrize("change", ["economics", "seed", "model", "transition", "foreign_budget", "missing_budget", "cell"])
def test_undeclared_policy_origin_changes_refuse_before_allocating_a_child(tmp_path, change):
    config, initial = base_policy_setup()
    _, spec = sources_and_spec(config, initial, tmp_path, "preserve_and_stop", replicates=1)
    batch = prepare_study(spec, config, input_root=tmp_path, data_root=tmp_path / "data", out_dir=tmp_path / "reports")
    root = Path(batch["data_dir"])
    contract = provider_budget_contract(spec, config, manifest_sha256=batch["manifest_sha256"])
    publish_json(root / "provider-budget-contract.json", contract.model_dump(mode="json"))
    cell = study_cells(spec)[0]
    budget = ProviderBudget.create(root / "provider-budget.db", contract, scope=cell["cell_key"], binding_key=cell["policy"])
    fields = checkpoint_claim_fields(spec, batch["manifest"], root, cell["seed"], cell["arm"],
        policy_cell=cell, completion_guard=budget)
    configured = {**_arm_config(spec, config, cell["arm"]), "seed": cell["seed"]}
    claim = {**fields, "seed": cell["seed"], "arm": cell["arm"], "run_id": "declared-policy-child"}
    source = Path(fields["checkpoint_origin"]["database"])
    receipt = fields["checkpoint_origin"]["receipt"]
    before = file_sha256(source)
    if change == "economics":
        configured["population"]["size"] += 1
    elif change == "seed":
        configured["seed"] += 1
    elif change == "model":
        configured["llm"]["default_route"]["model"] = "undeclared-model"
    elif change == "transition":
        claim["checkpoint_origin"]["policy_transition"]["effective_tick"] += 1
    elif change == "foreign_budget":
        other = contract.model_copy(update={"study_manifest_sha256": "f" * 64})
        budget = ProviderBudget.create(tmp_path / "foreign.db", other, scope=cell["cell_key"], binding_key=cell["policy"])
        claim["provider_budget_contract_sha256"] = digest_json(other.model_dump(mode="json"))
    elif change == "missing_budget":
        budget = None
    else:
        claim["policy_cell"] = study_cells(spec)[-1]
    child = tmp_path / "child.db"
    with pytest.raises(ValueError):
        open_continuation(source, receipt, child, run_id=claim["run_id"], config=configured,
            interventions=[], max_bytes=spec.operations.max_disk_bytes, policy_claim=claim, completion_guard=budget)
    assert not child.exists() and file_sha256(source) == before


def test_origin_storage_admission_counts_every_model_replicate_before_copying(tmp_path):
    config, initial = base_policy_setup()
    sources, spec = sources_and_spec(config, initial, tmp_path, "preserve_and_stop")
    total = sum(path.stat().st_size for path in sources)
    raw = spec.model_dump(mode="json")
    # This admits the old arms-only estimate but cannot fit all model draws.
    raw["operations"]["max_disk_bytes"] = total * (1 + 2 * len(spec.arms)) + 256 * 1024
    with pytest.raises(ValueError, match="independent arm/replay copies"):
        prepare_study(StudySpec.model_validate(raw), config, input_root=tmp_path,
            data_root=tmp_path / "rejected", out_dir=tmp_path / "rejected-reports")
    assert not (tmp_path / "rejected").exists() and not (tmp_path / "rejected-reports").exists()


def test_completed_origin_policy_evidence_is_relocatable_without_current_prompts(tmp_path, monkeypatch):
    with policy_http_fixture(base_policy_setup()) as (config, initial, posts):
        config = copy.deepcopy(config)
        config["shocks"] = [{"kind": "oil", "trigger": "shock", "trigger_params": {"tick": 4},
            "duration_ticks": 0, "params": {"multiplier": 1.2}, "label": "Inherited future schedule"}]
        sources, spec = sources_and_spec(config, initial, tmp_path, "preserve_and_resume_phases", replicates=1)
        raw = spec.model_dump(mode="json")
        raw["arms"][0]["changes"] = {"shocks": [{"kind": "oil", "tick": 3, "multiplier": 1.5}]}
        spec = StudySpec.model_validate(raw)
        originals = {path: file_sha256(path) for path in sources}
        args = dict(spec=spec, config=config, input_root=tmp_path,
            data_root=tmp_path / "data", out_dir=tmp_path / "reports")
        paused = run_study(**args, pause_after_phase="MORNING", approve_live_inference=True)
        final = run_study(**args, resume_batch=paused["batch"]["data_dir"], approve_live_inference=True)
        assert all(row["eligibility"]["status"] == "eligible" for row in final["results"]), final
        for row in final["results"]:
            with closed_checkpoint(row["source_database"], max_bytes=spec.operations.max_disk_bytes) as store:
                assert store.scalar("SELECT COUNT(*) FROM shocks WHERE fired_tick=4") == 1
                assert store.scalar("SELECT COUNT(*) FROM shocks WHERE fired_tick=3") == (row["policy"] == "model_a")
        assert all(file_sha256(path) == digest for path, digest in originals.items())
        calls = len(posts)
    shutil.copytree(args["data_root"], tmp_path / "copied-data")
    shutil.copytree(args["out_dir"], tmp_path / "copied-reports")
    copied = tmp_path / "copied-reports" / Path(final["artifacts"]["json"]).relative_to(args["out_dir"])
    monkeypatch.setattr("research.policy_studies.prompt_source_identity", lambda: "f" * 64)
    hashes = {path: file_sha256(path) for path in (tmp_path / "copied-data").rglob("*") if path.is_file()}
    loaded = load_policy_result(copied, data_root=tmp_path / "copied-data", out_dir=tmp_path / "copied-reports")
    assert loaded["verification"]["status"] == "verified", loaded["verification"]
    assert {path: file_sha256(path) for path in (tmp_path / "copied-data").rglob("*") if path.is_file()} == hashes
    assert len(posts) == calls


@pytest.mark.parametrize("change", ["owned_origin", "inherited_input", "policy_transition"])
def test_changed_origin_evidence_refuses_resume_before_calls_or_writes(tmp_path, change):
    with policy_http_fixture(base_policy_setup()) as (config, initial, posts):
        _, spec = sources_and_spec(config, initial, tmp_path, "preserve_and_resume_phases", replicates=1)
        args = dict(spec=spec, config=config, input_root=tmp_path,
            data_root=tmp_path / "data", out_dir=tmp_path / "reports")
        paused = run_study(**args, pause_after_phase="MORNING", approve_live_inference=True)
        row = paused["results"][0]
        claim_path = Path(row["attempt_claim"])
        claim = json.loads(claim_path.read_text())
        if change == "policy_transition":
            claim["checkpoint_origin"]["policy_transition"]["effective_tick"] += 1
            claim_path.write_text(json.dumps(claim), encoding="utf-8")
        else:
            target = claim["checkpoint_origin"]["database"] if change == "owned_origin" else row["source_database"]
            with sqlite3.connect(target) as connection:
                connection.execute("UPDATE llm_calls SET cost_usd=cost_usd+1 WHERE id=1")
            connection.close()
        before = {path: file_sha256(path) for path in tmp_path.rglob("*") if path.is_file()}
        calls = len(posts)
        with pytest.raises(ValueError):
            run_study(**args, resume_batch=paused["batch"]["data_dir"], approve_live_inference=True)
        assert len(posts) == calls
        assert {path: file_sha256(path) for path in tmp_path.rglob("*") if path.is_file()} == before


@pytest.mark.parametrize("pause_policy", ["preserve_and_stop", "preserve_and_resume_phases"])
@pytest.mark.parametrize("failure", ["exhausted", "invalid_response"])
def test_origin_policy_failures_retain_inherited_history_and_original_allowance(tmp_path, pause_policy, failure):
    with policy_http_fixture(base_policy_setup(), max_calls=1 if failure == "exhausted" else 500,
            invalid_responses=failure == "invalid_response") as (config, initial, posts):
        sources, spec = sources_and_spec(config, initial, tmp_path, pause_policy, replicates=1)
        originals = {path: file_sha256(path) for path in sources}
        args = dict(spec=spec, config=config, input_root=tmp_path,
            data_root=tmp_path / "data", out_dir=tmp_path / "reports")
        final = run_study(**args, approve_live_inference=True)
        usage = final["provider_budget"]["usage"]
        calls = len(posts)
        assert usage["sealed"] is True and 1 <= calls <= usage["provider_calls"]
        assert usage["provider_calls"] - calls <= usage["unresolved_calls"] + usage["unknown_usage_calls"]
        if calls < usage["provider_calls"]:
            assert usage["encumbered_nano_usd"] > usage["usage_cost_nano_usd"]
        assert all(row["eligibility"]["status"] == "ineligible" for row in final["results"])
        started = [row for row in final["results"] if row.get("attempt_claim")]
        assert started
        for row in started:
            assert row["inherited_provider_calls"] == 1 and row["inherited_spend_usd"] == 7.5
            assert row["provider_calls"] <= usage["provider_calls"] and row["spend_usd"] < .1
        loaded = load_policy_result(final["artifacts"]["json"], data_root=args["data_root"], out_dir=args["out_dir"])
        assert loaded["verification"]["status"] == "verified", loaded["verification"]
        for domain in ("goods_price", "equity_price"):
            assert loaded["summary"]["metrics"][domain]["model_a"]["paired_effect"]["n_pairs"] == 0
        assert all(file_sha256(path) == digest for path, digest in originals.items())


def test_checkpoint_policy_cli_preserves_sources_and_drafts_without_provider_access(tmp_path, monkeypatch, capsys):
    from research.policy_studies import ROOT, main as draft_main
    from research.study_runner import main as runner_main

    config, initial = base_policy_setup()
    sources, _ = sources_and_spec(config, initial, tmp_path, "preserve_and_resume", replicates=1)
    originals = {path: file_sha256(path) for path in sources}
    design = {"policies": [{"key": p.key, "llm": p.llm, "temperature": p.behavior.temperature,
        "repair_temperature": p.repair_temperature} for p in initial.policy_design.policies],
        "tariffs": [tariff.model_dump(mode="json") for tariff in initial.policy_design.tariffs]}
    design_path, study_path = tmp_path / "design.json", tmp_path / "study.json"
    design_path.write_text(json.dumps(design), encoding="utf-8")
    arguments = ["policy_studies", "--config", str(ROOT / "runs/price-lab-pilot.yaml"),
        "--design", str(design_path), "--output", str(study_path), "--input-root", str(tmp_path),
        "--model-replicates", "draw1", "draw2", "--ticks", "5", "--max-provider-calls", "200",
        "--max-tokens", "1000000", "--max-spend-usd", ".1", "--pause-policy", "preserve_and_resume"]
    for path in sources:
        arguments += ["--checkpoint", str(path)]
    monkeypatch.setattr("sys.argv", arguments)
    assert draft_main() == 0
    assert json.loads(capsys.readouterr().out)["provider_calls"] == 0
    declared = StudySpec.model_validate_json(study_path.read_text())
    assert declared.origin.tick == 2 and declared.randomness.seeds == [1, 2]
    assert declared.time.intervention_start == 3 and declared.time.horizon == 5
    before = file_sha256(study_path)
    assert draft_main() == 2 and file_sha256(study_path) == before
    capsys.readouterr()
    monkeypatch.setattr("sys.argv", ["study_runner", str(study_path), "--config",
        str(ROOT / "runs/price-lab-pilot.yaml"), "--input-root", str(tmp_path), "--validate-only",
        "--data-root", str(tmp_path / "data"), "--out-dir", str(tmp_path / "reports")])
    assert runner_main() == 0 and json.loads(capsys.readouterr().out)["executed"] is False
    arguments[arguments.index("--output") + 1] = str(tmp_path / "conflicting-study.json")
    monkeypatch.setattr("sys.argv", [*arguments, "--seeds", "1", "2"])
    assert draft_main() == 2 and not (tmp_path / "conflicting-study.json").exists()
    assert not (tmp_path / "data").exists() and not (tmp_path / "reports").exists()
    assert all(file_sha256(path) == digest for path, digest in originals.items())
