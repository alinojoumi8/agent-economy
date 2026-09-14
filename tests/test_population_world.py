"""Whole-World checks for the unregistered population semantics draft.

Only a disposable fixture admits version 21 and installs its draft SQL. Public
schema/version admission stays unchanged until the full integration is ready.
"""
import asyncio
from contextlib import closing
import hashlib
from pathlib import Path

import pytest

import engine.semantics as semantics
from engine.city import CityError
from engine.migrations.v026_population_residence import SQL
from engine.population_history import ResidenceError
from engine.store import Store, open_read_only_connection
from world.loop import World
from world.replay_verify import verify_replay_connections

from .test_population_authority import finance
from .test_population_residence_history import contents
from .test_semantics20_civic_succession import apply, civic_config


@pytest.fixture
def draft_world_factory(monkeypatch, tmp_path):
    monkeypatch.setattr(semantics, "CURRENT_ENGINE_SEMANTICS_VERSION", 21)
    worlds = []

    def create(name="world", *, replay_source=None):
        config = civic_config()
        config["engine_semantics_version"] = 21
        if replay_source is not None:
            config.update(replay_source_path=str(replay_source), replay_source_closed=True)
        path = tmp_path/f"{name}.db"
        fresh = not path.exists()
        store = Store(str(path), create=fresh)
        if fresh:
            store.conn.executescript(SQL)
            store.init_run_meta(name, config["seed"], config)
        try:
            world = World(store, config, replay=replay_source is not None)
        except BaseException:
            store.close()
            raise
        worlds.append(world)
        world.initialize()
        world.restore_prng_state()
        return world

    def close(world):
        worlds.remove(world)
        world.close()

    create.close = close
    yield create
    for world in worlds:
        world.close()


def test_fresh_draft_world_registers_every_person_before_local_services(draft_world_factory):
    world = draft_world_factory()
    e = world.economy
    living = [row["id"] for row in world.store.query("SELECT id FROM agents WHERE alive=1 ORDER BY id")]
    assert living and all(e.population.is_local(person, 0) for person in living)
    assert world.store.scalar("SELECT COUNT(*) FROM person_residence_events") == len(living)
    assert world.store.scalar("SELECT COUNT(*) FROM population_resident_census WHERE tick=0") == 1
    assert e.ledger.reconcile()[0]
    asyncio.run(world.step())
    assert world.store.tick == 1
    assert world.store.scalar("SELECT COUNT(*) FROM population_resident_census WHERE tick=1") == 1
    assert e.ledger.reconcile()[0]


def ordinary_mover(world):
    # Avoid a synthetic genesis birthday during this six-day boundary fixture.
    # Biological hazards and the real World phases retain their configured rules.
    return world.store.query_one(
        "SELECT a.id,a.region_id FROM agents a JOIN person_lifecycle p ON p.agent_id=a.id "
        "WHERE a.alive=1 AND a.kind='citizen' AND a.role IS NULL AND a.retired=0 "
        "AND a.employer_id IS NOT NULL "
        "AND a.age>=18 AND CAST(-p.birth_tick/365 AS INTEGER)=CAST((10-p.birth_tick)/365 AS INTEGER) "
        "ORDER BY a.id LIMIT 1")


def movement_fixture(world, create, *, reopen=(), name="world", replay_source=None):
    person = ordinary_mover(world)
    assert person is not None
    actor, region = int(person["id"]), int(person["region_id"])
    accounts = [row["id"] for row in world.store.query(
        "SELECT id FROM accounts WHERE owner_type='agent' AND owner_id=? "
        "AND kind IN ('checking','savings') ORDER BY id", (actor,))]
    original_leases = [dict(row) for row in world.store.query(
        "SELECT * FROM occupancy_leases WHERE agent_id=? AND status='active' ORDER BY id", (actor,))]
    departure = world.economy.population.propose(0, actor, "departure", [actor],
        "world-fixture-departure", due_tick=2, phase="GENESIS")["movement_id"]
    for day in range(1, 7):
        if day == 4:
            # These are explicit, identical harness inputs, not a public scenario
            # loader or a claim that the agents chose to migrate endogenously.
            world.economy.population.propose(3, actor, "return", [actor],
                "world-fixture-return", due_tick=5, destination_region_id=region)
        asyncio.run(world.step())
        e = world.economy
        resident = day < 2 or day >= 5
        assert e.population.is_local(actor, day) is resident
        assert bool(world.store.scalar("SELECT COUNT(*) FROM effective_presence WHERE tick=? AND agent_id=?",
                                      (day, actor))) is resident
        assert bool(world.store.scalar("SELECT COUNT(*) FROM time_days WHERE tick=? AND agent_id=?",
                                      (day, actor))) is resident
        if not resident:
            assert world.store.scalar("SELECT COUNT(*) FROM llm_calls WHERE tick=? AND agent_id=?", (day, actor)) == 0
            assert world.store.scalar("SELECT COUNT(*) FROM occupancy_leases WHERE agent_id=? AND status='active'", (actor,)) == 0
        if day >= 2:
            assert world.store.scalar("SELECT status FROM population_movements WHERE id=?", (departure,)) == "applied"
        e.households.check_invariants(day)
        e.population.commitments.check_invariants()
        assert e.ledger.reconcile()[0]
        if day in reopen:
            create.close(world)
            world = create(name, replay_source=replay_source)
    # Normal work can create an earned-wage receivable. The existing funded
    # wallets must survive the movement without being recreated on return.
    assert [row["id"] for row in world.store.query(
        "SELECT id FROM accounts WHERE owner_type='agent' AND owner_id=? "
        "AND kind IN ('checking','savings') ORDER BY id", (actor,))] == accounts
    for lease in original_leases:
        current = world.store.query_one("SELECT * FROM occupancy_leases WHERE id=?", (lease["id"],))
        assert current["status"] == "cancelled" and current["ended_tick"] == 2
    return world, actor


