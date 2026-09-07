"""Canonical child identity, constrained needs, demographic accounting and replay."""
from __future__ import annotations

import asyncio
import copy
import json
import random
import sqlite3

import pytest

from agents.scheduler import Scheduler
from engine.actions import ActionExecutor
from engine.core import Economy
from engine.households import HouseholdError
from engine.keyed_random import demographic_draw
from engine.migrations import registry
from engine.store import Store
from run_config import load_config
from research.export_bundle import export_bundle, validate_bundle
from research.hashing import HashContractError, canonical_hashes, load_hash_contract
from world.loop import World
from world.replay_verify import verify_replay

from .conftest import make_agent, make_bank


@pytest.fixture
def family(store):
    config = {"engine_semantics_version": 15, "seed": 42,
              "lifecycle": {"birth_annual_prob": 0, "population_mode": "drift"}}
    e = Economy(store, config, random.Random(1), random.Random(2))
    e.ensure_system_accounts()
    bank = make_bank(e)
    parent, account = make_agent(e, bank, "Parent", age=30, cash=10_000, dependents=2)
    e.households.initialize()
    return e, parent, account, bank


def test_birth_is_atomic_permanent_and_does_not_mint_or_reify_dependents(family, monkeypatch):
    e, parent, account, _ = family
    counts = {table: e.store.scalar(f"SELECT COUNT(*) FROM {table}") for table in
              ("agents", "accounts", "transactions", "person_lifecycle", "household_memberships", "events")}
    real_insert = e.store.insert

    def fail_membership(table, **values):
        if table == "guardianships":
            raise RuntimeError("injected birth failure")
        return real_insert(table, **values)

    monkeypatch.setattr(e.store, "insert", fail_membership)
    with pytest.raises(RuntimeError, match="injected birth"):
        e.households.birth(1, parent)
    for table, count in counts.items():
        assert e.store.scalar(f"SELECT COUNT(*) FROM {table}") == count
    monkeypatch.setattr(e.store, "insert", real_insert)
    child = e.households.birth(1, parent)
    assert e.households.birth(1, parent) == child
    assert e.store.scalar("SELECT COUNT(*) FROM events WHERE kind='birth'") == 1
    assert e.store.scalar("SELECT dependents FROM agents WHERE id=?", (parent,)) == 2
    assert e.ledger.balance(account) == 10_000
    assert e.store.scalar("SELECT SUM(balance_cents) FROM accounts WHERE owner_type='agent' AND owner_id=?", (child,)) == 0
    assert e.store.scalar("SELECT COUNT(*) FROM transactions") == counts["transactions"]
    assert e.households.membership(child)["household_id"] == e.households.membership(parent)["household_id"]
    assert e.households.guardian_id(child) == parent
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        e.store.execute("UPDATE person_lifecycle SET birth_tick=0 WHERE agent_id=?", (child,))
    with pytest.raises(sqlite3.IntegrityError, match="permanent"):
        e.store.execute("DELETE FROM person_lifecycle WHERE agent_id=?", (child,))
    assert e.ledger.reconcile()[0]


def test_primary_membership_guard_and_unrecorded_origin_rejection(family):
    e, parent, _, bank = family
    member = e.households.membership(parent)
    with pytest.raises(sqlite3.IntegrityError):
        e.store.insert("household_memberships", household_id=member["household_id"],
                       agent_id=parent, role="adult", joined_tick=0)
    stranger, _ = make_agent(e, bank, "Unrecorded")
    with pytest.raises(HouseholdError, match="historical"):
        e.households.register_person(2, stranger, "arrival")
    assert e.store.scalar("SELECT COUNT(*) FROM person_lifecycle WHERE agent_id=?", (stranger,)) == 0


def test_birth_cannot_follow_same_tick_parent_death(family, monkeypatch):
    e, parent, _, _ = family
    stale = e.store.query_one("SELECT * FROM agents WHERE id=?", (parent,))
    e.lifecycle.settle_death(1, parent)
    e.lifecycle.p["birth_annual_prob"] = 365
    monkeypatch.setattr(e.lifecycle, "_draw", lambda *args: 0.0)
    e.lifecycle._maybe_birth(1, stale)
    assert e.store.scalar("SELECT COUNT(*) FROM person_lifecycle WHERE origin='birth'") == 0
    with pytest.raises(HouseholdError, match="living adult"):
        e.households.birth(1, parent)


