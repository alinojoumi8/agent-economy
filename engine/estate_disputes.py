"""Keep bounded cash for known monetary disputes until an actual disposition.

Admitted creditors take priority over contested amounts. A reserve owns no
new cash: receipts fund a segregated estate account, and resolution returns
its actual balance through the same creditor/distribution waterfall.
"""
from __future__ import annotations

import json

from .estates import EstateError


class EstateDisputes:
    OPEN_STATUSES = ("filed", "pleading", "hearing", "settlement_offered")

    def __init__(self, economy):
        self.e = economy
        self.store = economy.store
        self.ledger = economy.ledger
        self.enabled = economy.engine_semantics_version >= 20

    def register(self, tick, matter):
        if not self.enabled or matter["respondent_type"] != "agent" or matter["status"] not in self.OPEN_STATUSES:
            return None
        case = self.store.query_one("SELECT * FROM estate_cases WHERE deceased_agent_id=?", (matter["respondent_id"],))
        if case is None:
            return None
        existing = self.store.scalar("SELECT id FROM estate_legal_reserves WHERE matter_id=?", (matter["id"],))
        if existing is not None:
            return existing
        remedy = json.loads(matter["requested_remedy_json"] or "{}")
        requested = remedy.get("amount_cents")
        if remedy.get("type") != "damages" or type(requested) is not int or requested <= 0:
            return None
        if tick < max(case["opened_tick"], matter["filed_tick"]):
            raise EstateError("estate dispute cannot be admitted before its case and filing")
        obligations = self.store.query("SELECT * FROM obligations WHERE contract_id=? AND obligor_type='agent' "
            "AND obligor_id=? AND obligee_type=? AND obligee_id=? AND obligation_type IN ('payment','indemnity') "
            "AND amount_cents>0 AND status IN ('pending','breached') ORDER BY id",
            (matter["contract_id"], matter["respondent_id"], matter["claimant_type"], matter["claimant_id"]))
        if remedy.get("independent_damages") is True:
            obligations = []
        elif "obligation_ids" in remedy:
            obligations = self.e.legal_awards.linked_obligations(matter, remedy)
        currency = self.e.legal_awards._currency(matter, remedy, obligations)
        prior = {row["id"]: self.e.legal_awards._prior_obligation_payments(row) for row in obligations}
        limit = max(0, requested - sum(prior.values()))
        with self.store.savepoint("estate_dispute_admission"):
            account = self.ledger.create_account("agent", case["deceased_agent_id"], "legal_escrow",
                currency_code=currency, label=f"estate-dispute:{case['id']}:{matter['id']}")
            reserve = self.store.insert("estate_legal_reserves", estate_id=case["id"], matter_id=matter["id"],
                registered_tick=tick, registered_after_receipt_id=self.e.estate_cases._receipt_frontier(),
                currency_code=currency, requested_cents=requested, prior_paid_cents=sum(prior.values()),
                reserve_limit_cents=limit, escrow_account_id=account)
            protected = limit
            for obligation in obligations:
                portion = min(protected, obligation["amount_cents"] - prior[obligation["id"]])
                if portion:
                    self.store.insert("estate_reserve_obligations", reserve_id=reserve, obligation_id=obligation["id"], protected_cents=portion)
                    protected -= portion
            return reserve

    def at_receipt(self, receipt):
        return self.store.query("SELECT r.* FROM estate_legal_reserves r WHERE r.estate_id=? AND r.currency_code=? "
            "AND r.registered_tick<=? AND r.registered_after_receipt_id<? AND NOT EXISTS "
            "(SELECT 1 FROM estate_reserve_resolutions s WHERE s.reserve_id=r.id AND s.tick<=? AND s.after_receipt_id<?) ORDER BY r.id",
            (receipt["estate_id"], receipt["currency_code"], receipt["tick"], receipt["id"], receipt["tick"], receipt["id"]))

    def protected(self, claim, receipt):
        if claim["kind"] != "contract_payment":
            return 0
        return sum(self.store.scalar("SELECT COALESCE(SUM(protected_cents),0) FROM estate_reserve_obligations "
                   "WHERE reserve_id=? AND obligation_id=?", (reserve["id"], claim["source_id"])) for reserve in self.at_receipt(receipt))

    def fund(self, tick, receipt, remaining):
        for reserve in self.at_receipt(receipt):
            amount = min(remaining, max(0, reserve["reserve_limit_cents"] - self.ledger.balance(reserve["escrow_account_id"])))
            if amount:
                self.e.estate_cases._disburse(tick, receipt["id"], receipt["source_account_id"], reserve["escrow_account_id"], amount, reserve=reserve)
                remaining -= amount
        return remaining

    def resolve(self, tick, matter_id, event_id):
        reserve = self.store.query_one("SELECT * FROM estate_legal_reserves WHERE matter_id=?", (matter_id,))
        if reserve is None or self.store.scalar("SELECT id FROM estate_reserve_resolutions WHERE reserve_id=?", (reserve["id"],)):
            return
        if tick < reserve["registered_tick"]:
            raise EstateError("estate dispute resolution cannot precede admission")
        matter = self.store.query_one("SELECT * FROM legal_matters WHERE id=?", (matter_id,))
        if matter["status"] not in ("decided", "dismissed", "settled"):
            raise EstateError("estate dispute needs an actual final legal disposition")
        with self.e.estate_cases._batch():
            amount = self.ledger.balance(reserve["escrow_account_id"])
            if amount < 0:
                raise EstateError("estate dispute escrow is negative")
            person = self.store.scalar("SELECT deceased_agent_id FROM estate_cases WHERE id=?", (reserve["estate_id"],))
            transaction = self.ledger.transfer(tick, reserve["escrow_account_id"], self.e.estate_cases._wallet(person, reserve["currency_code"]),
                amount, kind="estate_dispute_release", memo=f"estate dispute {reserve['id']}") if amount else None
            self.store.insert("estate_reserve_resolutions", reserve_id=reserve["id"], tick=tick,
                after_receipt_id=self.e.estate_cases._receipt_frontier(), event_id=event_id, released_cents=amount, transaction_id=transaction)
            self.e.estate_cases.schedule_security_release(tick, reserve["estate_id"])

    def check_invariants(self):
        if not self.enabled:
            return
        for reserve in self.store.query("SELECT * FROM estate_legal_reserves ORDER BY id"):
            case = self.store.query_one("SELECT * FROM estate_cases WHERE id=?", (reserve["estate_id"],))
            matter = self.store.query_one("SELECT * FROM legal_matters WHERE id=?", (reserve["matter_id"],))
            account = self.store.query_one("SELECT * FROM accounts WHERE id=?", (reserve["escrow_account_id"],))
            if matter is None or (matter["respondent_type"], matter["respondent_id"]) != ("agent", case["deceased_agent_id"]) or reserve["registered_tick"] < max(case["opened_tick"], matter["filed_tick"]):
                raise EstateError("estate reserve has the wrong matter or admission time")
            if (account["owner_type"], account["owner_id"], account["kind"], account["currency_code"]) != ("agent", case["deceased_agent_id"], "legal_escrow", reserve["currency_code"]):
                raise EstateError("estate reserve has the wrong escrow account")
            funded = self.store.scalar("SELECT COALESCE(SUM(amount_cents),0) FROM estate_disbursements WHERE reserve_id=?", (reserve["id"],))
            resolution = self.store.query_one("SELECT * FROM estate_reserve_resolutions WHERE reserve_id=?", (reserve["id"],))
            released = resolution["released_cents"] if resolution else 0
            if funded > reserve["reserve_limit_cents"] or account["balance_cents"] != funded - released or (resolution and released != funded):
                raise EstateError("estate reserve cash does not reconcile")
            links = self.store.query("SELECT l.*,o.contract_id,o.obligor_type,o.obligor_id,o.obligee_type,o.obligee_id,o.currency_code,o.amount_cents FROM estate_reserve_obligations l JOIN obligations o ON o.id=l.obligation_id WHERE l.reserve_id=?", (reserve["id"],))
            if sum(link["protected_cents"] for link in links) > reserve["reserve_limit_cents"]:
                raise EstateError("estate dispute protects more than its recorded limit")
            for link in links:
                if (link["contract_id"], link["obligor_type"], link["obligor_id"], link["obligee_type"], link["obligee_id"], link["currency_code"]) != (
                        matter["contract_id"], "agent", case["deceased_agent_id"], matter["claimant_type"], matter["claimant_id"], reserve["currency_code"]) or link["protected_cents"] > link["amount_cents"]:
                    raise EstateError("estate dispute protects an unrelated obligation")
            if resolution:
                event = self.store.query_one("SELECT * FROM events WHERE id=?", (resolution["event_id"],))
                if event is None or event["kind"] not in ("legal_decision_enforced", "matter_settled") or event["tick"] != resolution["tick"] or json.loads(event["payload_json"]).get("matter_id") != matter["id"]:
                    raise EstateError("estate reserve has no matching legal disposition")
                if released:
                    receipt = self.store.query_one("SELECT r.*,a.owner_type,a.owner_id,a.kind FROM estate_receipts r "
                        "JOIN accounts a ON a.id=r.source_account_id WHERE r.origin_transaction_id=? AND r.estate_id=?",
                        (resolution["transaction_id"], case["id"]))
                    if receipt is None or (receipt["tick"], receipt["currency_code"], receipt["received_cents"],
                            receipt["owner_type"], receipt["owner_id"]) != (
                            resolution["tick"], reserve["currency_code"], released, "agent", case["deceased_agent_id"]
                            ) or receipt["kind"] not in ("checking", "savings", "fx") or receipt["id"] <= resolution["after_receipt_id"]:
                        raise EstateError("estate reserve release has no matching later estate receipt")
                    expected = {account["id"]: -released, receipt["source_account_id"]: released}
                    if self.e.cash_estates._transaction_legs(resolution["transaction_id"], resolution["tick"], reserve["currency_code"]) != expected:
                        raise EstateError("estate reserve release disagrees with the cash ledger")
