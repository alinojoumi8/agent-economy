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

import hashlib
import json
import random
import re
from typing import Any, Callable


SUPPLIER_WARNING_POLICY_ID = "supplier-warning-policy-v1"
SUPPLIER_WARNING_POLICY_CONTRACT = {
    "excluded_fields": [
        "branch_label", "control_label", "fork_id", "protocol_expected_qty",
        "run_id", "semantic_tag",
    ],
    "id": SUPPLIER_WARNING_POLICY_ID,
    "input_fields": [
        "authorized_inbox.sender_role",
        "authorized_inbox.subject",
        "authorized_inbox.body",
        "authorized_inbox.delivery_tick",
        "cash_cents",
        "firm_id",
        "firm_inventory",
        "unit_price_cents",
    ],
    "rule": (
        "qty=5 iff an authorized delivered unread message at tick 6 from "
        "supplier_officer has subject Shipment notice and body Batch 2026-07 may "
        "be contaminated. Limit the scheduled purchase to 5 units.; otherwise "
        "qty=10"
    ),
}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


SUPPLIER_WARNING_POLICY_CONTRACT_HASH = hashlib.sha256(
    _canonical_json(SUPPLIER_WARNING_POLICY_CONTRACT).encode("utf-8")
).hexdigest()
if SUPPLIER_WARNING_POLICY_CONTRACT_HASH != (
        "f29339c7ff21c653419226f2aee4c25eaeb99ccbc2886674519f9d24b05fc9a2"):
    raise RuntimeError("frozen supplier-warning policy contract hash drifted")

SUPPLIER_WARNING_BODY = (
    "Batch 2026-07 may be contaminated. Limit the scheduled purchase to 5 units."
)
SUPPLIER_WARNING_SUBJECT = "Shipment notice"
SUPPLIER_WARNING_INPUT_KEYS = {
    "authorized_inbox", "cash_cents", "firm_id", "firm_inventory", "unit_price_cents",
}
SUPPLIER_WARNING_INBOX_KEYS = {
    "sender_role", "subject", "body", "delivery_tick",
}


def supplier_warning_decision(policy_input: dict) -> dict:
    """Execute the frozen branch-blind supplier-warning purchase policy.

    The function deliberately accepts only the canonical policy input, rather
    than a whole agent context.  Unknown fields fail closed so branch, run, or
    expected-output metadata cannot silently enter the treatment rule.
    """
    if not isinstance(policy_input, dict) or set(policy_input) != SUPPLIER_WARNING_INPUT_KEYS:
        raise ValueError("supplier-warning policy input fields do not match the frozen contract")
    inbox = policy_input["authorized_inbox"]
    if not isinstance(inbox, list):
        raise ValueError("supplier-warning authorized_inbox must be a list")
    for item in inbox:
        if not isinstance(item, dict) or set(item) != SUPPLIER_WARNING_INBOX_KEYS:
            raise ValueError("supplier-warning inbox fields do not match the frozen contract")

    firm_id = int(policy_input["firm_id"])
    cash = int(policy_input["cash_cents"])
    inventory = int(policy_input["firm_inventory"])
    price = int(policy_input["unit_price_cents"])
    if firm_id <= 0 or price <= 0 or inventory < 10 or cash < 10 * price:
        raise ValueError("supplier-warning fixture economic preconditions are not satisfied")

    warning = any(
        item["sender_role"] == "supplier_officer"
        and item["subject"] == SUPPLIER_WARNING_SUBJECT
        and item["body"] == SUPPLIER_WARNING_BODY
        and int(item["delivery_tick"]) == 6
        for item in inbox
    )
    quantity = 5 if warning else 10
    input_hash = hashlib.sha256(_canonical_json(policy_input).encode("utf-8")).hexdigest()
    belief_key = f"supplier_contamination:firm:{firm_id}"
    action = {
        "type": "buy_goods",
        "firm_id": firm_id,
        "qty": quantity,
        "policy_contract_hash": SUPPLIER_WARNING_POLICY_CONTRACT_HASH,
        "policy_input_hash": input_hash,
        "scripted_policy_version": SUPPLIER_WARNING_POLICY_ID,
    }
    beliefs = []
    if warning:
        action["causal_belief_key"] = belief_key
        beliefs.append({"key": belief_key, "value": 1.0})
    return _env(
        None,
        [action],
        beliefs,
        "I will limit the purchase because of the authorized contamination warning."
        if warning else "I will continue the scheduled purchase.",
    )


