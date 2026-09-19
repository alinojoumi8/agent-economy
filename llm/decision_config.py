"""Strict opt-in routing contract for bounded economic choices."""
from __future__ import annotations

from .decisions import finite_number


POLICY_VERSION = "bounded-economic-choice-v1"
POLICY_VERSION_V2 = "bounded-economic-choice-v2"
POLICY_VERSION_V3 = "bounded-economic-choice-v3"
POLICY_VERSION_V4 = "bounded-economic-choice-v4"
POLICY_VERSIONS = {POLICY_VERSION, POLICY_VERSION_V2, POLICY_VERSION_V3, POLICY_VERSION_V4}


def decision_policy(config: dict) -> dict | None:
    raw = config.get("llm", {}).get("decision_policy")
    if raw is None:
        return None
    allowed = {"version", "primary", "escalation", "minimum_confidence", "on_abstain",
               "population_fraction", "eligible_tiers", "activation_tick", "max_goods_offers",
               "max_job_options", "max_quantity", "spending_bps", "max_output_tokens"}
    if isinstance(raw, dict) and raw.get("version") == POLICY_VERSION_V4:
        allowed |= {"domains", "services", "max_candidates", "price_steps_bps", "investment_bps",
                    "max_investment_quantity", "firm_reserve_payrolls", "strategic_review_interval_ticks"}
    if not isinstance(raw, dict) or set(raw) - allowed or raw.get("version") not in POLICY_VERSIONS:
        raise ValueError("decision_policy requires a known bounded-economic-choice contract and known fields")
    if int(config.get("engine_semantics_version", 1)) < 16:
        raise ValueError("typed decision policies require prospective Semantics 16 or later")
    value = {"minimum_confidence": 0.0, "on_abstain": "wait", "population_fraction": 1.0,
             "eligible_tiers": ["legacy", "local", "flash", "premium"], "activation_tick": 1,
             "max_goods_offers": 4, "max_job_options": 3, "max_quantity": 8,
             "spending_bps": 2000, "max_output_tokens": 2048, **raw}
    if value["version"] == POLICY_VERSION_V4:
        from agents.decision_domains import DOMAINS, SELECTION_SERVICES
        value = {"domains": [], "services": [], "max_candidates": 64,
                 "price_steps_bps": [-500, 0, 500], "investment_bps": 2500,
                 "max_investment_quantity": 5, "firm_reserve_payrolls": 1,
                 "strategic_review_interval_ticks": 7, **value}
        for field, names in (("domains", set(DOMAINS) - {"judgments"}), ("services", SELECTION_SERVICES)):
            selected = value[field]
            if (not isinstance(selected, list) or any(not isinstance(s, str) or s not in names for s in selected)
                    or len(set(selected)) != len(selected)):
                raise ValueError(f"decision_policy.{field} must contain distinct supported names")
        if "commons" in value["services"] and int(config.get("engine_semantics_version", 1)) < 20:
            raise ValueError("Commons selection requires Semantics 20+ reaction idempotence")
        for field, lo, hi in (("max_candidates", 3, 64), ("investment_bps", 1, 10000),
                              ("max_investment_quantity", 1, 100), ("firm_reserve_payrolls", 1, 12),
                              ("strategic_review_interval_ticks", 0, 365)):
            if type(value[field]) is not int or not lo <= value[field] <= hi:
                raise ValueError(f"decision_policy.{field} is outside its bounded integer range")
        steps = value["price_steps_bps"]
        if (not isinstance(steps, list) or not 1 <= len(steps) <= 7 or 0 not in steps
                or any(type(s) is not int or not -2000 <= s <= 2000 for s in steps)
                or steps != sorted(set(steps))):
            raise ValueError("price_steps_bps must be sorted distinct bounded changes including zero")
    for field in ("primary", "escalation"):
        route = value.get(field)
        if field == "escalation" and route is None:
            continue
        if (not isinstance(route, dict) or set(route) - {"provider", "model", "timeout_s"}
                or any(not isinstance(route.get(k), str) or not route[k].strip()
                       for k in ("provider", "model"))):
            raise ValueError(f"decision_policy.{field} requires one explicit provider/model route")
        if "timeout_s" in route and not finite_number(route["timeout_s"], .01, 600):
            raise ValueError("typed route timeout must be positive and at most 600 seconds")
    if value["on_abstain"] not in {"wait", "escalate"}:
        raise ValueError("typed abstention must be wait or a declared escalation")
    if value["on_abstain"] == "escalate" and value.get("escalation") is None:
        raise ValueError("typed escalation requires its explicit route")
    for field in ("minimum_confidence", "population_fraction"):
        if not finite_number(value[field], 0, 1):
            raise ValueError(f"decision_policy.{field} must be between zero and one")
    if (not isinstance(value["eligible_tiers"], list) or not value["eligible_tiers"]
            or any(tier not in {"legacy", "local", "flash", "premium"} for tier in value["eligible_tiers"])
            or len(set(value["eligible_tiers"])) != len(value["eligible_tiers"])):
        raise ValueError("typed policy must declare distinct eligible compute tiers")
    for field, lower, upper in (("activation_tick", 1, 10**9), ("max_goods_offers", 1, 6),
                               ("max_job_options", 1, 6), ("max_quantity", 1, 8),
                               ("spending_bps", 1, 10000), ("max_output_tokens", 128, 8192)):
        if type(value[field]) is not int or not lower <= value[field] <= upper:
            raise ValueError(f"decision_policy.{field} is outside its bounded integer range")
    return value