def test_child_clock_majority_retirement_and_no_automatic_assets(family):
    e, parent, _, _ = family
    child = e.households.birth(1, parent)
    def age(tick):
        actor = e.store.query_one("SELECT * FROM agents WHERE id=?", (child,))
        e.lifecycle._age_and_retire(tick, actor)
        return e.store.scalar("SELECT age FROM agents WHERE id=?", (child,))
    assert age(365) == 0
    assert age(366) == 1
    assert age(1 + 18 * 365 - 1) == 17
    assert e.households.guardian_id(child) == parent
    assert age(1 + 18 * 365) == 18
    assert e.households.guardian_id(child) is None
    assert e.households.membership(child)["role"] == "adult"
    assert e.store.scalar("SELECT end_reason FROM household_memberships WHERE agent_id=? AND left_tick IS NOT NULL", (child,)) == "adulthood"
    assert e.store.scalar("SELECT COUNT(*) FROM employments WHERE agent_id=?", (child,)) == 0
    assert e.store.scalar("SELECT balance_cents FROM accounts WHERE owner_id=? AND owner_type='agent'", (child,)) == 0
    assert age(1 + 65 * 365) == 65
    assert e.store.scalar("SELECT retired FROM agents WHERE id=?", (child,)) == 1
    assert e.store.scalar("SELECT life_stage FROM person_lifecycle WHERE agent_id=?", (child,)) == "retired"


def test_child_decisions_and_employment_are_rejected(family):
    e, parent, _, _ = family
    child = e.households.birth(1, parent)
    scheduled = Scheduler(e.store, e.config).scheduled_agents(1)
    assert child not in {int(a["id"]) for a in scheduled}
    firm = e.firms.found_firm(1, parent, "Food", "food", opening_capital_cents=0)
    job = e.labor.post_job(1, firm, "Assistant", 100)
    assert e.labor.apply_job(1, child, job) is None
    result = ActionExecutor(e).execute_action(1, child, {"type": "apply_job", "job_id": job})
    assert not result["ok"] and "minor" in result["reason"]
    assert e.store.scalar("SELECT validation_status FROM action_proposals WHERE actor_id=?", (child,)) == "rejected"


def test_needs_buy_actual_inventory_once_and_report_shortfall(family, monkeypatch):
    e, parent, account, _ = family
    first = e.households.birth(1, parent)
    second = e.households.birth(2, parent)
    firm = e.firms.found_firm(1, parent, "Food", "food",
        product={"product": "food", "unit_price_cents": 125}, opening_capital_cents=0)
    e.store.update("firms", firm, inventory=1)
    before = e.ledger.balance(account)
    insert = e.store.insert
    def fail_need(table, **values):
        if table == "child_needs":
            raise RuntimeError("injected need failure")
        return insert(table, **values)
    monkeypatch.setattr(e.store, "insert", fail_need)
    with pytest.raises(RuntimeError, match="injected need"):
        e.households.provision_children(2)
    assert e.ledger.balance(account) == before
    assert e.store.scalar("SELECT inventory FROM firms WHERE id=?", (firm,)) == 1
    monkeypatch.setattr(e.store, "insert", insert)
    e.households.provision_children(2)
    e.households.provision_children(2)
    needs = e.store.query("SELECT * FROM child_needs ORDER BY child_agent_id")
    assert [r["child_agent_id"] for r in needs] == [first, second]
    assert [r["purchased_units"] for r in needs] == [1, 0]
    assert [r["required_units"] for r in needs] == [1, 1]
    assert [r["care_status"] for r in needs] == ["time_allocation_pending"] * 2
    assert e.ledger.balance(account) == before - 125
    assert e.store.scalar("SELECT inventory FROM firms WHERE id=?", (firm,)) == 0
    assert e.store.scalar("SELECT COUNT(*) FROM events WHERE kind='goods_sale'") == 1
    assert e.ledger.reconcile()[0]


