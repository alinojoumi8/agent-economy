"""A real project survives its owner, with exact rights and original refunds."""
from __future__ import annotations

from fractions import Fraction
import asyncio
import copy
import hashlib
import json
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from engine.estates import EstateError
from engine.lifecycle import Lifecycle
from engine.ledger import SYS_COMMODITY
from engine.project_rights import interests_at, steward_at
from research.export_bundle import export_bundle, validate_bundle
from research.hashing import canonical_hashes
from server.projections.construction import construction_projects_as_of, build_construction_project_detail
from server.projections.living_agents import build_living_agents_workspace
from server.projections.workspaces import build_world_workspace
from server.v2_api import install_v2_routes
from world.replay_verify import verify_replay

from .test_semantics13_construction import _config, _owner, _advance_to_building, _permit_clerk
from .test_semantics17_household_decisions import _world
from .test_semantics19_estate_cash import spent_loan
from .test_v2_regions import _qualified_migration_destination


@pytest.fixture
def property_world(tmp_path):
    config = _config(semantics=20)
    config.setdefault("households", {})["scheduled_births"] = []
    config.setdefault("lifecycle", {}).update(population_mode="drift", birth_annual_prob=0)
    world = _world(tmp_path / "property.db", config)
    try:
        owner = _owner(world)
        heir = world.store.query_one("SELECT a.* FROM agents a WHERE a.alive=1 AND a.age>=18 AND a.kind='citizen' "
            "AND a.id<>? AND a.region_id=? AND NOT EXISTS (SELECT 1 FROM agency_staff s WHERE s.agent_id=a.id AND s.active=1) "
            "ORDER BY a.id LIMIT 1", (owner["id"], owner["region_id"]))
        assert heir is not None
        world.store.execute("DELETE FROM social_ties WHERE agent_a=? OR agent_b=?", (owner["id"], owner["id"]))
        world.store.insert("social_ties", agent_a=owner["id"], agent_b=heir["id"], weight=10)
        yield world, owner, heir
    finally:
        world.close()


def validate(world):
    e = world.economy
    e.project_rights.check_invariants()
    e.estate_cases.check_invariants()
    e.business_control.check_invariants()
    e.daily_time.check_invariants()
    assert e.ledger.reconcile()[0]


def finish(world, actor, project, *, start=6):
    for tick in range(start, start+3):
        world.economy.daily_time.prepare_day(tick)
        result = world.runtime.executor.execute_action(tick, actor, {
            "type": "perform_construction_work", "project_id": project, "work_units": 2,
            "wage_cents": 100, "procurement_cents": 100, "dedupe_key": f"inherited-work-{project}-{tick}"})
        assert result["ok"], result
    assert result["status"] == "completed"


def join_household(e, actor, resident, tick):
    membership = e.households.membership(actor)
    e.store.update("household_memberships", membership["id"], left_tick=tick, end_reason="fixture")
    e.store.insert("household_memberships", household_id=e.households.membership(resident)["household_id"],
                   agent_id=actor, role="adult", joined_tick=tick)


def test_successor_finishes_a_real_project_and_uses_the_completed_home(property_world):
    world, owner, heir = property_world
    e = world.economy
    project, _ = _advance_to_building(world, owner)
    original = dict(e.construction._project(project))
    e.lifecycle.settle_death(5, owner["id"])
    assert e.construction._authorized_project(heir["id"], e.construction._project(project))
    assert e.construction.decision_context(heir["id"], 5)["eligible_actions"][0]["project_id"] == project
    finish(world, heir["id"], project)
    completed = e.construction._project(project)
    assert completed["owner_id"] == original["owner_id"] == owner["id"]
    assert completed["initiator_agent_id"] == owner["id"]
    assert e.city._home_place(heir["region_id"], heir["id"]) == completed["place_id"]
    assert e.store.scalar("SELECT actor_agent_id FROM construction_contributions WHERE project_id=? AND contribution_type='refund'", (project,)) == owner["id"]
    assert e.ledger.balance(owner["checking_account_id"]) == 0
    assert interests_at(e.store, project, 4)[0]["agent_id"] == owner["id"]
    assert interests_at(e.store, project, 5)[0]["agent_id"] == heir["id"]
    assert steward_at(e.store, project, 4)["steward_agent_id"] == owner["id"]
    assert steward_at(e.store, project, 5)["steward_agent_id"] == heir["id"]
    validate(world)


