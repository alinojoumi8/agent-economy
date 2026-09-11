"""Death ends consent and personal authority, while institutional evidence survives."""
import asyncio
import copy
import hashlib
import json
import random
import shutil
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from engine.core import Economy
from engine.estates import EstateError
from engine.households import HouseholdError
from engine.lifecycle import Lifecycle
from engine.migrations import registry
from engine.store import Store
from research.export_bundle import export_bundle, validate_bundle
from research.hashing import canonical_hashes
from server.v2_api import install_v2_routes
from world.replay_verify import verify_replay

from .conftest import make_agent, make_bank
from .test_semantics17_household_decisions import family, opportunity
from .test_semantics17_household_decisions import _world
from .test_semantics13_construction import _config


@pytest.fixture
def continuity(store):
    config = {"engine_semantics_version": 20, "seed": 1,
              "lifecycle": {"birth_annual_prob": 0, "population_mode": "drift"},
              "family_decisions": {"scripted_matching": False},
              "political_model": {"house_seats": 1, "senate_seats": 1,
                                  "actor_bound_authorization": True}}
    store.execute("UPDATE run_meta SET config_json=?", (json.dumps(config),))
    e = Economy(store, config, random.Random(1), random.Random(2))
    e.ensure_system_accounts()
    for region, currency in ((1, "USD"), (2, "CAD")):
        store.insert("regions", id=region, region_key="northstar" if region == 1 else "shore",
                     name=currency, currency_code=currency, population_target=10,
                     specialization_json="{}", x=region, y=0, legal_ruleset="test")
        store.insert("currencies", code=currency, name=currency, numeraire_rate_ppm=1_000_000, issuer_region_id=region)
    bank = make_bank(e)
    people = [make_agent(e, bank, name, age=30, region_id=1, cadence_json='{"career":1}')[0]
              for name in ("Aria", "Ben", "Casey")]
    for i, person in enumerate(people):
        for other in people[i + 1:]:
            store.insert("social_ties", agent_a=person, agent_b=other, weight=0.8)
    e.households.initialize()
    return e, people


def validate(e):
    # These direct transition tests skip the normal nightly age phase.
    tick = e.store.scalar("SELECT COALESCE(MAX(tick),0) FROM events")
    for person in e.store.query("SELECT * FROM agents WHERE alive=1 ORDER BY id"):
        e.households.advance_age(tick, person)
    e.estate_cases.check_invariants()
    e.households.check_invariants(tick)
    assert e.ledger.reconcile()[0]
    assert e.estate_cases._pending is None


def item_for(e, person, kind):
    return e.store.query_one("SELECT i.* FROM estate_items i JOIN estate_cases c ON c.id=i.estate_id "
        "WHERE c.deceased_agent_id=? AND i.kind=?", (person, kind))


def pending_family(e, people, *, child=False):
    a, b, c = people
    affected = e.households.birth(1, a) if child else c
    if not child:
        home = e.households.membership(a)["household_id"]
        e.families._move_members(1, [{"agent_id": c}], home, "declared_household")
    proposal = e.families.propose(2, a, "partnership", "shared-consent", partner_id=b)
    return affected, proposal["household_decision_id"]


def seat(e, person, tick=0):
    party = e.store.scalar("SELECT id FROM political_parties ORDER BY id LIMIT 1")
    if party is None:
        account = e.ledger.create_account("party", None, "treasury")
        party = e.store.insert("political_parties", name="Fixture Party", platform_json="{}", treasury_account_id=account)
        e.store.update("accounts", account, owner_id=party)
    committee = e.store.scalar("SELECT id FROM committees ORDER BY id LIMIT 1")
    if committee is None:
        committee = e.store.insert("committees", name="House Finance", chamber="house", jurisdiction="tax")
    member = e.store.insert("legislators", agent_id=person, chamber="house", seat_number=1,
                            party_id=party, term_start_tick=tick, term_end_tick=tick + 100, active=1)
    e.store.insert("committee_members", committee_id=committee, legislator_id=member, is_chair=1)
    e.store.update("agents", person, role="legislator_house")
    return member


