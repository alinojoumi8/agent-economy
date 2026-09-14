import json

import pytest

from research.metric_registry import metric_definition, read_metric_observation
from tests.conftest import make_agent, make_bank


def test_legacy_metric_versions_cannot_be_relabelled(store):
    store.record_metric(0, "gdp_proxy", 1500)
    result = read_metric_observation(store, "gdp_proxy", 0)
    assert result["reason"] == "incompatible_metric_semantics"
    assert result["value"] is None
    assert store.metric_latest("gdp_proxy") == 1500


def test_macro_observation_requires_exact_tick_and_known_single_currency(economy):
    store = economy.store
    store.set_meta(tick=3, config_json=json.dumps({"engine_semantics_version": 7}))
    store.record_metric(2, "gdp_proxy", 42)
    assert read_metric_observation(store, "gdp_proxy", 2)["value"] == 42
    assert read_metric_observation(store, "gdp_proxy", 3)["reason"] == "not_recorded_at_tick"
    economy.ledger.create_account("system", None, "external", currency_code="CAD")
    result = read_metric_observation(store, "gdp_proxy", 2)
    assert result["value"] is None
    assert result["reason"] == "multiple_or_unknown_currencies_without_conversion"
    assert store.metric_latest("gdp_proxy") == 42


def test_share_price_requires_execution_and_reports_age(economy):
    bank = make_bank(economy)
    seller, _ = make_agent(economy, bank, "Seller", 0)
    buyer, _ = make_agent(economy, bank, "Buyer", 100_000)
    firm = economy.firms.found_firm(0, seller, "Listed firm", "tech", opening_capital_cents=0)
    economy.store.update("firms", firm, status="listed")
    economy.store.set_meta(tick=3)
    name = f"stock:{firm}"
    economy.exchange.place_order(1, seller, firm, "sell", 10, 1200)
    assert read_metric_observation(economy.store, name, 1)["reason"] == "no_execution"
    economy.exchange.place_order(1, buyer, firm, "buy", 3, 1300)
    assert len(economy.exchange.match_firm(1, firm)) == 1
    before = economy.store.conn.total_changes
    observation = read_metric_observation(economy.store, name, 3)
    assert observation["value"] == 1200
    assert observation["observed_tick"] == 1 and observation["age_ticks"] == 2
    assert observation["currency"] == "USD"
    assert observation["definition"]["price_kind"] == "execution"
    assert economy.store.conn.total_changes == before
    assert economy.ledger.reconcile()[0]
    assert read_metric_observation(economy.store, name, 0)["reason"] == "no_execution"


def test_missing_future_unknown_and_nonfinite_values_are_explicit(store):
    store.set_meta(tick=2, config_json=json.dumps({"engine_semantics_version": 7}))
    assert read_metric_observation(store, "policy_rate", 3)["reason"] == "future_tick"
    assert read_metric_observation(store, "unknown_price", 1)["reason"] == "unregistered_metric"
    assert read_metric_observation(store, "policy_rate", 1)["reason"] == "not_recorded_at_tick"
    store.record_metric(1, "policy_rate", float("inf"))
    assert read_metric_observation(store, "policy_rate", 1)["reason"] == "nonfinite_value"


@pytest.mark.parametrize("tick", [-1, True, 1.5, "2"])
def test_invalid_ticks_do_not_become_observations(store, tick):
    with pytest.raises(ValueError):
        read_metric_observation(store, "cpi", tick)


def test_dynamic_instrument_keys_are_strict_and_price_types_differ():
    assert metric_definition("stock:1").price_kind == "execution"
    assert metric_definition("cpi").price_kind == "posted_index"
    assert metric_definition("stock:0") is None
    assert metric_definition("stock:1 OR 1=1") is None
