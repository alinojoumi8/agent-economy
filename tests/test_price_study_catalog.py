import pytest

from research.price_catalog import draft_price_study, price_study_catalog
from research.studies import validate_study_inputs
from research.study_runner import _arm_config
from run_config import load_config


def test_goods_and_equities_have_equal_catalog_and_outcome_support():
    catalog = price_study_catalog()
    assert [item["domain"] for item in catalog["presets"]] == ["goods", "equities"]
    config = load_config("runs/price-lab-pilot.yaml")
    for preset, primary in [("G2", "goods_price"), ("F2", "equity_price")]:
        spec = draft_price_study(config, preset, seeds=[1, 2], horizon=8, intervention_tick=3)
        assert spec.domains == ["goods", "equities"]
        assert [item.key for item in spec.analysis.outcomes if item.purpose == "primary"] == [primary]
        assert len(spec.analysis.outcomes) == 4
        assert spec.analysis.outcomes[0].metric == "goods_vwap:2"
        assert spec.analysis.outcomes[0].aggregation == "window_vwap"
        assert spec.analysis.outcomes[2].metric == "equity_price:1"
        assert spec.operations.max_spend_usd == 0 and spec.operations.max_provider_calls == 0
        assert _arm_config(spec, config, "control")["shocks"] == []
        treatment = _arm_config(spec, config, spec.arms[1].key)["shocks"]
        assert treatment[0]["trigger_params"] == {"tick": 3}
        assert treatment[0]["kind"] == ("oil" if preset == "G2" else "scandal")
        validate_study_inputs(spec, config, input_root=".")


def test_catalog_does_not_silently_change_bad_horizons_or_live_routes():
    config = load_config("runs/price-lab-pilot.yaml")
    for kwargs in [{"horizon": 2}, {"seeds": [1, 1]}, {"goods_firm_id": -1}, {"equity_firm_id": -1}]:
        options = {"seeds": [1, 2], "horizon": 8, "intervention_tick": 3, **kwargs}
        with pytest.raises(ValueError):
            draft_price_study(config, "G2", **options)
    config["llm"]["default_route"] = {"provider": "external", "model": "live"}
    with pytest.raises(ValueError, match="scripted"):
        draft_price_study(config, "F2", seeds=[1, 2], horizon=8, intervention_tick=3)