@pytest.mark.parametrize("child", [True, False])
def test_death_inventories_child_and_other_adult_consent_without_transferring_it(continuity, child):
    e, people = continuity
    affected, proposal = pending_family(e, people, child=child)
    before = [tuple(r) for r in e.store.query("SELECT * FROM household_assents ORDER BY decision_id,actor_id")]
    e.lifecycle.settle_death(3, affected)
    item = item_for(e, affected, "family_commitment")
    assert item["source_id"] == proposal and item["disposition"] == "extinguished"
    assert json.loads(item["snapshot_json"])["status"] == "pending"
    decision = e.store.query_one("SELECT * FROM household_decisions WHERE id=?", (proposal,))
    assert (decision["status"], decision["reason"], decision["settled_tick"]) == ("cancelled", "person_died", 3)
    assert [tuple(r) for r in e.store.query("SELECT * FROM household_assents ORDER BY decision_id,actor_id")] == before
    with pytest.raises(HouseholdError, match="no longer pending"):
        e.families.respond(4, people[1], proposal, "accept")
    assert e.store.scalar("SELECT COUNT(*) FROM partnerships") == 0
    validate(e)


def test_agreed_move_cannot_relocate_survivors_on_a_deceased_childs_consent_snapshot(continuity):
    e, (a, b, _) = continuity
    pair = e.families.propose(0, a, "partnership", "pair", partner_id=b)["household_decision_id"]
    assert e.families.respond(0, b, pair, "accept")["status"] == "applied"
    child = e.households.birth(1, a)
    opportunity(e, a)
    move = e.families.propose(2, a, "joint_move", "move", destination_region_id=2)["household_decision_id"]
    assert e.families.respond(2, b, move, "accept")["status"] == "agreed"
    e.lifecycle.settle_death(3, child)
    assert item_for(e, child, "family_commitment")["source_id"] == move
    e.families.run_nightly(4)
    assert [r[0] for r in e.store.query("SELECT region_id FROM agents WHERE id IN (?,?) ORDER BY id", (a, b))] == [1, 1]
    assert e.store.scalar("SELECT COUNT(*) FROM migrations") == 0
    assert e.store.scalar("SELECT reason FROM household_decisions WHERE id=?", (move,)) == "person_died"
    validate(e)


def test_office_death_preserves_votes_bills_and_agency_resources_without_granting_heir_authority(continuity, tmp_path):
    e, (person, heir, _) = continuity
    member = seat(e, person)
    agency = e.store.insert("agencies", name="Agency", mandate="markets", capacity=1.5, leader_agent_id=person)
    bill = e.politics.sponsor_bill(1, person, {"title": "Original tax bill", "topic": "tax", "policy_changes": {"tax_rate_bps": 2000}})
    assert bill["ok"], bill
    assert e.politics.committee_vote(1, person, bill["bill_id"], "yes")["ok"]
    records = {table: [tuple(r) for r in e.store.query(f"SELECT * FROM {table} ORDER BY 1")]
               for table in ("bills", "bill_versions", "legislative_votes", "committee_members", "political_parties")}
    e.lifecycle.settle_death(2, person)
    assert e.store.scalar("SELECT active FROM legislators WHERE id=?", (member,)) == 0
    assert e.store.scalar("SELECT term_end_tick FROM legislators WHERE id=?", (member,)) == 2
    assert e.store.scalar("SELECT leader_agent_id FROM agencies WHERE id=?", (agency,)) is None
    assert e.store.scalar("SELECT capacity FROM agencies WHERE id=?", (agency,)) == 1.5
    assert e.politics.state()["legislators"] == []
    assert not e.politics.cast_vote(3, person, bill["bill_id"], "yes")["ok"]
    assert not e.politics.cast_vote(3, heir, bill["bill_id"], "yes")["ok"]
    assert not e.legal.controls(person, "agent", person)
    for table, rows in records.items():
        assert [tuple(r) for r in e.store.query(f"SELECT * FROM {table} ORDER BY 1")] == rows
    old = json.loads(item_for(e, person, "legislative_office")["snapshot_json"])
    assert old["active"] == 1 and old["term_end_tick"] == 100 and old["committee_memberships"]
    assert item_for(e, person, "agency_leadership")["disposition"] == "extinguished"
    assert validate_bundle(export_bundle(e.store, tmp_path / "authority-export"))["tables"]["estate_items"]["row_count"] > 0
    validate(e)


def test_former_officeholders_keep_distinct_identities_through_three_deaths(continuity):
    e, people = continuity
    members = []
    # Each appointment is declared test setup. The actual engine closes each
    # death; this does not stand in for a candidate/election model.
    for tick, person in enumerate(people, start=1):
        members.append(seat(e, person, tick=tick))
        e.lifecycle.settle_death(tick + 1, person)
        validate(e)
    assert [tuple(r) for r in e.store.query("SELECT agent_id,active FROM legislators ORDER BY id")] == [(p, 0) for p in people]
    assert [json.loads(r[0])["id"] for r in e.store.query("SELECT snapshot_json FROM estate_items WHERE kind='legislative_office' ORDER BY id")] == members


