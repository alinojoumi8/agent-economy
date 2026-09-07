"""Mutual assent, custody, atomic relocation and recorded family decisions."""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import random
import sqlite3

import pytest

from agents.citizen_actions import citizen_world_action_types
from agents.participant import ParticipantService
from agents.policies import citizen_decision, founder_decision
from engine.actions import ActionExecutor
from engine.core import Economy
from engine.households import HouseholdError
from engine.migrations import registry
from engine.store import Store
from research.hashing import HashContractError, canonical_hashes, load_hash_contract
from research.export_bundle import export_bundle, validate_bundle
from run_config import load_config
from world.loop import World
from world.replay_verify import verify_replay

from .conftest import make_agent, make_bank


@pytest.fixture
def family(store):
    config = {"engine_semantics_version": 17, "seed": 1,
              "lifecycle": {"birth_annual_prob": 0, "population_mode": "drift"},
              "family_decisions": {"scripted_matching": False}}
    store.execute("UPDATE run_meta SET config_json=?", (json.dumps(config),))
    e = Economy(store, config, random.Random(1), random.Random(2))
    e.ensure_system_accounts()
    for region, currency in ((1, "USD"), (2, "CAD")):
        store.insert("regions", id=region, region_key=f"region-{region}", name=currency,
                     currency_code=currency, population_target=10, specialization_json="{}",
                     x=region, y=0, legal_ruleset="test")
        store.insert("currencies", code=currency, name=currency, numeraire_rate_ppm=1_000_000, issuer_region_id=region)
    bank = make_bank(e)
    people = [make_agent(e, bank, f"Person {i}", age=30, region_id=1,
                        cadence_json='{"career":1}') for i in range(3)]
    for i, (a, _) in enumerate(people):
        for b, _ in people[i + 1:]:
            store.insert("social_ties", agent_a=a, agent_b=b, weight=0.8)
    e.households.initialize()
    return e, [p[0] for p in people], [p[1] for p in people]


def propose(e, a, b, tick=1, key="pair"):
    return e.families.propose(tick, a, "partnership", key, partner_id=b)["household_decision_id"]


def join(e, a, b):
    proposal = propose(e, a, b)
    assert e.families.respond(1, b, proposal, "accept")["status"] == "applied"
    return proposal


def opportunity(e, sponsor):
    for region, wage in ((1, 10_000), (2, 40_000)):
        firm = e.store.insert("firms", name=f"Employer {region}", region_id=region,
                              currency_code="USD" if region == 1 else "CAD")
        e.store.insert("jobs", tick=1, firm_id=firm, title="worker", wage_cents=wage, status="open")
    assert e.regions._qualified_migration_option(2, sponsor, 2)[1] == ""


def test_mutual_assent_preserves_accounts_assets_and_primary_custody(family):
    e, (a, b, outsider), accounts = family
    child = e.households.birth(1, a)
    before = [tuple(r) for r in e.store.query("SELECT * FROM accounts ORDER BY id")]
    homes = [e.households.membership(p)["household_id"] for p in (a, b)]
    decision = propose(e, a, b)
    assert e.families.partnership(a) is None
    assert len(set(homes)) == 2
    assert e.families.decision_context(outsider, 1)["pending"] == []
    assert e.families.decision_context(b, 1)["pending"][0]["own_assent"] is None
    with pytest.raises(HouseholdError, match="affected adult"):
        e.families.respond(1, outsider, decision, "accept")
    e.families.respond(1, b, decision, "accept")
    assert e.families.respond(2, b, decision, "accept")["status"] == "applied"
    assert propose(e, a, b) == decision
    assert e.store.scalar("SELECT COUNT(*) FROM partnerships") == 1
    assert e.store.scalar("SELECT COUNT(*) FROM household_assents") == 2
    assert len({e.households.membership(p)["household_id"] for p in (a, b, child)}) == 1
    assert e.households.guardian_id(child) == a
    assert [tuple(r) for r in e.store.query("SELECT * FROM accounts ORDER BY id")] == before
    assert e.ledger.reconcile()[0]
    with pytest.raises(HouseholdError, match="different household terms"):
        propose(e, a, outsider)
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        e.store.execute("UPDATE household_assents SET decision='reject' WHERE actor_id=?", (b,))


