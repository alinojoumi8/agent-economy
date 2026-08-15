"""Historical, privacy, and envelope contracts for Living Agents."""
from __future__ import annotations

import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.projections import (
    build_agent_journey,
    build_living_agents_workspace,
)
from server.v2_api import install_v2_routes
from tests.test_world_os_workspace_projections import _seed_workspace_history


def _seed_living_agents_history(economy) -> None:
    _seed_workspace_history(economy)
    store = economy.store
    store.execute(
        "INSERT INTO agents "
        "(id,name,kind,occupation,age,alive,arrived_tick,region_id,population_tier) "
        "VALUES (2,'Peripheral Agent','citizen','builder',31,1,0,1,'periphery')"
    )
    store.execute(
        "INSERT INTO accounts "
        "(id,owner_type,owner_id,kind,label,balance_cents,currency_code) VALUES "
        "(1001,'agent',1,'checking','agent one',100,'USD'),"
        "(1002,'agent',2,'checking','agent two',40,'USD')"
    )
    store.execute(
        "UPDATE agents SET checking_account_id=1001 WHERE id=1"
    )
    store.execute(
        "UPDATE agents SET checking_account_id=1002 WHERE id=2"
    )
    store.execute(
        "UPDATE firms SET founder_agent_id=1 WHERE id=1"
    )
    store.execute(
        "INSERT INTO transactions (id,tick,kind,memo,currency_code) VALUES "
        "(1001,3,'seed','living-agents','USD'),"
        "(1002,8,'seed','future-balance-canary','USD')"
    )
    store.execute(
        "INSERT INTO ledger_entries (id,tick,txn_id,account_id,delta_cents) VALUES "
        "(1001,3,1001,1001,100),(1002,8,1002,1001,700)"
    )
    store.execute(
        "INSERT INTO employments "
        "(id,firm_id,agent_id,title,wage_cents,start_tick,end_tick,status,"
        "pay_interval_ticks,next_pay_tick) VALUES "
        "(1,1,1,'Baker',25,2,8,'ended',30,32)"
    )
    store.execute(
        "INSERT INTO agent_skill_history "
        "(id,tick,agent_id,skill_key,old_level,new_level,xp_delta,new_xp,source) "
        "VALUES (1,3,1,'labor',0,1,10,10,'work'),"
        "(2,8,1,'labor',1,2,20,30,'future-skill-source-canary')"
    )
    store.execute(
        "INSERT INTO compute_subscriptions "
        "(id,agent_id,tier,payer_type,payer_id,payer_account_id,price_cents,"
        "created_tick,effective_tick,expiry_tick,status,reason) VALUES "
        "(1,1,'flash','agent',1,1001,20,3,3,7,'expired','historical'),"
        "(2,1,'premium','agent',1,1001,50,8,8,20,'active','future-plan-canary')"
    )
    store.execute(
        "INSERT INTO places "
        "(id,place_key,region_id,name,kind,owner_type,owner_id,x,y,capacity,"
        "created_tick,metadata_json) VALUES "
        "(2,'core-home',1,'Core Residential District','residential_district',"
        "'region',1,.25,.35,20,2,'{}'),"
        "(3,'peripheral-home',1,'Peripheral Secret District','residential_district',"
        "'region',1,.27,.37,20,2,'{}')"
    )
    store.execute(
        "INSERT INTO occupancy_leases "
        "(id,dedupe_key,agent_id,place_id,slot,start_tick,end_tick,priority,"
        "source_type,source_id,status,created_tick) VALUES "
        "(1,?,1,2,'evening',3,20,1,'routine_home',1,'active',3),"
        "(2,?,2,3,'evening',3,20,1,'routine_home',2,'active',3)",
        ("c" * 64, "d" * 64),
    )
    store.execute(
        "INSERT INTO claims "
        "(id,tick,claim_key,subject_type,subject_id,predicate,value_json,"
        "truth_status,source_event_ids_json,creator_agent_id) VALUES "
        "(1,3,'public-output','agent',1,'published','{}','true','[]',1),"
        "(2,8,'future-output','agent',1,'published','{}','true','[]',1)"
    )
    store.execute(
        "INSERT INTO information_items "
        "(id,tick,item_type,author_agent_id,claim_id,body,source_event_ids_json,status) "
        "VALUES (1,3,'report',1,1,'private-output-body-canary','[]','published'),"
        "(2,8,'report',1,2,'future-output-canary','[]','published')"
    )
    store.commit()


