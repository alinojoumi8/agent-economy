import copy
import json
from pathlib import Path

import pytest

from research.artifacts import digest_json, file_sha256
from research.attempts import verify_attempt
from research.studies import StudySpec, validate_study_inputs
from research.study_runner import collect_outcomes, run_study, validate_execution
from tests.test_study_protocol import protocol
from tests.test_research_attempt_integrity import _config
from tests.conftest import make_agent, make_bank


def test_real_study_runs_both_price_domains_and_verifies_each_replay(protocol, tmp_path):
    config = _config()
    protocol["model"]["resolved_config_sha256"] = digest_json(config)
    protocol["randomness"]["seeds"] = [1, 2]
    protocol["operations"]["max_wall_seconds"] = 120
    spec = StudySpec.model_validate(protocol)
    result = run_study(spec, config, input_root=tmp_path,
                       data_root=tmp_path / "data", out_dir=tmp_path / "out")
    assert len(result["results"]) == 4
    assert result["operations"]["stop_reason"] is None
    assert result["summary"]["coverage"]["base"]["eligible"] == 2, result["results"]
    assert result["summary"]["coverage"]["cost"]["eligible"] == 2, result["results"]
    assert set(result["summary"]["metrics"]) == {"posted_index", "equity_price"}
    assert result["summary"]["analysis_kind"] == "model_conditional_exploratory"
    for row in result["results"]:
        assert verify_attempt(row, expected_ticks=3) == []
        assert set(row["outcome_observations"]) == {"posted_index", "equity_price"}
    altered = copy.deepcopy(result["results"][0])
    altered["outcome_observations"]["equity_price"]["outcome"]["currency"] = "CAD"
    assert "source_receipt_mismatch" in verify_attempt(altered, expected_ticks=3)
    assert Path(result["artifacts"]["json"]).is_file()
    assert "Usable pairs" in Path(result["artifacts"]["markdown"]).read_text(encoding="utf-8")
    assert result["operations"]["provider_spend_usd"] == 0


def test_budget_exhaustion_retains_assignments_and_null_effects(protocol, tmp_path):
    config = _config()
    protocol["model"]["resolved_config_sha256"] = digest_json(config)
    # Allow the declared context snapshot, but leave no room for manifests or
    # execution. A one-byte budget fails earlier during snapshot preflight.
    description = Path(__file__).resolve().parents[1] / "docs/research/model-description.md"
    protocol["operations"]["max_disk_bytes"] = description.stat().st_size
    result = run_study(StudySpec.model_validate(protocol), config, input_root=tmp_path,
                       data_root=tmp_path / "data", out_dir=tmp_path / "out")
    assert len(result["results"]) == 6
    assert all(row["execution_status"] == "planned" for row in result["results"])
    assert result["summary"]["coverage"]["base"] == {
        "assigned": 3, "started": 0, "completed": 0, "eligible": 0}
    effect = result["summary"]["metrics"]["equity_price"]["cost"]["paired_effect"]
    assert effect["mean_difference"] is None and effect["ci95_bootstrap"] is None
    assert result["operations"]["stop_reason"] == "disk_budget_exhausted"
    assert Path(result["batch"]["data_dir"], "manifest.json").is_file()
    assert not list(Path(result["batch"]["data_dir"]).rglob("*.db"))


def test_context_over_budget_is_rejected_before_publishing_a_batch(protocol, tmp_path):
    config = _config()
    protocol["model"]["resolved_config_sha256"] = digest_json(config)
    protocol["operations"]["max_disk_bytes"] = 1
    with pytest.raises(ValueError, match="snapshot size limit"):
        run_study(StudySpec.model_validate(protocol), config, input_root=tmp_path,
                  data_root=tmp_path / "data", out_dir=tmp_path / "out")
    assert not (tmp_path / "data").exists()
    assert not (tmp_path / "out").exists()


def test_worker_wall_limit_preserves_partial_artifacts_and_stops_later_cells(protocol, tmp_path):
    config = _config()
    protocol["model"]["resolved_config_sha256"] = digest_json(config)
    protocol["operations"]["max_wall_seconds"] = 1
    protocol["time"].update(horizon=10000, measurement_end=10000)
    result = run_study(StudySpec.model_validate(protocol), config, input_root=tmp_path,
                       data_root=tmp_path / "data", out_dir=tmp_path / "out")
    assert result["operations"]["stop_reason"] == "wall_time_budget_exhausted"
    assert all(row["eligibility"]["status"] == "ineligible" for row in result["results"])
    assert all(row["execution_status"] == "planned" for row in result["results"][1:])
    assert not list(Path(result["batch"]["data_dir"]).rglob("replay-receipt.json"))


