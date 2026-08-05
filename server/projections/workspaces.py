"""Deterministic, ordinary-observer projections for route-native World OS workspaces."""
from __future__ import annotations

from typing import Any

from engine.store import load_json


def _dicts(rows) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def _json_fields(row: dict[str, Any], *fields: str) -> dict[str, Any]:
    for field in fields:
        if field in row:
            row[field.removesuffix("_json")] = load_json(row.pop(field), {} if field != "source_event_ids_json" else [])
    return row


def _config(store) -> dict[str, Any]:
    return load_json(store.get_meta()["config_json"], {}) or {}


def _firm_status(row: dict[str, Any], as_of_tick: int) -> str:
    bankrupt = row.get("bankrupt_tick")
    listed = row.get("listed_tick")
    if bankrupt is not None and int(bankrupt) <= as_of_tick:
        return "bankrupt"
    if listed is not None and int(listed) <= as_of_tick:
        return "listed"
    return "private"


def _balances_as_of(store, account_ids, as_of_tick: int) -> dict[int, int]:
    relevant = sorted({int(account_id) for account_id in account_ids
                       if account_id is not None})
    if not relevant:
        return {}
    placeholders = ",".join("?" for _ in relevant)
    return {
        int(row["account_id"]): int(row["balance"])
        for row in store.query(
            "SELECT account_id,COALESCE(SUM(delta_cents),0) AS balance "
            f"FROM ledger_entries WHERE tick<=? AND account_id IN ({placeholders}) "
            "GROUP BY account_id",
            (int(as_of_tick), *relevant),
        )
    }


def _mask_future_ticks(row: dict[str, Any], as_of_tick: int, *fields: str) -> None:
    for field in fields:
        value = row.get(field)
        if value is not None and int(value) > int(as_of_tick):
            row[field] = None


def _firms_as_of(store, as_of_tick: int) -> list[dict[str, Any]]:
    rows = _dicts(store.query(
        "SELECT f.id,f.name,f.sector,f.account_id,f.founded_tick,f.listed_tick,"
        "f.bankrupt_tick,f.region_id,r.name AS region_name,r.currency_code "
        "FROM firms f LEFT JOIN regions r ON r.id=f.region_id "
        "WHERE f.founded_tick<=? ORDER BY f.id", (int(as_of_tick),)))
    employment = {
        int(row["firm_id"]): int(row["n"])
        for row in store.query(
            "SELECT firm_id,COUNT(*) AS n FROM employments WHERE start_tick<=? "
            "AND (end_tick IS NULL OR end_tick>?) GROUP BY firm_id",
            (int(as_of_tick), int(as_of_tick)))
    }
    balances = _balances_as_of(
        store, (row.get("account_id") for row in rows), as_of_tick)
    result = []
    for row in rows:
        status = _firm_status(row, as_of_tick)
        _mask_future_ticks(row, as_of_tick, "listed_tick", "bankrupt_tick")
        account_id = row.pop("account_id", None)
        row["status"] = status
        row["active"] = status != "bankrupt"
        row["employees"] = employment.get(int(row["id"]), 0)
        row["balance_cents"] = balances.get(int(account_id), 0) if account_id is not None else None
        result.append(row)
    return result


def _banks_as_of(store, as_of_tick: int) -> list[dict[str, Any]]:
    rows = _dicts(store.query(
        "SELECT id,name,reserve_account_id,equity_account_id,reserve_requirement_bps,"
        "failed_tick FROM banks ORDER BY id"))
    balances = _balances_as_of(
        store,
        (account_id for row in rows
         for account_id in (row.get("reserve_account_id"), row.get("equity_account_id"))),
        as_of_tick,
    )
    for row in rows:
        failed = row.pop("failed_tick", None)
        row["status"] = "failed" if failed is not None and int(failed) <= as_of_tick else "open"
        row["active"] = row["status"] == "open"
        row["reserve_cents"] = balances.get(int(row.pop("reserve_account_id")), 0)
        row["equity_cents"] = balances.get(int(row.pop("equity_account_id")), 0)
        row["currency_code"] = "USD"
    return rows


