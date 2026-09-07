"""Additive records for semantics 15 people, households and child needs."""
from __future__ import annotations

NAME = "persistent_households"

SQL = r"""
CREATE TABLE person_lifecycle (
    agent_id INTEGER PRIMARY KEY REFERENCES agents(id),
    origin TEXT NOT NULL CHECK(origin IN ('genesis','birth','arrival','engine_created')),
    origin_tick INTEGER NOT NULL CHECK(origin_tick >= 0),
    birth_tick INTEGER NOT NULL CHECK(birth_tick <= origin_tick),
    birth_key TEXT UNIQUE,
    life_stage TEXT NOT NULL CHECK(life_stage IN ('child','school_age','adult','retired','dead')),
    death_tick INTEGER CHECK(death_tick >= origin_tick),
    legacy_dependents INTEGER NOT NULL CHECK(legacy_dependents >= 0),
    CHECK((origin='birth' AND birth_key IS NOT NULL AND birth_tick=origin_tick)
       OR (origin<>'birth' AND birth_key IS NULL))
);
CREATE TRIGGER person_lifecycle_origin_immutable
BEFORE UPDATE OF agent_id,origin,origin_tick,birth_tick,birth_key,legacy_dependents
ON person_lifecycle BEGIN
    SELECT RAISE(ABORT, 'person origin is immutable');
END;
CREATE TRIGGER person_lifecycle_no_delete BEFORE DELETE ON person_lifecycle BEGIN
    SELECT RAISE(ABORT, 'person identity is permanent');
END;

CREATE TABLE households (
    id INTEGER PRIMARY KEY,
    region_id INTEGER REFERENCES regions(id),
    formed_tick INTEGER NOT NULL CHECK(formed_tick >= 0),
    dissolved_tick INTEGER CHECK(dissolved_tick >= formed_tick),
    policy TEXT NOT NULL CHECK(policy='guardian_basic_needs_v1')
);
CREATE TABLE household_memberships (
    id INTEGER PRIMARY KEY,
    household_id INTEGER NOT NULL REFERENCES households(id),
    agent_id INTEGER NOT NULL REFERENCES person_lifecycle(agent_id),
    role TEXT NOT NULL CHECK(role IN ('adult','dependent')),
    joined_tick INTEGER NOT NULL CHECK(joined_tick >= 0),
    left_tick INTEGER CHECK(left_tick >= joined_tick),
    end_reason TEXT,
    CHECK((left_tick IS NULL)=(end_reason IS NULL))
);
CREATE UNIQUE INDEX ix_household_primary_member
    ON household_memberships(agent_id) WHERE left_tick IS NULL;
CREATE INDEX ix_household_members ON household_memberships(household_id, left_tick, agent_id);

CREATE TABLE parent_child_relations (
    id INTEGER PRIMARY KEY,
    parent_agent_id INTEGER NOT NULL REFERENCES person_lifecycle(agent_id),
    child_agent_id INTEGER NOT NULL REFERENCES person_lifecycle(agent_id),
    formed_tick INTEGER NOT NULL CHECK(formed_tick >= 0),
    provenance TEXT NOT NULL CHECK(provenance IN ('birth_hazard','scheduled_birth')),
    CHECK(parent_agent_id<>child_agent_id),
    UNIQUE(parent_agent_id,child_agent_id)
);
CREATE TABLE guardianships (
    id INTEGER PRIMARY KEY,
    child_agent_id INTEGER NOT NULL REFERENCES person_lifecycle(agent_id),
    guardian_agent_id INTEGER NOT NULL REFERENCES person_lifecycle(agent_id),
    started_tick INTEGER NOT NULL CHECK(started_tick >= 0),
    ended_tick INTEGER CHECK(ended_tick >= started_tick),
    reason TEXT NOT NULL,
    end_reason TEXT,
    CHECK(child_agent_id<>guardian_agent_id),
    CHECK((ended_tick IS NULL)=(end_reason IS NULL))
);
CREATE UNIQUE INDEX ix_active_primary_guardian
    ON guardianships(child_agent_id) WHERE ended_tick IS NULL;
CREATE INDEX ix_guardian_dependents ON guardianships(guardian_agent_id,ended_tick);

CREATE TABLE child_needs (
    id INTEGER PRIMARY KEY,
    tick INTEGER NOT NULL CHECK(tick > 0),
    child_agent_id INTEGER NOT NULL REFERENCES person_lifecycle(agent_id),
    household_id INTEGER NOT NULL REFERENCES households(id),
    guardian_agent_id INTEGER REFERENCES person_lifecycle(agent_id),
    currency_code TEXT,
    goods_sector TEXT NOT NULL,
    required_units INTEGER NOT NULL CHECK(required_units >= 0),
    purchased_units INTEGER NOT NULL CHECK(purchased_units BETWEEN 0 AND required_units),
    spent_cents INTEGER NOT NULL CHECK(spent_cents >= 0),
    care_required_minutes INTEGER NOT NULL CHECK(care_required_minutes BETWEEN 0 AND 1440),
    care_status TEXT NOT NULL CHECK(care_status IN ('unassigned','time_allocation_pending','not_required')),
    purchases_json TEXT NOT NULL,
    UNIQUE(tick,child_agent_id)
);
CREATE TABLE population_census (
    tick INTEGER PRIMARY KEY CHECK(tick >= 0),
    opening_population INTEGER NOT NULL CHECK(opening_population >= 0),
    births INTEGER NOT NULL CHECK(births >= 0),
    arrivals INTEGER NOT NULL CHECK(arrivals >= 0),
    other_entries INTEGER NOT NULL CHECK(other_entries >= 0),
    deaths INTEGER NOT NULL CHECK(deaths >= 0),
    closing_population INTEGER NOT NULL CHECK(closing_population >= 0),
    active_households INTEGER NOT NULL CHECK(active_households >= 0),
    unassigned_minors INTEGER NOT NULL CHECK(unassigned_minors >= 0),
    legacy_dependents INTEGER NOT NULL CHECK(legacy_dependents >= 0),
    CHECK(closing_population=opening_population+births+arrivals+other_entries-deaths)
);
"""


def verify(conn) -> None:
    tables = {str(row[0]) for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    required = {"person_lifecycle", "households", "household_memberships",
                "parent_child_relations", "guardianships", "child_needs", "population_census"}
    if not required <= tables:
        raise RuntimeError("persistent household tables are missing")
    required_objects = {"ix_household_primary_member", "ix_active_primary_guardian",
                        "person_lifecycle_origin_immutable", "person_lifecycle_no_delete"}
    objects = {str(row[0]) for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('index','trigger')")}
    if not required_objects <= objects:
        raise RuntimeError("persistent household identity guards are missing")