def test_multiple_inherited_projects_do_not_collide_with_original_owner_index(property_world):
    world, owner, heir = property_world
    e = world.economy
    inherited, _ = _advance_to_building(world, owner, prefix="inherited")
    own, _ = _advance_to_building(world, heir, prefix="existing")
    e.lifecycle.settle_death(5, owner["id"])
    assert {p["id"] for p in e.project_rights.owned_projects(heir["id"])} == {inherited, own}
    assert e.construction._project(inherited)["owner_id"] == owner["id"]
    assert e.construction._project(own)["owner_id"] == heir["id"]
    assert e.construction._authorized_project(heir["id"], e.construction._project(inherited))
    validate(world)


def test_children_keep_fractional_ownership_through_guardian_and_sibling_death(property_world):
    world, owner, guardian = property_world
    e = world.economy
    project, _ = _advance_to_building(world, owner)
    children = [e.households.birth(tick, owner["id"]) for tick in (3, 4)]
    join_household(e, guardian["id"], owner["id"], 4)
    e.lifecycle.settle_death(5, owner["id"])
    assert [(row["agent_id"], row["numerator"], row["denominator"]) for row in interests_at(e.store, project)] == [(child, "1", "2") for child in children]
    assert steward_at(e.store, project)["steward_agent_id"] == guardian["id"]
    assert not e.construction._authorized_project(children[0], e.construction._project(project))
    e.store.insert("social_ties", agent_a=children[0], agent_b=children[1], weight=10)
    e.lifecycle.settle_death(6, children[0])
    current = interests_at(e.store, project)
    assert [(r["agent_id"], r["numerator"], r["denominator"]) for r in current] == [(children[1], "1", "1")]
    assert len(interests_at(e.store, project, 5)) == 2
    e.lifecycle.settle_death(7, guardian["id"])
    assert steward_at(e.store, project)["steward_agent_id"] != guardian["id"]
    assert not e.construction._authorized_project(guardian["id"], e.construction._project(project))
    e.store.update("agents", children[1], age=18)
    e.households.reconcile_custody(8)
    assert steward_at(e.store, project, 5)["steward_agent_id"] == guardian["id"]
    assert steward_at(e.store, project, 8)["steward_agent_id"] == children[1]
    lots = e.store.query("SELECT numerator,denominator FROM project_interest_lots WHERE project_id=? AND ended_tick IS NULL", (project,))
    assert sum((Fraction(int(r["numerator"]), int(r["denominator"])) for r in lots), Fraction()) == 1
    validate(world)


def test_custody_change_revokes_a_living_guardians_property_authority_immediately(property_world):
    world, owner, guardian = property_world
    e = world.economy
    project, _ = _advance_to_building(world, owner)
    child = e.households.birth(4, owner["id"])
    join_household(e, guardian["id"], owner["id"], 4)
    e.lifecycle.settle_death(5, owner["id"])
    assert e.construction._authorized_project(guardian["id"], e.construction._project(project))
    member = e.households.membership(guardian["id"])
    e.store.update("household_memberships", member["id"], left_tick=6, end_reason="fixture_move")
    e.households.reconcile_custody(6)
    assert e.store.scalar("SELECT alive FROM agents WHERE id=?", (guardian["id"],)) == 1
    assert steward_at(e.store, project)["capacity"] == "vacant"
    assert not e.construction._authorized_project(guardian["id"], e.construction._project(project))
    assert interests_at(e.store, project)[0]["agent_id"] == child
    assert steward_at(e.store, project, 5)["steward_agent_id"] == guardian["id"]
    validate(world)


