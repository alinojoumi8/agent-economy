"""Both price domains bind the new stream contract and survive resume/replay."""
from __future__ import annotations

from pathlib import Path

import pytest

from research.artifacts import file_sha256
from research.price_catalog import draft_price_study
from research.studies import StudySpec
from research.study_runner import run_study
from research.study_results import load_study_result
from tests.test_research_attempt_integrity import _config


def test_study_refuses_mislabeled_randomness_and_unvalidated_confirmatory_intent():
    config = _config()
    config["engine_semantics_version"] = 16
    spec = draft_price_study(config, "G2", seeds=[1, 2], horizon=3, intervention_tick=2)
    assert spec.randomness.stream_contract == "mechanism_day_identity_v1"
    for group, field, value in [("randomness", "stream_contract", "legacy_shared_rng_v1"),
                                ("randomness", "seed_role", "initial_world_and_engine_stream"),
                                ("model", "engine_semantics_version", 15),
                                ("analysis", "intent", "confirmatory")]:
        raw = spec.model_dump(mode="json")
        raw[group][field] = value
        with pytest.raises(ValueError):
            StudySpec.model_validate(raw)


@pytest.mark.parametrize("preset", ["G2", "F2"])
def test_keyed_goods_and_equity_studies_resume_and_replay_exactly(tmp_path, preset):
    config = _config()
    config["engine_semantics_version"] = 16
    config["households"] = {"scheduled_births": [{"tick": 2, "parent_agent_id": 1}]}
    spec = draft_price_study(config, preset, seeds=[1, 2], horizon=3, intervention_tick=2)
    raw = spec.model_dump(mode="json")
    raw["operations"].update(pause_policy="preserve_and_resume", max_wall_seconds=180)
    spec = StudySpec.model_validate(raw)
    options = dict(spec=spec, config=config, input_root=tmp_path,
                   data_root=tmp_path / "data", out_dir=tmp_path / "out")
    paused = run_study(**options, pause_after_ticks=1)
    assert paused["status"] == "paused"
    assert paused["results"][0]["ticks"] == 1
    receipt = Path(paused["artifacts"]["json"])
    digest = file_sha256(receipt)
    final = run_study(**options, resume_batch=paused["batch"]["data_dir"])
    assert final["status"] == "finalized"
    assert len(final["results"]) == 4
    assert all(row["eligibility"] == {"status": "eligible", "reasons": []} for row in final["results"]), final
    assert file_sha256(receipt) == digest
    verified = load_study_result(final["artifacts"]["json"], data_root=options["data_root"], out_dir=options["out_dir"])
    assert verified["verification"]["status"] == "verified"
    assert set(final["summary"]["metrics"]) == {"goods_price", "goods_volume", "equity_price", "equity_volume"}
