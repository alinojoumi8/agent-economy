"""Double-entry ledger. The single most important invariant in the system.

Every transaction is a set of *legs* — (account_id, delta_cents) pairs — that MUST
sum to zero. Because each transaction is balanced, the grand sum of all account
balances is invariant; we construct the world so that sum is 0 and check it every
tick (PRD R1). Money is integer cents; floats are never used for balances.

The "outside world" (initial endowments, commodity inputs bought from outside,
arrival savings minted in, wealth destroyed in a bank failure) is represented as
real accounts flagged `is_external`. They can go negative. This keeps the books
closed and auditable: nothing is created or destroyed without a matching leg.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from .store import Store


class LedgerError(Exception):
    """Raised when a transaction is unbalanced or an account is missing."""


class ReconciliationError(Exception):
    """Raised when the books fail to reconcile — halts the run (PRD R1)."""


@dataclass
class Leg:
    account_id: int
    delta_cents: int
    memo: str = ""


# Well-known system account labels (created once at genesis).
SYS_EXTERNAL = "sys:external"          # endowment source / rest-of-world sink
SYS_COMMODITY = "sys:commodity"        # firms buy raw inputs from here (energy/oil)
SYS_INFLOW = "sys:population_inflow"   # mints arrival starting savings (PRD R11 conservation)
SYS_LOSS = "sys:loss"                  # destroyed wealth (bank-failure haircuts, write-offs)
SYS_MEDICAL = "sys:medical"            # out-of-pocket medical costs leave here
SYS_GOV = "sys:gov"                    # government treasury (P1 fiscal)
SYS_HOUSING = "sys:housing"            # rent/move-in costs paid by households


class Ledger:
    def __init__(self, store: Store):
        self.store = store

    # ── account management ───────────────────────────────────────────────────
    def create_account(self, owner_type: str, owner_id: Optional[int], kind: str, *,
                        bank_id: Optional[int] = None, label: str = "",
                        is_external: bool = False, opening_cents: int = 0,
                        funding_label: str = SYS_EXTERNAL, tick: Optional[int] = None,
                        currency_code: str = "USD") -> int:
        currency_code = str(currency_code or "USD").upper()
        acct_id = self.store.insert(
            "accounts", owner_type=owner_type, owner_id=owner_id, bank_id=bank_id,
            kind=kind, label=label, balance_cents=0, is_external=1 if is_external else 0,
            currency_code=currency_code,
        )
        if opening_cents:
            # Fund from a visible source account so the books stay balanced. Genesis
            # uses the external endowment; arrivals mint from population_inflow (R11).
            src = self.system_account(funding_label, currency_code=currency_code)
            self.post(self.store.tick if tick is None else tick, "endowment", [
                Leg(acct_id, opening_cents, "opening balance"),
                Leg(src, -opening_cents, "endowment source"),
            ], memo=f"endow {label or acct_id}")
        return acct_id

    def ensure_system_account(self, label: str, *, currency_code: str = "USD") -> int:
        currency_code = str(currency_code or "USD").upper()
        row = self.store.query_one(
            "SELECT id FROM accounts WHERE owner_type='system' AND label=? AND currency_code=?",
            (label, currency_code)
        )
        if row:
            return int(row["id"])
        return self.store.insert(
            "accounts", owner_type="system", owner_id=None, bank_id=None,
            kind="external", label=label, balance_cents=0, is_external=1,
            currency_code=currency_code,
        )

    def system_account(self, label: str, *, currency_code: str = "USD") -> int:
        currency_code = str(currency_code or "USD").upper()
        row = self.store.query_one(
            "SELECT id FROM accounts WHERE owner_type='system' AND label=? AND currency_code=?",
            (label, currency_code)
        )
        if not row:
            return self.ensure_system_account(label, currency_code=currency_code)
        return int(row["id"])

    def balance(self, account_id: int) -> int:
        v = self.store.scalar("SELECT balance_cents FROM accounts WHERE id=?", (account_id,))
        if v is None:
            raise LedgerError(f"account {account_id} does not exist")
        return int(v)

    def agent_checking_id(self, agent_id: int) -> Optional[int]:
        v = self.store.scalar("SELECT checking_account_id FROM agents WHERE id=?", (agent_id,))
        return int(v) if v is not None else None

    def net_worth_agent(self, agent_id: int) -> int:
        """Cash across all of an agent's deposit accounts, minus outstanding debt."""
        cash = int(self.store.scalar(
            "SELECT COALESCE(SUM(balance_cents),0) FROM accounts "
            "WHERE owner_type='agent' AND owner_id=?", (agent_id,), default=0))
        debt = int(self.store.scalar(
            "SELECT COALESCE(SUM(outstanding_cents),0) FROM loans "
            "WHERE borrower_type='agent' AND borrower_id=? AND status='active'",
            (agent_id,), default=0))
        return cash - debt

    # ── the one write path ───────────────────────────────────────────────────
    def post(self, tick: int, kind: str, legs: list[Leg], memo: str = "") -> int:
        """Post one balanced transaction atomically. Raises if legs don't sum to 0."""
        if not legs:
            raise LedgerError(f"empty transaction '{kind}'")

        accounts = {}
        totals: dict[str, int] = {}
        for leg in legs:
            account = self.store.query_one(
                "SELECT balance_cents, currency_code FROM accounts WHERE id=?", (leg.account_id,))
            if account is None:
                raise LedgerError(f"account {leg.account_id} does not exist (txn '{kind}')")
            accounts[leg.account_id] = account
            currency = str(account["currency_code"] or "USD")
            totals[currency] = totals.get(currency, 0) + int(leg.delta_cents)
        unbalanced = {currency: total for currency, total in totals.items() if total != 0}
        if unbalanced:
            raise LedgerError(
                f"unbalanced transaction '{kind}' by currency: {unbalanced}; legs={legs}"
            )

        now = datetime.now(timezone.utc).isoformat()
        transaction_currency = next(iter(totals)) if len(totals) == 1 else "MULTI"
        txn_id = self.store.insert("transactions", tick=tick, kind=kind, memo=memo,
                                   created_at=now, currency_code=transaction_currency)

        # For counter_account annotation on 2-leg txns (the common case).
        counter = None
        if len(legs) == 2:
            counter = {legs[0].account_id: legs[1].account_id,
                       legs[1].account_id: legs[0].account_id}

        for leg in legs:
            self.store.execute(
                "UPDATE accounts SET balance_cents = balance_cents + ? WHERE id=?",
                (leg.delta_cents, leg.account_id),
            )
            self.store.insert(
                "ledger_entries", tick=tick, txn_id=txn_id, account_id=leg.account_id,
                delta_cents=leg.delta_cents,
                counter_account_id=(counter.get(leg.account_id) if counter else None),
                memo=leg.memo or memo,
            )
        return txn_id

    def transfer(self, tick: int, from_acct: int, to_acct: int, amount_cents: int,
                 kind: str = "transfer", memo: str = "") -> int:
        """Move money between two accounts. Handles inter-bank reserve settlement.

        A cross-bank deposit move also settles reserves between the two banks so a
        bank's reserves actually drain during a run (TECH-SPEC §9)."""
        if amount_cents <= 0:
            raise LedgerError(f"transfer amount must be positive, got {amount_cents}")
        legs = [Leg(from_acct, -amount_cents, memo), Leg(to_acct, amount_cents, memo)]

        f = self.store.query_one("SELECT bank_id, kind FROM accounts WHERE id=?", (from_acct,))
        t = self.store.query_one("SELECT bank_id, kind FROM accounts WHERE id=?", (to_acct,))
        currencies = self.store.query(
            "SELECT id, currency_code FROM accounts WHERE id IN (?,?)", (from_acct, to_acct))
        if len(currencies) != 2 or len({str(row["currency_code"] or "USD") for row in currencies}) != 1:
            raise LedgerError("direct transfer requires accounts in the same currency; use the FX market")
        if f and t and f["bank_id"] and t["bank_id"] and f["bank_id"] != t["bank_id"] \
                and f["kind"] in ("checking", "savings") and t["kind"] in ("checking", "savings"):
            from_reserve = self._bank_reserve(int(f["bank_id"]))
            to_reserve = self._bank_reserve(int(t["bank_id"]))
            if from_reserve and to_reserve:
                legs += [Leg(from_reserve, -amount_cents, "reserve settlement"),
                         Leg(to_reserve, amount_cents, "reserve settlement")]
        return self.post(tick, kind, legs, memo=memo)

    def _bank_reserve(self, bank_id: int) -> Optional[int]:
        v = self.store.scalar("SELECT reserve_account_id FROM banks WHERE id=?", (bank_id,))
        return int(v) if v is not None else None

    # ── reconciliation (PRD R1) ──────────────────────────────────────────────
    def reconcile(self) -> tuple[bool, dict]:
        """Return (ok, diagnostics). Two checks:
          1. grand sum of all balances == 0 (double-entry conservation);
          2. each account's materialised balance == sum of its ledger deltas.
        """
        grand = int(self.store.scalar("SELECT COALESCE(SUM(balance_cents),0) FROM accounts", default=0))
        currency_sums = {str(row["currency_code"] or "USD"): int(row["total"] or 0)
                         for row in self.store.query(
                             "SELECT currency_code, COALESCE(SUM(balance_cents),0) AS total "
                             "FROM accounts GROUP BY currency_code")}
        mismatches = self.store.query(
            "SELECT a.id AS id, a.label AS label, a.balance_cents AS bal, "
            "       COALESCE(le.total_cents,0) AS recomputed "
            "FROM accounts a "
            "LEFT JOIN account_ledger_totals le ON le.account_id = a.id "
            "WHERE a.balance_cents <> COALESCE(le.total_cents,0)"
        )
        currencies_conserved = all(value == 0 for value in currency_sums.values())
        ok = currencies_conserved and (len(mismatches) == 0)
        diag = {
            "grand_sum_cents": grand,
            "conserved": currencies_conserved,
            "currency_sums": currency_sums,
            "account_mismatches": [
                {"account_id": int(m["id"]), "label": m["label"],
                 "stored": int(m["bal"]), "recomputed": int(m["recomputed"])}
                for m in mismatches
            ],
        }
        return ok, diag

    def total_deposits_cents(self) -> int:
        return int(self.store.scalar(
            "SELECT COALESCE(SUM(balance_cents),0) FROM accounts WHERE kind IN ('checking','savings')",
            default=0))
