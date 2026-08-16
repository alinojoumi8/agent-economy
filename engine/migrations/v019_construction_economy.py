"""Semantics 13 construction projects, permits, contributions, and receipts."""
from __future__ import annotations


NAME = "construction_economy"

SQL = r"""
CREATE TABLE construction_projects (
    id                         INTEGER PRIMARY KEY,
    project_key                TEXT NOT NULL UNIQUE
                               CHECK(length(project_key) BETWEEN 16 AND 96),
    name                       TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 160),
    owner_type                 TEXT NOT NULL
                               CHECK(owner_type IN ('agent','firm','agency')),
    owner_id                   INTEGER NOT NULL CHECK(owner_id > 0),
    initiator_agent_id         INTEGER NOT NULL REFERENCES agents(id),
    region_id                  INTEGER NOT NULL REFERENCES regions(id),
    site_key                   TEXT NOT NULL CHECK(length(site_key) BETWEEN 1 AND 120),
    site_x                     REAL NOT NULL CHECK(site_x >= 0.0 AND site_x <= 1.0),
    site_y                     REAL NOT NULL CHECK(site_y >= 0.0 AND site_y <= 1.0),
    target_place_type          TEXT NOT NULL
                               CHECK(target_place_type IN
                                  ('private_home','workplace','public_facility')),
    status                     TEXT NOT NULL
                               CHECK(status IN
                                  ('proposed','permitting','funding','building',
                                   'completed','cancelled')),
    permit_case_id             INTEGER UNIQUE,
    required_funding_cents     INTEGER NOT NULL CHECK(required_funding_cents > 0),
    required_work_units        INTEGER NOT NULL CHECK(required_work_units > 0),
    contributed_funding_cents  INTEGER NOT NULL DEFAULT 0
                               CHECK(contributed_funding_cents >= 0),
    contributed_work_units     INTEGER NOT NULL DEFAULT 0
                               CHECK(contributed_work_units >= 0),
    spent_funding_cents        INTEGER NOT NULL DEFAULT 0
                               CHECK(spent_funding_cents >= 0),
    refunded_funding_cents     INTEGER NOT NULL DEFAULT 0
                               CHECK(refunded_funding_cents >= 0),
    escrow_account_id          INTEGER NOT NULL UNIQUE REFERENCES accounts(id),
    proposed_tick              INTEGER NOT NULL CHECK(proposed_tick >= 0),
    permitting_tick            INTEGER,
    funding_tick               INTEGER,
    building_tick              INTEGER,
    foundation_tick            INTEGER,
    frame_tick                 INTEGER,
    shell_tick                 INTEGER,
    completed_tick             INTEGER,
    cancelled_tick             INTEGER,
    place_id                   INTEGER UNIQUE REFERENCES places(id),
    evidence_refs_json         TEXT NOT NULL DEFAULT '[]',
    proposed_event_id          INTEGER REFERENCES events(id),
    permit_event_id            INTEGER REFERENCES events(id),
    completion_event_id        INTEGER REFERENCES events(id),
    cancellation_event_id      INTEGER REFERENCES events(id),
    CHECK(contributed_funding_cents <= required_funding_cents),
    CHECK(contributed_work_units <= required_work_units),
    CHECK(spent_funding_cents + refunded_funding_cents
          <= contributed_funding_cents),
    CHECK(permitting_tick IS NULL OR permitting_tick >= proposed_tick),
    CHECK(funding_tick IS NULL OR funding_tick >= proposed_tick),
    CHECK(building_tick IS NULL OR building_tick >= proposed_tick),
    CHECK(foundation_tick IS NULL OR foundation_tick >= proposed_tick),
    CHECK(frame_tick IS NULL OR frame_tick >= proposed_tick),
    CHECK(shell_tick IS NULL OR shell_tick >= proposed_tick),
    CHECK(completed_tick IS NULL OR completed_tick >= proposed_tick),
    CHECK(cancelled_tick IS NULL OR cancelled_tick >= proposed_tick),
    CHECK((status='completed' AND completed_tick IS NOT NULL AND place_id IS NOT NULL)
          OR status<>'completed'),
    CHECK((status='cancelled' AND cancelled_tick IS NOT NULL)
          OR status<>'cancelled')
);
CREATE INDEX ix_construction_projects_status
    ON construction_projects(status, proposed_tick, id);
CREATE INDEX ix_construction_projects_region
    ON construction_projects(region_id, target_place_type, status, id);
CREATE INDEX ix_construction_projects_owner
    ON construction_projects(owner_type, owner_id, status, id);
CREATE UNIQUE INDEX ux_construction_active_owner_kind
    ON construction_projects(owner_type, owner_id, target_place_type)
    WHERE status IN ('proposed','permitting','funding','building');
CREATE UNIQUE INDEX ux_construction_occupied_site
    ON construction_projects(region_id, site_key)
    WHERE status<>'cancelled';

CREATE TABLE construction_permit_cases (
    id                    INTEGER PRIMARY KEY,
    project_id            INTEGER NOT NULL UNIQUE REFERENCES construction_projects(id),
    agency_id             INTEGER NOT NULL REFERENCES agencies(id),
    applicant_agent_id    INTEGER NOT NULL REFERENCES agents(id),
    region_id             INTEGER NOT NULL REFERENCES regions(id),
    status                TEXT NOT NULL
                          CHECK(status IN ('submitted','approved','denied','withdrawn')),
    created_tick          INTEGER NOT NULL CHECK(created_tick >= 0),
    decided_tick          INTEGER,
    decision_actor_id     INTEGER REFERENCES agents(id),
    reason_code           TEXT,
    created_event_id      INTEGER REFERENCES events(id),
    outcome_event_id      INTEGER REFERENCES events(id),
    CHECK(decided_tick IS NULL OR decided_tick >= created_tick),
    CHECK((status='submitted' AND decided_tick IS NULL)
          OR (status<>'submitted' AND decided_tick IS NOT NULL))
);
CREATE INDEX ix_construction_permit_queue
    ON construction_permit_cases(agency_id, status, created_tick, id);

CREATE TABLE construction_contributions (
    id                         INTEGER PRIMARY KEY,
    dedupe_key                 TEXT NOT NULL UNIQUE CHECK(length(dedupe_key)=64),
    project_id                 INTEGER NOT NULL REFERENCES construction_projects(id),
    actor_agent_id             INTEGER NOT NULL REFERENCES agents(id),
    contribution_type          TEXT NOT NULL
                               CHECK(contribution_type IN ('funding','work','refund')),
    amount_cents               INTEGER NOT NULL DEFAULT 0 CHECK(amount_cents >= 0),
    work_units                 INTEGER NOT NULL DEFAULT 0 CHECK(work_units >= 0),
    source_account_id          INTEGER REFERENCES accounts(id),
    transaction_id             INTEGER REFERENCES transactions(id),
    wage_transaction_id        INTEGER REFERENCES transactions(id),
    procurement_transaction_id INTEGER REFERENCES transactions(id),
    source_contribution_id     INTEGER REFERENCES construction_contributions(id),
    evidence_event_id          INTEGER REFERENCES events(id),
    tick                       INTEGER NOT NULL CHECK(tick >= 0),
    evidence_refs_json         TEXT NOT NULL DEFAULT '[]',
    metadata_json              TEXT NOT NULL DEFAULT '{}',
    CHECK(
        (contribution_type='funding' AND amount_cents > 0 AND work_units=0)
        OR (contribution_type='work' AND work_units > 0)
        OR (contribution_type='refund' AND amount_cents > 0 AND work_units=0)
    )
);
CREATE INDEX ix_construction_contributions_project
    ON construction_contributions(project_id, tick, id);
CREATE INDEX ix_construction_contributions_actor
    ON construction_contributions(actor_agent_id, tick DESC, id DESC);

CREATE TABLE construction_action_receipts (
    id              INTEGER PRIMARY KEY,
    actor_agent_id  INTEGER NOT NULL REFERENCES agents(id),
    dedupe_key      TEXT NOT NULL CHECK(length(dedupe_key) BETWEEN 8 AND 128),
    action_type     TEXT NOT NULL,
    payload_hash    TEXT NOT NULL CHECK(length(payload_hash)=64),
    project_id      INTEGER REFERENCES construction_projects(id),
    tick            INTEGER NOT NULL CHECK(tick >= 0),
    ok              INTEGER NOT NULL CHECK(ok IN (0,1)),
    result_json     TEXT NOT NULL,
    UNIQUE(actor_agent_id, dedupe_key)
);
CREATE INDEX ix_construction_receipts_project
    ON construction_action_receipts(project_id, tick, id);
"""


def verify(conn) -> None:
    expected = {
        "construction_projects",
        "construction_permit_cases",
        "construction_contributions",
        "construction_action_receipts",
    }
    present = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE "
            "'construction_%'"
        )
    }
    missing = expected - present
    if missing:
        raise RuntimeError(f"construction tables are missing: {sorted(missing)}")
    required_indexes = {
        "ix_construction_projects_status",
        "ix_construction_projects_region",
        "ix_construction_projects_owner",
        "ux_construction_active_owner_kind",
        "ux_construction_occupied_site",
        "ix_construction_permit_queue",
        "ix_construction_contributions_project",
        "ix_construction_contributions_actor",
        "ix_construction_receipts_project",
    }
    indexes = {
        str(row[0])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
    }
    missing_indexes = required_indexes - indexes
    if missing_indexes:
        raise RuntimeError(
            f"construction indexes are missing: {sorted(missing_indexes)}")