def test_organization_api_keeps_directors_on_earlier_days_after_successive_deaths(continuity):
    e, (a, b, _) = continuity
    agency_a = e.store.insert("agencies", name="First Agency", mandate="markets", capacity=1.5, leader_agent_id=a)
    agency_b = e.store.insert("agencies", name="Second Agency", mandate="services", capacity=0.5, leader_agent_id=b)
    e.store.execute("UPDATE run_meta SET tick=5")
    app = FastAPI()
    install_v2_routes(app, SimpleNamespace(store=e.store, economy=e, config=e.config), SimpleNamespace(hosted_safe=False))

    def agencies(client, tick):
        response = client.get(f"/api/v2/workspaces/organizations?tick={tick}")
        assert response.status_code == 200, response.text
        rows = [row for row in response.json()["data"]["organizations"] if row["type"] == "agency"]
        # No estate snapshots, beneficiary identities or future death fields.
        assert all(set(row) == {"id", "name", "mandate", "capacity", "leader_agent_id", "type", "status", "active"}
                   for row in rows)
        return {row["id"]: row for row in rows}

    with TestClient(app) as client:
        original = agencies(client, 1)
        e.lifecycle.settle_death(2, a)
        e.lifecycle.settle_death(4, b)
        before_reads = canonical_hashes(e.store)["authoritative_sha256"]
        assert agencies(client, 1) == original
        assert e.city.agency_detail(agency_a, 1)["leader_agent_id"] == a
        assert e.city.agency_detail(agency_b, 1)["leader_agent_id"] == b
        for tick, leaders in ((2, (None, b)), (3, (None, b)), (4, (None, None)), (5, (None, None))):
            selected = agencies(client, tick)
            assert (selected[agency_a]["leader_agent_id"], selected[agency_b]["leader_agent_id"]) == leaders
            assert (e.city.agency_detail(agency_a, tick)["leader_agent_id"], e.city.agency_detail(agency_b, tick)["leader_agent_id"]) == leaders
            assert (selected[agency_a]["capacity"], selected[agency_b]["capacity"]) == (1.5, 0.5)
        assert canonical_hashes(e.store)["authoritative_sha256"] == before_reads
    validate(e)


def test_counsel_death_releases_representation_but_the_living_client_can_continue_the_case(continuity):
    e, (client, respondent, counsel) = continuity
    e.store.update("agents", counsel, occupation="lawyer", role="lawyer")
    filed = e.legal.file_claim(1, client, {"counsel_agent_id": counsel, "claimant": {"type": "agent", "id": client},
        "respondent": {"type": "agent", "id": respondent}, "requested_remedy": {"type": "damages", "amount_cents": 40}})
    assert filed["ok"], filed
    matter = filed["matter_id"]
    assert e.legal_representation.respond(1, counsel, {
        "request_id": filed["counsel_request_id"], "decision": "accept"})["ok"]
    assert e.store.scalar("SELECT counsel_agent_id FROM legal_matters WHERE id=?", (matter,)) == counsel
    e.lifecycle.settle_death(2, counsel)
    assert item_for(e, counsel, "legal_representation")["source_id"] == matter
    assert e.store.scalar("SELECT counsel_agent_id FROM legal_matters WHERE id=?", (matter,)) is None
    assert e.store.scalar("SELECT status FROM legal_matters WHERE id=?", (matter,)) == "filed"
    evidence = e.store.scalar("SELECT id FROM events WHERE kind='legal_matter_filed' ORDER BY id DESC LIMIT 1")
    filing = {"matter_id": matter, "filer_type": "agent", "filer_id": client, "filing_type": "evidence",
              "evidence_event_ids": [evidence], "body": "Client continues the recorded matter."}
    assert not e.legal.submit_filing(3, counsel, filing)["ok"]
    assert e.legal.submit_filing(3, client, filing)["ok"]
    assert e.store.scalar("SELECT COUNT(*) FROM legal_awards") == 0
    validate(e)