def test_child_food_never_borrows_or_nets_foreign_currency(family):
    e, parent, account, _ = family
    e.households.birth(1, parent)
    local = e.firms.found_firm(1, parent, "Local food", "food",
        product={"product": "food", "unit_price_cents": 125}, opening_capital_cents=0)
    foreign = e.firms.found_firm(1, parent, "Foreign food", "food",
        product={"product": "food", "unit_price_cents": 25}, opening_capital_cents=0)
    e.store.update("firms", local, inventory=10)
    e.store.update("firms", foreign, inventory=10, currency_code="EUR")
    foreign_account = int(e.store.scalar("SELECT account_id FROM firms WHERE id=?", (foreign,)))
    e.store.update("accounts", foreign_account, currency_code="EUR")
    e.ledger.transfer(1, account, e.ledger.system_account("sys:gov"), 9_920, kind="fixture_budget")
    e.households.provision_children(1)
    need = e.store.query_one("SELECT * FROM child_needs")
    assert need["currency_code"] == "USD" and need["purchased_units"] == need["spent_cents"] == 0
    assert e.ledger.balance(account) == 80
    assert e.store.scalar("SELECT SUM(inventory) FROM firms") == 20
    assert e.store.scalar("SELECT COUNT(*) FROM loans") == 0
    assert e.ledger.reconcile()[0]


def test_guardian_death_preserves_child_gap_and_atomic_estate(family, monkeypatch):
    e, parent, account, _ = family
    child = e.households.birth(1, parent)
    real_close = e.households.close_person
    def fail(*args):
        raise RuntimeError("custody failure")
    monkeypatch.setattr(e.households, "close_person", fail)
    with pytest.raises(RuntimeError, match="custody failure"):
        e.lifecycle.settle_death(1, parent)
    assert e.ledger.balance(account) == 10_000
    assert e.store.scalar("SELECT alive FROM agents WHERE id=?", (parent,)) == 1
    monkeypatch.setattr(e.households, "close_person", real_close)
    e.lifecycle.settle_death(1, parent)
    e.lifecycle.settle_death(1, parent)
    assert e.store.scalar("SELECT COUNT(*) FROM events WHERE kind='death'") == 1
    assert e.store.scalar("SELECT alive FROM agents WHERE id=?", (child,)) == 1
    assert e.households.guardian_id(child) is None
    assert e.households.membership(child) is not None
    assert e.store.scalar("SELECT COUNT(*) FROM parent_child_relations") == 1
    e.households.provision_children(1)
    need = e.store.query_one("SELECT * FROM child_needs")
    assert need["care_status"] == "unassigned" and need["purchased_units"] == 0
    e.households.record_census(1)
    census = e.store.query_one("SELECT * FROM population_census WHERE tick=1")
    assert census["opening_population"] == census["closing_population"] == 1
    assert census["births"] == census["deaths"] == census["unassigned_minors"] == 1
    assert e.ledger.reconcile()[0]


def test_keyed_health_draws_survive_extra_births_branches_and_order(family):
    e, parent, _, _ = family
    before = e.lifecycle.prng.getstate()
    target = [e.lifecycle._draw(t, parent, "mortality") for t in range(1, 50)]
    e.households.birth(1, parent)
    for tick in range(49, 0, -1):
        e.lifecycle._draw(tick, 9001, "sick_transition")
        e.lifecycle._draw(tick, parent, "birth")
    assert [e.lifecycle._draw(t, parent, "mortality") for t in range(1, 50)] == target
    assert e.lifecycle.prng.getstate() == before
    assert len({demographic_draw(seed, mechanism, 1, parent)
                for seed in (41, 42) for mechanism in ("birth", "mortality")}) == 4