def _agent_regions_at(
    store, agents: list[dict[str, Any]], as_of_tick: int,
) -> dict[int, int | None]:
    tick = int(as_of_tick)
    result = {
        int(agent["id"]): (
            int(agent["region_id"]) if agent.get("region_id") is not None else None
        )
        for agent in agents
    }
    completed = store.query(
        "SELECT agent_id,destination_region_id FROM ("
        "SELECT agent_id,destination_region_id,ROW_NUMBER() OVER ("
        "PARTITION BY agent_id ORDER BY completed_tick DESC,id DESC) AS position "
        "FROM migrations WHERE completed_tick IS NOT NULL AND completed_tick<=?) "
        "WHERE position=1",
        (tick,),
    )
    completed_agents = set()
    for row in completed:
        agent_id = int(row["agent_id"])
        if agent_id in result:
            result[agent_id] = int(row["destination_region_id"])
            completed_agents.add(agent_id)
    future = store.query(
        "SELECT agent_id,origin_region_id FROM ("
        "SELECT agent_id,origin_region_id,ROW_NUMBER() OVER ("
        "PARTITION BY agent_id ORDER BY completed_tick,id) AS position "
        "FROM migrations WHERE completed_tick>?) WHERE position=1",
        (tick,),
    )
    for row in future:
        agent_id = int(row["agent_id"])
        if agent_id in result and agent_id not in completed_agents:
            result[agent_id] = int(row["origin_region_id"])
    return result


def build_world_workspace(store, *, as_of_tick: int) -> dict:
    tick = int(as_of_tick)
    regions = [_json_fields(row, "specialization_json") for row in _dicts(store.query(
        "SELECT id,region_key,name,currency_code,population_target,specialization_json,x,y,"
        "legal_ruleset FROM regions ORDER BY id"))]
    region_by_id = {int(row["id"]): row for row in regions}
    agents = _dicts(store.query(
        "SELECT id,name,role,occupation,population_tier,region_id,arrived_tick,died_tick "
        "FROM agents WHERE arrived_tick<=? AND (died_tick IS NULL OR died_tick>?) ORDER BY id",
        (tick, tick)))
    agent_regions = _agent_regions_at(store, agents, tick)
    for agent in agents:
        _mask_future_ticks(agent, tick, "died_tick")
        agent["region_id"] = agent_regions[int(agent["id"])]
        region = region_by_id.get(agent["region_id"])
        agent["region_name"] = region["name"] if region else None
    places = [_json_fields(row, "metadata_json") for row in _dicts(store.query(
        "SELECT id,place_key,region_id,name,kind,owner_type,owner_id,x,y,capacity,"
        "created_tick,closed_tick,metadata_json FROM places WHERE created_tick<=? "
        "AND (closed_tick IS NULL OR closed_tick>?) ORDER BY id", (tick, tick)))]
    for place in places:
        _mask_future_ticks(place, tick, "closed_tick")
    presence = _dicts(store.query(
        "SELECT ep.id,ep.tick,ep.slot,ep.agent_id,ep.place_id,ep.source_type "
        "FROM effective_presence ep WHERE ep.tick=? ORDER BY ep.slot,ep.agent_id", (tick,)))
    organizations = [row for row in _firms_as_of(store, tick) if row["active"]]
    migrations = _dicts(store.query(
        "SELECT id,agent_id,origin_region_id,destination_region_id,requested_tick AS tick,"
        "completed_tick,status FROM migrations WHERE requested_tick<=? ORDER BY requested_tick,id",
        (tick,)))
    for migration in migrations:
        if (migration["completed_tick"] is not None
                and int(migration["completed_tick"]) > tick):
            migration.update({"completed_tick": None, "status": "pending"})
    shipments = _dicts(store.query(
        "SELECT id,created_tick AS tick,exporter_firm_id,importer_firm_id,origin_region_id,"
        "destination_region_id,quantity,invoice_cents,invoice_currency,arrival_tick,status "
        "FROM trade_shipments WHERE created_tick<=? ORDER BY created_tick,id", (tick,)))
    for shipment in shipments:
        if int(shipment["arrival_tick"]) > tick:
            shipment.update({"arrival_tick": None, "status": "in_transit"})
    flows = [
        {"kind": "migration", **row} for row in migrations
    ] + [
        {"kind": "trade", **row} for row in shipments
    ]
    currencies = sorted({str(row["currency_code"]) for row in regions if row.get("currency_code")})
    return {
        "enabled": bool(regions), "regions": regions, "agents": agents,
        "organizations": organizations, "places": places, "presence": presence,
        "flows": flows,
        "summary": {
            "population": len(agents), "active_organizations": len(organizations),
            "currencies": currencies, "migration_count": len(migrations),
            "trade_count": len(shipments),
        },
    }


