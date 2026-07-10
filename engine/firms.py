"""Firms: founding, production, goods market, payroll, and bankruptcy waterfall.

A firm converts labour + commodity inputs into inventory each tick, posts a price,
sells to budget-constrained households, pays wages, and can go bankrupt with a
creditor waterfall. A global commodity index feeds every firm's input cost — this
is the variable the oil shock moves (PRD R9 / TECH-SPEC §9).
"""
from __future__ import annotations

import json
from typing import Optional

from .ledger import Ledger, Leg, SYS_COMMODITY, SYS_GOV
from .store import Store, load_json

DEFAULT_PRODUCT = {
    "product": "goods",
    "unit_price_cents": 500,
    "base_input_cost_cents": 180,
    "output_per_worker": 6,
}


class Firms:
    def __init__(self, store: Store, ledger: Ledger):
        self.store = store
        self.ledger = ledger

    # ── queries ──────────────────────────────────────────────────────────────
    def get(self, firm_id: int):
        return self.store.query_one("SELECT * FROM firms WHERE id=?", (firm_id,))

    def product(self, firm) -> dict:
        p = load_json(firm["product_json"], {}) or {}
        return {**DEFAULT_PRODUCT, **p}

    def commodity_index(self) -> float:
        v = self.store.metric_latest("commodity_index", 1.0)
        return v if v else 1.0

    def active_employees(self, firm_id: int) -> list:
        return self.store.query(
            "SELECT e.* FROM employments e JOIN agents a ON a.id=e.agent_id "
            "WHERE e.firm_id=? AND e.status='active' AND a.alive=1 AND a.health<>'critical'",
            (firm_id,))

    # ── founding (via law firm, PRD R3) ──────────────────────────────────────
    def found_firm(self, tick: int, founder_agent_id: int, name: str, sector: str,
                   product: Optional[dict] = None, opening_capital_cents: int = 0,
                   shares: int = 1000) -> int:
        acct_id = self.ledger.create_account("firm", None, "checking", label=f"firm:{name}")
        firm_id = self.store.insert(
            "firms", name=name, sector=sector, founder_agent_id=founder_agent_id,
            status="private", product_json=json.dumps(product or DEFAULT_PRODUCT),
            account_id=acct_id, founded_tick=tick, shares_outstanding=shares, inventory=0)
        self.store.execute("UPDATE accounts SET owner_id=? WHERE id=?", (firm_id, acct_id))
        # Founder capitalises the firm from personal funds.
        if opening_capital_cents > 0:
            founder_acct = self.ledger.agent_checking_id(founder_agent_id)
            if founder_acct and self.ledger.balance(founder_acct) >= opening_capital_cents:
                self.ledger.transfer(tick, founder_acct, acct_id, opening_capital_cents,
                                     kind="equity_investment", memo=f"found {name}")
        self.store.insert("shares", firm_id=firm_id, holder_type="agent",
                          holder_id=founder_agent_id, qty=shares)
        self.store.log_event(tick, "company_founded", {
            "firm_id": firm_id, "name": name, "sector": sector,
            "founder_agent_id": founder_agent_id}, phase="EXECUTION",
            subject_type="firm", subject_id=firm_id, importance=2.5)
        return firm_id

    def set_price(self, tick: int, firm_id: int, price_cents: int) -> None:
        firm = self.get(firm_id)
        prod = self.product(firm)
        old = prod["unit_price_cents"]
        prod["unit_price_cents"] = max(1, int(price_cents))
        self.store.update("firms", firm_id, product_json=json.dumps(prod))
        self.store.log_event(tick, "price_set", {
            "firm_id": firm_id, "product": prod["product"],
            "old_cents": old, "new_cents": prod["unit_price_cents"]}, phase="EXECUTION")

    # ── production (NIGHT_CLOSE) ──────────────────────────────────────────────
    def produce(self, tick: int) -> None:
        for firm in self.store.query("SELECT * FROM firms WHERE status IN ('private','listed')"):
            self._produce_one(tick, firm)

    def _produce_one(self, tick: int, firm) -> None:
        firm_id = int(firm["id"])
        prod = self.product(firm)
        workers = len(self.active_employees(firm_id))
        if workers == 0 and firm["founder_agent_id"]:
            fa = self.store.query_one("SELECT alive, health FROM agents WHERE id=?",
                                      (firm["founder_agent_id"],))
            if fa and fa["alive"] and fa["health"] != "critical":
                workers = 1  # owner-operator
        if workers == 0:
            return
        unit_cost = max(1, int(prod["base_input_cost_cents"] * self.commodity_index()))
        desired = workers * int(prod["output_per_worker"])
        acct = int(firm["account_id"])
        cash = self.ledger.balance(acct)
        affordable = cash // unit_cost if unit_cost > 0 else desired
        produced = max(0, min(desired, affordable))
        if produced <= 0:
            return
        commodity_acct = self.ledger.system_account(SYS_COMMODITY)
        self.ledger.post(tick, "production_input", [
            Leg(acct, -produced * unit_cost, "input cost"),
            Leg(commodity_acct, produced * unit_cost, "commodity purchase"),
        ], memo=f"firm {firm_id} produce {produced}")
        self.store.update("firms", firm_id, inventory=int(firm["inventory"]) + produced)
        self.store.log_event(tick, "production", {
            "firm_id": firm_id, "units": produced, "unit_cost_cents": unit_cost}, phase="NIGHT_CLOSE")

    # ── goods purchase (settles instantly) ───────────────────────────────────
    def buy_goods(self, tick: int, buyer_agent_id: int, firm_id: int, qty: int) -> dict:
        firm = self.get(firm_id)
        if not firm or firm["status"] == "bankrupt":
            return {"ok": False, "reason": "firm unavailable"}
        prod = self.product(firm)
        price = int(prod["unit_price_cents"])
        stock = int(firm["inventory"])
        qty = min(qty, stock)
        if qty <= 0:
            return {"ok": False, "reason": "out of stock"}
        buyer_acct = self.ledger.agent_checking_id(buyer_agent_id)
        if buyer_acct is None:
            return {"ok": False, "reason": "no account"}
        affordable = self.ledger.balance(buyer_acct) // price if price > 0 else qty
        qty = min(qty, affordable)
        if qty <= 0:
            return {"ok": False, "reason": "insufficient funds"}
        total = qty * price
        self.ledger.transfer(tick, buyer_acct, int(firm["account_id"]), total,
                             kind="goods_purchase", memo=f"buy {qty} {prod['product']}")
        self.store.update("firms", firm_id, inventory=stock - qty)
        self.store.log_event(tick, "goods_sale", {
            "firm_id": firm_id, "buyer_id": buyer_agent_id, "qty": qty,
            "unit_price_cents": price, "total_cents": total}, phase="MARKET")
        return {"ok": True, "qty": qty, "total_cents": total, "unit_price_cents": price}

    # ── payroll (NIGHT_CLOSE on paydays) ─────────────────────────────────────
    def process_payroll(self, tick: int) -> None:
        due = self.store.query(
            "SELECT * FROM employments WHERE status='active' AND next_pay_tick <= ?", (tick,))
        distressed: set[int] = set()
        for emp in due:
            firm = self.get(int(emp["firm_id"]))
            if not firm or firm["status"] == "bankrupt":
                continue
            agent = self.store.query_one("SELECT alive, health FROM agents WHERE id=?", (emp["agent_id"],))
            interval = int(emp["pay_interval_ticks"])
            if not agent or not agent["alive"]:
                self.store.update("employments", int(emp["id"]), status="ended", end_tick=tick)
                continue
            if agent["health"] == "sick":
                # Sick agents skip labour that period → lost wages (PRD R11).
                self.store.update("employments", int(emp["id"]), next_pay_tick=tick + interval)
                self.store.log_event(tick, "wage_skipped_illness", {
                    "agent_id": int(emp["agent_id"]), "firm_id": int(emp["firm_id"])},
                    phase="NIGHT_CLOSE")
                continue
            wage = int(emp["wage_cents"])
            firm_acct = int(firm["account_id"])
            emp_acct = self.ledger.agent_checking_id(int(emp["agent_id"]))
            if emp_acct is None:
                continue
            if self.ledger.balance(firm_acct) >= wage:
                # Flat income tax withheld at source (PRD R12); 0 when no government.
                tax_bps = int(self.store.metric_latest("tax_rate_bps", 0.0))
                tax = (wage * tax_bps) // 10000 if tax_bps > 0 else 0
                legs = [Leg(firm_acct, -wage, "gross wages"),
                        Leg(emp_acct, wage - tax, "net wages")]
                if tax > 0:
                    legs.append(Leg(self.ledger.system_account(SYS_GOV), tax, "income tax"))
                self.ledger.post(tick, "wage", legs, memo=f"wages firm {firm['id']}")
                self.store.update("employments", int(emp["id"]), next_pay_tick=tick + interval)
                self.store.log_event(tick, "wage_paid", {
                    "firm_id": int(emp["firm_id"]), "agent_id": int(emp["agent_id"]),
                    "wage_cents": wage, "tax_cents": tax, "net_cents": wage - tax},
                    phase="NIGHT_CLOSE")
            else:
                distressed.add(int(emp["firm_id"]))
                self.store.update("employments", int(emp["id"]), next_pay_tick=tick + interval)
                self.store.log_event(tick, "wage_missed", {
                    "firm_id": int(emp["firm_id"]), "agent_id": int(emp["agent_id"])},
                    phase="NIGHT_CLOSE", importance=1.5)
        for firm_id in distressed:
            self._maybe_bankrupt(tick, firm_id)

    def _maybe_bankrupt(self, tick: int, firm_id: int) -> None:
        firm = self.get(firm_id)
        if not firm or firm["status"] == "bankrupt":
            return
        cash = self.ledger.balance(int(firm["account_id"]))
        debt = int(self.store.scalar(
            "SELECT COALESCE(SUM(outstanding_cents),0) FROM loans "
            "WHERE borrower_type='firm' AND borrower_id=? AND status='active'", (firm_id,), default=0))
        # Bankrupt if it cannot meet a full payroll cycle and is deeply cash-negative vs debt.
        payroll = int(self.store.scalar(
            "SELECT COALESCE(SUM(wage_cents),0) FROM employments WHERE firm_id=? AND status='active'",
            (firm_id,), default=0))
        if cash < payroll and (cash < payroll // 2) and (debt > 0 or payroll > 0):
            self.bankrupt_firm(tick, firm_id, reason="insolvency")

    def bankrupt_firm(self, tick: int, firm_id: int, reason: str = "insolvency") -> None:
        """Creditor waterfall: remaining cash pays down bank loans; employees are
        terminated; shares are wiped; the firm delists (PRD R3)."""
        firm = self.get(firm_id)
        if not firm or firm["status"] == "bankrupt":
            return
        firm_acct = int(firm["account_id"])
        loans = self.store.query(
            "SELECT * FROM loans WHERE borrower_type='firm' AND borrower_id=? AND status='active' "
            "ORDER BY id", (firm_id,))
        for loan in loans:
            cash = self.ledger.balance(firm_acct)
            if cash <= 0:
                break
            pay = min(cash, int(loan["outstanding_cents"]))
            bank = self.store.query_one("SELECT reserve_account_id FROM banks WHERE id=?", (loan["bank_id"],))
            if pay > 0 and bank:
                self.ledger.transfer(tick, firm_acct, int(bank["reserve_account_id"]), pay,
                                     kind="bankruptcy_recovery", memo=f"waterfall firm {firm_id}")
                self.store.update("loans", int(loan["id"]),
                                  outstanding_cents=int(loan["outstanding_cents"]) - pay,
                                  status="default")
        # Terminate employment.
        self.store.execute(
            "UPDATE employments SET status='ended', end_tick=? WHERE firm_id=? AND status='active'",
            (tick, firm_id))
        self.store.execute("UPDATE agents SET employer_id=NULL WHERE employer_id=?", (firm_id,))
        # Wipe equity / delist.
        self.store.execute("DELETE FROM shares WHERE firm_id=?", (firm_id,))
        self.store.execute(
            "UPDATE orders SET status='cancelled' WHERE firm_id=? AND status IN ('open','partial')",
            (firm_id,))
        self.store.update("firms", firm_id, status="bankrupt", bankrupt_tick=tick,
                          shares_outstanding=0)
        self.store.log_event(tick, "bankruptcy", {
            "firm_id": firm_id, "name": firm["name"], "reason": reason},
            phase="NIGHT_CLOSE", subject_type="firm", subject_id=firm_id, importance=4.0)

    # ── IPO / listing (R4) ───────────────────────────────────────────────────
    def list_firm(self, tick: int, firm_id: int, ipo_price_cents: int, float_shares: int) -> None:
        firm = self.get(firm_id)
        if not firm or firm["status"] != "private":
            return
        self.store.update("firms", firm_id, status="listed", listed_tick=tick)
        self.store.record_metric(tick, f"stock:{firm_id}", ipo_price_cents)
        self.store.log_event(tick, "ipo", {
            "firm_id": firm_id, "name": firm["name"], "ipo_price_cents": ipo_price_cents,
            "float_shares": float_shares}, phase="MARKET", subject_type="firm",
            subject_id=firm_id, importance=3.0)
