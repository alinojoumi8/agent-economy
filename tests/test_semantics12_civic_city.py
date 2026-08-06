"""Semantics 12 permit-office, place, attention, and replay contracts."""
from __future__ import annotations

import asyncio
from dataclasses import replace
import json
import sqlite3
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from engine.actions import ActionExecutor
from engine.migrations import registry as migration_registry
from engine.migrations.registry import MigrationError
from engine.store import Store
from run import open_run
from run_config import load_config
from server.app import create_app
from server.v2_api import install_v2_routes
from world.loop import World
from world.replay_verify import verify_replay


def _config() -> dict:
    config = load_config("runs/civic-rehearsal.yaml")
    config["checkpoint_every"] = 0
    config["speed_delay_s"] = 0.0
    return config


@pytest.fixture()
def civic_world(tmp_path):
    config = _config()
    store = Store(str(tmp_path / "civic.db"))
    store.init_run_meta("semantics12-civic", int(config["seed"]), config)
    world = World(store, config)
    world.initialize()
    try:
        yield world
    finally:
        store.close()


def _lawyer_id(store: Store) -> int:
    return int(store.scalar(
        "SELECT id FROM agents WHERE alive=1 "
        "AND lower(COALESCE(occupation,''))='lawyer' ORDER BY id LIMIT 1"))


def _same_region_applicants(store: Store, count: int = 3, *, employed=False):
    rows = store.query(
        "SELECT a.*,ac.balance_cents,"
        "EXISTS(SELECT 1 FROM employments e "
        "WHERE e.agent_id=a.id AND e.status='active') AS employed "
        "FROM agents a JOIN accounts ac ON ac.id=a.checking_account_id "
        "WHERE a.alive=1 AND a.role IS NULL AND a.region_id IS NOT NULL "
        "AND ac.balance_cents>=200000 "
        "AND NOT EXISTS(SELECT 1 FROM firms f WHERE f.founder_agent_id=a.id "
        "AND f.status<>'bankrupt') ORDER BY a.region_id,a.id")
    by_region: dict[int, list] = {}
    for row in rows:
        if employed and not bool(row["employed"]):
            continue
        by_region.setdefault(int(row["region_id"]), []).append(row)
    candidates = max(by_region.values(), key=len)
    assert len(candidates) >= count
    return candidates[:count]


def _application(lawyer_id: int, name: str, *, sector="technology") -> dict:
    return {
        "name": name,
        "sector": sector,
        "lawyer_agent_id": lawyer_id,
        "opening_capital": 100000,
        "business_idea": {
            "mission": "Build dependable local business capacity.",
            "customer_problem": "Customers need reliable supply in this market.",
            "offering": "A reliable locally delivered service",
        },
    }


def _allow_direct_applications(world: World) -> None:
    world.economy.config["entrepreneurship"]["enabled"] = False


def test_schema_17_migrates_v16_atomically(monkeypatch, tmp_path) -> None:
    path = tmp_path / "v16-to-v17.db"
    original = migration_registry._MIGRATIONS
    before_v17 = tuple(migration for migration in original if migration.version < 17)
    v17 = next(migration for migration in original if migration.version == 17)
    after_v17 = tuple(migration for migration in original if migration.version > 17)
    monkeypatch.setattr(migration_registry, "_MIGRATIONS", before_v17)
    Store(str(path)).close()

    raw = sqlite3.connect(path)
    try:
        assert raw.execute(
            "SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 16
        assert raw.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='places'"
        ).fetchone() is None
    finally:
        raw.close()

    def fail_verify(_conn) -> None:
        raise RuntimeError("forced v17 verification failure")

    failing = replace(v17, verify=fail_verify)
    monkeypatch.setattr(
        migration_registry, "_MIGRATIONS", (*before_v17, failing, *after_v17))
    with pytest.raises(MigrationError, match="failed applying migration v17"):
        Store(str(path))

    raw = sqlite3.connect(path)
    try:
        assert raw.execute(
            "SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 16
        assert raw.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='places'"
        ).fetchone() is None
        assert "attention_context_key" not in {
            row[1] for row in raw.execute("PRAGMA table_info(agent_decisions)")
        }
    finally:
        raw.close()

    monkeypatch.setattr(migration_registry, "_MIGRATIONS", original)
    upgraded = Store(str(path))
    try:
        migration = upgraded.query_one(
            "SELECT name,source_schema,status FROM schema_migrations "
            "WHERE version=17")
        assert tuple(migration) == ("civic_city", 16, "applied")
        assert upgraded.scalar(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
            "AND name IN ('places','service_cases','attention_contexts')") == 3
    finally:
        upgraded.close()