def test_same_tick_migration_keeps_remote_inheritance_without_assigning_a_home_in_the_new_region(property_world):
    world, owner, heir = property_world
    e = world.economy
    heir = e.store.query_one("SELECT a.* FROM agents a WHERE a.alive=1 AND a.age>=18 AND a.kind='citizen' "
        "AND a.health='healthy' AND a.retired=0 AND a.role IS NULL AND a.id<>? AND a.region_id=? "
        "AND NOT EXISTS (SELECT 1 FROM employments x WHERE x.agent_id=a.id AND x.status='active') "
        "AND NOT EXISTS (SELECT 1 FROM agency_staff s WHERE s.agent_id=a.id AND s.active=1) ORDER BY a.id LIMIT 1",
        (owner["id"], owner["region_id"]))
    assert heir is not None
    e.store.execute("DELETE FROM social_ties WHERE agent_a=? OR agent_b=?", (owner["id"], owner["id"]))
    e.store.insert("social_ties", agent_a=owner["id"], agent_b=heir["id"], weight=10)
    project, _ = _advance_to_building(world, owner)
    finish(world, owner["id"], project, start=5)
    place = e.construction._project(project)["place_id"]
    destination, career_tick = _qualified_migration_destination(e.store, heir)
    cadence = max(1, int(json.loads(heir["cadence_json"] or "{}").get("career", 30)))
    while career_tick < 8:
        career_tick += cadence
    requested = e.regions.request_migration(career_tick, heir["id"], destination, "new job")
    assert requested["ok"], requested
    e.lifecycle.settle_death(career_tick, owner["id"])
    e.regions.run_nightly(career_tick)
    e.city.run_nightly(career_tick)
    assert e.store.scalar("SELECT status FROM migrations WHERE id=?", (requested["migration_id"],)) == "completed"
    assert e.store.scalar("SELECT region_id FROM agents WHERE id=?", (heir["id"],)) == destination
    assert interests_at(e.store, project)[0]["agent_id"] == heir["id"]
    assert e.city._home_place(destination, heir["id"]) != place
    assert not e.construction._authorized_project(heir["id"], e.construction._project(project))
    validate(world)


