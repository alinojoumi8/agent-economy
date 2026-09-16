"""Judgments replace a fixed earnings interval, without a second wage claim.

Accruals form a cents interval for each employment. Payments, actual losses and
earlier novations consume its oldest unpaid cents. Filing fixes the end of a
case's interval; subsequent work and payments retain their separate history.
"""
from __future__ import annotations

import json

from .estates import EstateError
from .ledger import Leg, SYS_GOV


class WageAwards:
    def __init__(self, economy):
        self.e = economy
        self.store = economy.store
        self.ledger = economy.ledger
        self.enabled = economy.engine_semantics_version >= 20

    def scopes(self, matter_id):
        return self.store.query("SELECT * FROM legal_wage_scopes WHERE matter_id=? ORDER BY claim_id", (matter_id,))

    def novated(self, claim_id):
        if not self.enabled:
            return 0
        return self.store.scalar("SELECT COALESCE(SUM(removed_cents),0) FROM wage_claim_novations WHERE claim_id=?", (claim_id,))

    def consumption(self, claim_id, start, end, *, before_transaction=None):
        rows = self.store.query("SELECT transaction_id,kind,gross_cents AS amount FROM wage_settlements WHERE claim_id=? "
            "UNION ALL SELECT transaction_id,'novation',removed_cents FROM wage_claim_novations WHERE claim_id=? AND removed_cents>0 "
            "ORDER BY transaction_id", (claim_id, claim_id))
        offset, paid, consumed, written_off = 0, 0, 0, 0
        for row in rows:
            if before_transaction is not None and row["transaction_id"] >= before_transaction:
                continue
            overlap = max(0, min(end, offset + row["amount"]) - max(start, offset))
            consumed += overlap
            if row["kind"] == "payment":
                paid += overlap
            elif row["kind"] == "write_off":
                written_off += overlap
            offset += row["amount"]
        return paid, end - start - consumed, written_off

    def preview(self, tick, claimant, firm, raw_scopes=None):
        if raw_scopes is None:
            raw_scopes = [{"claim_id": r["id"], "through_accrual_id": r["through_id"]} for r in self.store.query(
                "SELECT c.id,MAX(a.id) AS through_id FROM wage_claims c JOIN wage_claim_holders h ON h.claim_id=c.id "
                "JOIN wage_accruals a ON a.claim_id=c.id WHERE h.ended_tick IS NULL AND h.owner_type='agent' "
                "AND h.owner_id=? AND c.firm_id=? AND a.tick<=? GROUP BY c.id ORDER BY c.id", (claimant, firm, tick))]
            automatic = True
        else:
            automatic = False
        if not isinstance(raw_scopes, list) or not raw_scopes:
            raise EstateError("wage relief requires recorded earned-wage scopes")
        scopes, seen = [], set()
        for raw in raw_scopes:
            if not isinstance(raw, dict) or any(type(raw.get(k)) is not int or raw[k] <= 0 for k in ("claim_id", "through_accrual_id")):
                raise EstateError("wage scope needs positive integer claim_id and through_accrual_id")
            claim_id, through_id = raw["claim_id"], raw["through_accrual_id"]
            if claim_id in seen:
                raise EstateError("wage scopes must identify distinct claims")
            seen.add(claim_id)
            claim = self.store.query_one("SELECT * FROM wage_claims WHERE id=?", (claim_id,))
            holder = self.e.earned_wages.holder(claim_id) if claim else None
            cutoff = self.store.query_one("SELECT * FROM wage_accruals WHERE id=? AND claim_id=? AND tick<=?", (through_id, claim_id, tick))
            if not claim or not holder or (holder["owner_type"], holder["owner_id"], claim["firm_id"]) != ("agent", claimant, firm) or not cutoff:
                raise EstateError("wage scope does not match the claimant, employer and recorded work")
            start = self.store.scalar("SELECT COALESCE(MAX(s.end_cents),0) FROM legal_wage_scopes s "
                "JOIN wage_claim_novations n ON n.scope_id=s.id WHERE s.claim_id=?", (claim_id,))
            end = self.store.scalar("SELECT COALESCE(SUM(earned_cents),0) FROM wage_accruals WHERE claim_id=? AND id<=?", (claim_id, through_id))
            if end <= start or self.consumption(claim_id, start, end)[1] <= 0:
                if automatic:
                    continue
                raise EstateError("selected wage interval has no unpaid, unadjudicated earnings")
            if self.store.scalar("SELECT s.id FROM legal_wage_scopes s JOIN legal_matters m ON m.id=s.matter_id "
                    "WHERE s.claim_id=? AND s.start_cents<? AND s.end_cents>? "
                    "AND m.status NOT IN ('decided','dismissed','settled') LIMIT 1", (claim_id, end, start)):
                raise EstateError("wage interval already has a pending legal matter")
            scopes.append({"claim_id": claim_id, "holder_id": holder["id"], "through_accrual_id": through_id,
                           "start_cents": start, "end_cents": end, "currency_code": claim["currency_code"]})
        if not scopes:
            raise EstateError("no unpaid, unadjudicated wage interval is available")
        if len({r["currency_code"] for r in scopes}) != 1:
            raise EstateError("file separate wage matters for each currency")
        return scopes

    def register(self, tick, matter):
        remedy = json.loads(matter["requested_remedy_json"] or "{}")
        if matter["claim_type"] != "unpaid_wages" and "wage_scopes" not in remedy:
            return
        if (matter["claimant_type"], matter["respondent_type"]) != ("agent", "firm"):
            raise EstateError("wage relief requires a wage holder and its employer")
        if remedy.get("independent_damages") is True:
            raise EstateError("file additional non-wage damages separately from earned-wage relief")
        scopes = self.preview(tick, matter["claimant_id"], matter["respondent_id"], remedy.get("wage_scopes"))
        currency = remedy.get("currency_code", scopes[0]["currency_code"])
        if currency != scopes[0]["currency_code"]:
            raise EstateError("wage relief must use the earned-wage currency")
        for scope in scopes:
            self.store.insert("legal_wage_scopes", matter_id=matter["id"], registered_tick=tick, **scope)

    def prior(self, scope):
        return self.consumption(scope["claim_id"], scope["start_cents"], scope["end_cents"])[0]

    def prior_loss(self, scope):
        return self.consumption(scope["claim_id"], scope["start_cents"], scope["end_cents"])[2]

    def recognize(self, tick, award, scopes):
        if any(s["registered_tick"] > tick for s in scopes):
            raise EstateError("wage adjudication cannot precede the filed earnings interval")
        currency = award["currency_code"]
        payable = self.ledger.create_account("firm", award["respondent_id"], "legal_wage_payable", currency_code=currency,
                                              label=f"wage-award:{award['id']}:payable")
        receivable = self.ledger.create_account("agent", award["claimant_id"], "legal_wage_receivable", currency_code=currency,
                                                 label=f"wage-award:{award['id']}:receivable")
        owed = award["awarded_cents"] - award["credited_cents"] - award["credited_loss_cents"]
        legs = [Leg(payable, -owed, "adjudicated gross compensation"), Leg(receivable, owed, "gross compensation receivable")] if owed else []
        links = []
        for scope in scopes:
            claim = self.store.query_one("SELECT * FROM wage_claims WHERE id=?", (scope["claim_id"],))
            holder = self.store.query_one("SELECT * FROM wage_claim_holders WHERE id=?", (scope["holder_id"],))
            prior, removed, discharged = self.consumption(claim["id"], scope["start_cents"], scope["end_cents"])
            if removed:
                legs += [Leg(claim["payable_account_id"], removed, "replace disputed wage payable"),
                         Leg(holder["receivable_account_id"], -removed, "replace disputed wage receivable")]
            links.append((scope, prior, removed, discharged))
        transaction = self.ledger.post(tick, "wage_award_novation", legs, memo=f"wage award {award['id']}") if legs else None
        self.store.insert("legal_wage_awards", award_id=award["id"], payable_account_id=payable,
                          receivable_account_id=receivable, recognition_transaction_id=transaction)
        for scope, prior, removed, discharged in links:
            self.store.insert("wage_claim_novations", award_id=award["id"], scope_id=scope["id"], claim_id=scope["claim_id"],
                              prior_paid_cents=prior, prior_written_off_cents=discharged, removed_cents=removed, transaction_id=transaction)

    def settle(self, tick, award):
        right = self.store.query_one("SELECT * FROM legal_wage_awards WHERE award_id=?", (award["id"],))
        if right is None:
            raise EstateError("wage award lacks its compensation accounts")
        amount = min(self.e.legal_awards.remaining(award), max(0, self.ledger.balance(award["source_account_id"])))
        if not amount:
            return 0
        with self.e.estate_cases._batch():
            rate = max(0, min(10_000, int(self.store.metric_latest("tax_rate_bps", 0))))
            tax = amount * rate // 10_000
            legs = [Leg(award["source_account_id"], -amount, "gross wage award payment"),
                    Leg(right["payable_account_id"], amount, "release compensation payable"),
                    Leg(right["receivable_account_id"], -amount, "release compensation receivable")]
            if amount > tax:
                legs.append(Leg(award["destination_account_id"], amount - tax, "net wage award payment"))
            if tax:
                legs.append(Leg(self.ledger.system_account(SYS_GOV, currency_code=award["currency_code"]), tax, "income tax"))
            transaction = self.ledger.post(tick, "wage_award_payment", legs, memo=f"collect wage award {award['id']}")
            self.e.legal_awards.note_payment(tick, award["id"], amount, transaction, tax=tax)
        return amount

    def process_due(self, tick, *, firm_id=None, claimant_id=None):
        if not self.enabled:
            return
        for award in self.store.query("SELECT a.* FROM legal_awards a JOIN legal_wage_awards w ON w.award_id=a.id "
                "WHERE (? IS NULL OR a.respondent_id=?) AND (? IS NULL OR a.claimant_id=?) ORDER BY a.id",
                (firm_id, firm_id, claimant_id, claimant_id)):
            if self.e.legal_awards.remaining(award) > 0:
                self.settle(tick, award)

    def check_invariants(self):
        if not self.enabled:
            return
        for scope in self.store.query("SELECT * FROM legal_wage_scopes ORDER BY id"):
            matter = self.store.query_one("SELECT * FROM legal_matters WHERE id=?", (scope["matter_id"],))
            claim = self.store.query_one("SELECT * FROM wage_claims WHERE id=?", (scope["claim_id"],))
            holder = self.store.query_one("SELECT * FROM wage_claim_holders WHERE id=?", (scope["holder_id"],))
            cutoff = self.store.query_one("SELECT * FROM wage_accruals WHERE id=?", (scope["through_accrual_id"],))
            end = self.store.scalar("SELECT COALESCE(SUM(earned_cents),0) FROM wage_accruals WHERE claim_id=? AND id<=?",
                                     (claim["id"], scope["through_accrual_id"]))
            if (matter["claimant_type"], matter["claimant_id"], matter["respondent_type"], matter["respondent_id"], matter["filed_tick"]) != (
                    holder["owner_type"], holder["owner_id"], "firm", claim["firm_id"], scope["registered_tick"]) or holder["claim_id"] != claim["id"]:
                raise EstateError("wage scope has different parties or filing time")
            if scope["currency_code"] != claim["currency_code"] or cutoff["claim_id"] != claim["id"] or cutoff["tick"] > scope["registered_tick"] or end != scope["end_cents"]:
                raise EstateError("wage scope extends beyond its recorded earned work")
        for right in self.store.query("SELECT * FROM legal_wage_awards ORDER BY id"):
            award = self.store.query_one("SELECT * FROM legal_awards WHERE id=?", (right["award_id"],))
            links = self.store.query("SELECT n.*,s.holder_id,s.start_cents,s.end_cents,s.matter_id,s.currency_code FROM wage_claim_novations n "
                "JOIN legal_wage_scopes s ON s.id=n.scope_id WHERE n.award_id=? ORDER BY n.claim_id", (award["id"],))
            if not links or any((n["matter_id"], n["currency_code"]) != (award["matter_id"], award["currency_code"]) for n in links):
                raise EstateError("wage award lacks its filed compensation intervals")
            if self.store.scalar("SELECT id FROM legal_award_obligations WHERE award_id=?", (award["id"],)):
                raise EstateError("wage compensation duplicates an independent contract award")
            payable = self.store.query_one("SELECT * FROM accounts WHERE id=?", (right["payable_account_id"],))
            receivable = self.store.query_one("SELECT * FROM accounts WHERE id=?", (right["receivable_account_id"],))
            if (payable["owner_type"], payable["owner_id"], payable["kind"], payable["currency_code"]) != (
                    "firm", award["respondent_id"], "legal_wage_payable", award["currency_code"]) or (
                    receivable["owner_type"], receivable["owner_id"], receivable["kind"], receivable["currency_code"]) != (
                    "agent", award["claimant_id"], "legal_wage_receivable", award["currency_code"]):
                raise EstateError("wage award compensation accounts have different parties or currency")
            owed = self.e.legal_awards.remaining(award)
            if payable["balance_cents"] != -owed or receivable["balance_cents"] != owed:
                raise EstateError("wage award ledger balance does not match its unpaid compensation")
            recognition = award["awarded_cents"] - award["credited_cents"] - award["credited_loss_cents"]
            expected = {payable["id"]: -recognition, receivable["id"]: recognition}
            for link in links:
                claim = self.store.query_one("SELECT * FROM wage_claims WHERE id=?", (link["claim_id"],))
                holder = self.store.query_one("SELECT * FROM wage_claim_holders WHERE id=?", (link["holder_id"],))
                if link["transaction_id"] != right["recognition_transaction_id"]:
                    raise EstateError("wage novation has a different recognition transaction")
                prior, unpaid, discharged = self.consumption(claim["id"], link["start_cents"], link["end_cents"], before_transaction=link["transaction_id"])
                if (prior, unpaid, discharged) != (link["prior_paid_cents"], link["removed_cents"], link["prior_written_off_cents"]):
                    raise EstateError("wage novation duplicates payment or misstates the replaced earnings")
                previous = self.store.scalar("SELECT COALESCE(MAX(s.end_cents),0) FROM wage_claim_novations n "
                    "JOIN legal_wage_scopes s ON s.id=n.scope_id WHERE n.claim_id=? AND n.id<?", (claim["id"], link["id"]))
                if link["start_cents"] != previous:
                    raise EstateError("wage adjudication overlaps or skips an earlier earnings interval")
                expected[claim["payable_account_id"]] = expected.get(claim["payable_account_id"], 0) + link["removed_cents"]
                expected[holder["receivable_account_id"]] = expected.get(holder["receivable_account_id"], 0) - link["removed_cents"]
            expected = {k: v for k, v in expected.items() if v}
            if expected:
                if self.e.cash_estates._transaction_legs(right["recognition_transaction_id"], award["tick"], award["currency_code"]) != expected:
                    raise EstateError("wage judgment and noncash rights replacement disagree")
            elif right["recognition_transaction_id"] is not None:
                raise EstateError("fully credited wage award has an unexplained ledger movement")
