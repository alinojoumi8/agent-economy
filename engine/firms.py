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
        founder = self.store.query_one(
            "SELECT region_id, checking_account_id FROM agents WHERE id=?", (founder_agent_id,))
        region_id = int(founder["region_id"]) if founder and founder["region_id"] is not None else None
        currency = "USD"
        bank_id = None
        if founder and founder["checking_account_id"] is not None:
            source = self.store.query_one(
                "SELECT currency_code,bank_id FROM accounts WHERE id=?", (founder["checking_account_id"],))
            if source:
                currency = str(source["currency_code"] or "USD")
                bank_id = int(source["bank_id"]) if source["bank_id"] is not None else None
        acct_id = self.ledger.create_account(
            "firm", None, "checking", bank_id=bank_id, label=f"firm:{name}", currency_code=currency)
        firm_id = self.store.insert(
            "firms", name=name, sector=sector, founder_agent_id=founder_agent_id,
            status="private", product_json=json.dumps(product or DEFAULT_PRODUCT),
            account_id=acct_id, founded_tick=tick, shares_outstanding=shares, inventory=0,
            region_id=region_id, currency_code=currency)
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
        currency = str(firm["currency_code"] or "USD")
        commodity_acct = self.ledger.system_account(SYS_COMMODITY, currency_code=currency)
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
        buyer_currency = self.store.scalar(
            "SELECT currency_code FROM accounts WHERE id=?", (buyer_acct,), default="USD")
        if str(buyer_currency or "USD") != str(firm["currency_code"] or "USD"):
            return {"ok": False, "reason": "cross-border purchases require a trade shipment and FX"}
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
                    currency = str(firm["currency_code"] or "USD")
                    legs.append(Leg(self.ledger.system_account(
                        SYS_GOV, currency_code=currency), tax, "income tax"))
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
    def list_firm(self, tick: int, firm_id: int, ipo_price_cents: Optional[int],
                  float_shares: int, *, legacy_reference_price: bool = False) -> None:
        """Bootstrap a listing without inventing a modern market price.

        `legacy_reference_price` exists solely for exact replay of semantics 1-5
        genesis runs.  Semantics 6+ listings either begin without a price or use
        :meth:`close_ipo`, whose clearing price comes from agent-authored bids.
        """
        firm = self.get(firm_id)
        if not firm or firm["status"] != "private":
            return
        self.store.update("firms", firm_id, status="listed", listed_tick=tick)
        if legacy_reference_price:
            if ipo_price_cents is None or int(ipo_price_cents) <= 0:
                raise ValueError("legacy listing requires a positive reference price")
            self.store.record_metric(tick, f"stock:{firm_id}", int(ipo_price_cents))
            self.store.log_event(tick, "ipo", {
                "firm_id": firm_id, "name": firm["name"],
                "ipo_price_cents": int(ipo_price_cents),
                "float_shares": float_shares}, phase="MARKET", subject_type="firm",
                subject_id=firm_id, importance=3.0)
            return
        self.store.log_event(tick, "bootstrap_listing", {
            "firm_id": firm_id, "name": firm["name"], "float_shares": float_shares,
            "reference_price_cents": None,
        }, phase="MARKET", subject_type="firm", subject_id=firm_id, importance=2.0)

    def ipo_qualification(self, tick: int, firm_id: int) -> dict:
        """Return deterministic qualification facts, not a discretionary price."""
        firm = self.get(firm_id)
        if not firm:
            return {"qualified": False, "reasons": ["firm missing"]}
        age = max(0, int(tick) - int(firm["founded_tick"] or 0))
        employees = int(self.store.scalar(
            "SELECT COUNT(*) FROM employments WHERE firm_id=? AND status='active'",
            (firm_id,), default=0))
        sales = int(self.store.scalar(
            "SELECT COUNT(*) FROM events WHERE kind='goods_sale' "
            "AND json_extract(payload_json,'$.firm_id')=?", (firm_id,), default=0))
        cash = self.ledger.balance(int(firm["account_id"])) if firm["account_id"] else 0
        reasons: list[str] = []
        if firm["status"] != "private":
            reasons.append("firm must be private")
        if age < 30:
            reasons.append("firm needs 30 ticks of operating history")
        if not (employees >= 2 or sales >= 3 or cash >= 100_000):
            reasons.append("firm needs scale: 2 employees, 3 sales, or 100000 cents cash")
        if int(firm["shares_outstanding"] or 0) <= 0:
            reasons.append("firm has no outstanding equity")
        active = self.store.query_one(
            "SELECT id FROM ipo_offerings WHERE firm_id=? AND status='building'", (firm_id,))
        if active:
            reasons.append("firm already has an active offering")
        return {
            "qualified": not reasons, "reasons": reasons, "firm_age_ticks": age,
            "employees": employees, "sales": sales, "cash_cents": cash,
            "shares_outstanding": int(firm["shares_outstanding"] or 0),
        }

    def open_ipo(self, tick: int, actor_id: int, firm_id: int, shares_offered: int,
                 reserve_price_cents: int, minimum_subscription_bps: int = 5000) -> dict:
        qualification = self.ipo_qualification(tick, firm_id)
        if not qualification["qualified"]:
            return {"ok": False, "reason": "; ".join(qualification["reasons"])}
        firm = self.get(firm_id)
        offered = int(shares_offered)
        reserve = int(reserve_price_cents)
        outstanding = int(firm["shares_outstanding"])
        if offered <= 0 or offered > outstanding:
            return {"ok": False, "reason": "shares_offered must be between 1 and current shares outstanding"}
        if reserve <= 0:
            return {"ok": False, "reason": "reserve price must be positive and agent-authored"}
        minimum = int(minimum_subscription_bps)
        if minimum < 1 or minimum > 10_000:
            return {"ok": False, "reason": "minimum subscription must be 1..10000 bps"}
        offering_id = self.store.insert(
            "ipo_offerings", firm_id=firm_id, issuer_agent_id=actor_id,
            opened_tick=tick, shares_offered=offered, reserve_price_cents=reserve,
            minimum_subscription_bps=minimum, status="building")
        self.store.log_event(tick, "ipo_book_opened", {
            "offering_id": offering_id, "firm_id": firm_id, "issuer_agent_id": actor_id,
            "shares_offered": offered, "reserve_price_cents": reserve,
            "minimum_subscription_bps": minimum,
        }, phase="EXECUTION", subject_type="ipo_offering", subject_id=offering_id,
            importance=2.5)
        return {"ok": True, "offering_id": offering_id}

    def place_ipo_bid(self, tick: int, bidder_agent_id: int, offering_id: int,
                      qty: int, max_price_cents: int) -> dict:
        offering = self.store.query_one(
            "SELECT io.*,f.account_id AS firm_account_id,f.currency_code FROM ipo_offerings io "
            "JOIN firms f ON f.id=io.firm_id WHERE io.id=?", (offering_id,))
        if not offering or offering["status"] != "building":
            return {"ok": False, "reason": "IPO offering is not open"}
        if int(offering["issuer_agent_id"]) == int(bidder_agent_id):
            return {"ok": False, "reason": "issuer cannot bid in its own offering"}
        quantity = int(qty)
        limit = int(max_price_cents)
        if quantity <= 0 or limit < int(offering["reserve_price_cents"]):
            return {"ok": False, "reason": "positive quantity and a bid at or above reserve are required"}
        bidder_account = self.ledger.agent_checking_id(bidder_agent_id)
        if bidder_account is None:
            return {"ok": False, "reason": "bidder has no checking account"}
        account = self.store.query_one(
            "SELECT balance_cents,currency_code FROM accounts WHERE id=?", (bidder_account,))
        if (not account or str(account["currency_code"] or "USD")
                != str(offering["currency_code"] or "USD")):
            return {"ok": False, "reason": "IPO bid requires the issuer currency"}
        commitment = quantity * limit
        currency = str(offering["currency_code"] or "USD")
        existing_commitment = int(self.store.scalar(
            "SELECT COALESCE(SUM(ib.qty * ib.max_price_cents), 0) "
            "FROM ipo_bids ib JOIN ipo_offerings io ON io.id=ib.offering_id "
            "JOIN firms f ON f.id=io.firm_id "
            "WHERE ib.bidder_agent_id=? AND ib.status='open' "
            "AND io.status='building' AND COALESCE(f.currency_code,'USD')=?",
            (bidder_agent_id, currency), default=0))
        if int(account["balance_cents"]) < existing_commitment + commitment:
            return {"ok": False, "reason": "insufficient funds for bid commitment"}
        bid_id = self.store.insert(
            "ipo_bids", offering_id=offering_id, tick=tick,
            bidder_agent_id=bidder_agent_id, qty=quantity,
            max_price_cents=limit, status="open")
        self.store.log_event(tick, "ipo_bid_placed", {
            "bid_id": bid_id, "offering_id": offering_id,
            "bidder_agent_id": bidder_agent_id, "qty": quantity,
            "max_price_cents": limit,
        }, phase="EXECUTION", subject_type="ipo_offering", subject_id=offering_id,
            importance=1.2)
        return {"ok": True, "bid_id": bid_id}

    def close_ipo(self, tick: int, actor_id: int, offering_id: int) -> dict:
        offering = self.store.query_one(
            "SELECT io.*,f.name AS firm_name,f.account_id AS firm_account_id,"
            "f.shares_outstanding,f.status AS firm_status FROM ipo_offerings io "
            "JOIN firms f ON f.id=io.firm_id WHERE io.id=?", (offering_id,))
        if not offering or offering["status"] != "building" or offering["firm_status"] != "private":
            return {"ok": False, "reason": "IPO offering is not closable"}
        bids = self.store.query(
            "SELECT * FROM ipo_bids WHERE offering_id=? AND status='open' "
            "ORDER BY max_price_cents DESC,tick,id", (offering_id,))
        if not bids:
            return {"ok": False, "reason": "book has no valid bids; no market price exists"}
        offered = int(offering["shares_offered"])
        reserve = int(offering["reserve_price_cents"])

        # Revalidate the book against current balances before discovering a
        # price.  Funds are conservatively reserved at each bid's limit in
        # price/time order, so cash spent after bid placement cannot leave an
        # unfunded high bid setting the marginal clearing price.
        available_by_agent: dict[int, int] = {}
        funded_qty_by_bid: dict[int, int] = {}
        for bid in bids:
            bidder_id = int(bid["bidder_agent_id"])
            if bidder_id not in available_by_agent:
                account_id = self.ledger.agent_checking_id(bidder_id)
                available_by_agent[bidder_id] = (
                    self.ledger.balance(account_id) if account_id is not None else 0)
            limit = int(bid["max_price_cents"])
            funded_qty = min(
                int(bid["qty"]), available_by_agent[bidder_id] // limit)
            funded_qty_by_bid[int(bid["id"])] = funded_qty
            available_by_agent[bidder_id] -= funded_qty * limit

        declared = 0
        marginal = reserve
        for bid in bids:
            funded_qty = funded_qty_by_bid[int(bid["id"])]
            if funded_qty <= 0:
                continue
            declared += funded_qty
            marginal = int(bid["max_price_cents"])
            if declared >= offered:
                break
        clearing = max(reserve, marginal if declared >= offered else reserve)

        # Pre-compute allocations from current balances.  No cash or shares move
        # until the minimum subscription is known to pass.
        remaining = offered
        allocations: list[tuple[object, int, int]] = []
        for bid in bids:
            if remaining <= 0:
                break
            if int(bid["max_price_cents"]) < clearing:
                continue
            allocated = min(funded_qty_by_bid[int(bid["id"])], remaining)
            if allocated <= 0:
                continue
            remaining -= allocated
            allocations.append((bid, allocated, allocated * clearing))
        sold = sum(item[1] for item in allocations)
        minimum_shares = (
            offered * int(offering["minimum_subscription_bps"]) + 9_999) // 10_000
        if sold < minimum_shares:
            return {"ok": False, "reason": "book does not meet minimum subscription"}

        firm_id = int(offering["firm_id"])
        firm_account = int(offering["firm_account_id"])
        proceeds = 0
        allocated_ids: set[int] = set()
        for bid, allocated, amount in allocations:
            bidder_id = int(bid["bidder_agent_id"])
            bidder_account = self.ledger.agent_checking_id(bidder_id)
            txn_id = self.ledger.transfer(
                tick, int(bidder_account), firm_account, amount, kind="ipo_subscription",
                memo=f"IPO offering {offering_id}, bid {int(bid['id'])}")
            self.store.execute(
                "INSERT INTO shares(firm_id,holder_type,holder_id,qty) VALUES(?, 'agent', ?, ?) "
                "ON CONFLICT(firm_id,holder_type,holder_id) DO UPDATE SET qty=qty+excluded.qty",
                (firm_id, bidder_id, allocated))
            self.store.insert(
                "share_movements", tick=tick, firm_id=firm_id,
                from_holder_type=None, from_holder_id=None,
                to_holder_type="agent", to_holder_id=bidder_id, qty=allocated,
                movement_type="ipo_primary_issuance", reference_type="ipo_bid",
                reference_id=int(bid["id"]), price_cents=clearing,
                amount_cents=amount, transaction_id=txn_id)
            self.store.update("ipo_bids", int(bid["id"]), status="allocated",
                              qty_allocated=allocated)
            allocated_ids.add(int(bid["id"]))
            proceeds += amount
        for bid in bids:
            if int(bid["id"]) not in allocated_ids:
                self.store.update("ipo_bids", int(bid["id"]), status="rejected")
        self.store.update(
            "firms", firm_id, status="listed", listed_tick=tick,
            shares_outstanding=int(offering["shares_outstanding"]) + sold)
        self.store.update(
            "ipo_offerings", offering_id, status="listed", closed_tick=tick,
            clearing_price_cents=clearing, shares_sold=sold, proceeds_cents=proceeds)
        # This is a discovered primary-market price: both the issuer reserve and
        # the marginal investor bid are persisted agent actions.
        self.store.record_metric(tick, f"stock:{firm_id}", clearing)
        self.store.log_event(tick, "ipo", {
            "offering_id": offering_id, "firm_id": firm_id,
            "issuer_agent_id": actor_id, "clearing_price_cents": clearing,
            "shares_offered": offered, "shares_sold": sold,
            "proceeds_cents": proceeds,
        }, phase="MARKET", subject_type="firm", subject_id=firm_id, importance=3.5)
        return {"ok": True, "firm_id": firm_id, "offering_id": offering_id,
                "clearing_price_cents": clearing, "shares_sold": sold,
                "proceeds_cents": proceeds}
