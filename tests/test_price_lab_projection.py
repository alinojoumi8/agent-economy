import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from research.prices import price_observations
from server.projections.price_lab import build_price_lab
from server.v2_api import install_v2_routes
from tests.conftest import make_agent, make_bank


@pytest.fixture
def market(economy):
    bank = make_bank(economy)
    seller, _ = make_agent(economy, bank, "Seller", 0)
    buyer, _ = make_agent(economy, bank, "Buyer", 10_000)
    firm = economy.firms.found_firm(0, seller, "Measured firm", "goods")
    economy.store.update("firms", firm, inventory=8, status="listed")
    economy.firms.set_price(1, firm, 200)
    economy.firms.buy_goods(1, buyer, firm, 2)
    economy.firms.set_price(3, firm, 400)
    economy.firms.buy_goods(3, buyer, firm, 1)
    economy.exchange.place_order(2, seller, firm, "sell", 1, 700)
    economy.exchange.place_order(2, buyer, firm, "buy", 1, 800)
    economy.exchange.match_firm(2, firm)
    future = economy.firms.found_firm(4, seller, "FUTURE-PRICE-FIRM", "goods")
    economy.store.set_meta(tick=4, active_tick=None, status="paused")
    return economy, firm, future


def test_series_preserves_missing_days_units_and_future_boundaries(market):
    economy, firm, _ = market
    before = economy.store.conn.total_changes
    data = build_price_lab(economy.store, as_of_tick=2, firm_id=firm, window=30)
    assert "FUTURE-PRICE-FIRM" not in json.dumps(data)
    assert data["selected_firm"]["id"] == firm
    assert "account_id" not in data["selected_firm"]
    observation = data["observation"]
    assert observation["goods"]["posted_price"]["value"] == 200
    assert observation["goods"]["quantity"] == 2
    assert observation["equities"]["book"]["status"] == "unavailable"
    assert observation["series"]["points"] == [
        {"tick": 0, "goods_vwap": None, "goods_volume": 0, "goods_reason": "no_execution",
         "equity_vwap": None, "equity_volume": 0, "equity_reason": "no_execution"},
        {"tick": 1, "goods_vwap": 200, "goods_volume": 2, "goods_reason": None,
         "equity_vwap": None, "equity_volume": 0, "equity_reason": "no_execution"},
        {"tick": 2, "goods_vwap": None, "goods_volume": 0, "goods_reason": "no_execution",
         "equity_vwap": 700, "equity_volume": 1, "equity_reason": None}]
    assert economy.store.conn.total_changes == before
    assert price_observations(economy.store, firm, tick=4, start_tick=2, include_series=True)["series"]["points"][1]["goods_vwap"] == 400


def test_daily_invalid_measurement_does_not_bridge_or_pollute_other_days(market):
    economy, firm, _ = market
    economy.store.log_event(2, "goods_sale", {"firm_id": firm, "buyer_id": 2,
        "qty": 1, "unit_price_cents": 500, "total_cents": 1})
    data = build_price_lab(economy.store, as_of_tick=3, firm_id=firm)["observation"]
    assert data["goods"]["executed_price"]["value"] is None
    assert data["series"]["points"][1]["goods_vwap"] == 200
    assert data["series"]["points"][2]["goods_vwap"] is None
    assert data["series"]["points"][2]["goods_volume"] is None
    assert data["series"]["points"][2]["goods_reason"] == "invalid_sale_evidence"
    assert data["series"]["points"][3]["goods_vwap"] == 400


def test_price_projection_enforces_cursor_fork_identity_and_read_only_routes(market):
    economy, firm, future = market
    app = FastAPI()
    install_v2_routes(app, SimpleNamespace(store=economy.store, config=economy.config, economy=economy),
                      SimpleNamespace(hosted_safe=False))
    try:
        with TestClient(app) as client:
            before = economy.store.conn.total_changes
            response = client.get(f"/api/v2/workspaces/price-lab?tick=2&firm_id={firm}&window=7")
            assert response.status_code == 200, response.text
            envelope = response.json()
            assert envelope["projection"] == "workspace.price_lab"
            assert envelope["run_id"] == "test" and envelope["tick"] == 2
            assert envelope["data"]["observation"]["tick"] == 2
            assert client.get(f"/api/v2/workspaces/price-lab?tick=2&firm_id={future}").status_code == 404
            assert client.get("/api/v2/workspaces/price-lab?tick=5").status_code == 409
            assert client.get("/api/v2/workspaces/price-lab?fork_id=unrelated").status_code == 409
            assert client.get("/api/v2/workspaces/price-lab?firm_id=-1").status_code == 422
            assert client.get("/api/v2/workspaces/price-lab?window=91").status_code == 422
            assert client.post("/api/v2/workspaces/price-lab", json={}).status_code == 405
            assert economy.store.conn.total_changes == before
    finally:
        app.state.operator_workspace.close()


def test_empty_market_is_an_explicit_capability_state(economy):
    data = build_price_lab(economy.store, as_of_tick=0)
    assert data["observation"] is None and data["firms"] == []
    assert data["empty_reason"] == "no_firms_at_selected_tick"