def test_world_departure_and_return_cross_all_phases_and_daily_restarts(draft_world_factory):
    create = draft_world_factory
    world, actor = movement_fixture(create(), create, reopen=(2, 4))
    assert world.store.tick == 6
    assert world.store.scalar("SELECT COUNT(*) FROM person_residence_events WHERE agent_id=?", (actor,)) == 3
    assert world.store.scalar("SELECT departures FROM population_resident_census WHERE tick=2") == 1
    assert world.store.scalar("SELECT returns FROM population_resident_census WHERE tick=5") == 1


def lease_arguments(row):
    return {key: row[key] for key in ("agent_id", "place_id", "slot", "start_tick", "end_tick",
                                    "priority", "source_type", "source_id", "created_tick")}


def depart_first_day(world):
    person = ordinary_mover(world)
    actor = int(person["id"])
    leases = [dict(row) for row in world.store.query(
        "SELECT * FROM occupancy_leases WHERE agent_id=? AND status='active' ORDER BY id", (actor,))]
    assert leases
    movement = world.economy.population.propose(0, actor, "departure", [actor], "first-day-out",
                                               due_tick=1, phase="GENESIS")["movement_id"]
    asyncio.run(world.step())
    assert not world.economy.population.is_local(actor, 1)
    return actor, int(person["region_id"]), movement, leases


def test_departure_occupancy_failure_rolls_back_the_whole_group_and_retries(
        draft_world_factory, monkeypatch):
    world = draft_world_factory()
    e, actor = world.economy, int(ordinary_mover(world)["id"])
    movement = e.population.propose(0, actor, "departure", [actor], "atomic-occupancy",
                                    due_tick=2, phase="GENESIS")["movement_id"]
    asyncio.run(world.step())
    # Enter the same post-lifecycle boundary used by NIGHT_CLOSE, including
    # birthdays of other residents before household-wide reconciliation.
    e.lifecycle.run_nightly(2)
    before = contents(world.store)
    record = world.store.log_event

    def fail_presence(tick, kind, payload=None, **kwargs):
        if kind == "population_commitment_ended" and payload["kind"] == "local_occupancy":
            raise RuntimeError("injected occupancy receipt failure")
        return record(tick, kind, payload, **kwargs)

    with monkeypatch.context() as injected:
        injected.setattr(world.store, "log_event", fail_presence)
        with pytest.raises(RuntimeError, match="occupancy receipt failure"):
            e.population.settle(2, movement)
    assert contents(world.store) == before
    assert e.population.settle(2, movement)["status"] == "applied"
    ended = world.store.scalar("SELECT COUNT(*) FROM population_commitment_endings "
                               "WHERE movement_id=? AND kind='local_occupancy'", (movement,))
    assert ended == 3
    after = contents(world.store)
    assert e.population.settle(2, movement)["status"] == "applied"
    assert contents(world.store) == after
    assert e.ledger.reconcile()[0]


def test_return_creates_fresh_occupancy_without_restoring_departure_ended_intervals(draft_world_factory):
    world = draft_world_factory()
    actor, region, _, leases = depart_first_day(world)
    e = world.economy
    before = contents(world.store)
    with pytest.raises(CityError, match="living resident"):
        e.city._ensure_lease(**lease_arguments(leases[0]))
    assert contents(world.store) == before
    movement = e.population.propose(1, actor, "return", [actor], "back-home",
                                     due_tick=2, destination_region_id=region)["movement_id"]
    e.lifecycle.run_nightly(2)
    balances = finance(e)
    assert e.population.settle(2, movement)["status"] == "applied"
    assert finance(e) == balances
    before = contents(world.store)
    for lease in leases:
        with pytest.raises(CityError, match="new interval"):
            e.city._ensure_lease(**lease_arguments(lease))
    assert contents(world.store) == before
    e.city._sync_routine_leases(2)
    e.city.establish_effective_presence(2)
    fresh = world.store.query("SELECT id,start_tick FROM occupancy_leases WHERE agent_id=? AND status='active'", (actor,))
    assert fresh and all(row["id"] not in {lease["id"] for lease in leases} and row["start_tick"] == 2 for row in fresh)
    e.population.commitments.check_invariants()