def build_organizations_workspace(store, *, as_of_tick: int) -> dict:
    tick = int(as_of_tick)
    config = _config(store)
    firms = _firms_as_of(store, tick)
    banks = _banks_as_of(store, tick)
    agencies = _dicts(store.query(
        "SELECT a.id,a.name,a.mandate,a.capacity,a.leader_agent_id FROM agencies a ORDER BY a.id"))
    for row in agencies:
        row.update({"type": "agency", "status": "active", "active": True})
    contracts = [_json_fields(row, "metadata_json") for row in _dicts(store.query(
        "SELECT id,contract_type,title,jurisdiction,ruleset_key,offered_tick,executed_tick,"
        "effective_tick,expiry_tick,terminated_tick,metadata_json FROM contracts "
        "WHERE offered_tick<=? ORDER BY offered_tick,id", (tick,)))]
    for row in contracts:
        row["status"] = _contract_status(row, tick)
        _mask_future_ticks(
            row, tick, "executed_tick", "effective_tick", "expiry_tick",
            "terminated_tick")
    disclosures = [_json_fields(row, "facts_json", "source_event_ids_json") for row in _dicts(store.query(
        "SELECT id,tick,firm_id,disclosure_type,period_start_tick,period_end_tick,facts_json,"
        "source_event_ids_json FROM firm_disclosures WHERE tick<=? ORDER BY tick,id", (tick,)))]
    organizations = [
        {"type": "firm", **row} for row in firms
    ] + [
        {"type": "bank", **row} for row in banks
    ] + agencies
    organizations.sort(key=lambda row: (str(row["type"]), int(row["id"])))
    return {
        "organizations": organizations,
        "firms": firms,
        "banks": banks,
        "institutions": {
            "legal_enabled": bool(config.get("legal", {}).get("enabled", False)),
            "politics_enabled": bool(config.get("politics", {}).get("enabled", False)),
            "agencies": agencies,
        },
        "contracts": contracts,
        "disclosures": disclosures,
    }


def _market_orders(store, table: str, trades_table: str, as_of_tick: int) -> list[dict[str, Any]]:
    rows = _dicts(store.query(
        f"SELECT * FROM (SELECT * FROM {table} WHERE tick<=? "
        "ORDER BY tick DESC,id DESC LIMIT 100) ORDER BY tick,id",
        (int(as_of_tick),)))
    order_ids = [int(row["id"]) for row in rows]
    filled_by_order: dict[int, int] = {}
    if order_ids:
        placeholders = ",".join("?" for _ in order_ids)
        if table == "orders":
            fills = store.query(
                "SELECT order_id,COALESCE(SUM(amount),0) AS filled FROM ("
                f"SELECT buy_order_id AS order_id,qty AS amount FROM {trades_table} "
                f"WHERE tick<=? AND buy_order_id IN ({placeholders}) UNION ALL "
                f"SELECT sell_order_id AS order_id,qty AS amount FROM {trades_table} "
                f"WHERE tick<=? AND sell_order_id IN ({placeholders}) "
                "AND sell_order_id<>buy_order_id) GROUP BY order_id",
                (int(as_of_tick), *order_ids, int(as_of_tick), *order_ids),
            )
        else:
            fills = store.query(
                "SELECT order_id,COALESCE(SUM(base_qty),0) AS filled "
                f"FROM {trades_table} WHERE tick<=? AND order_id IN ({placeholders}) "
                "GROUP BY order_id",
                (int(as_of_tick), *order_ids),
            )
        filled_by_order = {
            int(row["order_id"]): int(row["filled"]) for row in fills
        }
    for row in rows:
        filled = filled_by_order.get(int(row["id"]), 0)
        remaining = max(0, int(row["qty"]) - filled)
        row["qty_remaining"] = remaining
        row["status"] = "filled" if remaining == 0 else "partial" if filled else "open"
    return rows