@pytest.mark.parametrize("change", ["birth", "death", "separation", "adulthood", "expiry", "reject"])
def test_old_terms_cannot_authorize_a_changed_household(family, change):
    e, (a, b, _), _ = family
    child = e.households.birth(1, a)
    decision = propose(e, a, b)
    if change == "birth":
        e.households.birth(2, a)
    elif change == "death":
        e.lifecycle.settle_death(2, a)
    elif change == "separation":
        # Explicit separation can withdraw an adult without trapping them in a proposal.
        e.families.propose(2, a, "separation", "leave")
    elif change == "adulthood":
        e.store.update("agents", child, age=18)
    if change == "reject":
        assert e.families.respond(2, b, decision, "reject")["status"] == "rejected"
    else:
        tick = 31 if change == "expiry" else 2
        e.families.reconcile(tick)
        with pytest.raises(HouseholdError, match="no longer pending"):
            e.families.respond(tick, b, decision, "accept")
    assert e.store.scalar("SELECT COUNT(*) FROM partnerships") == 0
    assert e.households.membership(b)["household_id"] != e.households.membership(child)["household_id"]


def test_every_existing_adult_must_assent_and_separation_takes_primary_wards(family):
    e, (a, b, c), _ = family
    first = join(e, a, b)
    child = e.households.birth(1, a)
    separation = e.families.propose(2, a, "separation", "leave")
    assert separation["status"] == "applied"
    assert e.families.partnership(a) is None
    assert e.households.membership(a)["household_id"] == e.households.membership(child)["household_id"]
    assert e.households.guardian_id(child) == a
    assert e.store.scalar("SELECT ended_tick FROM partnerships WHERE decision_id=?", (first,)) == 2
    # A household can contain another consenting adult without making them a partner.
    current = e.households.membership(c)
    e.store.update("household_memberships", current["id"], left_tick=2, end_reason="test_household")
    e.store.insert("household_memberships", household_id=e.households.membership(a)["household_id"],
                   agent_id=c, role="adult", joined_tick=2)
    next_decision = propose(e, a, b, tick=3, key="pair-again")
    assert e.families.respond(3, b, next_decision, "accept")["status"] == "pending"
    assert e.families.respond(3, c, next_decision, "accept")["status"] == "applied"


def test_merge_failure_rolls_back_final_assent_memberships_and_relationship(family, monkeypatch):
    e, (a, b, _), _ = family
    proposal = propose(e, a, b)
    before = [tuple(r) for r in e.store.query("SELECT * FROM household_memberships")]
    original = e.store.insert
    def fail(table, **values):
        if table == "partnerships":
            raise RuntimeError("injected relationship failure")
        return original(table, **values)
    monkeypatch.setattr(e.store, "insert", fail)
    with pytest.raises(RuntimeError, match="injected"):
        e.families.respond(1, b, proposal, "accept")
    assert [tuple(r) for r in e.store.query("SELECT * FROM household_memberships")] == before
    assert e.store.scalar("SELECT COUNT(*) FROM household_assents") == 1
    assert e.store.scalar("SELECT status FROM household_decisions") == "pending"