def test_actual_health_outcomes_are_unchanged_by_an_extra_child(tmp_path):
    paths = [tmp_path / "control.db", tmp_path / "extra-child.db"]
    outcomes = []
    for index, path in enumerate(paths):
        store = Store(str(path))
        config = {"engine_semantics_version": 15, "seed": 123,
                  "lifecycle": {"birth_annual_prob": 0, "population_mode": "drift",
                                "illness_onset_annual_young": 100}}
        store.init_run_meta(path.stem, 123, config)
        e = Economy(store, config, random.Random(1), random.Random(2))
        try:
            e.ensure_system_accounts()
            bank = make_bank(e)
            parent, _ = make_agent(e, bank, "Parent", age=35)
            e.households.initialize()
            if index:
                child = e.households.birth(1, parent)
                store.update("agents", child, health="critical")
            for tick in range(1, 61):
                e.lifecycle.run_nightly(tick)
            outcomes.append([tuple(row) for row in store.query(
                "SELECT tick,kind FROM events WHERE subject_type='agent' AND subject_id=? "
                "AND kind IN ('illness_onset','illness_critical','recovery','death') ORDER BY id", (parent,))])
        finally:
            store.close()
    assert outcomes[0] == outcomes[1]
    assert outcomes[0], "the comparison must actually exercise health transitions"


def test_adult_separation_preserves_assets_and_child_history(family):
    e, parent, account, _ = family
    child = e.households.birth(1, parent)
    previous = int(e.households.membership(parent)["household_id"])
    new = e.households.split_household(1, parent)
    assert new != previous
    assert e.households.split_household(1, parent) == new
    assert e.households.membership(child)["household_id"] == previous
    assert e.households.guardian_id(child) is None
    assert e.ledger.balance(account) == 10_000
    assert e.store.scalar("SELECT end_reason FROM household_memberships WHERE agent_id=? AND left_tick IS NOT NULL", (parent,)) == "adult_separation"
    with pytest.raises(HouseholdError, match="living adult"):
        e.households.split_household(1, child)
    assert e.store.scalar("SELECT COUNT(*) FROM parent_child_relations") == 1


def test_guardian_succession_uses_existing_adult_member_and_transfers_no_assets(family):
    e, parent, _, _ = family
    older_child = e.households.birth(1, parent)
    younger_child = e.households.birth(18 * 365, parent)
    e.households.advance_age(18 * 365 + 1, e.store.query_one("SELECT * FROM agents WHERE id=?", (older_child,)))
    e.lifecycle.settle_death(18 * 365 + 1, parent)
    assert e.households.guardian_id(younger_child) == older_child
    assert e.store.scalar("SELECT COUNT(*) FROM guardianships WHERE child_agent_id=?", (younger_child,)) == 2
    assert e.store.scalar("SELECT balance_cents FROM accounts WHERE owner_type='agent' AND owner_id=?", (older_child,)) == 0


def test_stable_mode_replaces_adult_deaths_only(family):
    e, parent, _, _ = family
    e.lifecycle.p["population_mode"] = "stable"
    child = e.households.birth(1, parent)
    e.lifecycle.settle_death(1, child)
    assert e.store.scalar("SELECT COUNT(*) FROM events WHERE kind='arrival_scheduled'") == 0
    e.lifecycle.settle_death(1, parent)
    payload = json.loads(e.store.scalar("SELECT payload_json FROM events WHERE kind='arrival_scheduled'"))
    assert 6 <= payload["due_tick"] <= 21
    assert e.store.scalar("SELECT COUNT(*) FROM households WHERE dissolved_tick=1") == 1


def test_census_rejects_corrupt_clock_and_rewriting(family):
    e, parent, _, _ = family
    e.lifecycle.run_nightly(1)
    e.households.record_census(1)
    e.households.record_census(1)
    e.households.birth(1, parent)
    with pytest.raises(HouseholdError, match="rewrite"):
        e.households.record_census(1)
    e.store.update("agents", parent, age=9)
    with pytest.raises(HouseholdError, match="reconciliation"):
        e.households.check_invariants(1)


