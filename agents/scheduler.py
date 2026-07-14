"""Wakeup scheduler (TECH-SPEC §3).

Every agent acts *only when scheduled* — the single biggest cost lever. Citizens
act on personal cadences (shop ~daily-ish, portfolio weekly, career monthly) plus
event-triggered wakeups (your bank is in the news, you got fired, someone told you
something alarming). Institutional agents act every tick. The governor's cadence
multiplier stretches citizen cadences under budget pressure.
"""
from __future__ import annotations

from engine.store import Store, load_json


class Scheduler:
    def __init__(self, store: Store, config: dict):
        self.store = store
        self.config = config
        self.base_act_every = int(config.get("behavior", {}).get("act_every", 3))
        self.event_wake_importance = float(config.get("behavior", {}).get("event_wake_importance", 2.0))
        self.institutional_role_purposes = bool(
            config.get("llm", {}).get("institutional_role_purposes", False))

    def scheduled_agents(self, tick: int, cadence_multiplier: int = 1, citizens_enabled: bool = True) -> list:
        if int(self.config.get("engine_semantics_version", 1)) >= 5:
            # In the living-world profile, only the promoted core receives an
            # LLM/scripted strategic turn. Peripheral agents still participate
            # in payroll, consumption, lifecycle, markets, exposure, and votes
            # through deterministic engines.
            agents = self.store.query(
                "SELECT * FROM agents WHERE alive=1 AND population_tier='core' ORDER BY id")
        else:
            agents = self.store.query("SELECT * FROM agents WHERE alive=1 ORDER BY id")
        out = []
        meeting_interval = int(self.config.get("central_bank", {}).get("meeting_interval_ticks", 7))
        liquidity_decision_due = (
            int(self.config.get("engine_semantics_version", 1)) >= 6
            and self._has_pending_liquidity_request())
        for a in agents:
            if (self.institutional_role_purposes
                    and a["role"] in {"editor", "reporter"}):
                # The Newsroom owns these seats and already records role-bound
                # reporter/newsroom calls. A second generic strategic turn
                # collides with the reporter response contract.
                continue
            if a["role"] == "central_banker":
                # Regular rate meetings retain their cadence, but an unresolved
                # lender-of-last-resort request is an immediate policy wakeup.
                if liquidity_decision_due or tick % max(1, meeting_interval) == 0:
                    out.append(a)
                continue
            if a["role"]:  # other institutional agents act every tick
                out.append(a)
                continue
            if not citizens_enabled:
                if self._event_triggered(int(a["id"]), tick):
                    out.append(a)
                continue
            if self._citizen_wakes(a, tick, cadence_multiplier):
                out.append(a)
        return out

    def _has_pending_liquidity_request(self) -> bool:
        return self.store.query_one(
            "SELECT 1 FROM liquidity_support_requests r "
            "JOIN banks b ON b.id=r.bank_id "
            "WHERE r.status='pending' AND b.status='open' "
            "ORDER BY r.request_event_id LIMIT 1") is not None

    def _citizen_wakes(self, a, tick: int, cadence_multiplier: int) -> bool:
        agent_id = int(a["id"])
        cadence = load_json(a["cadence_json"], {}) or {}
        act_every = max(1, int(cadence.get("act", self.base_act_every)) * max(1, cadence_multiplier))
        portfolio_every = max(1, int(cadence.get("portfolio", 7)) * max(1, cadence_multiplier))
        career_every = max(1, int(cadence.get("career", 30)) * max(1, cadence_multiplier))
        # Concern-specific cadences are independent wakeups, not annotations
        # that only matter when they happen to coincide with the base cadence.
        if tick % portfolio_every == agent_id % portfolio_every:
            return True
        if tick % career_every == agent_id % career_every:
            return True
        # Deterministic phase offset so wakeups spread evenly across ticks.
        if tick % act_every == agent_id % act_every:
            return True
        # Unemployed working-age agents search more actively.
        if not a["retired"] and a["health"] == "healthy":
            employed = self.store.query_one(
                "SELECT 1 FROM employments WHERE agent_id=? AND status='active'", (agent_id,))
            if not employed and tick % 2 == agent_id % 2:
                return True
        return self._event_triggered(agent_id, tick)

    def _event_triggered(self, agent_id: int, tick: int) -> bool:
        row = self.store.query_one(
            "SELECT 1 FROM memories WHERE agent_id=? AND tick>=? AND kind='observation' "
            "AND importance >= ? LIMIT 1", (agent_id, tick - 1, self.event_wake_importance))
        return row is not None
