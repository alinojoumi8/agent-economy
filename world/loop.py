"""The world loop: ticks and phases in fixed order (TECH-SPEC §3).

Phase order per tick T (determinism requires ordered execution):
  1 NIGHT_CLOSE   interest, loan payments, payroll, production, lifecycle draws,
                  shock evaluation, metrics snapshot, reconciliation check
  2 MORNING       scheduled agents perceive + decide (LLM, concurrent)
  3 EXECUTION     validator + engine apply queued actions (deterministic order)
  4 MARKET        order book matches; session closes
  5 NEWSROOM      outlets write stories from the day's true events
  6 EVENING       conversation pairs
  7 MEMORY        nightly compression, belief extraction

A failed reconciliation halts the run with a diagnostic dump (PRD R1). The budget
governor is consulted every tick; at 100% the run pauses cleanly (PRD R7).
"""
from __future__ import annotations

import asyncio
import json
import random
import shutil
import time
import uuid
from pathlib import Path
from typing import Callable, Optional

from engine.core import Economy
from engine.ledger import ReconciliationError, SYS_INFLOW
from engine.store import Store, load_json
from llm.gateway import Gateway, BudgetExceeded
from agents.runtime import AgentRuntime
from agents.personas.vendor.persona_gen import sample_persona
from .genesis import Genesis
from .metrics import Metrics
from .newsroom import Newsroom, Conversations
from .shocks import Shocks
from oracle.analyst import Oracle

PHASES = ("NIGHT_CLOSE", "MORNING", "EXECUTION", "MARKET", "NEWSROOM", "EVENING", "MEMORY")


