"""Stable-lifecycle acceptance must explain every retained population change."""
import json
import sqlite3

import pytest

from reports.scale_population import stable_population_evidence


EXPECTED = {"agents": 3, "alive": 3, "citizen_kind": 2, "staff_kind": 1,
            "core": 2, "periphery": 1, "regions": {"north": 2, "south": 1}}
CONFIG = {"engine_semantics_version": 7, "lifecycle": {"population_mode": "stable"},
          "living_world": {"career_migration_enabled": False}}


@pytest.fixture
def population():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE regions(id INTEGER PRIMARY KEY,region_key TEXT);
        CREATE TABLE agents(id INTEGER PRIMARY KEY,kind TEXT,alive INTEGER,
            population_tier TEXT,region_id INTEGER,arrived_tick INTEGER,died_tick INTEGER);
        CREATE TABLE events(id INTEGER PRIMARY KEY,tick INTEGER,kind TEXT,
            phase TEXT,subject_type TEXT,subject_id INTEGER,payload_json TEXT);
        INSERT INTO regions VALUES(1,'north'),(2,'south');
        INSERT INTO agents VALUES(1,'staff',1,'core',1,0,NULL),
            (2,'citizen',0,'periphery',1,0,5),(3,'citizen',1,'core',2,0,NULL),
            (4,'citizen',1,'periphery',2,10,NULL);
    """)
    events = [
        (1, 0, "genesis", None, {"agents": 3}),
        (2, 5, "death", 2, {"agent_id": 2}),
        (3, 5, "arrival_scheduled", None, {"due_tick": 10}),
        (4, 10, "arrival", 4, {"agent_id": 4, "schedule_event_id": 3}),
    ]
    for event_id, tick, kind, agent_id, payload in events:
        conn.execute("INSERT INTO events VALUES(?,?,?,'NIGHT_CLOSE',?,?,?)",
                     (event_id, tick, kind, "agent" if agent_id else None,
                      agent_id, json.dumps(payload)))
    yield conn
    conn.close()


def test_retained_dead_rows_and_replacement_region_are_reconciled(population):
    passed, evidence = stable_population_evidence(population, 10, CONFIG, EXPECTED)
    assert passed
    assert evidence["initial"] == EXPECTED
    assert evidence["observed"]["agents"] == 4
    assert evidence["living"]["agents"] == 3
    assert evidence["living"]["regions"] == {"north": 1, "south": 2}
    assert evidence["deaths"] == evidence["arrivals"] == 1
    assert evidence["pending_replacements"] == 0


def test_future_replacement_is_explicit_and_overdue_replacement_fails(population):
    population.execute("DELETE FROM events WHERE kind='arrival'")
    population.execute("DELETE FROM agents WHERE id=4")
    passed, evidence = stable_population_evidence(population, 9, CONFIG, EXPECTED)
    assert passed
    assert evidence["living"]["agents"] == 2
    assert evidence["pending_replacements"] == 1
    assert not stable_population_evidence(population, 10, CONFIG, EXPECTED)[0]


@pytest.mark.parametrize("mutation", [
    "DELETE FROM events WHERE kind='death'",
    "DELETE FROM events WHERE kind='arrival_scheduled'",
    "DELETE FROM events WHERE kind='arrival'",
    "DELETE FROM agents WHERE id=2",
    "UPDATE agents SET arrived_tick=0 WHERE id=4",
    "UPDATE agents SET died_tick=6 WHERE id=2",
    "UPDATE agents SET alive=1 WHERE id=2",
    "UPDATE agents SET region_id=2 WHERE id=1",
    "UPDATE agents SET population_tier='core' WHERE id=4",
    "UPDATE events SET payload_json='{\"agent_id\":true}' WHERE kind='death'",
    "UPDATE events SET subject_id=3 WHERE kind='death'",
    "UPDATE events SET phase='EXECUTION' WHERE kind='arrival'",
    "UPDATE events SET subject_type='agent',subject_id=2 WHERE kind='arrival_scheduled'",
    "UPDATE events SET payload_json='{\"due_tick\":6}' WHERE kind='arrival_scheduled'",
    "UPDATE events SET payload_json='{\"agent_id\":4,\"schedule_event_id\":99}' WHERE kind='arrival'",
    "INSERT INTO events SELECT 5,tick,kind,phase,subject_type,subject_id,payload_json FROM events WHERE kind='arrival'",
    "INSERT INTO agents VALUES(5,'citizen',1,'periphery',1,10,NULL)",
])
def test_population_tampering_fails_closed(population, mutation):
    population.execute(mutation)
    passed, evidence = stable_population_evidence(population, 10, CONFIG, EXPECTED)
    assert not passed
    assert evidence["error"]


def test_tier_history_must_explain_current_and_initial_cohorts(population):
    population.execute("UPDATE agents SET population_tier='periphery' WHERE id=3")
    population.execute("UPDATE agents SET population_tier='core' WHERE id=4")
    for event_id, agent, old, new in [(5, 3, "core", "periphery"), (6, 4, "periphery", "core")]:
        population.execute("INSERT INTO events VALUES(?,10,'agent_tier_changed','NIGHT_CLOSE','agent',?,?)",
                           (event_id, agent, json.dumps({"agent_id": agent, "old_tier": old, "new_tier": new})))
    assert stable_population_evidence(population, 10, CONFIG, EXPECTED)[0]
    population.execute("DELETE FROM events WHERE id=5")
    assert not stable_population_evidence(population, 10, CONFIG, EXPECTED)[0]


def test_unrecognized_demographic_policy_is_not_accepted(population):
    assert not stable_population_evidence(population, 10, {**CONFIG, "engine_semantics_version": 21}, EXPECTED)[0]


@pytest.mark.parametrize("override", [
    {"lifecycle": None}, {"lifecycle": []}, {"living_world": None},
    {"lifecycle": {"population_mode": "drift"}},
    {"living_world": {"career_migration_enabled": True}},
    {"lifecycle": {"population_mode": "stable", "arrival_delay_min": True}},
])
def test_malformed_or_changed_population_policy_fails_closed(population, override):
    assert not stable_population_evidence(population, 10, {**CONFIG, **override}, EXPECTED)[0]