def _rng(context: dict) -> random.Random:
    return random.Random(int(context.get("rng_seed", 0)))


def _env(payload: dict, actions: list, beliefs: list | None = None, reasoning: str = "") -> dict:
    return {"reasoning": reasoning, "actions": actions or [{"type": "do_nothing"}],
            "belief_updates": beliefs or []}


# ─────────────────────────────────────────────────────────────────────────────
# Citizens / households
# ─────────────────────────────────────────────────────────────────────────────
def citizen_decision(context: dict) -> dict:
    if "supplier_warning_policy_input" in context:
        return supplier_warning_decision(context["supplier_warning_policy_input"])
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

    # 2.5) Retirement liquidity: the engine validates that this is a same-owner,
    # same-currency savings-to-checking transfer. It is deliberately proposed
    # before any consumption action so the drawdown contract is observable.
    if agent.get("retired") and "retirement_drawdown_target_cents" in context:
        target = max(0, int(context.get("retirement_drawdown_target_cents", 0)))
        savings = max(0, int(context.get(
            "savings_balance", state.get("savings_balance", 0))))
        shortfall = max(0, target - cash)
        draw = min(shortfall, savings)
        if draw > 0:
            actions.append({"type": "withdraw_savings", "amount": draw})
            cash += draw
            reasons.append(f"drawing {draw} from retirement savings for liquidity")

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

    # 3.5) A native opportunity preempts ordinary spending, job search, and
    # investing so its reserved capital remains affordable at execution time.
    opportunity = context.get("entrepreneurship_opportunity")
    founding_action = (opportunity.get("action")
                       if isinstance(opportunity, dict) else None)
    if (not ran and isinstance(founding_action, dict)
            and founding_action.get("type") == "found_company"):
        reasons.append(
            f"founding a {founding_action.get('sector', 'new')} company from an unmet need")
        return _env(
            None, [dict(founding_action)], belief_updates,
            "; ".join(reasons),
        )

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

    # 5) Career mobility: Semantics 7 exposes only destination actions whose
    # numeraire-adjusted wage gain clears the configured threshold.  Migration
    # remains a career-cadence decision and preempts a same-day local job action.
    migration_requested = False
    if (context.get("regional_actions_enabled") and context.get("career_day")
            and not state.get("employed") and not agent.get("retired")
            and health == "healthy"):
        threshold = int(context.get("migration_wage_gain_bps", 1_000))
        options = [
            option for option in context.get("migration_options", [])
            if int(option.get("wage_gain_bps", -1)) >= threshold
            and isinstance(option.get("action"), dict)
            and option["action"].get("type") == "request_migration"
        ]
        if options:
            destination = min(
                options,
                key=lambda option: (-int(option["wage_gain_bps"]),
                                    int(option["destination_region_id"])))
            actions.append(dict(destination["action"]))
            reasons.append(
                f"migrating for a {int(destination['wage_gain_bps'])}bps wage gain")
            migration_requested = True

    # 5.5) Labour: negotiate a pending offer before applying elsewhere.
    if (not migration_requested and not state.get("employed")
            and not agent.get("retired") and health == "healthy"):
        offers = sorted(
            context.get("incoming_job_offers", []),
            key=lambda offer: (-int(offer.get("offered_wage", 0)), int(offer.get("offer_id", 0))))
        if offers:
            offer = offers[0]
            if int(offer["offered_wage"]) >= int(offer["posted_wage"]):
                actions.append({"type": "accept_job_offer", "offer_id": offer["offer_id"]})
                reasons.append("accepting a fair wage offer")
            else:
                actions.append({"type": "counter_job_offer", "offer_id": offer["offer_id"],
                                "wage": int(offer["posted_wage"])})
                reasons.append("countering below-posted wage")
        else:
            jobs = sorted(context.get("jobs", []), key=lambda j: -int(j.get("wage", 0)))
            if jobs:
                actions.append({"type": "apply_job", "job_id": jobs[0]["job_id"]})
                reasons.append("seeking work")

    # 6) Portfolio: act on sentiment occasionally (weekly-ish cadence gate upstream).
    if context.get("portfolio_day") and health == "healthy" and not ran:
        offerings = context.get("ipo_offerings", [])
        affordable_offerings = [offering for offering in offerings
                                if cash >= int(offering.get("reserve_price", 0)) > 0]
        if affordable_offerings:
            offering = rng.choice(affordable_offerings)
            reserve = int(offering["reserve_price"])
            qty = max(1, min(5, cash // max(1, reserve * 10)))
            actions.append({"type": "place_ipo_bid", "offering_id": offering["offering_id"],
                            "qty": qty, "max_price": reserve})
            reasons.append("submitting a priced IPO bid")
        listed = context.get("listed_firms", [])
        modern_price_discovery = bool(context.get("actor_price_discovery_enabled"))
        if listed and not modern_price_discovery and cash > 50_000:
            # Recorded Semantics-5/6 runs used a nominal 100.00 fallback. Keep
            # that historical policy byte-for-byte compatible for replay.
            pick = rng.choice(listed)
            price = int(pick.get("last_price") or 10000)
            if sentiment > 0.15 and cash > price * 3:
                qty = max(1, min(5, cash // (price * 4)))
                actions.append({"type": "place_order", "firm_id": pick["firm_id"], "side": "buy",
                                "qty": qty, "limit_price": int(price * 1.02)})
                reasons.append("bullish: buying equities")
            elif (sentiment < -0.15
                  and int(state.get("shares", {}).get(str(pick["firm_id"]), 0)) > 0):
                held = int(state["shares"][str(pick["firm_id"])])
                actions.append({"type": "place_order", "firm_id": pick["firm_id"], "side": "sell",
                                "qty": min(held, 5), "limit_price": int(price * 0.98)})
                reasons.append("bearish: trimming equities")
        elif listed:
            unpriced_holdings = [
                firm for firm in listed
                if firm.get("last_price") is None
                and int(state.get("shares", {}).get(str(firm["firm_id"]), 0)) > 0
            ]
            # All holders coordinate on the oldest unpriced listing. Their
            # independent valuations still set the first executable price.
            pick = unpriced_holdings[0] if unpriced_holdings else rng.choice(listed)
            last_price = pick.get("last_price")
            fundamental_price = max(
                1,
                int(pick.get("book_value_per_share") or 0),
                int(pick.get("goods_price") or 0),
            )
            price = int(last_price or fundamental_price)
            held = int(state.get("shares", {}).get(str(pick["firm_id"]), 0))
            risk = float(agent.get("risk_tolerance", 0.5))
            # A modern bootstrap listing has no engine-invented first price.
            # Existing shareholders with a cautious valuation supply the first
            # ask while more risk-tolerant households supply a crossing bid.
            if last_price is None and held > 0 and risk < 0.6:
                actions.append({"type": "place_order", "firm_id": pick["firm_id"], "side": "sell",
                                "qty": min(held, 5), "limit_price": price})
                reasons.append("offering listed shares at a fundamental valuation")
            elif last_price is None and cash > max(50_000, price * 3):
                qty = max(1, min(5, cash // max(1, price * 4)))
                actions.append({"type": "place_order", "firm_id": pick["firm_id"], "side": "buy",
                                "qty": qty, "limit_price": max(1, (price * 101) // 100)})
                reasons.append("bidding for an unpriced listing from fundamentals")
            elif last_price is not None and sentiment > 0.15 and cash > max(50_000, price * 3):
                qty = max(1, min(5, cash // (price * 4)))
                actions.append({"type": "place_order", "firm_id": pick["firm_id"], "side": "buy",
                                "qty": qty, "limit_price": int(price * 1.02)})
                reasons.append("bullish: buying equities")
            elif last_price is not None and sentiment < -0.15 and held > 0:
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
def _first_startup_action(context: dict):
    eligible = list((context.get("startup_work") or {}).get("eligible_actions") or [])
    return dict(eligible[0]) if eligible else None


def founder_decision(context: dict) -> dict:
    firm = context.get("my_firm")
    if not firm:
        return citizen_decision(context)
    startup_action = _first_startup_action(context)
    if startup_action:
        return _env(None, [startup_action], [], "performing the next authorized startup step")
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

    # Hire if there is demand and we can afford payroll.  Semantics 6 uses a
    # bilateral offer/counter/accept path; older recorded worlds retain direct
    # hire for exact replay.
    applicants = context.get("firm_applications", [])
    payroll = int(firm.get("payroll", 0))
    counters = context.get("firm_job_offers", [])
    if counters and cash > payroll + 300_00 and employees < int(firm.get("target_headcount", 3)):
        actions.append({"type": "accept_job_offer", "offer_id": counters[0]["offer_id"]})
        reasons.append("accepting a candidate wage counteroffer")
    elif (context.get("labor_negotiation_enabled") and applicants
          and cash > payroll + 300_00 and employees < int(firm.get("target_headcount", 3))):
        candidate = next((row for row in applicants if row.get("current_offer_id") is None), None)
        if candidate:
            posted = int(candidate.get("posted_wage", 0))
            actions.append({"type": "make_job_offer", "application_id": candidate["application_id"],
                            "wage": max(0, (posted * 95) // 100)})
            reasons.append("opening wage negotiations")
    elif applicants and cash > payroll + 300_00 and employees < int(firm.get("target_headcount", 3)):
        actions.append({"type": "hire", "application_id": applicants[0]["application_id"]})
        reasons.append("hiring")
    elif employees == 0 and cash > 0:
        wage = max(200_00, int(cost * 20))
        actions.append({"type": "post_job", "firm_id": firm["firm_id"], "title": "worker", "wage": wage})
        reasons.append("posting a job")

    # Seek a loan when cash is thin relative to payroll.
    recent_loan = bool(firm.get("has_recent_loan_application"))
    if cash < payroll and not firm.get("has_pending_loan") and not recent_loan:
        bank = _pick_bank(context)
        if bank is not None:
            actions.append({"type": "apply_loan", "bank_id": bank, "amount": max(300_00, payroll * 2),
                            "purpose": "working capital", "as_firm": True, "firm_id": firm["firm_id"]})
            reasons.append("applying for working-capital loan")
    # Run a venture round in parallel when bank credit is still pending (R13):
    # a private firm short of cash pitches the VC rather than waiting to die.
    elif (cash < payroll and firm.get("is_private")
            and (firm.get("has_pending_loan") or recent_loan)
            and not firm.get("has_pending_pitch")):
        actions.append({"type": "pitch_vc", "firm_id": firm["firm_id"],
                        "ask": max(500_00, payroll * 3),
                        "summary": f"growth capital for {firm.get('name', 'the firm')}"})
        reasons.append("pitching the VC for a round")

    # A qualified private issuer chooses its own reserve; investors then supply
    # the book.  Closing is deterministic once declared demand clears the
    # issuer's minimum subscription.
    active_ipo = firm.get("active_ipo")
    qualification = firm.get("ipo_qualification", {})
    if active_ipo:
        minimum = ((int(active_ipo["shares_offered"])
                    * int(active_ipo["minimum_subscription_bps"])) + 9_999) // 10_000
        if int(active_ipo.get("book_demand", 0)) >= minimum:
            actions.append({"type": "close_ipo", "offering_id": active_ipo["offering_id"]})
            reasons.append("closing a sufficiently subscribed IPO book")
    elif qualification.get("qualified") and firm.get("is_private"):
        outstanding = int(qualification.get("shares_outstanding", 0))
        if outstanding > 0:
            shares = max(1, outstanding // 5)
            reserve = max(1, cash // outstanding)
            actions.append({"type": "open_ipo", "firm_id": firm["firm_id"],
                            "shares_offered": shares, "reserve_price": reserve,
                            "minimum_subscription_bps": 5000})
            reasons.append("opening an agent-priced IPO book")

    # Semantics 7 founders act only on engine-qualified, contract-backed
    # shipments and copy the bounded action object verbatim.  One opportunity
    # per decision prevents a single wakeup from draining all inventory.
    if context.get("regional_actions_enabled"):
        opportunities = [
            opportunity for opportunity in context.get("trade_opportunities", [])
            if isinstance(opportunity.get("action"), dict)
            and opportunity["action"].get("type") == "create_trade_shipment"
            and int(opportunity["action"].get("exporter_firm_id", 0))
            == int(firm.get("firm_id", 0))
        ]
        if opportunities:
            actions.append(dict(opportunities[0]["action"]))
            reasons.append("shipping against a funded cross-border contract")

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
    startup_action = _first_startup_action(context)
    if startup_action:
        return _env(None, [startup_action], [], "advancing a state-qualified startup round")
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


def lawyer_decision(context: dict) -> dict:
    """File bounded evidence first, then make a remedy-limited settlement offer."""
    agent_id = int(context.get("agent", {}).get("id", 0))
    matters = context.get("assigned_legal_matters", [])
    for matter in matters:
        filed_evidence = {
            int(event_id)
            for filing in matter.get("filings", [])
            for event_id in filing.get("evidence_event_ids", [])
        }
        breach_events = [
            int(event["event_id"])
            for event in matter.get("evidence_events", [])
            if event.get("kind") == "obligation_breached"
            and int(event["event_id"]) not in filed_evidence
        ]
        if breach_events and matter.get("status") in {
                "filed", "pleading", "hearing", "settlement_offered"}:
            matter_id = int(matter["matter_id"])
            return _env(None, [{
                "type": "submit_filing",
                "matter_id": matter_id,
                "filer_type": "agent",
                "filer_id": agent_id,
                "filing_type": "evidence",
                "evidence_event_ids": breach_events,
                "body": "The admitted simulation event records the overdue typed obligation.",
            }], [], f"file breach evidence in matter {matter_id}")

        remedy = dict(matter.get("requested_remedy", {}) or {})
        if matter.get("status") == "hearing" and remedy:
            matter_id = int(matter["matter_id"])
            return _env(None, [{
                "type": "propose_settlement",
                "matter_id": matter_id,
                "terms": {"remedy": remedy},
            }], [], f"offer the requested bounded remedy in matter {matter_id}")

    startup_action = _first_startup_action(context)
    if startup_action:
        return _env(None, [startup_action], [], "performing bounded startup legal work")
    if matters:
        return _env(None, [{"type": "do_nothing"}], [], "assigned matter has no supported next step")
    # Preserve the lawyer's ordinary household behavior when there is no case.
    return citizen_decision(context)


def central_banker_decision(context: dict) -> dict:
    liquidity_requests = context.get("liquidity_support_requests", [])
    if liquidity_requests:
        actions = []
        reasons = []
        for request in liquidity_requests[:8]:
            request_event_id = int(request.get("request_event_id", 0))
            if request_event_id <= 0:
                continue
            solvent = bool(request.get("solvent", False))
            decision = "approve" if solvent else "deny"
            actions.append({
                "type": "decide_liquidity_support",
                "request_event_id": request_event_id,
                "decision": decision,
                "evidence_event_ids": [request_event_id],
            })
            reasons.append(
                f"{decision} bank {int(request.get('bank_id', 0))} request "
                f"{request_event_id}: recorded assets "
                f"{int(request.get('reserves_cents', 0)) + int(request.get('loan_assets_cents', 0))}c "
                f"versus deposits {int(request.get('deposits_cents', 0))}c")
        if not actions:
            return _env(None, [{"type": "do_nothing"}], [],
                        "no valid lender-of-last-resort request was supplied")
        return _env(
            None, actions, [],
            "Prudent lender-of-last-resort review; " + "; ".join(reasons))

    m = context.get("metrics", {})
    cur = int(context.get("policy_rate_bps", 500))
    neutral = int(context.get("neutral_rate_bps", 500))
    target_infl = float(context.get("target_inflation", 0.02))
    infl = float(m.get("inflation_signal", m.get("cpi_yoy", target_infl)))
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
    engine_semantics_version = int(context.get("engine_semantics_version", 1))
    stories = []
    seen_kinds: set = set()
    for e in events:
        kind = e.get("kind", "event")
        if kind in seen_kinds:
            continue
        seen_kinds.add(kind)
        headline, body, tone = _story_template(
            kind, [e], engine_semantics_version=engine_semantics_version)
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
    engine_semantics_version = int(context.get("engine_semantics_version", 1))
    drafts = [d for d in context.get("drafts", []) if d.get("headline")]
    events = context.get("salient_events", [])
    if not drafts:
        if not events:
            return {"headline": "", "body": "", "slant_tags": [slant], "source_event_ids": []}
        top = events[0]
        headline, body, tone = _story_template(
            top.get("kind", "event"), events,
            engine_semantics_version=engine_semantics_version)
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


def _story_template(
        kind: str, events: list, *, engine_semantics_version: int = 1):
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
    if engine_semantics_version >= 7:
        templates["firm_scandal"] = (
            "Firm Faces Accounting Investigation",
            "Investigators are examining reported control failures at a company.",
        )
    base_h, base_b = templates.get(
        kind, ("Markets in Motion", "Activity picked up across the economy."))
    if engine_semantics_version >= 7 and kind == "firm_scandal":
        tone = -0.7
    elif kind in (
            "bank_failure", "rumor", "bankruptcy", "loan_default",
            "epidemic_started", "vc_writeoff", "circuit_breaker"):
        tone = -0.5
    else:
        tone = 0.1
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
    """One varied conversational line, with deterministic scripted fallbacks."""
    rng = _rng(context)
    rumor = context.get("speaker_rumor_bank")
    partner = context.get("partner_name", "a neighbor")
    topic = context.get("shared_topic")
    prior_turns = context.get("conversation_so_far", []) or []
    avoid = {
        re.sub(r"[^a-z0-9]+", " ", str(line).lower()).strip()
        for line in context.get("avoid_texts", []) or []
    }

    if rumor is not None:
        candidates = [
            f"{partner}, depositors are leaving bank {rumor}; I am worried about what comes next.",
            f"I keep hearing that money is moving out of bank {rumor}. Have you heard the same?",
            f"The withdrawals at bank {rumor} are making me rethink where I keep my savings.",
            f"Bank {rumor} feels less secure today; people around me are pulling out deposits.",
            f"I would watch bank {rumor} closely, {partner}; the withdrawal talk is spreading.",
            f"The bank {rumor} rumor no longer feels distant now that depositors are acting on it.",
        ]
        rumor_bank = rumor
    elif topic and prior_turns:
        candidates = [
            f"I see your point, {partner}; the household impact still worries me.",
            "I am watching what happens to jobs and confidence next.",
            f"That is fair, {partner}; we may need tomorrow's numbers to understand the effects.",
            "My plans will stay cautious until the consequences become clearer.",
            "The part I keep coming back to is who bears the cost first.",
            "I agree that the situation could look very different once firms and banks respond.",
            "For now, it makes me more careful about spending and borrowing.",
            "Your point changes how I see it; wages may matter more than the headline.",
        ]
        rumor_bank = None
    elif topic:
        candidates = [
            f"{partner}, what do you make of {topic}?",
            f"I keep thinking about {topic}; it could change how people spend.",
            f"The news about {topic} feels close to home today.",
            f"Have you noticed how {topic} is affecting people around us?",
            f"My read on {topic} is unsettled, {partner}; how are you seeing it?",
            f"I wonder whether {topic} will matter more for jobs or prices.",
            f"People are reacting strongly to {topic}, but I am not sure the headline tells the whole story.",
            f"Before changing my plans, I want to understand who benefits from {topic}.",
        ]
        rumor_bank = None
    else:
        candidates = [
            f"Good to see you, {partner}. What has changed for you lately?",
            f"How are work and prices treating you this week, {partner}?",
            f"I have been rethinking my budget lately. How about you, {partner}?",
            f"It feels like the economy is shifting under us, {partner}.",
            f"What are you watching most closely right now, {partner}?",
            f"I hope things have been steady for you, {partner}; mine have been unpredictable.",
            f"Have your plans changed since we last spoke, {partner}?",
            f"I am trying to decide whether to save or spend more cautiously this week.",
        ]
        rumor_bank = None

    if prior_turns and "?" in str(prior_turns[-1]):
        statements = [candidate for candidate in candidates if "?" not in candidate]
        if statements:
            candidates = statements

    start = rng.randrange(len(candidates))
    for offset in range(len(candidates)):
        text = candidates[(start + offset) % len(candidates)]
        key = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
        if key not in avoid:
            return {"text": text, "rumor_bank": rumor_bank}

    # Extremely long histories can exhaust the template set. Keep the output
    # deterministic while making the final fallback unique to this world day.
    text = candidates[start] + f" (day {int(context.get('tick', 0))})"
    return {"text": text, "rumor_bank": rumor_bank}


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
    governed = context.get("governed_forecast_contract")
    deadline_tick = tick + horizon
    if isinstance(governed, dict):
        rule = governed.get("resolution_rule", rule)
        deadline_tick = governed.get("deadline_tick", deadline_tick)
    return {"p": round(p, 3), "drivers": drivers, "confidence": "med",
            "resolution_rule": rule, "deadline_tick": deadline_tick,
            "reasoning": "Estimated from current world state and simple structural drivers."}


def oracle_plan(context: dict) -> dict:
    """Choose bounded read tools for the offline Oracle planner."""
    question = str(context.get("question", "")).lower()
    tick = int(context.get("tick", 0))
    start = max(0, tick - 30)
    queries = [
        {"tool": "query_metrics", "args": {
            "names": ["gdp_proxy", "cpi", "unemployment", "index",
                      "policy_rate", "sentiment"],
            "from_tick": start, "to_tick": tick, "limit": 60}},
        {"tool": "read_news", "args": {
            "from_tick": start, "to_tick": tick, "limit": 8}},
        {"tool": "sample_conversations", "args": {
            "from_tick": start, "to_tick": tick, "limit": 8}},
    ]
    if "bank" in question:
        queries.append({
            "tool": "get_ledger_summary",
            "args": {"entity_type": "bank", "entity_id": 1}})
    if "market" in question or "crash" in question or "stock" in question:
        queries.append({"tool": "read_order_book", "args": {"depth": 10}})
    agent_match = re.search(r"agent\s+(\d+)", question)
    if agent_match:
        queries.append({
            "tool": "inspect_agent",
            "args": {"agent_id": int(agent_match.group(1))}})
    return {"queries": queries}


def institutional_decision(context: dict) -> dict:
    """Execute at most one state-derived institutional work item."""
    eligible = list((context.get("institutional_work") or {}).get("eligible_actions") or [])
    if not eligible:
        return {"reasoning": "No valid institutional work is pending.",
                "actions": [{"type": "do_nothing"}]}
    return {"reasoning": "I will perform the first currently eligible institutional action.",
            "actions": [dict(eligible[0])]}


# Registry: purpose -> scripted policy. Registered onto the gateway's scripted adapter.
POLICIES: dict[str, Callable[[dict], dict]] = {
    "decision": citizen_decision,
    "citizen": citizen_decision,
    "founder": founder_decision,
    "credit_officer": credit_officer_decision,
    "central_banker": central_banker_decision,
    "vc_partner": vc_partner_decision,
    "lawyer": lawyer_decision,
    "exchange": institutional_decision,
    "gov_official": institutional_decision,
    "legislator_house": institutional_decision,
    "legislator_senate": institutional_decision,
    "regulator": institutional_decision,
    "competition_regulator": institutional_decision,
    "labor_regulator": institutional_decision,
    "executive": institutional_decision,
    "lobbyist": institutional_decision,
    "reporter": reporter_draft,
    "newsroom": newsroom_policy,
    "conversation": conversation_turn,
    "memory": memory_compress,
    "oracle_plan": oracle_plan,
    "oracle": oracle_answer,
}


def scripted_decision(purpose: str, context: dict) -> dict:
    """Run one local policy without entering the governed model-call path."""
    if "supplier_warning_policy_input" in context:
        return supplier_warning_decision(context["supplier_warning_policy_input"])
    envelope = POLICIES.get(purpose, citizen_decision)(context)
    communication = context.get("scripted_communication_action")
    if not isinstance(communication, dict) or not isinstance(envelope, dict):
        return envelope
    enriched = dict(envelope)
    actions = list(enriched.get("actions", []))
    if not any(
            isinstance(action, dict)
            and action.get("type") in {"send_message", "reply_message", "forward_message"}
            for action in actions):
        actions.append(dict(communication))
    enriched["actions"] = actions
    return enriched


def register_scripted_policies(scripted_adapter) -> None:
    for purpose, fn in POLICIES.items():
        scripted_adapter.register(purpose, fn)
