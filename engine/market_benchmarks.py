"""Bounded, endowed market fixtures that settle through the production engines.

These isolated markets do not run the daily World scheduler. Values and costs
are experimental reservation values, not estimated values of real firms.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json

from engine.exchange import Exchange
from engine.firms import Firms
from engine.ledger import Ledger
from engine.store import Store


POLICIES = ("value_bound_v1", "seeded_noise_v1", "adaptive_margin_v1")
FIXTURE_VERSION = "endowed-unit-market-v1"


@dataclass(frozen=True)
class MarketCase:
    key: str
    domain: str
    buyer_values: tuple[int, ...]
    seller_costs: tuple[int, ...]
    redemption_cents: int | None = None

    def __post_init__(self) -> None:
        if self.domain not in {"goods", "equities"}:
            raise ValueError("unknown market domain")
        if any(not 1 <= len(values) <= 32 for values in (self.buyer_values, self.seller_costs)):
            raise ValueError("a fixture requires 1..32 buyers and sellers")
        if any(type(v) is not int or not 1 <= v <= 1_000_000
               for v in (*self.buyer_values, *self.seller_costs)):
            raise ValueError("reservation values must be positive integer cents")
        if self.domain == "equities":
            if type(self.redemption_cents) is not int or not 1 <= self.redemption_cents <= 1_000_000:
                raise ValueError("equity fixtures require funded positive redemption")
        elif self.redemption_cents is not None:
            raise ValueError("goods have no cash redemption")


CASES = {
    "G1": MarketCase("G1", "goods", (120, 100, 80, 60), (20, 40, 90, 130)),
    "F1": MarketCase("F1", "equities", (120, 110, 90, 80), (80, 90, 110, 120), 100),
}


def _draw(seed: int, case: str, session: int, actor: str, purpose: str) -> int:
    # Stable independent keys: one actor's activity never consumes another's draw.
    key = json.dumps([FIXTURE_VERSION, seed, case, session, actor, purpose], separators=(",", ":"))
    return int.from_bytes(hashlib.sha256(key.encode()).digest(), "big")


def policy_quote(policy: str, *, side: str, reservation: int,
                 unfilled_sessions: int, draw: int) -> int:
    """Private information is limited to this actor's reservation and failures."""
    if policy not in POLICIES or side not in {"buy", "sell"}:
        raise ValueError("unsupported policy or side")
    if policy == "value_bound_v1":
        return reservation
    if policy == "seeded_noise_v1":
        return 1 + draw % reservation if side == "buy" else reservation + draw % 101
    margin = max(0, 30 - 10 * unfilled_sessions)
    return max(1, reservation - margin) if side == "buy" else reservation + margin