def test_joint_move_waits_for_all_adults_and_moves_children_without_converting_cash(family):
    e, (a, b, _), accounts = family
    join(e, a, b)
    child = e.households.birth(1, a)
    opportunity(e, a)
    decision = e.families.propose(2, a, "joint_move", "move", destination_region_id=2)["household_decision_id"]
    e.families.run_nightly(3)
    assert e.store.scalar("SELECT region_id FROM agents WHERE id=?", (a,)) == 1
    e.families.respond(3, b, decision, "accept")
    e.families.run_nightly(3)
    assert e.store.scalar("SELECT region_id FROM agents WHERE id=?", (a,)) == 1
    balances = [e.ledger.balance(account) for account in accounts]
    e.families.run_nightly(4)
    assert {e.store.scalar("SELECT region_id FROM agents WHERE id=?", (p,)) for p in (a, b, child)} == {2}
    assert e.store.scalar("SELECT COUNT(*) FROM migrations") == 3
    assert e.store.scalar("SELECT SUM(balance_cents) FROM accounts WHERE currency_code='CAD'") == 0
    assert [e.ledger.balance(account) for account in accounts] == balances
    assert e.households.guardian_id(child) == a
    e.households.reconcile_residence(4)
    assert len({e.households.membership(p)["household_id"] for p in (a, b, child)}) == 1
    e.families.run_nightly(5)
    assert e.store.scalar("SELECT COUNT(*) FROM migrations") == 3
    assert e.ledger.reconcile()[0]


def test_joint_move_rollback_and_death_before_settlement(family, monkeypatch):
    e, (a, b, _), _ = family
    join(e, a, b)
    child = e.households.birth(1, a)
    opportunity(e, a)
    decision = e.families.propose(2, a, "joint_move", "move", destination_region_id=2)["household_decision_id"]
    e.families.respond(2, b, decision, "accept")
    original = e.store.insert
    def fail(table, **values):
        if table == "migrations" and values["agent_id"] == b:
            raise RuntimeError("injected move failure")
        return original(table, **values)
    monkeypatch.setattr(e.store, "insert", fail)
    with pytest.raises(RuntimeError, match="injected"):
        e.families.run_nightly(3)
    assert e.store.scalar("SELECT COUNT(*) FROM migrations") == 0
    assert e.store.scalar("SELECT COUNT(*) FROM accounts WHERE currency_code='CAD'") == 0
    assert {e.store.scalar("SELECT region_id FROM agents WHERE id=?", (p,)) for p in (a, b, child)} == {1}
    monkeypatch.setattr(e.store, "insert", original)
    e.lifecycle.settle_death(3, a)
    e.families.run_nightly(4)
    assert e.store.scalar("SELECT status FROM household_decisions WHERE id=?", (decision,)) == "cancelled"
    assert e.families.partnership(b) is None
    assert e.households.guardian_id(child) == b
    assert e.store.scalar("SELECT COUNT(*) FROM migrations") == 0


@pytest.mark.parametrize("change", ["employment", "credit", "withdrawal"])
def test_joint_move_rechecks_each_member_and_allows_withdrawal(family, monkeypatch, change):
    e, (a, b, _), _ = family
    join(e, a, b)
    opportunity(e, a)
    decision = e.families.propose(2, a, "joint_move", "move", destination_region_id=2)["household_decision_id"]
    e.families.respond(2, b, decision, "accept")
    if change == "employment":
        firm = e.store.scalar("SELECT id FROM firms WHERE region_id=1")
        e.store.insert("employments", agent_id=b, firm_id=firm, wage_cents=5000,
                       start_tick=3, next_pay_tick=30, status="active")
    elif change == "credit":
        original = e.regions._agent_credit_exposure
        monkeypatch.setattr(e.regions, "_agent_credit_exposure", lambda person: "active loan" if person == b else original(person))
    else:
        assert e.families.cancel(3, b, decision)["status"] == "cancelled"
        assert e.families.cancel(3, b, decision)["status"] == "cancelled"
    e.families.run_nightly(4)
    assert e.store.scalar("SELECT status FROM household_decisions WHERE id=?", (decision,)) == "cancelled"
    assert e.store.scalar("SELECT COUNT(*) FROM migrations") == 0
    assert e.store.scalar("SELECT COUNT(*) FROM agents WHERE region_id=2") == 0


def test_scripted_companion_keeps_job_and_does_not_issue_an_individual_move():
    pending = {"kind": "joint_move", "household_decision_id": 4, "own_assent": None,
               "status": "pending", "own_employment_ending": [{"id": 1, "wage_cents": 5000}]}
    context = {"household_decisions": {"scripted_matching": True, "pending": [pending]}}
    assert citizen_decision(context)["actions"] == [
        {"type": "respond_household", "household_decision_id": 4, "decision": "reject"}]
    pending["own_employment_ending"] = []
    assert citizen_decision(context)["actions"][0]["decision"] == "accept"
    context["my_firm"] = {"firm_id": 1}
    assert founder_decision(context)["actions"][0]["decision"] == "accept"


