"""Stock exchange: a deterministic limit-order book with price-time priority.

The engine NEVER sets a price (PRD R4). Prices emerge only from orders agents
place. Matching is fully deterministic (sorted by price then submission seq), so
replay reproduces trades exactly. Cash settles through the ledger; shares move on
the cap table.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .ledger import Ledger, Leg
from .store import Store

MARKET_PRICE = None  # market orders carry NULL limit_price_cents


@dataclass
class Fill:
    firm_id: int
    buyer_id: int
    seller_id: int
    qty: int
    price_cents: int


class Exchange:
    def __init__(self, store: Store, ledger: Ledger,
                 circuit_breaker_drop: Optional[float] = None):
        self.store = store
        self.ledger = ledger
        # Optional circuit breaker (TECH-SPEC §9): halt a symbol for the rest of
        # the session once it falls this fraction below the previous close.
        self.circuit_breaker_drop = circuit_breaker_drop

    # ── cap table helpers ────────────────────────────────────────────────────
    def shares_held(self, firm_id: int, holder_type: str, holder_id: int) -> int:
        v = self.store.scalar(
            "SELECT qty FROM shares WHERE firm_id=? AND holder_type=? AND holder_id=?",
            (firm_id, holder_type, holder_id))
        return int(v) if v is not None else 0

    def _adjust_shares(self, firm_id: int, holder_type: str, holder_id: int, delta: int) -> None:
        row = self.store.query_one(
            "SELECT id, qty FROM shares WHERE firm_id=? AND holder_type=? AND holder_id=?",
            (firm_id, holder_type, holder_id))
        if row:
            new_qty = int(row["qty"]) + delta
            if new_qty == 0:
                self.store.execute("DELETE FROM shares WHERE id=?", (row["id"],))
            else:
                self.store.execute("UPDATE shares SET qty=? WHERE id=?", (new_qty, row["id"]))
        elif delta != 0:
            self.store.insert("shares", firm_id=firm_id, holder_type=holder_type,
                              holder_id=holder_id, qty=delta)

    def last_price(self, firm_id: int) -> Optional[int]:
        v = self.store.scalar(
            "SELECT price_cents FROM trades WHERE firm_id=? ORDER BY id DESC LIMIT 1", (firm_id,))
        if v is not None:
            return int(v)
        v = self.store.scalar("SELECT value FROM metrics WHERE name=? ORDER BY tick DESC LIMIT 1",
                              (f"stock:{firm_id}",))
        return int(v) if v is not None else None

    # ── order placement (called by the executor) ─────────────────────────────
    def place_order(self, tick: int, agent_id: int, firm_id: int, side: str,
                    qty: int, limit_price_cents: Optional[int], order_type: str = "limit") -> int:
        seq = int(self.store.scalar("SELECT COALESCE(MAX(seq),0)+1 FROM orders", default=1))
        return self.store.insert(
            "orders", tick=tick, agent_id=agent_id, firm_id=firm_id, side=side,
            order_type=order_type, qty=qty, qty_remaining=qty,
            limit_price_cents=limit_price_cents, seq=seq, status="open")

    # ── matching (MARKET phase) ──────────────────────────────────────────────
    def match_firm(self, tick: int, firm_id: int) -> list[Fill]:
        """Match the open book for one firm. Returns the fills produced."""
        fills: list[Fill] = []
        prev_close = self.last_price(firm_id)   # breaker reference: previous close
        firm_currency = str(self.store.scalar(
            "SELECT currency_code FROM firms WHERE id=?", (firm_id,), default="USD") or "USD")
        while True:
            buys = self.store.query(
                "SELECT * FROM orders WHERE firm_id=? AND side='buy' AND status IN ('open','partial') "
                "AND qty_remaining > 0", (firm_id,))
            sells = self.store.query(
                "SELECT * FROM orders WHERE firm_id=? AND side='sell' AND status IN ('open','partial') "
                "AND qty_remaining > 0", (firm_id,))
            if not buys or not sells:
                break

            # Price-time priority. Market orders sort most aggressive.
            def buy_key(o):
                price = o["limit_price_cents"]
                return (-(price if price is not None else 10**15), o["seq"])

            def sell_key(o):
                price = o["limit_price_cents"]
                return ((price if price is not None else 0), o["seq"])

            best_buy = sorted(buys, key=buy_key)[0]
            best_sell = sorted(sells, key=sell_key)[0]

            bp = best_buy["limit_price_cents"]
            sp = best_sell["limit_price_cents"]
            # Do the two orders cross?
            crosses = (bp is None or sp is None or bp >= sp)
            if not crosses:
                break

            # Trade price = the resting (earlier) order's limit; market orders take
            # the counterparty's price. Two market orders may use a prior close,
            # but the engine never invents an initial reference price.
            if best_buy["seq"] < best_sell["seq"]:
                resting, aggressor = best_buy, best_sell
            else:
                resting, aggressor = best_sell, best_buy
            price = resting["limit_price_cents"]
            if price is None:
                price = aggressor["limit_price_cents"]
            if price is None:
                price = self.last_price(firm_id)
            if price is None:
                # No agent has expressed a price yet. Leave both orders on the book
                # for a priced counterparty; expire_session closes them later.
                break
            price = int(price)
            if price <= 0:
                # cannot trade at non-positive price; drop the offending market order
                self._expire_order(best_sell["id"] if sp is None else best_buy["id"])
                continue

            fill_qty = min(int(best_buy["qty_remaining"]), int(best_sell["qty_remaining"]))
            buyer_id = int(best_buy["agent_id"])
            seller_id = int(best_sell["agent_id"])

            # Re-validate resources at match time (limit orders may rest across ticks).
            seller_shares = self.shares_held(firm_id, "agent", seller_id)
            if seller_shares < fill_qty:
                fill_qty = seller_shares
            buyer_acct = self.ledger.agent_checking_id(buyer_id)
            if buyer_acct is None:
                self._cancel_order(best_buy["id"]); continue
            seller_acct = self.ledger.agent_checking_id(seller_id)
            buyer_currency = str(self.store.scalar(
                "SELECT currency_code FROM accounts WHERE id=?", (buyer_acct,),
                default="") or "")
            seller_currency = str(self.store.scalar(
                "SELECT currency_code FROM accounts WHERE id=?", (seller_acct,),
                default="") or "") if seller_acct is not None else ""
            currency_mismatch = False
            if buyer_currency != firm_currency:
                self._cancel_order(best_buy["id"])
                currency_mismatch = True
            if seller_currency != firm_currency:
                self._cancel_order(best_sell["id"])
                currency_mismatch = True
            if currency_mismatch:
                continue
            affordable = self.ledger.balance(buyer_acct) // price
            if affordable < fill_qty:
                fill_qty = max(0, affordable)

            if fill_qty <= 0:
                # Whichever side can't perform gets cancelled so the loop can progress.
                if seller_shares <= 0:
                    self._cancel_order(best_sell["id"])
                else:
                    self._cancel_order(best_buy["id"])
                continue

            self._settle(tick, firm_id, best_buy, best_sell, buyer_id, seller_id, fill_qty, price)
            fills.append(Fill(firm_id, buyer_id, seller_id, fill_qty, price))

            # Circuit breaker: a fill at/below the halt threshold stops the
            # symbol for the remainder of the session (unmatched orders simply
            # expire at session close).
            if (self.circuit_breaker_drop and prev_close
                    and price <= prev_close * (1.0 - self.circuit_breaker_drop)):
                self.store.log_event(tick, "circuit_breaker", {
                    "firm_id": firm_id, "halt_price_cents": price,
                    "prev_close_cents": prev_close,
                    "drop": round(1.0 - price / prev_close, 4)}, phase="MARKET",
                    subject_type="firm", subject_id=firm_id, importance=3.5)
                break

        return fills

    def _settle(self, tick, firm_id, buy, sell, buyer_id, seller_id, qty, price) -> None:
        cost = qty * price
        buyer_acct = self.ledger.agent_checking_id(buyer_id)
        seller_acct = self.ledger.agent_checking_id(seller_id)
        self.ledger.transfer(tick, buyer_acct, seller_acct, cost, kind="equity_trade",
                             memo=f"buy {qty} shares of firm {firm_id} @ {price}")
        self._adjust_shares(firm_id, "agent", seller_id, -qty)
        self._adjust_shares(firm_id, "agent", buyer_id, +qty)

        self.store.insert("trades", tick=tick, firm_id=firm_id, buy_order_id=buy["id"],
                          sell_order_id=sell["id"], buyer_id=buyer_id, seller_id=seller_id,
                          qty=qty, price_cents=price)
        for o in (buy, sell):
            rem = int(o["qty_remaining"]) - qty
            self.store.execute(
                "UPDATE orders SET qty_remaining=?, status=? WHERE id=?",
                (rem, "filled" if rem == 0 else "partial", o["id"]))
        self.store.record_metric(tick, f"stock:{firm_id}", price)
        self.store.log_event(tick, "trade", {
            "firm_id": firm_id, "buyer": buyer_id, "seller": seller_id,
            "qty": qty, "price_cents": price}, phase="MARKET",
            subject_type="firm", subject_id=firm_id, importance=1.5)

    def _cancel_order(self, order_id: int) -> None:
        self.store.execute("UPDATE orders SET status='cancelled' WHERE id=?", (order_id,))

    def _expire_order(self, order_id: int) -> None:
        self.store.execute("UPDATE orders SET status='expired' WHERE id=?", (order_id,))

    def expire_session(self, tick: int) -> None:
        """Orders live for one session (TECH-SPEC §9)."""
        self.store.execute(
            "UPDATE orders SET status='expired' WHERE status IN ('open','partial')")

    # ── index (float-weighted) ───────────────────────────────────────────────
    def compute_index(self, tick: int, base_divisor: Optional[float] = None) -> Optional[float]:
        firms = self.store.query(
            "SELECT id, shares_outstanding FROM firms WHERE status='listed'")
        total = 0.0
        weight = 0.0
        for f in firms:
            price = self.last_price(int(f["id"]))
            if price is None:
                continue
            so = int(f["shares_outstanding"]) or 1
            total += price * so
            weight += so
        if weight == 0:
            return None
        # Market-cap weighted average price (in cents), scaled to an index near 100.
        avg = total / weight
        divisor = base_divisor or self.store.scalar(
            "SELECT value FROM metrics WHERE name='index_divisor' ORDER BY tick DESC LIMIT 1")
        if divisor is None:
            divisor = avg / 100.0 if avg else 1.0
            self.store.record_metric(tick, "index_divisor", divisor)
        return avg / divisor if divisor else None
