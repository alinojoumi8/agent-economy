"""Agent lifecycle: health, death, aging, births, arrivals (PRD R11) and the
health economy built on top of it (P1 R17).

Design rule: **biology is engine-side, reactions are LLM-side.** Illness, death,
and aging are drawn from a dedicated seeded PRNG so the lifecycle schedule replays
identically (acceptance: identical seed ⇒ identical lifecycle event schedule). The
LLM never decides who gets sick or dies; agents react through the normal loop.

Estate settlement runs as one atomic batch and conserves money exactly: debts
settle via the creditor waterfall, the remainder transfers to the heir (strongest
living social tie) or escheats to government.

Health economy (R17): when a hospital firm exists (sector 'health'), medical
spending becomes hospital revenue instead of vanishing into the sys:medical sink —
sickness feeds a real firm with payroll. Health insurance (an insurer firm, sector
'insurance') collects premiums and pays `coverage_bps` of each medical bill as a
claim; policies lapse when premiums go unpaid. An epidemic shock scales the
illness-onset hazard through the `epidemic_multiplier` metric — the PRNG draw
sequence is unchanged (one draw per agent per night), only the threshold moves,
so lifecycle schedules stay comparable across experiment arms.
"""
from __future__ import annotations

import random
from typing import Optional

from .credit import Bank
from .firms import Firms
from .ledger import Ledger, Leg, SYS_MEDICAL, SYS_GOV
from .store import Store

DEFAULT_HEALTH = {
    "premium_cents": 3000,          # per premium interval
    "coverage_bps": 8000,           # insurer pays 80% of medical bills
    "premium_interval_ticks": 30,
}

DEFAULT_PARAMS = {
    "illness_onset_annual_young": 0.04,   # 20–40
    "illness_onset_annual_old": 0.15,     # 65+
    "sick_recovery_per_tick": 0.20,       # mean duration ~5 ticks
    "sick_to_critical_per_tick": 0.05,
    "critical_death_per_tick": 0.10,
    "critical_recovery_per_tick": 0.25,
    "medical_cost_cents": 5000,           # per sick tick, out-of-pocket
    "retirement_age": 65,
    "birth_annual_prob": 0.05,            # age-appropriate households
    "birth_min_age": 22,
    "birth_max_age": 42,
    "arrival_delay_min": 5,
    "arrival_delay_max": 20,
    "population_mode": "stable",          # stable | drift
    "mortality_baseline_annual_50": 0.005,
    "mortality_doubling_years": 8.0,      # Gompertz-ish doubling
}