def build_markets_workspace(store, *, as_of_tick: int) -> dict:
    tick = int(as_of_tick)
    orders = _market_orders(store, "orders", "trades", tick)
    trades = _dicts(store.query(
        "SELECT t.id,t.tick,t.firm_id,f.name AS firm_name,t.buy_order_id,t.sell_order_id,"
        "t.qty,t.price_cents FROM (SELECT * FROM trades WHERE tick<=? "
        "ORDER BY tick DESC,id DESC LIMIT 100) t LEFT JOIN firms f ON f.id=t.firm_id "
        "ORDER BY t.tick,t.id", (tick,)))
    fx_orders = _market_orders(store, "fx_orders", "fx_trades", tick)
    fx_trades = _dicts(store.query(
        "SELECT id,tick,order_id,actor_id,pair,side,base_qty,quote_qty,rate_ppm "
        "FROM (SELECT * FROM fx_trades WHERE tick<=? "
        "ORDER BY tick DESC,id DESC LIMIT 100) ORDER BY tick,id", (tick,)))
    circuit_breakers = _dicts(store.query(
        "SELECT id,tick,phase,kind,subject_type,subject_id,importance FROM events "
        "WHERE tick<=? AND kind LIKE '%circuit%' ORDER BY tick,id", (tick,)))
    metrics = _dicts(store.query(
        "SELECT tick,name,value FROM metrics WHERE tick<=? ORDER BY tick DESC,id DESC LIMIT 200",
        (tick,)))
    metrics.reverse()
    currencies = _dicts(store.query(
        "SELECT code,name,minor_unit,numeraire_rate_ppm FROM currencies ORDER BY code"))
    return {
        "orders": orders, "trades": trades, "fx_orders": fx_orders,
        "fx_trades": fx_trades, "circuit_breakers": circuit_breakers,
        "metrics": metrics, "currencies": currencies,
    }


def _contract_status(row: dict[str, Any], tick: int) -> str:
    if row.get("terminated_tick") is not None and int(row["terminated_tick"]) <= tick:
        return "terminated"
    if row.get("expiry_tick") is not None and int(row["expiry_tick"]) <= tick:
        return "expired"
    if row.get("executed_tick") is not None and int(row["executed_tick"]) <= tick:
        return "executed"
    return "offered"


