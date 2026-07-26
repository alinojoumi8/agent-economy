"""Semantics 12 civic places, service workflow, and attention contexts."""
from __future__ import annotations


NAME = "civic_city"

SQL = r"""
CREATE TABLE places (
    id              INTEGER PRIMARY KEY,
    place_key       TEXT NOT NULL UNIQUE CHECK(length(place_key) BETWEEN 3 AND 160),
    region_id       INTEGER REFERENCES regions(id),
    name            TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 160),
    kind            TEXT NOT NULL CHECK(kind IN
                       ('residential_district','public_commons','firm_workplace',
                        'licensing_office')),
    owner_type      TEXT NOT NULL CHECK(owner_type IN
                       ('region','firm','agency','government')),
    owner_id        INTEGER,
    x               REAL NOT NULL CHECK(x >= 0.0 AND x <= 1.0),
    y               REAL NOT NULL CHECK(y >= 0.0 AND y <= 1.0),
    capacity        INTEGER CHECK(capacity IS NULL OR capacity > 0),
    active          INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
    created_tick    INTEGER NOT NULL DEFAULT 0 CHECK(created_tick >= 0),
    closed_tick     INTEGER CHECK(closed_tick IS NULL OR closed_tick >= created_tick),
    metadata_json   TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX ix_places_region_kind
    ON places(region_id, kind, active, id);
CREATE INDEX ix_places_owner
    ON places(owner_type, owner_id, active, id);

CREATE TABLE occupancy_leases (
    id              INTEGER PRIMARY KEY,
    dedupe_key      TEXT NOT NULL UNIQUE CHECK(length(dedupe_key)=64),
    agent_id        INTEGER NOT NULL REFERENCES agents(id),
    place_id        INTEGER NOT NULL REFERENCES places(id),
    slot            TEXT NOT NULL CHECK(slot IN ('morning','business','evening')),
    start_tick      INTEGER NOT NULL CHECK(start_tick >= 0),
    end_tick        INTEGER NOT NULL CHECK(end_tick >= start_tick),
    priority        INTEGER NOT NULL DEFAULT 0,
    source_type     TEXT NOT NULL CHECK(source_type IN
                       ('routine_home','routine_work','appointment',
                        'agency_assignment','public_commons')),
    source_id       INTEGER,
    status          TEXT NOT NULL DEFAULT 'active' CHECK(status IN
                       ('active','expired','cancelled')),
    created_tick    INTEGER NOT NULL CHECK(created_tick >= 0),
    ended_tick      INTEGER,
    CHECK(ended_tick IS NULL OR ended_tick >= created_tick)
);
CREATE INDEX ix_occupancy_effective_agent
    ON occupancy_leases(agent_id, slot, status, start_tick, end_tick, priority DESC, id);
CREATE INDEX ix_occupancy_effective_place
    ON occupancy_leases(place_id, slot, status, start_tick, end_tick, agent_id);
CREATE INDEX ix_occupancy_source
    ON occupancy_leases(source_type, source_id, status, id);

CREATE TABLE effective_presence (
    id              INTEGER PRIMARY KEY,
    tick            INTEGER NOT NULL CHECK(tick >= 0),
    slot            TEXT NOT NULL CHECK(slot IN ('morning','business','evening')),
    agent_id        INTEGER NOT NULL REFERENCES agents(id),
    place_id        INTEGER NOT NULL REFERENCES places(id),
    lease_id        INTEGER NOT NULL REFERENCES occupancy_leases(id),
    priority        INTEGER NOT NULL,
    source_type     TEXT NOT NULL,
    UNIQUE(tick, slot, agent_id)
);
CREATE INDEX ix_effective_presence_place
    ON effective_presence(tick, slot, place_id, agent_id);
CREATE INDEX ix_effective_presence_agent
    ON effective_presence(agent_id, tick, slot);

CREATE TABLE agency_staff (
    id              INTEGER PRIMARY KEY,
    agency_id       INTEGER NOT NULL REFERENCES agencies(id),
    agent_id        INTEGER NOT NULL REFERENCES agents(id),
    place_id        INTEGER NOT NULL REFERENCES places(id),
    region_id       INTEGER REFERENCES regions(id),
    role_key        TEXT NOT NULL CHECK(role_key IN ('permit_clerk')),
    effective_tick  INTEGER NOT NULL CHECK(effective_tick >= 0),
    ended_tick      INTEGER,
    active          INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
    created_tick    INTEGER NOT NULL CHECK(created_tick >= 0),
    CHECK(ended_tick IS NULL OR ended_tick >= effective_tick)
);
CREATE UNIQUE INDEX ux_agency_staff_active_agent
    ON agency_staff(agent_id, role_key) WHERE active=1;
CREATE INDEX ix_agency_staff_assignment
    ON agency_staff(agency_id, role_key, active, agent_id);
CREATE INDEX ix_agency_staff_region
    ON agency_staff(region_id, role_key, active, agent_id);

CREATE TABLE service_cases (
    id                       INTEGER PRIMARY KEY,
    case_type                TEXT NOT NULL CHECK(case_type IN ('business_permit')),
    agency_id                INTEGER NOT NULL REFERENCES agencies(id),
    applicant_agent_id       INTEGER NOT NULL REFERENCES agents(id),
    region_id                INTEGER REFERENCES regions(id),
    priority                 INTEGER NOT NULL DEFAULT 0,
    status                   TEXT NOT NULL CHECK(status IN
                              ('applied','appointment_scheduled','submitted',
                               'under_review','approved','denied','abandoned',
                               'withdrawn')),
    created_tick             INTEGER NOT NULL CHECK(created_tick >= 0),
    submitted_tick           INTEGER,
    decided_tick             INTEGER,
    updated_tick             INTEGER NOT NULL CHECK(updated_tick >= created_tick),
    no_show_count            INTEGER NOT NULL DEFAULT 0 CHECK(no_show_count >= 0),
    business_name            TEXT NOT NULL CHECK(length(business_name) BETWEEN 1 AND 60),
    sector                   TEXT NOT NULL CHECK(length(sector) BETWEEN 1 AND 40),
    lawyer_agent_id          INTEGER NOT NULL REFERENCES agents(id),
    opening_capital_cents    INTEGER NOT NULL CHECK(opening_capital_cents >= 0),
    business_idea_json       TEXT NOT NULL,
    application_payload_json TEXT NOT NULL,
    application_payload_hash TEXT NOT NULL CHECK(length(application_payload_hash)=64),
    fee_cents                INTEGER NOT NULL CHECK(fee_cents >= 0),
    fee_transaction_id       INTEGER REFERENCES transactions(id),
    decision                 TEXT CHECK(decision IS NULL OR decision IN ('approve','deny')),
    reason_code              TEXT,
    created_event_id         INTEGER REFERENCES events(id),
    outcome_event_id         INTEGER REFERENCES events(id),
    CHECK(submitted_tick IS NULL OR submitted_tick >= created_tick),
    CHECK(decided_tick IS NULL OR decided_tick >= created_tick)
);
CREATE INDEX ix_service_cases_queue
    ON service_cases(agency_id, status, priority DESC, created_tick, id);
CREATE INDEX ix_service_cases_applicant
    ON service_cases(applicant_agent_id, created_tick DESC, id DESC);
CREATE INDEX ix_service_cases_name
    ON service_cases(business_name COLLATE NOCASE, status, created_tick, id);
CREATE UNIQUE INDEX ux_service_cases_active_applicant
    ON service_cases(applicant_agent_id, case_type)
    WHERE status IN ('applied','appointment_scheduled','submitted','under_review');

CREATE TABLE service_appointments (
    id                 INTEGER PRIMARY KEY,
    case_id            INTEGER NOT NULL REFERENCES service_cases(id),
    agency_id          INTEGER NOT NULL REFERENCES agencies(id),
    place_id           INTEGER NOT NULL REFERENCES places(id),
    applicant_agent_id INTEGER NOT NULL REFERENCES agents(id),
    scheduled_tick     INTEGER NOT NULL CHECK(scheduled_tick >= 0),
    slot               TEXT NOT NULL DEFAULT 'business' CHECK(slot='business'),
    attempt_number     INTEGER NOT NULL CHECK(attempt_number BETWEEN 1 AND 3),
    schedule_sequence  INTEGER NOT NULL CHECK(schedule_sequence >= 1),
    capacity_rank      INTEGER NOT NULL CHECK(capacity_rank >= 1),
    lease_id           INTEGER REFERENCES occupancy_leases(id),
    status             TEXT NOT NULL CHECK(status IN
                          ('scheduled','attended','no_show','cancelled')),
    created_tick       INTEGER NOT NULL CHECK(created_tick >= 0),
    scheduled_event_id INTEGER REFERENCES events(id),
    attended_tick      INTEGER,
    outcome_event_id   INTEGER REFERENCES events(id),
    UNIQUE(case_id, schedule_sequence),
    CHECK(attended_tick IS NULL OR attended_tick >= scheduled_tick)
);
CREATE INDEX ix_service_appointments_day
    ON service_appointments(place_id, scheduled_tick, slot, status, capacity_rank, id);
CREATE INDEX ix_service_appointments_applicant
    ON service_appointments(applicant_agent_id, scheduled_tick, status, id);

CREATE TABLE institution_tasks (
    id                 INTEGER PRIMARY KEY,
    agency_id          INTEGER NOT NULL REFERENCES agencies(id),
    task_type          TEXT NOT NULL CHECK(task_type IN ('decide_business_permit')),
    source_case_id     INTEGER NOT NULL REFERENCES service_cases(id),
    assigned_agent_id  INTEGER REFERENCES agents(id),
    priority           INTEGER NOT NULL DEFAULT 0,
    created_tick       INTEGER NOT NULL CHECK(created_tick >= 0),
    due_tick           INTEGER NOT NULL CHECK(due_tick >= created_tick),
    assigned_tick      INTEGER,
    completed_tick     INTEGER,
    status             TEXT NOT NULL CHECK(status IN
                          ('pending','assigned','completed','cancelled')),
    payload_json       TEXT NOT NULL DEFAULT '{}',
    assigned_event_id  INTEGER REFERENCES events(id),
    outcome_event_id   INTEGER REFERENCES events(id),
    UNIQUE(task_type, source_case_id),
    CHECK(assigned_tick IS NULL OR assigned_tick >= created_tick),
    CHECK(completed_tick IS NULL OR completed_tick >= created_tick)
);
CREATE INDEX ix_institution_tasks_agency
    ON institution_tasks(agency_id, status, priority DESC, created_tick, source_case_id, id);
CREATE INDEX ix_institution_tasks_assignee
    ON institution_tasks(assigned_agent_id, status, due_tick, priority DESC, id);

CREATE TABLE civic_authorizations (
    id                       INTEGER PRIMARY KEY,
    authorization_type       TEXT NOT NULL CHECK(authorization_type='business_permit'),
    holder_agent_id          INTEGER NOT NULL REFERENCES agents(id),
    case_id                  INTEGER NOT NULL UNIQUE REFERENCES service_cases(id),
    application_payload_json TEXT NOT NULL,
    application_payload_hash TEXT NOT NULL CHECK(length(application_payload_hash)=64),
    issued_tick              INTEGER NOT NULL CHECK(issued_tick >= 0),
    expiry_tick              INTEGER NOT NULL CHECK(expiry_tick > issued_tick),
    consumed_tick            INTEGER,
    consumed_by_firm_id      INTEGER REFERENCES firms(id),
    status                   TEXT NOT NULL CHECK(status IN
                              ('active','consumed','expired','revoked')),
    issued_event_id          INTEGER REFERENCES events(id),
    consumed_event_id        INTEGER REFERENCES events(id),
    CHECK(consumed_tick IS NULL OR consumed_tick >= issued_tick)
);
CREATE INDEX ix_civic_authorizations_holder
    ON civic_authorizations(holder_agent_id, authorization_type, status, expiry_tick, id);

CREATE TABLE attention_contexts (
    id              INTEGER PRIMARY KEY,
    context_key     TEXT NOT NULL UNIQUE CHECK(length(context_key)=64),
    agent_id        INTEGER NOT NULL REFERENCES agents(id),
    tick            INTEGER NOT NULL CHECK(tick >= 0),
    purpose         TEXT NOT NULL,
    decision_id     INTEGER UNIQUE REFERENCES agent_decisions(id),
    lane_limit      INTEGER NOT NULL CHECK(lane_limit BETWEEN 1 AND 8),
    snapshot_json   TEXT NOT NULL,
    created_tick    INTEGER NOT NULL CHECK(created_tick >= 0),
    UNIQUE(agent_id, tick, purpose)
);
CREATE INDEX ix_attention_contexts_agent
    ON attention_contexts(agent_id, tick DESC, id DESC);

CREATE TABLE attention_context_items (
    id                  INTEGER PRIMARY KEY,
    context_id          INTEGER NOT NULL REFERENCES attention_contexts(id) ON DELETE CASCADE,
    lane                TEXT NOT NULL CHECK(lane IN ('mentions','needs_action','activity')),
    ordinal             INTEGER NOT NULL CHECK(ordinal BETWEEN 0 AND 7),
    source_event_id     INTEGER REFERENCES events(id),
    subject_type        TEXT,
    subject_id          INTEGER,
    title               TEXT NOT NULL,
    summary             TEXT NOT NULL,
    action_type         TEXT,
    action_payload_json TEXT,
    occurred_tick       INTEGER NOT NULL CHECK(occurred_tick >= 0),
    UNIQUE(context_id, lane, ordinal)
);
CREATE INDEX ix_attention_items_context
    ON attention_context_items(context_id, lane, ordinal);
CREATE INDEX ix_attention_items_source_event
    ON attention_context_items(source_event_id, context_id);

ALTER TABLE agent_decisions ADD COLUMN attention_context_key TEXT;
CREATE INDEX ix_agent_decisions_attention
    ON agent_decisions(attention_context_key);
"""