def test_living_agents_projection_is_historical_and_privacy_safe(economy):
    _seed_living_agents_history(economy)
    data = build_living_agents_workspace(
        economy.store,
        as_of_tick=4,
        runtime=None,
        limit=2,
    )

    assert data["summary"]["living_agents"] == 2
    assert data["summary"]["active_employments"] == 1
    assert data["summary"]["runtime_active"] == 0
    assert len(data["activity"]["items"]) == 2
    assert data["activity"]["next_cursor"] == 2
    assert data["privacy"]["private_bodies_omitted"] is True

    core = next(agent for agent in data["agents"] if agent["id"] == 1)
    peripheral = next(agent for agent in data["agents"] if agent["id"] == 2)
    assert core["balance_cents"] == 100
    assert core["compute"]["tier"] == "flash"
    assert core["skills"] == [{
        "skill_key": "labor",
        "level": 1,
        "xp": 10,
        "last_practiced_tick": 3,
        "milestone_count": 1,
        "source": "work",
        "evidence_ref": {
            "kind": "agent_skill_history", "id": 1, "tick": 3,
        },
    }]
    assert core["residence"]["name"] == "Core Residential District"
    assert peripheral["residence"] == {
        "visibility": "region_only",
        "region": {"id": 1, "name": "North"},
    }
    peripheral_projects = [
        project for project in data["projects"]
        if project["kind"] == "residence"
        and project["privacy"] == "aggregated"
    ]
    assert peripheral_projects
    assert all(project["owner_agent_id"] is None for project in peripheral_projects)
    assert peripheral_projects[0]["project_id"] == "residence:district:1"
    assert peripheral_projects[0]["evidence_refs"] == [{
        "kind": "occupancy_aggregate", "id": "1:residence", "tick": 3,
    }]

    serialized = json.dumps(data, sort_keys=True)
    for canary in (
        "private-output-body-canary",
        "future-output-canary",
        "future-skill-source-canary",
        "future-plan-canary",
        "future-balance-canary",
        "Peripheral Secret District",
        "peripheral-home",
    ):
        assert canary not in serialized
    assert "request_json" not in serialized
    assert "response_json" not in serialized


def test_living_agents_filters_pagination_and_agent_journey(economy):
    _seed_living_agents_history(economy)
    skills = build_living_agents_workspace(
        economy.store, as_of_tick=4, project_kind="skill", limit=100
    )
    assert skills["projects"]
    assert {project["kind"] for project in skills["projects"]} == {"skill"}
    assert {item["kind"] for item in skills["activity"]["items"]} == {"skill"}

    first = build_living_agents_workspace(
        economy.store, as_of_tick=4, after=0, limit=1
    )
    second = build_living_agents_workspace(
        economy.store, as_of_tick=4,
        after=first["activity"]["next_cursor"], limit=1,
    )
    assert first["activity"]["items"][0] != second["activity"]["items"][0]

    journey = build_agent_journey(
        economy.store, agent_id=1, as_of_tick=4
    )
    assert journey is not None
    assert journey["profile"]["name"] == "Public Agent"
    assert journey["current_state"]["employment"]["firm_name"] == "Past Firm"
    assert journey["public_outputs"][0]["stage"] == "published"
    assert journey["runtime"] is None
    assert build_agent_journey(
        economy.store, agent_id=999, as_of_tick=4
    ) is None


def test_living_agents_api_uses_canonical_envelopes_and_omits_historical_runtime(
    economy,
):
    _seed_living_agents_history(economy)

    class Gateway:
        def active_agent_status(self):
            return [{
                "agent_id": 2,
                "state": "working",
                "active_calls": 1,
                "tick": 10,
                "oldest_elapsed_ms": 42,
                "prompt": "runtime-private-canary",
            }]

    world = SimpleNamespace(
        store=economy.store,
        config=economy.config,
        economy=economy,
        gateway=Gateway(),
    )
    controller = SimpleNamespace(hosted_safe=False)
    app = FastAPI()
    install_v2_routes(app, world, controller)
    with TestClient(app) as client:
        historical = client.get(
            "/api/v2/workspaces/living-agents",
            params={"tick": 4, "project_kind": "skill", "limit": 1},
        )
        assert historical.status_code == 200
        body = historical.json()
        assert body["projection"] == "workspace.living_agents"
        assert body["tick"] == 4
        assert body["data"]["summary"]["runtime_active"] == 0
        assert "runtime-private-canary" not in json.dumps(body)

        journey = client.get(
            "/api/v2/agents/1/journey", params={"tick": 4}
        )
        assert journey.status_code == 200
        assert journey.json()["projection"] == "workspace.agent_journey"
        assert journey.json()["data"]["runtime"] is None

        live = client.get("/api/v2/workspaces/living-agents")
        assert live.status_code == 200
        assert live.json()["data"]["summary"]["runtime_active"] == 1
        assert "runtime-private-canary" not in json.dumps(live.json())

        assert client.get(
            "/api/v2/workspaces/living-agents",
            params={"project_kind": "unknown"},
        ).status_code == 422
        assert client.get(
            "/api/v2/agents/1/journey", params={"tick": 10}
        ).status_code == 404
    app.state.operator_workspace.close()
