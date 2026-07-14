"""Government fiscal layer + elections (PRD R12).

Flat income tax withheld at payroll funds unemployment benefits paid from the
government treasury (`sys:gov` — a real external-flagged account, so a negative
balance IS the deficit and every flow is conserved). Periodic elections shift
fiscal policy within guardrails.

Design rule (mirrors R11): **ballot aggregation is engine-side, what shapes the
vote is LLM-side.** Each agent's ballot is a deterministic function of its
political lean and its lived economy — unemployment, benefit receipt, and its
`sentiment` belief (which the LLM writes during real runs). No PRNG is drawn, so
elections replay exactly and never desync the engine PRNG stream.

Fiscal policy state lives in `metrics` (`tax_rate_bps`, `unemployment_benefit_cents`)
exactly like `policy_rate`: checkpoint/resume-safe, dashboard-chartable, and
targetable by conditional shocks.
"""
from __future__ import annotations

from .ledger import Ledger, Leg, SYS_GOV
from .store import Store

DEFAULT_PARAMS = {
    "tax_rate_bps": 1500,                 # 15% flat tax on wages
    "unemployment_benefit_cents": 120_000,  # per benefit cycle
    "benefit_interval_ticks": 30,
    "election_interval_ticks": 180,
    "tax_step_bps": 300,                  # max fiscal shift per election
    "benefit_step_cents": 40_000,
    "min_tax_bps": 500,
    "max_tax_bps": 3000,
    "min_benefit_cents": 0,
    "max_benefit_cents": 400_000,
    "vote_threshold": 0.25,               # net grievance needed to vote "expand"
}