def build_politics_law_workspace(store, *, as_of_tick: int) -> dict:
    tick = int(as_of_tick)
    config = _config(store)
    bills = [_json_fields(row, "policy_changes_json", "metadata_json") for row in _dicts(store.query(
        "SELECT id,bill_key,title,origin_chamber,committee_id,introduced_tick,"
        "executive_action_tick,effective_tick,policy_changes_json,metadata_json "
        "FROM bills WHERE introduced_tick<=? ORDER BY introduced_tick,id", (tick,)))]
    for row in bills:
        action = store.query_one(
            "SELECT action_type,tick FROM bill_actions WHERE bill_id=? AND tick<=? "
            "ORDER BY tick DESC,id DESC LIMIT 1", (int(row["id"]), tick))
        version = store.scalar(
            "SELECT COALESCE(MAX(version),1) FROM bill_versions WHERE bill_id=? AND tick<=?",
            (int(row["id"]), tick), default=1)
        row["status"] = str(action["action_type"]) if action else "introduced"
        row["current_version"] = int(version or 1)
        _mask_future_ticks(row, tick, "executive_action_tick", "effective_tick")
    versions = [_json_fields(row, "text_json") for row in _dicts(store.query(
        "SELECT id,bill_id,version,tick,summary,text_json FROM bill_versions "
        "WHERE tick<=? ORDER BY tick,id", (tick,)))]
    votes = _dicts(store.query(
        "SELECT id,bill_id,version,legislator_id,stage,vote,tick FROM legislative_votes "
        "WHERE tick<=? ORDER BY tick,id", (tick,)))
    rules = [_json_fields(row, "value_json") for row in _dicts(store.query(
        "SELECT id,bill_id,rule_key,value_json,enacted_tick,effective_tick,status "
        "FROM policy_rules WHERE enacted_tick<=? ORDER BY enacted_tick,id", (tick,)))]
    for row in rules:
        if int(row["effective_tick"]) > tick:
            row["status"] = "pending"
        _mask_future_ticks(row, tick, "effective_tick")
    lobbying = _dicts(store.query(
        "SELECT id,tick,sponsor_type,sponsor_id,bill_id,activity_type,position,amount_cents,"
        "disclosure_tick,disclosed FROM lobbying_activities WHERE tick<=? ORDER BY tick,id",
        (tick,)))
    for row in lobbying:
        if int(row["disclosure_tick"]) > tick:
            row["disclosed"] = 0
        _mask_future_ticks(row, tick, "disclosure_tick")
    contracts = [_json_fields(row, "metadata_json") for row in _dicts(store.query(
        "SELECT id,contract_type,title,jurisdiction,ruleset_key,offered_tick,executed_tick,"
        "expiry_tick,terminated_tick,metadata_json FROM contracts WHERE offered_tick<=? "
        "ORDER BY offered_tick,id", (tick,)))]
    for row in contracts:
        row["status"] = _contract_status(row, tick)
        _mask_future_ticks(
            row, tick, "executed_tick", "expiry_tick", "terminated_tick")
    obligations = [_json_fields(row, "terms_json") for row in _dicts(store.query(
        "SELECT o.id,o.contract_id,o.obligation_type,o.due_tick,o.grace_ticks,o.amount_cents,"
        "o.currency_code,o.performed_tick,o.breached_tick,o.terms_json "
        "FROM obligations o JOIN contracts c ON c.id=o.contract_id "
        "WHERE c.offered_tick<=? ORDER BY o.due_tick,o.id", (tick,)))]
    for row in obligations:
        if row["breached_tick"] is not None and int(row["breached_tick"]) <= tick:
            row["status"] = "breached"
        elif row["performed_tick"] is not None and int(row["performed_tick"]) <= tick:
            row["status"] = "performed"
        else:
            row["status"] = "pending"
        _mask_future_ticks(row, tick, "performed_tick", "breached_tick")
    matters = [_json_fields(row, "requested_remedy_json", "settlement_json", "metadata_json") for row in _dicts(store.query(
        "SELECT id,matter_type,venue,contract_id,claim_type,filed_tick,response_due_tick,"
        "resolved_tick,requested_remedy_json,settlement_json,metadata_json FROM legal_matters "
        "WHERE filed_tick<=? ORDER BY filed_tick,id", (tick,)))]
    for row in matters:
        row["status"] = "resolved" if row["resolved_tick"] is not None and int(row["resolved_tick"]) <= tick else "filed"
        _mask_future_ticks(row, tick, "resolved_tick")
    mergers = [_json_fields(row, "metadata_json") for row in _dicts(store.query(
        "SELECT id,proposed_tick,acquirer_firm_id,target_firm_id,consideration_type,price_cents,"
        "currency_code,target_approved_tick,regulator_notified_tick,closed_tick,terminated_tick,"
        "metadata_json FROM mergers WHERE proposed_tick<=? ORDER BY proposed_tick,id", (tick,)))]
    for row in mergers:
        if row["terminated_tick"] is not None and int(row["terminated_tick"]) <= tick:
            row["status"] = "terminated"
        elif row["closed_tick"] is not None and int(row["closed_tick"]) <= tick:
            row["status"] = "closed"
        elif row["regulator_notified_tick"] is not None and int(row["regulator_notified_tick"]) <= tick:
            row["status"] = "under_review"
        elif row["target_approved_tick"] is not None and int(row["target_approved_tick"]) <= tick:
            row["status"] = "approved"
        else:
            row["status"] = "proposed"
        _mask_future_ticks(
            row, tick, "target_approved_tick", "regulator_notified_tick",
            "closed_tick", "terminated_tick")
    reviews = [_json_fields(row, "remedy_json") for row in _dicts(store.query(
        "SELECT id,merger_id,tick,pre_hhi,post_hhi,delta_hhi,threshold_hhi,threshold_delta,"
        "outcome,remedy_json FROM merger_reviews WHERE tick<=? ORDER BY tick,id", (tick,)))]
    return {
        "politics": {
            "enabled": bool(config.get("politics", {}).get("enabled", False)),
            "institutional_actions_enabled": bool(config.get("politics", {}).get(
                "institutional_actions_enabled", False)),
        },
        "legal": {"enabled": bool(config.get("legal", {}).get("enabled", False))},
        "bills": bills, "bill_versions": versions, "votes": votes, "rules": rules,
        "lobbying": lobbying, "contracts": contracts, "obligations": obligations,
        "matters": matters, "mergers": mergers, "merger_reviews": reviews,
    }


