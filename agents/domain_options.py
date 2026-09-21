"""Pure candidate generation from authorized, detached v4 observations."""
from __future__ import annotations

from copy import deepcopy

from .decision_domains import ACTION_DOMAIN
from .decision_candidates import _integer
from llm.decisions import canonical_json


def options_for(context: dict, policy: dict) -> tuple[list[dict], list[str]]:
    enabled = set(policy["domains"])
    agent, state = context.get("agent", {}), context.get("state", {})
    actor = _integer(agent.get("id"), "actor", minimum=1)
    currency = str(state.get("currency_code") or "USD")
    cash = _integer(state.get("checking_balance", 0), "cash")
    resources = context.get("decision_resources", {})
    personal = f"agent:{actor}:{currency}"
    rows, exclusions = [], []

    def add(action, *, facts=None, costs=None, rank=50, exclusive=False, source="observation"):
        if not isinstance(action, dict) or action.get("type") not in ACTION_DOMAIN:
            raise ValueError("unclassified action in decision observation")
        domain = ACTION_DOMAIN[action["type"]]
        if (facts or {}).get("company_decision") and action["type"] in {"accept_job_offer", "reject_job_offer", "counter_job_offer"}:
            domain = "founder_operations"
        if domain not in enabled or domain == "judgments":
            return
        requirements = costs or {}
        for key, amount in requirements.items():
            _integer(amount, "commitment")
            available = resources.get(key, {}).get("available_cents")
            if available is None and key == personal:
                available = cash
            if available is None or amount > _integer(available, "available resource"):
                exclusions.append(f"{domain}:insufficient_resource")
                return
        rows.append({"actions": [deepcopy(action)], "domain": domain,
                     "facts": deepcopy(facts or {}), "requirements": dict(requirements),
                     "exclusive": exclusive, "source": source, "baseline_rank": rank})

    # Hard occupancy cannot be bypassed by a shopping or financial menu.
    if (context.get("frontier") or {}).get("task"):
        return [], ["busy_frontier_task"]
    if agent.get("age", 18) < 18 or agent.get("alive") is False:
        return [], ["ineligible_actor"]
    required = context.get("civic_required_action")
    if required:
        if "entrepreneurship" not in enabled:
            return [], ["unrepresented_required_civic_action"]
        add(required, facts={"required_appointment": True}, exclusive=True, rank=0)
        return rows, exclusions

    # Shopping and labor alternatives remain distinct choices; the composer can
    # also offer compatible shopping+employment bundles without double spending.
    if "consumption" in enabled and agent.get("health") != "critical":
        budget = min(cash * policy["spending_bps"] // 10000,
                     resources.get(personal, {}).get("available_cents", cash))
        target = min(policy["max_quantity"], max(1, 1 + int(agent.get("dependents", 0))))
        for offer in sorted(context.get("prices", []), key=lambda x: (x["price"], x["firm_id"]))[:policy["max_goods_offers"]]:
            price = _integer(offer["price"], "goods price", minimum=1)
            qty = min(_integer(offer["inventory"], "inventory"), budget // price,
                      policy["max_quantity"], int(context.get("shopping_qty_cap", policy["max_quantity"])))
            if str(offer.get("currency_code") or currency) != currency:
                continue
            for quantity in sorted({1, min(target, qty), qty}):
                if 0 < quantity <= qty:
                    add({"type": "buy_goods", "firm_id": _integer(offer["firm_id"], "seller", minimum=1), "qty": quantity},
                        facts={"quantity": quantity, "consumption_target": target,
                               "target_basis": "declared preference", "price_cents": price,
                               "product": str(offer.get("product", "goods"))[:160]},
                        costs={personal: price * quantity}, rank=10 + abs(quantity - target))
    if "career" in enabled and agent.get("health", "healthy") == "healthy" and not agent.get("retired") and not state.get("employed"):
        pending = set(context.get("pending_job_ids", []))
        for offer in context.get("incoming_job_offers", [])[:policy["max_job_options"]]:
            if str(offer.get("currency_code") or currency) != currency:
                continue
            oid = _integer(offer["offer_id"], "offer", minimum=1)
            wage = _integer(offer["offered_wage"], "wage", minimum=1)
            add({"type": "accept_job_offer", "offer_id": oid}, facts={"wage_cents": wage}, rank=5)
            add({"type": "reject_job_offer", "offer_id": oid}, facts={"foregone_wage_cents": wage})
            add({"type": "counter_job_offer", "offer_id": oid, "wage": wage * 105 // 100},
                facts={"offered_wage_cents": wage, "counter_not_guaranteed": True})
        if not context.get("incoming_job_offers"):
            jobs = sorted(context.get("jobs", []), key=lambda j: (-j["wage"], j["job_id"]))
            for job in [j for j in jobs if j["job_id"] not in pending][:policy["max_job_options"]]:
                if str(job.get("currency_code") or currency) == currency:
                    add({"type": "apply_job", "job_id": _integer(job["job_id"], "job", minimum=1)},
                        facts={"wage_cents": _integer(job["wage"], "wage"), "application_is_not_hire": True}, rank=7)

    firm = context.get("my_firm") or {}
    if firm and "founder_operations" in enabled:
        fid = _integer(firm["firm_id"], "firm", minimum=1)
        firm_key = f"firm:{fid}:{firm.get('currency_code', currency)}"
        price = _integer(firm["price"], "posted price", minimum=1)
        for step in policy["price_steps_bps"]:
            new_price = max(1, price * (10000 + step) // 10000)
            add({"type": "set_price", "firm_id": fid, "price": new_price},
                facts={"old_price_cents": price, "price_cents": new_price,
                       "input_cost_cents": firm.get("unit_cost"), "inventory": firm.get("inventory"),
                       "executed_sales_units": firm.get("executed_sales_units"),
                       "sales_window": firm.get("sales_window")}, rank=20 if step == 0 else 30)
        for app in context.get("firm_applications", [])[:policy["max_job_options"]]:
            if app.get("current_offer_id") or app.get("job_pending_offer_count", 0) or app.get("state", "pending") != "pending":
                continue
            wage = _integer(app["posted_wage"], "posted wage")
            add({"type": "make_job_offer", "application_id": app["application_id"], "wage": wage},
                facts={"candidate_id": app["agent_id"], "wage_commitment_cents": wage}, costs={firm_key: wage}, rank=6)
        for offer in context.get("firm_job_offers", [])[:policy["max_job_options"]]:
            if not offer.get("candidate_alive", True) or offer.get("candidate_retired") or offer.get("candidate_employed"):
                continue
            wage = _integer(offer["requested_wage"], "requested wage")
            add({"type": "accept_job_offer", "offer_id": offer["offer_id"]},
                facts={"wage_commitment_cents": wage, "company_decision": True}, costs={firm_key: wage}, rank=5)
            add({"type": "reject_job_offer", "offer_id": offer["offer_id"]}, facts={"company_decision": True})
            counter = max(1, wage * 95 // 100)
            add({"type": "counter_job_offer", "offer_id": offer["offer_id"], "wage": counter},
                facts={"company_decision": True, "requested_wage_cents": wage},
                costs={firm_key: counter}, rank=15)
        if firm.get("open_jobs", 0) + firm.get("employees", 0) < firm.get("target_headcount", 0):
            wage = firm.get("default_wage_cents")
            if type(wage) is int and wage > 0:
                add({"type": "post_job", "firm_id": fid, "title": "worker", "wage": wage},
                    facts={"wage_commitment_cents": wage}, costs={firm_key: wage}, rank=8)
        for employee in firm.get("employee_roster", []):
            add({"type": "fire", "employment_id": employee["employment_id"]},
                facts={"ends_employment_for": employee["agent_id"], "wage_cents": employee["wage"]}, rank=90)

    if "investment" in enabled and context.get("portfolio_day"):
        budget = min(cash * policy["investment_bps"] // 10000,
                     resources.get(personal, {}).get("available_cents", cash))
        outstanding = context.get("open_equity_orders", [])
        committed_shares = {}
        for order in outstanding:
            if order["side"] == "sell":
                committed_shares[order["firm_id"]] = committed_shares.get(order["firm_id"], 0) + order["qty_remaining"]
            add({"type": "cancel_orders", "firm_id": order["firm_id"]}, facts={"cancels_existing_orders": True})
        for listing in context.get("listed_firms", []):
            fid = _integer(listing["firm_id"], "listing", minimum=1)
            if str(listing.get("currency_code") or currency) != currency:
                continue
            last = listing.get("last_price")
            anchor = last or max(int(listing.get("book_value_per_share") or 0), int(listing.get("goods_price") or 0))
            if not anchor:
                exclusions.append("investment:missing_valuation_basis")
                continue
            anchor = _integer(anchor, "valuation", minimum=1)
            held = max(0, int(state.get("shares", {}).get(str(fid), 0)) - committed_shares.get(fid, 0))
            for bps in (-200, 0, 200):
                limit = max(1, anchor * (10000 + bps) // 10000)
                facts = {"valuation_basis": "last_trade" if last else "visible_fundamentals",
                         "reference_cents": anchor, "limit_cents": limit, "fill_not_guaranteed": True}
                for side, bound in (("buy", budget // limit), ("sell", held)):
                    bound = min(bound, policy["max_investment_quantity"])
                    for qty in sorted({1, bound}):
                        if 0 < qty <= bound:
                            add({"type": "place_order", "firm_id": fid, "side": side, "qty": qty, "limit_price": limit},
                                facts=facts, costs={personal: qty * limit} if side == "buy" else {}, rank=40)
        for offering in context.get("ipo_offerings", []):
            if str(offering.get("currency_code") or currency) != currency:
                continue
            reserve = _integer(offering["reserve_price"], "IPO reserve", minimum=1)
            qty = min(policy["max_investment_quantity"], budget // reserve)
            if qty:
                add({"type": "place_ipo_bid", "offering_id": offering["offering_id"], "qty": qty, "max_price": reserve},
                    facts={"allocation_not_guaranteed": True}, costs={personal: qty * reserve}, rank=45)
        for quote in context.get("fx_quotes", []):
            for side in ("buy", "sell"):
                action = quote.get(side + "_action")
                if action:
                    unit = quote["quote_currency"] if side == "buy" else quote["base_currency"]
                    cost = (action["qty"] * action["limit_rate_ppm"] + 999999) // 1000000 if side == "buy" else action["qty"]
                    add(action, facts={"pair": quote["pair"], "fill_not_guaranteed": True}, costs={f"agent:{actor}:{unit}": cost})
        for order in context.get("open_fx_orders", []):
            add(order["cancel_action"])

    if "personal_finance" in enabled:
        savings = _integer(state.get("savings_balance", context.get("savings_balance", 0)), "savings")
        shortfall = max(0, int(context.get("retirement_drawdown_target_cents", 0)) - cash)
        if agent.get("retired") and min(savings, shortfall):
            add({"type": "withdraw_savings", "amount": min(savings, shortfall)}, rank=4,
                facts={"own_savings_cents": savings, "checking_shortfall_cents": shortfall})
        if context.get("insured"):
            add({"type": "cancel_insurance"}, facts={"ends_coverage": True}, rank=95)
        elif context.get("insurance_offer"):
            offer = context["insurance_offer"]
            premium = _integer(offer.get("premium_cents", offer.get("premium", 0)), "premium", minimum=1)
            add({"type": "buy_insurance"}, facts=offer, costs={personal: premium}, rank=35)
        for bank in context.get("banks", []):
            if bank.get("id") != state.get("bank_id") and bank.get("status") == "open" and str(bank.get("currency_code") or currency) == currency:
                add({"type": "move_deposits", "to_bank_id": bank["id"]},
                    facts={"public_confidence": bank.get("confidence_signal"), "moves_existing_deposits": True}, rank=70)

    if "learning_compute" in enabled:
        for option in context.get("study_skill_options", []):
            add(option["action"], facts={"skill": option["skill_key"], "xp_gain": option.get("xp_gain")},
                costs={personal: _integer(option["price_cents"], "study price")}, exclusive=True, rank=45)
        for option in context.get("compute_plan_offers", []):
            if option.get("eligible"):
                add(option["action"], facts={k: option[k] for k in ("tier", "price_cents", "duration_ticks")},
                    costs={personal: _integer(option["price_cents"], "plan price")}, rank=55)
        if context.get("compute_plan_cancel_action"):
            add(context["compute_plan_cancel_action"], facts={"ends_paid_compute_plan": True}, rank=85)

    if context.get("purpose") == "central_banker" and "bank_policy" in enabled:
        terms = context.get("monetary_bounds", {})
        current = _integer(context["policy_rate_bps"], "policy rate")
        for step in (-int(terms.get("max_step_bps", 50)), 0, int(terms.get("max_step_bps", 50))):
            rate = max(int(terms.get("min_rate_bps", 0)), min(int(terms.get("max_rate_bps", 2000)), current + step))
            add({"type": "set_policy_rate", "rate_bps": rate}, facts={"current_bps": current, "metrics": context.get("metrics", {})}, rank=20 if step == 0 else 40)
        for request in context.get("liquidity_support_requests", []):
            for decision in (("approve", "deny") if request.get("solvent") else ("deny",)):
                add({"type": "decide_liquidity_support", "request_event_id": request["request_event_id"],
                     "decision": decision, "evidence_event_ids": [request["request_event_id"]]}, facts=request, rank=2)

    # These are engine-prepared alternatives, not action payloads parsed from
    # arbitrary text. Counterparty consent and execution-time checks still apply.
    sources = ("construction_work", "household_decisions", "daily_time", "population_boundary",
               "legal_work", "estate_legal_work", "legal_representation", "institutional_work",
               "estate_property_market", "estate_unlisted_market", "startup_work")
    for key in sources:
        data = context.get(key) or {}
        if not isinstance(data, dict):
            continue
        for action in data.get("eligible_actions", []):
            if action.get("type") == "issue_legal_decision":
                exclusions.append("unrepresented_binding_judgment")
                continue
            # No meaningful current separation choice when there is no partner.
            if action.get("type") == "separate_household" and not data.get("partner_id"):
                continue
            details = context.get("domain_action_terms", {}).get(canonical_json(action), {})
            costs = details.get("requirements", {})
            if action.get("type") in {"lobby", "contribute_construction_funding"}:
                costs = {personal: int(action.get("amount_cents", 0))}
            add(action, facts={"source": key, "terms": data.get("terms"),
                               "pending": data.get("pending", []), "bills": data.get("bills", []),
                               **details.get("facts", {})}, costs=costs,
                exclusive=action.get("type") == "perform_construction_work",
                source=key, rank=15 if key == "institutional_work" else 50)
            if action.get("type") == "accept_contract":
                add({"type": "reject_contract", "contract_id": action["contract_id"]},
                    facts={"source": key, "declines_existing_contract": True}, source=key)
            if action.get("type") == "executive_bill_action" and action.get("action") == "sign":
                add({**action, "action": "veto"}, facts={"source": key, "bills": data.get("bills", [])}, source=key)
            if action.get("type") == "lobby" and action.get("position") == "support":
                add({**action, "position": "oppose"}, facts={"source": key, "bills": data.get("bills", [])},
                    costs={personal: int(action.get("amount_cents", 0))}, source=key)
    for data in context.get("entrepreneurship_options", []):
        add(data["action"], facts={k: v for k, v in data.items() if k != "action"},
            costs={personal: int(data.get("commitment_cents", 0))}, exclusive=True, rank=25)
    for option in (context.get("frontier") or {}).get("options", []):
        add(option["action"], facts={"duration_ticks": option["duration_ticks"], "cost_cents": option["cost_cents"]},
            costs={personal: option["cost_cents"]}, exclusive=True, rank=60)
    for key in ("migration_options", "trade_opportunities"):
        for option in context.get(key, []):
            if option.get("action"):
                add(option["action"], facts={k: v for k, v in option.items() if k != "action"}, exclusive=key == "migration_options")
    for option in context.get("prepared_decision_options", []):
        add(option["action"], facts=option.get("facts"), costs=option.get("requirements"),
            rank=option.get("baseline_rank", 50), exclusive=bool(option.get("exclusive")), source="prepared")
    if context.get("scripted_communication_action"):
        add(context["scripted_communication_action"], facts={"source": "authorized_prepared_message"}, rank=40)
    return rows, exclusions
