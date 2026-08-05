"""Action validator + executor — the LLM→engine contract (TECH-SPEC §5).

Agents (and institutional roles) emit a list of JSON actions. This module is the
*only* path from a proposed action to a state change. Each action is validated
against hard, non-negotiable rules (does the money exist? does the share exist? is
the counterparty alive? is the rate within guardrails?). Invalid actions are
rejected back to the event log — itself interesting data (agents attempting to
overspend is realistic behaviour), never a crash.
"""
from __future__ import annotations

import json
import logging

from typing import Any, Optional

from .core import Economy
from .credit import LoanTerms
from .firms import DEFAULT_PRODUCT, normalize_business_idea
from .ledger import Leg
from .semantics import semantics_version
from .types import ActionEnvelope, ValidationError, positive_integer_id
from .commands import CommandValidationError, default_registry
from causal import CausalLinkService
from communications.handlers import CommunicationRejected, CommunicationService
from communications.privacy import safe_action_for_diagnostic, safe_command_metadata
from observability import get_logger, log_event as operational_log


logger = get_logger("engine.actions")

VALID_TYPES = {
    "buy_goods", "place_order", "cancel_orders", "apply_loan", "approve_loan", "deny_loan",
    "post_job", "apply_job", "set_price", "hire", "fire", "found_company", "transfer",
    "make_job_offer", "counter_job_offer", "accept_job_offer", "reject_job_offer",
    "open_ipo", "place_ipo_bid", "close_ipo",
    "move_deposits", "set_policy_rate", "decide_liquidity_support", "say_public", "do_nothing",
    "pitch_vc", "fund_pitch", "decline_pitch",          # VC track (P1 R13)
    "buy_insurance", "cancel_insurance",                # health economy (P1 R17)
    # v2 legal-institutional kernel
    "propose_contract", "counter_contract", "accept_contract", "reject_contract",
    "perform_obligation", "issue_legal_notice", "file_claim", "submit_filing",
    "propose_settlement", "accept_settlement", "issue_legal_decision",
    # v2 startup, financing, IP, disclosure, and M&A lifecycle
    "propose_term_sheet", "accept_term_sheet", "run_due_diligence", "close_funding_round",
    "register_ip", "license_ip", "publish_disclosure", "propose_merger", "approve_merger",
    "review_merger", "close_merger",
    # v2 narrative economy and federal-lite political feedback
    "create_claim", "publish_information", "repost_information", "correct_claim",
    "sponsor_bill", "amend_bill", "committee_vote", "cast_legislative_vote",
    "executive_bill_action", "override_veto", "lobby",
    # v2 regional population, trade, migration, and foreign exchange
    "place_fx_order", "cancel_fx_orders", "create_trade_shipment", "request_migration",
    # semantics-7 retirement liquidity
    "withdraw_savings",
    # semantics-8 private and public communication
    "send_message", "reply_message", "forward_message",
    # semantics-11 compute economy and learnable skills
    "buy_compute_plan", "cancel_compute_plan", "set_compute_sponsorship", "study_skill",
    # semantics-12 civic permit workflow
    "apply_business_permit", "attend_civic_appointment", "decide_business_permit",
}

COMMUNICATION_TYPES = {"send_message", "reply_message", "forward_message"}