def test_failed_authority_disposition_rolls_back_family_cancellation_and_the_whole_death(continuity, monkeypatch):
    e, people = continuity
    affected, _ = pending_family(e, people)
    seat(e, affected)
    before = canonical_hashes(e.store)["authoritative_sha256"]
    original = e.civic_authority.close_person
    def fail(*args):
        original(*args)
        raise RuntimeError("injected authority disposition failure")
    monkeypatch.setattr(e.civic_authority, "close_person", fail)
    with pytest.raises(RuntimeError, match="injected authority"):
        e.lifecycle.settle_death(3, affected)
    assert canonical_hashes(e.store)["authoritative_sha256"] == before
    assert e.estate_cases._pending is None
    monkeypatch.setattr(e.civic_authority, "close_person", original)
    e.lifecycle.settle_death(3, affected)
    validate(e)


@pytest.mark.parametrize("target", ["legislator", "agency", "counsel"])
def test_reconciliation_rejects_restoring_dead_personal_authority(continuity, target):
    e, (person, client, respondent) = continuity
    member = seat(e, person)
    agency = e.store.insert("agencies", name="Agency", mandate="markets", capacity=1, leader_agent_id=person)
    e.store.update("agents", person, occupation="lawyer")
    filed = e.legal.file_claim(1, client, {"counsel_agent_id": person, "claimant": {"type": "agent", "id": client},
        "respondent": {"type": "agent", "id": respondent}, "requested_remedy": {"type": "none"}})
    assert filed["ok"], filed
    assert e.legal_representation.respond(1, person, {
        "request_id": filed["counsel_request_id"], "decision": "accept"})["ok"]
    e.lifecycle.settle_death(2, person)
    if target == "legislator":
        e.store.update("legislators", member, active=1)
    elif target == "agency":
        e.store.update("agencies", agency, leader_agent_id=person)
    else:
        e.store.update("legal_matters", filed["matter_id"], counsel_agent_id=person)
    with pytest.raises(EstateError, match="deceased"):
        e.estate_cases.check_invariants()


def test_older_recorded_semantics_retain_their_authority_behavior(family):
    e, (person, _, _), _ = family
    member = seat(e, person)
    e.lifecycle.settle_death(2, person)
    assert e.engine_semantics_version == 17
    assert e.store.scalar("SELECT active FROM legislators WHERE id=?", (member,)) == 1
    assert e.politics._legislator_for_agent(person) is not None
    assert e.legal.controls(person, "agent", person)
    assert e.store.scalar("SELECT COUNT(*) FROM estate_cases") == 0


def test_migration_preserves_original_office_evidence_and_the_untouched_source_file(tmp_path, monkeypatch):
    original = tmp_path / "original24.db"
    migrations = registry._MIGRATIONS
    monkeypatch.setattr(registry, "_MIGRATIONS", tuple(m for m in migrations if m.version < 25))
    store = Store(str(original))
    config = {"engine_semantics_version": 19, "political_model": {"house_seats": 2, "senate_seats": 1}}
    store.init_run_meta("existing-offices", 1, config)
    store.execute("UPDATE run_meta SET schema_version=24")
    e = Economy(store, config, random.Random(1), random.Random(2))
    e.ensure_system_accounts()
    e.politics.initialize()
    leader = store.scalar("SELECT agent_id FROM legislators WHERE chamber='house' ORDER BY id LIMIT 1")
    bill = e.politics.sponsor_bill(0, leader, {"title": "Existing bill", "policy_changes": {"tax_rate_bps": 1000}})
    assert bill["ok"], bill
    sponsor = store.scalar("SELECT sponsor_legislator_id FROM bills WHERE id=?", (bill["bill_id"],))
    before = canonical_hashes(store)["tables"]
    store.close()
    digest = hashlib.sha256(original.read_bytes()).hexdigest()
    monkeypatch.setattr(registry, "_MIGRATIONS", migrations)
    migrated = tmp_path / "migrated25.db"
    shutil.copy2(original, migrated)
    store = Store(str(migrated))
    try:
        after = canonical_hashes(store)["tables"]
        assert {name for name in before if before[name] != after[name]} <= {"run_meta", "schema_migrations"}
        assert store.scalar("SELECT COUNT(*) FROM legislators") == 3
        assert store.scalar("SELECT sponsor_legislator_id FROM bills WHERE id=?", (bill["bill_id"],)) == sponsor
        assert store.scalar("SELECT name FROM sqlite_master WHERE name='ix_occupied_legislative_seat'") == "ix_occupied_legislative_seat"
    finally:
        store.close()
    assert hashlib.sha256(original.read_bytes()).hexdigest() == digest