def test_newborn_city_presence_shares_household_without_inventing_a_school(tmp_path):
    config = load_config("runs/civic-rehearsal.yaml")
    config.update(engine_semantics_version=15, checkpoint_every=0)
    config["checkpoint_dir"] = str(tmp_path / "checkpoints")
    config["lifecycle"]["birth_annual_prob"] = 0
    world = _world(tmp_path / "city.db", config)
    try:
        parent = int(world.store.scalar(
            "SELECT id FROM agents WHERE kind='citizen' AND region_id IS NOT NULL AND age>=18 ORDER BY id LIMIT 1"))
        child = world.economy.households.birth(1, parent)
        world.economy.city._sync_routine_leases(1)
        world.economy.city.establish_effective_presence(1)
        home = world.store.scalar("SELECT place_id FROM effective_presence WHERE tick=1 AND agent_id=? AND slot='morning'", (parent,))
        child_places = world.store.query("SELECT place_id,source_type FROM effective_presence WHERE tick=1 AND agent_id=? ORDER BY slot", (child,))
        assert len(child_places) == 3
        assert all(row["place_id"] == home and row["source_type"] == "routine_home" for row in child_places)
        original = int(world.economy.households.membership(child)["household_id"])
        # Model the already-settled individual relocation boundary. The regional
        # engine owns FX/job effects; this assertion concerns membership/custody.
        destination = int(world.store.scalar("SELECT id FROM regions WHERE id<>(SELECT region_id FROM agents WHERE id=?) ORDER BY id LIMIT 1", (parent,)))
        world.store.update("agents", parent, region_id=destination)
        world.economy.households.reconcile_residence(1)
        assert world.economy.households.membership(parent)["household_id"] != original
        assert world.economy.households.membership(child)["household_id"] == original
        assert world.economy.households.guardian_id(child) is None
    finally:
        world.close()


@pytest.mark.parametrize("settings", [
    {"child_goods_units": True}, {"child_goods_units": -1},
    {"care_minutes_per_child": 1441}, {"goods_sector": " "},
    {"scheduled_births": [{"tick": 1.0, "parent_agent_id": 1}]},
    {"scheduled_births": [{"tick": 1, "parent_agent_id": 1}] * 2}, {"unknown": 1},
])
def test_invalid_demographic_settings_fail_closed(store, settings):
    with pytest.raises(HouseholdError):
        Economy(store, {"engine_semantics_version": 15, "households": settings}, random.Random(1), random.Random(2))


def test_schema_21_migration_is_additive_atomic_and_does_not_invent_people(tmp_path, monkeypatch):
    path = tmp_path / "v20.db"
    all_migrations = registry._MIGRATIONS
    monkeypatch.setattr(registry, "_MIGRATIONS", tuple(m for m in all_migrations if m.version < 21))
    s = Store(str(path))
    s.init_run_meta("old", 1, {"engine_semantics_version": 14})
    s.execute("UPDATE run_meta SET schema_version=20")
    s.insert("agents", name="Legacy", kind="citizen", age=40, dependents=3)
    s.close()
    m = next(m for m in all_migrations if m.version == 21)
    bad = registry.Migration.create(21, m.name, m.sql + "\nTHIS IS INVALID SQL;", verify=m.verify)
    monkeypatch.setattr(registry, "_MIGRATIONS", (*all_migrations[:-1], bad))
    with pytest.raises(registry.MigrationError):
        Store(str(path))
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT 1 FROM sqlite_master WHERE name='person_lifecycle'").fetchone() is None
        assert connection.execute("SELECT schema_version FROM run_meta").fetchone()[0] == 20
    monkeypatch.setattr(registry, "_MIGRATIONS", all_migrations)
    s = Store(str(path))
    try:
        assert s.scalar("SELECT dependents FROM agents") == 3
        assert s.scalar("SELECT COUNT(*) FROM person_lifecycle") == 0
        assert s.scalar("SELECT schema_version FROM run_meta") == 21
    finally:
        s.close()


def _world(path, config, *, replay=False):
    s = Store(str(path))
    s.init_run_meta(path.stem, int(config["seed"]), config)
    w = World(s, config, replay=replay)
    w.initialize()
    return w


