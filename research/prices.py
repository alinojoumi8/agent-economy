"""Read-only price discovery evidence, with explicit historical limitations.

Goods are comparable within one firm's product unit. This reader does not
combine unlike products or currencies, reconstruct unrecorded demand, or use
today's mutable book under a historical cursor.
"""
from __future__ import annotations

import math

from engine.store import Store, load_json

PRICE_CONTRACT_VERSION = "price-observations-v1"


def _observation(value=None, *, reason=None, observed_tick=None, tick=None,
                 evidence=(), kind="execution") -> dict:
    return {"value": value, "status": "available" if value is not None else "unavailable",
            "reason": reason, "kind": kind, "observed_tick": observed_tick,
            "age_ticks": tick - observed_tick if tick is not None and observed_tick is not None else None,
            "evidence": list(evidence)}


def _integer(value, *, minimum=0) -> bool:
    return type(value) is int and value >= minimum


def price_observations(store: Store, firm_id: int, *, tick: int,
                       start_tick: int | None = None, include_series: bool = False) -> dict:
    """Measure successful goods sales and distinct-owner equity executions."""
    start = tick if start_tick is None else start_tick
    if not _integer(firm_id, minimum=1) or not _integer(tick) or not _integer(start) or start > tick:
        raise ValueError("firm and window must be valid integer identities")
    if include_series and tick - start >= 90:
        raise ValueError("interactive price series is limited to 90 ticks")
    meta = store.get_meta()
    if tick > int(meta["tick"]):
        raise ValueError("price window extends beyond the recorded world")
    if meta["active_tick"] is not None and tick >= int(meta["active_tick"]):
        raise ValueError("price window includes an uncommitted tick")
    firm = store.query_one("SELECT * FROM firms WHERE id=? AND founded_tick<=?", (firm_id, tick))
    if firm is None:
        raise ValueError("firm did not exist at this cursor")
    currency = str(firm["currency_code"] or "")
    if not currency:
        raise ValueError("instrument currency is unavailable")

    # Currency is a fixed instrument attribute in the current engine. Product
    # labels, inventory, quotes and order status are mutable and handled below.
    sales = store.query(
        "SELECT id,tick,payload_json FROM events WHERE kind='goods_sale' "
        "AND tick<=? AND json_valid(payload_json) "
        "AND json_extract(payload_json,'$.firm_id')=? ORDER BY tick,id", (tick, firm_id))
    quantity, notional, valid_sales, invalid_sales, last_sale = 0, 0, [], [], None
    daily_goods, daily_equities = {}, {}
    invalid_goods_ticks, invalid_equity_ticks = set(), set()
    for sale in sales:
        payload = load_json(sale["payload_json"], {})
        qty, price, total = (payload.get(key) for key in ("qty", "unit_price_cents", "total_cents"))
        if not (_integer(qty, minimum=1) and _integer(price, minimum=1)
                and _integer(total, minimum=1) and total == qty * price):
            if int(sale["tick"]) >= start:
                invalid_sales.append(int(sale["id"]))
                invalid_goods_ticks.add(int(sale["tick"]))
            continue
        last_sale = (sale, payload)
        if int(sale["tick"]) >= start:
            quantity += qty
            notional += total
            valid_sales.append(int(sale["id"]))
            if include_series:
                bucket = daily_goods.setdefault(int(sale["tick"]), [0, 0])
                bucket[0] += qty
                bucket[1] += total
    executed = _observation(notional / quantity if quantity else None,
        reason="invalid_sale_evidence" if invalid_sales else "no_execution_in_window" if not quantity else None,
        evidence=[{"type": "event", "id": item} for item in valid_sales], kind="volume_weighted_execution")
    if invalid_sales:
        # A partial sum could misrepresent the requested complete window.
        executed = _observation(reason="invalid_sale_evidence", kind="volume_weighted_execution")
    last_goods = (_observation(last_sale[1]["unit_price_cents"],
        observed_tick=int(last_sale[0]["tick"]), tick=tick,
        evidence=[{"type": "event", "id": int(last_sale[0]["id"])}])
        if last_sale else _observation(reason="no_execution"))

    price_event = store.query_one(
        "SELECT id,tick,payload_json FROM events WHERE kind='price_set' AND tick<=? "
        "AND json_valid(payload_json) AND json_extract(payload_json,'$.firm_id')=? "
        "ORDER BY tick DESC,id DESC LIMIT 1", (tick, firm_id))
    posted = _observation(reason="posted_price_not_recorded", kind="posted")
    if price_event:
        value = load_json(price_event["payload_json"], {}).get("new_cents")
        if _integer(value, minimum=1):
            posted = _observation(value, observed_tick=int(price_event["tick"]), tick=tick,
                evidence=[{"type": "event", "id": int(price_event["id"])}], kind="posted")
    elif tick == int(meta["tick"]) and meta["active_tick"] is None:
        # A present-state observation is allowed only at a committed boundary.
        value = load_json(firm["product_json"], {}).get("unit_price_cents")
        if _integer(value, minimum=1):
            posted = _observation(value, observed_tick=tick, tick=tick,
                evidence=[{"type": "current_firm_state", "id": firm_id}], kind="posted")

    trades = store.query(
        "SELECT id,tick,buyer_id,seller_id,qty,price_cents FROM trades "
        "WHERE firm_id=? AND tick<=? ORDER BY tick,id", (firm_id, tick))
    valid_trades, excluded_self, invalid_trades = [], [], []
    last_equity = None
    for trade in trades:
        in_window = int(trade["tick"]) >= start
        if trade["buyer_id"] == trade["seller_id"]:
            if in_window:
                excluded_self.append(int(trade["id"]))
            continue
        if not (_integer(trade["qty"], minimum=1) and _integer(trade["price_cents"], minimum=1)):
            if in_window:
                invalid_trades.append(int(trade["id"]))
                invalid_equity_ticks.add(int(trade["tick"]))
            continue
        last_equity = trade
        if in_window:
            valid_trades.append(trade)
            if include_series:
                bucket = daily_equities.setdefault(int(trade["tick"]), [0, 0])
                bucket[0] += int(trade["qty"])
                bucket[1] += int(trade["qty"]) * int(trade["price_cents"])
    equity_qty = sum(int(item["qty"]) for item in valid_trades)
    equity_notional = sum(int(item["qty"]) * int(item["price_cents"]) for item in valid_trades)
    equity_price = (_observation(int(last_equity["price_cents"]),
        observed_tick=int(last_equity["tick"]), tick=tick,
        evidence=[{"type": "trade", "id": int(last_equity["id"])}])
        if last_equity else _observation(reason="no_qualified_execution"))
    equity_vwap = _observation(
        equity_notional / equity_qty if equity_qty and not invalid_trades else None,
        reason="invalid_trade_evidence" if invalid_trades else "no_execution_in_window" if not equity_qty else None,
        evidence=[{"type": "trade", "id": int(item["id"])} for item in valid_trades],
        kind="volume_weighted_execution")

    book = {"status": "unavailable", "reason": "historical_book_state_not_recorded",
            "sampling": "current_committed_boundary", "best_bid_cents": None,
            "best_ask_cents": None, "spread_cents": None,
            "bid_quantity": None, "ask_quantity": None}
    if tick == int(meta["tick"]) and meta["active_tick"] is None:
        orders = store.query(
            "SELECT side,limit_price_cents,qty_remaining FROM orders WHERE firm_id=? "
            "AND tick<=? AND status IN ('open','partial') AND qty_remaining>0 "
            "AND limit_price_cents>0 ORDER BY seq", (firm_id, tick))
        buys = [row for row in orders if row["side"] == "buy"]
        sells = [row for row in orders if row["side"] == "sell"]
        bid = max((int(row["limit_price_cents"]) for row in buys), default=None)
        ask = min((int(row["limit_price_cents"]) for row in sells), default=None)
        book.update(status="available", reason=None, best_bid_cents=bid, best_ask_cents=ask,
            spread_cents=ask - bid if bid is not None and ask is not None else None,
            bid_quantity=sum(int(row["qty_remaining"]) for row in buys if row["limit_price_cents"] == bid),
            ask_quantity=sum(int(row["qty_remaining"]) for row in sells if row["limit_price_cents"] == ask))
    result = {
        "contract_version": PRICE_CONTRACT_VERSION,
        "firm_id": firm_id, "tick": tick, "start_tick": start, "currency": currency,
        "goods": {"unit": "currency_minor_units_per_firm_product_unit", "posted_price": posted,
                  "executed_price": executed, "last_execution": last_goods,
                  "quantity": quantity if not invalid_sales else None,
                  "notional_cents": notional if not invalid_sales else None,
                  "sale_count": len(valid_sales), "invalid_event_ids": invalid_sales,
                  "demand": {"status": "unavailable", "reason": "intended_and_unmet_demand_not_recorded"}},
        "equities": {"unit": "currency_minor_units_per_share", "last_execution": equity_price,
                     "executed_price": equity_vwap, "quantity": equity_qty if not invalid_trades else None,
                     "notional_cents": equity_notional if not invalid_trades else None,
                     "trade_count": len(valid_trades), "excluded_self_trade_ids": excluded_self,
                     "invalid_trade_ids": invalid_trades, "book": book},
        "limitations": ["Goods comparison is within a firm's product unit; no cross-product basket is inferred.",
                        "Equity evidence excludes identical buyer/seller IDs; broader beneficial ownership is not recorded.",
                        "Current book quantities are displayed orders, not reserved or guaranteed executable depth.",
                        "Daily observations do not measure intraday latency or identify causal effects."]}
    if include_series:
        points = []
        for day in range(start, tick + 1):
            goods_qty, goods_total = daily_goods.get(day, (0, 0))
            equity_volume, equity_total = daily_equities.get(day, (0, 0))
            points.append({"tick": day,
                "goods_vwap": goods_total / goods_qty if goods_qty and day not in invalid_goods_ticks else None,
                "goods_volume": goods_qty if day not in invalid_goods_ticks else None,
                "goods_reason": "invalid_sale_evidence" if day in invalid_goods_ticks else "no_execution" if not goods_qty else None,
                "equity_vwap": equity_total / equity_volume if equity_volume and day not in invalid_equity_ticks else None,
                "equity_volume": equity_volume if day not in invalid_equity_ticks else None,
                "equity_reason": "invalid_trade_evidence" if day in invalid_equity_ticks else "no_execution" if not equity_volume else None})
        result["series"] = {"contract": "daily-qualified-execution-v1", "sampling": "daily",
                            "currency": currency, "points": points, "missing_policy": "no_carry_forward"}
    return result