def test_capacity_fifo_priority_and_business_presence_override(civic_world) -> None:
    world = civic_world
    store = world.store
    city = world.economy.city
    _allow_direct_applications(world)
    lawyer_id = _lawyer_id(store)
    applicants = _same_region_applicants(store, employed=True)

    cases = []
    for index, applicant in enumerate(applicants):
        result = city.apply_business_permit(
            1, int(applicant["id"]),
            _application(lawyer_id, f"Queue Order {index}"))
        assert result["ok"], result
        cases.append(int(result["case_id"]))
    store.execute(
        "UPDATE service_cases SET priority=5 WHERE id=?", (cases[2],))
    city.finalize(1)

    scheduled = store.query(
        "SELECT case_id,scheduled_tick,capacity_rank "
        "FROM service_appointments ORDER BY scheduled_tick,capacity_rank,id")
    assert [int(row["case_id"]) for row in scheduled] == [
        cases[2], cases[0], cases[1]]
    assert [int(row["scheduled_tick"]) for row in scheduled] == [2, 3, 4]

    priority_applicant = int(applicants[2]["id"])
    firm_id = int(store.scalar(
        "SELECT firm_id FROM employments WHERE agent_id=? AND status='active'",
        (priority_applicant,)))
    city.run_nightly(2)
    presence = store.query_one(
        "SELECT p.kind,p.owner_id FROM effective_presence ep "
        "JOIN places p ON p.id=ep.place_id "
        "WHERE ep.tick=2 AND ep.slot='business' AND ep.agent_id=?",
        (priority_applicant,))
    assert tuple(presence) == ("licensing_office", int(
        store.scalar(
            "SELECT owner_id FROM places WHERE kind='licensing_office' "
            "AND region_id=?", (int(applicants[2]["region_id"]),))))
    assert priority_applicant not in {
        int(row["agent_id"])
        for row in world.economy.firms.productive_employees(firm_id, 2)
    }
    assert store.query_one(
        "SELECT 1 FROM employments WHERE agent_id=? AND status='active'",
        (priority_applicant,)) is not None


def test_three_no_shows_abandon_case_and_preserve_fee(civic_world) -> None:
    world = civic_world
    store = world.store
    city = world.economy.city
    _allow_direct_applications(world)
    applicant = _same_region_applicants(store, 1)[0]
    actor_id = int(applicant["id"])
    before = world.economy.ledger.balance(
        world.economy.ledger.agent_checking_id(actor_id))
    result = city.apply_business_permit(
        1, actor_id, _application(_lawyer_id(store), "No Show Works"))
    assert result["ok"], result
    city.finalize(1)
    for tick in (2, 3, 4):
        city.finalize(tick)

    case = store.query_one(
        "SELECT status,no_show_count,reason_code FROM service_cases WHERE id=?",
        (int(result["case_id"]),))
    assert tuple(case) == ("abandoned", 3, "three_no_shows")
    assert [
        tuple(row) for row in store.query(
            "SELECT attempt_number,status FROM service_appointments "
            "WHERE case_id=? ORDER BY attempt_number", (int(result["case_id"]),))
    ] == [(1, "no_show"), (2, "no_show"), (3, "no_show")]
    after = world.economy.ledger.balance(
        world.economy.ledger.agent_checking_id(actor_id))
    assert before - after == 2500


