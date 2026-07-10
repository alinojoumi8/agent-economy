"""Order-book matching against known fixtures (PRD R4)."""
from tests.conftest import make_bank, make_agent


def _listed_firm(economy, founder_id, shares=1000):
    firm_id = economy.firms.found_firm(0, founder_id, "TestCo", "tech", opening_capital_cents=0)
    economy.store.update("firms", firm_id, status="listed")
    return firm_id


def test_price_time_priority_and_partial_fills(economy):
    bank = make_bank(economy)
    seller, _ = make_agent(economy, bank, "Seller", 0)
    b1, _ = make_agent(economy, bank, "Buyer1", 100_000_00)
    b2, _ = make_agent(economy, bank, "Buyer2", 100_000_00)
    firm = _listed_firm(economy, seller)

    # Seller offers 10 @ 100.00; buyer1 bids 6 @ 101.00 (earlier), buyer2 bids 6 @ 102.00 (later, better price)
    economy.exchange.place_order(1, seller, firm, "sell", 10, 100_00)
    economy.exchange.place_order(1, b1, firm, "buy", 6, 101_00)
    economy.exchange.place_order(1, b2, firm, "buy", 6, 102_00)
    fills = economy.exchange.match_firm(1, firm)

    assert sum(f.qty for f in fills) == 10
    # Better-priced buyer2 fills first; resting sell sets the trade price (100.00).
    assert fills[0].buyer_id == b2 and fills[0].qty == 6
    assert fills[0].price_cents == 100_00
    assert fills[1].buyer_id == b1 and fills[1].qty == 4
    assert economy.exchange.shares_held(firm, "agent", b2) == 6
    assert economy.exchange.shares_held(firm, "agent", b1) == 4
    ok, _ = economy.ledger.reconcile()
    assert ok


def test_engine_never_sets_price_without_orders(economy):
    bank = make_bank(economy)
    founder, _ = make_agent(economy, bank, "F", 0)
    firm = _listed_firm(economy, founder)
    fills = economy.exchange.match_firm(1, firm)
    assert fills == []
    assert economy.store.query("SELECT * FROM trades") == []


def test_cannot_sell_shares_you_dont_own(economy):
    bank = make_bank(economy)
    founder, _ = make_agent(economy, bank, "F", 0)
    stranger, _ = make_agent(economy, bank, "S", 10_000_00)
    firm = _listed_firm(economy, founder)
    from engine.actions import ActionExecutor
    ex = ActionExecutor(economy)
    res = ex.execute_action(1, stranger, {"type": "place_order", "firm_id": firm,
                                          "side": "sell", "qty": 5, "limit_price": 100_00})
    assert not res["ok"] and "insufficient shares" in res["reason"]