class Lifecycle:
    def __init__(self, store: Store, ledger: Ledger, bank: Bank, firms: Firms,
                 prng: random.Random, params: Optional[dict] = None,
                 health_cfg: Optional[dict] = None):
        self.store = store
        self.ledger = ledger
        self.bank = bank
        self.firms = firms
        self.prng = prng  # dedicated lifecycle PRNG
        self.p = {**DEFAULT_PARAMS, **(params or {})}
        self.h = {**DEFAULT_HEALTH, **(health_cfg or {})}

    # ── nightly driver ───────────────────────────────────────────────────────
    def run_nightly(self, tick: int) -> None:
        self._collect_premiums(tick)
        agents = self.store.query(
            "SELECT id, age, health, alive, retired, dependents, sick_since_tick, arrived_tick "
            "FROM agents WHERE alive=1 ORDER BY id")
        for a in agents:
            self._age_and_retire(tick, a)
            self._health_transition(tick, a)
            self._maybe_birth(tick, a)

    # ── aging / retirement ───────────────────────────────────────────────────
    def _age_and_retire(self, tick: int, a) -> None:
        agent_id = int(a["id"])
        # Birthday offset is deterministic from id so aging replays identically.
        offset = agent_id % 365
        if tick > 0 and tick % 365 == offset:
            new_age = int(a["age"]) + 1
            self.store.update("agents", agent_id, age=new_age)
            self.store.log_event(tick, "birthday", {"agent_id": agent_id, "age": new_age},
                                 phase="NIGHT_CLOSE", subject_type="agent", subject_id=agent_id,
                                 importance=0.5)
            if new_age >= self.p["retirement_age"] and not a["retired"]:
                self._retire(tick, agent_id)

    def _retire(self, tick: int, agent_id: int) -> None:
        self.store.update("agents", agent_id, retired=1)
        self.store.execute(
            "UPDATE employments SET status='ended', end_tick=? WHERE agent_id=? AND status='active'",
            (tick, agent_id))
        self.store.execute("UPDATE agents SET employer_id=NULL WHERE id=?", (agent_id,))
        self.store.log_event(tick, "retirement", {"agent_id": agent_id}, phase="NIGHT_CLOSE",
                             subject_type="agent", subject_id=agent_id, importance=1.5)

    # ── health ───────────────────────────────────────────────────────────────
    def _illness_onset_annual(self, age: int) -> float:
        young, old = self.p["illness_onset_annual_young"], self.p["illness_onset_annual_old"]
        if age <= 40:
            return young
        if age >= 65:
            return old
        return young + (old - young) * (age - 40) / 25.0

    def _mortality_annual(self, age: int) -> float:
        if age < 50:
            return max(0.0002, 0.0002 * (age / 50.0))
        base = self.p["mortality_baseline_annual_50"]
        return base * (2 ** ((age - 50) / self.p["mortality_doubling_years"]))

    def _health_transition(self, tick: int, a) -> None:
        agent_id = int(a["id"])
        age = int(a["age"])
        health = a["health"]

        # Baseline mortality (all living agents).
        if self.prng.random() < self._mortality_annual(age) / 365.0:
            self.settle_death(tick, agent_id, cause="natural")
            return

        if health == "healthy":
            # Epidemic shocks scale the onset hazard (threshold only — the draw
            # sequence is untouched, so schedules stay comparable across arms).
            epidemic = self.store.metric_latest("epidemic_multiplier", 1.0) or 1.0
            hazard = min(0.9, self._illness_onset_annual(age) / 365.0 * epidemic)
            if self.prng.random() < hazard:
                self.store.update("agents", agent_id, health="sick", sick_since_tick=tick)
                self.store.log_event(tick, "illness_onset", {"agent_id": agent_id},
                                     phase="NIGHT_CLOSE", subject_type="agent",
                                     subject_id=agent_id, importance=1.5)
                self._charge_medical(tick, agent_id)
        elif health == "sick":
            self._charge_medical(tick, agent_id)
            roll = self.prng.random()
            if roll < self.p["sick_to_critical_per_tick"]:
                self.store.update("agents", agent_id, health="critical")
                self.store.log_event(tick, "illness_critical", {"agent_id": agent_id},
                                     phase="NIGHT_CLOSE", subject_type="agent",
                                     subject_id=agent_id, importance=2.5)
            elif roll < self.p["sick_to_critical_per_tick"] + self.p["sick_recovery_per_tick"]:
                self.store.update("agents", agent_id, health="healthy", sick_since_tick=None)
                self.store.log_event(tick, "recovery", {"agent_id": agent_id},
                                     phase="NIGHT_CLOSE", subject_type="agent", subject_id=agent_id)
        elif health == "critical":
            self._charge_medical(tick, agent_id, multiplier=3)
            roll = self.prng.random()
            if roll < self.p["critical_death_per_tick"]:
                self.settle_death(tick, agent_id, cause="illness")
            elif roll < self.p["critical_death_per_tick"] + self.p["critical_recovery_per_tick"]:
                self.store.update("agents", agent_id, health="healthy", sick_since_tick=None)
                self.store.log_event(tick, "recovery", {"agent_id": agent_id},
                                     phase="NIGHT_CLOSE", subject_type="agent", subject_id=agent_id)

    def _charge_medical(self, tick: int, agent_id: int, multiplier: int = 1) -> None:
        cost = int(self.p["medical_cost_cents"]) * multiplier
        acct = self.ledger.agent_checking_id(agent_id)
        if acct is None or cost <= 0:
            return
        currency = str(self.store.scalar(
            "SELECT currency_code FROM accounts WHERE id=?", (acct,), default="USD") or "USD")
        # Provider: an open hospital firm earns the fee (R17); else the sink.
        provider = self._hospital_account(currency) or self.ledger.system_account(
            SYS_MEDICAL, currency_code=currency)
        # Insurance covers coverage_bps of the bill, limited by insurer cash.
        covered = 0
        policy = self._active_policy(agent_id)
        if policy:
            insurer = self.store.query_one(
                "SELECT account_id FROM firms WHERE id=? AND status<>'bankrupt' AND currency_code=?",
                (policy["insurer_firm_id"], currency))
            if insurer and insurer["account_id"]:
                want = cost * int(policy["coverage_bps"]) // 10000
                covered = min(want, max(0, self.ledger.balance(int(insurer["account_id"]))))
                if covered > 0:
                    self.ledger.transfer(tick, int(insurer["account_id"]), provider, covered,
                                         kind="insurance_claim",
                                         memo=f"claim agent {agent_id}")
                    self.store.log_event(tick, "insurance_claim", {
                        "agent_id": agent_id, "policy_id": int(policy["id"]),
                        "covered_cents": covered, "bill_cents": cost}, phase="NIGHT_CLOSE",
                        subject_type="agent", subject_id=agent_id, importance=0.6)
        pay = min(cost - covered, self.ledger.balance(acct))
        if pay <= 0:
            return
        self.ledger.transfer(tick, acct, provider, pay, kind="medical_cost",
                             memo=f"medical out-of-pocket agent {agent_id}")

    # ── health economy plumbing (R17) ────────────────────────────────────────
    def _hospital_account(self, currency: str = "USD") -> Optional[int]:
        v = self.store.scalar(
            "SELECT account_id FROM firms WHERE sector='health' AND status<>'bankrupt' "
            "AND currency_code=? ORDER BY id LIMIT 1", (currency,))
        return int(v) if v is not None else None

    def _active_policy(self, agent_id: int):
        return self.store.query_one(
            "SELECT * FROM insurance_policies WHERE agent_id=? AND status='active' LIMIT 1",
            (agent_id,))

    def _collect_premiums(self, tick: int) -> None:
        due = self.store.query(
            "SELECT * FROM insurance_policies WHERE status='active' AND next_premium_tick <= ?",
            (tick,))
        for pol in due:
            pol_id = int(pol["id"])
            agent = self.store.query_one("SELECT alive FROM agents WHERE id=?", (pol["agent_id"],))
            insurer = self.store.query_one(
                "SELECT account_id, status, currency_code FROM firms WHERE id=?", (pol["insurer_firm_id"],))
            if not agent or not agent["alive"] or not insurer or insurer["status"] == "bankrupt":
                self.store.update("insurance_policies", pol_id, status="cancelled", end_tick=tick)
                continue
            acct = self.ledger.agent_checking_id(int(pol["agent_id"]))
            premium = int(pol["premium_cents"])
            acct_currency = self.store.scalar(
                "SELECT currency_code FROM accounts WHERE id=?", (acct,), default=None) if acct else None
            if (acct is not None and str(acct_currency or "USD") == str(insurer["currency_code"] or "USD")
                    and self.ledger.balance(acct) >= premium):
                self.ledger.transfer(tick, acct, int(insurer["account_id"]), premium,
                                     kind="insurance_premium", memo=f"premium policy {pol_id}")
                self.store.update("insurance_policies", pol_id,
                                  next_premium_tick=tick + int(pol["premium_interval_ticks"]))
            else:
                self.store.update("insurance_policies", pol_id, status="lapsed", end_tick=tick)
                self.store.log_event(tick, "policy_lapsed", {
                    "agent_id": int(pol["agent_id"]), "policy_id": pol_id},
                    phase="NIGHT_CLOSE", subject_type="agent",
                    subject_id=int(pol["agent_id"]), importance=1.0)

    # ── births (household events) ────────────────────────────────────────────
    def _maybe_birth(self, tick: int, a) -> None:
        age = int(a["age"])
        if not (self.p["birth_min_age"] <= age <= self.p["birth_max_age"]):
            return
        if self.prng.random() < self.p["birth_annual_prob"] / 365.0:
            new_dep = int(a["dependents"]) + 1
            self.store.update("agents", int(a["id"]), dependents=new_dep)
            self.store.log_event(tick, "birth", {"agent_id": int(a["id"]), "dependents": new_dep},
                                 phase="NIGHT_CLOSE", subject_type="agent", subject_id=int(a["id"]),
                                 importance=1.5)

    # ── death + estate settlement ────────────────────────────────────────────
    def settle_death(self, tick: int, agent_id: int, cause: str = "natural") -> None:
        agent = self.store.query_one("SELECT * FROM agents WHERE id=?", (agent_id,))
        if not agent or not agent["alive"]:
            return

        # 1) Settle debts via the creditor waterfall (dead agent's cash first).
        loans = self.store.query(
            "SELECT * FROM loans WHERE borrower_type='agent' AND borrower_id=? AND status='active'",
            (agent_id,))
        for loan in loans:
            acct = self.ledger.agent_checking_id(agent_id)
            cash = self.ledger.balance(acct) if acct else 0
            pay = min(cash, int(loan["outstanding_cents"]))
            bankrow = self.store.query_one("SELECT reserve_account_id FROM banks WHERE id=?",
                                           (loan["bank_id"],))
            if pay > 0 and bankrow:
                self.ledger.transfer(tick, acct, int(bankrow["reserve_account_id"]), pay,
                                     kind="estate_debt", memo=f"estate debt loan {loan['id']}")
            self.store.update("loans", int(loan["id"]),
                              outstanding_cents=max(0, int(loan["outstanding_cents"]) - pay),
                              status="paid" if pay >= int(loan["outstanding_cents"]) else "default")

        heir_id = self._find_heir(agent_id)

        # 2) Transfer remaining cash to heir (or escheat to government).
        for acct in self.store.query(
                "SELECT id, balance_cents, bank_id, currency_code FROM accounts "
                "WHERE owner_type='agent' AND owner_id=? AND balance_cents>0", (agent_id,)):
            bal = int(acct["balance_cents"])
            if heir_id:
                heir = self.store.query_one(
                    "SELECT id FROM accounts WHERE owner_type='agent' AND owner_id=? "
                    "AND currency_code=? ORDER BY CASE kind WHEN 'checking' THEN 0 ELSE 1 END,id LIMIT 1",
                    (heir_id, acct["currency_code"]))
                heir_acct = int(heir["id"]) if heir else self.ledger.create_account(
                    "agent", heir_id, "fx", label=f"inheritance:{heir_id}:{acct['currency_code']}",
                    currency_code=str(acct["currency_code"] or "USD"))
                if heir_acct:
                    self.ledger.transfer(tick, int(acct["id"]), heir_acct, bal,
                                         kind="inheritance", memo=f"estate to heir {heir_id}")
                    continue
            gov = self.ledger.system_account(
                SYS_GOV, currency_code=str(acct["currency_code"] or "USD"))
            self.ledger.transfer(tick, int(acct["id"]), gov, bal, kind="escheat",
                                 memo="escheat to government")

        # 3) Transfer share holdings to heir (or wind down sole-proprietor firms).
        self._transfer_shares_on_death(tick, agent_id, heir_id)

        # 4) Terminate employment; clear roles.
        self.store.execute(
            "UPDATE employments SET status='ended', end_tick=? WHERE agent_id=? AND status='active'",
            (tick, agent_id))

        # 5) Mark dead + schedule replacement arrival (stable population).
        self.store.update("agents", agent_id, alive=0, died_tick=tick, health="healthy",
                          employer_id=None)
        self.store.log_event(tick, "death", {
            "agent_id": agent_id, "name": agent["name"], "cause": cause,
            "occupation": agent["occupation"], "heir_id": heir_id}, phase="NIGHT_CLOSE",
            subject_type="agent", subject_id=agent_id, importance=4.0)
        if self.p["population_mode"] == "stable":
            delay = self.prng.randint(self.p["arrival_delay_min"], self.p["arrival_delay_max"])
            self.schedule_arrival(tick, tick + delay)

    def _find_heir(self, agent_id: int) -> Optional[int]:
        rows = self.store.query(
            "SELECT CASE WHEN t.agent_a=? THEN t.agent_b ELSE t.agent_a END AS other, t.weight "
            "FROM social_ties t WHERE (t.agent_a=? OR t.agent_b=?) ORDER BY t.weight DESC",
            (agent_id, agent_id, agent_id))
        for r in rows:
            other = int(r["other"])
            alive = self.store.scalar("SELECT alive FROM agents WHERE id=?", (other,))
            if alive:
                return other
        return None

    def _transfer_shares_on_death(self, tick: int, agent_id: int, heir_id: Optional[int]) -> None:
        holdings = self.store.query(
            "SELECT * FROM shares WHERE holder_type='agent' AND holder_id=?", (agent_id,))
        for h in holdings:
            firm_id = int(h["firm_id"])
            qty = int(h["qty"])
            if heir_id:
                self.store.execute("DELETE FROM shares WHERE id=?", (h["id"],))
                existing = self.store.query_one(
                    "SELECT id, qty FROM shares WHERE firm_id=? AND holder_type='agent' AND holder_id=?",
                    (firm_id, heir_id))
                if existing:
                    self.store.update("shares", int(existing["id"]), qty=int(existing["qty"]) + qty)
                else:
                    self.store.insert("shares", firm_id=firm_id, holder_type="agent",
                                      holder_id=heir_id, qty=qty)
            else:
                self.store.execute("DELETE FROM shares WHERE id=?", (h["id"],))
                # Sole-proprietor firm with no successor winds down.
                firm = self.store.query_one("SELECT * FROM firms WHERE id=?", (firm_id,))
                if firm and firm["founder_agent_id"] == agent_id and firm["status"] != "bankrupt":
                    self.firms.bankrupt_firm(tick, firm_id, reason="founder_death_no_heir")

    # ── arrivals (scheduling only; world layer spawns via persona library) ────
    def schedule_arrival(self, tick: int, due_tick: int) -> int:
        return self.store.log_event(tick, "arrival_scheduled", {"due_tick": due_tick},
                                    phase="NIGHT_CLOSE", importance=0.5)

    def pending_arrivals(self, tick: int) -> list[int]:
        """Scheduled arrivals now due and not yet spawned."""
        rows = self.store.query(
            "SELECT e.id AS id, e.payload_json AS payload FROM events e "
            "WHERE e.kind='arrival_scheduled' "
            "AND e.id NOT IN (SELECT CAST(json_extract(payload_json,'$.schedule_event_id') AS INTEGER) "
            "                 FROM events WHERE kind='arrival') "
            "ORDER BY e.id")
        due = []
        import json as _json
        for r in rows:
            payload = _json.loads(r["payload"]) if r["payload"] else {}
            if int(payload.get("due_tick", 0)) <= tick:
                due.append(int(r["id"]))
        return due
