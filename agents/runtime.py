"""Agent runtime — the perceive → decide → execute loop (PRD R2, TECH-SPEC §3).

Decisions for a tick are computed concurrently (LLM calls parallelise), then the
executor applies them in deterministic agent-id order so replay is exact. This
module also captures engine events as agent observations, and runs nightly memory
compression + belief extraction.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from engine.actions import ActionExecutor
from engine.core import Economy
from engine.store import load_json
from llm.gateway import (
    BudgetExceeded, Gateway, GatewayInterrupted, LLMRequest, ProviderUnavailable,
)
from .memory import Memory
from .prompts import ContextBuilder
from .policies import register_scripted_policies
from .scheduler import Scheduler
from .participant import ParticipantService
from observability import get_logger, log_event as operational_log


logger = get_logger("agents")


async def _gather_fail_fast(coroutines):
    """Preserve input ordering while cancelling queued work after a failure."""
    tasks = [asyncio.create_task(coroutine) for coroutine in coroutines]
    try:
        return await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


class AgentRuntime:
    def __init__(self, economy: Economy, gateway: Gateway, config: dict):
        self.e = economy
        self.store = economy.store
        self.gw = gateway
        self.config = config
        self.mem = Memory(self.store, config)
        self.ctx = ContextBuilder(economy, self.mem, config)
        self.participant = ParticipantService(self.store, self.ctx, config)
        self.executor = ActionExecutor(economy)
        self.scheduler = Scheduler(self.store, config)
        register_scripted_policies(self.gw.scripted)

    # ── MORNING: decide (concurrent) ─────────────────────────────────────────
    async def decide_all(self, tick: int) -> list[dict]:
        gov = self.gw.governor
        agents = self.scheduler.scheduled_agents(
            tick, cadence_multiplier=gov.cadence_multiplier(), citizens_enabled=gov.citizens_enabled())
        participant_decision = self.participant.decision_for_tick(tick)
        participant_agent_id = (
            int(participant_decision["agent_id"]) if participant_decision is not None else None)
        if participant_agent_id is not None:
            agents = [a for a in agents if int(a["id"]) != participant_agent_id]
        tasks = [self._decide_guarded(tick, a) for a in agents]
        results = await _gather_fail_fast(tasks)
        decisions = []
        errors = 0
        for a, res in zip(agents, results):
            if isinstance(res, (BudgetExceeded, GatewayInterrupted, ProviderUnavailable)):
                raise res
            if isinstance(res, Exception):
                errors += 1
                self.store.log_event(tick, "decision_error", {
                    "agent_id": int(a["id"]), "error": str(res)}, phase="MORNING", importance=0.5)
                operational_log(logger, logging.WARNING, "agent.decision.failed",
                                run_id=self.gw.run_id, tick=tick, agent_id=int(a["id"]),
                                role=a["role"] or "citizen",
                                error_type=type(res).__name__, error=str(res))
                continue
            if res is not None:
                decisions.append(res)
        if participant_decision is not None:
            decisions.append(participant_decision)
        # An LLM outage pauses the sim rather than skipping agents silently (§8).
        if agents and errors > len(agents) // 2:
            operational_log(logger, logging.ERROR, "agent.decision.outage_suspected",
                            run_id=self.gw.run_id, tick=tick, errors=errors,
                            scheduled_agents=len(agents))
            raise RuntimeError(
                f"LLM outage suspected: {errors}/{len(agents)} decisions failed at tick {tick}")
        # deterministic execution order
        decisions.sort(key=lambda d: d["agent_id"])
        return decisions

    async def _decide_guarded(self, tick: int, agent):
        try:
            return await self._decide_one(tick, agent)
        except (BudgetExceeded, GatewayInterrupted, ProviderUnavailable):
            raise
        except Exception as exc:
            return exc

    async def _decide_one(self, tick: int, a) -> Optional[dict]:
        context = self.ctx.build(a, tick)
        purpose = context.get("purpose", "decision")
        role = a["role"] or "citizen"
        system, user = self.ctx.render_prompt(context)
        req = LLMRequest(role=role, purpose=purpose, system=system, user=user, context=context,
                         agent_id=int(a["id"]), tick=tick,
                         max_tokens=int(self.config.get("llm", {}).get(
                             "decision_max_tokens", 900)))
        resp = await self.gw.complete(req)
        env = resp.parsed if isinstance(resp.parsed, dict) else {}
        return {"agent_id": int(a["id"]), "purpose": purpose, "envelope": env,
                "reasoning": env.get("reasoning", ""),
                "llm_call_id": getattr(resp, "call_id", None)}

    # ── EXECUTION: apply (deterministic order) ───────────────────────────────
    def execute_decisions(self, tick: int, decisions: list[dict]) -> None:
        for d in decisions:
            agent_id = d["agent_id"]
            env = d["envelope"] or {}
            actions = env.get("actions", []) if isinstance(env, dict) else []
            model_call_id = d.get("llm_call_id")
            rationale = str(d.get("reasoning") or "").strip()[:500]
            attributed_actions = []
            for action in actions:
                if not isinstance(action, dict):
                    attributed_actions.append(action)
                    continue
                attributed = dict(action)
                # Provenance is execution metadata, not model-controlled state.
                # Always bind an LLM-originated action to the authoritative call
                # record returned by the gateway, regardless of model output.
                if model_call_id is not None:
                    attributed["model_call_id"] = model_call_id
                if rationale and not attributed.get("rationale_summary"):
                    attributed["rationale_summary"] = rationale
                attributed_actions.append(attributed)
            results = self.executor.execute_actions(
                tick, agent_id, attributed_actions, phase="EXECUTION")
            self.participant.complete(d.get("participant_action_id"), results, tick)
            self.mem.apply_belief_updates(
                agent_id, env.get("belief_updates", []), tick,
                source=str(d.get("purpose") or "decision"),
                source_llm_call_id=d.get("llm_call_id"))
            reasoning = (d.get("reasoning") or "").strip()
            if reasoning:
                self.mem.observe(agent_id, tick, f"I decided: {reasoning}", importance=1.0,
                                 entities=["self"])

    # ── observation capture from engine events ───────────────────────────────
    def capture_event_observations(self, tick: int) -> None:
        events = self.store.query(
            "SELECT * FROM events WHERE tick=? AND kind NOT IN "
            "('action_rejected','metrics_snapshot','arrival_scheduled',"
            "'belief_updated','belief_update_normalized','belief_update_rejected') "
            "ORDER BY id", (tick,))
        for ev in events:
            payload = load_json(ev["payload_json"], {}) or {}
            kind = ev["kind"]
            importance = float(ev["importance"])
            # Direct-subject observation.
            if ev["subject_type"] == "agent" and ev["subject_id"]:
                self.mem.observe(int(ev["subject_id"]), tick, self._describe(kind, payload),
                                 importance=importance, entities=self._entities(kind, payload))
            # Bank failure / rumor concern depositors of that bank.
            if kind == "bank_failure":
                bank_id = payload.get("bank_id")
                for dep in self._depositors(bank_id):
                    self.mem.observe(dep, tick, f"My bank (bank {bank_id}) failed.",
                                     importance=5.0, entities=[f"bank:{bank_id}", f"rumor_bank:{bank_id}"])
            if kind == "death":
                for tie in self._ties(payload.get("agent_id")):
                    self.mem.observe(tie, tick, f"{payload.get('name','Someone')} has died.",
                                     importance=3.0, entities=["death"])

    def _describe(self, kind: str, payload: dict) -> str:
        return {
            "wage_paid": f"I was paid {payload.get('wage_cents',0)}c.",
            "hired": "I got a job.",
            "fired": "I was let go from my job.",
            "loan_originated": f"My loan of {payload.get('amount_cents',0)}c was approved.",
            "loan_default": "I defaulted on a loan.",
            "loan_arrears": "I missed a loan payment.",
            "illness_onset": "I fell ill.",
            "recovery": "I recovered.",
            "goods_sale": "I bought goods.",
            "deposit_move": f"I moved my deposits to bank {payload.get('to_bank')}.",
            "retirement": "I retired.",
            "birth": "A new dependent joined my household.",
            "benefit_paid": "I received an unemployment benefit payment.",
            "policy_bought": "I took out health insurance.",
            "policy_lapsed": "My health insurance lapsed - I couldn't pay the premium.",
            "insurance_claim": "My insurance covered part of my medical bill.",
            "pitch_made": "I pitched my company to the venture fund.",
            "vc_funded": "My company raised a venture round.",
        }.get(kind, f"Something happened: {kind}.")

    def _entities(self, kind: str, payload: dict) -> list[str]:
        ents = ["self"]
        if "bank_id" in payload:
            ents.append(f"bank:{payload['bank_id']}")
        if "to_bank" in payload:
            ents.append(f"bank:{payload['to_bank']}")
        if "firm_id" in payload:
            ents.append(f"firm:{payload['firm_id']}")
        return ents

    def _depositors(self, bank_id) -> list[int]:
        if bank_id is None:
            return []
        rows = self.store.query(
            "SELECT DISTINCT owner_id FROM accounts WHERE bank_id=? AND owner_type='agent'", (bank_id,))
        return [int(r["owner_id"]) for r in rows if r["owner_id"] is not None]

    def _ties(self, agent_id) -> list[int]:
        if agent_id is None:
            return []
        rows = self.store.query(
            "SELECT CASE WHEN agent_a=? THEN agent_b ELSE agent_a END AS other FROM social_ties "
            "WHERE agent_a=? OR agent_b=?", (agent_id, agent_id, agent_id))
        return [int(r["other"]) for r in rows]

    # ── MEMORY: nightly compression + belief extraction ──────────────────────
    async def compress_memories(self, tick: int) -> None:
        # Only agents with observations today need compressing.
        living_world = int(self.config.get("engine_semantics_version", 1)) >= 5
        if living_world:
            rows = self.store.query(
                "SELECT DISTINCT m.agent_id,a.population_tier FROM memories m "
                "JOIN agents a ON a.id=m.agent_id "
                "WHERE m.tick=? AND m.kind='observation' "
                "AND m.agent_id NOT IN (SELECT agent_id FROM memories "
                "WHERE tick=? AND kind='summary') ORDER BY m.agent_id", (tick, tick))
        else:
            rows = self.store.query(
                "SELECT DISTINCT agent_id,NULL AS population_tier FROM memories "
                "WHERE tick=? AND kind='observation' "
                "AND agent_id NOT IN (SELECT agent_id FROM memories "
                "WHERE tick=? AND kind='summary') ORDER BY agent_id", (tick, tick))
        # Semantics-v5 uses deterministic daily compression for everyone and a
        # model-capable weekly reflection for the core below. Older semantics
        # retain their daily model path unchanged.
        agent_ids = [] if living_world else [int(r["agent_id"]) for r in rows]
        for row in rows:
            if not living_world:
                continue
            aid = int(row["agent_id"])
            observations = self.mem.todays_observations(aid, tick)
            if not observations:
                continue
            summary = " | ".join(
                str(item.get("text", item)) for item in observations)[:1800]
            importance = max(
                (float(item.get("importance", 1.0)) for item in observations),
                default=1.0,
            )
            self.mem.write_summary(aid, tick, summary, importance)
        sem_tasks = [self._compress_one(tick, aid) for aid in agent_ids]
        results = await _gather_fail_fast(sem_tasks)
        for aid, res in zip(agent_ids, results):
            if isinstance(res, BudgetExceeded):
                raise res
            if isinstance(res, Exception):
                raise res
            if res is None:
                continue
            summary, importance, belief_updates, llm_call_id = res
            self.mem.apply_belief_updates(
                aid, belief_updates, tick, source="memory",
                source_llm_call_id=llm_call_id)
            self.mem.write_summary(aid, tick, summary, importance)

        if tick % 7 == 0:
            if living_world:
                weekly_rows = self.store.query(
                    "SELECT DISTINCT m.agent_id,a.population_tier FROM memories m "
                    "JOIN agents a ON a.id=m.agent_id WHERE m.kind='summary' "
                    "AND m.demoted=0 AND m.tick BETWEEN ? AND ? ORDER BY m.agent_id",
                    (tick - 6, tick))
            else:
                weekly_rows = self.store.query(
                    "SELECT DISTINCT agent_id,NULL AS population_tier FROM memories "
                    "WHERE kind='summary' AND demoted=0 AND tick BETWEEN ? AND ? "
                    "ORDER BY agent_id", (tick - 6, tick))
            weekly_ids = [
                int(r["agent_id"]) for r in weekly_rows
                if not living_world or r["population_tier"] == "core"
            ]
            for row in weekly_rows:
                if not living_world or row["population_tier"] == "core":
                    continue
                aid = int(row["agent_id"])
                daily = self.store.query(
                    "SELECT text,importance FROM memories WHERE agent_id=? "
                    "AND kind='summary' AND demoted=0 AND tick BETWEEN ? AND ? "
                    "ORDER BY tick,id", (aid, tick - 6, tick))
                if daily:
                    summary = "Week summary: " + " | ".join(
                        str(item["text"]) for item in daily)[:1800]
                    importance = max(float(item["importance"]) for item in daily)
                    self.mem.weekly_rollup(aid, tick, summary, importance)
            weekly_results = await _gather_fail_fast(
                self._rollup_week(tick, aid) for aid in weekly_ids)
            for aid, res in zip(weekly_ids, weekly_results):
                if isinstance(res, Exception):
                    raise res
                if res is None:
                    continue
                summary, importance = res
                self.mem.weekly_rollup(aid, tick, summary, importance)

    async def _compress_one(
        self, tick: int, agent_id: int,
    ) -> Optional[tuple[str, float, list[dict], Optional[int]]]:
        obs = self.mem.todays_observations(agent_id, tick)
        if not obs:
            return
        context = {"observations": obs, "tick": tick, "rng_seed": agent_id * 7 + tick,
                   "infl_hint": self.ctx.inflation_signal()}
        schema = '{"summary":"concise memory","importance":1.0,"belief_updates":[]}'
        req = LLMRequest(
            role="citizen", purpose="memory",
            system=(
                "Compress today's observations into one concise first-person memory. "
                "Respond ONLY with JSON matching " + schema
                + ". importance must be a number from 0 to 5. belief_updates must "
                  "contain only objects with key and numeric value fields."),
            user=json.dumps(context)[:4000], context=context,
            agent_id=agent_id, tick=tick, max_tokens=200)
        resp = await self.gw.complete(req, schema_hint=schema)
        env = resp.parsed if isinstance(resp.parsed, dict) else {}
        summary = str(env.get("summary", "")).strip()
        if not summary:
            summary = " | ".join(str(item.get("text", item)) for item in obs)[:1800]
        try:
            importance = float(env.get("importance", 1.0))
        except (TypeError, ValueError):
            importance = 1.0
        updates = env.get("belief_updates", [])
        return (summary, importance, updates if isinstance(updates, list) else [],
                getattr(resp, "call_id", None))

    async def _rollup_week(
        self, tick: int, agent_id: int,
    ) -> Optional[tuple[str, float]]:
        rows = self.store.query(
            "SELECT tick, text, importance FROM memories WHERE agent_id=? "
            "AND kind='summary' AND demoted=0 AND tick BETWEEN ? AND ? ORDER BY tick, id",
            (agent_id, tick - 6, tick))
        if not rows:
            return None
        daily = [{"tick": int(r["tick"]), "text": r["text"],
                  "importance": float(r["importance"])} for r in rows]
        context = {"weekly_summaries": daily, "tick": tick,
                   "rng_seed": agent_id * 701 + tick}
        schema = '{"summary":"concise weekly memory","importance":1.0}'
        req = LLMRequest(
            role="citizen", purpose="memory",
            system=("Synthesize the daily summaries into one concise weekly memory. "
                    "Respond ONLY with JSON matching " + schema + "."),
            user=json.dumps(daily)[:4000], context=context,
            agent_id=agent_id, tick=tick, max_tokens=240)
        resp = await self.gw.complete(req, schema_hint=schema)
        env = resp.parsed if isinstance(resp.parsed, dict) else {}
        summary = str(env.get("summary", "")).strip()
        if not summary:
            summary = "Week summary: " + " | ".join(r["text"] for r in daily)[:1800]
        importance = float(env.get("importance", max(r["importance"] for r in daily)))
        return summary, importance
