"""Scripted decision policies (deterministic, no LLM).

These make the world *do things* without any API key and reproducibly (build-order
step 1: prove the economy before involving an LLM). Each policy takes the same
structured `context` the prompt builder assembles and returns a valid decision
envelope {reasoning, actions, belief_updates}. Behaviour is seeded per (agent,
tick) so runs replay identically.

The citizen policy also implements the belief→behaviour channel the rumor pilot
needs: when trust in an agent's bank falls below a threshold, it moves its deposits
out — a bank run emerging from beliefs, not a hard-coded rule tying rumor→outflow.
"""
from __future__ import annotations

import random
import re
from typing import Any, Callable


def _rng(context: dict) -> random.Random:
    return random.Random(int(context.get("rng_seed", 0)))


def _env(payload: dict, actions: list, beliefs: list | None = None, reasoning: str = "") -> dict:
    return {"reasoning": reasoning, "actions": actions or [{"type": "do_nothing"}],
            "belief_updates": beliefs or []}


# ─────────────────────────────────────────────────────────────────────────────
# Citizens / households
# ─────────────────────────────────────────────────────────────────────────────
def citizen_decision(context: dict) -> dict:
    rng = _rng(context)
    agent = context.get("agent", {})
    state = context.get("state", {})
    beliefs = dict(context.get("beliefs", {}))
    actions: list[dict] = []
    belief_updates: list[dict] = []
    reasons: list[str] = []

    health = agent.get("health", "healthy")
    cash = int(state.get("checking_balance", 0))
    run_threshold = float(context.get("run_threshold", 0.35))

    # 1) React to news: shift sentiment + inflation expectation.
    sentiment = float(beliefs.get("sentiment", 0.0))
    infl = float(beliefs.get("inflation_expectation", 0.02))
    for item in context.get("news", []):
        tone = float(item.get("tone", 0.0))          # -1 negative .. +1 positive
        sentiment += 0.06 * tone
        if item.get("mentions_inflation"):
            infl += 0.004
    # 2) Process things heard (conversations / rumors) into beliefs.
    for heard in context.get("heard", []):
        bank_id = heard.get("rumor_bank")
        if bank_id is not None:
            key = f"trust:bank:{bank_id}"
            beliefs[key] = max(0.0, float(beliefs.get(key, 0.6)) - 0.25)
            belief_updates.append({"key": key, "value": round(beliefs[key], 3)})
            sentiment -= 0.05
            reasons.append(f"heard worrying talk about bank {bank_id}")
    sentiment = max(-1.0, min(1.0, sentiment))
    belief_updates.append({"key": "sentiment", "value": round(sentiment, 3)})
    belief_updates.append({"key": "inflation_expectation", "value": round(min(0.25, max(-0.05, infl)), 4)})

    # 3) Bank run: if trust in my bank collapsed, move deposits somewhere safer.
    my_bank = state.get("bank_id")
    ran = False
    if my_bank is not None:
        trust = float(beliefs.get(f"trust:bank:{my_bank}", 0.6))
        if trust <= run_threshold and cash > 0:
            safe = _safest_other_bank(context, my_bank)
            if safe is not None:
                actions.append({"type": "move_deposits", "to_bank_id": safe})
                reasons.append(f"pulling deposits from bank {my_bank} (trust {trust:.2f})")
                ran = True

    # 4) Consumption: buy goods (unless critically ill). Households with dependents buy more.
    if health != "critical" and not ran:
        firm = _cheapest_stocked_firm(context)
        if firm and cash > firm["price"] * 2:
            budget = int(cash * (0.12 + 0.03 * int(agent.get("dependents", 0))))
            qty = max(1, min(budget // max(1, firm["price"]), firm["inventory"], 8))
            if qty > 0:
                actions.append({"type": "buy_goods", "firm_id": firm["firm_id"], "qty": qty})
                reasons.append(f"buying {qty} {firm['product']}")

    # 4.5) Health insurance: cautious or older agents cover themselves (R17).
    if not ran and health == "healthy" and not context.get("insured"):
        offer = context.get("insurance_offer")
        if offer:
            premium = int(offer.get("premium", 3000))
            cautious = float(agent.get("risk_tolerance", 0.5)) < 0.45 or int(agent.get("age", 30)) >= 50
            if cautious and cash > premium * 8:
                actions.append({"type": "buy_insurance"})
                reasons.append("buying health coverage")

    # 5) Labour: unemployed & working-age → apply to the best open job.
    if not state.get("employed") and not agent.get("retired") and health == "healthy":
        jobs = sorted(context.get("jobs", []), key=lambda j: -int(j.get("wage", 0)))
        if jobs:
            actions.append({"type": "apply_job", "job_id": jobs[0]["job_id"]})
            reasons.append("seeking work")

    # 6) Portfolio: act on sentiment occasionally (weekly-ish cadence gate upstream).
    if context.get("portfolio_day") and health == "healthy" and not ran:
        listed = context.get("listed_firms", [])
        if listed and cash > 50_000:
            pick = rng.choice(listed)
            price = int(pick.get("last_price") or 10000)
            if sentiment > 0.15 and cash > price * 3:
                qty = max(1, min(5, cash // (price * 4)))
                actions.append({"type": "place_order", "firm_id": pick["firm_id"], "side": "buy",
                                "qty": qty, "limit_price": int(price * 1.02)})
                reasons.append("bullish: buying equities")
            elif sentiment < -0.15 and int(state.get("shares", {}).get(str(pick["firm_id"]), 0)) > 0:
                held = int(state["shares"][str(pick["firm_id"])])
                actions.append({"type": "place_order", "firm_id": pick["firm_id"], "side": "sell",
                                "qty": min(held, 5), "limit_price": int(price * 0.98)})
                reasons.append("bearish: trimming equities")

    if not actions:
        actions.append({"type": "do_nothing"})
    return _env(None, actions, belief_updates, "; ".join(reasons) or "quiet day")


def _cheapest_stocked_firm(context: dict):
    firms = [f for f in context.get("prices", []) if int(f.get("inventory", 0)) > 0 and int(f.get("price", 0)) > 0]
    return min(firms, key=lambda f: f["price"]) if firms else None


def _safest_other_bank(context: dict, my_bank: int):
    banks = [b for b in context.get("banks", []) if b.get("status") == "open" and b["id"] != my_bank]
    if not banks:
        return None
    return max(banks, key=lambda b: b.get("reserve_ratio", 0.0))["id"]


# ─────────────────────────────────────────────────────────────────────────────
# Firm founders / managers
# ─────────────────────────────────────────────────────────────────────────────
def founder_decision(context: dict) -> dict:
    firm = context.get("my_firm")
    if not firm:
        return citizen_decision(context)
    actions: list[dict] = []
    reasons: list[str] = []
    inv = int(firm.get("inventory", 0))
    price = int(firm.get("price", 500))
    cost = int(firm.get("unit_cost", 180))
    cash = int(firm.get("cash", 0))
    employees = int(firm.get("employees", 0))
    recent_sales = int(firm.get("recent_sales", 0))

    # Price toward a healthy markup, nudged by inventory pressure.
    target = int(cost * 1.6)
    if inv > 40 and recent_sales < inv // 3:
        target = int(price * 0.95)              # overstocked → discount
    elif inv < 8:
        target = int(price * 1.05)              # scarce → raise
    target = max(int(cost * 1.2) + 1, target)   # never below a living margin
    if abs(target - price) > 2:
        actions.append({"type": "set_price", "firm_id": firm["firm_id"], "price": target})
        reasons.append(f"reprice {price}->{target}")

    # Hire if there is demand and we can afford payroll.
    applicants = context.get("firm_applications", [])
    payroll = int(firm.get("payroll", 0))
    if applicants and cash > payroll + 300_00 and employees < int(firm.get("target_headcount", 3)):
        actions.append({"type": "hire", "application_id": applicants[0]["application_id"]})
        reasons.append("hiring")
    elif employees == 0 and cash > 0:
        wage = max(200_00, int(cost * 20))
        actions.append({"type": "post_job", "firm_id": firm["firm_id"], "title": "worker", "wage": wage})
        reasons.append("posting a job")

    # Seek a loan when cash is thin relative to payroll.
    if cash < payroll and not firm.get("has_pending_loan"):
        bank = _pick_bank(context)
        if bank is not None:
            actions.append({"type": "apply_loan", "bank_id": bank, "amount": max(300_00, payroll * 2),
                            "purpose": "working capital", "as_firm": True, "firm_id": firm["firm_id"]})
            reasons.append("applying for working-capital loan")
    # Run a venture round in parallel when bank credit is still pending (R13):
    # a private firm short of cash pitches the VC rather than waiting to die.
    elif (cash < payroll and firm.get("is_private") and firm.get("has_pending_loan")
            and not firm.get("has_pending_pitch")):
        actions.append({"type": "pitch_vc", "firm_id": firm["firm_id"],
                        "ask": max(500_00, payroll * 3),
                        "summary": f"growth capital for {firm.get('name', 'the firm')}"})
        reasons.append("pitching the VC for a round")

    if not actions:
        # Founder still consumes as a household.
        return citizen_decision(context)
    return _env(None, actions, [], "; ".join(reasons))


def _pick_bank(context: dict):
    banks = [b for b in context.get("banks", []) if b.get("status") == "open"]
    return banks[0]["id"] if banks else None


# ─────────────────────────────────────────────────────────────────────────────
# Institutional roles
# ─────────────────────────────────────────────────────────────────────────────
def credit_officer_decision(context: dict) -> dict:
    actions: list[dict] = []
    reasons: list[str] = []
    base_rate = int(context.get("policy_rate_bps", 500))
    for app in context.get("pending_loan_apps", []):
        amount = int(app.get("amount_cents", 0))
        income = int(app.get("borrower_income_cents", 0)) or 1
        net_worth = int(app.get("borrower_net_worth_cents", 0))
        # Simple underwriting: decline if the ask is a large multiple of annual income
        # and the borrower is thin on net worth; otherwise price to risk.
        leverage = amount / max(1, income)
        if leverage > 1.2 and net_worth < amount // 2:
            actions.append({"type": "deny_loan", "application_id": app["id"],
                            "reason": "insufficient capacity"})
            reasons.append(f"deny app {app['id']} (leverage {leverage:.1f})")
        else:
            premium = int(300 + 600 * min(1.0, leverage))
            rate = base_rate + premium
            actions.append({"type": "approve_loan", "application_id": app["id"],
                            "rate_bps": rate, "term_ticks": 360})
            reasons.append(f"approve app {app['id']} @ {rate}bps")
    return _env(None, actions or [{"type": "do_nothing"}], [], "; ".join(reasons) or "no applications")


def vc_partner_decision(context: dict) -> dict:
    """Scripted partner: fund pitches with traction at a risk-priced equity stake,
    keep dry powder, pass on the rest (R13)."""
    actions: list[dict] = []
    reasons: list[str] = []
    fund_cash = int(context.get("fund_cash", 0))
    for p in context.get("pending_pitches", []):
        ask = int(p.get("ask_cents", 0))
        traction = int(p.get("revenue_30", 0)) > 0 or int(p.get("employees", 0)) > 0
        affordable = ask <= int(fund_cash * 0.4) and fund_cash >= ask
        if traction and affordable and ask > 0:
            # Price the round to risk: thinner firm cash vs ask → more equity.
            dilution_pressure = min(1.0, ask / max(1, int(p.get("firm_cash", 0)) + ask))
            equity = 1500 + int(1500 * dilution_pressure)          # 15%–30% post-money
            actions.append({"type": "fund_pitch", "pitch_id": p["pitch_id"],
                            "amount": ask, "equity_bps": equity})
            reasons.append(f"term sheet: pitch {p['pitch_id']} @ {equity}bps")
            fund_cash -= ask
        else:
            why = "no traction" if not traction else "check too large for the fund"
            actions.append({"type": "decline_pitch", "pitch_id": p["pitch_id"], "reason": why})
            reasons.append(f"pass on pitch {p['pitch_id']} ({why})")
    return _env(None, actions or [{"type": "do_nothing"}], [], "; ".join(reasons) or "no pitches today")


def central_banker_decision(context: dict) -> dict:
    m = context.get("metrics", {})
    cur = int(context.get("policy_rate_bps", 500))
    neutral = int(context.get("neutral_rate_bps", 500))
    target_infl = float(context.get("target_inflation", 0.02))
    infl = float(m.get("cpi_yoy", target_infl))
    unemp = float(m.get("unemployment", 0.05))
    natural_unemp = float(context.get("natural_unemployment", 0.05))
    # Taylor rule (guardrailed further by the executor to ±max_step).
    taylor = neutral + int(150 * (infl - target_infl) * 100) - int(100 * (unemp - natural_unemp) * 100)
    step = max(-50, min(50, taylor - cur))
    new_rate = cur + step
    reasoning = f"Taylor: infl={infl:.3f} unemp={unemp:.3f} -> target {taylor}bps, move {step:+d}bps"
    if step == 0:
        return _env(None, [{"type": "do_nothing"}], [], "hold rate; " + reasoning)
    return _env(None, [{"type": "set_policy_rate", "rate_bps": new_rate}], [], reasoning)


def reporter_draft(context: dict) -> dict:
    """Reporter scripted stage: draft up to 3 neutral candidate stories, one per
    distinct salient event kind (TECH-SPEC §10 two-stage desk)."""
    events = context.get("salient_events", [])
    stories = []
    seen_kinds: set = set()
    for e in events:
        kind = e.get("kind", "event")
        if kind in seen_kinds:
            continue
        seen_kinds.add(kind)
        headline, body, tone = _story_template(kind, [e])
        stories.append({"headline": headline, "body": body, "tone": tone, "kind": kind,
                        "source_event_ids": [e["id"]]})
        if len(stories) >= 3:
            break
    return {"stories": stories}


# Kinds the pro-labor desk leads with when available.
_LABOR_KINDS = ("bankruptcy", "wage_missed", "benefits_paid", "election_held",
                "loan_default", "epidemic_started", "bank_failure")


def newsroom_policy(context: dict) -> dict:
    """Editor scripted stage: pick the draft that fits the outlet's slant and
    frame it; composes straight from events when the reporter came back empty."""
    outlet = context.get("outlet", {})
    slant = outlet.get("slant", "neutral")
    drafts = [d for d in context.get("drafts", []) if d.get("headline")]
    events = context.get("salient_events", [])
    if not drafts:
        if not events:
            return {"headline": "", "body": "", "slant_tags": [slant], "source_event_ids": []}
        top = events[0]
        headline, body, tone = _story_template(top.get("kind", "event"), events)
        pick = {"headline": headline, "body": body, "tone": tone,
                "kind": top.get("kind"), "source_event_ids": [e["id"] for e in events[:4]]}
    elif slant == "cautious-pro-labor":
        pick = next((d for d in drafts if d.get("kind") in _LABOR_KINDS), drafts[0])
    else:   # sensational desks chase the most dramatic (most negative) story
        pick = min(drafts, key=lambda d: float(d.get("tone", 0.0)))
    headline, body, tone = _apply_slant(pick["headline"], pick.get("body", ""),
                                        float(pick.get("tone", 0.0)), slant,
                                        n_related=len(events))
    return {"headline": headline, "body": body, "slant_tags": [slant], "tone": tone,
            "source_event_ids": pick.get("source_event_ids", [])}


def _story_template(kind: str, events: list):
    """Neutral story text for an event kind (the reporter's voice)."""
    templates = {
        "bank_failure": ("Bank Collapses as Depositors Flee",
                         "A bank has failed after a wave of withdrawals wiped out its reserves."),
        "rumor": ("Questions Swirl Around a Lender",
                  "Talk is spreading about the soundness of a major bank."),
        "bankruptcy": ("Firm Goes Under", "A company has filed for bankruptcy, shedding jobs."),
        "ipo": ("New Listing Hits the Exchange", "A firm went public today."),
        "policy_rate_set": ("Central Bank Moves Rates", "Policymakers adjusted the benchmark rate."),
        "loan_default": ("Borrower Defaults", "A loan has gone bad, testing lender balance sheets."),
        "death": ("A Notable Passing", "The community marks a death today."),
        "election_held": ("Voters Deliver a Fiscal Verdict",
                          "The election has reset the government's tax-and-benefit course."),
        "benefits_paid": ("Relief Checks Go Out", "Unemployment benefits reached households."),
        "vc_funded": ("Startup Lands Venture Backing", "A private firm closed a funding round."),
        "vc_writeoff": ("Venture Bet Goes to Zero", "An investor wrote off a failed portfolio company."),
        "epidemic_started": ("Illness Sweeps the Town", "Doctors report a surge of new cases."),
        "epidemic_ended": ("Outbreak Subsides", "New cases are back to normal levels."),
        "circuit_breaker": ("Trading Halted After Sharp Slide",
                            "The exchange halted a stock after it plunged past the breaker."),
    }
    base_h, base_b = templates.get(kind, ("Markets in Motion", "Activity picked up across the economy."))
    tone = -0.5 if kind in ("bank_failure", "rumor", "bankruptcy", "loan_default",
                            "epidemic_started", "vc_writeoff", "circuit_breaker") else 0.1
    return base_h, base_b, tone


def _apply_slant(headline: str, body: str, tone: float, slant: str, n_related: int = 1):
    """The editor's framing pass — identical slant voice as v1."""
    if slant == "pro-market-sensational":
        headline = headline.upper() + " — INVESTORS ON EDGE"
        tone -= 0.2
    elif slant == "cautious-pro-labor":
        headline = headline + " (workers weigh the fallout)"
        tone += 0.1
    return headline, body + f" [{n_related} related developments]", tone


def conversation_turn(context: dict) -> dict:
    """One short conversational line. Spreads salient rumors the speaker holds."""
    rumor = context.get("speaker_rumor_bank")
    partner = context.get("partner_name", "a neighbor")
    if rumor is not None:
        return {"text": f"Did you hear? People are pulling money out of bank {rumor}. I'm worried.",
                "rumor_bank": rumor}
    topic = context.get("shared_topic")
    if topic:
        return {"text": f"Quite something about {topic}, isn't it, {partner}?"}
    return {"text": f"Good to see you, {partner}. How's business?"}


def memory_compress(context: dict) -> dict:
    weekly = context.get("weekly_summaries", [])
    if weekly:
        importance = min(10.0, max(float(s.get("importance", 1.0)) for s in weekly) + 1.0)
        highlights = "; ".join(str(s.get("text", ""))[:90] for s in weekly[:3])
        return {"summary": f"Week summary: {len(weekly)} daily memories. {highlights}",
                "importance": importance, "belief_updates": []}
    obs = context.get("observations", [])
    if not obs:
        return {"summary": "", "importance": 1.0, "belief_updates": []}
    kinds = [o.get("kind", "") for o in obs]
    importance = min(10.0, 1.0 + max((float(o.get("importance", 1.0)) for o in obs), default=1.0))
    headline = obs[0].get("text", "")[:80]
    summary = f"Day summary: {len(obs)} events. Notably: {headline}"
    belief_updates = []
    if any(k in ("goods_sale", "price_set") for k in kinds):
        belief_updates.append({"key": "inflation_expectation", "value": context.get("infl_hint", 0.02)})
    return {"summary": summary, "importance": importance, "belief_updates": belief_updates}


def oracle_answer(context: dict) -> dict:
    """Scripted analyst: derive a probability from world state so the Oracle works
    offline. Real runs route the Oracle to a strong model instead."""
    q = (context.get("question", "") or "").lower()
    m = context.get("metrics", {})
    tick = int(context.get("tick", 0))
    horizon = int(context.get("default_horizon", 30))
    match = re.search(r"within\s+(\d+)\s+(?:tick|day)", q)
    if match:
        horizon = max(1, int(match.group(1)))
    drivers = []
    if "bank run" in q or "bank" in q:
        min_ratio = context.get("min_reserve_ratio", 1.0)
        trust = context.get("min_bank_trust", 0.6)
        p = max(0.02, min(0.95, 0.5 * (1 - min_ratio) + 0.6 * (0.6 - trust)))
        drivers = [f"lowest reserve ratio {min_ratio:.2f}", f"lowest bank trust {trust:.2f}"]
        rule = {"type": "bank_run", "window": 5, "deposit_drop": 0.30}
    elif "crash" in q or "market" in q:
        idx_change = float(m.get("index_change_10", 0.0))
        p = max(0.02, min(0.95, 0.3 - idx_change))
        drivers = [f"10-tick index change {idx_change:+.2%}"]
        rule = {"type": "index_drop", "window": horizon, "drop": 0.20}
    elif "recession" in q or "unemployment" in q:
        unemp = float(m.get("unemployment", 0.05))
        p = max(0.02, min(0.95, unemp * 4))
        drivers = [f"unemployment {unemp:.1%}"]
        rule = {"type": "unemployment_above", "threshold": 0.08, "window": horizon}
    else:
        return {"insufficient_data": True,
                "reason": "No machine-checkable resolution rule can be derived from world state."}
    return {"p": round(p, 3), "drivers": drivers, "confidence": "med",
            "resolution_rule": rule, "deadline_tick": tick + horizon,
            "reasoning": "Estimated from current world state and simple structural drivers."}


# Registry: purpose -> scripted policy. Registered onto the gateway's scripted adapter.
POLICIES: dict[str, Callable[[dict], dict]] = {
    "decision": citizen_decision,
    "citizen": citizen_decision,
    "founder": founder_decision,
    "credit_officer": credit_officer_decision,
    "central_banker": central_banker_decision,
    "vc_partner": vc_partner_decision,
    "reporter": reporter_draft,
    "newsroom": newsroom_policy,
    "conversation": conversation_turn,
    "memory": memory_compress,
    "oracle": oracle_answer,
}


def register_scripted_policies(scripted_adapter) -> None:
    for purpose, fn in POLICIES.items():
        scripted_adapter.register(purpose, fn)
