"""Read-only v4 observations; writes only existing per-tick authorization caches.

All SQL is scoped to the actor's own accounts/companies, assigned cases, or
existing public catalogs. No model is called while constructing these facts.
"""
from __future__ import annotations

from copy import deepcopy
import json

from llm.decision_config import POLICY_VERSION_V4, decision_policy
from llm.decisions import canonical_json


def enrich_decision_context(builder, actor, tick: int, context: dict) -> None:
    policy = decision_policy(builder.config)
    if not policy or policy["version"] != POLICY_VERSION_V4 or tick < policy["activation_tick"]:
        return
    store, economy, aid = builder.store, builder.e, int(actor["id"])
    context["agent"].update(age=int(actor["age"]), alive=bool(actor["alive"]),
        health=actor["health"], retired=bool(actor["retired"]),
        risk_tolerance=float(actor["risk_tolerance"] if actor["risk_tolerance"] is not None else .5),
        political_lean=float(actor["political_lean"] or 0))
    wallets = store.query("SELECT id,kind,currency_code,balance_cents FROM accounts WHERE owner_type='agent' AND owner_id=? ORDER BY id", (aid,))
    primary = next((r for r in wallets if r["id"] == actor["checking_account_id"]), None)
    resources = {}
    for wallet in wallets:
        resources[f"account:{wallet['id']}:{wallet['currency_code']}"] = {
            "account_id": wallet["id"], "balance_cents": wallet["balance_cents"],
            "committed_cents": 0, "available_cents": wallet["balance_cents"]}
        if wallet["kind"] == "checking":
            key = f"agent:{aid}:{wallet['currency_code']}"
            # Match the engine's single settlement account per currency, not a
            # sum that would falsely imply all accounts can fund one action.
            resources.setdefault(key, {"account_id": wallet["id"], "balance_cents": wallet["balance_cents"],
                                       "committed_cents": 0, "available_cents": wallet["balance_cents"]})
    if primary:
        context.setdefault("state", {}).update(checking_balance=int(primary["balance_cents"]), currency_code=primary["currency_code"])
        resources[f"agent:{aid}:{primary['currency_code']}"] = {
            "account_id": primary["id"], "balance_cents": primary["balance_cents"], "committed_cents": 0,
            "available_cents": primary["balance_cents"]}

    def commit(key, amount):
        if key in resources:
            row = resources[key]
            row["committed_cents"] += max(0, int(amount))
            row["available_cents"] = max(0, row["balance_cents"] - row["committed_cents"])

    orders = [dict(r) for r in store.query(
        "SELECT o.firm_id,o.side,o.qty_remaining,o.limit_price_cents,f.currency_code FROM orders o "
        "JOIN firms f ON f.id=o.firm_id WHERE o.agent_id=? AND o.status IN ('open','partial') AND o.qty_remaining>0 ORDER BY o.id", (aid,))]
    context["open_equity_orders"] = orders
    for order in orders:
        key = f"agent:{aid}:{order['currency_code']}"
        if order["side"] == "buy":
            commit(key, order["qty_remaining"] * order["limit_price_cents"] if order["limit_price_cents"] else resources.get(key, {}).get("balance_cents", 0))
    for bid in store.query("SELECT b.qty,b.max_price_cents,f.currency_code FROM ipo_bids b JOIN ipo_offerings o ON o.id=b.offering_id JOIN firms f ON f.id=o.firm_id WHERE b.bidder_agent_id=? AND b.status='open'", (aid,)):
        commit(f"agent:{aid}:{bid['currency_code']}", bid["qty"] * bid["max_price_cents"])
    for order in store.query("SELECT pair,side,qty_remaining,limit_rate_ppm FROM fx_orders WHERE actor_id=? AND status='open'", (aid,)):
        base, quote = order["pair"].split("/")
        key = f"agent:{aid}:{quote if order['side'] == 'buy' else base}"
        amount = order["qty_remaining"] if order["side"] == "sell" else (
            (order["qty_remaining"] * order["limit_rate_ppm"] + 999999) // 1000000
            if order["limit_rate_ppm"] else resources.get(key, {}).get("balance_cents", 0))
        commit(key, amount)
    context["decision_resources"] = resources
    if primary and "listed_firms" in context:
        # Currency remains explicit even when an older profile did not filter
        # its public market catalog by the citizen's settlement currency.
        for listing in context["listed_firms"]:
            listing["currency_code"] = store.scalar("SELECT currency_code FROM firms WHERE id=?", (listing["firm_id"],))
    prepared = context.setdefault("prepared_decision_options", [])

    def offer(action, facts=None, requirements=None, rank=50):
        prepared.append({"action": deepcopy(action), "facts": deepcopy(facts or {}),
                         "requirements": requirements or {}, "baseline_rank": rank})

    firm = context.get("my_firm")
    if firm:
        fid = int(firm["firm_id"])
        owned = store.query_one("SELECT currency_code,account_id FROM firms WHERE id=?", (fid,))
        firm["currency_code"] = owned["currency_code"]
        key = f"firm:{fid}:{owned['currency_code']}"
        firm["open_jobs"] = int(store.scalar("SELECT COUNT(*) FROM jobs WHERE firm_id=? AND status='open'", (fid,), default=0))
        context["firm_applications"] = builder._firm_applications(fid, include_posted_wage=True, actionable_only=True, exclude_agent_id=aid)
        context["firm_job_offers"] = builder._firm_job_offers(fid, actionable_only=True)
        firm["default_wage_cents"] = max(250000, int(firm["price"]) * 400)
        firm["sales_window"] = {"from_tick": max(0, tick - 3), "to_tick": tick - 1}
        firm["executed_sales_units"] = int(store.scalar(
            "SELECT COALESCE(SUM(json_extract(payload_json,'$.qty')),0) FROM events WHERE kind='goods_sale' AND tick>=? AND tick<? AND json_extract(payload_json,'$.firm_id')=?",
            (max(0, tick - 3), tick, fid), default=0) or 0)
        reserved = int(firm["payroll"]) * policy["firm_reserve_payrolls"]
        reserved += int(store.scalar("SELECT COALESCE(SUM(jo.wage_cents),0) FROM job_offers jo JOIN applications ap ON ap.id=jo.application_id JOIN jobs j ON j.id=ap.job_id WHERE j.firm_id=? AND jo.status='pending'", (fid,), default=0) or 0)
        resources[key] = {"account_id": owned["account_id"], "balance_cents": firm["cash"],
                          "committed_cents": reserved, "available_cents": max(0, firm["cash"] - reserved)}
        active, qualification = firm.get("active_ipo"), firm.get("ipo_qualification") or {}
        if active:
            minimum = (active["shares_offered"] * active["minimum_subscription_bps"] + 9999) // 10000
            if active["book_demand"] >= minimum:
                offer({"type": "close_ipo", "offering_id": active["offering_id"]}, {"subscribed_qty": active["book_demand"]})
        elif qualification.get("qualified") and firm.get("is_private") and qualification.get("shares_outstanding", 0) > 0:
            outstanding = qualification["shares_outstanding"]
            for share_bps in (1000, 2000):
                offer({"type": "open_ipo", "firm_id": fid, "shares_offered": max(1, outstanding * share_bps // 10000),
                       "reserve_price": max(1, firm["cash"] // outstanding), "minimum_subscription_bps": 5000},
                      {"valuation_basis": "issuer_book_cash", "qualification": qualification})

    # Current loan catalogs are prepared here to exclude recent applications
    # and prevent personal funds from being confused with corporate borrowing.
    if primary:
        borrowers = [("agent", aid, int(primary["balance_cents"]), max(30000, int(context.get("state", {}).get("wage", 0))), primary["currency_code"])]
        if firm:
            borrowers.append(("firm", firm["firm_id"], firm["cash"], max(30000, firm["payroll"] * 2), firm["currency_code"]))
        for kind, identity, balance, amount, unit in borrowers:
            if balance >= amount:
                continue
            for bank in store.query("SELECT id FROM banks WHERE status='open' AND currency_code=? ORDER BY id", (unit,)):
                recent = store.query_one("SELECT 1 FROM loan_applications WHERE borrower_type=? AND borrower_id=? AND bank_id=? AND tick>?", (kind, identity, bank["id"], tick - 7))
                migrating = kind == "agent" and store.query_one("SELECT 1 FROM migrations WHERE agent_id=? AND status='pending'", (aid,))
                if not recent and not migrating:
                    action = {"type": "apply_loan", "bank_id": bank["id"], "amount": amount, "purpose": "working capital" if kind == "firm" else "household liquidity"}
                    if kind == "firm":
                        action.update(as_firm=True, firm_id=identity)
                    offer(action, {"application_not_disbursement": True, "borrower_type": kind}, rank=55)

    if context.get("purpose") == "credit_officer":
        for application in context.get("pending_loan_apps", []):
            row = store.query_one("SELECT a.*,b.reserve_account_id,b.currency_code,b.risk_policy_json,b.status bank_status FROM loan_applications a JOIN banks b ON b.id=a.bank_id WHERE a.id=? AND a.status='pending'", (application["id"],))
            if not row:
                continue
            offer({"type": "deny_loan", "application_id": row["id"], "reason": "declined after capacity review"}, application, rank=40)
            if row["bank_status"] != "open":
                continue
            risk = json.loads(row["risk_policy_json"] or "{}")
            key = f"bank:{row['bank_id']}:{row['currency_code']}"
            balance = economy.ledger.balance(row["reserve_account_id"])
            resources[key] = {"balance_cents": balance, "committed_cents": 0, "available_cents": balance}
            leverage = row["amount_cents"] / max(1, application["borrower_income_cents"])
            rate = int(context["policy_rate_bps"]) + 300 + int(600 * min(1, leverage))
            rate = max(int(risk.get("min_rate_bps", 300)), min(int(risk.get("max_rate_bps", 3000)), rate))
            for term in (180, 360):
                offer({"type": "approve_loan", "application_id": row["id"], "rate_bps": rate, "term_ticks": term},
                      application, {key: row["amount_cents"]}, rank=20 if leverage <= 1.2 else 60)
    if context.get("purpose") == "central_banker":
        context["monetary_bounds"] = {key: int(builder.config.get("central_bank", {}).get(key, default))
                                      for key, default in (("max_step_bps", 50), ("min_rate_bps", 0), ("max_rate_bps", 2000))}
    if context.get("purpose") == "vc_partner" and primary:
        for pitch in context.get("pending_pitches", []):
            offer({"type": "decline_pitch", "pitch_id": pitch["pitch_id"], "reason": "outside current investment preference"}, pitch)
            if not pitch.get("native_startup") and pitch["ask_cents"] > 0:
                for equity in (1500, 2250, 3000):
                    offer({"type": "fund_pitch", "pitch_id": pitch["pitch_id"], "amount": pitch["ask_cents"], "equity_bps": equity},
                          pitch, {f"agent:{aid}:{primary['currency_code']}": pitch["ask_cents"]}, rank=30)

    startup = context.setdefault("startup_work", {"eligible_actions": []})
    actions = startup.setdefault("eligible_actions", [])
    if context.get("purpose") == "vc_partner":
        for pitch in context.get("pending_pitches", []):
            work = builder._startup_work(actor, tick, pending_pitches=[pitch],
                fund_cash=int(context.get("fund_cash", primary["balance_cents"] if primary else 0)),
                fund_currency=primary["currency_code"] if primary else None)
            actions.extend(work["eligible_actions"])
    if firm:
        actions.extend({"type": "accept_term_sheet", "term_sheet_id": row["id"]}
            for row in store.query("SELECT id FROM term_sheets WHERE firm_id=? AND status='offered' "
                "AND founder_accepted_tick IS NULL ORDER BY id", (firm["firm_id"],)))
    variations = []
    for action in actions:
        if action["type"] == "propose_term_sheet":
            for equity in (1500, 2250, 3000):
                item = deepcopy(action)
                item.update(equity_bps=equity,
                    pre_money_cents=max(1, item["amount_cents"] * (10000 - equity) // equity))
                variations.append(item)
        if action["type"] == "pitch_vc":
            for bps in (7500, 12500):
                variations.append({**deepcopy(action), "ask": max(1, action["ask"] * bps // 10000)})
    startup["eligible_actions"] = list({json.dumps(a, sort_keys=True): a for a in actions + variations}.values())

    sponsorship = context.get("compute_sponsorship") or {}
    for action in sponsorship.get("actions", []):
        if firm and action["firm_id"] == firm["firm_id"]:
            amount = economy.cognition._plan_cost(action["tier"]) * action["max_seats"]
            offer(action, {"compute_sponsorship": True, "seats": action["max_seats"]},
                  {f"firm:{firm['firm_id']}:{firm['currency_code']}": amount}, rank=65)

    # Attach complete term sheets to choices, rather than asking a selector to
    # judge an unexplained numeric ID. Only the already authorized action IDs
    # are resolved; no unrelated firm's private financing is exposed.
    startup["terms"] = [dict(row) for identity in sorted({a["term_sheet_id"]
        for a in startup["eligible_actions"] if "term_sheet_id" in a})
        if (row := store.query_one("SELECT * FROM term_sheets WHERE id=?", (identity,))) is not None]

    details = context.setdefault("domain_action_terms", {})
    for action in startup["eligible_actions"]:
        sheet = next((s for s in startup["terms"] if s["id"] == action.get("term_sheet_id")), None)
        if sheet and action["type"] == "close_funding_round":
            details[canonical_json(action)] = {"facts": {"term_sheet": sheet},
                "requirements": {f"agent:{aid}:{sheet['currency_code']}": sheet["amount_cents"]}}
        if action["type"] == "propose_term_sheet":
            details[canonical_json(action)] = {"facts": {"commitment_if_accepted": action["amount_cents"]},
                "requirements": {f"agent:{aid}:{action['currency_code']}": action["amount_cents"]}}
        if action["type"] in {"approve_merger", "close_merger"}:
            merger = store.query_one("SELECT * FROM mergers WHERE id=?", (action["merger_id"],))
            if merger:
                details[canonical_json(action)] = {"facts": {"merger": dict(merger),
                    "settlement": "existing merger engine revalidates both principals and consideration"}}

    # Estate bids are explicit budget offers, never invented market valuations.
    # The wallet ID, currency, exact lot/interest and expiry come from the
    # existing actor-authorized catalog; no other estate accounts are queried.
    for key, available_key, represented_key, id_key, suffix in (
        ("estate_property_market", "available_interests", "represented_interests", "custody_id", "property"),
        ("estate_unlisted_market", "available_lots", "represented_lots", "lot_id", "unlisted")):
        market = context.get(key) or {}
        for item in market.get(available_key, []):
            for wallet in item.get("buyer_wallets", []):
                resource = f"account:{wallet['id']}:{item['currency_code']}"
                # Existing market orders share checking funds with estate bids.
                reserved = next((r["committed_cents"] for k, r in resources.items()
                    if k.startswith("agent:") and r.get("account_id") == wallet["id"]), 0)
                if resource in resources:
                    resources[resource]["committed_cents"] = reserved
                    resources[resource]["available_cents"] = max(0, wallet["balance_cents"] - reserved)
                available = resources.get(resource, {}).get("available_cents", 0)
                for bps in (1000, policy["investment_bps"]):
                    amount = available * bps // 10000
                    if amount <= 0:
                        continue
                    action = {"type": f"place_estate_{suffix}_bid", id_key: item[id_key],
                        "buyer_account_id": wallet["id"], "currency_code": item["currency_code"],
                        "amount_cents": amount, "expires_tick": min(tick + 7, item["latest_expiry_tick"])}
                    if suffix == "unlisted":
                        action["qty"] = item["qty"]
                    offer(action, {"valuation_basis": "declared_budget_offer_not_market_price", "asset": item,
                        "commitment_until_tick": action["expires_tick"]}, {resource: amount}, rank=70)
        for item in market.get(represented_key, []):
            for bid in item.get("bids", []):
                if not bid.get("blocked_reason"):
                    offer({"type": f"accept_estate_{suffix}_bid", "bid_id": bid["id"]},
                          {"asset": item, "bid": bid}, rank=35)
        for bid in market.get("own_bids", []):
            offer(bid["withdraw_action"], {"withdraws_existing_bid": True, "bid": bid}, rank=80)

    _entrepreneurship_options(builder, actor, tick, context)
    # The already versioned startup cache is checkpointed at MORNING. Reuse it
    # for exact founding alternatives rather than creating an unrecorded bypass.
    authorizations = getattr(economy, "_startup_action_authorizations", {})
    supplied = [o["action"] for o in context.get("entrepreneurship_options", [])]
    supplied += (context.get("startup_work") or {}).get("eligible_actions", [])
    if supplied:
        existing = authorizations.get((tick, aid), [])
        distinct = {json.dumps(a, sort_keys=True): a for a in existing + supplied}
        authorizations[(tick, aid)] = deepcopy(list(distinct.values()))
        economy._startup_action_authorizations = authorizations

    from .decision_references import bind_event_references, BINDINGS_KEY
    context[BINDINGS_KEY] = bind_event_references(store, context)


def _entrepreneurship_options(builder, actor, tick, context):
    from .prompts import DEFAULT_ENTREPRENEURSHIP_SECTORS
    initial = context.get("entrepreneurship_opportunity")
    context["entrepreneurship_options"] = []
    if not initial:
        return
    action = initial["action"]
    if action["type"] == "found_company" and action.get("authorization_id"):
        context["entrepreneurship_options"] = [{**deepcopy(initial), "commitment_cents": action["opening_capital"]}]
        return
    settings = builder.config.get("entrepreneurship", {})
    sectors = list(settings.get("eligible_sectors", DEFAULT_ENTREPRENEURSHIP_SECTORS))
    sectors.append(action["sector"])
    region = builder.store.query_one("SELECT specialization_json FROM regions WHERE id=?", (actor["region_id"],))
    if region:
        sectors.extend(json.loads(region["specialization_json"] or "[]"))
    for sector in sorted(set(str(s).lower() for s in sectors)):
        opportunity = builder._entrepreneurship_opportunity(actor, tick, context, candidate_sector=sector)
        if opportunity is None:
            continue
        capital = opportunity["capital"]
        minimum = max(1, int(settings.get("minimum_opening_capital_cents", 100000)))
        maximum = min(capital["affordable_capital_cents"], int(settings.get("maximum_opening_capital_cents", capital["affordable_capital_cents"])))
        for amount in sorted({minimum, capital["opening_capital_cents"], maximum}):
            if minimum <= amount <= maximum:
                item = deepcopy(opportunity)
                item["action"]["opening_capital"] = amount
                item["capital"]["opening_capital_cents"] = amount
                item["commitment_cents"] = amount + capital["permit_fee_cents"]
                item["market"]["recent_sales_basis"] = "sale_event_count_not_units"
                context["entrepreneurship_options"].append(item)
    # An issued permit may have no new native opportunity; keep its exact terms.
    if not context["entrepreneurship_options"]:
        context["entrepreneurship_options"] = [{**deepcopy(initial), "commitment_cents": int(action.get("opening_capital", 0))}]
