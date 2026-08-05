"""As-of, lineage, and privacy contracts for route-native World OS workspaces."""
from __future__ import annotations

import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.projections import (
    build_experiments_workspace,
    build_markets_workspace,
    build_organizations_workspace,
    build_politics_law_workspace,
    build_world_workspace,
)
from server.v2_api import install_v2_routes


def _seed_workspace_history(economy) -> None:
    store = economy.store
    store.set_meta(
        tick=10, status="paused", phase="FINALIZE",
        config_json=json.dumps({
            "engine_semantics_version": 12,
            "legal": {"enabled": True},
            "politics": {"enabled": True, "institutional_actions_enabled": True},
        }, sort_keys=True),
    )
    store.execute(
        "INSERT INTO regions (id,region_key,name,currency_code,population_target,"
        "specialization_json,x,y,legal_ruleset) VALUES (1,'north','North','USD',10,'{}',.2,.3,'rules')")
    store.execute(
        "INSERT INTO currencies (code,name,minor_unit,numeraire_rate_ppm,issuer_region_id) "
        "VALUES ('USD','Dollar',2,1000000,1)")
    store.execute(
        "INSERT INTO agents (id,name,kind,occupation,age,alive,arrived_tick,region_id,population_tier) "
        "VALUES (1,'Public Agent','citizen','worker',30,1,0,1,'core')")
    store.execute("UPDATE agents SET died_tick=9 WHERE id=1")
    store.execute(
        "INSERT INTO firms (id,name,sector,status,founded_tick,listed_tick,bankrupt_tick,region_id) "
        "VALUES (1,'Past Firm','food','bankrupt',2,8,9,1)")
    store.execute(
        "INSERT INTO firms (id,name,sector,status,founded_tick,region_id) "
        "VALUES (2,'future-order-canary','tech','private',9,1)")
    store.execute(
        "INSERT INTO accounts (id,owner_type,owner_id,kind,label,balance_cents) "
        "VALUES (900,'firm',1,'checking','workspace firm',125)")
    store.execute("UPDATE firms SET account_id=900 WHERE id=1")
    store.execute(
        "INSERT INTO transactions (id,tick,kind,memo) VALUES (900,3,'seed','workspace')")
    store.execute(
        "INSERT INTO ledger_entries (id,tick,txn_id,account_id,delta_cents) "
        "VALUES (900,3,900,900,125)")
    store.execute(
        "INSERT INTO orders (id,tick,agent_id,firm_id,side,qty,qty_remaining,seq,status) "
        "VALUES (1,4,1,1,'buy',3,3,1,'filled'),(2,9,1,2,'sell',7,7,2,'open')")
    store.execute(
        "INSERT INTO trades (id,tick,firm_id,buy_order_id,sell_order_id,buyer_id,seller_id,qty,price_cents) "
        "VALUES (1,4,1,1,1,1,2,3,125),(2,9,2,2,2,1,2,7,900)")
    store.execute(
        "INSERT INTO fx_orders (id,tick,actor_id,pair,base_currency,quote_currency,side,qty,qty_remaining,seq,status) "
        "VALUES (1,4,1,'USD/USD','USD','USD','buy',5,0,1,'filled'),"
        "(2,9,1,'USD/USD','USD','USD','sell',9,9,2,'open')")
    store.execute(
        "INSERT INTO fx_trades (id,tick,order_id,actor_id,pair,side,base_qty,quote_qty,rate_ppm,base_account_id,quote_account_id) "
        "VALUES (1,4,1,1,'USD/USD','buy',5,5,1000000,1,1),"
        "(2,9,2,1,'USD/USD','sell',9,9,1000000,1,1)")
    store.execute(
        "INSERT INTO committees (id,name,chamber,jurisdiction) VALUES (1,'Finance','assembly','national')")
    store.execute(
        "INSERT INTO legislators (id,agent_id,chamber,seat_number,party_id,term_start_tick,term_end_tick,active) "
        "VALUES (1,1,'assembly',1,1,0,100,1)")
    store.execute(
        "INSERT INTO bills (id,bill_key,title,sponsor_legislator_id,origin_chamber,committee_id,status,current_version,introduced_tick,policy_changes_json,metadata_json) "
        "VALUES (1,'B-1','Past bill',1,'assembly',1,'enacted',1,4,'{}','{}'),"
        "(2,'B-2','future-bill-canary',1,'assembly',1,'introduced',1,9,'{}','{}')")
    store.execute(
        "INSERT INTO bill_versions (id,bill_id,version,tick,author_legislator_id,summary,text_json) "
        "VALUES (1,1,1,4,1,'past','{}'),(2,2,1,9,1,'future','{}')")
    store.execute(
        "INSERT INTO legislative_votes (id,bill_id,version,legislator_id,stage,vote,tick) "
        "VALUES (1,1,1,1,'floor','yes',4),(2,2,1,1,'floor','yes',9)")
    store.execute(
        "INSERT INTO policy_rules (id,bill_id,rule_key,value_json,enacted_tick,effective_tick,status) "
        "VALUES (1,1,'past-rule','{}',4,9,'active'),(2,2,'future-rule-canary','{}',9,9,'active')")
    store.execute(
        "UPDATE bills SET executive_action_tick=8,effective_tick=9 WHERE id=1")
    store.execute(
        "INSERT INTO lobbying_activities (id,tick,sponsor_type,sponsor_id,lobbyist_agent_id,"
        "target_agent_id,bill_id,activity_type,position,amount_cents,transaction_id,"
        "salience_effect,disclosure_tick,disclosed) "
        "VALUES (1,4,'firm',1,1,1,1,'meeting','support',50,900,.1,9,1)")
    store.execute(
        "INSERT INTO places (id,place_key,region_id,name,kind,owner_type,owner_id,x,y,capacity,"
        "created_tick,closed_tick,metadata_json) VALUES "
        "(1,'north-commons',1,'North Commons','public_commons','region',1,.2,.3,10,4,9,'{}')")
    store.execute(
        "INSERT INTO migrations (id,agent_id,origin_region_id,destination_region_id,"
        "requested_tick,completed_tick,status) VALUES (1,1,1,1,4,9,'completed')")
    store.execute(
        "INSERT INTO trade_shipments (id,created_tick,exporter_firm_id,importer_firm_id,"
        "origin_region_id,destination_region_id,quantity,invoice_cents,invoice_currency,"
        "arrival_tick,status) VALUES (1,4,1,1,1,1,2,100,'USD',9,'delivered')")
    store.execute(
        "INSERT INTO legal_matters (id,matter_type,venue,status,claimant_type,claimant_id,respondent_type,respondent_id,claim_type,filed_tick,response_due_tick,requested_remedy_json,metadata_json) "
        "VALUES (1,'civil','court','filed','agent',1,'firm',1,'breach',4,8,'{}','{}'),"
        "(2,'civil','court','filed','agent',1,'firm',2,'future-case-canary',9,12,'{}','{}')")
    store.execute(
        "UPDATE legal_matters SET resolved_tick=9,settlement_json='{}' WHERE id=1")
    store.execute(
        "INSERT INTO contracts (id,contract_type,title,jurisdiction,ruleset_key,drafter_agent_id,"
        "offered_tick,executed_tick,effective_tick,expiry_tick,terminated_tick,metadata_json) "
        "VALUES (1,'sale','Lifecycle contract','national','rules',1,4,5,6,8,9,'{}')")
    store.execute(
        "INSERT INTO obligations (id,contract_id,clause_id,obligation_type,obligor_type,"
        "obligor_id,obligee_type,obligee_id,due_tick,performed_tick,breached_tick,terms_json) "
        "VALUES (1,1,1,'pay','firm',1,'agent',1,6,7,8,'{}')")
    store.execute(
        "INSERT INTO mergers (id,proposed_tick,acquirer_firm_id,target_firm_id,proposer_agent_id,"
        "price_cents,target_approved_tick,regulator_notified_tick,closed_tick,terminated_tick,metadata_json) "
        "VALUES (1,4,1,2,1,1000,5,6,8,9,'{}')")
    store.execute(
        "INSERT INTO checkpoints (id,tick,path,created_at) VALUES (1,4,'safe.db','now'),(2,9,'future-checkpoint-canary','later')")
    store.execute(
        "INSERT INTO shocks (id,kind,trigger_type,trigger_json,label,fired,fired_tick) "
        "VALUES (1,'oil','shock','{}','past shock',1,4),(2,'oil','shock','{}','future-shock-canary',1,9)")
    store.execute(
        "INSERT INTO llm_calls (id,tick,agent_id,role,provider,model,purpose,response_json) "
        "VALUES (1,4,1,'citizen','private','private','decision','private-communication-canary')")
    store.commit()


