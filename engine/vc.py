"""Venture capital / private funding track (PRD R13).

Pitch → partner evaluation → term sheet → equity on the cap table → follow-on or
write-off. The pitch and the funding/decline decisions are agent actions (the VC
partner is an LLM seat in real runs, a scripted policy offline); this module is
the deterministic engine side: it validates, moves the money, issues post-money
shares, and tracks outcomes.

Investment mechanics: a funded pitch transfers cash from the partner's personal
fund account into the firm and issues NEW shares (dilution) so the VC holds
`equity_bps` of the post-money cap table. A firm whose funded pitch later goes
bankrupt is marked `written_off` on the nightly sweep — the equity was already
wiped by the bankruptcy waterfall.
"""
from __future__ import annotations

import json
from typing import Optional

from .ledger import Ledger
from .store import Store

PITCH_TTL_TICKS = 14   # pending pitches expire like stale loan applications


class VentureCapital:
    def __init__(self, store: Store, ledger: Ledger):
        self.store = store
        self.ledger = ledger

    # ── founder side ─────────────────────────────────────────────────────────
    def pitch(self, tick: int, founder_agent_id: int, firm_id: int, ask_cents: int,
              summary: str = "") -> Optional[int]:
        firm = self.store.query_one("SELECT * FROM firms WHERE id=?", (firm_id,))
        if not firm or firm["status"] != "private":
            return None   # private rounds are for private firms (listed raise on-market)
        if ask_cents <= 0:
            return None
        pending = self.store.query_one(
            "SELECT 1 FROM pitches WHERE firm_id=? AND status='pending'", (firm_id,))
        if pending:
            return None
        follow_on = 1 if self.store.query_one(
            "SELECT 1 FROM pitches WHERE firm_id=? AND status='funded'", (firm_id,)) else 0
        pid = self.store.insert(
            "pitches", tick=tick, firm_id=firm_id, founder_agent_id=founder_agent_id,
            ask_cents=ask_cents, summary=(summary or "")[:300], status="pending",
            follow_on=follow_on)
        self.store.log_event(tick, "pitch_made", {
            "pitch_id": pid, "firm_id": firm_id, "firm_name": firm["name"],
            "founder_agent_id": founder_agent_id, "ask_cents": ask_cents,
            "follow_on": bool(follow_on)}, phase="EXECUTION",
            subject_type="firm", subject_id=firm_id, importance=1.5)
        return pid

    # ── partner side ─────────────────────────────────────────────────────────
    def fund(self, tick: int, pitch_id: int, vc_agent_id: int, amount_cents: int,
             equity_bps: int) -> dict:
        pitch = self.store.query_one("SELECT * FROM pitches WHERE id=?", (pitch_id,))
        if not pitch or pitch["status"] != "pending":
            return {"ok": False, "reason": "pitch not pending"}
        firm = self.store.query_one("SELECT * FROM firms WHERE id=?", (pitch["firm_id"],))
        if not firm or firm["status"] != "private":
            return {"ok": False, "reason": "firm no longer private"}
        if amount_cents <= 0 or not (0 < equity_bps < 10000):
            return {"ok": False, "reason": "bad terms"}
        vc_acct = self.ledger.agent_checking_id(vc_agent_id)
        if vc_acct is None or self.ledger.balance(vc_acct) < amount_cents:
            return {"ok": False, "reason": "insufficient fund capital"}

        firm_id = int(firm["id"])
        # Post-money: VC ends up holding equity_bps of the enlarged cap table.
        outstanding = int(firm["shares_outstanding"])
        new_shares = max(1, round(outstanding * equity_bps / (10000 - equity_bps)))

        term_sheet = {"amount_cents": amount_cents, "equity_bps": equity_bps,
                      "shares_issued": new_shares, "pre_money_shares": outstanding}
        self.ledger.transfer(tick, vc_acct, int(firm["account_id"]), amount_cents,
                             kind="vc_investment", memo=f"VC round pitch {pitch_id}")
        self._adjust_holder(firm_id, vc_agent_id, new_shares)
        self.store.update("firms", firm_id, shares_outstanding=outstanding + new_shares)
        self.store.update("pitches", pitch_id, status="funded", decided_tick=tick,
                          vc_agent_id=vc_agent_id, invested_cents=amount_cents,
                          equity_bps=equity_bps, shares_issued=new_shares,
                          term_sheet_json=json.dumps(term_sheet))
        self.store.log_event(tick, "vc_funded", {
            "pitch_id": pitch_id, "firm_id": firm_id, "firm_name": firm["name"],
            "vc_agent_id": vc_agent_id, "amount_cents": amount_cents,
            "equity_bps": equity_bps, "shares_issued": new_shares,
            "follow_on": bool(pitch["follow_on"])}, phase="EXECUTION",
            subject_type="firm", subject_id=firm_id, importance=3.0)
        return {"ok": True, "pitch_id": pitch_id, "shares_issued": new_shares,
                "amount_cents": amount_cents}

    def decline(self, tick: int, pitch_id: int, vc_agent_id: int, reason: str = "") -> dict:
        pitch = self.store.query_one("SELECT status FROM pitches WHERE id=?", (pitch_id,))
        if not pitch or pitch["status"] != "pending":
            return {"ok": False, "reason": "pitch not pending"}
        self.store.update("pitches", pitch_id, status="declined", decided_tick=tick,
                          vc_agent_id=vc_agent_id)
        self.store.log_event(tick, "pitch_declined", {
            "pitch_id": pitch_id, "reason": (reason or "")[:120]}, phase="EXECUTION")
        return {"ok": True}

    def _adjust_holder(self, firm_id: int, agent_id: int, qty: int) -> None:
        row = self.store.query_one(
            "SELECT id, qty FROM shares WHERE firm_id=? AND holder_type='agent' AND holder_id=?",
            (firm_id, agent_id))
        if row:
            self.store.update("shares", int(row["id"]), qty=int(row["qty"]) + qty)
        else:
            self.store.insert("shares", firm_id=firm_id, holder_type="agent",
                              holder_id=agent_id, qty=qty)

    # ── nightly sweep: write-offs + stale pitches (NIGHT_CLOSE) ──────────────
    def run_nightly(self, tick: int) -> None:
        # Write off funded positions whose firm went bankrupt (equity already wiped
        # by the waterfall — this records the portfolio outcome).
        for p in self.store.query(
                "SELECT p.*, f.name AS firm_name FROM pitches p JOIN firms f ON f.id=p.firm_id "
                "WHERE p.status='funded' AND f.status='bankrupt'"):
            self.store.update("pitches", int(p["id"]), status="written_off")
            self.store.log_event(tick, "vc_writeoff", {
                "pitch_id": int(p["id"]), "firm_id": int(p["firm_id"]),
                "firm_name": p["firm_name"], "vc_agent_id": p["vc_agent_id"],
                "invested_cents": int(p["invested_cents"] or 0)}, phase="NIGHT_CLOSE",
                subject_type="firm", subject_id=int(p["firm_id"]), importance=2.5)
        # Expire stale pending pitches.
        self.store.execute(
            "UPDATE pitches SET status='expired' WHERE status='pending' AND tick < ?",
            (tick - PITCH_TTL_TICKS,))

    # ── portfolio view (context + dashboard) ─────────────────────────────────
    def portfolio(self, vc_agent_id: int) -> list[dict]:
        rows = self.store.query(
            "SELECT p.*, f.name AS firm_name, f.status AS firm_status FROM pitches p "
            "JOIN firms f ON f.id=p.firm_id WHERE p.vc_agent_id=? AND p.status IN "
            "('funded','written_off') ORDER BY p.id", (vc_agent_id,))
        return [{"pitch_id": int(r["id"]), "firm_id": int(r["firm_id"]),
                 "firm_name": r["firm_name"], "firm_status": r["firm_status"],
                 "invested_cents": int(r["invested_cents"] or 0),
                 "equity_bps": int(r["equity_bps"] or 0), "status": r["status"]}
                for r in rows]