def test_recorded_replay_and_restart_preserve_an_inherited_project_and_source(tmp_path, monkeypatch, caplog):
    config = _config(semantics=20)
    config.setdefault("households", {})["scheduled_births"] = []
    config.setdefault("lifecycle", {}).update(population_mode="drift", birth_annual_prob=0)
    config["checkpoint_dir"] = str(tmp_path / "checkpoints")
    owner_id = None
    original_draw = Lifecycle._draw

    def draw(self, tick, agent_id, mechanism):
        if tick == 1 and agent_id == owner_id and mechanism == "mortality":
            return 0.0
        return original_draw(self, tick, agent_id, mechanism)

    monkeypatch.setattr(Lifecycle, "_draw", draw)

    def open_seeded(path, run_config, *, replay=False):
        nonlocal owner_id
        world = _world(path, run_config, replay=replay)
        if world.store.tick != 0:
            return world
        # Both runs start from the same declared genesis fixture: a funded
        # project at tick zero. Inheritance then occurs in the real night phase.
        owner = _owner(world)
        owner_id = owner["id"]
        execute = world.runtime.executor.execute_action
        proposal = execute(0, owner_id, {"type": "propose_construction", "owner_type": "agent",
            "owner_id": owner_id, "region_id": owner["region_id"], "site_key": "replay-family-home",
            "target_place_type": "private_home", "name": "Replay family home", "required_funding_cents": 1200,
            "required_work_units": 6, "dedupe_key": "bootstrap-property-propose"})
        assert proposal["ok"], proposal
        project = proposal["project_id"]
        applied = execute(0, owner_id, {"type": "apply_construction_permit", "project_id": project,
                                      "dedupe_key": "bootstrap-property-apply"})
        assert applied["ok"], applied
        approved = execute(0, _permit_clerk(world, owner["region_id"]), {
            "type": "decide_construction_permit", "case_id": applied["permit_case_id"], "decision": "approve",
            "reason_code": "requirements_verified", "dedupe_key": "bootstrap-property-permit"})
        assert approved["ok"], approved
        funded = execute(0, owner_id, {"type": "contribute_construction_funding", "project_id": project,
                                     "amount_cents": 1200, "dedupe_key": "bootstrap-property-fund"})
        assert funded["ok"], funded
        return world

    path = tmp_path / "source.db"
    for _ in range(2):
        source = open_seeded(path, config)
        try:
            asyncio.run(source.step())
            assert source.store.scalar("SELECT COUNT(*) FROM project_interest_lots") >= 2
            validate(source)
        finally:
            source.close()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    replay_config = copy.deepcopy(config)
    replay_config["replay_source_path"] = str(path)
    replay = open_seeded(tmp_path / "replay.db", replay_config, replay=True)
    try:
        for _ in range(2):
            asyncio.run(replay.step())
        proof = verify_replay(path, replay.store.path)
        assert proof["exact"], proof["differences"]
        validate(replay)
        assert not any("action.execution.failed" in record.message for record in caplog.records)
    finally:
        replay.close()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_property_projections_preserve_past_ownership_and_actual_milestone_authorship(property_world, tmp_path):
    world, owner, heir = property_world
    e = world.economy
    e.store.update("agents", heir["id"], population_tier="core", pinned_core=1)
    project, _ = _advance_to_building(world, owner)
    earlier = construction_projects_as_of(e.store, as_of_tick=4)
    e.lifecycle.settle_death(5, owner["id"])
    finish(world, heir["id"], project)
    before = canonical_hashes(e.store)["authoritative_sha256"]
    assert construction_projects_as_of(e.store, as_of_tick=4) == earlier
    current = next(p for p in construction_projects_as_of(e.store, as_of_tick=8) if p["project_id"] == project)
    assert current["owner"]["id"] == heir["id"]
    assert current["ownership"]["original_owner"]["id"] == owner["id"]
    assert current["ownership"]["operator"]["agent_id"] == heir["id"]
    living = build_living_agents_workspace(e.store, as_of_tick=8, project_kind="construction", limit=200)
    record = next(p for p in living["projects"] if p["project_id"] == f"construction:{project}")
    assert record["beneficial_owner_ids"] == [heir["id"]]
    assert record["owner_agent_id"] == heir["id"]
    stages = {a["stage"]: a for a in living["activity"]["items"] if a["project_id"] == record["project_id"]}
    assert stages["proposed"]["agent_id"] == owner["id"]
    assert stages["completed"]["agent_id"] == heir["id"]
    completed = e.construction._project(project)
    metadata = json.loads(e.store.scalar("SELECT metadata_json FROM places WHERE id=?", (completed["place_id"],)))
    event = json.loads(e.store.scalar("SELECT payload_json FROM events WHERE id=?", (completed["completion_event_id"],)))
    assert metadata["original_owner_id"] == event["original_owner_id"] == owner["id"]
    assert "canonical_owner_id" not in metadata and "owner_id" not in event
    manifest = validate_bundle(export_bundle(e.store, tmp_path / "property-export"))
    assert manifest["tables"]["project_interest_lots"]["row_count"] == 2
    assert manifest["tables"]["project_stewardships"]["row_count"] == 2
    assert canonical_hashes(e.store)["authoritative_sha256"] == before
    validate(world)


