"""Wages earned from recorded work: claims first, cash only on settlement."""
from __future__ import annotations

from .ledger import Leg, SYS_GOV


class WageClaimError(ValueError):
    pass


class EarnedWages:
    def __init__(self, economy, normal_workday_minutes=480):
        self.e = economy
        self.store = economy.store
        self.ledger = economy.ledger
        self.normal_workday_minutes = normal_workday_minutes

    def holder(self, claim_id):
        holder = self.store.query_one(
            "SELECT * FROM wage_claim_holders WHERE claim_id=? AND ended_tick IS NULL", (claim_id,))
        if holder is None:
            raise WageClaimError("wage claim has no current beneficiary")
        return holder

    def outstanding(self, claim):
        novated = self.e.wage_awards.novated(claim["id"]) if self.e.engine_semantics_version >= 20 else 0
        return int(claim["accrued_cents"]) - int(claim["paid_cents"]) - int(claim["written_off_cents"]) - novated

    def _open_claim(self, tick, employment):
        claim = self.store.query_one("SELECT * FROM wage_claims WHERE employment_id=?", (employment["id"],))
        if claim:
            if claim["closed_tick"] is not None:
                raise WageClaimError("cannot accrue wages on a closed employment claim")
            return claim
        firm = self.e.firms.get(employment["firm_id"])
        if not firm or firm["account_id"] is None:
            raise WageClaimError("wage employer lacks an operating account")
        currency = self.store.scalar("SELECT currency_code FROM accounts WHERE id=?", (firm["account_id"],))
        interval = int(employment["pay_interval_ticks"])
        if interval <= 0 or self.normal_workday_minutes <= 0:
            raise WageClaimError("wage contract requires a positive period and normal workday")
        payable = self.ledger.create_account("firm", firm["id"], "wage_payable",
            label=f"wage-payable:{employment['id']}", currency_code=currency)
        receivable = self.ledger.create_account("agent", employment["agent_id"], "wage_receivable",
            label=f"wage-receivable:{employment['id']}:origin", currency_code=currency)
        claim_id = self.store.insert("wage_claims", employment_id=employment["id"],
            employee_id=employment["agent_id"], firm_id=firm["id"], currency_code=currency,
            payable_account_id=payable, denominator=interval * self.normal_workday_minutes, opened_tick=tick)
        self.store.insert("wage_claim_holders", claim_id=claim_id, owner_type="agent",
            owner_id=employment["agent_id"], receivable_account_id=receivable, started_tick=tick)
        return self.store.query_one("SELECT * FROM wage_claims WHERE id=?", (claim_id,))

    def accrue(self, tick, allocation_id):
        """Only a persisted, delivered employment allocation can earn a wage."""
        with self.store.savepoint("earned_wage_accrual"):
            previous = self.store.query_one("SELECT * FROM wage_accruals WHERE allocation_id=?", (allocation_id,))
            if previous:
                if previous["tick"] != tick:
                    raise WageClaimError("wage allocation belongs to another day")
                return dict(previous)
            work = self.store.query_one("SELECT * FROM time_allocations WHERE id=?", (allocation_id,))
            if (not work or work["tick"] != tick or work["kind"] != "employment"
                    or work["reference_type"] != "employment" or work["delivered_minutes"] <= 0):
                raise WageClaimError("wages require delivered employment time")
            employment = self.store.query_one("SELECT * FROM employments WHERE id=?", (work["reference_id"],))
            if (not employment or employment["agent_id"] != work["agent_id"]
                    or employment["status"] != "active"):
                raise WageClaimError("work does not belong to an active employment")
            claim = self._open_claim(tick, employment)
            expected = int(employment["pay_interval_ticks"]) * self.normal_workday_minutes
            if expected != claim["denominator"]:
                raise WageClaimError("changed wage period requires a new employment contract")
            wage = int(employment["wage_cents"])
            if wage < 0:
                raise WageClaimError("period wage cannot be negative")
            earned, remainder = divmod(wage * int(work["delivered_minutes"]) +
                                       int(claim["remainder_numerator"]), int(claim["denominator"]))
            holder = self.holder(claim["id"])
            transaction = None
            if earned:
                transaction = self.ledger.post(tick, "wage_accrual", [
                    Leg(claim["payable_account_id"], -earned, "earned wage payable"),
                    Leg(holder["receivable_account_id"], earned, "earned wage receivable"),
                ], memo=f"employment {employment['id']} earned from allocation {allocation_id}")
            self.store.update("wage_claims", claim["id"], accrued_cents=claim["accrued_cents"] + earned,
                              remainder_numerator=remainder)
            accrual_id = self.store.insert("wage_accruals", tick=tick, allocation_id=allocation_id,
                claim_id=claim["id"], worked_minutes=work["delivered_minutes"], period_wage_cents=wage,
                earned_cents=earned, remainder_numerator=remainder, transaction_id=transaction)
            self.store.log_event(tick, "wage_earned", {
                "agent_id": employment["agent_id"], "firm_id": employment["firm_id"],
                "employment_id": employment["id"], "claim_id": claim["id"],
                "worked_minutes": work["delivered_minutes"], "earned_cents": earned,
                "currency_code": claim["currency_code"], "non_cash": True,
            }, phase="NIGHT_CLOSE", subject_type="agent", subject_id=employment["agent_id"])
            return dict(self.store.query_one("SELECT * FROM wage_accruals WHERE id=?", (accrual_id,)))

    def _cash_target(self, holder, currency):
        if holder["owner_type"] == "system":
            return self.ledger.system_account(SYS_GOV, currency_code=currency)
        return self.e.regions._wallet("agent", holder["owner_id"], currency, create=True)

    def settle(self, tick, claim_id):
        """Pay available same-currency cash; leave unpaid earned claims explicit."""
        with self.store.savepoint("earned_wage_payment"):
            claim = self.store.query_one("SELECT * FROM wage_claims WHERE id=?", (claim_id,))
            if not claim:
                raise WageClaimError("unknown wage claim")
            owed = self.outstanding(claim)
            if owed == 0:
                return 0
            firm = self.e.firms.get(claim["firm_id"])
            if not firm or firm["account_id"] is None:
                raise WageClaimError("wage employer lacks an operating account")
            currency = self.store.scalar("SELECT currency_code FROM accounts WHERE id=?", (firm["account_id"],))
            if currency != claim["currency_code"]:
                raise WageClaimError("wage settlement cannot convert currencies")
            gross = min(owed, max(0, self.ledger.balance(firm["account_id"])))
            if gross == 0:
                return 0
            holder = self.holder(claim_id)
            rate = max(0, min(10_000, int(self.store.metric_latest("tax_rate_bps", 0))))
            tax = gross * rate // 10_000 if holder["owner_type"] == "agent" else 0
            target = self._cash_target(holder, currency)
            legs = [Leg(firm["account_id"], -gross, "gross wage payment"),
                    Leg(claim["payable_account_id"], gross, "release wage payable"),
                    Leg(holder["receivable_account_id"], -gross, "release wage receivable"),
                    Leg(target, gross - tax, "net wages")]
            if tax:
                legs.append(Leg(self.ledger.system_account(SYS_GOV, currency_code=currency), tax, "income tax"))
            transaction = self.ledger.post(tick, "wage", legs, memo=f"settle employment {claim['employment_id']} wages")
            self.store.update("wage_claims", claim_id, paid_cents=claim["paid_cents"] + gross)
            self.store.insert("wage_settlements", tick=tick, claim_id=claim_id, holder_id=holder["id"],
                              kind="payment", gross_cents=gross, tax_cents=tax, transaction_id=transaction)
            self.store.log_event(tick, "wage_paid", {
                "firm_id": claim["firm_id"], "agent_id": claim["employee_id"],
                "beneficiary_type": holder["owner_type"], "beneficiary_id": holder["owner_id"],
                "employment_id": claim["employment_id"], "claim_id": claim_id,
                "wage_cents": gross, "tax_cents": tax, "net_cents": gross - tax,
                "currency_code": currency, "unpaid_cents": owed - gross,
            }, phase="NIGHT_CLOSE")
            return gross

    def _close_paid_exit(self, tick, claim_id):
        claim = self.store.query_one("SELECT * FROM wage_claims WHERE id=?", (claim_id,))
        employment = self.store.query_one("SELECT status FROM employments WHERE id=?", (claim["employment_id"],))
        if claim["closed_tick"] is None and employment["status"] != "active" and self.outstanding(claim) == 0:
            self.store.update("wage_claims", claim_id, closed_tick=tick)
            self.store.log_event(tick, "wage_claim_closed", {
                "claim_id": claim_id, "employment_id": claim["employment_id"],
                "discarded_subcent_numerator": claim["remainder_numerator"],
                "denominator": claim["denominator"], "rounding_policy": "floor_at_employment_exit",
            }, phase="NIGHT_CLOSE")

    def process_due(self, tick):
        if self.e.engine_semantics_version >= 20:
            self.e.wage_awards.process_due(tick)
        distressed = set()
        for row in self.store.query(
                "SELECT c.id,c.firm_id,c.employment_id,e.next_pay_tick,e.pay_interval_ticks,e.status "
                "FROM wage_claims c JOIN employments e ON e.id=c.employment_id "
                "WHERE c.closed_tick IS NULL AND (e.next_pay_tick<=? OR e.status<>'active') ORDER BY c.employment_id", (tick,)):
            firm = self.e.firms.get(row["firm_id"])
            if firm["status"] == "bankrupt":
                self.write_off_firm(tick, row["firm_id"])
                self._close_paid_exit(tick, row["id"])
                continue
            self.settle(tick, row["id"])
            claim = self.store.query_one("SELECT * FROM wage_claims WHERE id=?", (row["id"],))
            owed = self.outstanding(claim)
            if owed:
                if row["status"] == "active" and tick >= row["next_pay_tick"] + row["pay_interval_ticks"]:
                    distressed.add(row["firm_id"])
                self.store.log_event(tick, "wage_missed", {
                    "firm_id": row["firm_id"], "agent_id": claim["employee_id"],
                    "employment_id": row["employment_id"], "claim_id": row["id"],
                    "wage_cents": owed, "claim_preserved": True,
                    **({"through_accrual_id": self.store.scalar("SELECT MAX(id) FROM wage_accruals WHERE claim_id=?", (row["id"],)),
                        "currency_code": claim["currency_code"]} if self.e.engine_semantics_version >= 20 else {}),
                }, phase="NIGHT_CLOSE", importance=1.5)
            elif row["status"] == "active":
                self.store.update("employments", row["employment_id"], next_pay_tick=tick + row["pay_interval_ticks"])
            self._close_paid_exit(tick, row["id"])
        # One contractual period of arrears precedes the existing insolvency
        # rule. A shortage on payday alone does not erase an earned claim.
        for firm_id in sorted(distressed):
            self.e.firms._maybe_bankrupt(tick, firm_id)

    def collect_before_death(self, tick, agent_id):
        if self.e.engine_semantics_version >= 20:
            self.e.wage_awards.process_due(tick, claimant_id=agent_id)
        for row in self.store.query(
                "SELECT claim_id FROM wage_claim_holders WHERE owner_type='agent' AND owner_id=? "
                "AND ended_tick IS NULL ORDER BY claim_id", (agent_id,)):
            self.settle(tick, row["claim_id"])

    def inherit(self, tick, agent_id, heir_id):
        """Move the receivable, never monetize it; preserve prior holder identity."""
        with self.store.savepoint("inherit_wage_claims"):
            for holder in self.store.query(
                    "SELECT h.*,c.currency_code,c.closed_tick FROM wage_claim_holders h "
                    "JOIN wage_claims c ON c.id=h.claim_id WHERE h.owner_type='agent' AND h.owner_id=? "
                    "AND h.ended_tick IS NULL AND c.closed_tick IS NULL ORDER BY c.id", (agent_id,)):
                owner_type = "agent" if heir_id is not None else "system"
                target = self.ledger.create_account(owner_type, heir_id, "wage_receivable",
                    label=f"wage-receivable:{holder['claim_id']}:estate:{agent_id}:{tick}",
                    currency_code=holder["currency_code"])
                amount = self.ledger.balance(holder["receivable_account_id"])
                if amount:
                    self.ledger.transfer(tick, holder["receivable_account_id"], target, amount,
                                         kind="wage_claim_inheritance", memo=f"estate wage claim {holder['claim_id']}")
                self.store.update("wage_claim_holders", holder["id"], ended_tick=tick)
                self.store.insert("wage_claim_holders", claim_id=holder["claim_id"], owner_type=owner_type,
                                  owner_id=heir_id, receivable_account_id=target, started_tick=tick)
                self.store.log_event(tick, "wage_claim_inherited", {
                    "agent_id": agent_id, "heir_id": heir_id, "claim_id": holder["claim_id"],
                    "receivable_cents": amount, "currency_code": holder["currency_code"], "cash_created_cents": 0,
                }, phase="NIGHT_CLOSE")

    def write_off_firm(self, tick, firm_id):
        with self.store.savepoint("bankrupt_wage_claims"):
            for claim in self.store.query("SELECT * FROM wage_claims WHERE firm_id=? AND closed_tick IS NULL ORDER BY id", (firm_id,)):
                owed = self.outstanding(claim)
                if not owed:
                    continue
                holder = self.holder(claim["id"])
                transaction = self.ledger.post(tick, "wage_claim_write_off", [
                    Leg(claim["payable_account_id"], owed, "extinguish final unpaid wages"),
                    Leg(holder["receivable_account_id"], -owed, "uncollectible wage claim"),
                ], memo=f"bankrupt firm {firm_id} wage claim {claim['id']}")
                self.store.update("wage_claims", claim["id"], written_off_cents=claim["written_off_cents"] + owed)
                self.store.insert("wage_settlements", tick=tick, claim_id=claim["id"], holder_id=holder["id"],
                                  kind="write_off", gross_cents=owed, tax_cents=0, transaction_id=transaction)
                self.store.log_event(tick, "wage_claim_written_off", {
                    "firm_id": firm_id, "claim_id": claim["id"], "cents": owed,
                    "beneficiary_type": holder["owner_type"], "beneficiary_id": holder["owner_id"],
                    "currency_code": claim["currency_code"],
                }, phase="NIGHT_CLOSE")
            if self.e.engine_semantics_version >= 20:
                self.e.legal_awards.write_off_firm(tick, firm_id)

    def check_invariants(self):
        for claim in self.store.query("SELECT * FROM wage_claims ORDER BY id"):
            holder = self.holder(claim["id"])
            owed = self.outstanding(claim)
            if owed < 0:
                raise WageClaimError("wage payments, losses and novations exceed earned work")
            accrued = self.store.scalar("SELECT COALESCE(SUM(earned_cents),0) FROM wage_accruals WHERE claim_id=?", (claim["id"],))
            if accrued != claim["accrued_cents"]:
                raise WageClaimError("daily accruals do not reconcile to the wage claim")
            if self.ledger.balance(claim["payable_account_id"]) != -owed or self.ledger.balance(holder["receivable_account_id"]) != owed:
                raise WageClaimError("wage claim and ledger balances disagree")
            for kind, field in (("payment", "paid_cents"), ("write_off", "written_off_cents")):
                settled = self.store.scalar("SELECT COALESCE(SUM(gross_cents),0) FROM wage_settlements WHERE claim_id=? AND kind=?", (claim["id"], kind))
                if settled != claim[field]:
                    raise WageClaimError("wage settlements do not reconcile")
            for previous in self.store.query("SELECT receivable_account_id FROM wage_claim_holders WHERE claim_id=? AND ended_tick IS NOT NULL", (claim["id"],)):
                if self.ledger.balance(previous["receivable_account_id"]) != 0:
                    raise WageClaimError("former wage beneficiary retains a duplicate claim")