@pytest.mark.parametrize("damage", [{"status": "active", "ended_tick": None}, {"priority": 9999}])
def test_changed_departure_occupancy_is_rejected_without_repair(draft_world_factory, damage):
    world = draft_world_factory()
    _, _, _, leases = depart_first_day(world)
    world.store.update("occupancy_leases", leases[0]["id"], **damage)
    before = contents(world.store)
    with pytest.raises(ResidenceError, match="changed or reactivated"):
        world.economy.population.commitments.check_invariants()
    assert contents(world.store) == before


@pytest.mark.parametrize("surface", ["routine", "presence"])
def test_city_checks_residence_before_replacing_existing_state(draft_world_factory, monkeypatch, surface):
    world = draft_world_factory()
    e, actor = world.economy, int(ordinary_mover(world)["id"])
    method = "is_available" if surface == "routine" else "is_local"
    original, seen = getattr(e.population, method), []

    def missing(person, *args, **kwargs):
        seen.append(person)
        if person == actor:
            raise ResidenceError("injected unavailable residence history")
        return original(person, *args, **kwargs)

    monkeypatch.setattr(e.population, method, missing)
    before = contents(world.store)
    with pytest.raises(ResidenceError, match="unavailable residence"):
        if surface == "routine":
            e.city._sync_routine_leases(0)
        else:
            e.city.establish_effective_presence(0)
    assert len(seen) > 1
    assert contents(world.store) == before


def test_task_assignment_skips_an_outside_clerk_and_uses_a_resident(draft_world_factory):
    world = draft_world_factory()
    e, mover = world.economy, ordinary_mover(world)
    applicant = world.store.scalar(
        "SELECT id FROM agents WHERE alive=1 AND kind='citizen' AND role IS NULL "
        "AND age>=18 AND region_id=? AND id<>? ORDER BY id LIMIT 1", (mover["region_id"], mover["id"]))
    _, case = apply(world, tick=0, applicant=applicant, name="Resident clerk queue")
    e.city.finalize(0)
    actor, _, _, _ = depart_first_day(world)
    task = world.store.query_one("SELECT * FROM institution_tasks WHERE source_case_id=?", (case,))
    assert task is not None
    staff = dict(world.store.query_one("SELECT * FROM agency_staff WHERE active=1 AND agency_id=?", (task["agency_id"],)))
    resident = int(staff["agent_id"])
    assert actor < resident
    staff.pop("id")
    staff["agent_id"] = actor
    world.store.insert("agency_staff", **staff)
    world.store.update("agents", actor, role="permit_clerk")
    world.store.update("institution_tasks", task["id"], status="pending", assigned_agent_id=None,
                       assigned_tick=None, assigned_event_id=None)
    balances = finance(e)
    e.city._assign_tasks(1)
    assigned = world.store.query_one("SELECT assigned_agent_id,status FROM institution_tasks WHERE id=?", (task["id"],))
    assert tuple(assigned) == (resident, "assigned")
    assert finance(e) == balances


def test_world_recorded_decisions_replay_the_same_declared_movement_inputs(draft_world_factory):
    create = draft_world_factory
    source, actor = movement_fixture(create("source"), create, name="source", reopen=(2, 4))
    population_tables = [str(row[0]) for row in source.store.query(
        "SELECT name FROM sqlite_master WHERE type='table' AND "
        "(name LIKE 'population_%' OR name='person_residence_events') ORDER BY name")]
    expected = {name: [tuple(row) for row in source.store.query(f'SELECT * FROM "{name}" ORDER BY rowid')]
                for name in population_tables}
    path = Path(source.store.path)
    create.close(source)
    original = (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
    replay, replay_actor = movement_fixture(create("replay", replay_source=path), create,
        name="replay", replay_source=path)
    assert replay_actor == actor
    assert not any(Path(str(path)+suffix).exists() for suffix in ("-wal", "-shm", "-journal"))
    with closing(open_read_only_connection(str(path), require_closed=True)) as source_connection:
        with closing(open_read_only_connection(replay.store.path)) as replay_connection:
            proof = verify_replay_connections(source_connection, replay_connection)
    assert proof["exact"], proof["differences"]
    actual = {name: [tuple(row) for row in replay.store.query(f'SELECT * FROM "{name}" ORDER BY rowid')]
              for name in population_tables}
    assert actual == expected
    assert (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns) == original
    assert not any(Path(str(path)+suffix).exists() for suffix in ("-wal", "-shm", "-journal"))
