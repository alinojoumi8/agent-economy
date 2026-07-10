"""Action validator + executor — the LLM→engine contract (TECH-SPEC §5).

Agents (and institutional roles) emit a list of JSON actions. This module is the
*only* path from a proposed action to a state change. Each action is validated
against hard, non-negotiable rules (does the money exist? does the share exist? is
the counterparty alive? is the rate within guardrails?). Invalid actions are
rejected back to the event log — itself interesting data (agents attempting to
overspend is realistic behaviour), never a crash.
"""
from __future__ import annotations

from typing import Any, Optional

from .core import Economy
from .credit import LoanTerms
from .ledger import Leg

VALID_TYPES = {
    "buy_goods", "place_order", "cancel_orders", "apply_loan", "approve_loan", "deny_loan",
    "post_job", "apply_job", "set_price", "hire", "fire", "found_company", "transfer",
    "move_deposits", "set_policy_rate", "say_public", "do_nothing",
    "pitch_vc", "fund_pitch", "decline_pitch",          # VC track (P1 R13)
    "buy_insurance", "cancel_insurance",                # health economy (P1 R17)
}


class ActionExecutor:
    def __init__(self, economy: Economy):
        self.e = economy
        self.store = economy.store

    # ── public entry ─────────────────────────────────────────────────────────
    def execute_actions(self, tick: int, actor_id: int, actions: list[dict], phase: str = "EXECUTION") -> list[dict]:
        results = []
        for i, action in enumerate(actions or []):
            results.append(self.execute_action(tick, actor_id, action, phase, seq=i))
        return results

    def execute_action(self, tick: int, actor_id: int, action: dict, phase: str = "EXECUTION",
                       seq: int = 0) -> dict:
        atype = (action or {}).get("type")
        if atype not in VALID_TYPES:
            return self._reject(tick, actor_id, action, f"unknown action type: {atype}", phase)
        actor = self._agent(actor_id)
        if not actor:
            return self._reject(tick, actor_id, action, "actor missing", phase)
        if not actor["alive"]:
            return self._reject(tick, actor_id, action, "actor not alive", phase)
        handler = getattr(self, f"_do_{atype}", None)
        if handler is None:
            return self._reject(tick, actor_id, action, f"unhandled action: {atype}", phase)
        try:
            result = handler(tick, actor_id, action, phase)
        except Exception as exc:  # never let a bad action crash the tick
            return self._reject(tick, actor_id, action, f"error: {exc}", phase)
        if not result.get("ok"):
            self._reject(tick, actor_id, action, result.get("reason", "rejected"), phase)
        return result

    def _reject(self, tick: int, actor_id: int, action: dict, reason: str, phase: str) -> dict:
        self.store.log_event(tick, "action_rejected", {
            "actor_id": actor_id, "action": action, "reason": reason},
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

        # Liquidity check on the source bank — this is where a run bites.
        if from_bank and not self.e.bank.can_settle_outflow(from_bank, amount):
            shortfall = amount - self.e.bank.reserves(from_bank)
            cb = self.e.central_bank_reserve_acct()
            supported = False
            if cb is not None:
                supported = self.e.bank.attempt_liquidity_support(tick, from_bank, shortfall, cb)
            if not supported:
                self.e.bank.fail_bank(tick, from_bank)
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
        return self.e.ledger.create_account("agent", agent_id, "checking", bank_id=bank_id,
                                            label=f"agent:{agent_id}@bank{bank_id}")

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
        app_id = self.e.labor.apply_job(tick, actor_id, job_id)
        if app_id is None:
            return {"ok": False, "reason": "job unavailable"}
        return {"ok": True, "application_id": app_id}

    def _do_hire(self, tick, actor_id, action, phase) -> dict:
        app_id = int(action.get("application_id", 0))
        app = self.store.query_one("SELECT * FROM applications WHERE id=?", (app_id,))
        if not app:
            return {"ok": False, "reason": "application missing"}
        job = self.store.query_one("SELECT firm_id FROM jobs WHERE id=?", (app["job_id"],))
        if not job or not self._controls_firm(actor_id, int(job["firm_id"])):
            return {"ok": False, "reason": "actor does not control hiring firm"}
        if not self._alive(int(app["agent_id"])):
            return {"ok": False, "reason": "candidate not alive"}
        emp_id = self.e.labor.hire(tick, app_id)
        if emp_id is None:
            return {"ok": False, "reason": "hire failed"}
        return {"ok": True, "employment_id": emp_id}

    def _do_fire(self, tick, actor_id, action, phase) -> dict:
        emp_id = int(action.get("employment_id", 0))
        emp = self.store.query_one("SELECT firm_id FROM employments WHERE id=?", (emp_id,))
        if not emp or not self._controls_firm(actor_id, int(emp["firm_id"])):
            return {"ok": False, "reason": "actor does not control firm"}
        return {"ok": self.e.labor.fire(tick, emp_id), "reason": "not active"}

    # ── founding ─────────────────────────────────────────────────────────────
    def _do_found_company(self, tick, actor_id, action, phase) -> dict:
        lawyer_id = int(action.get("lawyer_agent_id", 0))
        lawyer = self._agent(lawyer_id) if lawyer_id else None
        if not lawyer or not lawyer["alive"] or (lawyer["occupation"] or "").lower() != "lawyer":
            return {"ok": False, "reason": "a living lawyer is required to incorporate"}
        name = str(action.get("name", "")).strip()[:60]
        if not name:
            return {"ok": False, "reason": "company needs a name"}
        sector = str(action.get("sector", "services"))[:40]
        capital = int(action.get("opening_capital", 0))
        if capital < 0:
            return {"ok": False, "reason": "opening capital must be nonnegative"}
        if capital:
            founder_acct = self.e.ledger.agent_checking_id(actor_id)
            if founder_acct is None or self.e.ledger.balance(founder_acct) < capital:
                return {"ok": False, "reason": "insufficient opening capital"}
        product = action.get("product") if isinstance(action.get("product"), dict) else None
        firm_id = self.e.firms.found_firm(tick, actor_id, name, sector, product=product,
                                          opening_capital_cents=capital)
        return {"ok": True, "firm_id": firm_id}

    # ── equity ───────────────────────────────────────────────────────────────
    def _do_place_order(self, tick, actor_id, action, phase) -> dict:
        if phase != "EXECUTION":
            return {"ok": False, "reason": "market orders may only be placed during EXECUTION"}
        firm_id = int(action.get("firm_id", 0))
        side = str(action.get("side", "")).lower()
        qty = int(action.get("qty", 0))
        if side not in ("buy", "sell") or qty <= 0:
            return {"ok": False, "reason": "bad order side/qty"}
        firm = self.store.query_one("SELECT status FROM firms WHERE id=?", (firm_id,))
        if not firm or firm["status"] != "listed":
            return {"ok": False, "reason": "firm not listed"}
        limit = action.get("limit_price")
        order_type = "market" if limit in (None, 0) else "limit"
        limit_cents = int(limit) if limit not in (None, 0) else None
        if side == "sell":
            held = self.e.exchange.shares_held(firm_id, "agent", actor_id)
            if held < qty:
                return {"ok": False, "reason": f"insufficient shares ({held} < {qty})"}
        elif order_type == "limit":
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

    # ── credit: application + underwriting ───────────────────────────────────
    def _do_apply_loan(self, tick, actor_id, action, phase) -> dict:
        bank_id = int(action.get("bank_id", 0))
        amount = int(action.get("amount", 0))
        if amount <= 0:
            return {"ok": False, "reason": "amount must be positive"}
        bank = self.store.query_one("SELECT status FROM banks WHERE id=?", (bank_id,))
        if not bank or bank["status"] != "open":
            return {"ok": False, "reason": "bank unavailable"}
        borrower_type = "firm" if action.get("as_firm") else "agent"
        borrower_id = int(action.get("firm_id", actor_id)) if action.get("as_firm") else actor_id
        if borrower_type == "firm" and not self._controls_firm(actor_id, borrower_id):
            return {"ok": False, "reason": "actor does not control borrowing firm"}
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
        insurer = self.store.query_one(
            "SELECT id, account_id FROM firms WHERE sector='insurance' AND status<>'bankrupt' "
            "ORDER BY id LIMIT 1")
        if not insurer:
            return {"ok": False, "reason": "no insurer operating"}
        h = self.e.lifecycle.h
        premium = int(action.get("premium", h["premium_cents"]))
        coverage = int(h["coverage_bps"])
        interval = int(h["premium_interval_ticks"])
        acct = self.e.ledger.agent_checking_id(actor_id)
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


def _json(value, default):
    import json
    if value is None or value == "":
        return default
    try:
        return json.loads(value) if isinstance(value, str) else value
    except Exception:
        return default