def test_migration_death_and_staff_succession_keep_agency_work(civic_world) -> None:
    world = civic_world
    store = world.store
    city = world.economy.city
    _allow_direct_applications(world)
    lawyer_id = _lawyer_id(store)
    first, second, third = _same_region_applicants(store)

    moved = city.apply_business_permit(
        1, int(first["id"]), _application(lawyer_id, "Moving Permit"))
    deceased = city.apply_business_permit(
        1, int(second["id"]), _application(lawyer_id, "Estate Permit"))
    durable = city.apply_business_permit(
        1, int(third["id"]), _application(lawyer_id, "Durable Agency Work"))
    city.finalize(1)

    destination = int(store.scalar(
        "SELECT id FROM regions WHERE id<>? ORDER BY id LIMIT 1",
        (int(first["region_id"]),)))
    store.execute(
        "UPDATE agents SET region_id=? WHERE id=?",
        (destination, int(first["id"])))
    store.execute(
        "UPDATE agents SET alive=0 WHERE id=?", (int(second["id"]),))

    durable_case = int(durable["case_id"])
    agency_id = int(store.scalar(
        "SELECT agency_id FROM service_cases WHERE id=?", (durable_case,)))
    old_clerk = int(store.scalar(
        "SELECT agent_id FROM agency_staff WHERE agency_id=? "
        "AND role_key='permit_clerk' AND active=1", (agency_id,)))
    store.execute(
        "UPDATE service_appointments SET status='cancelled' WHERE case_id=?",
        (durable_case,))
    store.execute(
        "UPDATE service_cases SET status='under_review' WHERE id=?",
        (durable_case,))
    task_id = store.insert(
        "institution_tasks",
        agency_id=agency_id,
        task_type="decide_business_permit",
        source_case_id=durable_case,
        assigned_agent_id=old_clerk,
        priority=0,
        created_tick=1,
        due_tick=4,
        assigned_tick=1,
        status="assigned",
        payload_json="{}",
    )
    store.execute("UPDATE agents SET alive=0 WHERE id=?", (old_clerk,))

    city.run_nightly(2)
    city.finalize(2)

    moved_case = store.query_one(
        "SELECT region_id,agency_id,status FROM service_cases WHERE id=?",
        (int(moved["case_id"]),))
    assert int(moved_case["region_id"]) == destination
    assert int(moved_case["agency_id"]) != agency_id
    assert moved_case["status"] == "appointment_scheduled"
    dead_case = store.query_one(
        "SELECT status,reason_code FROM service_cases WHERE id=?",
        (int(deceased["case_id"]),))
    assert tuple(dead_case) == ("abandoned", "applicant_deceased")

    successor = int(store.scalar(
        "SELECT agent_id FROM agency_staff WHERE agency_id=? "
        "AND role_key='permit_clerk' AND active=1", (agency_id,)))
    assert successor != old_clerk
    task = store.query_one(
        "SELECT status,assigned_agent_id,source_case_id "
        "FROM institution_tasks WHERE id=?", (task_id,))
    assert tuple(task) == ("assigned", successor, durable_case)


def _permit_authorization(world: World):
    store = world.store
    executor = ActionExecutor(world.economy)
    opportunity = None
    founder = None
    application_tick = None
    for tick in range(1, 5):
        for agent in store.query(
                "SELECT * FROM agents WHERE alive=1 AND role IS NULL ORDER BY id"):
            context = world.runtime.ctx.build(agent, tick)
            candidate = context.get("entrepreneurship_opportunity")
            if (
                isinstance(candidate, dict)
                and candidate.get("action", {}).get("type")
                == "apply_business_permit"
            ):
                founder = agent
                opportunity = candidate
                application_tick = tick
                break
        if opportunity is not None:
            break
    assert opportunity is not None
    founder_id = int(founder["id"])
    applied = executor.execute_action(
        application_tick, founder_id, opportunity["action"])
    assert applied["ok"], applied
    world.economy.city.finalize(application_tick)
    appointment = store.query_one(
        "SELECT id,scheduled_tick FROM service_appointments WHERE case_id=?",
        (int(applied["case_id"]),))
    appointment_tick = int(appointment["scheduled_tick"])
    world.economy.city.run_nightly(appointment_tick)
    attended = executor.execute_action(appointment_tick, founder_id, {
        "type": "attend_civic_appointment",
        "appointment_id": int(appointment["id"]),
    })
    assert attended["ok"], attended
    world.economy.city.finalize(appointment_tick)
    case = store.query_one(
        "SELECT status FROM service_cases WHERE id=?", (int(applied["case_id"]),))
    if case["status"] == "under_review":
        task = store.query_one(
            "SELECT assigned_agent_id FROM institution_tasks "
            "WHERE source_case_id=?", (int(applied["case_id"]),))
        decided = executor.execute_action(appointment_tick + 1, int(
            task["assigned_agent_id"]), {
                "type": "decide_business_permit",
                "case_id": int(applied["case_id"]),
                "decision": "approve",
                "reason_code": "market_capacity_supported",
            })
        assert decided["ok"], decided
    authorization = store.query_one(
        "SELECT * FROM civic_authorizations WHERE case_id=?",
        (int(applied["case_id"]),))
    assert authorization is not None
    return founder_id, authorization, executor


