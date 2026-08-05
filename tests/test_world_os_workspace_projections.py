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
    store.execute(
        "INSERT INTO firms (id,name,sector,status,founded_tick,bankrupt_tick,region_id) "
        "VALUES (1,'Past Firm','food','bankrupt',2,9,1)")
    store.execute(
        "INSERT INTO firms (id,name,sector,status,founded_tick,region_id) "
        "VALUES (2,'future-order-canary','tech','private',9,1)")
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
        "VALUES (1,1,'past-rule','{}',4,4,'active'),(2,2,'future-rule-canary','{}',9,9,'active')")
    store.execute(
        "INSERT INTO legal_matters (id,matter_type,venue,status,claimant_type,claimant_id,respondent_type,respondent_id,claim_type,filed_tick,response_due_tick,requested_remedy_json,metadata_json) "
        "VALUES (1,'civil','court','filed','agent',1,'firm',1,'breach',4,8,'{}','{}'),"
        "(2,'civil','court','filed','agent',1,'firm',2,'future-case-canary',9,12,'{}','{}')")
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
        "world": build_world_workspace(world, economy.store, as_of_tick=4),
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
    assert [item["tick"] for item in payloads["politics"]["votes"]] == [4]
    assert [item["tick"] for item in payloads["experiments"]["checkpoints"]] == [4]

    at_ten = build_organizations_workspace(economy.store, as_of_tick=10)
    assert next(item for item in at_ten["organizations"] if item["id"] == 1)["status"] == "bankrupt"


def test_workspace_api_returns_canonical_envelopes_and_rejects_bad_lineage(economy, tmp_path):
    _seed_workspace_history(economy)
    world = SimpleNamespace(store=economy.store, config=economy.config, economy=economy)
    controller = SimpleNamespace(hosted_safe=False)
    app = FastAPI()
    install_v2_routes(app, world, controller)
    expected = {
        "world": build_world_workspace(world, economy.store, as_of_tick=4),
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
