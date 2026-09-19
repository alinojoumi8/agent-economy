"""Recorded monetary judgments and settlements, including estate succession.

For explicitly linked monetary obligations, an award states total adjudicated
entitlement: their earlier payments count toward it and their remaining claims
are replaced. Unrelated additional damages require an explicit declaration.
"""
from __future__ import annotations

import json

from .estates import EstateError
from .ledger import Leg, SYS_GOV


class LegalAwards:
    def __init__(self, economy):
        self.e = economy
        self.store = economy.store
        self.ledger = economy.ledger
        self.enabled = economy.engine_semantics_version >= 20

    def linked_obligations(self, matter, remedy):
        requested = json.loads(matter["requested_remedy_json"] or "{}")
        identifiers = remedy.get("obligation_ids", requested.get("obligation_ids"))
        if identifiers is None:
            identifiers = [r["obligation_id"] for r in self.store.query(
                "SELECT DISTINCT CAST(json_extract(e.payload_json,'$.obligation_id') AS INTEGER) AS obligation_id "
                "FROM legal_filings f JOIN json_each(f.evidence_event_ids_json) j JOIN events e ON e.id=j.value "
                "WHERE f.matter_id=? AND f.admitted=1 AND e.kind IN ('obligation_breached','obligation_performed') "
                "AND json_extract(e.payload_json,'$.obligation_id') IS NOT NULL ORDER BY obligation_id", (matter["id"],))]
        if not isinstance(identifiers, list) or any(type(i) is not int or i <= 0 for i in identifiers) or len(set(identifiers)) != len(identifiers):
            raise EstateError("award obligation_ids must contain distinct positive integers")
        obligations = []
        for identifier in sorted(identifiers):
            row = self.store.query_one("SELECT * FROM obligations WHERE id=?", (identifier,))
            if row is None or row["obligation_type"] not in ("payment", "indemnity") or (row["amount_cents"] or 0) <= 0 or (
                    row["contract_id"], row["obligor_type"], row["obligor_id"], row["obligee_type"], row["obligee_id"]) != (
                    matter["contract_id"], matter["respondent_type"], matter["respondent_id"], matter["claimant_type"], matter["claimant_id"]):
                raise EstateError("award obligation does not match the matter and monetary parties")
            if self.store.scalar("SELECT id FROM legal_award_obligations WHERE obligation_id=?", (identifier,)):
                raise EstateError("obligation already belongs to a recorded award")
            obligations.append(row)
        if not obligations and remedy.get("independent_damages") is not True and self.store.scalar(
                "SELECT id FROM obligations WHERE contract_id=? AND obligor_type=? AND obligor_id=? "
                "AND obligee_type=? AND obligee_id=? AND obligation_type IN ('payment','indemnity') "
                "AND status IN ('pending','breached') LIMIT 1",
                (matter["contract_id"], matter["respondent_type"], matter["respondent_id"], matter["claimant_type"], matter["claimant_id"])):
            raise EstateError("identify the monetary obligation_ids being replaced, or declare independent_damages=true")
        return obligations

    def _currency(self, matter, remedy, obligations):
        requested = json.loads(matter["requested_remedy_json"] or "{}")
        currency = remedy.get("currency_code", requested.get("currency_code"))
        currencies = {row["currency_code"] for row in obligations}
        if currency is None and len(currencies) == 1:
            currency = next(iter(currencies))
        if currency is None:
            account = self.e.legal._entity_account(matter["respondent_type"], matter["respondent_id"])
            currency = self.store.scalar("SELECT currency_code FROM accounts WHERE id=?", (account,))
        if not isinstance(currency, str) or not currency or (currencies and currencies != {currency}):
            raise EstateError("award needs one explicit currency matching its obligations")
        return currency

    def _account(self, kind, person, currency, *, creditor=False):
        if creditor:
            return self.e.estate_cases._creditor_account(kind, person, currency)
        kind = "gov" if kind == "government" else kind
        return self.store.scalar("SELECT id FROM accounts WHERE owner_type=? AND owner_id=? AND currency_code=? "
            "AND kind IN ('checking','savings','fx','treasury') ORDER BY CASE kind WHEN 'checking' THEN 0 ELSE 1 END,id LIMIT 1",
            (kind, person, currency))

    def validate(self, matter, remedy):
        if (matter["claimant_type"], matter["claimant_id"]) == (matter["respondent_type"], matter["respondent_id"]):
            return "monetary relief requires different parties"
        try:
            scopes = self.e.wage_awards.scopes(matter["id"])
            if scopes:
                if remedy.get("independent_damages") is True or remedy.get("obligation_ids"):
                    raise EstateError("wage compensation and other damages require separate matters")
                if "wage_scopes" in remedy and remedy["wage_scopes"] != [
                        {"claim_id": s["claim_id"], "through_accrual_id": s["through_accrual_id"]} for s in scopes]:
                    raise EstateError("judgment cannot change the filed earnings interval")
                self._currency(matter, remedy, scopes)
            else:
                self._currency(matter, remedy, self.linked_obligations(matter, remedy))
                if remedy.get("independent_damages") is not True and self.store.scalar(
                        "SELECT e.id FROM legal_filings f JOIN json_each(f.evidence_event_ids_json) j JOIN events e ON e.id=j.value "
                        "WHERE f.matter_id=? AND f.admitted=1 AND e.kind IN ('wage_missed','wage_earned','wage_paid') "
                        "AND json_extract(e.payload_json,'$.claim_id') IS NOT NULL LIMIT 1", (matter["id"],)):
                    raise EstateError("earned-wage damages require a filed wage scope; additional non-wage damages must be explicit")
        except EstateError as error:
            return str(error)
        return None

    def _prior_obligation_payments(self, obligation):
        payments = {row["transaction_id"] for row in self.store.query(
            "SELECT d.transaction_id FROM estate_disbursements d JOIN estate_claims c ON c.id=d.claim_id "
            "WHERE c.kind='contract_payment' AND c.source_id=?", (obligation["id"],))}
        if obligation["transaction_id"] is not None:
            payments.add(obligation["transaction_id"])
        total = 0
        for transaction in sorted(payments):
            total += self.store.scalar("SELECT COALESCE(SUM(l.delta_cents),0) FROM ledger_entries l JOIN accounts a ON a.id=l.account_id "
                "WHERE l.txn_id=? AND a.owner_type=? AND a.owner_id=? AND a.currency_code=? "
                "AND a.kind IN ('checking','savings','fx','treasury')",
                (transaction, "gov" if obligation["obligee_type"] == "government" else obligation["obligee_type"],
                 obligation["obligee_id"], obligation["currency_code"]))
        if not 0 <= total <= obligation["amount_cents"]:
            raise EstateError("linked obligation's prior payments do not reconcile")
        return total

    def paid(self, award_id):
        return self.store.scalar("SELECT COALESCE(SUM(amount_cents),0) FROM legal_award_payments WHERE award_id=?", (award_id,))

    def written_off(self, award_id):
        return self.store.scalar("SELECT COALESCE(SUM(amount_cents),0) FROM legal_award_losses WHERE award_id=?", (award_id,))

    def remaining(self, award):
        return award["awarded_cents"] - award["credited_cents"] - award["credited_loss_cents"] - self.paid(award["id"]) - self.written_off(award["id"])

    def note_payment(self, tick, award_id, amount, transaction, disbursement=None, *, tax=0):
        award = self.store.query_one("SELECT * FROM legal_awards WHERE id=?", (award_id,))
        if award is None or amount <= 0 or amount > self.remaining(award) or tick < award["tick"] or not 0 <= tax <= amount:
            raise EstateError("award collection exceeds its recorded unpaid amount")
        return self.store.insert("legal_award_payments", award_id=award_id, tick=tick, amount_cents=amount,
                                 transaction_id=transaction, estate_disbursement_id=disbursement, tax_cents=tax)

    def collect_cash(self, tick, award):
        source = award["source_account_id"]
        paid = min(self.remaining(award), max(0, self.ledger.balance(source))) if source is not None else 0
        if paid:
            transaction = self.ledger.transfer(tick, source, award["destination_account_id"], paid,
                kind="legal_damages", memo=f"matter {award['matter_id']} damages")
            self.note_payment(tick, award["id"], paid, transaction)
            return transaction
        return None

    def collect_firm_cash_awards(self, tick, firm_id):
        with self.e.estate_cases._batch():
            for award in self.store.query("SELECT a.* FROM legal_awards a WHERE a.respondent_type='firm' AND a.respondent_id=? "
                    "AND NOT EXISTS (SELECT 1 FROM legal_wage_awards w WHERE w.award_id=a.id) ORDER BY a.id", (firm_id,)):
                self.collect_cash(tick, award)

    def write_off_firm(self, tick, firm_id):
        firm = self.e.firms.get(firm_id)
        if not firm or firm["status"] != "bankrupt" or firm["bankrupt_tick"] is None or firm["bankrupt_tick"] > tick:
            raise EstateError("award losses require a recorded firm bankruptcy")
        with self.e.estate_cases._batch():
            for award in self.store.query("SELECT * FROM legal_awards WHERE respondent_type='firm' AND respondent_id=? ORDER BY id", (firm_id,)):
                owed = self.remaining(award)
                if not owed:
                    continue
                right = self.store.query_one("SELECT * FROM legal_wage_awards WHERE award_id=?", (award["id"],))
                transaction = self.ledger.post(tick, "wage_award_write_off", [
                    Leg(right["payable_account_id"], owed, "extinguish compensation payable"),
                    Leg(right["receivable_account_id"], -owed, "uncollectible compensation"),
                ], memo=f"bankrupt firm {firm_id} award {award['id']}") if right else None
                self.store.insert("legal_award_losses", award_id=award["id"], tick=tick, reason="firm_bankruptcy",
                                  amount_cents=owed, transaction_id=transaction)
                self.store.log_event(tick, "legal_award_written_off", {"award_id": award["id"], "firm_id": firm_id,
                    "amount_cents": owed, "currency_code": award["currency_code"], "reason": "firm_bankruptcy"}, phase="NIGHT_CLOSE")

    def issue(self, tick, matter, remedy, *, basis):
        if tick < matter["filed_tick"]:
            raise EstateError("award cannot precede its legal matter")
        error = self.validate(matter, remedy)
        if error:
            raise EstateError(error)
        if self.store.scalar("SELECT id FROM legal_awards WHERE matter_id=?", (matter["id"],)):
            raise EstateError("matter already has a recorded monetary award")
        scopes = self.e.wage_awards.scopes(matter["id"])
        obligations = [] if scopes else self.linked_obligations(matter, remedy)
        currency = self._currency(matter, remedy, scopes or obligations)
        amount = int(remedy["amount_cents"])
        prior = {row["id"]: self._prior_obligation_payments(row) for row in obligations}
        with self.e.estate_cases._batch():
            source = self._account(matter["respondent_type"], matter["respondent_id"], currency)
            target = self._account(matter["claimant_type"], matter["claimant_id"], currency, creditor=True)
            credited = min(amount, sum(prior.values()) + sum(self.e.wage_awards.prior(s) for s in scopes))
            credited_loss = min(amount - credited, sum(self.e.wage_awards.prior_loss(s) for s in scopes))
            award_id = self.store.insert("legal_awards", matter_id=matter["id"], tick=tick, basis=basis,
                claimant_type=matter["claimant_type"], claimant_id=matter["claimant_id"],
                respondent_type=matter["respondent_type"], respondent_id=matter["respondent_id"],
                currency_code=currency, awarded_cents=amount, credited_cents=credited, credited_loss_cents=credited_loss,
                source_account_id=source, destination_account_id=target)
            for obligation in obligations:
                self.store.insert("legal_award_obligations", award_id=award_id, obligation_id=obligation["id"],
                                  original_amount_cents=obligation["amount_cents"], prior_paid_cents=prior[obligation["id"]])
                self.e.estate_cases.release_obligation(tick, obligation["id"], award_id=award_id)
                self.store.update("obligations", obligation["id"], status="adjudicated")
            award = self.store.query_one("SELECT * FROM legal_awards WHERE id=?", (award_id,))
            if scopes:
                self.e.wage_awards.recognize(tick, award, scopes)
            estate = self.store.query_one("SELECT * FROM estate_cases WHERE deceased_agent_id=?", (matter["respondent_id"],)) if matter["respondent_type"] == "agent" else None
            claim_id, paid, transaction = None, 0, None
            if estate:
                claim_id = self.e.estate_cases.register_award(tick, estate, award)
            elif matter["respondent_type"] == "firm" and self.e.firms.get(matter["respondent_id"])["status"] == "bankrupt":
                self.write_off_firm(tick, matter["respondent_id"])
            elif scopes:
                paid = self.e.wage_awards.settle(tick, award)
                transaction = self.store.scalar("SELECT transaction_id FROM legal_award_payments WHERE award_id=? ORDER BY id DESC LIMIT 1", (award_id,))
            elif source is not None:
                transaction = self.collect_cash(tick, award)
                paid = self.paid(award_id)
            return {"type": "damages", "award_id": award_id, "awarded_cents": amount,
                    "credited_cents": credited, "paid_cents": paid, "unpaid_cents": self.remaining(award),
                    "currency_code": currency, "transaction_id": transaction, "estate_claim_id": claim_id,
                    "payment_basis": "gross_wages" if scopes else "cash", "written_off_cents": self.written_off(award_id),
                    "credited_loss_cents": credited_loss,
                    "tax_cents": self.store.scalar("SELECT COALESCE(SUM(tax_cents),0) FROM legal_award_payments WHERE award_id=?", (award_id,))}

    def check_invariants(self):
        if not self.enabled:
            return
        for award in self.store.query("SELECT * FROM legal_awards ORDER BY id"):
            matter = self.store.query_one("SELECT * FROM legal_matters WHERE id=?", (award["matter_id"],))
            if matter is None or any(award[k] != matter[k] for k in ("claimant_type", "claimant_id", "respondent_type", "respondent_id")):
                raise EstateError("award parties disagree with their legal matter")
            if award["basis"] == "decision":
                decision = self.store.query_one("SELECT * FROM legal_decisions WHERE matter_id=?", (matter["id"],))
                if decision is None or decision["outcome"] != "claimant" or decision["tick"] != award["tick"] or json.loads(decision["remedy_json"]).get("amount_cents") != award["awarded_cents"]:
                    raise EstateError("award lacks its recorded court decision")
            else:
                offer = json.loads(matter["settlement_json"] or "{}")
                if matter["status"] != "settled" or offer.get("status") != "accepted" or offer.get("accepted_tick") != award["tick"] or offer.get("enforcement", {}).get("award_id") != award["id"]:
                    raise EstateError("award lacks its accepted settlement")
            links = self.store.query("SELECT * FROM legal_award_obligations WHERE award_id=? ORDER BY obligation_id", (award["id"],))
            wage_links = self.store.query("SELECT * FROM wage_claim_novations WHERE award_id=?", (award["id"],))
            if award["credited_cents"] != min(award["awarded_cents"], sum(row["prior_paid_cents"] for row in [*links, *wage_links])):
                raise EstateError("award credit does not match its linked prior payments")
            if award["credited_loss_cents"] != min(award["awarded_cents"] - award["credited_cents"], sum(row["prior_written_off_cents"] for row in wage_links)):
                raise EstateError("award credit does not match the wages already discharged")
            for link in links:
                obligation = self.store.query_one("SELECT * FROM obligations WHERE id=?", (link["obligation_id"],))
                if obligation is None or obligation["obligation_type"] not in ("payment", "indemnity") or (
                        obligation["contract_id"], obligation["obligor_type"], obligation["obligor_id"], obligation["obligee_type"], obligation["obligee_id"], obligation["currency_code"], obligation["amount_cents"]) != (
                        matter["contract_id"], award["respondent_type"], award["respondent_id"], award["claimant_type"], award["claimant_id"], award["currency_code"], link["original_amount_cents"]):
                    raise EstateError("award replaces an unrelated obligation")
                if obligation["status"] != "adjudicated" or self._prior_obligation_payments(obligation) != link["prior_paid_cents"]:
                    raise EstateError("adjudicated obligation can be collected again")
            if self.remaining(award) < 0:
                raise EstateError("monetary award was over-collected")
            for payment in self.store.query("SELECT * FROM legal_award_payments WHERE award_id=? ORDER BY id", (award["id"],)):
                received = self.store.scalar("SELECT COALESCE(SUM(delta_cents),0) FROM ledger_entries WHERE txn_id=? AND account_id=? AND tick=?",
                    (payment["transaction_id"], award["destination_account_id"], payment["tick"]))
                if received != payment["amount_cents"] - payment["tax_cents"] or payment["tick"] < award["tick"]:
                    raise EstateError("award payment disagrees with the cash ledger")
                if payment["estate_disbursement_id"] is not None:
                    row = self.store.query_one("SELECT d.*,c.kind,c.source_id FROM estate_disbursements d JOIN estate_claims c ON c.id=d.claim_id WHERE d.id=?", (payment["estate_disbursement_id"],))
                    if row is None or (row["kind"], row["source_id"], row["amount_cents"], row["transaction_id"]) != ("legal_award", award["id"], payment["amount_cents"], payment["transaction_id"]):
                        raise EstateError("award estate payment has no matching disbursement")
                    source_id = self.store.scalar("SELECT source_account_id FROM estate_receipts WHERE id=?", (row["receipt_id"],))
                else:
                    source_id = award["source_account_id"]
                source = self.store.query_one("SELECT * FROM accounts WHERE id=?", (source_id,))
                target = self.store.query_one("SELECT * FROM accounts WHERE id=?", (award["destination_account_id"],))
                respondent = "gov" if award["respondent_type"] == "government" else award["respondent_type"]
                claimant = "gov" if award["claimant_type"] == "government" else award["claimant_type"]
                if source is None or target is None or (source["owner_type"], source["owner_id"], source["currency_code"]) != (respondent, award["respondent_id"], award["currency_code"]) or (
                        target["owner_type"], target["owner_id"], target["currency_code"]) != (claimant, award["claimant_id"], award["currency_code"]):
                    raise EstateError("award payment uses another party's cash or currency")
                expected = {source["id"]: -payment["amount_cents"], target["id"]: payment["amount_cents"] - payment["tax_cents"]}
                right = self.store.query_one("SELECT * FROM legal_wage_awards WHERE award_id=?", (award["id"],))
                if right:
                    expected[right["payable_account_id"]] = payment["amount_cents"]
                    expected[right["receivable_account_id"]] = -payment["amount_cents"]
                    if payment["tax_cents"]:
                        expected[self.ledger.system_account(SYS_GOV, currency_code=award["currency_code"])] = payment["tax_cents"]
                elif payment["tax_cents"]:
                    raise EstateError("non-wage cash award cannot invent wage withholding")
                if not right and source["bank_id"] and target["bank_id"] and source["bank_id"] != target["bank_id"] and source["kind"] in ("checking", "savings") and target["kind"] in ("checking", "savings"):
                    source_reserve, target_reserve = self.ledger._bank_reserve(source["bank_id"]), self.ledger._bank_reserve(target["bank_id"])
                    if source_reserve and target_reserve:
                        expected[source_reserve] = expected.get(source_reserve, 0) - payment["amount_cents"]
                        expected[target_reserve] = expected.get(target_reserve, 0) + payment["amount_cents"]
                if self.e.cash_estates._transaction_legs(payment["transaction_id"], payment["tick"], award["currency_code"]) != {k: v for k, v in expected.items() if v}:
                    raise EstateError("award payment and settlement legs disagree")
            for loss in self.store.query("SELECT * FROM legal_award_losses WHERE award_id=?", (award["id"],)):
                firm = self.e.firms.get(award["respondent_id"]) if award["respondent_type"] == "firm" else None
                if not firm or firm["status"] != "bankrupt" or firm["bankrupt_tick"] is None or not award["tick"] <= loss["tick"] or firm["bankrupt_tick"] > loss["tick"]:
                    raise EstateError("award loss lacks its recorded firm resolution")
                right = self.store.query_one("SELECT * FROM legal_wage_awards WHERE award_id=?", (award["id"],))
                if right:
                    expected = {right["payable_account_id"]: loss["amount_cents"], right["receivable_account_id"]: -loss["amount_cents"]}
                    if self.e.cash_estates._transaction_legs(loss["transaction_id"], loss["tick"], award["currency_code"]) != expected:
                        raise EstateError("award loss and noncash liability release disagree")
                elif loss["transaction_id"] is not None:
                    raise EstateError("cash award loss cannot invent a ledger movement")
        self.e.wage_awards.check_invariants()