def test_authorization_payload_expiry_and_exactly_once_consumption(
        civic_world) -> None:
    world = civic_world
    store = world.store
    founder_id, authorization, executor = _permit_authorization(world)
    action = world.economy.city.founding_opportunity(
        founder_id, int(authorization["issued_tick"]) + 1)["action"]

    mismatch = executor.execute_action(
        int(authorization["issued_tick"]) + 1,
        founder_id,
        {**action, "name": f"{action['name']} Mutated"},
    )
    assert not mismatch["ok"]
    assert "permit authorization payload" in mismatch["reason"]
    assert store.scalar(
        "SELECT status FROM civic_authorizations WHERE id=?",
        (int(authorization["id"]),)) == "active"

    founded = executor.execute_action(
        int(authorization["issued_tick"]) + 1, founder_id, action)
    assert founded["ok"], founded
    repeated = executor.execute_action(
        int(authorization["issued_tick"]) + 2, founder_id, action)
    assert not repeated["ok"]
    assert store.scalar(
        "SELECT COUNT(*) FROM firms WHERE founder_agent_id=?",
        (founder_id,)) == 1
    consumed = store.query_one(
        "SELECT status,consumed_by_firm_id FROM civic_authorizations WHERE id=?",
        (int(authorization["id"]),))
    assert tuple(consumed) == ("consumed", int(founded["firm_id"]))


def test_authorization_expires_and_cannot_found(civic_world) -> None:
    world = civic_world
    store = world.store
    founder_id, authorization, executor = _permit_authorization(world)
    action = world.economy.city.founding_opportunity(
        founder_id, int(authorization["issued_tick"]) + 1)["action"]
    expiry = int(authorization["expiry_tick"])
    world.economy.city.run_nightly(expiry + 1)
    assert store.scalar(
        "SELECT status FROM civic_authorizations WHERE id=?",
        (int(authorization["id"]),)) == "expired"
    rejected = executor.execute_action(expiry + 1, founder_id, action)
    assert not rejected["ok"]
    assert "active business permit authorization" in rejected["reason"]


