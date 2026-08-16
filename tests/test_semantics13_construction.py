"""Semantics-13 construction economy, projection, and replay contracts."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from engine.actions import ActionExecutor
from engine.migrations import registry as migration_registry
from engine.store import Store
from run_config import load_config
from server.projections import (
    build_construction_project_detail,
    build_construction_projects,
    build_world_workspace,
)
from server.v2_api import install_v2_routes
from world.loop import World


def _config(*, semantics: int = 13, enabled: bool = True) -> dict:
    config = load_config("runs/civic-rehearsal.yaml")
    config["engine_semantics_version"] = semantics
    config["checkpoint_every"] = 0
    config["speed_delay_s"] = 0.0
    config["construction"] = {
        "enabled": enabled,
        "agent_initiation": True,
        "private_home_funding_cents": 1_200,
        "workplace_funding_cents": 2_400,
        "public_facility_funding_cents": 3_600,
        "private_home_work_units": 6,
        "workplace_work_units": 9,
        "public_facility_work_units": 12,
        "funding_contribution_cents": 1_200,
        "work_units_per_action": 2,
    }
    return config


def _open_world(path, *, semantics: int = 13, enabled: bool = True) -> World:
    config = _config(semantics=semantics, enabled=enabled)
    store = Store(str(path))
    store.init_run_meta(
        f"semantics-{semantics}-construction", int(config["seed"]), config)
    world = World(store, config)
    world.initialize()
    return world


@pytest.fixture
def construction_world(tmp_path):
    world = _open_world(tmp_path / "construction.db")
    try:
        yield world
    finally:
        world.close()


def _owner(world: World, *, tier: str = "core"):
    return world.store.query_one(
        "SELECT a.*,ac.balance_cents FROM agents a "
        "JOIN accounts ac ON ac.id=a.checking_account_id "
        "WHERE a.alive=1 AND a.region_id IS NOT NULL "
        "AND a.population_tier=? "
        "AND NOT EXISTS (SELECT 1 FROM agency_staff s "
        " WHERE s.agent_id=a.id AND s.active=1) "
        "ORDER BY ac.balance_cents DESC,a.id LIMIT 1",
        (tier,),
    )


def _permit_clerk(world: World, region_id: int) -> int:
    return int(world.store.scalar(
        "SELECT s.agent_id FROM agency_staff s "
        "WHERE s.region_id=? AND s.role_key='permit_clerk' AND s.active=1 "
        "ORDER BY s.agent_id LIMIT 1",
        (int(region_id),),
    ))


def _propose(
    world: World, owner, *, prefix: str = "home",
    target: str = "private_home", owner_type: str = "agent",
    owner_id: int | None = None, funding: int = 1_200, work: int = 6,
) -> dict:
    actor_id = int(owner["id"])
    return world.runtime.executor.execute_action(1, actor_id, {
        "type": "propose_construction",
        "owner_type": owner_type,
        "owner_id": actor_id if owner_id is None else int(owner_id),
        "region_id": int(owner["region_id"]),
        "site_key": f"{prefix}-site",
        "target_place_type": target,
        "name": f"{prefix.title()} Project",
        "required_funding_cents": funding,
        "required_work_units": work,
        "dedupe_key": f"{prefix}-proposal-0001",
    })


def _advance_to_building(
    world: World, owner, *, prefix: str = "home",
    funding: int = 1_200, work: int = 6,
) -> tuple[int, int]:
    executor = world.runtime.executor
    actor_id = int(owner["id"])
    proposed = _propose(
        world, owner, prefix=prefix, funding=funding, work=work)
    assert proposed["ok"], proposed
    project_id = int(proposed["project_id"])
    applied = executor.execute_action(2, actor_id, {
        "type": "apply_construction_permit",
        "project_id": project_id,
        "dedupe_key": f"{prefix}-permit-0001",
    })
    assert applied["ok"], applied
    case_id = int(applied["permit_case_id"])
    clerk_id = _permit_clerk(world, int(owner["region_id"]))
    approved = executor.execute_action(3, clerk_id, {
        "type": "decide_construction_permit",
        "case_id": case_id,
        "decision": "approve",
        "reason_code": "requirements_verified",
        "dedupe_key": f"{prefix}-approval-0001",
    })
    assert approved["ok"], approved
    funded = executor.execute_action(4, actor_id, {
        "type": "contribute_construction_funding",
        "project_id": project_id,
        "amount_cents": funding,
        "dedupe_key": f"{prefix}-funding-0001",
    })
    assert funded["ok"], funded
    assert funded["status"] == "building"
    assert funded["stage"] == "foundation"
    return project_id, clerk_id


def _complete_home(world: World, owner, *, prefix: str = "home") -> int:
    project_id, _clerk_id = _advance_to_building(
        world, owner, prefix=prefix)
    executor = world.runtime.executor
    actor_id = int(owner["id"])
    expected = [(5, "frame"), (6, "shell"), (7, "completed")]
    for tick, stage in expected:
        result = executor.execute_action(tick, actor_id, {
            "type": "perform_construction_work",
            "project_id": project_id,
            "work_units": 2,
            "wage_cents": 100,
            "procurement_cents": 100,
            "dedupe_key": f"{prefix}-work-{tick:04d}",
        })
        assert result["ok"], result
        assert result["stage"] == stage
    return project_id


def test_full_lifecycle_requires_permit_and_funding_and_creates_one_place(
    construction_world,
):
    world = construction_world
    store = world.store
    owner = _owner(world)
    assert owner is not None
    executor = world.runtime.executor
    actor_id = int(owner["id"])

    proposed = _propose(world, owner, prefix="lifecycle")
    assert proposed["ok"], proposed
    project_id = int(proposed["project_id"])
    assert store.scalar(
        "SELECT COUNT(*) FROM places WHERE metadata_json LIKE ?",
        (f'%"construction_project_id":{project_id}%',),
    ) == 0

    premature = executor.execute_action(2, actor_id, {
        "type": "perform_construction_work",
        "project_id": project_id,
        "work_units": 1,
        "wage_cents": 0,
        "procurement_cents": 0,
        "dedupe_key": "lifecycle-work-too-soon",
    })
    assert premature == {
        "ok": False,
        "reason": "construction work requires a fully funded project",
    }

    applied = executor.execute_action(2, actor_id, {
        "type": "apply_construction_permit",
        "project_id": project_id,
        "dedupe_key": "lifecycle-permit-0001",
    })
    assert applied["ok"], applied
    case_id = int(applied["permit_case_id"])
    unauthorized = executor.execute_action(3, actor_id, {
        "type": "decide_construction_permit",
        "case_id": case_id,
        "decision": "approve",
        "reason_code": "requirements_verified",
        "dedupe_key": "lifecycle-owner-review",
    })
    assert not unauthorized["ok"]
    assert "agency staff" in unauthorized["reason"]

    clerk_id = _permit_clerk(world, int(owner["region_id"]))
    approved = executor.execute_action(3, clerk_id, {
        "type": "decide_construction_permit",
        "case_id": case_id,
        "decision": "approve",
        "reason_code": "requirements_verified",
        "dedupe_key": "lifecycle-clerk-review",
    })
    assert approved["ok"], approved

    overfunded = executor.execute_action(4, actor_id, {
        "type": "contribute_construction_funding",
        "project_id": project_id,
        "amount_cents": 1_201,
        "dedupe_key": "lifecycle-overfund",
    })
    assert not overfunded["ok"]
    assert "remaining requirement" in overfunded["reason"]

    poor_id = store.insert(
        "agents", name="Unfunded Builder", kind="citizen",
        occupation="builder", age=30, alive=1, arrived_tick=0,
        region_id=int(owner["region_id"]), population_tier="core")
    poor_account = world.economy.ledger.create_account(
        "agent", poor_id, "checking", label="unfunded-builder")
    store.update("agents", poor_id, checking_account_id=poor_account)
    insufficient = executor.execute_action(4, poor_id, {
        "type": "contribute_construction_funding",
        "project_id": project_id,
        "amount_cents": 1_200,
        "dedupe_key": "lifecycle-no-cash",
    })
    assert insufficient == {
        "ok": False,
        "reason": "insufficient funds for construction contribution",
    }

    funded_action = {
        "type": "contribute_construction_funding",
        "project_id": project_id,
        "amount_cents": 1_200,
        "dedupe_key": "lifecycle-funded-0001",
    }
    funded = executor.execute_action(4, actor_id, funded_action)
    assert funded["ok"] and funded["stage"] == "foundation"
    duplicate_funding = executor.execute_action(4, actor_id, funded_action)
    assert duplicate_funding["ok"]
    assert duplicate_funding["idempotent"] is True
    assert store.scalar(
        "SELECT COUNT(*) FROM construction_contributions "
        "WHERE project_id=? AND contribution_type='funding'",
        (project_id,),
    ) == 1
    conflict = executor.execute_action(4, actor_id, {
        **funded_action,
        "amount_cents": 1_199,
    })
    assert not conflict["ok"]
    assert conflict["idempotency_conflict"] is True

    assert store.scalar(
        "SELECT COUNT(*) FROM places WHERE metadata_json LIKE ?",
        (f'%"construction_project_id":{project_id}%',),
    ) == 0
    work_actions = []
    for tick, expected_stage in ((5, "frame"), (6, "shell"), (7, "completed")):
        action = {
            "type": "perform_construction_work",
            "project_id": project_id,
            "work_units": 2,
            "wage_cents": 100,
            "procurement_cents": 100,
            "dedupe_key": f"lifecycle-work-{tick:04d}",
        }
        result = executor.execute_action(tick, actor_id, action)
        assert result["ok"], result
        assert result["stage"] == expected_stage
        work_actions.append((action, result))
        expected_places = 1 if expected_stage == "completed" else 0
        assert store.scalar(
            "SELECT COUNT(*) FROM places WHERE metadata_json LIKE ?",
            (f'%"construction_project_id":{project_id}%',),
        ) == expected_places

    final_action, final_result = work_actions[-1]
    duplicate_completion = executor.execute_action(7, actor_id, final_action)
    assert duplicate_completion["idempotent"] is True
    assert duplicate_completion["place_id"] == final_result["place_id"]
    assert store.scalar(
        "SELECT COUNT(*) FROM places WHERE metadata_json LIKE ?",
        (f'%"construction_project_id":{project_id}%',),
    ) == 1
    project = store.query_one(
        "SELECT * FROM construction_projects WHERE id=?", (project_id,))
    assert tuple(project[key] for key in (
        "status", "contributed_funding_cents", "contributed_work_units",
        "spent_funding_cents", "refunded_funding_cents",
    )) == ("completed", 1_200, 6, 600, 600)
    kinds = {
        row["kind"] for row in store.query(
            "SELECT kind FROM transactions WHERE kind LIKE 'construction_%'")
    }
    assert kinds == {
        "construction_funding",
        "construction_wage",
        "construction_procurement",
        "construction_refund",
    }
    reconciled, diagnostics = world.economy.ledger.reconcile()
    assert reconciled, diagnostics


def test_cancellation_refunds_only_unspent_escrow_and_is_idempotent(
    construction_world,
):
    world = construction_world
    owner = _owner(world)
    actor_id = int(owner["id"])
    account_id = int(owner["checking_account_id"])
    opening = world.economy.ledger.balance(account_id)
    project_id, _clerk_id = _advance_to_building(
        world, owner, prefix="cancel")
    worked = world.runtime.executor.execute_action(5, actor_id, {
        "type": "perform_construction_work",
        "project_id": project_id,
        "work_units": 2,
        "wage_cents": 100,
        "procurement_cents": 100,
        "dedupe_key": "cancel-work-0001",
    })
    assert worked["ok"], worked
    excessive_cost = world.runtime.executor.execute_action(5, actor_id, {
        "type": "perform_construction_work",
        "project_id": project_id,
        "work_units": 1,
        "wage_cents": 201,
        "procurement_cents": 0,
        "dedupe_key": "cancel-cost-cap-0001",
    })
    assert excessive_cost == {
        "ok": False,
        "reason": (
            "construction work costs exceed the deterministic "
            "200-cent budget for 1 work units"),
    }
    cancel_action = {
        "type": "cancel_construction",
        "project_id": project_id,
        "reason_code": "owner_cancelled",
        "dedupe_key": "cancel-project-0001",
    }
    cancelled = world.runtime.executor.execute_action(6, actor_id, cancel_action)
    assert cancelled == {
        "ok": True,
        "project_id": project_id,
        "status": "cancelled",
        "refund_cents": 1_000,
        "refund_transaction_ids": cancelled["refund_transaction_ids"],
    }
    assert len(cancelled["refund_transaction_ids"]) == 1
    duplicate = world.runtime.executor.execute_action(6, actor_id, cancel_action)
    assert duplicate["idempotent"] is True
    assert world.store.scalar(
        "SELECT COUNT(*) FROM construction_contributions "
        "WHERE project_id=? AND contribution_type='refund'",
        (project_id,),
    ) == 1
    assert world.economy.ledger.balance(account_id) == opening - 100
    project = world.store.query_one(
        "SELECT status,spent_funding_cents,refunded_funding_cents,place_id "
        "FROM construction_projects WHERE id=?",
        (project_id,),
    )
    assert tuple(project) == ("cancelled", 200, 1_000, None)
    projected = build_construction_project_detail(
        world.store, project_id=str(project_id), as_of_tick=6)
    assert projected is not None
    assert projected["project"]["stage"] == "frame"
    reconciled, diagnostics = world.economy.ledger.reconcile()
    assert reconciled, diagnostics


def test_historical_projection_reconstructs_exact_stages_and_places(
    construction_world,
):
    world = construction_world
    owner = _owner(world)
    project_id = _complete_home(world, owner, prefix="history")

    expectations = {
        1: ("proposed", None, 0, None),
        2: ("permitting", None, 0, None),
        3: ("funding", None, 0, None),
        4: ("building", "foundation", 0, None),
        5: ("building", "frame", 2, None),
        6: ("building", "shell", 4, None),
        7: ("completed", "completed", 6, "present"),
    }
    for tick, (status, stage, work, place) in expectations.items():
        data = build_construction_projects(
            world.store, as_of_tick=tick, limit=100)
        item = next(
            project for project in data["projects"]["items"]
            if project["project_id"] == project_id)
        assert (item["status"], item["stage"]) == (status, stage)
        assert item["contributed"]["work_units"] == work
        assert (item["place_id"] is not None) == (place == "present")
        workspace = build_world_workspace(world.store, as_of_tick=tick)
        construction = next(
            project for project in workspace["construction_projects"]
            if project["project_id"] == project_id)
        assert construction["status"] == status
        place_ids = {entry["id"] for entry in workspace["places"]}
        assert (item["place_id"] in place_ids) == (place == "present")

    detail = build_construction_project_detail(
        world.store, project_id=str(project_id), as_of_tick=5)
    assert detail is not None
    assert detail["project"]["stage"] == "frame"
    assert detail["project"]["milestone_count"] == 5
    assert detail["contribution_summary"] == [
        {
            "type": "funding",
            "count": 1,
            "amount_cents": 1_200,
            "work_units": 0,
            "latest_tick": 4,
        },
        {
            "type": "work",
            "count": 1,
            "amount_cents": 0,
            "work_units": 2,
            "latest_tick": 5,
        },
    ]


def test_peripheral_private_homes_are_aggregated_without_reversible_links(
    construction_world,
):
    world = construction_world
    owner = _owner(world, tier="periphery")
    assert owner is not None
    proposal = _propose(world, owner, prefix="private-canary")
    assert proposal["ok"], proposal
    project_id = int(proposal["project_id"])
    data = build_construction_projects(
        world.store, as_of_tick=1, project_kind="private_home")
    aggregate = next(
        item for item in data["projects"]["items"]
        if item["privacy"] == "aggregated_private")
    assert aggregate["aggregate_count"] >= 1
    assert aggregate["owner"] is None
    assert aggregate["initiator_agent_id"] is None
    assert aggregate["place_id"] is None
    assert aggregate["permit"] is None
    assert aggregate["evidence_refs"] == []
    serialized = json.dumps(aggregate, sort_keys=True)
    for canary in (
        "private-canary-site",
        str(owner["name"]),
    ):
        assert canary not in serialized
    assert aggregate["project_id"] != project_id
    assert aggregate["project_id"].startswith("private-homes:region:")
    assert build_construction_project_detail(
        world.store, project_id=str(project_id), as_of_tick=1
    ) is None
    world.store.insert(
        "agent_tier_history", tick=2, agent_id=int(owner["id"]),
        old_tier="periphery", new_tier="core", score=1.0, reason_json="{}")
    world.store.update("agents", int(owner["id"]), population_tier="core")
    still_historical = build_construction_projects(
        world.store, as_of_tick=1, project_kind="private_home")
    assert all(
        item["project_id"] != project_id
        for item in still_historical["projects"]["items"])
    current = build_construction_projects(
        world.store, as_of_tick=2, project_kind="private_home")
    exact = next(
        item for item in current["projects"]["items"]
        if item["project_id"] == project_id)
    assert exact["privacy"] == "public"


def test_construction_api_envelopes_filters_pagination_and_lineage(
    construction_world,
):
    world = construction_world
    owner = _owner(world)
    project_id = _complete_home(world, owner, prefix="api")
    world.store.set_meta(tick=7)
    controller = SimpleNamespace(hosted_safe=False)
    app = FastAPI()
    install_v2_routes(app, world, controller)
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/v2/construction-projects",
                params={
                    "tick": 5,
                    "project_kind": "private_home",
                    "status": "building",
                    "limit": 1,
                },
            )
            assert response.status_code == 200
            body = response.json()
            assert body["projection"] == "workspace.construction_projects"
            assert body["tick"] == 5
            assert body["data"]["projects"]["total"] == 1
            assert body["data"]["projects"]["items"][0]["stage"] == "frame"

            detail = client.get(
                f"/api/v2/construction-projects/{project_id}",
                params={"tick": 6},
            )
            assert detail.status_code == 200
            assert detail.json()["projection"] == (
                "workspace.construction_project_detail")
            assert detail.json()["data"]["project"]["stage"] == "shell"

            map_response = client.get(
                "/api/v2/world-map",
                params={"tick": 5, "layers": "construction_projects"},
            )
            assert map_response.status_code == 200
            map_body = map_response.json()
            assert map_body["projection"] == "world.map"
            assert map_body["data"]["construction_projects"][0]["stage"] == "frame"
            assert "places" not in map_body["data"]

            assert client.get(
                "/api/v2/construction-projects",
                params={"project_kind": "invented"},
            ).status_code == 422
            assert client.get(
                "/api/v2/construction-projects",
                params={"status": "invented"},
            ).status_code == 422
            assert client.get(
                "/api/v2/construction-projects/999999",
                params={"tick": 7},
            ).status_code == 404
            assert client.get(
                "/api/v2/construction-projects",
                params={"fork_id": "missing"},
            ).status_code == 409
    finally:
        app.state.operator_workspace.close()


def test_semantics_12_rejects_construction_without_mutating_historical_runs(
    tmp_path,
):
    world = _open_world(
        tmp_path / "semantics12.db", semantics=12, enabled=False)
    try:
        owner = _owner(world)
        result = ActionExecutor(world.economy).execute_action(
            1, int(owner["id"]), {
                "type": "propose_construction",
                "owner_type": "agent",
                "owner_id": int(owner["id"]),
                "region_id": int(owner["region_id"]),
                "site_key": "legacy-site",
                "target_place_type": "private_home",
                "name": "Legacy Home",
                "required_funding_cents": 1_200,
                "required_work_units": 6,
                "dedupe_key": "legacy-proposal-0001",
            })
        assert result == {
            "ok": False,
            "reason": (
                "invalid propose_construction command: "
                "unknown action type: propose_construction"
            ),
        }
        assert world.store.scalar(
            "SELECT COUNT(*) FROM construction_projects") == 0
        assert world.store.scalar(
            "SELECT COUNT(*) FROM construction_action_receipts") == 0
    finally:
        world.close()


def test_agent_decision_context_supplies_one_exact_construction_action(
    construction_world,
):
    world = construction_world
    owner = _owner(world)
    context = world.economy.construction.decision_context(
        int(owner["id"]), 1)
    assert context["rule"] == (
        "copy one eligible action exactly or deliberately do nothing")
    assert len(context["eligible_actions"]) == 1
    action = context["eligible_actions"][0]
    assert action["type"] == "propose_construction"
    assert action["owner_id"] == int(owner["id"])
    assert action["target_place_type"] == "private_home"
    result = world.runtime.executor.execute_action(
        1, int(owner["id"]), action)
    assert result["ok"], result
    next_context = world.economy.construction.decision_context(
        int(owner["id"]), 2)
    assert next_context["eligible_actions"] == [{
        "type": "apply_construction_permit",
        "project_id": int(result["project_id"]),
        "dedupe_key": f"construction-project-{int(result['project_id'])}-permit",
    }]


def test_same_seed_and_actions_produce_identical_authoritative_construction(
    tmp_path,
):
    worlds = [
        _open_world(tmp_path / "first.db"),
        _open_world(tmp_path / "second.db"),
    ]
    try:
        project_ids = []
        for index, world in enumerate(worlds):
            owner = _owner(world)
            project_ids.append(_complete_home(
                world, owner, prefix="deterministic"))
            assert project_ids[index] == project_ids[0]

        queries = (
            "SELECT project_key,name,owner_type,owner_id,region_id,site_key,"
            "site_x,site_y,target_place_type,status,required_funding_cents,"
            "required_work_units,contributed_funding_cents,"
            "contributed_work_units,spent_funding_cents,"
            "refunded_funding_cents,proposed_tick,permitting_tick,funding_tick,"
            "building_tick,foundation_tick,frame_tick,shell_tick,completed_tick "
            "FROM construction_projects ORDER BY id",
            "SELECT project_id,actor_agent_id,contribution_type,amount_cents,"
            "work_units,tick,metadata_json FROM construction_contributions "
            "ORDER BY id",
            "SELECT tick,kind,memo,currency_code FROM transactions "
            "WHERE kind LIKE 'construction_%' ORDER BY id",
        )
        for query in queries:
            first = [tuple(row) for row in worlds[0].store.query(query)]
            second = [tuple(row) for row in worlds[1].store.query(query)]
            assert first == second
    finally:
        for world in worlds:
            world.close()


def test_schema_19_migrates_v18_additively_and_reopens_idempotently(
    tmp_path, monkeypatch,
):
    path = tmp_path / "v18-construction.db"
    original = migration_registry._MIGRATIONS
    before_v19 = tuple(
        migration for migration in original if migration.version < 19)
    monkeypatch.setattr(migration_registry, "_MIGRATIONS", before_v19)
    legacy = Store(str(path))
    try:
        assert legacy.scalar(
            "SELECT MAX(version) FROM schema_migrations") == 18
        assert legacy.scalar(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type='table' AND name='construction_projects'") == 0
    finally:
        legacy.close()

    monkeypatch.setattr(migration_registry, "_MIGRATIONS", original)
    upgraded = Store(str(path))
    try:
        assert upgraded.scalar(
            "SELECT MAX(version) FROM schema_migrations") == 19
        migration = upgraded.query_one(
            "SELECT name,source_schema,status FROM schema_migrations "
            "WHERE version=19")
        assert tuple(migration) == ("construction_economy", 18, "applied")
        tables = {
            row["name"] for row in upgraded.query(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name LIKE 'construction_%'")
        }
        assert tables == {
            "construction_projects",
            "construction_permit_cases",
            "construction_contributions",
            "construction_action_receipts",
        }
    finally:
        upgraded.close()

    reopened = Store(str(path))
    try:
        assert reopened.scalar(
            "SELECT COUNT(*) FROM schema_migrations WHERE version=19") == 1
    finally:
        reopened.close()
