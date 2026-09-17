"""Semantics-20 estate inventory, beneficial interests and realized-cash claims.

The deceased remains a nominee for unpaid personal receivables. Recorded heirs
own the residual interest; their own wallets never secure an estate debt. The
opening event closes the inventory, not pending claims or illiquid rights.
"""
from __future__ import annotations

from collections import deque
from contextlib import contextmanager
import json

from .estates import EstateError
from .ledger import Leg, SYS_GOV, SYS_LOSS


class EstateCases:
    POLICY = "family_equal_deficit_then_bank_then_contract_v1"
    FINALITY_POLICY = "prospective_receipts_no_clawback_v1"
    CASH_KINDS = ("checking", "savings", "fx")

    def __init__(self, economy):
        self.e = economy
        self.store = economy.store
        self.ledger = economy.ledger
        self.enabled = economy.engine_semantics_version >= 20
        self._pending = None
        self._security_updates = None

    @contextmanager
    def _batch(self):
        """Nested payments queue receipts; only the outer atomic call drains."""
        outer = self._pending is None
        if outer:
            self._pending = deque()
            self._security_updates = set()
        try:
            with self.store.savepoint("estate_receipt_batch"):
                yield
                if outer:
                    while self._pending or self._security_updates:
                        if self._pending:
                            self._receive(*self._pending.popleft())
                            continue
                        tick, estate_id = min(self._security_updates)
                        self._security_updates.remove((tick, estate_id))
                        self._release_assets(tick, estate_id)
        finally:
            if outer:
                self._pending = None
                self._security_updates = None

    def schedule_security_release(self, tick, estate_id):
        with self._batch():
            self._security_updates.add((tick, estate_id))

    def _release_assets(self, tick, estate_id):
        self.e.estate_securities.release_ready(tick, estate_id)
        self.e.estate_property.release_ready(tick, estate_id)
        self.e.legal_representation.reconcile(tick)
        self.e.estate_securities.revoke_invalid_orders(tick, estate_id)
        self.e.estate_unlisted_sales.reconcile(tick)
        self.e.project_rights.refresh(tick)

    def cash_received(self, tick, transaction, legs):
        """Ledger hook: net credits to an inventoried estate's cash wallets."""
        totals = {}
        for leg in legs:
            totals[leg.account_id] = totals.get(leg.account_id, 0) + leg.delta_cents
        with self._batch():
            for account_id, amount in sorted(totals.items()):
                if amount <= 0:
                    continue
                account = self.store.query_one(
                    "SELECT a.*,c.id AS estate_id FROM accounts a JOIN estate_cases c "
                    "ON a.owner_type='agent' AND a.owner_id=c.deceased_agent_id "
                    "WHERE a.id=? AND a.kind IN ('checking','savings','fx')", (account_id,))
                if account:
                    self._pending.append((tick, account["estate_id"], account_id, transaction, amount, account["balance_cents"]))

    def beneficiaries_for(self, tick, agent_id):
        """Equal living partner/child shares; then parents; then strongest tie."""
        recipients = {}
        for row in self.store.query(
                "SELECT CASE WHEN p.agent_a=? THEN p.agent_b ELSE p.agent_a END AS person "
                "FROM partnerships p WHERE (p.agent_a=? OR p.agent_b=?) AND p.started_tick<=? "
                "AND (p.ended_tick IS NULL OR p.ended_tick>?) ORDER BY p.id",
                (agent_id, agent_id, agent_id, tick, tick)):
            if self.store.scalar("SELECT alive FROM agents WHERE id=?", (row["person"],)):
                recipients[row["person"]] = "partner"
        for row in self.store.query(
                "SELECT r.child_agent_id FROM parent_child_relations r JOIN agents a ON a.id=r.child_agent_id "
                "WHERE r.parent_agent_id=? AND r.formed_tick<=? AND a.alive=1 ORDER BY a.id", (agent_id, tick)):
            recipients.setdefault(row["child_agent_id"], "child")
        if not recipients:
            for row in self.store.query(
                    "SELECT r.parent_agent_id FROM parent_child_relations r JOIN agents a ON a.id=r.parent_agent_id "
                    "WHERE r.child_agent_id=? AND r.formed_tick<=? AND a.alive=1 ORDER BY a.id", (agent_id, tick)):
                recipients[row["parent_agent_id"]] = "parent"
        if not recipients:
            heir = self.e.lifecycle._find_heir(agent_id)
            if heir is not None:
                recipients[heir] = "social_tie"
        return [(person, 1, basis) for person, basis in sorted(recipients.items())] or [(None, 1, "escheat")]

    def _wallet(self, agent_id, currency):
        if agent_id is None:
            return self.ledger.system_account(SYS_GOV, currency_code=currency)
        if not self.store.scalar("SELECT alive FROM agents WHERE id=?", (agent_id,)) and not self.store.scalar(
                "SELECT id FROM estate_cases WHERE deceased_agent_id=?", (agent_id,)):
            raise EstateError("deceased recipient lacks a recorded estate")
        account = self.store.scalar(
            "SELECT id FROM accounts WHERE owner_type='agent' AND owner_id=? AND currency_code=? "
            "AND kind IN ('checking','savings','fx') "
            "ORDER BY CASE kind WHEN 'checking' THEN 0 ELSE 1 END,id LIMIT 1", (agent_id, currency))
        return int(account) if account is not None else self.ledger.create_account(
            "agent", agent_id, "fx", currency_code=currency, label=f"estate-receipts:{agent_id}:{currency}")

    def _creditor_account(self, owner_type, owner_id, currency):
        if owner_type == "agent":
            return self._wallet(owner_id, currency)
        owner_type = "gov" if owner_type == "government" else owner_type
        account = self.store.query_one(
            "SELECT * FROM accounts WHERE owner_type=? AND owner_id=? AND currency_code=? "
            "AND kind IN ('checking','savings','fx','treasury') ORDER BY id LIMIT 1",
            (owner_type, owner_id, currency))
        if account is None:
            raise EstateError("estate contractual creditor has no same-currency cash account")
        return int(account["id"])

    def _item(self, estate_id, kind, row, disposition, amount=None, currency=None):
        self.store.insert("estate_items", estate_id=estate_id, kind=kind, source_id=row["id"],
            disposition=disposition, amount=amount, currency_code=currency,
            snapshot_json=json.dumps(dict(row), sort_keys=True, separators=(",", ":")))

    def open(self, tick, agent_id):
        """Inside the full death transition, after collection of available wages."""
        if not self.enabled:
            raise EstateError("estate cases require Semantics 20")
        if self.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=?", (agent_id,)):
            raise EstateError("estate opening cannot be repeated")
        if not self.store.scalar("SELECT alive FROM agents WHERE id=?", (agent_id,)):
            raise EstateError("estate opening requires an active death transition")
        beneficiaries = self.beneficiaries_for(tick, agent_id)
        with self._batch():
            estate_id = self.store.insert("estate_cases", deceased_agent_id=agent_id,
                opened_tick=tick, policy=self.POLICY, distribution_finality_policy=self.FINALITY_POLICY,
                beneficiary_count=len(beneficiaries))
            for person, weight, basis in beneficiaries:
                self.store.insert("estate_beneficiaries", estate_id=estate_id,
                                  agent_id=person, weight=weight, basis=basis)
            wallets = self.store.query("SELECT * FROM accounts WHERE owner_type='agent' AND owner_id=? "
                "AND kind IN ('checking','savings','fx') ORDER BY currency_code,id", (agent_id,))
            for wallet in wallets:
                self._item(estate_id, "cash", wallet,
                    "unresolved_deficit" if wallet["balance_cents"] < 0 else "distributed",
                    wallet["balance_cents"], wallet["currency_code"])
            self._register_claims(tick, estate_id, agent_id)
            self._inventory_rights(tick, estate_id, agent_id)
            self.e.project_rights.distribute(tick, estate_id, agent_id)
            for wallet in wallets:
                if wallet["balance_cents"] > 0:
                    self._receive(tick, estate_id, wallet["id"], None, wallet["balance_cents"], wallet["balance_cents"])
            # Retain unpaid bank claims against future estate receipts, while
            # recognizing the initial shortfall now in the existing credit model.
            for claim in self.store.query("SELECT * FROM estate_claims WHERE estate_id=? "
                                          "AND kind='bank_principal' ORDER BY source_id", (estate_id,)):
                unpaid = claim["principal_cents"] - self._paid(claim["id"])
                if unpaid:
                    transaction = self.ledger.post(tick, "estate_case_loan_loss", [
                        Leg(claim["equity_account_id"], -unpaid), Leg(claim["loss_account_id"], unpaid)],
                        memo=f"estate {estate_id} bank claim {claim['id']}")
                    self.store.insert("estate_claim_losses", claim_id=claim["id"], tick=tick,
                                      amount_cents=unpaid, transaction_id=transaction)
                self.store.update("loans", claim["source_id"], outstanding_cents=0,
                                  status="default" if unpaid else "paid")
            self.e.estate_securities.open(tick, estate_id, agent_id,
                [(person, weight) for person, weight, _ in beneficiaries])
            event = self.store.log_event(tick, "estate_case_opened", {
                "estate_id": estate_id, "agent_id": agent_id, "policy": self.POLICY,
                "distribution_finality_policy": self.FINALITY_POLICY,
                "beneficiary_count": len(beneficiaries), "scope": "opening_inventory_and_realized_cash",
            }, phase="NIGHT_CLOSE", subject_type="agent", subject_id=agent_id)
            self.store.update("estate_cases", estate_id, completed_event_id=event,
                item_count=self.store.scalar("SELECT COUNT(*) FROM estate_items WHERE estate_id=?", (estate_id,)),
                claim_count=self.store.scalar("SELECT COUNT(*) FROM estate_claims WHERE estate_id=?", (estate_id,)))
        return estate_id

    def finality_at(self, estate_id, tick):
        """Read recorded end-of-tick estate status; opening is not claim closure."""
        if type(tick) is not int or tick < 0:
            raise ValueError("estate status requires a nonnegative integer tick")
        if not self.enabled:
            return None
        case = self.store.query_one("SELECT * FROM estate_cases WHERE id=? AND opened_tick<=?", (estate_id, tick))
        if case is None:
            return None
        claims = self.store.query("SELECT c.currency_code,COUNT(*) AS claim_count,SUM(c.remaining_cents) AS remaining_cents FROM ("
            "SELECT c.currency_code,c.principal_cents-COALESCE((SELECT SUM(d.amount_cents) FROM estate_disbursements d "
            "JOIN estate_receipts r ON r.id=d.receipt_id WHERE d.claim_id=c.id AND r.tick<=?),0)-COALESCE("
            "(SELECT SUM(l.amount_cents) FROM estate_claim_releases l WHERE l.claim_id=c.id AND l.tick<=?),0) AS remaining_cents "
            "FROM estate_claims c WHERE c.estate_id=? AND c.registered_tick<=?) c WHERE c.remaining_cents>0 "
            "GROUP BY c.currency_code ORDER BY c.currency_code", (tick, tick, estate_id, tick))
        return {
            "estate_id": estate_id, "as_of_tick": tick,
            "distribution_finality_policy": case["distribution_finality_policy"],
            "opening_inventory_recorded": bool(self.store.scalar("SELECT id FROM events WHERE id=? AND tick<=?",
                (case["completed_event_id"], tick))),
            "outstanding_claims_by_currency": [dict(row) for row in claims],
            "unresolved_disputes": self.store.scalar("SELECT COUNT(*) FROM estate_legal_reserves r WHERE r.estate_id=? "
                "AND r.registered_tick<=? AND NOT EXISTS (SELECT 1 FROM estate_reserve_resolutions s "
                "WHERE s.reserve_id=r.id AND s.tick<=?)", (estate_id, tick, tick)),
            "retained_property_interests": self.store.scalar("SELECT COUNT(*) FROM estate_project_custody c WHERE c.estate_id=? "
                "AND c.opened_tick<=? AND NOT EXISTS (SELECT 1 FROM estate_project_releases r "
                "WHERE r.custody_id=c.id AND r.tick<=?)", (estate_id, tick, tick)),
            "retained_security_lots": self.store.scalar("SELECT COUNT(*) FROM estate_security_lots l WHERE l.estate_id=? "
                "AND l.started_tick<=? AND NOT EXISTS (SELECT 1 FROM estate_security_releases r "
                "WHERE r.lot_id=l.id AND r.tick<=?)", (estate_id, tick, tick)),
        }

    def _register_claims(self, tick, estate_id, agent_id):
        for loan in self.store.query("SELECT * FROM loans WHERE borrower_type='agent' "
                                     "AND borrower_id=? AND status='active' ORDER BY id", (agent_id,)):
            bank = self.e.bank.get(loan["bank_id"])
            if bank is None or loan["outstanding_cents"] < 0:
                raise EstateError("invalid estate bank principal")
            currency = str(bank["currency_code"] or "USD")
            for field, kind in (("reserve_account_id", "reserve"), ("equity_account_id", "equity")):
                account = self.store.query_one("SELECT * FROM accounts WHERE id=?", (bank[field],))
                if account is None or (account["owner_type"], account["owner_id"], account["kind"], account["currency_code"]) != (
                        "bank", bank["id"], kind, currency):
                    raise EstateError("estate bank accounts have the wrong identity or currency")
            self._item(estate_id, "bank_principal", loan, "creditor_claim", loan["outstanding_cents"], currency)
            if loan["outstanding_cents"]:
                self.store.insert("estate_claims", estate_id=estate_id, kind="bank_principal", source_id=loan["id"],
                    registered_tick=tick, registered_after_receipt_id=self._receipt_frontier(),
                    creditor_type="bank", creditor_id=bank["id"], currency_code=currency,
                    destination_account_id=bank["reserve_account_id"], principal_cents=loan["outstanding_cents"],
                    equity_account_id=bank["equity_account_id"],
                    loss_account_id=self.ledger.system_account(SYS_LOSS, currency_code=currency))
            else:
                self.store.update("loans", loan["id"], outstanding_cents=0, status="paid")
        for obligation in self.store.query("SELECT * FROM obligations WHERE obligor_type='agent' "
                "AND obligor_id=? AND status IN ('pending','breached') ORDER BY id", (agent_id,)):
            monetary = (obligation["obligation_type"] in ("payment", "indemnity")
                        and (obligation["amount_cents"] or 0) > 0)
            self_claim = obligation["obligee_type"] == "agent" and obligation["obligee_id"] == agent_id
            self._item(estate_id, "personal_obligation", obligation,
                       "creditor_claim" if monetary and not self_claim else "extinguished",
                       obligation["amount_cents"], obligation["currency_code"])
            if monetary and not self_claim:
                self.store.insert("estate_claims", estate_id=estate_id, kind="contract_payment", source_id=obligation["id"],
                    registered_tick=tick, registered_after_receipt_id=self._receipt_frontier(),
                    creditor_type=obligation["obligee_type"], creditor_id=obligation["obligee_id"],
                    currency_code=obligation["currency_code"], principal_cents=obligation["amount_cents"],
                    destination_account_id=self._creditor_account(obligation["obligee_type"],
                        obligation["obligee_id"], obligation["currency_code"]))
            else:
                self.store.update("obligations", obligation["id"], status="cancelled")
        case = self.store.query_one("SELECT * FROM estate_cases WHERE id=?", (estate_id,))
        for award in self.store.query("SELECT * FROM legal_awards WHERE respondent_type='agent' AND respondent_id=? ORDER BY id", (agent_id,)):
            self._item(estate_id, "legal_award", award, "creditor_claim", self.e.legal_awards.remaining(award), award["currency_code"])
            self.register_award(tick, case, award)
        for matter in self.store.query("SELECT * FROM legal_matters WHERE respondent_type='agent' AND respondent_id=? ORDER BY id", (agent_id,)):
            self.e.estate_disputes.register(tick, matter)

    def _inventory_rights(self, tick, estate_id, agent_id):
        for share in self.store.query("SELECT * FROM shares WHERE holder_type='agent' AND holder_id=? AND qty<>0 ORDER BY id", (agent_id,)):
            self._item(estate_id, "security", share, "retained", share["qty"])
        for holder in self.store.query("SELECT h.*,c.currency_code FROM wage_claim_holders h JOIN wage_claims c ON c.id=h.claim_id "
                "WHERE h.owner_type='agent' AND h.owner_id=? AND h.ended_tick IS NULL AND c.closed_tick IS NULL ORDER BY h.id", (agent_id,)):
            self._item(estate_id, "wage_receivable", holder, "retained",
                       self.ledger.balance(holder["receivable_account_id"]), holder["currency_code"])
        retained = (
            ("noncash_account", "SELECT * FROM accounts WHERE owner_type='agent' AND owner_id=? AND kind NOT IN ('checking','savings','fx') ORDER BY id"),
            ("funding_refund_right", "SELECT c.* FROM construction_contributions c JOIN accounts a ON a.id=c.source_account_id WHERE a.owner_type='agent' AND a.owner_id=? AND c.contribution_type='funding' ORDER BY c.id"),
            ("contract_interest", "SELECT * FROM contract_parties WHERE party_type='agent' AND party_id=? ORDER BY id"),
            ("contract_receivable", "SELECT * FROM obligations WHERE obligee_type='agent' AND obligee_id=? AND status='pending' ORDER BY id"),
            ("legal_claim", "SELECT * FROM legal_matters WHERE claimant_type='agent' AND claimant_id=? ORDER BY id"),
            ("legal_liability", "SELECT * FROM legal_matters WHERE respondent_type='agent' AND respondent_id=? ORDER BY id"),
        )
        for kind, query in retained:
            for row in self.store.query(query, (agent_id,)):
                self._item(estate_id, kind, row, "retained")
        for project in self.e.project_rights.owned_projects(agent_id):
            self._item(estate_id, "personal_project", project, "retained")
        # Personal entitlements and unfilled requests do not pass the person's
        # identity or future service commitments to another agent.
        endings = (
            ("insurance", "insurance_policies", "agent_id=? AND status='active'", {"status": "cancelled", "end_tick": tick}),
            ("compute_access", "compute_subscriptions", "agent_id=? AND status IN ('pending','active')", {"status": "cancelled"}),
            ("loan_application", "loan_applications", "borrower_type='agent' AND borrower_id=? AND status='pending'", {"status": "expired", "decided_tick": tick}),
            ("job_application", "applications", "agent_id=? AND state IN ('pending','negotiating')", {"state": "withdrawn"}),
            ("job_offer", "job_offers", "application_id IN (SELECT id FROM applications WHERE agent_id=?) AND status='pending'", {"status": "expired", "decided_tick": tick}),
            ("migration", "migrations", "agent_id=? AND status='pending'", {"status": "cancelled"}),
            ("stock_order", "orders", "agent_id=? AND status IN ('open','partial')", {"status": "cancelled"}),
            ("fx_order", "fx_orders", "actor_id=? AND status='open'", {"status": "cancelled"}),
            ("ipo_bid", "ipo_bids", "bidder_agent_id=? AND status='open'", {"status": "cancelled"}),
        )
        for kind, table, predicate, changes in endings:
            for row in self.store.query(f"SELECT * FROM {table} WHERE {predicate} ORDER BY id", (agent_id,)):
                self._item(estate_id, kind, row, "extinguished")
                self.store.update(table, row["id"], **changes)
        for row in self.e.families.pending_interests(agent_id):
            self._item(estate_id, "family_commitment", row, "extinguished")
            self.e.families.end_for_death(tick, row)
        self.e.civic_authority.close_person(tick, estate_id, agent_id)

    def _paid(self, claim_id):
        return int(self.store.scalar("SELECT COALESCE(SUM(amount_cents),0) FROM estate_disbursements WHERE claim_id=?", (claim_id,)))

    def _receipt_frontier(self):
        return self.store.scalar("SELECT COALESCE(MAX(id),0) FROM estate_receipts")

    def _released(self, claim_id, receipt=None):
        if receipt is None:
            return self.store.scalar("SELECT COALESCE(SUM(amount_cents),0) FROM estate_claim_releases WHERE claim_id=?", (claim_id,))
        return self.store.scalar("SELECT COALESCE(SUM(amount_cents),0) FROM estate_claim_releases "
            "WHERE claim_id=? AND after_receipt_id<? AND tick<=?", (claim_id, receipt["id"], receipt["tick"]))

    def _claims_for_receipt(self, receipt):
        return self.store.query("SELECT * FROM estate_claims WHERE estate_id=? AND currency_code=? "
            "AND registered_tick<=? AND registered_after_receipt_id<? "
            "ORDER BY CASE kind WHEN 'bank_principal' THEN 0 WHEN 'contract_payment' THEN 1 ELSE 2 END,source_id,id",
            (receipt["estate_id"], receipt["currency_code"], receipt["tick"], receipt["id"]))

    def release_obligation(self, tick, obligation_id, *, award_id=None, reason="contract_terminated"):
        claim = self.store.query_one("SELECT * FROM estate_claims WHERE kind='contract_payment' AND source_id=?", (obligation_id,))
        if claim is None:
            return None
        amount = claim["principal_cents"] - self._paid(claim["id"]) - self._released(claim["id"])
        if amount <= 0:
            return None
        if tick < claim["registered_tick"]:
            raise EstateError("estate claim release cannot precede its admission")
        release = self.store.insert("estate_claim_releases", claim_id=claim["id"], tick=tick,
            after_receipt_id=self._receipt_frontier(), amount_cents=amount, award_id=award_id,
            reason="adjudicated" if award_id is not None else reason)
        self.schedule_security_release(tick, claim["estate_id"])
        return release

    def register_award(self, tick, estate, award):
        if tick < max(estate["opened_tick"], award["tick"]):
            raise EstateError("estate award admission cannot precede the estate or decision")
        if (award["respondent_type"], award["respondent_id"]) != ("agent", estate["deceased_agent_id"]):
            raise EstateError("legal award does not belong to this estate")
        existing = self.store.scalar("SELECT id FROM estate_claims WHERE kind='legal_award' AND source_id=?", (award["id"],))
        if existing is not None:
            return existing
        remaining = self.e.legal_awards.remaining(award)
        if remaining <= 0:
            return None
        return self.store.insert("estate_claims", estate_id=estate["id"], kind="legal_award", source_id=award["id"],
            registered_tick=tick, registered_after_receipt_id=self._receipt_frontier(),
            is_opening=int(estate["completed_event_id"] is None),
            creditor_type=award["claimant_type"], creditor_id=award["claimant_id"],
            destination_account_id=award["destination_account_id"], currency_code=award["currency_code"], principal_cents=remaining)

    def _receive(self, tick, estate_id, account_id, origin, received, post_balance):
        if self.store.scalar("SELECT id FROM estate_receipts WHERE source_account_id=? "
                "AND origin_transaction_id IS ?", (account_id, origin)):
            raise EstateError("estate receipt was already processed")
        account = self.store.query_one("SELECT * FROM accounts WHERE id=?", (account_id,))
        available = min(received, max(0, post_balance))
        if available > max(0, account["balance_cents"]):
            raise EstateError("estate receipt cash was spent before distribution")
        receipt_id = self.store.insert("estate_receipts", estate_id=estate_id, tick=tick,
            source_account_id=account_id, origin_transaction_id=origin, currency_code=account["currency_code"],
            received_cents=received, post_balance_cents=post_balance, available_cents=available)
        receipt = self.store.query_one("SELECT * FROM estate_receipts WHERE id=?", (receipt_id,))
        remaining = self._offset_cash_deficits(receipt, available)
        for claim in self._claims_for_receipt(receipt):
            due = claim["principal_cents"] - self._paid(claim["id"]) - self._released(claim["id"], receipt)
            amount = min(remaining, max(0, due - self.e.estate_disputes.protected(claim, receipt)))
            if amount <= 0:
                continue
            self._disburse(tick, receipt_id, account_id, claim["destination_account_id"], amount, claim=claim)
            remaining -= amount
        remaining = self.e.estate_disputes.fund(tick, receipt, remaining)
        if remaining:
            beneficiaries = self.store.query("SELECT * FROM estate_beneficiaries WHERE estate_id=? ORDER BY COALESCE(agent_id,0),id", (estate_id,))
            denominator = sum(b["weight"] for b in beneficiaries)
            amounts = [remaining * b["weight"] // denominator for b in beneficiaries]
            priority = sorted(range(len(beneficiaries)), key=lambda i: (-(remaining * beneficiaries[i]["weight"] % denominator), i))
            for i in priority[:remaining-sum(amounts)]:
                amounts[i] += 1
            for beneficiary, amount in zip(beneficiaries, amounts):
                if amount:
                    self._disburse(tick, receipt_id, account_id,
                        self._wallet(beneficiary["agent_id"], account["currency_code"]), amount, beneficiary=beneficiary)
        self._release_assets(tick, estate_id)

    def _offset_cash_deficits(self, receipt, remaining):
        if remaining <= 0:
            return remaining
        targets = self.store.query("SELECT a.* FROM accounts a JOIN estate_cases c "
            "ON a.owner_type='agent' AND a.owner_id=c.deceased_agent_id "
            "WHERE c.id=? AND a.currency_code=? AND a.kind IN ('checking','savings','fx') "
            "AND a.id<>? AND a.balance_cents<0 ORDER BY a.id",
            (receipt["estate_id"], receipt["currency_code"], receipt["source_account_id"]))
        for target in targets:
            amount = min(remaining, -target["balance_cents"])
            if amount <= 0:
                break
            transaction = self.ledger.transfer(receipt["tick"], receipt["source_account_id"],
                target["id"], amount, kind="estate_cash_deficit_offset",
                memo=f"estate receipt {receipt['id']} offsets wallet {target['id']}")
            self.store.insert("estate_cash_offsets", receipt_id=receipt["id"],
                destination_account_id=target["id"], negative_before_cents=target["balance_cents"],
                amount_cents=amount, transaction_id=transaction)
            remaining -= amount
        return remaining

    def _disburse(self, tick, receipt_id, source, target, amount, *, claim=None, beneficiary=None, reserve=None):
        transaction = self.ledger.transfer(tick, source, target, amount,
            kind="estate_case_creditor" if claim is not None else "estate_case_reserve" if reserve is not None else "estate_case_distribution", memo=f"estate receipt {receipt_id}")
        recovery = None
        if claim is not None and self.store.scalar("SELECT id FROM estate_claim_losses WHERE claim_id=?", (claim["id"],)):
            recovery = self.ledger.post(tick, "estate_case_loss_recovery", [
                Leg(claim["equity_account_id"], amount), Leg(claim["loss_account_id"], -amount)],
                memo=f"estate bank claim {claim['id']} recovered")
        disbursement_id = self.store.insert("estate_disbursements", receipt_id=receipt_id, claim_id=claim["id"] if claim is not None else None,
            beneficiary_id=beneficiary["id"] if beneficiary is not None else None,
            reserve_id=reserve["id"] if reserve is not None else None,
            destination_account_id=target, amount_cents=amount, transaction_id=transaction, recovery_transaction_id=recovery)
        if claim is not None and claim["kind"] == "legal_award":
            self.e.legal_awards.note_payment(tick, claim["source_id"], amount, transaction, disbursement_id)
        if claim is not None and self._paid(claim["id"]) + self._released(claim["id"]) == claim["principal_cents"]:
            if claim["kind"] == "bank_principal":
                self.store.update("loans", claim["source_id"], outstanding_cents=0, status="paid")
            elif claim["kind"] == "contract_payment":
                self.store.update("obligations", claim["source_id"], status="performed", performed_tick=tick, transaction_id=transaction)

    def check_invariants(self):
        if not self.enabled:
            return
        if self.store.scalar("SELECT o.id FROM estate_cash_offsets o LEFT JOIN estate_receipts r ON r.id=o.receipt_id "
                             "LEFT JOIN estate_cases c ON c.id=r.estate_id WHERE c.id IS NULL LIMIT 1"):
            raise EstateError("estate cash deficit offset has no recorded estate receipt")
        for case in self.store.query("SELECT * FROM estate_cases ORDER BY id"):
            event = self.store.query_one("SELECT * FROM events WHERE id=?", (case["completed_event_id"],))
            if event is None or (event["kind"], event["tick"], event["subject_id"]) != (
                    "estate_case_opened", case["opened_tick"], case["deceased_agent_id"]):
                raise EstateError("estate opening event is missing or inconsistent")
            if (case["distribution_finality_policy"] != self.FINALITY_POLICY
                    or json.loads(event["payload_json"]).get("distribution_finality_policy") != case["distribution_finality_policy"]):
                raise EstateError("estate distribution finality lacks its recorded opening policy")
            for table, field in (("estate_beneficiaries", "beneficiary_count"), ("estate_items", "item_count")):
                if self.store.scalar(f"SELECT COUNT(*) FROM {table} WHERE estate_id=?", (case["id"],)) != case[field]:
                    raise EstateError("estate opening inventory count changed")
            if self.store.scalar("SELECT COUNT(*) FROM estate_claims WHERE estate_id=? AND is_opening=1", (case["id"],)) != case["claim_count"]:
                raise EstateError("estate opening claim count changed")
            for beneficiary in self.store.query("SELECT * FROM estate_beneficiaries WHERE estate_id=?", (case["id"],)):
                if beneficiary["agent_id"] == case["deceased_agent_id"]:
                    raise EstateError("estate cannot name the deceased as beneficiary")
        already_paid = {}
        for receipt in self.store.query("SELECT r.*,c.deceased_agent_id,c.opened_tick FROM estate_receipts r JOIN estate_cases c ON c.id=r.estate_id ORDER BY r.id"):
            account = self.store.query_one("SELECT * FROM accounts WHERE id=?", (receipt["source_account_id"],))
            if ((account["owner_type"], account["owner_id"], account["currency_code"]) !=
                    ("agent", receipt["deceased_agent_id"], receipt["currency_code"])
                    or account["kind"] not in self.CASH_KINDS or receipt["tick"] < receipt["opened_tick"]):
                raise EstateError("estate cash receipt has the wrong wallet or time")
            if receipt["origin_transaction_id"] is not None:
                amount = self.store.scalar("SELECT COALESCE(SUM(delta_cents),0) FROM ledger_entries "
                    "WHERE txn_id=? AND account_id=? AND tick=?", (receipt["origin_transaction_id"], account["id"], receipt["tick"]))
                if amount != receipt["received_cents"]:
                    raise EstateError("late estate receipt disagrees with original payment")
                balance = self.store.scalar("SELECT COALESCE(SUM(delta_cents),0) FROM ledger_entries "
                    "WHERE account_id=? AND txn_id<=?", (account["id"], receipt["origin_transaction_id"]))
                if balance != receipt["post_balance_cents"]:
                    raise EstateError("estate receipt deficit absorption has the wrong source balance")
            else:
                item = self.store.query_one("SELECT * FROM estate_items WHERE estate_id=? AND kind='cash' AND source_id=?", (receipt["estate_id"], account["id"]))
                if item is None or item["amount"] != receipt["received_cents"] or receipt["tick"] != receipt["opened_tick"]:
                    raise EstateError("opening cash receipt disagrees with inventory")
            disbursements = self.store.query("SELECT * FROM estate_disbursements WHERE receipt_id=? ORDER BY id", (receipt["id"],))
            offsets = self.store.query("SELECT * FROM estate_cash_offsets WHERE receipt_id=? ORDER BY id", (receipt["id"],))
            offset_total = sum(row["amount_cents"] for row in offsets)
            if sum(row["amount_cents"] for row in disbursements) + offset_total != receipt["available_cents"]:
                raise EstateError("realized estate cash is not fully accounted for")
            self._check_cash_offsets(receipt, offsets, disbursements)
            self._check_waterfall(receipt, disbursements, already_paid, receipt["available_cents"] - offset_total)
            for payment in disbursements:
                target = self.store.query_one("SELECT * FROM accounts WHERE id=?", (payment["destination_account_id"],))
                if payment["claim_id"] is not None:
                    claim = self.store.query_one("SELECT * FROM estate_claims WHERE id=?", (payment["claim_id"],))
                    if (claim["estate_id"], claim["destination_account_id"], claim["currency_code"]) != (
                            receipt["estate_id"], target["id"], receipt["currency_code"]):
                        raise EstateError("estate creditor receipt has the wrong claim")
                    if payment["recovery_transaction_id"] is not None and claim["kind"] != "bank_principal":
                        raise EstateError("only a bank principal write-off can be recovered")
                elif payment["reserve_id"] is not None:
                    reserve = self.store.query_one("SELECT * FROM estate_legal_reserves WHERE id=?", (payment["reserve_id"],))
                    if reserve is None or (reserve["estate_id"], reserve["currency_code"], reserve["escrow_account_id"]) != (receipt["estate_id"], receipt["currency_code"], target["id"]):
                        raise EstateError("estate reserve funding has the wrong dispute")
                else:
                    beneficiary = self.store.query_one("SELECT * FROM estate_beneficiaries WHERE id=?", (payment["beneficiary_id"],))
                    if beneficiary["estate_id"] != receipt["estate_id"]:
                        raise EstateError("estate distribution has the wrong beneficiary case")
                    if beneficiary["agent_id"] is None:
                        valid = target["owner_type"] == "system" and target["label"] == SYS_GOV
                    else:
                        valid = (target["owner_type"] == "agent" and target["owner_id"] == beneficiary["agent_id"] and target["kind"] in self.CASH_KINDS)
                    if not valid:
                        raise EstateError("estate distribution has the wrong beneficial wallet")
                expected = self._transfer_legs(account, target, payment["amount_cents"])
                if self.e.cash_estates._transaction_legs(payment["transaction_id"], receipt["tick"], receipt["currency_code"]) != expected:
                    raise EstateError("estate cash payment and ledger disagree")
        for claim in self.store.query("SELECT * FROM estate_claims ORDER BY id"):
            paid = self._paid(claim["id"])
            released = self._released(claim["id"])
            if paid + released > claim["principal_cents"]:
                raise EstateError("estate creditor was overpaid")
            case = self.store.query_one("SELECT * FROM estate_cases WHERE id=?", (claim["estate_id"],))
            if claim["registered_tick"] < case["opened_tick"] or (claim["is_opening"] and claim["registered_tick"] != case["opened_tick"]):
                raise EstateError("estate claim admission has the wrong time")
            for release in self.store.query("SELECT * FROM estate_claim_releases WHERE claim_id=? ORDER BY id", (claim["id"],)):
                if claim["kind"] != "contract_payment" or release["tick"] < claim["registered_tick"]:
                    raise EstateError("only an admitted contractual claim can be released")
                if release["award_id"] is not None and not self.store.scalar(
                        "SELECT id FROM legal_award_obligations WHERE award_id=? AND obligation_id=?", (release["award_id"], claim["source_id"])):
                    raise EstateError("estate claim release has no matching adjudicated obligation")
                if release["reason"] in ("contract_terminated", "contract_expired") and not self.store.scalar(
                        "SELECT o.id FROM obligations o JOIN contracts c ON c.id=o.contract_id WHERE o.id=? AND o.status='cancelled' AND c.status=?",
                        (claim["source_id"], "expired" if release["reason"] == "contract_expired" else "terminated")):
                    raise EstateError("estate contractual release lacks a terminated obligation")
            if claim["kind"] == "legal_award":
                award = self.store.query_one("SELECT * FROM legal_awards WHERE id=?", (claim["source_id"],))
                if award is None or (award["respondent_type"], award["respondent_id"], award["currency_code"], award["destination_account_id"]) != (
                        "agent", case["deceased_agent_id"], claim["currency_code"], claim["destination_account_id"]) or self.e.legal_awards.remaining(award) != claim["principal_cents"] - paid:
                    raise EstateError("estate award claim does not reconcile with its unpaid judgment")
            if claim["kind"] != "bank_principal":
                continue
            loss = self.store.query_one("SELECT * FROM estate_claim_losses WHERE claim_id=?", (claim["id"],))
            recovered = 0
            for payment in self.store.query("SELECT d.*,r.tick FROM estate_disbursements d JOIN estate_receipts r ON r.id=d.receipt_id "
                    "WHERE d.claim_id=? AND d.recovery_transaction_id IS NOT NULL ORDER BY d.id", (claim["id"],)):
                recovered += payment["amount_cents"]
                if self.e.cash_estates._transaction_legs(payment["recovery_transaction_id"], payment["tick"], claim["currency_code"]) != {
                        claim["equity_account_id"]: payment["amount_cents"], claim["loss_account_id"]: -payment["amount_cents"]}:
                    raise EstateError("estate recovery does not reverse the bank loss")
            charged = loss["amount_cents"] if loss else 0
            if paid + charged - recovered != claim["principal_cents"] or recovered > charged:
                raise EstateError("estate principal, write-off and recoveries disagree")
            if loss and self.e.cash_estates._transaction_legs(loss["transaction_id"], loss["tick"], claim["currency_code"]) != {
                    claim["equity_account_id"]: -charged, claim["loss_account_id"]: charged}:
                raise EstateError("estate principal loss does not reconcile")
            loan = self.store.query_one("SELECT * FROM loans WHERE id=?", (claim["source_id"],))
            if loan["outstanding_cents"] != 0 or loan["status"] != ("paid" if paid == claim["principal_cents"] else "default"):
                raise EstateError("estate principal can be collected twice")
        self.e.estate_disputes.check_invariants()
        self.e.civic_authority.check_invariants()
        if self.store.scalar("SELECT p.id FROM insurance_policies p JOIN estate_cases c ON c.deceased_agent_id=p.agent_id "
                             "WHERE p.status='active' LIMIT 1"):
            raise EstateError("a deceased person retains active insurance")
        if self.store.scalar("SELECT s.id FROM compute_subscriptions s JOIN estate_cases c ON c.deceased_agent_id=s.agent_id "
                             "WHERE s.status IN ('pending','active') LIMIT 1"):
            raise EstateError("a deceased person retains pending or active compute access")
        if self.store.scalar("SELECT a.id FROM loan_applications a JOIN estate_cases c ON c.deceased_agent_id=a.borrower_id "
                             "WHERE a.borrower_type='agent' AND a.status='pending' LIMIT 1"):
            raise EstateError("a deceased person retains a pending loan application")
        self._check_ended_services()
        if self.store.scalar("SELECT a.id FROM applications a JOIN estate_cases c ON c.deceased_agent_id=a.agent_id "
                             "WHERE a.state IN ('pending','negotiating') LIMIT 1"):
            raise EstateError("a deceased candidate retains a pending job application")
        if self.store.scalar("SELECT o.id FROM job_offers o JOIN applications a ON a.id=o.application_id "
                             "JOIN estate_cases c ON c.deceased_agent_id=a.agent_id WHERE o.status='pending' LIMIT 1"):
            raise EstateError("a deceased candidate retains a pending job offer")
        if self.e.families.pending_deceased_participant() is not None:
            raise EstateError("an estate still has an unsettled family commitment")
        self.e.estate_securities.check_invariants()
        self.e.estate_unlisted_sales.check_invariants()
        self.e.estate_property.check_invariants()
        self.e.estate_property_sales.check_invariants()
        self.e.estate_administration.check_invariants()
        self.e.legal_authority.check_invariants()
        self.e.legal_representation.check_invariants()

    def _check_ended_services(self):
        endings = {
            "insurance": ("insurance_policies", "agent_id", "cancelled", "end_tick"),
            "compute_access": ("compute_subscriptions", "agent_id", "cancelled", None),
            "loan_application": ("loan_applications", "borrower_id", "expired", "decided_tick"),
        }
        for item in self.store.query("SELECT i.*,c.deceased_agent_id,c.opened_tick FROM estate_items i "
                "JOIN estate_cases c ON c.id=i.estate_id "
                "WHERE i.kind IN ('insurance','compute_access','loan_application') ORDER BY i.id"):
            table, owner_field, closed_status, closed_tick = endings[item["kind"]]
            recorded = json.loads(item["snapshot_json"])
            if (item["disposition"] != "extinguished" or recorded.get("id") != item["source_id"]
                    or recorded.get(owner_field) != item["deceased_agent_id"]
                    or (item["kind"] == "loan_application" and recorded.get("borrower_type") != "agent")):
                raise EstateError("an ended service inventory has the wrong personal identity")
            expected = {**recorded, "status": closed_status}
            if closed_tick:
                expected[closed_tick] = item["opened_tick"]
            actual = self.store.query_one(f"SELECT * FROM {table} WHERE id=?", (item["source_id"],))
            actual = dict(actual) if actual is not None else None
            # Preserve recorded fields while allowing future additive metadata.
            if actual is None or any(key not in actual or actual[key] != value
                                     for key, value in expected.items()):
                raise EstateError("an ended service record changed after death")

    def _transfer_legs(self, source, target, amount):
        expected = {source["id"]: -amount, target["id"]: amount}
        if (source["bank_id"] and target["bank_id"] and source["bank_id"] != target["bank_id"]
                and source["kind"] in ("checking", "savings") and target["kind"] in ("checking", "savings")):
            source_reserve = self.ledger._bank_reserve(source["bank_id"])
            target_reserve = self.ledger._bank_reserve(target["bank_id"])
            if source_reserve and target_reserve:
                expected[source_reserve] = expected.get(source_reserve, 0) - amount
                expected[target_reserve] = expected.get(target_reserve, 0) + amount
        return expected

    def _check_cash_offsets(self, receipt, offsets, payments):
        allocations = [row["transaction_id"] for row in (*offsets, *payments)]
        if not allocations:
            return  # A fully absorbed incoming credit has no available cash.
        frontier = min(allocations)
        if receipt["origin_transaction_id"] is not None and frontier <= receipt["origin_transaction_id"]:
            raise EstateError("estate cash allocation precedes its receipt")
        if offsets and payments and max(row["transaction_id"] for row in offsets) >= min(
                row["transaction_id"] for row in payments):
            raise EstateError("estate cash deficits were not settled before creditors and heirs")
        # Queued credits can already be posted when a receipt starts processing.
        # Reconstruct that frontier instead of using later/current wallet balances.
        balances = self.store.query("SELECT a.id,COALESCE(SUM(le.delta_cents),0) AS balance "
            "FROM accounts a LEFT JOIN ledger_entries le ON le.account_id=a.id AND le.txn_id<? "
            "WHERE a.owner_type='agent' AND a.owner_id=? AND a.currency_code=? "
            "AND a.kind IN ('checking','savings','fx') GROUP BY a.id ORDER BY a.id",
            (frontier, receipt["deceased_agent_id"], receipt["currency_code"]))
        budget = receipt["available_cents"]
        expected_offsets = []
        for balance in balances:
            if balance["id"] == receipt["source_account_id"]:
                if balance["balance"] < receipt["available_cents"]:
                    raise EstateError("estate receipt allocation exceeded its wallet cash")
                continue
            amount = min(budget, max(0, -balance["balance"]))
            if amount:
                expected_offsets.append((balance["id"], balance["balance"], amount))
                budget -= amount
        actual_offsets = [(row["destination_account_id"], row["negative_before_cents"], row["amount_cents"]) for row in offsets]
        if actual_offsets != expected_offsets:
            raise EstateError("estate cash deficit offsets violate the recorded balance priority")
        source = self.store.query_one("SELECT * FROM accounts WHERE id=?", (receipt["source_account_id"],))
        for offset in offsets:
            target = self.store.query_one("SELECT * FROM accounts WHERE id=?", (offset["destination_account_id"],))
            transaction = self.store.query_one("SELECT * FROM transactions WHERE id=?", (offset["transaction_id"],))
            if (target is None or target["owner_type"] != "agent" or target["owner_id"] != receipt["deceased_agent_id"]
                    or target["currency_code"] != receipt["currency_code"] or target["kind"] not in self.CASH_KINDS
                    or target["id"] == source["id"] or transaction is None
                    or transaction["kind"] != "estate_cash_deficit_offset"):
                raise EstateError("estate cash deficit offset has the wrong wallet or transaction")
            expected = self._transfer_legs(source, target, offset["amount_cents"])
            if self.e.cash_estates._transaction_legs(offset["transaction_id"], receipt["tick"], receipt["currency_code"]) != expected:
                raise EstateError("estate cash deficit offset and ledger disagree")

    def _check_waterfall(self, receipt, payments, already_paid, remaining):
        expected_claims = {}
        for claim in self._claims_for_receipt(receipt):
            due = claim["principal_cents"] - already_paid.get(claim["id"], 0) - self._released(claim["id"], receipt)
            payment = min(remaining, max(0, due - self.e.estate_disputes.protected(claim, receipt)))
            if payment:
                expected_claims[claim["id"]] = payment
                already_paid[claim["id"]] = already_paid.get(claim["id"], 0) + payment
                remaining -= payment
        actual_claims = {p["claim_id"]: p["amount_cents"] for p in payments if p["claim_id"] is not None}
        if expected_claims != actual_claims:
            raise EstateError("estate payment violates recorded creditor priority")
        expected_reserves = {}
        for reserve in self.e.estate_disputes.at_receipt(receipt):
            key = ("reserve", reserve["id"])
            amount = min(remaining, max(0, reserve["reserve_limit_cents"] - already_paid.get(key, 0)))
            if amount:
                expected_reserves[reserve["id"]] = amount
                already_paid[key] = already_paid.get(key, 0) + amount
                remaining -= amount
        if expected_reserves != {p["reserve_id"]: p["amount_cents"] for p in payments if p["reserve_id"] is not None}:
            raise EstateError("estate receipt does not fund its recorded legal reserves")
        beneficiaries = self.store.query("SELECT * FROM estate_beneficiaries WHERE estate_id=? ORDER BY COALESCE(agent_id,0),id", (receipt["estate_id"],))
        denominator = sum(b["weight"] for b in beneficiaries)
        portions = {b["id"]: remaining * b["weight"] // denominator for b in beneficiaries}
        remainders = sorted(beneficiaries, key=lambda b: (-(remaining * b["weight"] % denominator), b["agent_id"] or 0))
        for beneficiary in remainders[:remaining-sum(portions.values())]:
            portions[beneficiary["id"]] += 1
        expected_beneficiaries = {key: value for key, value in portions.items() if value}
        actual_beneficiaries = {p["beneficiary_id"]: p["amount_cents"] for p in payments if p["beneficiary_id"] is not None}
        if expected_beneficiaries != actual_beneficiaries:
            raise EstateError("estate cash does not follow recorded beneficiary weights")