def test_schema_22_upgrade_preserves_legacy_state_and_is_atomic(tmp_path, monkeypatch):
    path = tmp_path / "schema21.db"
    migrations = registry._MIGRATIONS
    monkeypatch.setattr(registry, "_MIGRATIONS", tuple(m for m in migrations if m.version < 22))
    store = Store(str(path))
    store.init_run_meta("old", 1, {"engine_semantics_version": 16})
    store.execute("UPDATE run_meta SET schema_version=21")
    store.insert("agents", name="Existing person", kind="citizen", age=42)
    store.close()
    migration = next(m for m in migrations if m.version == 22)
    bad = registry.Migration.create(22, migration.name, migration.sql + "\nINVALID SQL;", verify=migration.verify)
    monkeypatch.setattr(registry, "_MIGRATIONS", tuple(bad if m.version == 22 else m for m in migrations))
    with pytest.raises(registry.MigrationError):
        Store(str(path))
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='household_decisions'").fetchone() is None
        assert conn.execute("SELECT schema_version FROM run_meta").fetchone()[0] == 21
    monkeypatch.setattr(registry, "_MIGRATIONS", migrations)
    store = Store(str(path))
    try:
        assert store.scalar("SELECT COUNT(*) FROM agents") == 1
        assert store.scalar("SELECT COUNT(*) FROM household_decisions") == 0
        assert store.scalar("SELECT schema_version FROM run_meta") == 22
    finally:
        store.close()


def test_strict_commands_minor_and_kinship_rejection(family):
    e, (a, b, _), _ = family
    executor = ActionExecutor(e)
    for partner in (True, 1.5, str(b), None):
        assert not executor.execute_action(1, a, {"type": "propose_partnership", "partner_id": partner, "request_key": "bad"})["ok"]
    child = e.households.birth(1, a)
    assert not executor.execute_action(1, child, {"type": "separate_household", "request_key": "minor"})["ok"]
    e.store.insert("parent_child_relations", parent_agent_id=a, child_agent_id=b, formed_tick=0, provenance="scheduled_birth")
    with pytest.raises(HouseholdError, match="ancestry"):
        propose(e, a, b)
    assert "respond_household" not in citizen_world_action_types(16)
    assert "respond_household" in citizen_world_action_types(17)


def test_household_decisions_are_authoritative_and_cannot_be_hidden_by_old_semantics(family):
    e, (a, b, _), _ = family
    before = canonical_hashes(e.store)
    assert before["contract_id"] == "hash-contract-v4"
    join(e, a, b)
    after = canonical_hashes(e.store)
    assert before["authoritative_sha256"] != after["authoritative_sha256"]
    assert before["tables"]["household_assents"]["sha256"] != after["tables"]["household_assents"]["sha256"]
    with pytest.raises(HashContractError, match="requires hash-contract-v4"):
        canonical_hashes(e.store, load_hash_contract("research/hash-contract-v3.json"))
    e.store.execute("UPDATE run_meta SET config_json=?", (json.dumps({"engine_semantics_version": 16}),))
    with pytest.raises(HashContractError, match="populated household decisions"):
        canonical_hashes(e.store)


def test_family_export_selects_v4_and_includes_agreements(family, tmp_path):
    e, (a, b, _), _ = family
    join(e, a, b)
    manifest = validate_bundle(export_bundle(e.store, tmp_path / "exports"))
    assert manifest["tables"]["household_decisions"]["row_count"] == 1
    assert manifest["tables"]["household_assents"]["row_count"] == 2
    assert manifest["tables"]["partnerships"]["row_count"] == 1