def build_experiments_workspace(store, *, as_of_tick: int) -> dict:
    tick = int(as_of_tick)
    checkpoints = _dicts(store.query(
        "SELECT id,tick,created_at FROM checkpoints WHERE tick<=? ORDER BY tick,id", (tick,)))
    shocks = [_json_fields(row, "trigger_json", "params_json") for row in _dicts(store.query(
        "SELECT id,kind,trigger_type,trigger_json,duration_ticks,params_json,label,fired,"
        "fired_tick,active_until_tick FROM shocks WHERE fired_tick IS NULL OR fired_tick<=? "
        "ORDER BY COALESCE(fired_tick,0),id", (tick,)))]
    predictions = [_json_fields(row, "drivers_json", "resolution_rule_json", "evidence_json") for row in _dicts(store.query(
        "SELECT id,asked_tick,question,p,confidence,drivers_json,resolution_rule_json,deadline_tick,"
        "resolved_tick,outcome,brier,evidence_json,status FROM predictions WHERE asked_tick<=? "
        "ORDER BY asked_tick,id", (tick,)))]
    for row in predictions:
        if row["resolved_tick"] is not None and int(row["resolved_tick"]) > tick:
            row.update({"resolved_tick": None, "outcome": None, "brier": None, "status": "open"})
    acceptance = _dicts(store.query(
        "SELECT id,scheduled_tick,question,status,prediction_id,detail FROM acceptance_checkpoints "
        "WHERE scheduled_tick<=? ORDER BY scheduled_tick,id", (tick,)))
    datasets = [_json_fields(row, "metadata_json") for row in _dicts(store.query(
        "SELECT id,dataset_key,release_date,vintage_date,checksum_sha256,transform_version,"
        "usage_terms,status,metadata_json FROM dataset_manifests ORDER BY id"))]
    scenarios = [_json_fields(row, "metadata_json") for row in _dicts(store.query(
        "SELECT id,scenario_key,version,title,manifest_checksum,limitations,metadata_json "
        "FROM scenario_packs ORDER BY id"))]
    current = tick == int(store.tick)
    experiments = []
    results = []
    if current:
        experiments = [_json_fields(row, "paired_seeds_json", "treatment_variables_json") for row in _dicts(store.query(
            "SELECT id,experiment_key,scenario_key,created_at,checkpoint_hash,paired_seeds_json,"
            "treatment_variables_json,status FROM counterfactual_experiments ORDER BY id"))]
        results = [_json_fields(row, "metrics_json", "causal_trace_json") for row in _dicts(store.query(
            "SELECT id,experiment_id,arm,seed,run_id,replay_hash,metrics_json,causal_trace_json "
            "FROM counterfactual_results ORDER BY experiment_id,arm,seed,id"))]
    meta = store.get_meta()
    return {
        "run": {
            "run_id": str(meta["run_id"]), "parent_run_id": meta["parent_run_id"],
            "fork_tick": meta["fork_tick"], "status": str(meta["status"]),
        },
        "checkpoints": checkpoints, "shocks": shocks, "predictions": predictions,
        "acceptance": acceptance, "datasets": datasets, "scenarios": scenarios,
        "experiments": experiments, "results": results,
        "current_only_artifacts_omitted": not current,
    }
