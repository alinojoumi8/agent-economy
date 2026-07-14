"""Banks and credit: deposits, loan schedules, default, and bank failure.

Lending is reserves-funded (a bank lends from its reserve account; the loan asset
is tracked in the `loans` table, off the cash ledger). Every cash movement still
balances, so money is conserved. Bank runs bite because a cross-bank withdrawal
settles reserves (see Ledger.transfer): once a fractional-reserve bank's reserves
run dry it becomes illiquid, triggers interbank borrowing → central-bank LOLR →
and, failing that, a depositor haircut (TECH-SPEC §9).
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Optional

from .ledger import Ledger, Leg, SYS_LOSS
from .store import Store, load_json


@dataclass
class LoanTerms:
    amount_cents: int
    rate_bps: int
    term_ticks: int
    payment_interval_ticks: int = 30


class Bank:
    def __init__(self, store: Store, ledger: Ledger, *,
                 local_currency_action_surfaces: bool = False):
        self.store = store
        self.ledger = ledger
        self.local_currency_action_surfaces = bool(local_currency_action_surfaces)

    # ── queries ──────────────────────────────────────────────────────────────
    def get(self, bank_id: int):
        return self.store.query_one("SELECT * FROM banks WHERE id=?", (bank_id,))

    def reserves(self, bank_id: int) -> int:
        b = self.get(bank_id)
        return self.ledger.balance(int(b["reserve_account_id"]))

    def deposits(self, bank_id: int) -> int:
        return int(self.store.scalar(
            "SELECT COALESCE(SUM(balance_cents),0) FROM accounts "
            "WHERE bank_id=? AND kind IN ('checking','savings')", (bank_id,), default=0))

    def outstanding_loans(self, bank_id: int) -> int:
        return int(self.store.scalar(
            "SELECT COALESCE(SUM(outstanding_cents),0) FROM loans "
            "WHERE bank_id=? AND status='active'", (bank_id,), default=0))

    def reserve_ratio(self, bank_id: int) -> float:
        dep = self.deposits(bank_id)
        return (self.reserves(bank_id) / dep) if dep else 1.0

    # ── loan origination ─────────────────────────────────────────────────────
    @staticmethod
    def amortized_payment(principal: int, rate_bps: int, n_payments: int) -> int:
        """Level payment for a fully-amortising loan, integer cents (ceil)."""
        if n_payments <= 0:
            return principal
        r = (rate_bps / 10000.0) * (30 / 365.0)  # per-interval rate (interval≈30 ticks)
        if r <= 0:
            return math.ceil(principal / n_payments)
        factor = (r * (1 + r) ** n_payments) / ((1 + r) ** n_payments - 1)
        return max(1, math.ceil(principal * factor))

    def disburse_loan(self, tick: int, bank_id: int, borrower_type: str, borrower_id: int,
                      terms: LoanTerms, purpose: str = "", collateral: Optional[dict] = None) -> Optional[int]:
        b = self.get(bank_id)
        if not b or b["status"] != "open":
            return None
        reserve_acct = int(b["reserve_account_id"])
        if self.ledger.balance(reserve_acct) < terms.amount_cents:
            self.store.log_event(tick, "loan_denied_liquidity", {
                "bank_id": bank_id, "borrower_id": borrower_id, "amount": terms.amount_cents},
                phase="EXECUTION")
            return None
        borrower_acct = self._borrower_account(borrower_type, borrower_id)
        if borrower_acct is None:
            return None
        if (self.local_currency_action_surfaces
                and not self._account_uses_bank_currency(b, borrower_acct)):
            self.store.log_event(tick, "loan_denied_currency", {
                "bank_id": bank_id, "borrower_type": borrower_type,
                "borrower_id": borrower_id,
            }, phase="EXECUTION", subject_type=borrower_type, subject_id=borrower_id,
                importance=1.5)
            return None

        self.ledger.post(tick, "loan_disburse", [
            Leg(borrower_acct, terms.amount_cents, "loan proceeds"),
            Leg(reserve_acct, -terms.amount_cents, "loan funded from reserves"),
        ], memo=f"loan to {borrower_type}:{borrower_id}")

        n_payments = max(1, terms.term_ticks // terms.payment_interval_ticks)
        pmt = self.amortized_payment(terms.amount_cents, terms.rate_bps, n_payments)
        loan_id = self.store.insert(
            "loans", bank_id=bank_id, borrower_type=borrower_type, borrower_id=borrower_id,
            principal_cents=terms.amount_cents, outstanding_cents=terms.amount_cents,
            rate_bps=terms.rate_bps, term_ticks=terms.term_ticks, origin_tick=tick,
            payment_cents=pmt, payment_interval_ticks=terms.payment_interval_ticks,
            next_due_tick=tick + terms.payment_interval_ticks, missed_payments=0,
            collateral_json=json.dumps(collateral or {}), purpose=purpose, status="active")
        self.store.log_event(tick, "loan_originated", {
            "loan_id": loan_id, "bank_id": bank_id, "borrower_type": borrower_type,
            "borrower_id": borrower_id, "amount_cents": terms.amount_cents,
            "rate_bps": terms.rate_bps, "term_ticks": terms.term_ticks, "purpose": purpose},
            phase="EXECUTION", subject_type=borrower_type, subject_id=borrower_id, importance=2.0)
        return loan_id

    def _borrower_account(self, borrower_type: str, borrower_id: int) -> Optional[int]:
        if borrower_type == "agent":
            return self.ledger.agent_checking_id(borrower_id)
        if borrower_type == "firm":
            v = self.store.scalar("SELECT account_id FROM firms WHERE id=?", (borrower_id,))
            return int(v) if v is not None else None
        return None

    def _account_uses_bank_currency(self, bank, account_id: int) -> bool:
        currency = self.store.scalar(
            "SELECT currency_code FROM accounts WHERE id=?", (account_id,), default=None)
        return (currency is not None
                and str(currency or "USD") == str(bank["currency_code"] or "USD"))

    # ── scheduled payments + default (NIGHT_CLOSE) ───────────────────────────
    def process_due_loans(self, tick: int) -> None:
        due = self.store.query(
            "SELECT * FROM loans WHERE status='active' AND next_due_tick <= ?", (tick,))
        for loan in due:
            self._process_one_payment(tick, loan)

    def _process_one_payment(self, tick: int, loan) -> None:
        loan_id = int(loan["id"])
        bank = self.get(int(loan["bank_id"]))
        reserve_acct = int(bank["reserve_account_id"])
        equity_acct = int(bank["equity_account_id"])
        borrower_acct = self._borrower_account(loan["borrower_type"], int(loan["borrower_id"]))
        currency_mismatch = (
            self.local_currency_action_surfaces
            and
            borrower_acct is not None
            and not self._account_uses_bank_currency(bank, borrower_acct))
        if currency_mismatch:
            borrower_acct = None
        outstanding = int(loan["outstanding_cents"])
        pmt = min(int(loan["payment_cents"]), outstanding + self._interest_due(loan))
        interest = self._interest_due(loan)
        principal_part = max(0, pmt - interest)
        principal_part = min(principal_part, outstanding)
        total_due = principal_part + interest

        bal = self.ledger.balance(borrower_acct) if borrower_acct else 0
        if borrower_acct is None or bal < total_due:
            missed = int(loan["missed_payments"]) + 1
            self.store.update("loans", loan_id, missed_payments=missed,
                              next_due_tick=tick + int(loan["payment_interval_ticks"]))
            payload = {
                "loan_id": loan_id, "borrower_id": int(loan["borrower_id"]),
                "missed_payments": missed}
            if currency_mismatch:
                payload["reason"] = "borrower primary currency no longer matches bank"
            self.store.log_event(tick, "loan_arrears", payload, phase="NIGHT_CLOSE",
                subject_type=loan["borrower_type"], subject_id=int(loan["borrower_id"]),
                importance=1.5)
            if missed >= 3:
                self._default_loan(tick, loan)
            return

        legs = [Leg(borrower_acct, -total_due, "loan payment")]
        if principal_part:
            legs.append(Leg(reserve_acct, principal_part, "principal repaid"))
        if interest:
            legs.append(Leg(equity_acct, interest, "interest income"))
        self.ledger.post(tick, "loan_payment", legs, memo=f"loan {loan_id} payment")

        new_out = outstanding - principal_part
        status = "paid" if new_out <= 0 else "active"
        self.store.update("loans", loan_id, outstanding_cents=new_out, missed_payments=0,
                          next_due_tick=tick + int(loan["payment_interval_ticks"]), status=status)
        if status == "paid":
            self.store.log_event(tick, "loan_paid", {"loan_id": loan_id},
                                 phase="NIGHT_CLOSE", subject_type=loan["borrower_type"],
                                 subject_id=int(loan["borrower_id"]))

    def _interest_due(self, loan) -> int:
        r = (int(loan["rate_bps"]) / 10000.0) * (int(loan["payment_interval_ticks"]) / 365.0)
        return int(round(int(loan["outstanding_cents"]) * r))

    def _default_loan(self, tick: int, loan) -> None:
        loan_id = int(loan["id"])
        bank = self.get(int(loan["bank_id"]))
        reserve_acct = int(bank["reserve_account_id"])
        outstanding = int(loan["outstanding_cents"])
        recovered = 0
        collateral = load_json(loan["collateral_json"], {}) or {}
        borrower_acct = self._borrower_account(loan["borrower_type"], int(loan["borrower_id"]))
        if (self.local_currency_action_surfaces and borrower_acct is not None
                and not self._account_uses_bank_currency(bank, borrower_acct)):
            borrower_acct = None

        # Cash-collateral seizure (up to outstanding).
        if collateral.get("cash") and borrower_acct is not None:
            seize = min(int(collateral["cash"]), outstanding, self.ledger.balance(borrower_acct))
            if seize > 0:
                self.ledger.transfer(tick, borrower_acct, reserve_acct, seize,
                                     kind="collateral_seizure", memo=f"seize collateral loan {loan_id}")
                recovered += seize

        charged_off = outstanding - recovered
        self.store.update("loans", loan_id, outstanding_cents=0, status="default")
        self.store.log_event(tick, "loan_default", {
            "loan_id": loan_id, "bank_id": int(loan["bank_id"]),
            "borrower_type": loan["borrower_type"], "borrower_id": int(loan["borrower_id"]),
            "charged_off_cents": charged_off, "recovered_cents": recovered},
            phase="NIGHT_CLOSE", subject_type=loan["borrower_type"],
            subject_id=int(loan["borrower_id"]), importance=3.0)

    # ── liquidity + failure (TECH-SPEC §9) ───────────────────────────────────
    def can_settle_outflow(self, bank_id: int, amount_cents: int) -> bool:
        return self.reserves(bank_id) >= amount_cents

    def attempt_liquidity_support(self, tick: int, bank_id: int, shortfall_cents: int,
                                  central_bank_reserve_acct: int, lolr_decider=None) -> bool:
        """Try to cover a reserve shortfall: interbank first, then central-bank LOLR.

        `lolr_decider(bank_id, shortfall) -> bool` optionally injects an LLM/central-
        banker decision; default rule lends if the bank is solvent (loan assets +
        reserves ≥ deposits)."""
        b = self.get(bank_id)
        reserve_acct = int(b["reserve_account_id"])

        # 1) Interbank: borrow surplus reserves from another open bank.
        others = self.store.query(
            "SELECT * FROM banks WHERE id<>? AND status='open'", (bank_id,))
        for ob in others:
            surplus = self.reserves(int(ob["id"])) - self.deposits(int(ob["id"])) // 10
            lend = min(shortfall_cents, max(0, surplus))
            if lend > 0:
                self.ledger.transfer(tick, int(ob["reserve_account_id"]), reserve_acct, lend,
                                     kind="interbank_loan", memo=f"interbank to bank {bank_id}")
                self.store.log_event(tick, "interbank_loan", {
                    "from_bank": int(ob["id"]), "to_bank": bank_id, "amount_cents": lend},
                    phase="NIGHT_CLOSE", importance=2.0)
                shortfall_cents -= lend
            if shortfall_cents <= 0:
                return True

        # 2) Central bank lender of last resort.
        solvent = (self.reserves(bank_id) + self.outstanding_loans(bank_id)) >= self.deposits(bank_id)
        approve = lolr_decider(bank_id, shortfall_cents) if lolr_decider else solvent
        if approve:
            self.ledger.transfer(tick, central_bank_reserve_acct, reserve_acct, shortfall_cents,
                                 kind="lolr", memo=f"central bank LOLR to bank {bank_id}")
            self.store.log_event(tick, "lolr_granted", {
                "bank_id": bank_id, "amount_cents": shortfall_cents}, phase="NIGHT_CLOSE",
                subject_type="bank", subject_id=bank_id, importance=3.0)
            return True

        self.store.log_event(tick, "lolr_denied", {"bank_id": bank_id}, phase="NIGHT_CLOSE",
                             subject_type="bank", subject_id=bank_id, importance=3.0)
        return False

    def fail_bank(self, tick: int, bank_id: int) -> None:
        """Depositor haircut: reserves are distributed pro-rata; the shortfall is
        written off to the loss sink (destroyed wealth). This is what makes runs bite."""
        b = self.get(bank_id)
        reserve_acct = int(b["reserve_account_id"])
        deposits = self.store.query(
            "SELECT id, balance_cents FROM accounts WHERE bank_id=? AND kind IN ('checking','savings') "
            "AND balance_cents > 0", (bank_id,))
        total_dep = sum(int(d["balance_cents"]) for d in deposits)
        available = max(0, self.ledger.balance(reserve_acct))
        recovery = min(1.0, (available / total_dep) if total_dep else 1.0)
        loss_acct = self.ledger.system_account(SYS_LOSS)

        for d in deposits:
            bal = int(d["balance_cents"])
            haircut = bal - int(bal * recovery)
            if haircut > 0:
                self.ledger.post(tick, "depositor_haircut", [
                    Leg(int(d["id"]), -haircut, "bank failure haircut"),
                    Leg(loss_acct, haircut, "destroyed in bank failure"),
                ], memo=f"haircut bank {bank_id}")
        self.store.update("banks", bank_id, status="failed", failed_tick=tick)
        self.store.log_event(tick, "bank_failure", {
            "bank_id": bank_id, "recovery_rate": round(recovery, 4),
            "haircut_rate": round(1 - recovery, 4), "deposits_cents": total_dep},
            phase="NIGHT_CLOSE", subject_type="bank", subject_id=bank_id, importance=5.0)
