import json

import pytest

from research.prices import fixed_basket_index, price_observations
from research.metric_registry import read_metric_observation
from tests.conftest import make_agent, make_bank


@pytest.fixture
def market(economy):
    bank = make_bank(economy)
    seller, _ = make_agent(economy, bank, "Seller", 0)
    buyer, _ = make_agent(economy, bank, "Buyer", 100_000)
    firm = economy.firms.found_firm(0, seller, "Market fixture", "grocery")
    economy.store.update("firms", firm, inventory=20, status="listed")
    economy.store.set_meta(tick=3)
    return economy, firm, seller, buyer


def test_goods_price_is_reconstructed_from_sales_without_inventing_demand(market):
    economy, firm, _, buyer = market
    economy.firms.set_price(1, firm, 200)
    assert economy.firms.buy_goods(1, buyer, firm, 2)["ok"]
    economy.firms.set_price(2, firm, 300)
    assert economy.firms.buy_goods(2, buyer, firm, 4)["ok"]
    before = economy.store.conn.total_changes
    data = price_observations(economy.store, firm, tick=3, start_tick=1)
    assert data["goods"]["executed_price"]["value"] == pytest.approx(1600 / 6)
    assert data["goods"]["quantity"] == 6
    assert data["goods"]["notional_cents"] == 1600
    assert len(data["goods"]["executed_price"]["evidence"]) == 2
    assert data["goods"]["last_execution"]["age_ticks"] == 1
    assert data["goods"]["demand"]["status"] == "unavailable"
    assert economy.store.conn.total_changes == before
    assert economy.ledger.reconcile()[0]
    registered = read_metric_observation(economy.store, f"goods_vwap:{firm}", 2)
    assert registered["value"] == 300
    assert registered["definition"]["version"] == "goods-sales-vwap-v1"
    assert read_metric_observation(economy.store, f"goods_volume:{firm}", 1)["value"] == 2
    historical = price_observations(economy.store, firm, tick=1)
    assert historical["goods"]["posted_price"]["value"] == 200
    assert historical["goods"]["executed_price"]["value"] == 200
    assert historical["goods"]["quantity"] == 2
    assert historical["equities"]["book"]["reason"] == "historical_book_state_not_recorded"


def test_quotes_no_trades_and_mutable_historical_state_remain_distinct(market):
    economy, firm, seller, buyer = market
    economy.exchange.place_order(3, buyer, firm, "buy", 2, 800)
    economy.exchange.place_order(3, seller, firm, "sell", 5, 1200)
    assert economy.exchange.match_firm(3, firm) == []
    current = price_observations(economy.store, firm, tick=3)
    assert current["goods"]["posted_price"]["status"] == "available"
    assert current["goods"]["executed_price"]["value"] is None
    assert current["equities"]["last_execution"]["value"] is None
    assert current["equities"]["book"]["spread_cents"] == 400
    assert current["equities"]["book"]["bid_quantity"] == 2
    assert current["equities"]["book"]["ask_quantity"] == 5
    old = price_observations(economy.store, firm, tick=1)
    assert old["goods"]["posted_price"]["value"] is None
    assert old["equities"]["book"]["spread_cents"] is None
    assert old["equities"]["book"]["bid_quantity"] is None


def test_equity_volume_price_age_and_same_owner_exclusions(market):
    economy, firm, seller, buyer = market
    sell_order = economy.exchange.place_order(1, seller, firm, "sell", 10, 1200)
    buy_order = economy.exchange.place_order(1, buyer, firm, "buy", 3, 1300)
    economy.exchange.match_firm(1, firm)
    economy.store.insert("trades", tick=2, firm_id=firm, buy_order_id=buy_order,
        sell_order_id=sell_order, buyer_id=buyer, seller_id=buyer, qty=100, price_cents=5000)
    result = price_observations(economy.store, firm, tick=3, start_tick=1)["equities"]
    assert result["last_execution"]["value"] == 1200
    assert result["last_execution"]["age_ticks"] == 2
    assert result["quantity"] == 3
    assert result["notional_cents"] == 3600
    assert len(result["excluded_self_trade_ids"]) == 1
    assert result["trade_count"] == 1
    assert read_metric_observation(economy.store, f"equity_price:{firm}", 3)["value"] == 1200
    assert read_metric_observation(economy.store, f"equity_vwap:{firm}", 1)["value"] == 1200
    assert read_metric_observation(economy.store, f"equity_volume:{firm}", 2)["value"] == 0
    assert economy.ledger.reconcile()[0]


def test_invalid_sale_evidence_does_not_become_a_partial_window_estimate(market):
    economy, firm, _, buyer = market
    economy.firms.set_price(1, firm, 200)
    economy.firms.buy_goods(1, buyer, firm, 2)
    economy.store.log_event(2, "goods_sale", {"firm_id": firm, "buyer_id": buyer,
        "qty": 2, "unit_price_cents": 200, "total_cents": 1}, phase="MARKET")
    result = price_observations(economy.store, firm, tick=3, start_tick=1)["goods"]
    assert result["executed_price"]["value"] is None
    assert result["executed_price"]["reason"] == "invalid_sale_evidence"
    assert result["quantity"] is None and result["notional_cents"] is None
    assert len(result["invalid_event_ids"]) == 1


@pytest.mark.parametrize("kwargs", [
    {"tick": 4}, {"tick": True}, {"tick": 1.5}, {"tick": -1},
    {"tick": 2, "start_tick": 3}, {"tick": 2, "start_tick": "1"}])
def test_price_window_rejects_invalid_or_future_cursors(market, kwargs):
    economy, firm, _, _ = market
    with pytest.raises(ValueError):
        price_observations(economy.store, firm, **kwargs)


def test_uncommitted_prices_and_future_firms_are_unavailable(market):
    economy, firm, _, _ = market
    economy.store.set_meta(active_tick=3)
    with pytest.raises(ValueError, match="uncommitted"):
        price_observations(economy.store, firm, tick=3)
    economy.store.update("firms", firm, founded_tick=2)
    with pytest.raises(ValueError, match="did not exist"):
        price_observations(economy.store, firm, tick=1)


def test_fixed_basket_retains_missing_members_and_currency_units():
    basket = [
        {"key": "grain", "currency": "USD", "quantity": 2, "base_price": 100, "price": 150},
        {"key": "tools", "currency": "USD", "quantity": 1, "base_price": 200, "price": 300}]
    result = fixed_basket_index(basket, currency="USD")
    assert result["value"] == 150
    basket[1]["price"] = None
    missing = fixed_basket_index(basket, currency="USD")
    assert missing["value"] is None
    assert missing["observed_baseline_expenditure_share"] == .5
    assert missing["missing_items"] == ["tools"]
    basket[1]["currency"] = "CAD"
    with pytest.raises(ValueError, match="one currency"):
        fixed_basket_index(basket, currency="USD")
    basket[1]["currency"] = "USD"
    basket[1]["price"] = float("nan")
    with pytest.raises(ValueError, match="finite"):
        fixed_basket_index(basket, currency="USD")


def test_fixed_basket_change_of_money_unit_does_not_change_index():
    basket = [{"key": "grain", "currency": "USD", "quantity": 3,
               "base_price": 250, "price": 200}]
    cents = fixed_basket_index(basket, currency="USD")["value"]
    scaled = json.loads(json.dumps(basket))
    scaled[0]["base_price"] /= 100
    scaled[0]["price"] /= 100
    assert fixed_basket_index(scaled, currency="USD")["value"] == cents == 80