def test_full_world_birth_needs_resume_and_exact_recorded_replay(tmp_path):
    config = load_config("runs/household-rehearsal.yaml")
    config["checkpoint_dir"] = str(tmp_path / "checkpoints")
    config["budget"]["conversation_pairs"] = 0
    source_path = tmp_path / "source.db"
    source = _world(source_path, config)
    try:
        asyncio.run(source.step())
        child = int(source.store.scalar("SELECT agent_id FROM person_lifecycle WHERE origin='birth'"))
        assert source.store.scalar("SELECT COUNT(*) FROM llm_calls WHERE agent_id=?", (child,)) == 0
        assert source.store.scalar("SELECT age FROM agents WHERE id=?", (child,)) == 0
        assert source.store.scalar("SELECT COUNT(*) FROM child_needs WHERE child_agent_id=?", (child,)) == 1
        assert source.store.query_one("SELECT 1 FROM memories WHERE agent_id=? AND kind='observation' AND text='I was born.'", (child,))
    finally:
        source.close()
    resumed_store = Store(str(source_path))
    resumed = World(resumed_store, config)
    resumed.initialize()
    try:
        asyncio.run(resumed.step())
        assert resumed.store.tick == 2
        assert resumed.store.scalar("SELECT COUNT(*) FROM person_lifecycle WHERE origin='birth'") == 1
        assert resumed.store.scalar("SELECT COUNT(*) FROM population_census") == 3
    finally:
        resumed.close()
    replay_config = copy.deepcopy(config)
    replay_config["replay_source_path"] = str(source_path)
    replay = _world(tmp_path / "replay.db", replay_config, replay=True)
    try:
        asyncio.run(replay.step())
        asyncio.run(replay.step())
        proof = verify_replay(source_path, replay.store.path)
        assert proof["exact"], proof["differences"]
        assert replay.economy.ledger.reconcile()[0]
    finally:
        replay.close()


def test_household_hash_and_default_export_include_new_economic_records(tmp_path):
    config = load_config("runs/household-rehearsal.yaml")
    config["checkpoint_dir"] = str(tmp_path / "checkpoints")
    world = _world(tmp_path / "household-export.db", config)
    try:
        asyncio.run(world.step())
        before = canonical_hashes(world.store)
        assert before["contract_id"] == "hash-contract-v3"
        assert before["schema_inventory_sha256"] == "34a2daceed85dc29c5dc8fd5e51f6da6c1bfcd6d78f82c1e3abbcf3366f2623c"
        for version in (1, 2):
            with pytest.raises(HashContractError, match="requires hash-contract-v3"):
                canonical_hashes(world.store, load_hash_contract(f"research/hash-contract-v{version}.json"))
        bundle = export_bundle(world.store, tmp_path / "exports")
        manifest = validate_bundle(bundle)
        assert manifest["tables"]["person_lifecycle"]["row_count"] == 25
        assert manifest["tables"]["child_needs"]["row_count"] == 1
        assert manifest["tables"]["parent_child_relations"]["row_count"] == 1
        parent = world.store.query_one("SELECT * FROM agents WHERE id=11")
        context = world.runtime.ctx.build(parent, 2)
        assert context["household"]["responsible_child_count"] == 1
        assert context["household"]["child_goods_units_per_day"] == 1
        assert context["household"]["previous_day_spending"][0]["purchased_units"] == 1
        other = world.economy.households.decision_context(12, 2)
        assert other["responsible_children"] == [] and other["previous_day_spending"] == []
        _, user_prompt = world.runtime.ctx.render_prompt(context)
        assert "YOUR MEMBERSHIP AND CHILD SUPPORT" in user_prompt
        before = canonical_hashes(world.store)
        world.store.execute("UPDATE child_needs SET care_required_minutes=care_required_minutes+1")
        after = canonical_hashes(world.store)
        assert after["authoritative_sha256"] != before["authoritative_sha256"]
        assert after["tables"]["child_needs"]["sha256"] != before["tables"]["child_needs"]["sha256"]
        world.store.execute("UPDATE run_meta SET config_json=?", (json.dumps({"engine_semantics_version": 14}),))
        with pytest.raises(HashContractError, match="populated household"):
            canonical_hashes(world.store)
    finally:
        world.close()