def test_nightly_shared_death_and_office_vacancies_survive_restart_and_exact_replay(tmp_path, monkeypatch, caplog):
    config = _config(semantics=20)
    config["construction"].update(enabled=False, agent_initiation=False)
    config.setdefault("entrepreneurship", {})["enabled"] = False
    config.setdefault("households", {})["scheduled_births"] = []
    config.setdefault("lifecycle", {}).update(population_mode="drift", birth_annual_prob=0)
    config.setdefault("family_decisions", {})["scripted_matching"] = False
    config["checkpoint_dir"] = str(tmp_path / "checkpoints")
    targets = {}
    draw = Lifecycle._draw

    def forced_deaths(self, tick, person, mechanism):
        if tick == 1 and mechanism == "mortality" and person in targets.values():
            return 0.0
        return draw(self, tick, person, mechanism)

    monkeypatch.setattr(Lifecycle, "_draw", forced_deaths)

    def open_seeded(path, settings, *, replay=False):
        world = _world(path, settings, replay=replay)
        if world.store.tick != 0:
            return world
        e = world.economy
        people = e.store.query("SELECT a.id,a.region_id FROM agents a WHERE a.alive=1 AND a.kind='citizen' "
            "AND a.age BETWEEN 25 AND 45 AND a.retired=0 AND NOT EXISTS (SELECT 1 FROM partnerships p "
            "WHERE p.ended_tick IS NULL AND (p.agent_a=a.id OR p.agent_b=a.id)) ORDER BY a.region_id,a.id")
        a = people[0]["id"]
        peers = [row["id"] for row in people[1:] if row["region_id"] == people[0]["region_id"]]
        b, affected = peers[:2]
        tie = e.store.query_one("SELECT 1 FROM social_ties WHERE agent_a=? AND agent_b=?", (a, b))
        if tie is not None:
            e.store.execute("UPDATE social_ties SET weight=1 WHERE agent_a=? AND agent_b=?", (a, b))
        else:
            e.store.insert("social_ties", agent_a=a, agent_b=b, weight=1)
        # Declared shared residence among existing adults. Birth/dependent
        # cases above use the actual positive birth tick instead.
        targets["member"] = affected
        e.families._move_members(0, [{"agent_id": affected}], e.households.membership(a)["household_id"], "declared_genesis_household")
        assert e.families.propose(0, a, "partnership", "genesis-consent", partner_id=b)["status"] == "pending"
        targets["legislator"] = e.store.scalar("SELECT agent_id FROM legislators WHERE active=1 ORDER BY id LIMIT 1")
        targets["director"] = e.store.scalar("SELECT leader_agent_id FROM agencies ORDER BY id LIMIT 1")
        targets["counsel"] = e.store.scalar("SELECT id FROM agents WHERE alive=1 AND role='lawyer' ORDER BY id LIMIT 1")
        assert all(value is not None for value in targets.values())
        filed = e.legal.file_claim(0, a, {"counsel_agent_id": targets["counsel"],
            "claimant": {"type": "agent", "id": a}, "respondent": {"type": "agent", "id": b},
            "requested_remedy": {"type": "none"}})
        assert filed["ok"], filed
        assert e.legal_representation.respond(0, targets["counsel"], {
            "request_id": filed["counsel_request_id"], "decision": "accept"})["ok"]
        return world

    source_path = tmp_path / "source.db"
    for _ in range(2):
        source = open_seeded(source_path, config)
        try:
            asyncio.run(source.step())
            assert all(source.store.scalar("SELECT alive FROM agents WHERE id=?", (person,)) == 0 for person in targets.values())
            assert item_for(source.economy, targets["member"], "family_commitment") is not None
            assert item_for(source.economy, targets["legislator"], "legislative_office") is not None
            assert item_for(source.economy, targets["director"], "agency_leadership") is not None
            assert item_for(source.economy, targets["counsel"], "legal_representation") is not None
            source.economy.estate_cases.check_invariants()
        finally:
            source.close()
    before = hashlib.sha256(source_path.read_bytes()).hexdigest()
    replay_config = copy.deepcopy(config)
    replay_config["replay_source_path"] = str(source_path)
    replay = open_seeded(tmp_path / "replay.db", replay_config, replay=True)
    try:
        for _ in range(2):
            asyncio.run(replay.step())
        proof = verify_replay(source_path, replay.store.path)
        assert proof["exact"], proof["differences"]
        replay.economy.estate_cases.check_invariants()
        assert not any("action.execution.failed" in record.message for record in caplog.records)
    finally:
        replay.close()
    assert hashlib.sha256(source_path.read_bytes()).hexdigest() == before