def test_joint_title_projects_appear_for_both_heirs_and_guardian_without_assigning_a_sole_owner(property_world):
    world, owner, guardian = property_world
    e = world.economy
    project, _ = _advance_to_building(world, owner)
    children = [e.households.birth(tick, owner["id"]) for tick in (3, 4)]
    join_household(e, guardian["id"], owner["id"], 4)
    for person in [guardian["id"], *children]:
        e.store.update("agents", person, population_tier="core", pinned_core=1)
    e.lifecycle.settle_death(5, owner["id"])
    for person in [guardian["id"], *children]:
        living = build_living_agents_workspace(e.store, as_of_tick=5, agent_id=person, project_kind="construction")
        record = next(p for p in living["projects"] if p["project_id"] == f"construction:{project}")
        assert record["owner_agent_id"] is None
        assert record["beneficial_owner_ids"] == children
        assert record["steward_agent_id"] == guardian["id"]
        assert [(p["numerator"], p["denominator"]) for p in record["ownership"]["owners"]] == [("1", "2"), ("1", "2")]
    validate(world)


@pytest.mark.parametrize("private_party", ["heir", "guardian"])
@pytest.mark.parametrize("creditor_custody", [False, True])
def test_private_inheritance_hides_home_through_every_city_layer_and_person_residence(property_world, private_party, creditor_custody):
    world, owner, guardian = property_world
    e = world.economy
    if creditor_custody:
        wallet = owner["checking_account_id"]
        bank = e.store.scalar("SELECT bank_id FROM accounts WHERE id=?", (wallet,))
        spent_loan(e, bank, owner["id"], wallet, 2000)
    project, _ = _advance_to_building(world, owner, prefix="withheld-home-canary")
    finish(world, owner["id"], project, start=5)
    children = [e.households.birth(tick, owner["id"]) for tick in (8, 9)]
    join_household(e, guardian["id"], owner["id"], 9)
    for person in [guardian["id"], *children]:
        e.store.update("agents", person, population_tier="core", pinned_core=1)
    private = children[0] if private_party == "heir" else guardian["id"]
    e.store.update("agents", private, population_tier="periphery", pinned_core=0)
    if creditor_custody:
        for account in e.store.query("SELECT * FROM accounts WHERE owner_type='agent' AND owner_id=? "
                "AND kind IN ('checking','savings','fx') AND balance_cents>0 ORDER BY id", (owner["id"],)):
            e.ledger.transfer(9, account["id"], e.ledger.system_account(SYS_COMMODITY,
                currency_code=account["currency_code"]), account["balance_cents"])
    e.lifecycle.settle_death(10, owner["id"])
    if creditor_custody:
        assert interests_at(e.store, project)[0]["agent_id"] == owner["id"]
        assert steward_at(e.store, project)["capacity"] == "estate"
    e.city.run_nightly(10)
    e.city.establish_effective_presence(11)
    e.store.set_meta(tick=11)
    place = e.construction._project(project)["place_id"]
    # A public co-owner can be resident at a home withheld for another owner.
    assert e.city._home_place(owner["region_id"], children[1]) == place
    assert build_construction_project_detail(e.store, project_id=str(project), as_of_tick=11) is None
    before = canonical_hashes(e.store)["authoritative_sha256"]
    workspace = build_world_workspace(e.store, as_of_tick=11)
    living = build_living_agents_workspace(e.store, as_of_tick=11, agent_id=children[1])
    assert all(p["id"] != place for p in workspace["places"])
    assert all(p["place_id"] != place for p in workspace["presence"])
    assert living["agents"][0]["residence"] is None
    assert "withheld-home-canary" not in json.dumps([workspace, living]).lower()
    app = FastAPI()
    install_v2_routes(app, world, SimpleNamespace(hosted_safe=False))
    with TestClient(app) as client:
        for path in ["/api/v2/world-map?tick=11&population=all", "/api/v2/world-map?tick=11&layers=agents", "/api/v2/map"]:
            response = client.get(path)
            assert response.status_code == 200, response.text
            payload = response.json().get("data", response.json())
            assert "withheld-home-canary" not in json.dumps(payload).lower()
            assert all(p["id"] != place for p in payload.get("places", []))
            assert all(p.get("place_id") != place for p in payload.get("presence", []))
            for person in payload.get("agents", payload.get("core_agents", [])):
                assert person.get("place_id") != place
    assert canonical_hashes(e.store)["authoritative_sha256"] == before
    validate(world)


