"""Bounded read-only Oracle choices; hypotheses and resolution stay in code."""
from .tools import oracle_tool_definitions, validate_oracle_plan
from agents.selection_services import SelectionService


async def select_plan(oracle, question, tick, governed_contract):
    catalog = oracle_tool_definitions(oracle.store, tick=tick)
    by_name = {item["name"]: item for item in catalog}
    queries = []
    names = by_name.get("query_metrics", {}).get("available_metric_names", [])
    preferred = [name for name in names if name in {"gdp_proxy", "cpi", "unemployment", "sentiment", "tax_rate_bps"}]
    if preferred:
        queries.append({"tool": "query_metrics", "args": {"names": preferred,
            "from_tick": max(0, tick - 30), "to_tick": tick, "limit": 200}})
    rule = (governed_contract or {}).get("resolution_rule", {})
    metric = rule.get("metric") or rule.get("name")
    if metric in names and metric not in preferred:
        queries.append({"tool": "query_metrics", "args": {"names": [metric],
            "from_tick": max(0, tick - 30), "to_tick": tick, "limit": 200}})
    queries.extend([
        {"tool": "read_news", "args": {"from_tick": max(0, tick - 7), "to_tick": tick, "limit": 10}},
        {"tool": "read_order_book", "args": {"depth": 10}},
        {"tool": "sample_conversations", "args": {"from_tick": max(0, tick - 7), "to_tick": tick, "limit": 10}},
    ])
    for entity in by_name.get("get_ledger_summary", {}).get("available_entity_types", []):
        queries.append({"tool": "get_ledger_summary", "args": {"entity_type": entity}})
    plans = {f"plan_{i}": {"queries": [query]} for i, query in enumerate(queries)}
    if queries:
        plans["overview"] = {"queries": queries[:oracle.tools.MAX_QUERIES]}
    for plan in plans.values():
        validate_oracle_plan(plan, current_tick=tick, tool_catalog=catalog, max_queries=oracle.tools.MAX_QUERIES)
    criteria = {**plans, "none": {"meaning": "None of these read plans addresses the question"}}
    selector = SelectionService(oracle.gw, oracle.config)
    receipt = await selector.evaluate("oracle_tools", actor_id=None, tick=tick,
        state={"question": question, "tick": tick, "governed_contract": governed_contract},
        questions={"plan": {"type": "choice", "instructions":
            "Choose the complete read-only evidence plan useful for the question. No execution or settlement authority is granted.",
            "criteria": criteria}}, baseline={"plan": {"type": "choice", "choice": "overview" if queries else "none"}})
    choice = selector.accepted_choice(receipt, "plan")
    return plans.get(choice, {"queries": []})


async def select_probability(oracle, question, tick, contract, evidence):
    contract = oracle._normalize_governed_contract(contract, tick=tick)
    if contract is None:
        raise ValueError("typed probability requires a governed forecast contract")
    selector = SelectionService(oracle.gw, oracle.config)
    receipt = await selector.evaluate("oracle_forecast", actor_id=None, tick=tick,
        state={"question": question, "as_of_tick": tick, "resolution_rule": contract["resolution_rule"],
               "deadline_tick": contract["deadline_tick"], "read_only_evidence": evidence},
        questions={"occurs": {"type": "noul", "instructions":
            "Estimate the probability that the supplied deterministic resolution rule evaluates true at its deadline. Use only the supplied evidence."}},
        baseline={"occurs": {"type": "noul", "noul": .5}})
    return receipt["answers"]["occurs"]["noul"]
