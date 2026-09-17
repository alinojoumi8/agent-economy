"""Recorded positive-cash and bank-principal waterfall, not full probate.

Semantics 19 accelerates existing bank principal, pays loans in ascending ID
order from all same-currency checking/savings/FX wallets, charges off any
shortfall against bank equity and distributes remaining cash. It retains the
reserves-funded credit model. Illiquid rights and later receipts are separate
W5 work; this component never values them or labels the entire estate closed.
"""
from __future__ import annotations

from .ledger import Leg, SYS_GOV, SYS_LOSS


class EstateError(RuntimeError):
    """The recorded cash waterfall cannot be reconciled."""


class CashEstates:
    POLICY = "positive_cash_bank_principal_v1"
    CASH_KINDS = ("checking", "savings", "fx")

    def __init__(self, economy):
        self.e = economy
        self.store = economy.store
        self.ledger = economy.ledger

    def settle(self, tick: int, agent_id: int, heir_id: int | None) -> int:
        """Called inside the death savepoint after collectible wages arrive."""
        if self.e.engine_semantics_version < 19:
            raise EstateError("cash estate receipts require Semantics 19")
        existing = self.store.query_one("SELECT * FROM cash_estates WHERE deceased_agent_id=?", (agent_id,))
        if existing:
            if existing["heir_id"] != heir_id or existing["tick"] != tick:
                raise EstateError("cash estate already has different settlement terms")
            self.check_invariants(existing["id"])
            return int(existing["id"])
        if not self.store.scalar("SELECT alive FROM agents WHERE id=?", (agent_id,)):
            raise EstateError("cash settlement must run during an active death transition")
        if heir_id is not None and (heir_id == agent_id or not self.store.scalar(
                "SELECT alive FROM agents WHERE id=?", (heir_id,))):
            raise EstateError("cash beneficiary must be a different living person")
        with self.store.savepoint("estate_cash_waterfall"):
            return self._settle(tick, agent_id, heir_id)

    def _settle(self, tick, agent_id, heir_id):
        assets = self.store.query(
            "SELECT * FROM accounts WHERE owner_type='agent' AND owner_id=? "
            "AND kind IN ('checking','savings','fx') ORDER BY currency_code,id", (agent_id,))
        loans = self.store.query(
            "SELECT * FROM loans WHERE borrower_type='agent' AND borrower_id=? "
            "AND status='active' ORDER BY id", (agent_id,))
        estate_id = self.store.insert("cash_estates", deceased_agent_id=agent_id, tick=tick,
            heir_id=heir_id, policy=self.POLICY, cash_account_count=len(assets), loan_count=len(loans))
        available = {int(a["id"]): max(0, int(a["balance_cents"])) for a in assets}
        for loan in loans:
            bank = self.e.bank.get(loan["bank_id"])
            if bank is None:
                raise EstateError("estate creditor bank is missing")
            currency = str(bank["currency_code"] or "USD")
            for field, kind in (("reserve_account_id", "reserve"), ("equity_account_id", "equity")):
                account = self.store.query_one("SELECT * FROM accounts WHERE id=?", (bank[field],))
                if (account is None or account["currency_code"] != currency
                        or account["kind"] != kind or account["owner_type"] != "bank"
                        or account["owner_id"] != bank["id"]):
                    raise EstateError("estate creditor accounts do not match its bank and currency")
            principal = int(loan["outstanding_cents"])
            if principal < 0:
                raise EstateError("estate principal cannot be negative")
            remaining = principal
            for asset in assets:
                if asset["currency_code"] != currency or not remaining:
                    continue
                amount = min(available[asset["id"]], remaining)
                if amount:
                    self._transfer(tick, estate_id, asset["id"], bank["reserve_account_id"],
                                   currency, amount, "loan", loan["id"])
                    available[asset["id"]] -= amount
                    remaining -= amount
            transaction = loss_account = None
            if remaining:
                loss_account = self.ledger.system_account(SYS_LOSS, currency_code=currency)
                transaction = self.ledger.post(tick, "estate_loan_loss", [
                    Leg(bank["equity_account_id"], -remaining, "estate principal charge-off"),
                    Leg(loss_account, remaining, "uncollectible estate principal"),
                ], memo=f"estate {estate_id} loan {loan['id']}")
            self.store.update("loans", loan["id"], outstanding_cents=0,
                              status="default" if remaining else "paid")
            self.store.insert("estate_loan_claims", estate_id=estate_id, loan_id=loan["id"],
                bank_id=bank["id"], currency_code=currency, principal_cents=principal,
                paid_cents=principal-remaining, written_off_cents=remaining,
                reserve_account_id=bank["reserve_account_id"], equity_account_id=bank["equity_account_id"],
                loss_account_id=loss_account, chargeoff_transaction_id=transaction)
        for asset in assets:
            residual = available[asset["id"]]
            currency = str(asset["currency_code"] or "USD")
            if residual:
                target = self._beneficiary_wallet(heir_id, currency)
                self._transfer(tick, estate_id, asset["id"], target, currency, residual,
                               "inheritance" if heir_id is not None else "escheat")
            self.store.insert("estate_cash_assets", estate_id=estate_id, account_id=asset["id"],
                currency_code=currency, opening_cents=asset["balance_cents"],
                loan_paid_cents=max(0, asset["balance_cents"])-residual, residual_cents=residual)
        # Public event identifies the evidence without publishing creditor amounts.
        event_id = self.store.log_event(tick, "estate_cash_settled", {
            "estate_id": estate_id, "agent_id": agent_id, "heir_id": heir_id,
            "scope": self.POLICY, "cash_account_count": len(assets), "loan_count": len(loans),
        }, phase="NIGHT_CLOSE", subject_type="agent", subject_id=agent_id)
        self.store.update("cash_estates", estate_id, completed_event_id=event_id)
        self.check_invariants(estate_id)
        return estate_id

    def _beneficiary_wallet(self, heir_id, currency):
        if heir_id is None:
            return self.ledger.system_account(SYS_GOV, currency_code=currency)
        account = self.store.query_one(
            "SELECT id FROM accounts WHERE owner_type='agent' AND owner_id=? "
            "AND currency_code=? AND kind IN ('checking','savings','fx') "
            "ORDER BY CASE kind WHEN 'checking' THEN 0 ELSE 1 END,id LIMIT 1", (heir_id, currency))
        return int(account["id"]) if account else self.ledger.create_account(
            "agent", heir_id, "fx", currency_code=currency, label=f"inheritance:{heir_id}:{currency}")

    def _transfer(self, tick, estate_id, source, destination, currency, amount, kind, loan_id=None):
        transaction = self.ledger.transfer(tick, source, destination, amount,
            kind="estate_debt" if kind == "loan" else kind, memo=f"estate {estate_id}")
        self.store.insert("estate_cash_transfers", estate_id=estate_id, source_account_id=source,
            destination_account_id=destination, currency_code=currency, kind=kind,
            loan_id=loan_id, amount_cents=amount, transaction_id=transaction)

    def _transaction_legs(self, transaction_id, tick, currency):
        rows = self.store.query(
            "SELECT l.account_id,l.delta_cents,l.tick,a.currency_code FROM ledger_entries l "
            "JOIN accounts a ON a.id=l.account_id WHERE l.txn_id=? ORDER BY l.id", (transaction_id,))
        if not rows or any(row["tick"] != tick or row["currency_code"] != currency for row in rows):
            raise EstateError("estate receipt transaction has the wrong day or currency")
        totals = {}
        for row in rows:
            totals[row["account_id"]] = totals.get(row["account_id"], 0) + row["delta_cents"]
        if sum(totals.values()):
            raise EstateError("estate transaction is not balanced")
        return totals

    def check_invariants(self, estate_id=None):
        """Reconcile immutable receipts, without treating later inflows as errors."""
        estates = self.store.query("SELECT * FROM cash_estates" + (" WHERE id=?" if estate_id is not None else "")
                                   + " ORDER BY id", (estate_id,) if estate_id is not None else ())
        for estate in estates:
            assets = self.store.query("SELECT * FROM estate_cash_assets WHERE estate_id=?", (estate["id"],))
            claims = self.store.query("SELECT * FROM estate_loan_claims WHERE estate_id=?", (estate["id"],))
            transfers = self.store.query("SELECT * FROM estate_cash_transfers WHERE estate_id=?", (estate["id"],))
            event = self.store.query_one("SELECT kind,tick,subject_id FROM events WHERE id=?", (estate["completed_event_id"],))
            if (event is None or event["kind"] != "estate_cash_settled" or event["tick"] != estate["tick"]
                    or event["subject_id"] != estate["deceased_agent_id"]
                    or len(assets) != estate["cash_account_count"] or len(claims) != estate["loan_count"]):
                raise EstateError("cash estate completion and inventory disagree")
            by_account = {a["account_id"]: a for a in assets}
            by_loan = {c["loan_id"]: c for c in claims}
            for transfer in transfers:
                asset = by_account.get(transfer["source_account_id"])
                if asset is None or asset["currency_code"] != transfer["currency_code"]:
                    raise EstateError("estate transfer has no matching cash inventory")
                target = self.store.query_one("SELECT * FROM accounts WHERE id=?", (transfer["destination_account_id"],))
                source = self.store.query_one("SELECT * FROM accounts WHERE id=?", (transfer["source_account_id"],))
                if source is None or target is None:
                    raise EstateError("estate transfer account is missing")
                if transfer["kind"] == "loan":
                    claim = by_loan.get(transfer["loan_id"])
                    if (claim is None or claim["reserve_account_id"] != target["id"]
                            or claim["currency_code"] != transfer["currency_code"]):
                        raise EstateError("estate loan payment has the wrong creditor")
                elif estate["heir_id"] is None:
                    if (transfer["kind"] != "escheat" or target["label"] != SYS_GOV
                            or target["owner_type"] != "system"):
                        raise EstateError("estate escheat has the wrong beneficiary")
                elif (transfer["kind"] != "inheritance" or target["owner_type"] != "agent"
                      or target["owner_id"] != estate["heir_id"] or target["kind"] not in self.CASH_KINDS):
                    raise EstateError("estate inheritance has the wrong beneficiary")
                legs = self._transaction_legs(transfer["transaction_id"], estate["tick"], transfer["currency_code"])
                amount = transfer["amount_cents"]
                expected = {source["id"]: -amount, target["id"]: amount}
                if (source["bank_id"] and target["bank_id"] and source["bank_id"] != target["bank_id"]
                        and source["kind"] in ("checking", "savings") and target["kind"] in ("checking", "savings")):
                    from_reserve = self.ledger._bank_reserve(source["bank_id"])
                    to_reserve = self.ledger._bank_reserve(target["bank_id"])
                    if from_reserve and to_reserve:
                        expected[from_reserve] = expected.get(from_reserve, 0) - amount
                        expected[to_reserve] = expected.get(to_reserve, 0) + amount
                if legs != expected:
                    raise EstateError("estate transfer receipt and ledger disagree")
            for asset in assets:
                account = self.store.query_one("SELECT * FROM accounts WHERE id=?", (asset["account_id"],))
                if (account["owner_type"] != "agent" or account["owner_id"] != estate["deceased_agent_id"]
                        or account["kind"] not in self.CASH_KINDS or account["currency_code"] != asset["currency_code"]):
                    raise EstateError("estate cash inventory has the wrong owner or currency")
                for field, is_loan in (("loan_paid_cents", True), ("residual_cents", False)):
                    actual = sum(t["amount_cents"] for t in transfers if t["source_account_id"] == asset["account_id"]
                                 and (t["kind"] == "loan") == is_loan)
                    if actual != asset[field]:
                        raise EstateError("estate cash inventory and transfers disagree")
            for claim in claims:
                loan = self.store.query_one("SELECT * FROM loans WHERE id=?", (claim["loan_id"],))
                paid = sum(t["amount_cents"] for t in transfers if t["loan_id"] == claim["loan_id"])
                if (loan["borrower_type"] != "agent" or loan["borrower_id"] != estate["deceased_agent_id"]
                        or loan["bank_id"] != claim["bank_id"] or loan["outstanding_cents"] != 0
                        or loan["status"] != ("default" if claim["written_off_cents"] else "paid")
                        or paid != claim["paid_cents"]):
                    raise EstateError("estate loan principal and payments disagree")
                if claim["written_off_cents"]:
                    actual = self._transaction_legs(claim["chargeoff_transaction_id"], estate["tick"], claim["currency_code"])
                    expected = {claim["equity_account_id"]: -claim["written_off_cents"],
                                claim["loss_account_id"]: claim["written_off_cents"]}
                    if actual != expected:
                        raise EstateError("estate bank loss and equity charge-off disagree")