def test_workspace_builders_are_as_of_and_exclude_private_or_future_rows(economy):
    _seed_workspace_history(economy)
    world = SimpleNamespace(store=economy.store, config=economy.config, economy=economy)
    payloads = {
        "world": build_world_workspace(economy.store, as_of_tick=4),
        "organizations": build_organizations_workspace(economy.store, as_of_tick=4),
        "markets": build_markets_workspace(economy.store, as_of_tick=4),
        "politics": build_politics_law_workspace(economy.store, as_of_tick=4),
        "experiments": build_experiments_workspace(economy.store, as_of_tick=4),
    }
    serialized = json.dumps(payloads, sort_keys=True)
    for canary in (
        "future-order-canary", "future-bill-canary", "future-rule-canary",
        "future-case-canary", "future-checkpoint-canary", "future-shock-canary",
        "private-communication-canary",
    ):
        assert canary not in serialized

    markets = payloads["markets"]
    assert [item["tick"] for item in markets["orders"]] == [4]
    assert [item["tick"] for item in markets["trades"]] == [4]
    assert [item["tick"] for item in markets["fx_orders"]] == [4]
    assert [item["tick"] for item in markets["fx_trades"]] == [4]
    assert payloads["organizations"]["organizations"][0]["status"] == "private"
    assert payloads["organizations"]["organizations"][0]["active"] is True
    assert payloads["organizations"]["organizations"][0]["listed_tick"] is None
    assert payloads["organizations"]["organizations"][0]["bankrupt_tick"] is None
    assert payloads["world"]["agents"][0]["died_tick"] is None
    assert payloads["world"]["places"][0]["closed_tick"] is None
    migration = next(item for item in payloads["world"]["flows"] if item["kind"] == "migration")
    assert migration["status"] == "pending"
    assert migration["completed_tick"] is None
    shipment = next(item for item in payloads["world"]["flows"] if item["kind"] == "trade")
    assert shipment["status"] == "in_transit"
    assert shipment["arrival_tick"] is None
    assert [item["tick"] for item in payloads["politics"]["votes"]] == [4]
    assert [item["tick"] for item in payloads["experiments"]["checkpoints"]] == [4]

    organizations_contract = payloads["organizations"]["contracts"][0]
    assert organizations_contract["status"] == "offered"
    for field in ("executed_tick", "effective_tick", "expiry_tick", "terminated_tick"):
        assert organizations_contract[field] is None
    politics = payloads["politics"]
    assert politics["bills"][0]["executive_action_tick"] is None
    assert politics["bills"][0]["effective_tick"] is None
    assert politics["rules"][0]["status"] == "pending"
    assert politics["rules"][0]["effective_tick"] is None
    assert politics["lobbying"][0]["disclosed"] == 0
    assert politics["lobbying"][0]["disclosure_tick"] is None
    assert politics["contracts"][0]["status"] == "offered"
    assert politics["contracts"][0]["executed_tick"] is None
    assert politics["contracts"][0]["expiry_tick"] is None
    assert politics["contracts"][0]["terminated_tick"] is None
    assert politics["obligations"][0]["status"] == "pending"
    assert politics["obligations"][0]["performed_tick"] is None
    assert politics["obligations"][0]["breached_tick"] is None
    assert politics["matters"][0]["status"] == "filed"
    assert politics["matters"][0]["resolved_tick"] is None
    assert politics["mergers"][0]["status"] == "proposed"
    for field in (
        "target_approved_tick", "regulator_notified_tick", "closed_tick", "terminated_tick",
    ):
        assert politics["mergers"][0][field] is None

    at_ten = build_organizations_workspace(economy.store, as_of_tick=10)
    assert next(item for item in at_ten["organizations"] if item["id"] == 1)["status"] == "bankrupt"