@pytest.mark.parametrize("semantics", [1, 2, 7, 16])
def test_earlier_semantics_keep_unknown_action_result(store, semantics):
    economy = Economy(store, {"engine_semantics_version": semantics}, random.Random(1), random.Random(2))
    result = ActionExecutor(economy).execute_action(1, 999, {"type": "separate_household", "request_key": "old"})
    prefix = "invalid separate_household command: " if semantics >= 8 else ""
    assert result == {"ok": False, "reason": prefix + "unknown action type: separate_household"}


def _world(path, config, *, replay=False):
    store = Store(str(path))
    store.init_run_meta(path.stem, config["seed"], config)
    world = World(store, config, replay=replay)
    world.initialize()
    return world


def test_real_scripted_household_decisions_resume_and_replay(tmp_path, caplog):
    config = load_config("runs/household-decisions-rehearsal.yaml")
    config["checkpoint_dir"] = str(tmp_path / "checkpoints")
    path = tmp_path / "source.db"
    source = _world(path, config)
    try:
        for _ in range(3):
            asyncio.run(source.step())
        assert source.store.scalar("SELECT COUNT(*) FROM partnerships") > 0
        assert source.store.scalar("SELECT COUNT(*) FROM household_assents WHERE decision='accept'") >= 2
    finally:
        source.close()
    source = _world(path, config)
    try:
        asyncio.run(source.step())
        assert source.store.tick == 4
    finally:
        source.close()
    replay_config = copy.deepcopy(config)
    replay_config["replay_source_path"] = str(path)
    replay = _world(tmp_path / "replay.db", replay_config, replay=True)
    try:
        for _ in range(4):
            asyncio.run(replay.step())
        proof = verify_replay(path, replay.store.path)
        assert proof["exact"], proof["differences"]
        assert replay.economy.ledger.reconcile()[0]
        assert not any("action.execution.failed" in record.message for record in caplog.records)
    finally:
        replay.close()


def test_model_and_external_catalog_receive_private_household_actions(tmp_path):
    config = load_config("runs/household-decisions-rehearsal.yaml")
    config["checkpoint_dir"] = str(tmp_path / "checkpoints")
    world = _world(tmp_path / "catalog.db", config)
    try:
        actor = world.store.query_one("SELECT * FROM agents WHERE kind='citizen' ORDER BY id LIMIT 1")
        context = world.runtime.ctx.build(actor, 1)
        system, prompt = world.runtime.ctx.render_prompt(context)
        assert "PRIVATE HOUSEHOLD DECISIONS" in prompt and "respond_household" in system
        catalog = ParticipantService(world.store, world.runtime.ctx, config).action_catalog(actor["id"])
        assert any(item["type"] == "separate_household" for item in catalog)
        assert any(item["type"] == "propose_partnership" for item in catalog)
    finally:
        world.close()


def test_schema_21_source_replays_without_upgrading_the_recording(tmp_path, monkeypatch):
    config = load_config("runs/price-lab-keyed.yaml")
    config.update(checkpoint_every=0, checkpoint_dir=str(tmp_path / "checkpoints"))
    config["budget"]["conversation_pairs"] = 0
    migrations = registry._MIGRATIONS
    monkeypatch.setattr(registry, "_MIGRATIONS", tuple(m for m in migrations if m.version < 22))
    path = tmp_path / "older-source.db"
    source = _world(path, config)
    try:
        source.store.execute("UPDATE run_meta SET schema_version=21")
        asyncio.run(source.step())
    finally:
        source.close()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(registry, "_MIGRATIONS", migrations)
    replay_config = copy.deepcopy(config)
    replay_config["replay_source_path"] = str(path)
    replay = _world(tmp_path / "new-replay.db", replay_config, replay=True)
    try:
        asyncio.run(replay.step())
        proof = verify_replay(path, replay.store.path)
        assert proof["exact"], proof["differences"]
        # The compatibility rule must never erase a populated new table.
        replay.store.insert("household_decisions", actor_id=11, request_key="tampered",
                            kind="separation", created_tick=1, expires_tick=2,
                            snapshot_json="{}", status="pending")
        assert "household_decisions" in verify_replay(path, replay.store.path)["differences"]
    finally:
        replay.close()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
