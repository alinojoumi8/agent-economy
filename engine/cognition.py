"""Deterministic compute subscriptions and learnable domain skills.

Skills are authoritative world state. Compute subscriptions decide model access.
Provider selection and operational concurrency remain the LLM gateway's concern.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from .ledger import Ledger, SYS_COMPUTE, SYS_EDUCATION, SYS_GOV
from .store import Store


SKILL_KEYS = (
    "household_finance",
    "labor",
    "commerce",
    "entrepreneurship",
    "finance",
    "law",
    "media",
    "governance",
)
XP_THRESHOLDS = (0, 10, 30, 70, 140, 250)
PLAN_TIERS = ("local", "flash", "premium")

DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "duration_ticks": 7,
    "flash_cost_cents": 5_000,
    "premium_cost_cents": 25_000,
    "study_cost_cents": 5_000,
    "premium_cap_fraction": 0.20,
    "initial_distribution": {"local": 0.50, "flash": 0.40, "premium": 0.10},
}

ROUTINE_INSTITUTIONAL_ROLES = {
    "legislator_house", "legislator_senate", "lobbyist", "reporter", "editor",
    "gov_official",
}
PREMIUM_INSTITUTIONAL_ROLES = {
    "central_banker", "credit_officer", "vc_partner", "exchange", "lawyer",
    "regulator", "competition_regulator", "labor_regulator", "executive", "oracle",
}

ROLE_SKILLS = {
    "central_banker": "finance",
    "credit_officer": "finance",
    "vc_partner": "finance",
    "exchange": "finance",
    "lawyer": "law",
    "regulator": "law",
    "competition_regulator": "law",
    "labor_regulator": "law",
    "editor": "media",
    "reporter": "media",
    "legislator_house": "governance",
    "legislator_senate": "governance",
    "lobbyist": "governance",
    "gov_official": "governance",
    "executive": "governance",
    "oracle": "governance",
}

OCCUPATION_SKILL_KEYWORDS = (
    ("entrepreneurship", ("founder", "entrepreneur", "business owner")),
    ("finance", ("account", "bank", "financ", "analyst", "trader", "broker")),
    ("law", ("law", "legal", "attorney", "paralegal")),
    ("media", ("journal", "report", "editor", "writer", "media")),
    ("governance", ("government", "policy", "civil service", "public admin")),
    ("commerce", ("sales", "retail", "merchant", "marketing", "shop", "buyer")),
    ("labor", ("engineer", "teacher", "doctor", "nurse", "worker", "technician",
               "driver", "operator", "mechanic", "chef", "scientist", "designer")),
)

COMPLEX_ACTIONS = {
    "found_company", "approve_loan", "deny_loan", "set_policy_rate",
    "decide_liquidity_support", "open_ipo", "close_ipo", "fund_pitch",
    "propose_contract", "counter_contract", "accept_contract", "file_claim",
    "submit_filing", "propose_settlement", "accept_settlement",
    "issue_legal_decision", "propose_term_sheet", "accept_term_sheet",
    "run_due_diligence", "close_funding_round", "register_ip", "license_ip",
    "publish_disclosure", "propose_merger", "approve_merger", "review_merger",
    "close_merger", "sponsor_bill", "amend_bill", "committee_vote",
    "cast_legislative_vote", "executive_bill_action", "override_veto", "lobby",
    "create_trade_shipment", "set_compute_sponsorship",
}

ACTION_SKILLS = {
    "buy_goods": "household_finance",
    "place_order": "finance",
    "cancel_orders": "finance",
    "apply_loan": "household_finance",
    "approve_loan": "finance",
    "deny_loan": "finance",
    "post_job": "labor",
    "apply_job": "labor",
    "make_job_offer": "labor",
    "counter_job_offer": "labor",
    "accept_job_offer": "labor",
    "reject_job_offer": "labor",
    "hire": "labor",
    "fire": "labor",
    "set_price": "commerce",
    "found_company": "entrepreneurship",
    "pitch_vc": "entrepreneurship",
    "fund_pitch": "finance",
    "decline_pitch": "finance",
    "open_ipo": "finance",
    "place_ipo_bid": "finance",
    "close_ipo": "finance",
    "transfer": "household_finance",
    "move_deposits": "household_finance",
    "withdraw_savings": "household_finance",
    "buy_insurance": "household_finance",
    "cancel_insurance": "household_finance",
    "buy_compute_plan": "household_finance",
    "cancel_compute_plan": "household_finance",
    "set_compute_sponsorship": "entrepreneurship",
    "set_policy_rate": "finance",
    "decide_liquidity_support": "finance",
    "propose_contract": "law",
    "counter_contract": "law",
    "accept_contract": "law",
    "reject_contract": "law",
    "perform_obligation": "law",
    "issue_legal_notice": "law",
    "file_claim": "law",
    "submit_filing": "law",
    "propose_settlement": "law",
    "accept_settlement": "law",
    "issue_legal_decision": "law",
    "propose_term_sheet": "entrepreneurship",
    "accept_term_sheet": "entrepreneurship",
    "run_due_diligence": "finance",
    "close_funding_round": "finance",
    "register_ip": "entrepreneurship",
    "license_ip": "entrepreneurship",
    "publish_disclosure": "finance",
    "propose_merger": "entrepreneurship",
    "approve_merger": "governance",
    "review_merger": "law",
    "close_merger": "entrepreneurship",
    "create_claim": "media",
    "publish_information": "media",
    "repost_information": "media",
    "correct_claim": "media",
    "say_public": "media",
    "send_message": "media",
    "reply_message": "media",
    "forward_message": "media",
    "sponsor_bill": "governance",
    "amend_bill": "governance",
    "committee_vote": "governance",
    "cast_legislative_vote": "governance",
    "executive_bill_action": "governance",
    "override_veto": "governance",
    "lobby": "governance",
    "place_fx_order": "finance",
    "cancel_fx_orders": "finance",
    "create_trade_shipment": "commerce",
    "request_migration": "labor",
}


def normalize_model_tier(value: object) -> str:
    """Interpret both Semantics-11 and historical model tier names."""
    tier = str(value or "local").lower().strip()
    if tier in PLAN_TIERS:
        return tier
    if tier == "strong":
        return "premium"
    if tier == "citizen":
        return "local"
    return "local"


def level_for_xp(xp: int) -> int:
    xp = max(0, int(xp))
    level = 0
    for candidate, threshold in enumerate(XP_THRESHOLDS):
        if xp >= threshold:
            level = candidate
    return min(5, level)


class CognitionEconomy:
    def __init__(self, store: Store, ledger: Ledger, params: dict | None, *,
                 engine_semantics_version: int, seed: int):
        self.store = store
        self.ledger = ledger
        self.engine_semantics_version = int(engine_semantics_version)
        self.p = {**DEFAULTS, **(params or {})}
        self.enabled = (
            self.engine_semantics_version >= 11
            and bool(self.p.get("enabled", True))
        )
        self.seed = int(seed)
        self.duration_ticks = max(1, int(self.p["duration_ticks"]))

    # -- deterministic seeding -------------------------------------------------
    def seed_world(self, tick: int = 0) -> None:
        if not self.enabled:
            return
        agents = self.store.query(
            "SELECT id,kind,role,occupation FROM agents WHERE alive=1 ORDER BY id")
        if not agents:
            return
        founder_ids = {int(row["founder_agent_id"]) for row in self.store.query(
            "SELECT founder_agent_id FROM firms WHERE founder_agent_id IS NOT NULL "
            "AND status<>'bankrupt'")}
        for agent in agents:
            self._seed_skills(agent, tick, int(agent["id"]) in founder_ids)

        citizens = [row for row in agents if str(row["kind"]) == "citizen"]
        citizen_tiers = self._exact_initial_tiers(citizens)
        for agent in agents:
            agent_id = int(agent["id"])
            role = str(agent["role"] or "")
            tier = self._institutional_tier(role) or citizen_tiers.get(agent_id, "local")
            payer_type = "government" if role else "launch_grant"
            payer_id = 1 if role else agent_id
            payer_account_id = (
                self.ledger.system_account(SYS_GOV) if role else None)
            reason = "institutional_launch_grant" if role else "citizen_launch_grant"
            self._seed_subscription(
                agent_id, tier, tick, payer_type, payer_id, payer_account_id, reason)

    def seed_agent(self, agent_id: int, tick: int) -> None:
        """Seed one later arrival without consuming either engine PRNG stream."""
        if not self.enabled:
            return
        agent = self.store.query_one(
            "SELECT id,kind,role,occupation FROM agents WHERE id=?", (agent_id,))
        if not agent:
            return
        founder = self.store.query_one(
            "SELECT 1 FROM firms WHERE founder_agent_id=? AND status<>'bankrupt' LIMIT 1",
            (agent_id,)) is not None
        self._seed_skills(agent, tick, founder)
        role = str(agent["role"] or "")
        tier = self._institutional_tier(role) or self._hashed_initial_tier(agent_id)
        self._seed_subscription(
            agent_id, tier, tick,
            "government" if role else "launch_grant",
            1 if role else agent_id,
            self.ledger.system_account(SYS_GOV) if role else None,
            "institutional_launch_grant" if role else "arrival_launch_grant",
        )

    def _seed_skills(self, agent, tick: int, founder: bool) -> None:
        agent_id = int(agent["id"])
        for key in SKILL_KEYS:
            self.store.execute(
                "INSERT OR IGNORE INTO agent_skills"
                "(agent_id,skill_key,xp,level,last_practiced_tick,source) "
                "VALUES (?,?,0,0,NULL,'genesis')", (agent_id, key))
        self._ensure_level(agent_id, "household_finance", 1, tick, "genesis")
        occupation_skill = self._occupation_skill(str(agent["occupation"] or ""))
        if occupation_skill:
            self._ensure_level(agent_id, occupation_skill, 1, tick, "occupation")
        if founder:
            self._ensure_level(agent_id, "entrepreneurship", 2, tick, "founder")
        role_skill = ROLE_SKILLS.get(str(agent["role"] or ""))
        if role_skill:
            self._ensure_level(agent_id, role_skill, 3, tick, "institutional_specialist")

    def _ensure_level(self, agent_id: int, skill_key: str, target_level: int,
                      tick: int, source: str) -> None:
        target_level = max(0, min(5, int(target_level)))
        target_xp = XP_THRESHOLDS[target_level]
        row = self.store.query_one(
            "SELECT xp,level FROM agent_skills WHERE agent_id=? AND skill_key=?",
            (agent_id, skill_key))
        old_xp = int(row["xp"] if row else 0)
        old_level = int(row["level"] if row else 0)
        if old_level >= target_level and old_xp >= target_xp:
            return
        new_xp = max(old_xp, target_xp)
        new_level = level_for_xp(new_xp)
        self.store.execute(
            "UPDATE agent_skills SET xp=?,level=?,last_practiced_tick=?,source=? "
            "WHERE agent_id=? AND skill_key=?",
            (new_xp, new_level, tick, source, agent_id, skill_key))
        self.store.insert(
            "agent_skill_history", tick=tick, agent_id=agent_id,
            skill_key=skill_key, old_level=old_level, new_level=new_level,
            xp_delta=new_xp - old_xp, new_xp=new_xp, source=source)

    def _exact_initial_tiers(self, citizens: list) -> dict[int, str]:
        distribution = {
            tier: max(0.0, float(self.p.get("initial_distribution", {}).get(tier, 0.0)))
            for tier in PLAN_TIERS
        }
        total_weight = sum(distribution.values()) or 1.0
        raw = {tier: len(citizens) * distribution[tier] / total_weight for tier in PLAN_TIERS}
        counts = {tier: int(raw[tier]) for tier in PLAN_TIERS}
        remaining = len(citizens) - sum(counts.values())
        order = sorted(PLAN_TIERS, key=lambda tier: (-(raw[tier] - counts[tier]), PLAN_TIERS.index(tier)))
        for tier in order[:remaining]:
            counts[tier] += 1
        ranked = sorted(citizens, key=lambda row: self._stable_rank(int(row["id"])))
        assigned: dict[int, str] = {}
        offset = 0
        for tier in PLAN_TIERS:
            for row in ranked[offset:offset + counts[tier]]:
                assigned[int(row["id"])] = tier
            offset += counts[tier]
        return assigned

    def _stable_rank(self, agent_id: int) -> str:
        return hashlib.sha256(f"{self.seed}:compute:{agent_id}".encode("utf-8")).hexdigest()

    def _hashed_initial_tier(self, agent_id: int) -> str:
        bucket = int(self._stable_rank(agent_id)[:12], 16) / float(16 ** 12)
        local_share = float(self.p.get("initial_distribution", {}).get("local", 0.5))
        flash_share = float(self.p.get("initial_distribution", {}).get("flash", 0.4))
        if bucket < local_share:
            return "local"
        if bucket < local_share + flash_share:
            return "flash"
        return "premium"

    @staticmethod
    def _occupation_skill(occupation: str) -> str:
        lowered = occupation.lower()
        for skill, keywords in OCCUPATION_SKILL_KEYWORDS:
            if any(keyword in lowered for keyword in keywords):
                return skill
        return "labor" if lowered else ""

    @staticmethod
    def _institutional_tier(role: str) -> str | None:
        if role in PREMIUM_INSTITUTIONAL_ROLES:
            return "premium"
        if role in ROUTINE_INSTITUTIONAL_ROLES:
            return "flash"
        return None

    def _seed_subscription(self, agent_id: int, tier: str, tick: int,
                           payer_type: str, payer_id: int | None,
                           payer_account_id: int | None, reason: str) -> None:
        if self.store.query_one(
                "SELECT 1 FROM compute_subscriptions WHERE agent_id=? LIMIT 1",
                (agent_id,)):
            return
        self.store.insert(
            "compute_subscriptions", agent_id=agent_id, tier=tier,
            payer_type=payer_type, payer_id=payer_id,
            payer_account_id=payer_account_id, price_cents=0,
            created_tick=tick, effective_tick=tick,
            expiry_tick=tick + self.duration_ticks, status="active", reason=reason)
        self.store.update("agents", agent_id, model_tier=tier)

    # -- subscriptions ---------------------------------------------------------
    def current_subscription(self, agent_id: int, tick: int | None = None):
        if not self.enabled:
            return None
        at_tick = self.store.tick if tick is None else int(tick)
        return self.store.query_one(
            "SELECT * FROM compute_subscriptions WHERE agent_id=? AND status='active' "
            "AND effective_tick<=? AND expiry_tick>? ORDER BY effective_tick DESC,id DESC LIMIT 1",
            (agent_id, at_tick, at_tick))

    def current_tier(self, agent_id: int) -> str:
        value = self.store.scalar(
            "SELECT model_tier FROM agents WHERE id=?", (agent_id,), default="local")
        return normalize_model_tier(value)

    def buy_compute_plan(self, tick: int, agent_id: int, tier: str) -> dict:
        if not self.enabled:
            return {"ok": False, "reason": "compute plans require semantics 11"}
        tier = str(tier or "").lower().strip()
        if tier not in {"flash", "premium"}:
            return {"ok": False, "reason": "tier must be flash or premium"}
        unavailable = self._plan_change_unavailable(tick, agent_id)
        if unavailable:
            return {"ok": False, "reason": unavailable}
        eligibility = self._tier_eligibility(agent_id, tier)
        if eligibility:
            return {"ok": False, "reason": eligibility}
        cost = self._plan_cost(tier)
        checking = self.ledger.agent_checking_id(agent_id)
        if checking is None or self.ledger.balance(checking) < cost:
            return {"ok": False, "reason": "insufficient funds for compute plan"}
        compute_account = self._system_account_for_source(SYS_COMPUTE, checking)
        self.ledger.transfer(
            tick, checking, compute_account, cost, kind="compute_subscription",
            memo=f"{tier} compute plan for agent {agent_id}")
        subscription_id = self._schedule_subscription(
            tick, agent_id, tier, "agent", agent_id, checking, cost,
            "self_purchased")
        self.store.log_event(
            tick, "compute_plan_purchased",
            {"agent_id": agent_id, "tier": tier, "price_cents": cost,
             "subscription_id": subscription_id, "effective_tick": tick + 1},
            phase="EXECUTION", subject_type="agent", subject_id=agent_id, importance=1.2)
        return {"ok": True, "subscription_id": subscription_id,
                "tier": tier, "effective_tick": tick + 1,
                "expiry_tick": tick + 1 + self.duration_ticks,
                "price_cents": cost}

    def cancel_compute_plan(self, tick: int, agent_id: int) -> dict:
        if not self.enabled:
            return {"ok": False, "reason": "compute plans require semantics 11"}
        if self.current_tier(agent_id) == "local":
            return {"ok": False, "reason": "agent already uses the free local plan"}
        unavailable = self._plan_change_unavailable(tick, agent_id)
        if unavailable:
            return {"ok": False, "reason": unavailable}
        checking = self.ledger.agent_checking_id(agent_id)
        subscription_id = self._schedule_subscription(
            tick, agent_id, "local", "agent", agent_id, checking, 0,
            "self_cancelled")
        self.store.log_event(
            tick, "compute_plan_cancelled",
            {"agent_id": agent_id, "subscription_id": subscription_id,
             "effective_tick": tick + 1},
            phase="EXECUTION", subject_type="agent", subject_id=agent_id, importance=1.0)
        return {"ok": True, "subscription_id": subscription_id,
                "tier": "local", "effective_tick": tick + 1}

    def set_compute_sponsorship(self, tick: int, founder_id: int, tier: str,
                                max_seats: int, firm_id: int | None = None) -> dict:
        if not self.enabled:
            return {"ok": False, "reason": "compute sponsorship requires semantics 11"}
        tier = str(tier or "").lower().strip()
        if tier not in {"flash", "premium"}:
            return {"ok": False, "reason": "sponsorship tier must be flash or premium"}
        max_seats = int(max_seats)
        if max_seats < 1 or max_seats > 25:
            return {"ok": False, "reason": "max_seats must be between 1 and 25"}
        if firm_id:
            firm = self.store.query_one(
                "SELECT id,founder_agent_id,account_id FROM firms "
                "WHERE id=? AND status<>'bankrupt'", (int(firm_id),))
        else:
            firm = self.store.query_one(
                "SELECT id,founder_agent_id,account_id FROM firms "
                "WHERE founder_agent_id=? AND status<>'bankrupt' ORDER BY id LIMIT 1",
                (founder_id,))
        if not firm or int(firm["founder_agent_id"] or 0) != founder_id:
            return {"ok": False, "reason": "actor is not an authorized firm founder"}
        selected = self._eligible_sponsorship_employee_ids(
            tick, int(firm["id"]), tier, max_seats)
        if not selected:
            return {"ok": False, "reason": "no employees are eligible at a renewal boundary"}
        cost_each = self._plan_cost(tier)
        total = cost_each * len(selected)
        firm_account = int(firm["account_id"])
        if self.ledger.balance(firm_account) < total:
            return {"ok": False, "reason": "firm has insufficient operating cash"}
        compute_account = self._system_account_for_source(SYS_COMPUTE, firm_account)
        self.ledger.transfer(
            tick, firm_account, compute_account, total, kind="compute_sponsorship",
            memo=f"{tier} sponsorship for {len(selected)} employees")
        subscription_ids = [
            self._schedule_subscription(
                tick, employee_id, tier, "firm", int(firm["id"]), firm_account,
                cost_each, "employer_sponsored")
            for employee_id in selected
        ]
        self.store.log_event(
            tick, "compute_sponsorship_set",
            {"founder_agent_id": founder_id, "firm_id": int(firm["id"]),
             "tier": tier, "agent_ids": selected, "price_cents": total,
             "effective_tick": tick + 1},
            phase="EXECUTION", subject_type="firm", subject_id=int(firm["id"]),
            importance=1.5)
        return {"ok": True, "firm_id": int(firm["id"]), "tier": tier,
                "agent_ids": selected, "subscription_ids": subscription_ids,
                "price_cents": total, "effective_tick": tick + 1}

    def _eligible_sponsorship_employee_ids(
            self, tick: int, firm_id: int, tier: str, max_seats: int) -> list[int]:
        candidates = self.store.query(
            "SELECT DISTINCT a.id FROM employments e JOIN agents a ON a.id=e.agent_id "
            "WHERE e.firm_id=? AND e.status='active' AND a.alive=1 ORDER BY e.start_tick,a.id",
            (int(firm_id),))
        selected: list[int] = []
        premium_seats_available = self._premium_new_seats_available() if tier == "premium" else 0
        for row in candidates:
            candidate_id = int(row["id"])
            if self._plan_change_unavailable(tick, candidate_id):
                continue
            if self._tier_eligibility(candidate_id, tier):
                continue
            consumes_new_premium_seat = (
                tier == "premium" and self.current_tier(candidate_id) != "premium")
            if consumes_new_premium_seat and premium_seats_available <= 0:
                continue
            selected.append(candidate_id)
            if consumes_new_premium_seat:
                premium_seats_available -= 1
            if len(selected) >= max_seats:
                break
        return selected

    def _plan_change_unavailable(self, tick: int, agent_id: int) -> str:
        if self.store.query_one(
                "SELECT 1 FROM compute_subscriptions WHERE agent_id=? AND status='pending' LIMIT 1",
                (agent_id,)):
            return "a compute plan change is already pending"
        current = self.current_subscription(agent_id, tick)
        if current and int(current["expiry_tick"]) != tick + 1:
            return f"compute plan is locked until renewal tick {int(current['expiry_tick'])}"
        return ""

    def _tier_eligibility(self, agent_id: int, tier: str) -> str:
        if tier != "premium":
            return ""
        highest = int(self.store.scalar(
            "SELECT COALESCE(MAX(level),0) FROM agent_skills "
            "WHERE agent_id=? AND skill_key<>'household_finance'",
            (agent_id,), default=0))
        if highest < 3:
            return "premium requires level 3 in a non-household skill"
        agent = self.store.query_one("SELECT kind,role FROM agents WHERE id=?", (agent_id,))
        if not agent or str(agent["kind"]) != "citizen" or agent["role"]:
            return ""
        population = int(self.store.scalar(
            "SELECT COUNT(*) FROM agents WHERE alive=1 AND kind='citizen' AND role IS NULL",
            default=0))
        cap = max(0, int(population * float(self.p["premium_cap_fraction"])))
        current_or_pending = int(self.store.scalar(
            "SELECT COUNT(DISTINCT s.agent_id) FROM compute_subscriptions s "
            "JOIN agents a ON a.id=s.agent_id "
            "WHERE s.tier='premium' AND s.status IN ('active','pending') "
            "AND a.alive=1 AND a.kind='citizen' AND a.role IS NULL",
            default=0))
        already_premium = self.current_tier(agent_id) == "premium"
        if not already_premium and current_or_pending >= cap:
            return "non-institutional premium seat cap reached"
        return ""

    def _premium_new_seats_available(self) -> int:
        population = int(self.store.scalar(
            "SELECT COUNT(*) FROM agents WHERE alive=1 AND kind='citizen' AND role IS NULL",
            default=0))
        cap = max(0, int(population * float(self.p["premium_cap_fraction"])))
        occupied = int(self.store.scalar(
            "SELECT COUNT(DISTINCT s.agent_id) FROM compute_subscriptions s "
            "JOIN agents a ON a.id=s.agent_id "
            "WHERE s.tier='premium' AND s.status IN ('active','pending') "
            "AND a.alive=1 AND a.kind='citizen' AND a.role IS NULL",
            default=0))
        return max(0, cap - occupied)

    def _schedule_subscription(self, tick: int, agent_id: int, tier: str,
                               payer_type: str, payer_id: int | None,
                               payer_account_id: int | None, price_cents: int,
                               reason: str) -> int:
        return self.store.insert(
            "compute_subscriptions", agent_id=agent_id, tier=tier,
            payer_type=payer_type, payer_id=payer_id,
            payer_account_id=payer_account_id, price_cents=price_cents,
            created_tick=tick, effective_tick=tick + 1,
            expiry_tick=tick + 1 + self.duration_ticks,
            status="pending", reason=reason)

    def _plan_cost(self, tier: str) -> int:
        if tier == "premium":
            return max(0, int(self.p["premium_cost_cents"]))
        if tier == "flash":
            return max(0, int(self.p["flash_cost_cents"]))
        return 0

    def _system_account_for_source(self, label: str, source_account_id: int) -> int:
        currency = str(self.store.scalar(
            "SELECT currency_code FROM accounts WHERE id=?", (source_account_id,),
            default="USD") or "USD")
        return self.ledger.system_account(label, currency_code=currency)

    def run_nightly(self, tick: int) -> None:
        if not self.enabled:
            return
        expiring = self.store.query(
            "SELECT id,agent_id,tier FROM compute_subscriptions "
            "WHERE status='active' AND expiry_tick<=? ORDER BY agent_id,id", (tick,))
        previous_tiers = {
            int(row["agent_id"]): self.current_tier(int(row["agent_id"]))
            for row in expiring
        }
        for row in expiring:
            self.store.execute(
                "UPDATE compute_subscriptions SET status='expired' WHERE id=?", (int(row["id"]),))
            self.store.update("agents", int(row["agent_id"]), model_tier="local")
        pending = self.store.query(
            "SELECT * FROM compute_subscriptions WHERE status='pending' "
            "AND effective_tick<=? ORDER BY agent_id,id", (tick,))
        activated_ids: set[int] = set()
        for row in pending:
            agent_id = int(row["agent_id"])
            activated_ids.add(agent_id)
            old_tier = previous_tiers.get(agent_id, self.current_tier(agent_id))
            self.store.execute(
                "UPDATE compute_subscriptions SET status='expired' "
                "WHERE agent_id=? AND status='active'", (agent_id,))
            self.store.execute(
                "UPDATE compute_subscriptions SET status='active' WHERE id=?", (int(row["id"]),))
            new_tier = str(row["tier"])
            self.store.update("agents", agent_id, model_tier=new_tier)
            self._log_plan_change(tick, agent_id, old_tier, new_tier, int(row["id"]),
                                  "scheduled_activation")
        for agent_id, old_tier in sorted(previous_tiers.items()):
            if agent_id in activated_ids:
                continue
            agent = self.store.query_one(
                "SELECT alive,role FROM agents WHERE id=?", (agent_id,))
            if (not agent or not bool(agent["alive"])
                    or self._institutional_tier(str(agent["role"] or ""))):
                continue
            subscription_id = self.store.insert(
                "compute_subscriptions", agent_id=agent_id, tier="local",
                payer_type="free", payer_id=None, payer_account_id=None,
                price_cents=0, created_tick=tick, effective_tick=tick,
                expiry_tick=tick + self.duration_ticks, status="active",
                reason="free_local_renewal")
            self.store.update("agents", agent_id, model_tier="local")
            if old_tier != "local":
                self._log_plan_change(
                    tick, agent_id, old_tier, "local", subscription_id,
                    "subscription_expired")
        self._renew_institutional_sponsorships(tick, previous_tiers)

    def _renew_institutional_sponsorships(
            self, tick: int, previous_tiers: dict[int, str] | None = None) -> None:
        agents = self.store.query(
            "SELECT id,role FROM agents WHERE alive=1 AND role IS NOT NULL ORDER BY id")
        government = self.ledger.system_account(SYS_GOV)
        for agent in agents:
            agent_id = int(agent["id"])
            tier = self._institutional_tier(str(agent["role"] or ""))
            if not tier:
                continue
            current = self.current_subscription(agent_id, tick)
            if current and str(current["tier"]) == tier:
                continue
            if self.store.query_one(
                    "SELECT 1 FROM compute_subscriptions WHERE agent_id=? AND status='pending' LIMIT 1",
                    (agent_id,)):
                continue
            cost = self._plan_cost(tier)
            compute = self._system_account_for_source(SYS_COMPUTE, government)
            if cost:
                self.ledger.transfer(
                    tick, government, compute, cost, kind="public_compute_sponsorship",
                    memo=f"institutional {tier} plan for agent {agent_id}")
            subscription_id = self.store.insert(
                "compute_subscriptions", agent_id=agent_id, tier=tier,
                payer_type="government", payer_id=1, payer_account_id=government,
                price_cents=cost, created_tick=tick, effective_tick=tick,
                expiry_tick=tick + self.duration_ticks, status="active",
                reason="institutional_sponsorship")
            old_tier = (previous_tiers or {}).get(agent_id, self.current_tier(agent_id))
            self.store.update("agents", agent_id, model_tier=tier)
            self._log_plan_change(
                tick, agent_id, old_tier, tier, subscription_id,
                "institutional_renewal")

    def _log_plan_change(self, tick: int, agent_id: int, old_tier: str,
                         new_tier: str, subscription_id: int, reason: str) -> None:
        self.store.log_event(
            tick, "compute_plan_changed",
            {"agent_id": agent_id, "old_tier": old_tier, "new_tier": new_tier,
             "subscription_id": subscription_id, "reason": reason},
            phase="NIGHT_CLOSE", subject_type="agent", subject_id=agent_id,
            importance=1.2)

    # -- skill progression -----------------------------------------------------
    def record_accepted_action(self, tick: int, agent_id: int, action_type: str,
                               *, proposal_id: int | None = None) -> None:
        if not self.enabled or action_type in {"do_nothing", "study_skill"}:
            return
        skill_key = ACTION_SKILLS.get(action_type, "household_finance")
        xp_delta = 4 if action_type in COMPLEX_ACTIONS else 2
        suffix = f":{int(proposal_id)}" if proposal_id is not None else ""
        self.award_xp(
            tick, agent_id, skill_key, xp_delta,
            f"action:{action_type}{suffix}")

    def award_xp(self, tick: int, agent_id: int, skill_key: str,
                 xp_delta: int, source: str) -> dict:
        if not self.enabled or skill_key not in SKILL_KEYS or xp_delta <= 0:
            return {"ok": False, "reason": "invalid skill award"}
        self.store.execute(
            "INSERT OR IGNORE INTO agent_skills"
            "(agent_id,skill_key,xp,level,last_practiced_tick,source) "
            "VALUES (?,?,0,0,NULL,'late_seed')", (agent_id, skill_key))
        row = self.store.query_one(
            "SELECT xp,level FROM agent_skills WHERE agent_id=? AND skill_key=?",
            (agent_id, skill_key))
        old_xp = int(row["xp"])
        old_level = int(row["level"])
        new_xp = old_xp + int(xp_delta)
        new_level = level_for_xp(new_xp)
        self.store.execute(
            "UPDATE agent_skills SET xp=?,level=?,last_practiced_tick=?,source=? "
            "WHERE agent_id=? AND skill_key=?",
            (new_xp, new_level, tick, source, agent_id, skill_key))
        history_id = self.store.insert(
            "agent_skill_history", tick=tick, agent_id=agent_id,
            skill_key=skill_key, old_level=old_level, new_level=new_level,
            xp_delta=int(xp_delta), new_xp=new_xp, source=source)
        if new_level != old_level:
            self.store.log_event(
                tick, "skill_level_changed",
                {"agent_id": agent_id, "skill_key": skill_key,
                 "old_level": old_level, "new_level": new_level,
                 "new_xp": new_xp, "history_id": history_id},
                phase="EXECUTION", subject_type="agent", subject_id=agent_id,
                importance=1.3)
        return {"ok": True, "skill_key": skill_key, "xp_delta": int(xp_delta),
                "xp": new_xp, "level": new_level, "history_id": history_id}

    def study_skill(self, tick: int, agent_id: int, skill_key: str, *,
                    proposal_id: int | None = None) -> dict:
        if not self.enabled:
            return {"ok": False, "reason": "skills require semantics 11"}
        skill_key = str(skill_key or "").lower().strip()
        if skill_key not in SKILL_KEYS:
            return {"ok": False, "reason": "unknown skill_key"}
        if not self.is_career_review_day(agent_id, tick):
            return {"ok": False, "reason": "study_skill is available only on career-review days"}
        cost = max(0, int(self.p["study_cost_cents"]))
        checking = self.ledger.agent_checking_id(agent_id)
        if checking is None or self.ledger.balance(checking) < cost:
            return {"ok": False, "reason": "insufficient funds for study"}
        education = self._system_account_for_source(SYS_EDUCATION, checking)
        if cost:
            self.ledger.transfer(
                tick, checking, education, cost, kind="skill_study",
                memo=f"study {skill_key}")
        source = f"study:{int(proposal_id)}" if proposal_id is not None else "study"
        progress = self.award_xp(tick, agent_id, skill_key, 10, source)
        self.store.log_event(
            tick, "skill_studied",
            {"agent_id": agent_id, "skill_key": skill_key,
             "price_cents": cost, "xp_delta": 10},
            phase="EXECUTION", subject_type="agent", subject_id=agent_id,
            importance=1.0)
        return {"ok": True, "price_cents": cost, **{
            key: value for key, value in progress.items() if key != "ok"}}

    def is_career_review_day(self, agent_id: int, tick: int) -> bool:
        raw = self.store.scalar(
            "SELECT cadence_json FROM agents WHERE id=?", (agent_id,), default="{}")
        try:
            cadence = json.loads(raw or "{}")
        except (TypeError, ValueError):
            cadence = {}
        every = max(1, int(cadence.get("career", 30)))
        return int(tick) % every == int(agent_id) % every

    # -- prompt/API projections ------------------------------------------------
    def decision_context(self, agent_id: int, tick: int) -> dict[str, Any]:
        if not self.enabled:
            return {}
        details = self.agent_projection(agent_id, include_history=False, tick=tick)
        renewal_open = not self._plan_change_unavailable(tick, agent_id)
        offers = []
        if renewal_open:
            for tier in ("flash", "premium"):
                reason = self._tier_eligibility(agent_id, tier)
                offers.append({
                    "tier": tier,
                    "price_cents": self._plan_cost(tier),
                    "duration_ticks": self.duration_ticks,
                    "eligible": not bool(reason),
                    "ineligible_reason": reason or None,
                    "action": {"type": "buy_compute_plan", "tier": tier},
                })
        study = []
        if self.is_career_review_day(agent_id, tick):
            study = [{
                "skill_key": key,
                "price_cents": int(self.p["study_cost_cents"]),
                "xp_gain": 10,
                "action": {"type": "study_skill", "skill_key": key},
            } for key in SKILL_KEYS]
        founder = self.store.query_one(
            "SELECT id,account_id FROM firms WHERE founder_agent_id=? AND status<>'bankrupt' "
            "ORDER BY id LIMIT 1", (agent_id,))
        sponsorship_actions = []
        if founder:
            firm_id = int(founder["id"])
            firm_cash = self.ledger.balance(int(founder["account_id"]))
            for tier in ("flash", "premium"):
                if (firm_cash >= self._plan_cost(tier)
                        and self._eligible_sponsorship_employee_ids(
                            tick, firm_id, tier, 1)):
                    sponsorship_actions.append({
                        "type": "set_compute_sponsorship", "tier": tier,
                        "max_seats": 1, "firm_id": firm_id,
                    })
        return {
            "compute_plan": details["compute_plan"],
            "skills": details["skills"],
            "compute_plan_offers": offers,
            "compute_plan_cancel_action": (
                {"type": "cancel_compute_plan"}
                if renewal_open and details["compute_plan"]["tier"] != "local" else None),
            "study_skill_options": study,
            "compute_sponsorship": ({
                "firm_id": int(founder["id"]),
                "max_seats_limit": 25,
                "actions": sponsorship_actions,
            } if sponsorship_actions else None),
        }

    def agent_projection(self, agent_id: int, *, include_history: bool = True,
                         tick: int | None = None) -> dict[str, Any]:
        tier = self.current_tier(agent_id)
        subscription = self.current_subscription(agent_id, tick)
        plan = {
            "tier": tier,
            "payer_type": str(subscription["payer_type"]) if subscription else "free",
            "payer_id": int(subscription["payer_id"]) if subscription and subscription["payer_id"] is not None else None,
            "price_cents": int(subscription["price_cents"]) if subscription else 0,
            "effective_tick": int(subscription["effective_tick"]) if subscription else None,
            "expiry_tick": int(subscription["expiry_tick"]) if subscription else None,
            "status": str(subscription["status"]) if subscription else "free",
        }
        skills = [dict(row) for row in self.store.query(
            "SELECT skill_key,xp,level,last_practiced_tick,source FROM agent_skills "
            "WHERE agent_id=? ORDER BY skill_key", (agent_id,))]
        result: dict[str, Any] = {"compute_plan": plan, "skills": skills}
        if include_history:
            result["skill_history"] = [dict(row) for row in self.store.query(
                "SELECT id,tick,skill_key,old_level,new_level,xp_delta,new_xp,source "
                "FROM agent_skill_history WHERE agent_id=? ORDER BY tick,id", (agent_id,))]
            result["subscription_history"] = [dict(row) for row in self.store.query(
                "SELECT id,tier,payer_type,payer_id,price_cents,created_tick,effective_tick,"
                "expiry_tick,status,reason FROM compute_subscriptions "
                "WHERE agent_id=? ORDER BY created_tick,id", (agent_id,))]
        return result