def verify(conn) -> None:
    expected = {
        "places",
        "occupancy_leases",
        "effective_presence",
        "agency_staff",
        "service_cases",
        "service_appointments",
        "institution_tasks",
        "civic_authorizations",
        "attention_contexts",
        "attention_context_items",
    }
    present = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
            "('places','occupancy_leases','effective_presence','agency_staff',"
            "'service_cases','service_appointments','institution_tasks',"
            "'civic_authorizations','attention_contexts','attention_context_items')"
        )
    }
    missing = expected - present
    if missing:
        raise RuntimeError(f"civic city tables are missing: {sorted(missing)}")
    decision_columns = {
        str(row[1]) for row in conn.execute("PRAGMA table_info(agent_decisions)")
    }
    if "attention_context_key" not in decision_columns:
        raise RuntimeError("agent_decisions.attention_context_key is missing")
    required_indexes = {
        "ix_occupancy_effective_agent",
        "ix_effective_presence_place",
        "ix_service_cases_queue",
        "ix_service_appointments_day",
        "ix_institution_tasks_assignee",
        "ix_attention_contexts_agent",
    }
    indexes = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )
    }
    missing_indexes = required_indexes - indexes
    if missing_indexes:
        raise RuntimeError(
            f"civic city indexes are missing: {sorted(missing_indexes)}")
