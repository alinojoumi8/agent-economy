import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from engine.schema import SCHEMA_VERSION
from research.artifacts import digest_json, file_sha256
from research.studies import StudySpec, load_study, prepare_study


@pytest.fixture
def protocol():
    return {
        "protocol_version": "research-study-v1", "key": "price-pilot",
        "title": "Paired price pilot", "hypothesis": "A cost change affects prices",
        "limitations": ["Daily scripted synthetic economy; shared RNG across mechanisms"],
        "domains": ["goods", "equities"],
        "model": {"engine_semantics_version": 7, "schema_version": SCHEMA_VERSION,
                  "resolved_config_sha256": digest_json({"engine_semantics_version": 7}),
                  "model_description_version": "agent-economy-odd-v1",
                  "regimes": ["reserve-funded-credit"]},
        "inputs": [], "calibration_targets": [],
        "arms": [
            {"key": "base", "label": "Unchanged cost", "role": "baseline",
             "changes": {}, "information_policy": "common public disclosures"},
            {"key": "cost", "label": "Higher cost", "role": "treatment",
             "changes": {"shocks": [{"kind": "oil", "tick": 1, "multiplier": 1.2}]},
             "information_policy": "common public disclosures"}],
        "behavior": {"family": "scripted", "version": "scripted-v1",
                     "prompt_sha256": None, "provider_reference": None,
                     "model_reference": None, "endpoint_reference": None,
                     "temperature": None, "wake_cadence": "daily",
                     "communication_policy": "public", "population_assignment": "all scripted"},
        "time": {"tick_duration": "one_day", "warmup_ticks": 0,
                 "intervention_start": 1, "intervention_end": 3,
                 "measurement_start": 1, "measurement_end": 3,
                 "horizon": 3, "stop_rule": "fixed_horizon"},
        "randomness": {"seeds": [1, 2, 3], "seed_role": "initial_world_and_engine_stream",
                       "stream_contract": "legacy_shared_rng_v1",
                       "pairing": "verified_common_genesis", "model_replicates": []},
        "analysis": {"intent": "exploratory", "estimand": "Mean paired difference",
                     "treatment_unit": "world_seed_pair",
                     "outcomes": [
                         {"key": "posted_index", "metric": "cpi",
                          "metric_version": "legacy-genesis-posted-v2",
                          "aggregation": "terminal", "currency": "USD", "purpose": "primary"},
                         {"key": "equity_price", "metric": "stock:1",
                          "metric_version": "last-execution-v1", "aggregation": "terminal",
                          "currency": "USD", "purpose": "primary"}],
                     "missing_data": "exclude_pair_report_reason",
                     "uncertainty": "paired_world_bootstrap", "minimum_pairs": 2,
                     "bootstrap_samples": 100, "multiple_outcome_policy": "descriptive_only"},
        "operations": {"mode": "provider_free", "max_provider_calls": 0,
                       "max_tokens": 0, "max_spend_usd": 0.0,
                       "max_wall_seconds": 120, "max_disk_bytes": 100_000_000,
                       "concurrency": 1, "failure_policy": "preserve_and_exclude",
                       "pause_policy": "preserve_and_stop"}}


def test_protocol_is_strict_at_each_level_and_preserves_both_domains(protocol):
    spec = StudySpec.model_validate(protocol)
    assert spec.domains == ["goods", "equities"]
    for path in [[], ["model"], ["time"], ["operations"], ["analysis", "outcomes", 0],
                 ["arms", 1], ["behavior"]]:
        raw = copy.deepcopy(protocol)
        section = raw
        for key in path:
            section = section[key]
        section["unexpected"] = "do not silently ignore"
        with pytest.raises(ValidationError, match="Extra inputs"):
            StudySpec.model_validate(raw)


@pytest.mark.parametrize("seeds", [[1, 1], [], [True], [1.2], ["1"], [-1]])
def test_protocol_rejects_invalid_seed_assignment(protocol, seeds):
    protocol["randomness"]["seeds"] = seeds
    with pytest.raises(ValidationError):
        StudySpec.model_validate(protocol)