def test_no_heir_cancels_unfinished_project_and_refunds_through_recorded_estate(property_world):
    world, owner, _ = property_world
    e = world.economy
    project, _ = _advance_to_building(world, owner)
    e.store.execute("DELETE FROM social_ties WHERE agent_a=? OR agent_b=?", (owner["id"], owner["id"]))
    e.lifecycle.settle_death(5, owner["id"])
    assert e.construction._project(project)["status"] == "cancelled"
    assert e.construction._project(project)["refunded_funding_cents"] == 1200
    assert interests_at(e.store, project)[0]["agent_id"] is None
    assert steward_at(e.store, project)["capacity"] == "vacant"
    refund = e.store.query_one("SELECT * FROM construction_contributions WHERE project_id=? AND contribution_type='refund'", (project,))
    assert refund["actor_agent_id"] == owner["id"]
    assert e.store.scalar("SELECT received_cents FROM estate_receipts WHERE origin_transaction_id=?", (refund["transaction_id"],)) == 1200
    assert e.ledger.balance(owner["checking_account_id"]) == 0
    before = canonical_hashes(e.store)["authoritative_sha256"]
    e.lifecycle.settle_death(5, owner["id"])
    e.construction.cancel_unclaimed(6, project)
    assert canonical_hashes(e.store)["authoritative_sha256"] == before
    validate(world)


def test_completed_unclaimed_house_does_not_become_a_random_residential_district(property_world):
    world, owner, heir = property_world
    e = world.economy
    project, _ = _advance_to_building(world, owner)
    finish(world, owner["id"], project, start=5)
    place = e.construction._project(project)["place_id"]
    e.store.execute("DELETE FROM social_ties WHERE agent_a=? OR agent_b=?", (owner["id"], owner["id"]))
    e.lifecycle.settle_death(8, owner["id"])
    assert e.construction._project(project)["status"] == "completed"
    assert interests_at(e.store, project)[0]["agent_id"] is None
    for actor in e.store.query("SELECT id,region_id FROM agents WHERE alive=1 AND region_id=?", (heir["region_id"],)):
        assert e.city._home_place(actor["region_id"], actor["id"]) != place
    validate(world)


def test_property_failure_rolls_back_death_cash_rights_and_construction(property_world, monkeypatch):
    world, owner, _ = property_world
    e = world.economy
    _advance_to_building(world, owner)
    before = canonical_hashes(e.store)["authoritative_sha256"]
    def fail(*args, **kwargs):
        raise RuntimeError("injected after property distribution")
    monkeypatch.setattr(e.project_rights, "refresh", fail)
    with pytest.raises(RuntimeError, match="injected"):
        e.lifecycle.settle_death(5, owner["id"])
    assert canonical_hashes(e.store)["authoritative_sha256"] == before
    assert e.estate_cases._pending is None
    validate(world)


def test_unclaimed_cancellation_rejects_owned_property_and_history_is_immutable(property_world):
    world, owner, _ = property_world
    e = world.economy
    project, _ = _advance_to_building(world, owner)
    before = canonical_hashes(e.store)["authoritative_sha256"]
    with pytest.raises(EstateError, match="beneficial owner"):
        e.construction.cancel_unclaimed(5, project)
    assert canonical_hashes(e.store)["authoritative_sha256"] == before
    e.lifecycle.settle_death(5, owner["id"])
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        e.store.execute("UPDATE project_interest_lots SET numerator='2'")
    with pytest.raises(sqlite3.IntegrityError, match="permanent"):
        e.store.execute("DELETE FROM project_stewardships")
    validate(world)