def test_workspace_api_returns_canonical_envelopes_and_rejects_bad_lineage(economy, tmp_path):
    _seed_workspace_history(economy)
    world = SimpleNamespace(store=economy.store, config=economy.config, economy=economy)
    controller = SimpleNamespace(hosted_safe=False)
    app = FastAPI()
    install_v2_routes(app, world, controller)
    expected = {
        "world": build_world_workspace(economy.store, as_of_tick=4),
        "organizations": build_organizations_workspace(economy.store, as_of_tick=4),
        "markets": build_markets_workspace(economy.store, as_of_tick=4),
        "politics-law": build_politics_law_workspace(economy.store, as_of_tick=4),
        "experiments": build_experiments_workspace(economy.store, as_of_tick=4),
    }
    with TestClient(app) as client:
        for slug, data in expected.items():
            response = client.get(f"/api/v2/workspaces/{slug}", params={"tick": 4})
            assert response.status_code == 200
            body = response.json()
            assert body["projection"] == f"workspace.{slug.replace('-', '_')}"
            assert body["tick"] == 4
            assert body["run_id"] == economy.store.get_meta()["run_id"]
            assert body["data"] == data
        assert client.get("/api/v2/workspaces/markets", params={"tick": 11}).status_code == 409
        assert client.get(
            "/api/v2/workspaces/markets", params={"fork_id": "wrong"}).status_code == 409
    app.state.operator_workspace.close()