class ActionExecutor:
    def __init__(self, economy: Economy):
        self.e = economy
        self.store = economy.store
        self.local_currency_action_surfaces = bool(
            economy.config.get("llm", {}).get("local_currency_action_surfaces", False))
        self.engine_semantics_version = semantics_version(economy.config, default=2)
        self.command_registry = default_registry(VALID_TYPES)
        self.communications = CommunicationService(self.store, economy.config)
        self.causal = CausalLinkService(self.store)

    def _startup_authorization_error(
        self, tick: int, actor_id: int, action: dict,
    ) -> dict | None:
        settings = self.e.config.get("entrepreneurship", {})
        if not (
            bool(settings.get("enabled", False))
            and tick >= max(0, int(settings.get("activation_tick", 0)))
        ):
            return None
        supplied = getattr(
            self.e, "_startup_action_authorizations", {}).get((tick, actor_id), [])
        if not any(action == expected for expected in supplied):
            return {
                "ok": False,
                "reason": "startup action must copy a current supplied action exactly",
            }
        return None

    # ── public entry ─────────────────────────────────────────────────────────
    def execute_actions(self, tick: int, actor_id: int, actions: list[dict], phase: str = "EXECUTION") -> list[dict]:
        if self.engine_semantics_version >= 12:
            appointment_indexes = [
                index for index, action in enumerate(actions or [])
                if isinstance(action, dict)
                and action.get("type") == "attend_civic_appointment"
            ]
            if appointment_indexes:
                selected = appointment_indexes[0]
                return [
                    self.execute_action(tick, actor_id, action, phase, seq=index)
                    if index == selected else self._reject(
                        tick, actor_id, action,
                        "attend_civic_appointment consumes the citizen's action for this turn",
                        phase,
                    )
                    for index, action in enumerate(actions or [])
                ]
        if self.engine_semantics_version >= 11:
            study_indexes = [
                index for index, action in enumerate(actions or [])
                if isinstance(action, dict) and action.get("type") == "study_skill"
            ]
            if study_indexes:
                selected = study_indexes[0]
                return [
                    self.execute_action(tick, actor_id, action, phase, seq=index)
                    if index == selected else self._reject(
                        tick, actor_id, action,
                        "study_skill consumes the citizen's action for this turn", phase)
                    for index, action in enumerate(actions or [])
                ]
        results = []
        for i, action in enumerate(actions or []):
            results.append(self.execute_action(tick, actor_id, action, phase, seq=i))
        return results

    def execute_action(self, tick: int, actor_id: int, action: dict, phase: str = "EXECUTION",
                       seq: int = 0) -> dict:
        try:
            envelope = ActionEnvelope.from_mapping(actor_id, action or {})
        except (TypeError, ValueError, ValidationError) as exc:
            return self._reject(tick, actor_id, action, f"invalid action envelope: {exc}", phase)
        action = envelope.engine_action()
        atype = envelope.action_type
        definition = None
        if self.engine_semantics_version >= 8 and atype in VALID_TYPES:
            try:
                definition, payload = self.command_registry.validate(
                    atype, envelope.payload, self.engine_semantics_version)
            except CommandValidationError as exc:
                return self._reject(
                    tick, actor_id, action, f"invalid {atype} command: {exc}", phase)
            action = {"type": atype, **payload}
            if envelope.evidence_event_ids:
                action["evidence_event_ids"] = list(envelope.evidence_event_ids)
            if envelope.model_call_id is not None:
                action["model_call_id"] = envelope.model_call_id
            if envelope.rationale_summary:
                action["rationale_summary"] = envelope.rationale_summary
        proposal_payload = (
            safe_command_metadata(atype, envelope.payload)
            if atype in COMMUNICATION_TYPES else envelope.payload)
        proposal_id = self.store.insert(
            "action_proposals", tick=tick, actor_id=actor_id, action_type=atype,
            payload_json=json.dumps(proposal_payload, sort_keys=True, default=str),
            evidence_event_ids_json=json.dumps(list(envelope.evidence_event_ids)),
            model_call_id=envelope.model_call_id,
            rationale_summary=envelope.rationale_summary,
            validation_status="pending")
        # `withdraw_savings` did not exist in historical semantics. Preserve
        # the exact legacy unknown-action rejection so stored 1-6 runs cannot
        # acquire a new result/event payload merely because the v7 handler is
        # now present in this binary.
        if (atype not in VALID_TYPES
                or (atype in COMMUNICATION_TYPES and self.engine_semantics_version < 8)
                or (atype == "withdraw_savings" and self.engine_semantics_version < 7)
                or (atype in {"buy_compute_plan", "cancel_compute_plan",
                              "set_compute_sponsorship", "study_skill"}
                    and self.engine_semantics_version < 11)
                or (atype in {"apply_business_permit", "attend_civic_appointment",
                              "decide_business_permit"}
                    and self.engine_semantics_version < 12)):
            result = self._reject(tick, actor_id, action, f"unknown action type: {atype}", phase)
            self.store.update("action_proposals", proposal_id, validation_status="rejected",
                              result_json=json.dumps(result, sort_keys=True))
            return result
        actor = self._agent(actor_id)
        if not actor:
            result = self._reject(tick, actor_id, action, "actor missing", phase)
            self.store.update("action_proposals", proposal_id, validation_status="rejected",
                              result_json=json.dumps(result, sort_keys=True))
            return result
        if not actor["alive"]:
            result = self._reject(tick, actor_id, action, "actor not alive", phase)
            self.store.update("action_proposals", proposal_id, validation_status="rejected",
                              result_json=json.dumps(result, sort_keys=True))
            return result
        handler_name = definition.handler_name if definition is not None else f"_do_{atype}"
        handler = getattr(self, handler_name, None)
        if handler is None:
            result = self._reject(tick, actor_id, action, f"unhandled action: {atype}", phase)
            self.store.update("action_proposals", proposal_id, validation_status="rejected",
                              result_json=json.dumps(result, sort_keys=True))
            return result
        try:
            # A handler may perform several writes before an unexpected error.
            # Keep the tick alive, but never retain a partially-applied action.
            with self.store.savepoint(
                    f"action_{tick}_{actor_id}_{phase}_{seq}"):
                last_event_id = int(self.store.scalar(
                    "SELECT COALESCE(MAX(id),0) FROM events", default=0))
                last_transaction_id = int(self.store.scalar(
                    "SELECT COALESCE(MAX(id),0) FROM transactions", default=0))
                if atype == "study_skill":
                    action = {**action, "_proposal_id": proposal_id}
                result = handler(tick, actor_id, action, phase)
                if self.engine_semantics_version >= 11 and result.get("ok"):
                    self.e.cognition.record_accepted_action(
                        tick, actor_id, atype, proposal_id=proposal_id)
                if self.engine_semantics_version >= 8 and result.get("ok"):
                    events = self.store.query(
                        "SELECT id FROM events WHERE id>? ORDER BY id", (last_event_id,))
                    transactions = self.store.query(
                        "SELECT id FROM transactions WHERE id>? ORDER BY id",
                        (last_transaction_id,),
                    )
                    for event in events:
                        self.causal.create(
                            "action_proposal", proposal_id,
                            "event", int(event["id"]),
                            "triggered", "engine", created_tick=tick,
                            provenance={
                                "action_type": atype,
                                "action_result": result,
                            })
                    for transaction in transactions:
                        transaction_id = int(transaction["id"])
                        entries = [
                            int(row["id"]) for row in self.store.query(
                                "SELECT id FROM ledger_entries WHERE txn_id=? ORDER BY id",
                                (transaction_id,),
                            )
                        ]
                        if events:
                            # Domain events are the settled economic fact.  Link
                            # their authoritative ledger effect directly, rather
                            # than making the proposal a second settlement truth.
                            self.causal.create(
                                "event", int(events[-1]["id"]),
                                "ledger_transaction", transaction_id,
                                "settled", "engine", created_tick=tick,
                                provenance={
                                    "action_type": atype,
                                    "proposal_id": proposal_id,
                                },
                                evidence={
                                    "transaction_id": transaction_id,
                                    "entry_ids": entries,
                                },
                            )
                        else:
                            self.causal.create(
                                "action_proposal", proposal_id,
                                "ledger_transaction", transaction_id,
                                "settled", "engine", created_tick=tick,
                                provenance={"action_type": atype},
                                evidence={
                                    "transaction_id": transaction_id,
                                    "entry_ids": entries,
                                },
                            )
        except Exception as exc:  # never let a bad action crash the tick
            operational_log(logger, logging.ERROR, "action.execution.failed",
                            tick=tick, actor_id=actor_id, action_type=atype,
                            phase=phase, error_type=type(exc).__name__, error=str(exc))
            result = self._reject(tick, actor_id, action, f"error: {exc}", phase)
            self.store.update("action_proposals", proposal_id, validation_status="rejected",
                              result_json=json.dumps(result, sort_keys=True))
            return result
        if not result.get("ok"):
            self._reject(tick, actor_id, action, result.get("reason", "rejected"), phase)
        self.store.update(
            "action_proposals", proposal_id,
            validation_status="accepted" if result.get("ok") else "rejected",
            result_json=json.dumps(result, sort_keys=True, default=str))
        return result

    def _reject(self, tick: int, actor_id: int, action: dict, reason: str, phase: str) -> dict:
        public_action = safe_action_for_diagnostic(action)
        self.store.log_event(tick, "action_rejected", {
            "actor_id": actor_id, "action": public_action, "reason": reason},
            phase=phase, subject_type="agent", subject_id=actor_id, importance=0.5)
        return {"ok": False, "reason": reason}

    # ── helpers ──────────────────────────────────────────────────────────────
    def _agent(self, agent_id: int):
        return self.store.query_one("SELECT * FROM agents WHERE id=?", (agent_id,))

    def _alive(self, agent_id: int) -> bool:
        v = self.store.scalar("SELECT alive FROM agents WHERE id=?", (agent_id,))
        return bool(v)

    # ── household / firm actions ─────────────────────────────────────────────
    def _do_do_nothing(self, tick, actor_id, action, phase) -> dict:
        return {"ok": True}

    def _do_buy_compute_plan(self, tick, actor_id, action, phase) -> dict:
        return self.e.cognition.buy_compute_plan(tick, actor_id, action.get("tier", ""))

    def _do_cancel_compute_plan(self, tick, actor_id, action, phase) -> dict:
        return self.e.cognition.cancel_compute_plan(tick, actor_id)

    def _do_set_compute_sponsorship(self, tick, actor_id, action, phase) -> dict:
        return self.e.cognition.set_compute_sponsorship(
            tick, actor_id, action.get("tier", ""),
            int(action.get("max_seats", 0)),
            int(action["firm_id"]) if action.get("firm_id") is not None else None,
        )

    def _do_study_skill(self, tick, actor_id, action, phase) -> dict:
        return self.e.cognition.study_skill(
            tick, actor_id, str(action.get("skill_key", "")),
            proposal_id=int(action["_proposal_id"]))

    def _do_send_message(self, tick, actor_id, action, phase) -> dict:
        try:
            return self.communications.send(tick, actor_id, action, phase=phase)
        except CommunicationRejected as exc:
            return {"ok": False, "reason": exc.code}

    def _do_reply_message(self, tick, actor_id, action, phase) -> dict:
        try:
            return self.communications.reply(tick, actor_id, action, phase=phase)
        except CommunicationRejected as exc:
            return {"ok": False, "reason": exc.code}

    def _do_forward_message(self, tick, actor_id, action, phase) -> dict:
        try:
            return self.communications.forward(tick, actor_id, action, phase=phase)
        except CommunicationRejected as exc:
            return {"ok": False, "reason": exc.code}

    def _do_say_public(self, tick, actor_id, action, phase) -> dict:
        text = str(action.get("text", "")).strip()[:500]
        if not text:
            return {"ok": False, "reason": "empty statement"}
        self.store.log_event(tick, "public_statement", {"actor_id": actor_id, "text": text},
                             phase=phase, subject_type="agent", subject_id=actor_id, importance=1.2)
        return {"ok": True}

    def _do_buy_goods(self, tick, actor_id, action, phase) -> dict:
        firm_id = int(action.get("firm_id", 0))
        qty = int(action.get("qty", 0))
        if qty <= 0:
            return {"ok": False, "reason": "qty must be positive"}
        # Execute the counterparty the agent selected. The engine must not replace
        # a rejected decision with a different trade of its own invention.
        return self.e.firms.buy_goods(tick, actor_id, firm_id, qty)

    def _do_set_price(self, tick, actor_id, action, phase) -> dict:
        firm_id = int(action.get("firm_id", 0)) or self._owned_firm(actor_id)
        if not firm_id:
            return {"ok": False, "reason": "no firm to price"}
        if not self._controls_firm(actor_id, firm_id):
            return {"ok": False, "reason": "actor does not control firm"}
        price = int(action.get("price", 0))
        if price <= 0:
            return {"ok": False, "reason": "price must be positive"}
        self.e.firms.set_price(tick, firm_id, price)
        return {"ok": True}

    def _do_transfer(self, tick, actor_id, action, phase) -> dict:
        to_acct = int(action.get("to_account", 0))
        amount = int(action.get("amount", 0))
        if amount <= 0:
            return {"ok": False, "reason": "amount must be positive"}
        from_acct = self.e.ledger.agent_checking_id(actor_id)
        if from_acct is None:
            return {"ok": False, "reason": "no source account"}
        dest = self.store.query_one(
            "SELECT id, owner_type, owner_id FROM accounts WHERE id=?", (to_acct,))
        if not dest:
            return {"ok": False, "reason": "destination account missing"}
        if dest["owner_type"] == "agent" and not self._alive(int(dest["owner_id"] or 0)):
            return {"ok": False, "reason": "destination agent not alive"}
        if self.e.ledger.balance(from_acct) < amount:
            return {"ok": False, "reason": "insufficient funds"}
        self.e.ledger.transfer(tick, from_acct, to_acct, amount, kind="transfer",
                               memo=str(action.get("memo", ""))[:120])
        return {"ok": True, "amount_cents": amount}

    # ── bank-run primitive ───────────────────────────────────────────────────
    def _do_move_deposits(self, tick, actor_id, action, phase) -> dict:
        to_bank = int(action.get("to_bank_id", 0))
        if self.local_currency_action_surfaces:
            src = self.store.query_one(
                "SELECT ac.* FROM agents a JOIN accounts ac ON ac.id=a.checking_account_id "
                "WHERE a.id=? AND ac.owner_type='agent' AND ac.owner_id=? AND ac.balance_cents>0",
                (actor_id, actor_id))
        else:
            src = self.store.query_one(
                "SELECT * FROM accounts WHERE owner_type='agent' AND owner_id=? AND kind='checking' "
                "AND balance_cents>0 ORDER BY balance_cents DESC LIMIT 1", (actor_id,))
        if not src:
            return {"ok": False, "reason": "no deposits to move"}
        from_bank = int(src["bank_id"]) if src["bank_id"] is not None else 0
        amount = int(action.get("amount", 0)) or int(src["balance_cents"])
        amount = min(amount, int(src["balance_cents"]))
        if amount <= 0:
            return {"ok": False, "reason": "nothing to move"}
        to_bank_row = self.store.query_one("SELECT * FROM banks WHERE id=? AND status='open'", (to_bank,))
        if not to_bank_row or to_bank == from_bank:
            return {"ok": False, "reason": "invalid destination bank"}
        source_currency = str(src["currency_code"] or "USD")
        if str(to_bank_row["currency_code"] or "USD") != source_currency:
            return {"ok": False, "reason": "cross-currency deposit moves require the FX market"}

        # Liquidity check on the source bank — this is where a run bites.
        if from_bank and not self.e.bank.can_settle_outflow(from_bank, amount):
            shortfall = amount - self.e.bank.reserves(from_bank)
            cb = self.e.central_bank_reserve_acct(source_currency)
            supported = False
            if cb is not None:
                supported = self.e.bank.attempt_liquidity_support(
                    tick, from_bank, shortfall, cb,
                    require_authorized_decision=self.engine_semantics_version >= 6,
                    phase=phase, source="deposit_transfer")
            if supported is None:
                pending = self.e.bank.pending_liquidity_requests(
                    bank_id=from_bank, limit=1)
                return {
                    "ok": False, "reason": "liquidity_support_pending",
                    "request_event_id": (
                        int(pending[0]["request_event_id"]) if pending else None),
                }
            if supported is False:
                self.e.bank.fail_bank(tick, from_bank, phase=phase)
                return {"ok": False, "reason": "bank_failed_during_run"}

        dest_acct = self._ensure_checking(actor_id, to_bank)
        self.e.ledger.transfer(tick, int(src["id"]), dest_acct, amount, kind="deposit_move",
                               memo=f"move to bank {to_bank}")
        # Point the agent's primary checking at the destination if the source is emptied.
        if self.e.ledger.balance(int(src["id"])) == 0:
            self.store.execute("UPDATE agents SET checking_account_id=? WHERE id=?", (dest_acct, actor_id))
        self.store.log_event(tick, "deposit_move", {
            "agent_id": actor_id, "from_bank": from_bank, "to_bank": to_bank,
            "amount_cents": amount}, phase=phase, subject_type="agent",
            subject_id=actor_id, importance=1.8)
        return {"ok": True, "amount_cents": amount}

    def _ensure_checking(self, agent_id: int, bank_id: int) -> int:
        row = self.store.query_one(
            "SELECT id FROM accounts WHERE owner_type='agent' AND owner_id=? AND bank_id=? AND kind='checking'",
            (agent_id, bank_id))
        if row:
            return int(row["id"])
        currency = str(self.store.scalar(
            "SELECT currency_code FROM banks WHERE id=?", (bank_id,), default="USD") or "USD")
        return self.e.ledger.create_account("agent", agent_id, "checking", bank_id=bank_id,
                                            label=f"agent:{agent_id}@bank{bank_id}",
                                            currency_code=currency)

    # ── labor ────────────────────────────────────────────────────────────────
    def _do_post_job(self, tick, actor_id, action, phase) -> dict:
        firm_id = int(action.get("firm_id", 0)) or self._owned_firm(actor_id)
        if not firm_id or not self._controls_firm(actor_id, firm_id):
            return {"ok": False, "reason": "actor does not control a firm"}
        wage = int(action.get("wage", 0))
        if wage < 0:
            return {"ok": False, "reason": "wage must be >= 0"}
        title = str(action.get("title", "worker"))[:60]
        job_id = self.e.labor.post_job(tick, firm_id, title, wage)
        return {"ok": True, "job_id": job_id}

    def _do_apply_job(self, tick, actor_id, action, phase) -> dict:
        job_id = int(action.get("job_id", 0))
        if self.local_currency_action_surfaces:
            job = self.store.query_one(
                "SELECT j.status,f.currency_code FROM jobs j JOIN firms f ON f.id=j.firm_id "
                "WHERE j.id=?", (job_id,))
            actor_currency = self.store.scalar(
                "SELECT ac.currency_code FROM agents a JOIN accounts ac "
                "ON ac.id=a.checking_account_id WHERE a.id=?", (actor_id,))
            if not job or job["status"] != "open":
                return {"ok": False, "reason": "job unavailable"}
            if (actor_currency is None
                    or str(job["currency_code"] or "USD")
                    != str(actor_currency or "USD")):
                return {"ok": False, "reason": "job must use the applicant's primary currency"}
        app_id = self.e.labor.apply_job(tick, actor_id, job_id)
        if app_id is None:
            return {"ok": False, "reason": "job unavailable"}
        return {"ok": True, "application_id": app_id}

    def _do_hire(self, tick, actor_id, action, phase) -> dict:
        if self.engine_semantics_version >= 6 and phase != "FIXTURE":
            return {"ok": False, "reason": "use wage offer and acceptance actions for new hires"}
        app_id = int(action.get("application_id", 0))
        app = self.store.query_one("SELECT * FROM applications WHERE id=?", (app_id,))
        if not app:
            return {"ok": False, "reason": "application missing"}
        job = self.store.query_one(
            "SELECT j.firm_id,f.currency_code FROM jobs j JOIN firms f ON f.id=j.firm_id "
            "WHERE j.id=?", (app["job_id"],))
        if not job or not self._controls_firm(actor_id, int(job["firm_id"])):
            return {"ok": False, "reason": "actor does not control hiring firm"}
        if not self._alive(int(app["agent_id"])):
            return {"ok": False, "reason": "candidate not alive"}
        if self.local_currency_action_surfaces:
            candidate_currency = self.store.scalar(
                "SELECT ac.currency_code FROM agents a JOIN accounts ac "
                "ON ac.id=a.checking_account_id WHERE a.id=?", (int(app["agent_id"]),))
            if (candidate_currency is None
                    or str(candidate_currency or "USD") != str(job["currency_code"] or "USD")):
                return {"ok": False, "reason": "hire must use the firm's payroll currency"}
        emp_id = self.e.labor.hire(tick, app_id)
        if emp_id is None:
            return {"ok": False, "reason": "hire failed"}
        return {"ok": True, "employment_id": emp_id}

    def _do_make_job_offer(self, tick, actor_id, action, phase) -> dict:
        if self.engine_semantics_version < 6:
            return {"ok": False, "reason": "wage bargaining requires engine semantics 6"}
        app_id = int(action.get("application_id", 0))
        wage = int(action.get("wage", -1))
        app = self._job_offer_application(app_id)
        if not app:
            return {"ok": False, "reason": "application missing or unavailable"}
        if not self._controls_firm(actor_id, int(app["firm_id"])):
            return {"ok": False, "reason": "actor does not control hiring firm"}
        if int(app["agent_id"]) == actor_id:
            return {"ok": False, "reason": "self-hiring cannot create a bilateral negotiation"}
        if not self._alive(int(app["agent_id"])):
            return {"ok": False, "reason": "candidate not alive"}
        if wage < 0:
            return {"ok": False, "reason": "wage must be >= 0"}
        # A negotiated employment cannot ever cross currencies: payroll posts
        # directly between the firm's and worker's local accounts.  This is a
        # semantics-6 invariant, independent of whether the optional legacy
        # local-currency action filtering is enabled.
        if not self._job_currency_matches(app):
            return {"ok": False, "reason": "offer must use the firm's payroll currency"}
        offer_id = self.e.labor.make_offer(tick, app_id, actor_id, wage)
        if offer_id is None:
            return {"ok": False, "reason": "application already has a pending offer"}
        return {"ok": True, "offer_id": offer_id, "application_id": app_id,
                "wage_cents": wage}

    def _do_counter_job_offer(self, tick, actor_id, action, phase) -> dict:
        if self.engine_semantics_version < 6:
            return {"ok": False, "reason": "wage bargaining requires engine semantics 6"}
        offer_id = positive_integer_id(action.get("offer_id"))
        if offer_id is None:
            return {"ok": False, "reason": "offer_id must be a positive integer"}
        wage = int(action.get("wage", -1))
        offer = self._job_offer(offer_id)
        reason = self._job_offer_counterparty_error(actor_id, offer)
        if reason:
            return {"ok": False, "reason": reason}
        if wage < 0:
            return {"ok": False, "reason": "wage must be >= 0"}
        if not self._job_currency_matches(offer):
            return {"ok": False, "reason": "offer must use the firm's payroll currency"}
        new_offer_id = self.e.labor.make_offer(
            tick, int(offer["application_id"]), actor_id, wage, parent_offer_id=offer_id)
        if new_offer_id is None:
            return {"ok": False, "reason": "offer is stale"}
        return {"ok": True, "offer_id": new_offer_id, "parent_offer_id": offer_id,
                "application_id": int(offer["application_id"]), "wage_cents": wage}

    def _do_accept_job_offer(self, tick, actor_id, action, phase) -> dict:
        if self.engine_semantics_version < 6:
            return {"ok": False, "reason": "wage bargaining requires engine semantics 6"}
        offer_id = positive_integer_id(action.get("offer_id"))
        if offer_id is None:
            return {"ok": False, "reason": "offer_id must be a positive integer"}
        offer = self._job_offer(offer_id)
        reason = self._job_offer_counterparty_error(actor_id, offer)
        if reason:
            return {"ok": False, "reason": reason}
        if not self._alive(int(offer["agent_id"])):
            return {"ok": False, "reason": "candidate not alive"}
        if not self._job_currency_matches(offer):
            return {"ok": False, "reason": "hire must use the firm's payroll currency"}
        emp_id = self.e.labor.accept_offer(tick, offer_id, actor_id)
        if emp_id is None:
            return {"ok": False, "reason": "offer acceptance failed"}
        return {"ok": True, "offer_id": offer_id, "employment_id": emp_id,
                "wage_cents": int(offer["wage_cents"])}

    def _do_reject_job_offer(self, tick, actor_id, action, phase) -> dict:
        if self.engine_semantics_version < 6:
            return {"ok": False, "reason": "wage bargaining requires engine semantics 6"}
        offer_id = positive_integer_id(action.get("offer_id"))
        if offer_id is None:
            return {"ok": False, "reason": "offer_id must be a positive integer"}
        offer = self._job_offer(offer_id)
        reason = self._job_offer_counterparty_error(actor_id, offer)
        if reason:
            return {"ok": False, "reason": reason}
        if not self.e.labor.reject_offer(tick, offer_id, actor_id):
            return {"ok": False, "reason": "offer rejection failed"}
        return {"ok": True, "offer_id": offer_id}

    def _do_fire(self, tick, actor_id, action, phase) -> dict:
        emp_id = int(action.get("employment_id", 0))
        emp = self.store.query_one("SELECT firm_id FROM employments WHERE id=?", (emp_id,))
        if not emp or not self._controls_firm(actor_id, int(emp["firm_id"])):
            return {"ok": False, "reason": "actor does not control firm"}
        return {"ok": self.e.labor.fire(tick, emp_id), "reason": "not active"}

    # -- IPO book building -------------------------------------------------
    def _do_open_ipo(self, tick, actor_id, action, phase) -> dict:
        if self.engine_semantics_version < 6:
            return {"ok": False, "reason": "agent-driven IPOs require engine semantics 6"}
        firm_id = int(action.get("firm_id", 0)) or self._owned_firm(actor_id)
        if not firm_id or not self._controls_firm(actor_id, firm_id):
            return {"ok": False, "reason": "actor does not control issuer"}
        return self.e.firms.open_ipo(
            tick, actor_id, firm_id, int(action.get("shares_offered", 0)),
            int(action.get("reserve_price", 0)),
            int(action.get("minimum_subscription_bps", 5000)))

    def _do_place_ipo_bid(self, tick, actor_id, action, phase) -> dict:
        if self.engine_semantics_version < 6:
            return {"ok": False, "reason": "agent-driven IPOs require engine semantics 6"}
        offering_id = int(action.get("offering_id", 0))
        offering = self.store.query_one(
            "SELECT firm_id FROM ipo_offerings WHERE id=? AND status='building'",
            (offering_id,))
        if offering and self._controls_firm(actor_id, int(offering["firm_id"])):
            return {"ok": False, "reason": "issuer controllers cannot bid in their own offering"}
        return self.e.firms.place_ipo_bid(
            tick, actor_id, offering_id,
            int(action.get("qty", 0)), int(action.get("max_price", 0)))

    def _do_close_ipo(self, tick, actor_id, action, phase) -> dict:
        if self.engine_semantics_version < 6:
            return {"ok": False, "reason": "agent-driven IPOs require engine semantics 6"}
        offering_id = int(action.get("offering_id", 0))
        offering = self.store.query_one(
            "SELECT firm_id,issuer_agent_id FROM ipo_offerings WHERE id=?", (offering_id,))
        if not offering or not self._controls_firm(actor_id, int(offering["firm_id"])):
            return {"ok": False, "reason": "actor does not control issuer"}
        return self.e.firms.close_ipo(tick, actor_id, offering_id)

    # ── founding ─────────────────────────────────────────────────────────────
    def _do_apply_business_permit(self, tick, actor_id, action, phase) -> dict:
        return self.e.city.apply_business_permit(tick, actor_id, action)

    def _do_attend_civic_appointment(self, tick, actor_id, action, phase) -> dict:
        return self.e.city.attend_appointment(
            tick, actor_id, int(action["appointment_id"]))

    def _do_decide_business_permit(self, tick, actor_id, action, phase) -> dict:
        return self.e.city.decide_business_permit(
            tick,
            actor_id,
            int(action["case_id"]),
            str(action["decision"]),
            str(action["reason_code"]),
        )

    def _do_found_company(self, tick, actor_id, action, phase) -> dict:
        entrepreneurship = self.e.config.get("entrepreneurship", {})
        activation_tick = max(0, int(
            entrepreneurship.get("activation_tick", 0)))
        entrepreneurship_active = (
            bool(entrepreneurship.get("enabled", False))
            and tick >= activation_tick
        )
        if entrepreneurship_active and "business_idea" in action:
            daily_limit = max(1, int(
                entrepreneurship.get("maximum_formations_per_tick", 2)))
            formed_today = int(self.store.scalar(
                "SELECT COUNT(*) FROM events WHERE tick=? "
                "AND kind='company_founded' "
                "AND json_type(payload_json,'$.business_idea')='object'",
                (tick,), default=0))
            if formed_today >= daily_limit:
                return {
                    "ok": False,
                    "reason": "daily entrepreneurship capacity reached",
                }
        lawyer_id = int(action.get("lawyer_agent_id", 0))
        lawyer = self._agent(lawyer_id) if lawyer_id else None
        if not lawyer or not lawyer["alive"] or (lawyer["occupation"] or "").lower() != "lawyer":
            return {"ok": False, "reason": "a living lawyer is required to incorporate"}
        name = str(action.get("name", "")).strip()[:60]
        if not name:
            return {"ok": False, "reason": "company needs a name"}
        sector = str(action.get("sector", "services"))[:40]
        civic_permit_required = (
            self.engine_semantics_version >= 12
            and self.e.city.enabled
            and self.e.city.permits_required
        )
        if entrepreneurship_active:
            existing = self.store.query_one(
                "SELECT id FROM firms WHERE founder_agent_id=? AND status<>'bankrupt' LIMIT 1",
                (actor_id,))
            if existing:
                return {"ok": False, "reason": "founder already controls an active company"}
            if not civic_permit_required:
                expected = getattr(
                    self.e, "_entrepreneurship_authorizations", {}).get((tick, actor_id))
                if expected is None:
                    return {
                        "ok": False,
                        "reason": "found_company is available only from a supplied entrepreneurship opportunity",
                    }
                submitted = {key: action.get(key) for key in expected}
                if submitted != expected:
                    return {
                        "ok": False,
                        "reason": "found_company must copy the supplied entrepreneurship action exactly",
                    }
        capital = int(action.get("opening_capital", 0))
        if capital < 0:
            return {"ok": False, "reason": "opening capital must be nonnegative"}
        if capital:
            founder_acct = self.e.ledger.agent_checking_id(actor_id)
            if founder_acct is None or self.e.ledger.balance(founder_acct) < capital:
                return {"ok": False, "reason": "insufficient opening capital"}
        product = action.get("product") if isinstance(action.get("product"), dict) else None
        business_idea = None
        if "business_idea" in action:
            try:
                business_idea = normalize_business_idea(action.get("business_idea"))
            except ValueError as exc:
                return {"ok": False, "reason": str(exc)}
            product = {**DEFAULT_PRODUCT, **(product or {})}
            product["business_idea"] = business_idea
            if not action.get("product") or "product" not in action["product"]:
                product["product"] = business_idea["offering"][:80]
        authorization_id = None
        if civic_permit_required:
            authorization_id, authorization_error = self.e.city.reserve_authorization(
                tick, actor_id, action)
            if authorization_error is not None:
                return {"ok": False, "reason": authorization_error}
        firm_id = self.e.firms.found_firm(tick, actor_id, name, sector, product=product,
                                          opening_capital_cents=capital,
                                          business_idea=business_idea)
        if authorization_id is not None:
            self.e.city.complete_authorization_consumption(
                tick, authorization_id, firm_id)
        return {
            "ok": True,
            "firm_id": firm_id,
            **(
                {"authorization_id": authorization_id}
                if authorization_id is not None else {}
            ),
        }

    # ── equity ───────────────────────────────────────────────────────────────
    def _do_place_order(self, tick, actor_id, action, phase) -> dict:
        if phase != "EXECUTION":
            return {"ok": False, "reason": "market orders may only be placed during EXECUTION"}
        firm_id = int(action.get("firm_id", 0))
        side = str(action.get("side", "")).lower()
        qty = int(action.get("qty", 0))
        if side not in ("buy", "sell") or qty <= 0:
            return {"ok": False, "reason": "bad order side/qty"}
        firm = self.store.query_one(
            "SELECT status,currency_code FROM firms WHERE id=?", (firm_id,))
        if not firm or firm["status"] != "listed":
            return {"ok": False, "reason": "firm not listed"}
        acct = None
        if self.local_currency_action_surfaces:
            acct = self.e.ledger.agent_checking_id(actor_id)
            actor_currency = self.store.scalar(
                "SELECT currency_code FROM accounts WHERE id=?", (acct,), default=None)
            if (acct is None or actor_currency is None
                    or str(actor_currency or "USD") != str(firm["currency_code"] or "USD")):
                return {"ok": False, "reason": "stock orders require the firm's settlement currency"}
        limit = action.get("limit_price")
        order_type = "market" if limit in (None, 0) else "limit"
        limit_cents = int(limit) if limit not in (None, 0) else None
        if side == "sell":
            held = self.e.exchange.shares_held(firm_id, "agent", actor_id)
            if held < qty:
                return {"ok": False, "reason": f"insufficient shares ({held} < {qty})"}
        elif order_type == "limit":
            if acct is None:
                acct = self.e.ledger.agent_checking_id(actor_id)
            if acct is None or self.e.ledger.balance(acct) < qty * limit_cents:
                return {"ok": False, "reason": "insufficient funds for buy order"}
        oid = self.e.exchange.place_order(tick, actor_id, firm_id, side, qty, limit_cents, order_type)
        self.store.log_event(tick, "order_placed", {
            "order_id": oid, "agent_id": actor_id, "firm_id": firm_id, "side": side,
            "qty": qty, "limit_price_cents": limit_cents}, phase=phase)
        return {"ok": True, "order_id": oid}

    def _do_cancel_orders(self, tick, actor_id, action, phase) -> dict:
        self.store.execute(
            "UPDATE orders SET status='cancelled' WHERE agent_id=? AND status IN ('open','partial')",
            (actor_id,))
        return {"ok": True}

    def _do_withdraw_savings(self, tick, actor_id, action, phase) -> dict:
        """Move a retiree's own savings into their own checking account."""
        if self.engine_semantics_version < 7:
            return {"ok": False, "reason": "withdraw_savings requires engine semantics 7"}
        amount = int(action.get("amount", 0))
        if amount <= 0:
            return {"ok": False, "reason": "amount must be positive"}
        agent = self._agent(actor_id)
        if not agent or not bool(agent["retired"]):
            return {"ok": False, "reason": "only retirees may withdraw savings"}
        savings_id = int(agent["savings_account_id"] or 0)
        checking_id = int(agent["checking_account_id"] or 0)
        if not savings_id or not checking_id or savings_id == checking_id:
            return {"ok": False, "reason": "retiree savings and checking accounts are required"}
        accounts = self.store.query(
            "SELECT id,owner_type,owner_id,kind,currency_code FROM accounts "
            "WHERE id IN (?,?) ORDER BY id", (savings_id, checking_id))
        by_id = {int(row["id"]): row for row in accounts}
        savings = by_id.get(savings_id)
        checking = by_id.get(checking_id)
        if (not savings or not checking
                or savings["owner_type"] != "agent" or checking["owner_type"] != "agent"
                or int(savings["owner_id"] or 0) != actor_id
                or int(checking["owner_id"] or 0) != actor_id
                or savings["kind"] != "savings" or checking["kind"] != "checking"):
            return {"ok": False, "reason": "accounts are not the actor's declared savings and checking"}
        if str(savings["currency_code"] or "USD") != str(checking["currency_code"] or "USD"):
            return {"ok": False, "reason": "savings and checking must use the same currency"}
        if self.e.ledger.balance(savings_id) < amount:
            return {"ok": False, "reason": "insufficient savings"}
        txn_id = self.e.ledger.transfer(
            tick, savings_id, checking_id, amount,
            kind="retirement_savings_withdrawal", memo="retirement liquidity drawdown")
        self.store.log_event(
            tick, "retirement_savings_withdrawal",
            {"agent_id": actor_id, "amount_cents": amount, "transaction_id": txn_id},
            phase=phase, subject_type="agent", subject_id=actor_id, importance=1.0)
        return {"ok": True, "amount_cents": amount, "transaction_id": txn_id}

    # ── credit: application + underwriting ───────────────────────────────────
    def _do_apply_loan(self, tick, actor_id, action, phase) -> dict:
        bank_id = int(action.get("bank_id", 0))
        amount = int(action.get("amount", 0))
        if amount <= 0:
            return {"ok": False, "reason": "amount must be positive"}
        bank = self.store.query_one(
            "SELECT status,currency_code FROM banks WHERE id=?", (bank_id,))
        if not bank or bank["status"] != "open":
            return {"ok": False, "reason": "bank unavailable"}
        borrower_type = "firm" if action.get("as_firm") else "agent"
        borrower_id = int(action.get("firm_id", actor_id)) if action.get("as_firm") else actor_id
        if borrower_type == "firm" and not self._controls_firm(actor_id, borrower_id):
            return {"ok": False, "reason": "actor does not control borrowing firm"}
        if (self.local_currency_action_surfaces and borrower_type == "agent"
                and self.store.query_one(
                "SELECT 1 FROM migrations WHERE agent_id=? AND status='pending'", (borrower_id,))):
            return {"ok": False, "reason": "resolve the pending migration before applying for credit"}
        if self.local_currency_action_surfaces:
            if borrower_type == "firm":
                borrower_currency = self.store.scalar(
                    "SELECT currency_code FROM firms WHERE id=?", (borrower_id,), default=None)
            else:
                borrower_currency = self.store.scalar(
                    "SELECT ac.currency_code FROM agents a JOIN accounts ac "
                    "ON ac.id=a.checking_account_id WHERE a.id=?", (borrower_id,), default=None)
            if (borrower_currency is None
                    or str(borrower_currency or "USD") != str(bank["currency_code"] or "USD")):
                return {"ok": False, "reason": "loan bank must use the borrower's primary currency"}
        # One application per bank per week per borrower (validator rule §5),
        # regardless of whether the earlier application is still pending.
        recent = self.store.query_one(
            "SELECT id FROM loan_applications WHERE bank_id=? AND borrower_type=? "
            "AND borrower_id=? AND tick > ?", (bank_id, borrower_type, borrower_id, tick - 7))
        if recent:
            return {"ok": False, "reason": "duplicate application within a week"}
        app_id = self.store.insert(
            "loan_applications", tick=tick, bank_id=bank_id, borrower_type=borrower_type,
            borrower_id=borrower_id, amount_cents=amount,
            purpose=str(action.get("purpose", ""))[:120], status="pending")
        self.store.log_event(tick, "loan_application", {
            "application_id": app_id, "bank_id": bank_id, "borrower_id": borrower_id,
            "amount_cents": amount, "purpose": action.get("purpose", "")}, phase=phase,
            subject_type="agent", subject_id=actor_id, importance=1.5)
        return {"ok": True, "application_id": app_id}

    def _do_approve_loan(self, tick, actor_id, action, phase) -> dict:
        if not self._is_credit_officer(actor_id):
            return {"ok": False, "reason": "only a credit officer can approve loans"}
        app_id = int(action.get("application_id", 0))
        app = self.store.query_one("SELECT * FROM loan_applications WHERE id=?", (app_id,))
        if not app or app["status"] != "pending":
            return {"ok": False, "reason": "application not pending"}
        if (self.local_currency_action_surfaces and app["borrower_type"] == "agent"
                and self.store.query_one(
                "SELECT 1 FROM migrations WHERE agent_id=? AND status='pending'",
                (int(app["borrower_id"]),))):
            return {"ok": False, "reason": "resolve the pending migration before loan approval"}
        bank = self.store.query_one("SELECT * FROM banks WHERE id=?", (app["bank_id"],))
        policy = _json(bank["risk_policy_json"], {})
        rate = int(action.get("rate_bps", policy.get("default_rate_bps", 900)))
        rate = max(policy.get("min_rate_bps", 300), min(policy.get("max_rate_bps", 3000), rate))
        term = int(action.get("term_ticks", 360))
        loan_id = self.e.bank.disburse_loan(
            tick, int(app["bank_id"]), app["borrower_type"], int(app["borrower_id"]),
            LoanTerms(int(app["amount_cents"]), rate, term), purpose=app["purpose"] or "",
            collateral=_json(app["collateral_json"], {}))
        if loan_id is None:
            self.store.update("loan_applications", app_id, status="denied", decided_tick=tick)
            return {"ok": False, "reason": "disbursement failed (liquidity)"}
        self.store.update("loan_applications", app_id, status="approved", decided_tick=tick,
                          rate_bps=rate, term_ticks=term, loan_id=loan_id)
        return {"ok": True, "loan_id": loan_id, "rate_bps": rate}

    def _do_deny_loan(self, tick, actor_id, action, phase) -> dict:
        if not self._is_credit_officer(actor_id):
            return {"ok": False, "reason": "only a credit officer can deny loans"}
        app_id = int(action.get("application_id", 0))
        app = self.store.query_one("SELECT status FROM loan_applications WHERE id=?", (app_id,))
        if not app or app["status"] != "pending":
            return {"ok": False, "reason": "application not pending"}
        self.store.update("loan_applications", app_id, status="denied", decided_tick=tick)
        self.store.log_event(tick, "loan_denied", {
            "application_id": app_id, "reason": str(action.get("reason", ""))[:120]}, phase=phase)
        return {"ok": True}

    # ── VC track: pitch → evaluation → term sheet → equity (P1 R13) ─────────
    def _do_pitch_vc(self, tick, actor_id, action, phase) -> dict:
        authorization_error = self._startup_authorization_error(
            tick, actor_id, action)
        if authorization_error is not None:
            return authorization_error
        firm_id = int(action.get("firm_id", 0)) or self._owned_firm(actor_id)
        if not firm_id or not self._controls_firm(actor_id, firm_id):
            return {"ok": False, "reason": "actor does not control a firm to pitch"}
        ask = int(action.get("ask", action.get("amount", 0)))
        pid = self.e.vc.pitch(tick, actor_id, firm_id, ask,
                              summary=str(action.get("summary", ""))[:300])
        if pid is None:
            return {"ok": False, "reason": "pitch rejected (firm not private, bad ask, or one already pending)"}
        return {"ok": True, "pitch_id": pid}

    def _do_fund_pitch(self, tick, actor_id, action, phase) -> dict:
        if not self._is_vc_partner(actor_id):
            return {"ok": False, "reason": "only a VC partner can issue a term sheet"}
        pitch_id = int(action.get("pitch_id", 0))
        amount = int(action.get("amount", 0))
        equity_bps = int(action.get("equity_bps", 2000))
        return self.e.vc.fund(tick, pitch_id, actor_id, amount, equity_bps)

    def _do_decline_pitch(self, tick, actor_id, action, phase) -> dict:
        if not self._is_vc_partner(actor_id):
            return {"ok": False, "reason": "only a VC partner can decline a pitch"}
        return self.e.vc.decline(tick, int(action.get("pitch_id", 0)), actor_id,
                                 reason=str(action.get("reason", ""))[:120])

    # ── health insurance (P1 R17) ────────────────────────────────────────────
    def _do_buy_insurance(self, tick, actor_id, action, phase) -> dict:
        existing = self.store.query_one(
            "SELECT 1 FROM insurance_policies WHERE agent_id=? AND status='active'", (actor_id,))
        if existing:
            return {"ok": False, "reason": "already insured"}
        acct = self.e.ledger.agent_checking_id(actor_id)
        currency = self.store.scalar(
            "SELECT currency_code FROM accounts WHERE id=?", (acct,), default=None) if acct else None
        insurer = self.store.query_one(
            "SELECT id, account_id FROM firms WHERE sector='insurance' AND status<>'bankrupt' "
            "AND currency_code=? ORDER BY id LIMIT 1", (str(currency or "USD"),))
        if not insurer:
            return {"ok": False, "reason": "no insurer operating"}
        h = self.e.lifecycle.h
        premium = int(action.get("premium", h["premium_cents"]))
        coverage = int(h["coverage_bps"])
        interval = int(h["premium_interval_ticks"])
        if acct is None or self.e.ledger.balance(acct) < premium:
            return {"ok": False, "reason": "cannot afford first premium"}
        # First premium settles on purchase; renewals run in the nightly sweep.
        self.e.ledger.transfer(tick, acct, int(insurer["account_id"]), premium,
                               kind="insurance_premium", memo=f"new policy agent {actor_id}")
        pol_id = self.store.insert(
            "insurance_policies", agent_id=actor_id, insurer_firm_id=int(insurer["id"]),
            premium_cents=premium, coverage_bps=coverage, start_tick=tick,
            next_premium_tick=tick + interval, premium_interval_ticks=interval,
            status="active")
        self.store.log_event(tick, "policy_bought", {
            "agent_id": actor_id, "policy_id": pol_id, "premium_cents": premium,
            "coverage_bps": coverage}, phase=phase, subject_type="agent",
            subject_id=actor_id, importance=1.0)
        return {"ok": True, "policy_id": pol_id}

    def _do_cancel_insurance(self, tick, actor_id, action, phase) -> dict:
        pol = self.store.query_one(
            "SELECT id FROM insurance_policies WHERE agent_id=? AND status='active'", (actor_id,))
        if not pol:
            return {"ok": False, "reason": "no active policy"}
        self.store.update("insurance_policies", int(pol["id"]), status="cancelled", end_tick=tick)
        return {"ok": True}

    # ── monetary policy (guardrailed) ────────────────────────────────────────
    # v2 legal-institutional actions.  Each delegates to the deterministic
    # legal service; prose in the proposal is never executed.
    def _do_propose_contract(self, tick, actor_id, action, phase) -> dict:
        return self.e.legal.propose_contract(tick, actor_id, action)

    def _do_counter_contract(self, tick, actor_id, action, phase) -> dict:
        return self.e.legal.counter_contract(
            tick, actor_id, int(action.get("contract_id", 0)),
            dict(action.get("changes", {})))

    def _do_accept_contract(self, tick, actor_id, action, phase) -> dict:
        return self.e.legal.accept_contract(
            tick, actor_id, int(action.get("contract_id", 0)),
            str(action.get("party_type", "agent")), int(action.get("party_id", actor_id)))

    def _do_reject_contract(self, tick, actor_id, action, phase) -> dict:
        return self.e.legal.reject_contract(tick, actor_id, int(action.get("contract_id", 0)))

    def _do_perform_obligation(self, tick, actor_id, action, phase) -> dict:
        return self.e.legal.perform_obligation(tick, actor_id, int(action.get("obligation_id", 0)))

    def _do_issue_legal_notice(self, tick, actor_id, action, phase) -> dict:
        return self.e.legal.issue_notice(tick, actor_id, action)

    def _do_file_claim(self, tick, actor_id, action, phase) -> dict:
        return self.e.legal.file_claim(tick, actor_id, action)

    def _do_submit_filing(self, tick, actor_id, action, phase) -> dict:
        return self.e.legal.submit_filing(tick, actor_id, action)

    def _do_propose_settlement(self, tick, actor_id, action, phase) -> dict:
        return self.e.legal.propose_settlement(
            tick, actor_id, int(action.get("matter_id", 0)), dict(action.get("terms", {})))

    def _do_accept_settlement(self, tick, actor_id, action, phase) -> dict:
        return self.e.legal.accept_settlement(tick, actor_id, int(action.get("matter_id", 0)))

    def _do_issue_legal_decision(self, tick, actor_id, action, phase) -> dict:
        return self.e.legal.issue_decision(tick, actor_id, action)

    def _do_propose_term_sheet(self, tick, actor_id, action, phase) -> dict:
        authorization_error = self._startup_authorization_error(
            tick, actor_id, action)
        if authorization_error is not None:
            return authorization_error
        return self.e.startups.propose_term_sheet(tick, actor_id, action)

    def _do_accept_term_sheet(self, tick, actor_id, action, phase) -> dict:
        authorization_error = self._startup_authorization_error(
            tick, actor_id, action)
        if authorization_error is not None:
            return authorization_error
        return self.e.startups.accept_term_sheet(tick, actor_id, int(action.get("term_sheet_id", 0)))

    def _do_run_due_diligence(self, tick, actor_id, action, phase) -> dict:
        authorization_error = self._startup_authorization_error(
            tick, actor_id, action)
        if authorization_error is not None:
            return authorization_error
        return self.e.startups.run_due_diligence(tick, actor_id, int(action.get("term_sheet_id", 0)))

    def _do_close_funding_round(self, tick, actor_id, action, phase) -> dict:
        authorization_error = self._startup_authorization_error(
            tick, actor_id, action)
        if authorization_error is not None:
            return authorization_error
        return self.e.startups.close_funding_round(tick, actor_id, int(action.get("term_sheet_id", 0)))

    def _do_register_ip(self, tick, actor_id, action, phase) -> dict:
        entrepreneurship = self.e.config.get("entrepreneurship", {})
        activation_tick = max(0, int(
            entrepreneurship.get("activation_tick", 0)))
        firm_id = int(action.get("firm_id", 0))
        firm = self.store.query_one(
            "SELECT founded_tick,product_json FROM firms WHERE id=?", (firm_id,))
        product = {}
        if firm is not None:
            try:
                product = json.loads(firm["product_json"] or "{}")
            except (TypeError, ValueError):
                product = {}
        native_startup = (
            bool(entrepreneurship.get("enabled", False))
            and tick >= activation_tick
            and firm is not None
            and int(firm["founded_tick"] or 0) >= activation_tick
            and isinstance(product.get("business_idea"), dict)
        )
        if native_startup and not self.store.query_one(
            "SELECT 1 FROM funding_rounds WHERE firm_id=? "
            "AND status='closed' LIMIT 1",
            (firm_id,),
        ):
            return {
                "ok": False,
                "reason": "native startup IP requires a closed funding round",
            }
        authorization_error = self._startup_authorization_error(
            tick, actor_id, action)
        if authorization_error is not None:
            return authorization_error
        return self.e.startups.register_ip(tick, actor_id, action)

    def _do_license_ip(self, tick, actor_id, action, phase) -> dict:
        return self.e.startups.license_ip(tick, actor_id, action)

    def _do_publish_disclosure(self, tick, actor_id, action, phase) -> dict:
        return self.e.startups.publish_disclosure(
            tick, actor_id, int(action.get("firm_id", 0)),
            str(action.get("disclosure_type", "earnings")), int(action.get("lookback_ticks", 30)))

    def _do_propose_merger(self, tick, actor_id, action, phase) -> dict:
        authorization_error = self._startup_authorization_error(
            tick, actor_id, action)
        if authorization_error is not None:
            return authorization_error
        return self.e.startups.propose_merger(tick, actor_id, action)

    def _do_approve_merger(self, tick, actor_id, action, phase) -> dict:
        authorization_error = self._startup_authorization_error(
            tick, actor_id, action)
        if authorization_error is not None:
            return authorization_error
        return self.e.startups.approve_merger(tick, actor_id, int(action.get("merger_id", 0)))

    def _do_review_merger(self, tick, actor_id, action, phase) -> dict:
        return self.e.startups.review_merger(
            tick, actor_id, int(action.get("merger_id", 0)), dict(action.get("remedy", {})))

    def _do_close_merger(self, tick, actor_id, action, phase) -> dict:
        authorization_error = self._startup_authorization_error(
            tick, actor_id, action)
        if authorization_error is not None:
            return authorization_error
        return self.e.startups.close_merger(tick, actor_id, int(action.get("merger_id", 0)))

    def _do_create_claim(self, tick, actor_id, action, phase) -> dict:
        return self.e.information.create_claim(tick, actor_id, action)

    def _do_publish_information(self, tick, actor_id, action, phase) -> dict:
        return self.e.information.publish_item(tick, actor_id, action)

    def _do_repost_information(self, tick, actor_id, action, phase) -> dict:
        return self.e.information.repost(
            tick, actor_id, int(action.get("parent_item_id", 0)), str(action.get("commentary", "")))

    def _do_correct_claim(self, tick, actor_id, action, phase) -> dict:
        return self.e.information.correct_claim(
            tick, actor_id, int(action.get("original_claim_id", 0)), dict(action.get("correction", {})))

    def _do_sponsor_bill(self, tick, actor_id, action, phase) -> dict:
        return self.e.politics.sponsor_bill(tick, actor_id, action)

    def _do_amend_bill(self, tick, actor_id, action, phase) -> dict:
        return self.e.politics.amend_bill(
            tick, actor_id, int(action.get("bill_id", 0)), dict(action.get("amendment", {})))

    def _do_committee_vote(self, tick, actor_id, action, phase) -> dict:
        return self.e.politics.committee_vote(
            tick, actor_id, int(action.get("bill_id", 0)), str(action.get("vote", "abstain")))

    def _do_cast_legislative_vote(self, tick, actor_id, action, phase) -> dict:
        return self.e.politics.cast_vote(
            tick, actor_id, int(action.get("bill_id", 0)), str(action.get("vote", "abstain")))

    def _do_executive_bill_action(self, tick, actor_id, action, phase) -> dict:
        return self.e.politics.executive_action(
            tick, actor_id, int(action.get("bill_id", 0)), str(action.get("action", "")),
            int(action.get("effective_delay_ticks", 1)))

    def _do_override_veto(self, tick, actor_id, action, phase) -> dict:
        return self.e.politics.override_veto(
            tick, actor_id, int(action.get("bill_id", 0)), str(action.get("vote", "yes")))

    def _do_lobby(self, tick, actor_id, action, phase) -> dict:
        return self.e.politics.lobby(tick, actor_id, action)

    def _do_place_fx_order(self, tick, actor_id, action, phase) -> dict:
        return self.e.regions.place_fx_order(tick, actor_id, action)

    def _do_cancel_fx_orders(self, tick, actor_id, action, phase) -> dict:
        return self.e.regions.cancel_fx_orders(tick, actor_id, action.get("pair"))

    def _do_create_trade_shipment(self, tick, actor_id, action, phase) -> dict:
        return self.e.regions.create_shipment(tick, actor_id, action)

    def _do_request_migration(self, tick, actor_id, action, phase) -> dict:
        return self.e.regions.request_migration(
            tick, actor_id, int(action.get("destination_region_id", 0)),
            str(action.get("reason", "")))

    def _do_decide_liquidity_support(self, tick, actor_id, action, phase) -> dict:
        if self.engine_semantics_version < 6:
            return {"ok": False, "reason": "agent-authored liquidity support is unavailable"}
        request_event_id = int(action.get("request_event_id", 0))
        evidence = action.get("evidence_event_ids", [])
        try:
            evidence_ids = [int(item) for item in evidence]
        except (TypeError, ValueError):
            return {"ok": False, "reason": "liquidity decision evidence is malformed"}
        if evidence_ids != [request_event_id] or request_event_id <= 0:
            return {
                "ok": False,
                "reason": "liquidity decision must cite exactly its request event",
            }
        request = self.e.bank.pending_liquidity_request(request_event_id)
        central_bank_reserve_acct = None
        if request is not None:
            currency_code = self.store.scalar(
                "SELECT currency_code FROM banks WHERE id=?",
                (int(request["bank_id"]),), default=None)
            if currency_code is not None:
                central_bank_reserve_acct = self.e.central_bank_reserve_acct(
                    str(currency_code))
        return self.e.bank.decide_liquidity_support(
            tick, actor_id, request_event_id, str(action.get("decision", "")),
            action.get("model_call_id"), central_bank_reserve_acct, phase=phase)

    def _do_set_policy_rate(self, tick, actor_id, action, phase) -> dict:
        a = self._agent(actor_id)
        if not a or a["role"] != "central_banker":
            return {"ok": False, "reason": "only the central banker sets policy"}
        guard = self.e.config.get("central_bank", {})
        cur = self.e.policy_rate_bps()
        target = int(action.get("rate_bps", cur))
        max_step = int(guard.get("max_step_bps", 50))
        lo = int(guard.get("min_rate_bps", 0))
        hi = int(guard.get("max_rate_bps", 2000))
        clamped = max(cur - max_step, min(cur + max_step, target))
        clamped = max(lo, min(hi, clamped))
        self.store.record_metric(tick, "policy_rate", clamped)
        self.store.log_event(tick, "policy_rate_set", {
            "old_bps": cur, "requested_bps": target, "new_bps": clamped}, phase=phase,
            subject_type="central_bank", subject_id=actor_id, importance=3.0)
        return {"ok": True, "rate_bps": clamped}

    # ── role / ownership predicates ──────────────────────────────────────────
    def _owned_firm(self, agent_id: int) -> int:
        v = self.store.scalar("SELECT id FROM firms WHERE founder_agent_id=? AND status<>'bankrupt' LIMIT 1",
                              (agent_id,))
        return int(v) if v is not None else 0

    def _controls_firm(self, agent_id: int, firm_id: int) -> bool:
        firm = self.store.query_one("SELECT founder_agent_id, status FROM firms WHERE id=?", (firm_id,))
        if not firm or firm["status"] == "bankrupt":
            return False
        if firm["founder_agent_id"] == agent_id:
            return True
        # Managers (staff employed by the firm with a management role) may act for it.
        a = self._agent(agent_id)
        return bool(a and a["employer_id"] == firm_id and (a["role"] or "") in ("manager", "founder"))

    def _is_credit_officer(self, agent_id: int) -> bool:
        a = self._agent(agent_id)
        return bool(a and a["role"] == "credit_officer" and a["alive"])

    def _is_vc_partner(self, agent_id: int) -> bool:
        a = self._agent(agent_id)
        return bool(a and a["role"] == "vc_partner" and a["alive"])

    def _job_offer_application(self, application_id: int):
        return self.store.query_one(
            "SELECT ap.*,j.firm_id,j.status AS job_status,f.currency_code "
            "FROM applications ap JOIN jobs j ON j.id=ap.job_id "
            "JOIN firms f ON f.id=j.firm_id WHERE ap.id=? "
            "AND ap.state IN ('pending','negotiating') AND j.status='open'",
            (application_id,))

    def _job_offer(self, offer_id: int):
        return self.store.query_one(
            "SELECT jo.*,ap.agent_id,ap.job_id,ap.state AS application_state,"
            "j.firm_id,j.status AS job_status,f.currency_code "
            "FROM job_offers jo JOIN applications ap ON ap.id=jo.application_id "
            "JOIN jobs j ON j.id=ap.job_id JOIN firms f ON f.id=j.firm_id "
            "WHERE jo.id=?", (offer_id,))

    def _job_offer_counterparty_error(self, actor_id: int, offer) -> Optional[str]:
        if not offer or offer["status"] != "pending":
            return "offer missing or stale"
        if offer["application_state"] != "negotiating" or offer["job_status"] != "open":
            return "application is no longer negotiable"
        candidate_id = int(offer["agent_id"])
        proposer_id = int(offer["proposer_agent_id"])
        if actor_id == proposer_id:
            return "proposer cannot respond to its own offer"
        if actor_id == candidate_id:
            return None
        if self._controls_firm(actor_id, int(offer["firm_id"])) and proposer_id == candidate_id:
            return None
        return "only the receiving candidate or hiring firm may respond"

    def _job_currency_matches(self, row) -> bool:
        candidate_currency = self.store.scalar(
            "SELECT ac.currency_code FROM agents a JOIN accounts ac "
            "ON ac.id=a.checking_account_id WHERE a.id=?", (int(row["agent_id"]),))
        return (candidate_currency is not None
                and str(candidate_currency or "USD") == str(row["currency_code"] or "USD"))


def _json(value, default):
    import json
    if value is None or value == "":
        return default
    try:
        return json.loads(value) if isinstance(value, str) else value
    except Exception:
        return default