def test_unsupported_execution_is_rejected_before_creating_a_batch(protocol, tmp_path):
    config = _config()
    protocol["model"]["resolved_config_sha256"] = digest_json(config)
    spec = StudySpec.model_validate(protocol)
    for change in [{"default_route": {"provider": "other", "model": "live"}},
                   {"providers": {"other": {"kind": "cli"}}},
                   {"routes": {"founder": {"provider": "other", "model": "live"}}}]:
        invalid = copy.deepcopy(config)
        invalid["llm"].update(change)
        with pytest.raises(ValueError, match="provider|route"):
            run_study(spec, invalid, input_root=tmp_path,
                       data_root=tmp_path / "data", out_dir=tmp_path / "out")
    assert not (tmp_path / "data").exists()
    protocol["operations"]["concurrency"] = 2
    with pytest.raises(ValueError, match="one attempt"):
        validate_execution(StudySpec.model_validate(protocol), config)


def test_outcome_window_and_currency_are_enforced_without_changing_source(protocol, economy):
    spec_data = copy.deepcopy(protocol)
    spec_data["domains"] = ["goods"]
    spec_data["analysis"]["outcomes"] = [{"key": "sales", "metric": "gdp_proxy",
        "metric_version": "final-goods-flow-v3", "aggregation": "window_sum",
        "currency": "USD", "purpose": "primary"}]
    spec = StudySpec.model_validate(spec_data)
    store = economy.store
    store.set_meta(tick=3, config_json=json.dumps({"engine_semantics_version": 7}))
    store.record_metric(1, "gdp_proxy", 20)
    store.record_metric(3, "gdp_proxy", 10)
    before = store.conn.total_changes
    missing = collect_outcomes(store, spec)
    assert missing["metrics"]["sales"] is None
    assert missing["outcome_observations"]["sales"]["available_points"] == 2
    assert store.conn.total_changes == before
    store.record_metric(2, "gdp_proxy", 5)
    assert collect_outcomes(store, spec)["metrics"]["sales"] == 35
    spec_data["analysis"]["outcomes"][0]["currency"] = "CAD"
    assert collect_outcomes(store, StudySpec.model_validate(spec_data))["metrics"]["sales"] is None


def test_validation_verifies_configuration_without_publishing(protocol, tmp_path):
    config = {"engine_semantics_version": 7}
    before = {path: file_sha256(path) for path in tmp_path.rglob("*") if path.is_file()}
    validate_study_inputs(StudySpec.model_validate(protocol), config, input_root=tmp_path)
    assert before == {path: file_sha256(path) for path in tmp_path.rglob("*") if path.is_file()}


def test_period_vwap_weights_executions_and_keeps_no_trade_days(protocol, economy):
    bank = make_bank(economy)
    seller, _ = make_agent(economy, bank, "Seller", 0)
    buyer, _ = make_agent(economy, bank, "Buyer", 100_000)
    firm = economy.firms.found_firm(0, seller, "Fixture", "retail")
    economy.store.update("firms", firm, inventory=20)
    economy.store.set_meta(tick=3)
    economy.firms.set_price(1, firm, 200)
    economy.firms.buy_goods(1, buyer, firm, 1)
    economy.firms.set_price(3, firm, 400)
    economy.firms.buy_goods(3, buyer, firm, 3)
    protocol["domains"] = ["goods"]
    protocol["analysis"]["outcomes"] = [{"key": "goods_price", "metric": f"goods_vwap:{firm}",
        "metric_version": "goods-sales-vwap-v1", "aggregation": "window_vwap",
        "currency": "USD", "purpose": "primary"}]
    measured = collect_outcomes(economy.store, StudySpec.model_validate(protocol))
    assert measured["metrics"]["goods_price"] == 350
    point = measured["outcome_observations"]["goods_price"]["points"][0]
    assert point["quantity"] == 4 and point["notional_cents"] == 1400
    assert point["start_tick"] == 1 and point["tick"] == 3
    protocol["analysis"]["outcomes"][0]["metric"] = "goods_vwap:999"
    unavailable = collect_outcomes(economy.store, StudySpec.model_validate(protocol))
    assert unavailable["metrics"]["goods_price"] is None
    assert unavailable["outcome_observations"]["goods_price"]["points"][0]["reason"] == "instrument_or_committed_window_unavailable"
