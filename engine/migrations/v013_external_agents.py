"""Schema 13: external-agent identities, credentials, turns, and receipts."""

NAME = "external_agent_gateway"

SQL = r"""
ALTER TABLE run_meta ADD COLUMN external_agent_influenced INTEGER NOT NULL DEFAULT 0;

CREATE TABLE external_agent_connections (
    id                    TEXT PRIMARY KEY CHECK(length(id) BETWEEN 16 AND 64),
    tenant_id             TEXT NOT NULL CHECK(length(tenant_id) BETWEEN 1 AND 128),
    owner_id_hash         TEXT NOT NULL CHECK(length(owner_id_hash)=64),
    display_name          TEXT NOT NULL CHECK(length(display_name) BETWEEN 1 AND 80),
    biography             TEXT NOT NULL DEFAULT '' CHECK(length(biography) <= 500),
    preferred_occupation  TEXT NOT NULL DEFAULT '' CHECK(length(preferred_occupation) <= 80),
    tier                  TEXT NOT NULL CHECK(tier IN ('observer','commons','actor')),
    scopes_json           TEXT NOT NULL CHECK(json_valid(scopes_json)),
    status                TEXT NOT NULL DEFAULT 'pending_actor'
                          CHECK(status IN ('pending_actor','active','suspended','revoked')),
    actor_id              INTEGER UNIQUE REFERENCES agents(id),
    actor_schedule_event_id INTEGER UNIQUE REFERENCES events(id),
    wake_interval_ticks   INTEGER NOT NULL DEFAULT 1 CHECK(wake_interval_ticks BETWEEN 1 AND 365),
    last_seen_at          TEXT,
    lease_expires_at      TEXT,
    created_tick          INTEGER NOT NULL CHECK(created_tick >= 0),
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL,
    CHECK((tier='observer' AND actor_id IS NULL AND actor_schedule_event_id IS NULL)
       OR (tier<>'observer'))
);

CREATE TABLE external_agent_credentials (
    id                 TEXT PRIMARY KEY CHECK(length(id) BETWEEN 16 AND 64),
    connection_id      TEXT NOT NULL REFERENCES external_agent_connections(id),
    kind               TEXT NOT NULL CHECK(kind IN ('personal','access','refresh')),
    token_hash         TEXT NOT NULL UNIQUE CHECK(length(token_hash)=64),
    scopes_json        TEXT NOT NULL CHECK(json_valid(scopes_json)),
    audience           TEXT NOT NULL CHECK(length(audience) BETWEEN 1 AND 200),
    expires_at         TEXT NOT NULL,
    rotated_from_id    TEXT REFERENCES external_agent_credentials(id),
    revoked_at         TEXT,
    created_at         TEXT NOT NULL,
    last_used_at       TEXT,
    CHECK(rotated_from_id IS NULL OR rotated_from_id <> id)
);

CREATE TABLE external_oauth_codes (
    id                 TEXT PRIMARY KEY CHECK(length(id) BETWEEN 16 AND 64),
    connection_id      TEXT NOT NULL REFERENCES external_agent_connections(id),
    code_hash          TEXT NOT NULL UNIQUE CHECK(length(code_hash)=64),
    client_id          TEXT NOT NULL CHECK(length(client_id) BETWEEN 1 AND 200),
    redirect_uri       TEXT NOT NULL CHECK(length(redirect_uri) BETWEEN 1 AND 1000),
    code_challenge     TEXT NOT NULL CHECK(length(code_challenge) BETWEEN 43 AND 128),
    challenge_method   TEXT NOT NULL CHECK(challenge_method='S256'),
    scopes_json        TEXT NOT NULL CHECK(json_valid(scopes_json)),
    audience           TEXT NOT NULL CHECK(length(audience) BETWEEN 1 AND 200),
    expires_at         TEXT NOT NULL,
    consumed_at        TEXT,
    created_at         TEXT NOT NULL
);

CREATE TABLE external_oauth_clients (
    client_id          TEXT PRIMARY KEY CHECK(length(client_id) BETWEEN 16 AND 200),
    client_name        TEXT NOT NULL CHECK(length(client_name) BETWEEN 1 AND 200),
    redirect_uris_json TEXT NOT NULL CHECK(json_valid(redirect_uris_json)),
    grant_types_json   TEXT NOT NULL CHECK(json_valid(grant_types_json)),
    response_types_json TEXT NOT NULL CHECK(json_valid(response_types_json)),
    token_endpoint_auth_method TEXT NOT NULL CHECK(token_endpoint_auth_method='none'),
    created_at         TEXT NOT NULL
);

CREATE TABLE external_actor_requests (
    id                 INTEGER PRIMARY KEY,
    connection_id      TEXT NOT NULL UNIQUE REFERENCES external_agent_connections(id),
    schedule_event_id  INTEGER NOT NULL UNIQUE REFERENCES events(id),
    requested_tick     INTEGER NOT NULL CHECK(requested_tick >= 0),
    due_tick           INTEGER NOT NULL CHECK(due_tick > requested_tick),
    public_name        TEXT NOT NULL CHECK(length(public_name) BETWEEN 1 AND 80),
    biography          TEXT NOT NULL DEFAULT '' CHECK(length(biography) <= 500),
    preferred_occupation TEXT NOT NULL DEFAULT '' CHECK(length(preferred_occupation) <= 80),
    status             TEXT NOT NULL DEFAULT 'scheduled'
                       CHECK(status IN ('scheduled','spawned','cancelled')),
    actor_id           INTEGER UNIQUE REFERENCES agents(id),
    spawned_tick       INTEGER,
    CHECK((status='spawned') = (actor_id IS NOT NULL AND spawned_tick IS NOT NULL))
);

CREATE TABLE external_agent_turns (
    id                    TEXT PRIMARY KEY CHECK(length(id) BETWEEN 16 AND 64),
    connection_id         TEXT NOT NULL REFERENCES external_agent_connections(id),
    actor_id               INTEGER REFERENCES agents(id),
    completed_tick         INTEGER NOT NULL CHECK(completed_tick >= 0),
    target_tick            INTEGER NOT NULL CHECK(target_tick > completed_tick),
    projection_hash        TEXT NOT NULL CHECK(length(projection_hash)=64),
    action_catalog_version TEXT NOT NULL CHECK(length(action_catalog_version)=64),
    envelope_json          TEXT NOT NULL CHECK(json_valid(envelope_json)),
    event_cursor           INTEGER NOT NULL DEFAULT 0 CHECK(event_cursor >= 0),
    deadline_at            TEXT NOT NULL,
    status                 TEXT NOT NULL DEFAULT 'open'
                           CHECK(status IN ('open','submitted','fallback','expired','closed')),
    created_at             TEXT NOT NULL,
    updated_at             TEXT NOT NULL,
    UNIQUE(connection_id, target_tick)
);

CREATE TABLE external_action_submissions (
    id                      TEXT PRIMARY KEY CHECK(length(id) BETWEEN 16 AND 64),
    connection_id           TEXT NOT NULL REFERENCES external_agent_connections(id),
    actor_id                 INTEGER NOT NULL REFERENCES agents(id),
    turn_id                  TEXT NOT NULL REFERENCES external_agent_turns(id),
    target_tick              INTEGER NOT NULL CHECK(target_tick >= 1),
    observed_projection_hash TEXT NOT NULL CHECK(length(observed_projection_hash)=64),
    idempotency_key          TEXT NOT NULL CHECK(length(idempotency_key) BETWEEN 1 AND 128),
    action_json              TEXT NOT NULL CHECK(json_valid(action_json)),
    rationale_summary       TEXT NOT NULL DEFAULT '' CHECK(length(rationale_summary) <= 500),
    status                   TEXT NOT NULL DEFAULT 'queued'
                             CHECK(status IN ('queued','executed','rejected','stale')),
    validator_results_json  TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(validator_results_json)),
    result_json              TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(result_json)),
    event_ids_json           TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(event_ids_json)),
    resulting_state_hash     TEXT,
    source_submission_id     TEXT,
    created_at               TEXT NOT NULL,
    completed_at             TEXT,
    UNIQUE(connection_id, idempotency_key)
);

CREATE TABLE external_security_audit (
    id                 INTEGER PRIMARY KEY,
    connection_id      TEXT REFERENCES external_agent_connections(id),
    tick               INTEGER NOT NULL CHECK(tick >= 0),
    event_kind         TEXT NOT NULL CHECK(length(event_kind) BETWEEN 1 AND 100),
    outcome            TEXT NOT NULL CHECK(outcome IN ('allowed','denied','changed')),
    details_json       TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(details_json)),
    created_at         TEXT NOT NULL
);

CREATE TABLE external_rate_windows (
    connection_id      TEXT NOT NULL REFERENCES external_agent_connections(id),
    window_started_at  TEXT NOT NULL,
    request_count      INTEGER NOT NULL DEFAULT 0 CHECK(request_count >= 0),
    PRIMARY KEY(connection_id, window_started_at)
);

CREATE INDEX ix_external_connections_owner
    ON external_agent_connections(tenant_id, owner_id_hash, status, created_at);
CREATE INDEX ix_external_credentials_connection
    ON external_agent_credentials(connection_id, kind, revoked_at, expires_at);
CREATE INDEX ix_external_turns_open
    ON external_agent_turns(connection_id, status, target_tick);
CREATE INDEX ix_external_submissions_due
    ON external_action_submissions(status, target_tick, actor_id);
CREATE UNIQUE INDEX ux_external_one_action_per_wake
    ON external_action_submissions(actor_id, target_tick)
    WHERE status IN ('queued','executed');
CREATE INDEX ix_external_audit_connection
    ON external_security_audit(connection_id, id DESC);

CREATE TRIGGER external_security_audit_no_update
BEFORE UPDATE ON external_security_audit
BEGIN SELECT RAISE(ABORT, 'external security audit is immutable'); END;

CREATE TRIGGER external_security_audit_no_delete
BEFORE DELETE ON external_security_audit
BEGIN SELECT RAISE(ABORT, 'external security audit is immutable'); END;

CREATE TRIGGER external_submission_identity_immutable
BEFORE UPDATE ON external_action_submissions
WHEN NEW.id<>OLD.id OR NEW.connection_id<>OLD.connection_id OR NEW.actor_id<>OLD.actor_id
  OR NEW.turn_id<>OLD.turn_id OR NEW.target_tick<>OLD.target_tick
  OR NEW.observed_projection_hash<>OLD.observed_projection_hash
  OR NEW.idempotency_key<>OLD.idempotency_key OR NEW.action_json<>OLD.action_json
  OR NEW.rationale_summary<>OLD.rationale_summary OR NEW.created_at<>OLD.created_at
BEGIN SELECT RAISE(ABORT, 'external action identity is immutable'); END;
"""


REQUIRED_TABLES = {
    "external_agent_connections",
    "external_agent_credentials",
    "external_oauth_codes",
    "external_oauth_clients",
    "external_actor_requests",
    "external_agent_turns",
    "external_action_submissions",
    "external_security_audit",
    "external_rate_windows",
}


def verify(conn) -> None:
    tables = {str(row[0]) for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    missing = sorted(REQUIRED_TABLES - tables)
    if missing:
        raise RuntimeError(f"schema 13 missing tables: {','.join(missing)}")
    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(run_meta)")}
    if "external_agent_influenced" not in columns:
        raise RuntimeError("schema 13 run influence marker missing")
    if list(conn.execute("PRAGMA foreign_key_check")):
        raise RuntimeError("schema 13 foreign-key verification failed")