def test_attention_privacy_world_map_and_causal_chain(civic_world) -> None:
    world = civic_world
    store = world.store
    asyncio.run(world.run(max_ticks=12))

    assert int(store.scalar(
        "SELECT COALESCE(MAX(n),0) FROM ("
        "SELECT context_id,lane,COUNT(*) AS n FROM attention_context_items "
        "GROUP BY context_id,lane)")) <= 8
    assert store.scalar(
        "SELECT COUNT(*) FROM attention_contexts WHERE decision_id IS NOT NULL"
    ) > 0
    assert store.scalar(
        "SELECT COUNT(*) FROM causal_links WHERE source_kind='event' "
        "AND target_kind='decision' AND relation='cited' "
        "AND authority='actor_claim'") > 0
    causal_founding = store.scalar(
        "SELECT COUNT(*) FROM events source_event "
        "JOIN causal_links cited ON cited.source_kind='event' "
        "AND cited.source_id=source_event.id AND cited.target_kind='decision' "
        "JOIN causal_links decided ON decided.source_kind='decision' "
        "AND decided.source_id=cited.target_id "
        "AND decided.target_kind='action_proposal' "
        "JOIN action_proposals proposal ON proposal.id=decided.target_id "
        "JOIN causal_links effected ON effected.source_kind='action_proposal' "
        "AND effected.source_id=proposal.id AND effected.target_kind='event' "
        "WHERE source_event.kind='business_permit_approved' "
        "AND proposal.action_type='found_company'",
        default=0,
    )
    assert int(causal_founding) > 0

    applicant = store.query_one(
        "SELECT applicant_agent_id,id FROM service_cases ORDER BY id LIMIT 1")
    other = store.query_one(
        "SELECT id FROM agents WHERE id<>? AND alive=1 ORDER BY id LIMIT 1",
        (int(applicant["applicant_agent_id"]),))
    clerk = store.query_one(
        "SELECT assigned_agent_id FROM institution_tasks "
        "WHERE assigned_agent_id IS NOT NULL ORDER BY id LIMIT 1")
    public_cases = world.economy.city.cases_for_viewer(None, store.tick)
    assert public_cases["visibility"] == "public"
    assert public_cases["items"] == []
    own_cases = world.economy.city.cases_for_viewer(
        int(applicant["applicant_agent_id"]), store.tick)
    assert {item["id"] for item in own_cases["items"]} == {int(applicant["id"])}
    assert world.economy.city.cases_for_viewer(
        int(other["id"]), store.tick)["items"] == []
    if clerk is not None:
        clerk_cases = world.economy.city.cases_for_viewer(
            int(clerk["assigned_agent_id"]), store.tick)
        assert clerk_cases["visibility"] == "assigned_clerk"

    first_context = store.query_one(
        "SELECT context_key,snapshot_json FROM attention_contexts "
        "ORDER BY id LIMIT 1")
    store.commit()
    reopened = sqlite3.connect(store.path)
    try:
        persisted = reopened.execute(
            "SELECT context_key,snapshot_json FROM attention_contexts "
            "ORDER BY id LIMIT 1").fetchone()
        assert tuple(first_context) == persisted
    finally:
        reopened.close()

    app = FastAPI()
    install_v2_routes(app, world, SimpleNamespace())
    with TestClient(app) as client:
        map_response = client.get(
            "/api/v2/world-map",
            params={"layers": "places,presence"})
        assert map_response.status_code == 200
        map_data = map_response.json()["data"]
        assert any(
            place["kind"] == "licensing_office"
            for place in map_data["places"])
        assert all(
            item.get("agent_id") is None and item.get("name") is None
            for item in map_data["presence"]
            if item.get("place_kind") == "licensing_office")

        public_response = client.get("/api/v2/civic/cases")
        assert public_response.json()["data"]["items"] == []
        own_response = client.get(
            "/api/v2/civic/cases",
            params={"agent_id": int(applicant["applicant_agent_id"])})
        assert {
            item["id"] for item in own_response.json()["data"]["items"]
        } == {int(applicant["id"])}
        denied = client.get(
            f"/api/v2/agents/{int(applicant['applicant_agent_id'])}/attention",
            params={"viewer_agent_id": int(other["id"])})
        assert denied.status_code == 403
        allowed = client.get(
            f"/api/v2/agents/{int(applicant['applicant_agent_id'])}/attention",
            params={"viewer_agent_id": int(applicant["applicant_agent_id"])})
        assert allowed.status_code == 200
        assert set(allowed.json()["data"]["lanes"]) == {
            "mentions", "needs_action", "activity"}