class Government:
    def __init__(self, store: Store, ledger: Ledger, params: dict | None = None):
        self.store = store
        self.ledger = ledger
        self.enabled = params is not None and params.get("enabled", True)
        self.p = {**DEFAULT_PARAMS, **(params or {})}

    # ── fiscal state (metrics-backed, like policy_rate) ──────────────────────
    def tax_rate_bps(self) -> int:
        return int(self.store.metric_latest("tax_rate_bps", 0.0))

    def benefit_cents(self) -> int:
        return int(self.store.metric_latest("unemployment_benefit_cents", 0.0))

    def treasury_balance(self) -> int:
        return int(self.store.scalar(
            "SELECT COALESCE(SUM(balance_cents),0) FROM accounts WHERE label=?", (SYS_GOV,), default=0))

    def initialize(self, tick: int = 0) -> None:
        """Record opening fiscal policy (genesis). Without this, tax stays 0."""
        if not self.enabled:
            return
        self.store.record_metric(tick, "tax_rate_bps", int(self.p["tax_rate_bps"]))
        self.store.record_metric(tick, "unemployment_benefit_cents",
                                 int(self.p["unemployment_benefit_cents"]))

    # ── nightly driver (NIGHT_CLOSE) ─────────────────────────────────────────
    def run_nightly(self, tick: int) -> None:
        if not self.enabled:
            return
        interval = max(1, int(self.p["benefit_interval_ticks"]))
        if tick % interval == 0:
            self._pay_benefits(tick)
        election_every = int(self.p["election_interval_ticks"])
        if election_every > 0 and tick > 0 and tick % election_every == 0:
            self.hold_election(tick)

    # ── unemployment benefits ────────────────────────────────────────────────
    def _eligible_unemployed(self) -> list[int]:
        rows = self.store.query(
            "SELECT a.id FROM agents a WHERE a.alive=1 AND a.kind='citizen' AND a.retired=0 "
            "AND a.age BETWEEN 18 AND 64 "
            "AND NOT EXISTS (SELECT 1 FROM employments e WHERE e.agent_id=a.id AND e.status='active') "
            "AND NOT EXISTS (SELECT 1 FROM firms f WHERE f.founder_agent_id=a.id AND f.status<>'bankrupt') "
            "ORDER BY a.id")
        return [int(r["id"]) for r in rows]

    def _pay_benefits(self, tick: int) -> None:
        amount = self.benefit_cents()
        if amount <= 0:
            return
        paid = 0
        total = 0
        for agent_id in self._eligible_unemployed():
            acct = self.ledger.agent_checking_id(agent_id)
            if acct is None:
                continue
            currency = str(self.store.scalar(
                "SELECT currency_code FROM accounts WHERE id=?", (acct,), default="USD") or "USD")
            gov = self.ledger.system_account(SYS_GOV, currency_code=currency)
            # Deficit spending is allowed: sys:gov is external and may go negative.
            self.ledger.post(tick, "unemployment_benefit", [
                Leg(acct, amount, "unemployment benefit"),
                Leg(gov, -amount, "benefit outlay")])
            self.store.log_event(tick, "benefit_paid", {
                "agent_id": agent_id, "amount_cents": amount}, phase="NIGHT_CLOSE",
                subject_type="agent", subject_id=agent_id, importance=0.8)
            paid += 1
            total += amount
        if paid:
            self.store.log_event(tick, "benefits_paid", {
                "recipients": paid, "total_cents": total,
                "treasury_cents": self.treasury_balance()}, phase="NIGHT_CLOSE",
                importance=1.5)

    # ── elections ────────────────────────────────────────────────────────────
    def hold_election(self, tick: int) -> dict:
        """Two-platform election: EXPAND (raise tax + benefits) vs AUSTERITY
        (cut both). Ballots derive from beliefs + economic experience; the
        outcome shifts fiscal policy one bounded step."""
        voters = self.store.query(
            "SELECT id, political_lean, retired, age FROM agents "
            "WHERE alive=1 AND age>=18 ORDER BY id")
        sentiments = {int(r["agent_id"]): float(r["value"]) for r in self.store.query(
            "SELECT agent_id, value FROM beliefs WHERE key='sentiment'")}
        employed = {int(r["agent_id"]) for r in self.store.query(
            "SELECT DISTINCT agent_id FROM employments WHERE status='active'")}
        founders = {int(r["founder_agent_id"]) for r in self.store.query(
            "SELECT founder_agent_id FROM firms WHERE status<>'bankrupt' "
            "AND founder_agent_id IS NOT NULL")}
        window = 2 * int(self.p["benefit_interval_ticks"])
        recent_benefit = {int(r["subject_id"]) for r in self.store.query(
            "SELECT DISTINCT subject_id FROM events WHERE kind='benefit_paid' AND tick>?",
            (tick - window,)) if r["subject_id"] is not None}

        expand = austerity = 0
        threshold = float(self.p["vote_threshold"])
        for v in voters:
            aid = int(v["id"])
            grievance = 0.0
            working_age = int(v["age"]) <= 64 and not v["retired"]
            if working_age and aid not in employed and aid not in founders:
                grievance += 0.5
            grievance += max(0.0, -sentiments.get(aid, 0.0)) * 0.5
            if aid in recent_benefit:
                grievance += 0.25
            lean = float(v["political_lean"] or 0.0)   # -1 left .. +1 right
            if grievance - 0.5 * lean > threshold:
                expand += 1
            else:
                austerity += 1

        tax, benefit = self.tax_rate_bps(), self.benefit_cents()
        if expand > austerity:
            new_tax = tax + int(self.p["tax_step_bps"])
            new_benefit = benefit + int(self.p["benefit_step_cents"])
            direction = "expand"
        else:
            new_tax = tax - int(self.p["tax_step_bps"])
            new_benefit = benefit - int(self.p["benefit_step_cents"])
            direction = "austerity"
        new_tax = max(int(self.p["min_tax_bps"]), min(int(self.p["max_tax_bps"]), new_tax))
        new_benefit = max(int(self.p["min_benefit_cents"]),
                          min(int(self.p["max_benefit_cents"]), new_benefit))
        self.store.record_metric(tick, "tax_rate_bps", new_tax)
        self.store.record_metric(tick, "unemployment_benefit_cents", new_benefit)

        result = {"tick": tick, "expand_votes": expand, "austerity_votes": austerity,
                  "turnout": len(voters), "direction": direction,
                  "old_tax_bps": tax, "new_tax_bps": new_tax,
                  "old_benefit_cents": benefit, "new_benefit_cents": new_benefit,
                  "treasury_cents": self.treasury_balance()}
        self.store.log_event(tick, "election_held", result, phase="NIGHT_CLOSE",
                             subject_type="gov", importance=4.0)
        return result