class MarketFixture:
    """One unit per buyer/seller; no borrowing, resale, fees, production or LLMs."""

    def __init__(self, store: Store, case: MarketCase):
        self.store, self.case = store, case
        self.ledger = Ledger(store)
        self.firms = Firms(store, self.ledger, engine_semantics_version=14)
        self.exchange = Exchange(store, self.ledger)
        self.buyers = [self._person(f"buyer-{i}", value)
                       for i, value in enumerate(case.buyer_values)]
        self.sellers = [self._person(f"seller-{i}", 0)
                        for i in range(len(case.seller_costs))]
        self.fulfilled: set[int] = set()
        self.remaining = set(range(len(self.sellers)))
        self.firm_ids: list[int] = []
        if case.domain == "goods":
            for i, (seller, cost) in enumerate(zip(self.sellers, case.seller_costs)):
                firm = self.firms.found_firm(0, seller, f"Endowed seller {i}", "benchmark",
                    product={"product": "homogeneous_unit", "unit_price_cents": cost})
                store.update("firms", firm, inventory=1)
                store.log_event(0, "benchmark_inventory_endowment", {"firm_id": firm, "qty": 1})
                self.firm_ids.append(firm)
            self.redemption_account = None
        else:
            firm = self.firms.found_firm(0, self.sellers[0], "Redeemable unit", "benchmark",
                                       shares=len(self.sellers))
            store.update("firms", firm, status="listed")
            for seller in self.sellers[1:]:
                self.exchange._adjust_shares(firm, "agent", self.sellers[0], -1)
                self.exchange._adjust_shares(firm, "agent", seller, 1)
            self.firm_ids = [firm]
            self.redemption_account = self.ledger.create_account(
                "firm", firm, "benchmark_redemption", label="benchmark:redemption",
                opening_cents=len(self.sellers) * int(case.redemption_cents))
            store.log_event(0, "benchmark_share_endowment", {
                "firm_id": firm, "sellers": self.sellers, "shares_each": 1,
                "redemption_cents": case.redemption_cents,
                "funded_cents": len(self.sellers) * int(case.redemption_cents)})
        store.log_event(0, "benchmark_contract", {"version": FIXTURE_VERSION, "case": asdict(case)})

    def _person(self, name: str, cash: int) -> int:
        person = self.store.insert("agents", name=name, kind="citizen", occupation="benchmark",
                                   age=35, alive=1)
        account = self.ledger.create_account("agent", person, "checking", label=name,
                                             opening_cents=cash)
        self.store.update("agents", person, checking_account_id=account)
        return person

    def _order(self, indices: list[int], seed: int, session: int, side: str,
               arrival: str) -> list[int]:
        if arrival == "value_order":
            reservations = self.case.buyer_values if side == "buy" else self.case.seller_costs
            return sorted(indices, key=lambda i: ((-1 if side == "buy" else 1) * reservations[i], i))
        return sorted(indices, key=lambda i: _draw(seed, self.case.key, session, f"{side}-{i}", "arrival"))

    def run(self, *, policy: str, seed: int, sessions: int, arrival: str = "seeded") -> None:
        if (policy not in POLICIES or type(seed) is not int or not 0 <= seed < 2**31
                or type(sessions) is not int or not 1 <= sessions <= 5
                or arrival not in {"seeded", "value_order"}):
            raise ValueError("unsupported bounded market assignment")
        for session in range(1, sessions + 1):
            asks = {i: policy_quote(policy, side="sell", reservation=self.case.seller_costs[i],
                unfilled_sessions=session - 1,
                draw=_draw(seed, self.case.key, session, f"sell-{i}", "quote")) for i in self.remaining}
            buyers = self._order([i for i in range(len(self.buyers)) if i not in self.fulfilled],
                                 seed, session, "buy", arrival)
            for i in self._order(list(self.remaining), seed, session, "sell", arrival):
                if self.case.domain == "goods":
                    self.firms.set_price(session, self.firm_ids[i], asks[i])
                else:
                    self.exchange.place_order(session, self.sellers[i], self.firm_ids[0], "sell", 1, asks[i])
            for i in buyers:
                bid = policy_quote(policy, side="buy", reservation=self.case.buyer_values[i],
                    unfilled_sessions=session - 1,
                    draw=_draw(seed, self.case.key, session, f"buy-{i}", "quote"))
                if self.case.domain == "goods":
                    available = [s for s in self.remaining if asks[s] <= bid]
                    seller = min(available, key=lambda s: (asks[s], s)) if available else None
                    receipt = (self.firms.buy_goods(session, self.buyers[i], self.firm_ids[seller], 1)
                               if seller is not None else {"ok": False, "reason": "no_acceptable_stock"})
                    filled = int(receipt.get("qty", 0))
                    self.store.log_event(session, "benchmark_purchase_intent", {
                        "buyer_index": i, "seller_index": seller, "reservation_cents": self.case.buyer_values[i],
                        "bid_cents": bid, "intended_qty": 1, "fulfilled_qty": filled,
                        "reason": None if filled else receipt.get("reason")}, phase="MARKET")
                    if filled:
                        self.fulfilled.add(i)
                        self.remaining.remove(seller)
                else:
                    self.exchange.place_order(session, self.buyers[i], self.firm_ids[0], "buy", 1, bid)
            if self.case.domain == "equities":
                for fill in self.exchange.match_firm(session, self.firm_ids[0]):
                    self.fulfilled.add(self.buyers.index(fill.buyer_id))
                    self.remaining.remove(self.sellers.index(fill.seller_id))
                book = self.store.query("SELECT side,limit_price_cents,qty_remaining FROM orders "
                    "WHERE status IN ('open','partial') AND qty_remaining>0 ORDER BY seq")
                bids = [int(row["limit_price_cents"]) for row in book if row["side"] == "buy"]
                offers = [int(row["limit_price_cents"]) for row in book if row["side"] == "sell"]
                self.store.log_event(session, "benchmark_book", {
                    "best_bid_cents": max(bids) if bids else None,
                    "best_ask_cents": min(offers) if offers else None,
                    "bid_quantity": sum(int(r["qty_remaining"]) for r in book if r["side"] == "buy"),
                    "ask_quantity": sum(int(r["qty_remaining"]) for r in book if r["side"] == "sell")}, phase="MARKET")
                self.exchange.expire_session(session)
            self.store.set_meta(tick=session)
        if self.case.domain == "equities":
            self._redeem(sessions)
        self.store.set_meta(status="completed", active_tick=None, next_phase="NIGHT_CLOSE")

    def _redeem(self, tick: int) -> None:
        firm = self.firm_ids[0]
        for holding in self.store.query("SELECT * FROM shares WHERE firm_id=? ORDER BY holder_id", (firm,)):
            holder, qty = int(holding["holder_id"]), int(holding["qty"])
            self.ledger.transfer(tick, self.redemption_account, self.ledger.agent_checking_id(holder),
                                 qty * int(self.case.redemption_cents), kind="benchmark_redemption")
            self.exchange._adjust_shares(firm, "agent", holder, -qty)
        self.store.update("firms", firm, shares_outstanding=0, status="redeemed")
        self.store.log_event(tick, "benchmark_redemption", {
            "firm_id": firm, "redeemed_shares": len(self.sellers),
            "redemption_cents": self.case.redemption_cents}, phase="MARKET")