class World:
    def __init__(self, store: Store, config: dict, *, replay: bool = False):
        self.store = store
        self.config = config
        seed = int(config.get("seed", 42))
        self.engine_prng = random.Random(seed)
        self.lifecycle_prng = random.Random(seed ^ 0x5F5E5F)
        self.persona_prng = random.Random(seed ^ 0xA11CE)

        cfg = dict(config)
        cfg["replay"] = replay
        self.economy = Economy(store, config, self.engine_prng, self.lifecycle_prng)
        self.gateway = Gateway(store, cfg)
        self.runtime = AgentRuntime(self.economy, self.gateway, config)
        self.metrics = Metrics(self.economy)
        self.shocks = Shocks(self.economy, config)
        self.newsroom = Newsroom(self.economy, self.gateway, config, self.shocks)
        self.conversations = Conversations(self.economy, self.gateway, config)
        self.oracle = Oracle(self.economy, self.gateway, config)

        self.status = "created"      # created|running|paused|halted|finished
        self.speed_delay_s = float(config.get("speed_delay_s", 0.0))
        self.checkpoint_every = int(config.get("checkpoint_every", 10))
        self._pause_requested = False
        self._stop_requested = False
        self.on_tick: Optional[Callable[[int, dict], None]] = None  # dashboard hook
        self.on_event: Optional[Callable[[dict], None]] = None

    # ── lifecycle of a run ───────────────────────────────────────────────────
    def initialize(self) -> None:
        """Genesis for a fresh run (no-op if already initialised)."""
        if self.store.scalar("SELECT COUNT(*) FROM agents", default=0):
            return
        Genesis(self.economy, self.config, self.persona_prng).build()
        self.shocks.load_from_config()
        ok, diag = self.economy.ledger.reconcile()
        if not ok:
            raise ReconciliationError(f"genesis does not reconcile: {diag}")
        self.metrics.snapshot(0)
        self.store.set_meta(status="paused", tick=0)
        self.store.commit()

    async def run(self, max_ticks: Optional[int] = None) -> None:
        self.status = "running"
        self.store.set_meta(status="running")
        start_tick = self.store.tick
        end_tick = (start_tick + max_ticks) if max_ticks else None
        try:
            while not self._stop_requested:
                if end_tick is not None and self.store.tick >= end_tick:
                    break
                if self._pause_requested:
                    break
                await self.step()
                if self.speed_delay_s > 0:
                    await asyncio.sleep(self.speed_delay_s)
        finally:
            new_status = "halted" if self.status == "halted" else "paused"
            if self._stop_requested:
                new_status = "finished"
            self.status = new_status
            self.store.set_meta(status=new_status)
            self._save_prng_state()
            self.checkpoint(self.store.tick, reason="pause")
            self.store.commit()
            self._pause_requested = False

    def request_pause(self) -> None:
        self._pause_requested = True

    def request_stop(self) -> None:
        self._stop_requested = True

    # ── one tick ─────────────────────────────────────────────────────────────
    async def step(self) -> dict:
        tick = self.store.tick + 1
        t0 = time.time()

        # 1 NIGHT_CLOSE (accrual, lifecycle, shocks, metrics, reconciliation)
        self._phase_night_close(tick)

        # Budget check — a clean pause, never a dead run.
        if self.gateway.governor.should_pause():
            self.store.log_event(tick, "budget_pause", self.gateway.governor.status(),
                                 phase="NIGHT_CLOSE", importance=4.0)
            self._pause_requested = True
            self.store.set_meta(tick=tick)
            self.store.commit()
            return {"tick": tick, "paused": "budget"}

        # 2 MORNING + 3 EXECUTION
        try:
            decisions = await self.runtime.decide_all(tick)
        except BudgetExceeded:
            self._pause_requested = True
            self.store.log_event(tick, "budget_pause", self.gateway.governor.status(),
                                 phase="MORNING", importance=4.0)
            self.store.set_meta(tick=tick)
            self.store.commit()
            return {"tick": tick, "paused": "budget"}
        self.runtime.execute_decisions(tick, decisions)

        # 4 MARKET
        self._phase_market(tick)

        # 5 NEWSROOM
        await self.newsroom.publish(tick)

        # 6 EVENING
        await self.conversations.evening(tick)

        # 7 MEMORY
        self.runtime.capture_event_observations(tick)
        await self.runtime.compress_memories(tick)

        # bookkeeping
        self.store.set_meta(tick=tick, phase="MEMORY")
        if self.checkpoint_every and tick % self.checkpoint_every == 0:
            self.checkpoint(tick)
        self.store.commit()

        summary = {"tick": tick, "wall_s": round(time.time() - t0, 3),
                   "decisions": len(decisions), "governor": self.gateway.governor.status()}
        if self.on_tick:
            try:
                self.on_tick(tick, summary)
            except Exception:
                pass
        return summary

    # ── phases ───────────────────────────────────────────────────────────────
    def _phase_night_close(self, tick: int) -> None:
        e = self.economy
        # Interest on savings (annual rate ≈ policy - 200bps, floored at 0).
        self._accrue_savings_interest(tick)
        # Loan payments + defaults.
        e.bank.process_due_loans(tick)
        # Payroll.
        e.firms.process_payroll(tick)
        # Production.
        e.firms.produce(tick)
        # Lifecycle draws (illness, deaths + estates, aging, retirement, births).
        e.lifecycle.run_nightly(tick)
        # Government: unemployment benefits + periodic elections (P1 R12).
        e.gov.run_nightly(tick)
        # VC portfolio sweep: write-offs + stale pitches (P1 R13).
        e.vc.run_nightly(tick)
        # Arrivals due today (stable population).
        self._spawn_due_arrivals(tick)
        # Bank liquidity check: any open bank below required reserves seeks support.
        self._bank_liquidity_sweep(tick)
        # Shock evaluation.
        self.shocks.evaluate(tick)
        # Metrics snapshot.
        self.metrics.snapshot(tick)
        # Oracle predictions: auto-resolve anything now determinable (PRD R6).
        self.oracle.resolve_open(tick)
        # Reconciliation — the invariant that keeps the whole thing honest.
        ok, diag = e.ledger.reconcile()
        if not ok:
            self.status = "halted"
            self.store.log_event(tick, "reconciliation_failure", diag,
                                 phase="NIGHT_CLOSE", importance=5.0)
            self.store.set_meta(status="halted", tick=tick)
            dump_path = Path(self.store.path).with_suffix(f".halt_t{tick}.json")
            dump_path.write_text(json.dumps(diag, indent=2))
            self.checkpoint(tick, reason="halt")
            self.store.commit()
            raise ReconciliationError(f"tick {tick}: books do not reconcile → {dump_path}")

    def _accrue_savings_interest(self, tick: int) -> None:
        rate_bps = max(0, self.economy.policy_rate_bps() - 200)
        if rate_bps <= 0:
            return
        daily = rate_bps / 10000.0 / 365.0
        rows = self.store.query(
            "SELECT a.id, a.balance_cents, a.bank_id FROM accounts a JOIN banks b ON b.id=a.bank_id "
            "WHERE a.kind='savings' AND a.balance_cents>0 AND b.status='open'")
        from engine.ledger import Leg
        for r in rows:
            interest = int(int(r["balance_cents"]) * daily)
            if interest <= 0:
                continue
            bank = self.economy.bank.get(int(r["bank_id"]))
            eq = int(bank["equity_account_id"])
            # Bank pays interest out of its equity (if equity lacks funds it still
            # posts — equity may go negative, which is meaningful: a weak bank).
            self.economy.ledger.post(tick, "savings_interest", [
                Leg(int(r["id"]), interest, "interest"), Leg(eq, -interest, "interest expense")])

    def _bank_liquidity_sweep(self, tick: int) -> None:
        cb = self.economy.central_bank_reserve_acct()
        for b in self.store.query("SELECT * FROM banks WHERE status='open'"):
            bid = int(b["id"])
            required = int(self.economy.bank.deposits(bid) *
                           int(b["reserve_requirement_bps"]) / 10000)
            shortfall = required - self.economy.bank.reserves(bid)
            if shortfall > 0:
                supported = False
                if cb is not None:
                    supported = self.economy.bank.attempt_liquidity_support(tick, bid, shortfall, cb)
                if not supported:
                    self.economy.bank.fail_bank(tick, bid)

    def _phase_market(self, tick: int) -> None:
        for f in self.store.query("SELECT id FROM firms WHERE status='listed'"):
            self.economy.exchange.match_firm(tick, int(f["id"]))
        self.economy.exchange.expire_session(tick)
        self.economy.labor.expire_stale_jobs(tick)
        # Expire stale pending loan applications (older than a week).
        self.store.execute(
            "UPDATE loan_applications SET status='expired' WHERE status='pending' AND tick < ?",
            (tick - 7,))

    # ── arrivals (R11: minted from population_inflow, visible + conserved) ────
    def _spawn_due_arrivals(self, tick: int) -> None:
        due_ids = self.economy.lifecycle.pending_arrivals(tick)
        if not due_ids:
            return
        banks = [int(r["id"]) for r in self.store.query("SELECT id FROM banks WHERE status='open'")]
        if not banks:
            return
        outlets = self.config.get("outlets", [{"id": 1}, {"id": 2}])
        for sched_id in due_ids:
            p = sample_persona(self.persona_prng, n_outlets=len(outlets))
            bank_id = self.engine_prng.choice(banks)
            agent_id = self.store.insert(
                "agents", name=p.name, kind="citizen", occupation=p.occupation,
                age=max(20, min(55, p.age)), health="healthy", dependents=p.dependents,
                personality_json=json.dumps(p.personality), political_lean=p.political_lean,
                media_diet_json=json.dumps(p.media_diet), risk_tolerance=p.risk_tolerance,
                cadence_json=json.dumps({"act": 2, "portfolio": 7, "career": 30}),
                model_tier="citizen", alive=1, retired=0, arrived_tick=tick)
            chk = self.economy.ledger.create_account(
                "agent", agent_id, "checking", bank_id=bank_id,
                label=f"agent:{agent_id}:checking", opening_cents=int(p.wealth_cents * 0.6),
                funding_label=SYS_INFLOW, tick=tick)
            self.store.update("agents", agent_id, checking_account_id=chk)
            # Social ties to a few residents + starting beliefs.
            residents = [int(r["id"]) for r in self.store.query(
                "SELECT id FROM agents WHERE alive=1 AND id<>? ORDER BY id", (agent_id,))]
            for other in self.engine_prng.sample(residents, min(3, len(residents))):
                lo, hi = min(agent_id, other), max(agent_id, other)
                self.store.insert("social_ties", agent_a=lo, agent_b=hi,
                                  weight=round(self.engine_prng.uniform(0.2, 0.7), 3))
            for bid in banks:
                self.store.insert("beliefs", agent_id=agent_id, key=f"trust:bank:{bid}",
                                  value=0.6, updated_tick=tick)
            self.runtime.mem.observe(agent_id, tick,
                                     "I just moved to town. I need to find work and settle in.",
                                     importance=3.0, entities=["self", "arrival"])
            self.store.log_event(tick, "arrival", {
                "agent_id": agent_id, "name": p.name, "occupation": p.occupation,
                "schedule_event_id": sched_id}, phase="NIGHT_CLOSE",
                subject_type="agent", subject_id=agent_id, importance=2.0)

    # ── checkpoints (SQLite backup + PRNG state, TECH-SPEC §13) ──────────────
    def checkpoint(self, tick: int, reason: str = "interval") -> Optional[str]:
        try:
            self._save_prng_state()
            ckpt_dir = Path(self.config.get("checkpoint_dir", "data/checkpoints"))
            ckpt_dir.mkdir(parents=True, exist_ok=True)
            run_id = self.store.get_meta()["run_id"]
            dest = ckpt_dir / f"{run_id}_t{tick}.db"
            src = __import__("sqlite3").connect(self.store.path)
            dst = __import__("sqlite3").connect(str(dest))
            with dst:
                src.backup(dst)
            src.close(); dst.close()
            self.store.insert("checkpoints", tick=tick, path=str(dest),
                              created_at=__import__("datetime").datetime.now(
                                  __import__("datetime").timezone.utc).isoformat())
            return str(dest)
        except Exception as exc:
            self.store.log_event(tick, "checkpoint_failed", {"error": str(exc)}, importance=2.0)
            return None

    def _save_prng_state(self) -> None:
        self.store.set_meta(
            prng_state=json.dumps(_prng_state(self.engine_prng)),
            lifecycle_prng_state=json.dumps(_prng_state(self.lifecycle_prng)),
            governor_json=json.dumps(self.gateway.governor.status()))

    def restore_prng_state(self) -> None:
        meta = self.store.get_meta()
        if meta["prng_state"]:
            self.engine_prng.setstate(_from_state(json.loads(meta["prng_state"])))
        if meta["lifecycle_prng_state"]:
            self.lifecycle_prng.setstate(_from_state(json.loads(meta["lifecycle_prng_state"])))


def _prng_state(r: random.Random):
    s = r.getstate()
    return [s[0], list(s[1]), s[2]]


def _from_state(s):
    return (s[0], tuple(s[1]), s[2])


def new_run_id() -> str:
    return uuid.uuid4().hex[:10]