def test_market_workspace_bounds_rows_and_aggregates_fills_without_n_plus_one(economy):
    _seed_workspace_history(economy)
    store = economy.store
    rows = range(100, 205)
    store.executemany(
        "INSERT INTO orders (id,tick,agent_id,firm_id,side,qty,qty_remaining,seq,status) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        [(row, row, 1, 1, "buy", 2, 1, row, "partial") for row in rows],
    )
    store.executemany(
        "INSERT INTO trades (id,tick,firm_id,buy_order_id,sell_order_id,buyer_id,seller_id,qty,price_cents) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        [(row, row, 1, row, row, 1, 1, 1, 100) for row in rows],
    )
    store.executemany(
        "INSERT INTO fx_orders (id,tick,actor_id,pair,base_currency,quote_currency,side,qty,"
        "qty_remaining,seq,status) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [(row, row, 1, "USD/USD", "USD", "USD", "buy", 2, 1, row, "partial")
         for row in rows],
    )
    store.executemany(
        "INSERT INTO fx_trades (id,tick,order_id,actor_id,pair,side,base_qty,quote_qty,rate_ppm,"
        "base_account_id,quote_account_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [(row, row, row, 1, "USD/USD", "buy", 1, 1, 1_000_000, 900, 900)
         for row in rows],
    )
    statements = []
    store.conn.set_trace_callback(statements.append)
    try:
        payload = build_markets_workspace(store, as_of_tick=300)
    finally:
        store.conn.set_trace_callback(None)

    for key in ("orders", "trades", "fx_orders", "fx_trades"):
        assert len(payload[key]) == 100
        assert [row["id"] for row in payload[key]] == list(range(105, 205))
    assert all(row["qty_remaining"] == 1 for row in payload["orders"])
    assert all(row["qty_remaining"] == 1 for row in payload["fx_orders"])
    trade_reads = [
        sql for sql in statements
        if sql.lstrip().upper().startswith("SELECT") and "FROM trades" in sql
    ]
    fx_trade_reads = [
        sql for sql in statements
        if sql.lstrip().upper().startswith("SELECT") and "FROM fx_trades" in sql
    ]
    assert len(trade_reads) <= 2
    assert len(fx_trade_reads) <= 2


def test_world_workspace_resolves_agent_regions_with_bounded_queries(economy):
    _seed_workspace_history(economy)
    store = economy.store
    store.executemany(
        "INSERT INTO agents (id,name,kind,occupation,age,alive,arrived_tick,region_id,population_tier) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        [(agent_id, f"Agent {agent_id}", "citizen", "worker", 30, 1, 0, 1, "core")
         for agent_id in range(2, 22)],
    )
    store.executemany(
        "INSERT INTO migrations (id,agent_id,origin_region_id,destination_region_id,"
        "requested_tick,completed_tick,status) VALUES (?,?,?,?,?,?,?)",
        [(agent_id, agent_id, 1, 1, 2, 3, "completed") for agent_id in range(2, 22)],
    )
    statements = []
    store.conn.set_trace_callback(statements.append)
    try:
        payload = build_world_workspace(store, as_of_tick=4)
    finally:
        store.conn.set_trace_callback(None)

    assert len(payload["agents"]) == 21
    migration_queries = [sql for sql in statements if "FROM migrations" in sql]
    assert len(migration_queries) <= 3
    assert not any("WHERE agent_id=" in sql for sql in migration_queries)


def test_organization_balance_projection_scopes_ledger_aggregation(economy):
    _seed_workspace_history(economy)
    statements = []
    economy.store.conn.set_trace_callback(statements.append)
    try:
        payload = build_organizations_workspace(economy.store, as_of_tick=4)
    finally:
        economy.store.conn.set_trace_callback(None)

    firm = next(row for row in payload["firms"] if row["id"] == 1)
    assert firm["balance_cents"] == 125
    ledger_queries = [sql for sql in statements if "FROM ledger_entries" in sql]
    assert ledger_queries
    assert all("account_id IN" in sql for sql in ledger_queries)