def test_protocol_rejects_unsupported_or_misleading_contracts(protocol):
    cases = [
        (["model", "engine_semantics_version"], 999),
        (["model", "schema_version"], 0),
        (["time", "measurement_end"], 2),
        (["time", "warmup_ticks"], 1),
        (["analysis", "intent"], "confirmatory"),
        (["analysis", "outcomes", 0, "metric_version"], "invented"),
        (["analysis", "outcomes", 0, "currency"], None),
        (["analysis", "outcomes", 0, "aggregation"], "window_sum"),
        (["analysis", "multiple_outcome_policy"], "single_primary"),
        (["operations", "max_spend_usd"], 2.0),
        (["operations", "mode"], "live"),
        (["operations", "max_wall_seconds"], 0),
        (["arms", 1, "key"], "base"),
        (["arms", 0, "changes"], {"price": 10}),
        (["arms", 1, "changes"], {}),
        (["randomness", "model_replicates"], ["unimplemented"]),
        (["behavior", "family"], "live_llm"),
    ]
    for path, value in cases:
        raw = copy.deepcopy(protocol)
        section = raw
        for key in path[:-1]:
            section = section[key]
        section[path[-1]] = value
        with pytest.raises(ValidationError):
            StudySpec.model_validate(raw)
    protocol["analysis"]["outcomes"].pop()
    with pytest.raises(ValidationError, match="each declared price domain"):
        StudySpec.model_validate(protocol)


def test_secret_values_and_nonfinite_changes_are_never_published(protocol, tmp_path):
    protocol["arms"][1]["changes"] = {"provider": {"api_key": "private-fixture"}}
    with pytest.raises(ValidationError, match="Extra inputs") as error:
        StudySpec.model_validate(protocol)
    # Pydantic's full error object may hold input; runners must not log it.
    assert "private-fixture" not in str(error.value.errors(include_input=False))
    protocol["arms"][1]["changes"] = {"shocks": [{"kind": "oil", "tick": 1, "multiplier": float("nan")}]}
    with pytest.raises(ValidationError):
        StudySpec.model_validate(protocol)
    assert not list(tmp_path.iterdir())


def test_prepare_verifies_inputs_configuration_and_preserves_prior_manifest(protocol, tmp_path):
    source = tmp_path / "input.json"
    source.write_text('{"vintage":"synthetic-1"}', encoding="utf-8")
    artifact = {"key": "cohort", "path": "input.json", "sha256": file_sha256(source),
                "role": "initialization", "vintage": "synthetic-1", "transform_version": "identity-v1"}
    protocol["inputs"] = [artifact]
    spec = StudySpec.model_validate(protocol)
    config = {"engine_semantics_version": 7}
    kwargs = {"input_root": tmp_path, "data_root": tmp_path / "data", "out_dir": tmp_path / "out"}
    first = prepare_study(spec, config, **kwargs)
    manifest = Path(first["data_dir"]) / "manifest.json"
    original = manifest.read_bytes()
    second = prepare_study(spec, config, **kwargs)
    assert first["batch_id"] != second["batch_id"]
    assert manifest.read_bytes() == original
    assert first["manifest_sha256"] == second["manifest_sha256"]
    assert first["manifest"]["creation_provenance"] == "prepared_before_attempt_initialization"
    assert len(first["manifest"]["code"]["source_tree_sha256"]) == 64
    with pytest.raises(ValueError, match="configuration differs"):
        prepare_study(spec, {**config, "seed": 5}, **kwargs)
    source.write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        prepare_study(spec, config, **kwargs)
    assert manifest.read_bytes() == original


def test_holdout_must_be_separate_and_inputs_cannot_escape_root(protocol, tmp_path):
    artifact = {"key": "fitting", "path": "../outside.json", "sha256": "a" * 64,
                "role": "calibration", "vintage": "v1", "transform_version": "identity-v1"}
    protocol["inputs"] = [artifact, {**artifact, "key": "heldout", "role": "holdout"}]
    with pytest.raises(ValidationError, match="holdout artifacts"):
        StudySpec.model_validate(protocol)
    protocol["inputs"].pop()
    with pytest.raises(ValueError, match="outside its declared root or missing"):
        prepare_study(StudySpec.model_validate(protocol), {"engine_semantics_version": 7},
                      input_root=tmp_path, data_root=tmp_path / "data", out_dir=tmp_path / "out")
    assert not (tmp_path / "data").exists()


def test_protocol_file_roundtrip_and_post_validation_mutation_are_checked(protocol, tmp_path):
    path = tmp_path / "study.json"
    path.write_text(json.dumps(protocol), encoding="utf-8")
    spec = load_study(path)
    spec.randomness.seeds.append(1)
    with pytest.raises(ValidationError, match="unique"):
        prepare_study(spec, {"engine_semantics_version": 7}, input_root=tmp_path,
                      data_root=tmp_path / "data", out_dir=tmp_path / "out")
    assert not (tmp_path / "data").exists()