def test_context_authorized_participant_catalog_and_exact_offline_replay(
        tmp_path) -> None:
    config = _config()
    source_store, source_world, source_id = open_run(
        config, None, None, data_dir=tmp_path)
    replay_store = None
    try:
        applicant_id = None
        for tick in range(1, 5):
            for agent in source_store.query(
                    "SELECT * FROM agents WHERE alive=1 AND role IS NULL ORDER BY id"):
                context = source_world.runtime.ctx.build(agent, tick)
                action = (
                    context.get("entrepreneurship_opportunity") or {}
                ).get("action", {})
                if action.get("type") == "apply_business_permit":
                    applicant_id = int(agent["id"])
                    break
            if applicant_id is not None:
                break
        assert applicant_id is not None
        catalog = source_world.runtime.participant.action_catalog(applicant_id)
        civic_items = [
            item for item in catalog
            if item["type"] == "apply_business_permit"]
        assert len(civic_items) == 1
        assert civic_items[0]["action"]["type"] == "apply_business_permit"
        assert all(
            item["type"] != "found_company" for item in catalog)

        asyncio.run(source_world.run(max_ticks=12))
        source_store.commit()
        replay_store, replay_world, replay_id = open_run(
            {}, None, source_id, data_dir=tmp_path)
        assert replay_id != source_id
        asyncio.run(replay_world.run(max_ticks=12))
        replay_store.commit()
        proof = verify_replay(source_store.path, replay_store.path)
        assert proof["exact"], proof["differences"]
        assert {
            "places",
            "occupancy_leases",
            "effective_presence",
            "service_cases",
            "service_appointments",
            "institution_tasks",
            "civic_authorizations",
            "attention_contexts",
            "attention_context_items",
        } <= {row["table"] for row in proof["tables"]}
    finally:
        if replay_store is not None:
            replay_store.close()
        source_store.close()


def test_external_rest_and_mcp_catalog_submit_exact_permit_action(
        civic_world: World) -> None:
    service = civic_world.runtime.external
    created = service.create_connection(
        tenant_id="tenant-civic",
        owner_id="owner-civic",
        display_name="Gateway Founder",
        biography="A founder using the existing citizenship gateway.",
        preferred_occupation="builder",
        tier="actor",
    )
    civic_world._spawn_due_arrivals(1)
    auth = service.authenticate(
        created["credential"]["token"], rate_limit=False)
    actor_id = int(auth["actor_id"])
    civic_world.store.set_meta(tick=1)

    app = create_app(civic_world)
    headers = {
        "Authorization": f"Bearer {created['credential']['token']}"}
    with TestClient(app) as client:
        assert client.get(
            "/api/run/status").json()["semantics_version"] == 12
        rest_turn = client.get(
            "/api/v2/agent/turn", headers=headers)
        assert rest_turn.status_code == 200
        turn = rest_turn.json()

        tools_response = client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {},
            },
        )
        assert tools_response.status_code == 200
        tool_names = {
            item["name"]
            for item in tools_response.json()["result"]["tools"]}
        assert {"ae_actions_list", "ae_action_submit"} <= tool_names

        mcp_catalog_response = client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "ae_actions_list",
                    "arguments": {},
                },
            },
        )
        assert mcp_catalog_response.status_code == 200
        mcp_catalog = mcp_catalog_response.json()[
            "result"]["structuredContent"]["actions"]
        native_catalog = civic_world.runtime.participant.action_catalog(
            actor_id)
        assert mcp_catalog == turn["action_catalog"] == native_catalog

        permit_actions = [
            item["action"] for item in mcp_catalog
            if item["type"] == "apply_business_permit"]
        assert len(permit_actions) == 1
        submission_response = client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "ae_action_submit",
                    "arguments": {
                        "target_tick": turn["target_tick"],
                        "action": permit_actions[0],
                        "observed_projection_hash": turn["projection_hash"],
                        "idempotency_key": "civic-permit-gateway-1",
                        "rationale_summary": (
                            "Apply through the existing gateway."),
                    },
                },
            },
        )
        assert submission_response.status_code == 200
        submitted = submission_response.json()[
            "result"]["structuredContent"]
        assert submitted["status"] == "queued"

    controlled, decisions = service.decisions_for_tick(
        int(turn["target_tick"]))
    assert controlled == {actor_id}
    civic_world.runtime.execute_decisions(
        int(turn["target_tick"]), decisions)
    receipt = service.receipt(auth, submitted["submission_id"])
    assert receipt["status"] == "executed"
    case = civic_world.store.query_one(
        "SELECT applicant_agent_id,status,fee_cents "
        "FROM service_cases WHERE applicant_agent_id=?",
        (actor_id,),
    )
    assert case is not None
    assert int(case["applicant_agent_id"]) == actor_id
    assert str(case["status"]) == "applied"
    assert int(case["fee_cents"]) == 2_500
