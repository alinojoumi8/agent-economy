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
        self.engine_semantics_version = int(config.get("engine_semantics_version", 1))
        self.retired_news_every = max(1, int(
            config.get("lifecycle", {}).get("retired_news_every", 1)))

    def scheduled_agents(self, tick: int, cadence_multiplier: int = 1, citizens_enabled: bool = True) -> list:
        semantics_version = int(self.config.get("engine_semantics_version", 1))
        if semantics_version >= 7:
            # Core and peripheral citizens share the same state-derived wakeup
            # cadence. AgentRuntime keeps the promoted core on its configured
            # provider while routing the periphery through local scripted
            # policies, so households actually consume and trade without
            # creating model calls for the long tail.
            agents = self.store.query(
                "SELECT * FROM agents WHERE alive=1 ORDER BY id")
        elif semantics_version >= 5:
            # Preserve the recorded Semantics-5/6 scheduling contract.
            agents = self.store.query(
                "SELECT * FROM agents WHERE alive=1 AND population_tier='core' ORDER BY id")
        else:
            agents = self.store.query("SELECT * FROM agents WHERE alive=1 ORDER BY id")
        # Resolve wake-up state in three bounded queries.  At flagship scale the
        # former per-citizen probes caused up to three extra SQLite queries for
        # every living agent on every tick.
        wake_state = self._wake_state(tick)
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
                if int(a["id"]) in wake_state["event_triggered"]:
                    out.append(a)
                continue
            if self._citizen_wakes(
                    a, tick, cadence_multiplier,
                    employed_ids=wake_state["employed"],
                    event_triggered_ids=wake_state["event_triggered"],
                    unpriced_holder_ids=wake_state["unpriced_holders"]):
                out.append(a)
        return out

    def _wake_state(self, tick: int) -> dict[str, set[int]]:
        employed = {
            int(row["agent_id"])
            for row in self.store.query(
                "SELECT agent_id FROM employments WHERE status='active'")
        }
        event_triggered = {
            int(row["agent_id"])
            for row in self.store.query(
                "SELECT DISTINCT agent_id FROM memories "
                "WHERE tick>=? AND kind='observation' AND importance>=?",
                (tick - 1, self.event_wake_importance))
        }
        unpriced_holders: set[int] = set()
        if self.engine_semantics_version >= 7:
            unpriced_holders = {
                int(row["agent_id"])
                for row in self.store.query(
                    "SELECT DISTINCT s.holder_id AS agent_id FROM shares s "
                    "JOIN firms f ON f.id=s.firm_id "
                    "WHERE s.holder_type='agent' AND s.qty>0 "
                    "AND f.status='listed' "
                    "AND NOT EXISTS (SELECT 1 FROM trades t WHERE t.firm_id=f.id) "
                    "AND NOT EXISTS (SELECT 1 FROM metrics m "
                    " WHERE m.name='stock:' || f.id)")
            }
        return {
            "employed": employed,
            "event_triggered": event_triggered,
            "unpriced_holders": unpriced_holders,
        }

    def _has_pending_liquidity_request(self) -> bool:
        return self.store.query_one(
            "SELECT 1 FROM liquidity_support_requests r "
            "JOIN banks b ON b.id=r.bank_id "
            "WHERE r.status='pending' AND b.status='open' "
            "ORDER BY r.request_event_id LIMIT 1") is not None

    def _citizen_wakes(
        self,
        a,
        tick: int,
        cadence_multiplier: int,
        *,
        employed_ids: set[int] | None = None,
        event_triggered_ids: set[int] | None = None,
        unpriced_holder_ids: set[int] | None = None,
    ) -> bool:
        agent_id = int(a["id"])
        # A listing cannot form its first price unless at least two holders see
        # the same book in the same session. Wake every holder while any of
        # their listed positions is still genuinely unpriced; the actors still
        # choose the bid/ask and therefore determine the price.
        if self.engine_semantics_version >= 7:
            holds_unpriced = (
                agent_id in unpriced_holder_ids
                if unpriced_holder_ids is not None
                else self._holds_unpriced_listing(agent_id)
            )
            if holds_unpriced:
                return True
        cadence = load_json(a["cadence_json"], {}) or {}
        act_every = max(1, int(cadence.get("act", self.base_act_every)) * max(1, cadence_multiplier))
        portfolio_every = max(1, int(cadence.get("portfolio", 7)) * max(1, cadence_multiplier))
        career_every = max(1, int(cadence.get("career", 30)) * max(1, cadence_multiplier))
        if self.engine_semantics_version >= 7 and bool(a["retired"]):
            news_every = max(1, int(cadence.get("news", self.retired_news_every))
                             * max(1, cadence_multiplier))
            if tick % news_every == agent_id % news_every:
                return True
        # Concern-specific cadences are independent wakeups, not annotations
        # that only matter when they happen to coincide with the base cadence.
        if tick % portfolio_every == agent_id % portfolio_every:
            return True
        if (not (self.engine_semantics_version >= 7 and bool(a["retired"]))
                and tick % career_every == agent_id % career_every):
            return True
        # Deterministic phase offset so wakeups spread evenly across ticks.
        if tick % act_every == agent_id % act_every:
            return True
        # Unemployed working-age agents search more actively.
        if not a["retired"] and a["health"] == "healthy":
            employed = (
                agent_id in employed_ids
                if employed_ids is not None
                else self.store.query_one(
                    "SELECT 1 FROM employments WHERE agent_id=? AND status='active'",
                    (agent_id,)) is not None
            )
            if not employed and tick % 2 == agent_id % 2:
                return True
        if event_triggered_ids is not None:
            return agent_id in event_triggered_ids
        return self._event_triggered(agent_id, tick)

    def _holds_unpriced_listing(self, agent_id: int) -> bool:
        return self.store.query_one(
            "SELECT 1 FROM shares s JOIN firms f ON f.id=s.firm_id "
            "WHERE s.holder_type='agent' AND s.holder_id=? AND s.qty>0 "
            "AND f.status='listed' "
            "AND NOT EXISTS (SELECT 1 FROM trades t WHERE t.firm_id=f.id) "
            "AND NOT EXISTS (SELECT 1 FROM metrics m WHERE m.name='stock:' || f.id) "
            "ORDER BY f.id LIMIT 1", (agent_id,)) is not None

    def _event_triggered(self, agent_id: int, tick: int) -> bool:
        row = self.store.query_one(
            "SELECT 1 FROM memories WHERE agent_id=? AND tick>=? AND kind='observation' "
            "AND importance >= ? LIMIT 1", (agent_id, tick - 1, self.event_wake_importance))
        return row is not None