def fixed_basket_index(basket: list[dict], *, currency: str) -> dict:
    """Complete fixed-quantity basket; missing items never reweight survivors."""
    if not basket or not currency or len({item.get("key") for item in basket}) != len(basket):
        raise ValueError("basket requires unique items and an explicit currency")
    denominator, numerator, observed_weight, missing = 0.0, 0.0, 0.0, []
    for item in basket:
        if set(item) != {"key", "currency", "quantity", "base_price", "price"}:
            raise ValueError("basket item has an unknown or missing field")
        if not isinstance(item["key"], str) or not item["key"] or item["currency"] != currency:
            raise ValueError("basket must use one currency and named comparable items")
        for name in ("quantity", "base_price"):
            value = item[name]
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError("baseline quantities and prices must be finite and positive")
        weight = item["quantity"] * item["base_price"]
        denominator += weight
        price = item["price"]
        if price is None:
            missing.append(item["key"])
        elif type(price) not in (int, float) or not math.isfinite(price) or price <= 0:
            raise ValueError("current prices must be finite and positive or explicitly missing")
        else:
            numerator += item["quantity"] * price
            observed_weight += weight
    if denominator <= 0 or not all(math.isfinite(value) for value in (denominator, numerator, observed_weight)):
        raise ValueError("basket aggregate exceeds finite numeric range")
    result = None if missing else 100 * (numerator / denominator)
    if result is not None and not math.isfinite(result):
        raise ValueError("basket index exceeds finite numeric range")
    return {"value": result,
            "status": "insufficient_coverage" if missing else "available", "currency": currency,
            "observed_baseline_expenditure_share": observed_weight / denominator,
            "missing_items": missing, "contract": "fixed-quantity-complete-basket-v1"}
