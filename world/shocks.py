"""Shock library (PRD R9): policy-rate override, oil/commodity shock, false rumor,
slanted-news directive, firm scandal — each wrappable in three trigger types
(taxonomy borrowed from Doxa's design, no code): shock (instant at tick N),
trend (gradual over a duration), conditional (fires when a metric predicate holds).

Scheduled in config or fired live from the dashboard. Every firing is a logged
event with observable downstream effects.
"""
from __future__ import annotations

import json
from typing import Optional

from engine.core import Economy
from engine.store import load_json

SHOCK_KINDS = ("policy_rate", "policy_rule_change", "oil", "rumor", "slant", "scandal", "epidemic")
TRIGGER_TYPES = ("shock", "trend", "conditional")


class Shocks:
    def __init__(self, economy: Economy, config: dict):
        self.e = economy
        self.store = economy.store
        self.config = config

    # ── scheduling ───────────────────────────────────────────────────────────
    def load_from_config(self) -> None:
        for s in self.config.get("shocks", []) or []:
            self.schedule(
                kind=s["kind"], trigger_type=s.get("trigger", "shock"),
                trigger=s.get("trigger_params", {"tick": s.get("tick", 1)}),
                duration_ticks=int(s.get("duration_ticks", 0)),
                params=s.get("params", {}), label=s.get("label", s["kind"]))

    def schedule(self, kind: str, trigger_type: str, trigger: dict, *,
                 duration_ticks: int = 0, params: Optional[dict] = None,
                 label: str = "") -> int:
        if kind not in SHOCK_KINDS:
            raise ValueError(f"unknown shock kind {kind}")
        if trigger_type not in TRIGGER_TYPES:
            raise ValueError(f"unknown trigger type {trigger_type}")
        if duration_ticks < 0:
            raise ValueError("shock duration_ticks must be non-negative")
        return self.store.insert(
            "shocks", kind=kind, trigger_type=trigger_type, trigger_json=json.dumps(trigger),
            duration_ticks=duration_ticks, params_json=json.dumps(params or {}),
            label=label or kind, fired=0)

    # ── evaluation (each tick, NIGHT_CLOSE before metrics) ───────────────────
    def evaluate(self, tick: int) -> list[dict]:
        fired = []
        for s in self.store.query("SELECT * FROM shocks"):
            trigger = load_json(s["trigger_json"], {}) or {}
            params = load_json(s["params_json"], {}) or {}
            sid = int(s["id"])
            if not s["fired"]:
                if self._should_fire(s, trigger, tick):
                    self._fire(tick, s, params)
                    fired.append({"id": sid, "kind": s["kind"], "label": s["label"]})
            elif s["active_until_tick"]:
                until = int(s["active_until_tick"])
                if s["trigger_type"] == "trend" and tick <= until:
                    self._apply_trend_step(tick, s, params)
                if tick == until + 1:
                    # Episode shocks (e.g. epidemic) get an end hook when defined.
                    ender = getattr(self, f"_end_{s['kind']}", None)
                    if ender:
                        ender(tick, s, params)
        return fired

    def _should_fire(self, s, trigger: dict, tick: int) -> bool:
        ttype = s["trigger_type"]
        if ttype == "shock":
            return tick >= int(trigger.get("tick", 0))
        if ttype == "trend":
            return tick >= int(trigger.get("start", trigger.get("tick", 0)))
        if ttype == "conditional":
            metric = trigger.get("metric")
            op = trigger.get("op", ">")
            threshold = float(trigger.get("threshold", 0.0))
            if not metric:
                return False
            val = self.store.metric_latest(metric, default=float("nan"))
            if val != val:  # NaN → metric not yet recorded
                return False
            return {"<": val < threshold, ">": val > threshold,
                    "<=": val <= threshold, ">=": val >= threshold}.get(op, False)
        return False

    # ── firing ───────────────────────────────────────────────────────────────
    def _fire(self, tick: int, s, params: dict) -> None:
        sid = int(s["id"])
        kind = s["kind"]
        duration = int(s["duration_ticks"] or 0)
        until = tick + duration if duration else None
        self.store.update("shocks", sid, fired=1, fired_tick=tick, active_until_tick=until)
        handler = getattr(self, f"_apply_{kind}")
        handler(tick, s, params, initial=True)
        self.store.log_event(tick, "shock_fired", {
            "shock_id": sid, "kind": kind, "label": s["label"], "params": params,
            "trigger_type": s["trigger_type"], "duration_ticks": duration},
            phase="NIGHT_CLOSE", importance=4.0)

    def _apply_trend_step(self, tick: int, s, params: dict) -> None:
        handler = getattr(self, f"_apply_{s['kind']}")
        handler(tick, s, params, initial=False)

    # ── the five shock hooks (TECH-SPEC §9) ──────────────────────────────────
    def _apply_policy_rate(self, tick: int, s, params: dict, initial: bool) -> None:
        """Override the policy rate directly (bypasses the banker, still logged)."""
        target = int(params.get("rate_bps", 500))
        old = self.e.policy_rate_bps()
        self.store.record_metric(tick, "policy_rate", target)
        self.store.log_event(tick, "policy_rate_set", {
            "old_bps": old, "requested_bps": target, "new_bps": target,
            "via": "shock"}, phase="NIGHT_CLOSE", importance=3.0)

    def _apply_policy_rule_change(self, tick: int, s, params: dict, initial: bool) -> None:
        """Apply validated typed rules; used by paired policy scenarios."""
        changes = dict(params.get("changes", {}))
        error = self.e.politics._validate_policy_changes(changes)
        if error:
            raise ValueError(error)
        for key, value in sorted(changes.items()):
            self.store.execute(
                "UPDATE policy_rules SET status='superseded' WHERE rule_key=? AND status='active'",
                (key,))
            self.store.insert(
                "policy_rules", bill_id=None, rule_key=key,
                value_json=json.dumps(value, sort_keys=True), enacted_tick=tick,
                effective_tick=tick, status="active")
            if key in {"tax_rate_bps", "unemployment_benefit_cents"}:
                self.store.record_metric(tick, key, float(value))
        self.store.log_event(tick, "policy_rule_change", {
            "changes": changes, "via": "scenario_shock"}, phase="NIGHT_CLOSE",
            subject_type="government", subject_id=1, importance=4.0)

    def _apply_oil(self, tick: int, s, params: dict, initial: bool) -> None:
        """Scale the global commodity index every firm's input costs read."""
        cur = self.store.metric_latest("commodity_index", 1.0)
        if s["trigger_type"] == "trend" and int(s["duration_ticks"] or 0) > 0:
            total = float(params.get("multiplier", 1.5))
            steps = max(1, int(s["duration_ticks"]))
            step_mult = total ** (1.0 / steps)
            new = cur * step_mult
        else:
            new = cur * float(params.get("multiplier", 1.5))
        self.store.record_metric(tick, "commodity_index", new)
        if initial:
            self.store.log_event(tick, "commodity_shock", {
                "old": round(cur, 4), "new": round(new, 4)}, phase="NIGHT_CLOSE", importance=3.0)

    def _apply_rumor(self, tick: int, s, params: dict, initial: bool) -> None:
        """Inject a synthetic 'heard' observation about a bank into targeted agents'
        memories. Purely informational — the engine touches no balance."""
        research_targeting = "bank_selector" in params or "audience" in params
        selector = str(params.get("bank_selector", "explicit"))
        if selector == "largest_by_deposits":
            candidates = [
                (self.e.bank.deposits(int(row["id"])), int(row["id"]))
                for row in self.store.query(
                    "SELECT id FROM banks WHERE status='open' ORDER BY id")
            ]
            if not candidates:
                raise RuntimeError("rumor shock requires an open bank")
            bank_id = max(candidates, key=lambda item: (item[0], -item[1]))[1]
        elif selector == "explicit":
            bank_id = int(params.get("bank_id", 1))
        else:
            raise ValueError(
                "rumor bank_selector must be explicit or largest_by_deposits")

        n = int(params.get("n_agents", 12))
        audience = str(params.get("audience", "all_citizens"))
        text = params.get("text",
            f"A friend of a friend says bank {bank_id} is about to go under — people are quietly pulling out.")
        if audience == "current_depositors":
            agents = self.store.query(
                "SELECT a.id FROM agents a JOIN accounts ac ON ac.id=a.checking_account_id "
                "WHERE a.alive=1 AND a.kind='citizen' AND ac.bank_id=? "
                "AND ac.balance_cents>0 ORDER BY a.id", (bank_id,))
        elif audience == "all_citizens":
            agents = self.store.query(
                "SELECT id FROM agents WHERE alive=1 AND kind='citizen' ORDER BY id")
        else:
            raise ValueError(
                "rumor audience must be all_citizens or current_depositors")
        # Deterministic target selection from the engine PRNG.
        ids = [int(r["id"]) for r in agents]
        self.e.prng.shuffle(ids)
        targets = ids[:n]
        if research_targeting:
            params["resolved_bank_id"] = bank_id
            params["bank_id"] = bank_id
            params["audience"] = audience
            params["target_agent_ids"] = targets
        for aid in targets:
            self.store.insert(
                "memories", agent_id=aid, tick=tick, kind="observation",
                text=text, importance=4.0,
                entities_json=json.dumps([f"bank:{bank_id}", f"rumor_bank:{bank_id}"]),
                last_accessed_tick=tick, demoted=0)
        event_payload = {
            "bank_id": bank_id, "n_agents": len(targets), "target_agent_ids": targets,
            "text": text, "truthful": False,
        }
        if research_targeting:
            event_payload.update({"bank_selector": selector, "audience": audience})
        self.store.log_event(tick, "rumor", event_payload,
            phase="NIGHT_CLOSE", subject_type="bank", subject_id=bank_id, importance=3.5)

    def _apply_slant(self, tick: int, s, params: dict, initial: bool) -> None:
        """Give one outlet a framing directive for N ticks (read by the newsroom)."""
        outlet_id = int(params.get("outlet_id", 1))
        directive = params.get("directive", "Frame today's coverage as alarming for financial stability.")
        until = tick + int(s["duration_ticks"] or params.get("ticks", 5))
        self.store.log_event(tick, "slant_directive", {
            "outlet_id": outlet_id, "directive": directive, "until_tick": until},
            phase="NIGHT_CLOSE", importance=2.0)

    def _apply_scandal(self, tick: int, s, params: dict, initial: bool) -> None:
        """Inject a TRUE negative event about a firm; the newsroom picks it up naturally."""
        firm_id = int(params.get("firm_id", 1))
        firm = self.store.query_one("SELECT name FROM firms WHERE id=?", (firm_id,))
        desc = params.get("description", "Regulators opened an investigation into accounting irregularities.")
        self.store.log_event(tick, "firm_scandal", {
            "firm_id": firm_id, "firm_name": firm["name"] if firm else f"firm {firm_id}",
            "description": desc}, phase="NIGHT_CLOSE", subject_type="firm",
            subject_id=firm_id, importance=4.0)

    def _apply_epidemic(self, tick: int, s, params: dict, initial: bool) -> None:
        """Scale the illness-onset hazard (a trend-type health shock, PRD R17).
        Ends when duration_ticks expire (the `_end_epidemic` hook resets to 1.0);
        without a duration it persists as a chronic-disease environment."""
        mult = float(params.get("multiplier", 4.0))
        self.store.record_metric(tick, "epidemic_multiplier", mult)
        if initial:
            self.store.log_event(tick, "epidemic_started", {
                "multiplier": mult, "duration_ticks": int(s["duration_ticks"] or 0)},
                phase="NIGHT_CLOSE", importance=4.5)

    def _end_epidemic(self, tick: int, s, params: dict) -> None:
        self.store.record_metric(tick, "epidemic_multiplier", 1.0)
        self.store.log_event(tick, "epidemic_ended", {"shock_id": int(s["id"])},
                             phase="NIGHT_CLOSE", importance=3.0)

    # ── active slant directives (newsroom queries this) ──────────────────────
    def active_slant_directives(self, tick: int) -> dict[int, str]:
        rows = self.store.query(
            "SELECT payload_json FROM events WHERE kind='slant_directive' ORDER BY id DESC LIMIT 10")
        out: dict[int, str] = {}
        for r in rows:
            p = load_json(r["payload_json"], {}) or {}
            if int(p.get("until_tick", 0)) >= tick and int(p.get("outlet_id", 0)) not in out:
                out[int(p["outlet_id"])] = p.get("directive", "")
        return out
