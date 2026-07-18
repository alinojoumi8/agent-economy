"""Schema 12: private communications, causal links, and projection cursors."""

NAME = "communications_and_causal_links"

SQL = r"""
CREATE TABLE IF NOT EXISTS comm_threads (
    id                  INTEGER PRIMARY KEY,
    created_tick        INTEGER NOT NULL CHECK(created_tick >= 0),
    created_by_agent_id INTEGER NOT NULL REFERENCES agents(id),
    subject             TEXT NOT NULL CHECK(length(subject) BETWEEN 1 AND 160),
    status              TEXT NOT NULL DEFAULT 'open'
                        CHECK(status IN ('open','closed')),
    organization_kind   TEXT,
    organization_id     INTEGER,
    root_event_id       INTEGER REFERENCES events(id),
    CHECK((organization_kind IS NULL) = (organization_id IS NULL))
);

CREATE TABLE IF NOT EXISTS comm_messages (
    id                   INTEGER PRIMARY KEY,
    thread_id            INTEGER NOT NULL REFERENCES comm_threads(id),
    parent_message_id    INTEGER REFERENCES comm_messages(id),
    forwarded_from_id    INTEGER REFERENCES comm_messages(id),
    sender_agent_id      INTEGER NOT NULL REFERENCES agents(id),
    created_tick         INTEGER NOT NULL CHECK(created_tick >= 0),
    deliver_at_tick      INTEGER NOT NULL,
    visibility           TEXT NOT NULL
                         CHECK(visibility IN ('participants','organization','public')),
    body_text            TEXT NOT NULL CHECK(length(body_text) BETWEEN 1 AND 2000),
    model_call_id        INTEGER REFERENCES llm_calls(id),
    created_event_id     INTEGER NOT NULL REFERENCES events(id),
    publication_event_id INTEGER REFERENCES events(id),
    status               TEXT NOT NULL DEFAULT 'queued'
                         CHECK(status IN
                           ('queued','delivered','partial','undeliverable','published')),
    CHECK(deliver_at_tick >= created_tick + 1),
    CHECK(parent_message_id IS NULL OR parent_message_id <> id),
    CHECK(forwarded_from_id IS NULL OR forwarded_from_id <> id),
    CHECK(
      (visibility='public' AND status IN ('queued','published'))
      OR
      (visibility<>'public' AND status<>'published')
    )
);

CREATE TABLE IF NOT EXISTS comm_audiences (
    id                       INTEGER PRIMARY KEY,
    message_id               INTEGER NOT NULL REFERENCES comm_messages(id),
    audience_key             TEXT NOT NULL,
    audience_kind            TEXT NOT NULL
                             CHECK(audience_kind IN ('agent','organization','public')),
    audience_agent_id        INTEGER REFERENCES agents(id),
    organization_kind        TEXT,
    organization_id          INTEGER,
    resolved_tick            INTEGER,
    resolution_status        TEXT NOT NULL DEFAULT 'queued'
                             CHECK(resolution_status IN
                               ('queued','delivered','partial','undeliverable','published')),
    resolved_recipient_count INTEGER NOT NULL DEFAULT 0
                             CHECK(resolved_recipient_count >= 0),
    membership_snapshot_hash TEXT,
    failure_reason           TEXT,
    CHECK(
      (audience_kind='agent' AND audience_agent_id IS NOT NULL
       AND organization_kind IS NULL AND organization_id IS NULL
       AND audience_key='agent:' || audience_agent_id)
      OR
      (audience_kind='organization' AND audience_agent_id IS NULL
       AND organization_kind IS NOT NULL AND organization_id IS NOT NULL
       AND audience_key='organization:' || organization_kind || ':' || organization_id)
      OR
      (audience_kind='public' AND audience_agent_id IS NULL
       AND organization_kind IS NULL AND organization_id IS NULL
       AND audience_key='public')
    ),
    CHECK((resolution_status='queued') = (resolved_tick IS NULL)),
    UNIQUE(message_id, audience_key)
);

CREATE TABLE IF NOT EXISTS comm_deliveries (
    id                 INTEGER PRIMARY KEY,
    dedupe_key         TEXT NOT NULL UNIQUE CHECK(length(dedupe_key)=64),
    message_id         INTEGER NOT NULL REFERENCES comm_messages(id),
    audience_id        INTEGER NOT NULL REFERENCES comm_audiences(id),
    recipient_agent_id INTEGER NOT NULL REFERENCES agents(id),
    delivery_tick      INTEGER NOT NULL,
    grant_basis        TEXT NOT NULL
                       CHECK(grant_basis IN ('direct_delivery','organization_at_delivery')),
    membership_ref_json TEXT,
    memory_id          INTEGER REFERENCES memories(id),
    read_tick          INTEGER,
    read_context_key   TEXT,
    delivery_status    TEXT NOT NULL
                       CHECK(delivery_status IN ('delivered','undeliverable')),
    failure_reason     TEXT,
    CHECK(
      (delivery_status='delivered' AND memory_id IS NOT NULL AND failure_reason IS NULL)
      OR
      (delivery_status='undeliverable' AND memory_id IS NULL
       AND read_tick IS NULL AND read_context_key IS NULL AND failure_reason IS NOT NULL)
    ),
    CHECK((read_tick IS NULL) = (read_context_key IS NULL)),
    UNIQUE(memory_id),
    UNIQUE(message_id, recipient_agent_id)
);

CREATE TABLE IF NOT EXISTS comm_disclosure_authorities (
    id                  INTEGER PRIMARY KEY,
    case_id             INTEGER NOT NULL,
    authority_kind      TEXT NOT NULL CHECK(authority_kind IN ('court_order','agreement')),
    authority_record_id TEXT NOT NULL,
    authority_event_id  INTEGER NOT NULL REFERENCES events(id),
    authority_ref_json  TEXT NOT NULL,
    created_tick        INTEGER NOT NULL,
    UNIQUE(case_id, authority_kind, authority_record_id)
);

CREATE TABLE IF NOT EXISTS comm_disclosures (
    id               INTEGER PRIMARY KEY,
    dedupe_key       TEXT NOT NULL UNIQUE CHECK(length(dedupe_key)=64),
    message_id       INTEGER NOT NULL REFERENCES comm_messages(id),
    case_id          INTEGER NOT NULL,
    grantee_agent_id INTEGER NOT NULL REFERENCES agents(id),
    granted_tick     INTEGER NOT NULL,
    authority_id     INTEGER NOT NULL REFERENCES comm_disclosure_authorities(id),
    UNIQUE(message_id, case_id, grantee_agent_id)
);

CREATE TABLE IF NOT EXISTS agent_decisions (
    id                    INTEGER PRIMARY KEY,
    dedupe_key            TEXT NOT NULL UNIQUE CHECK(length(dedupe_key)=64),
    tick                  INTEGER NOT NULL CHECK(tick >= 0),
    agent_id              INTEGER NOT NULL REFERENCES agents(id),
    purpose               TEXT NOT NULL,
    method                TEXT NOT NULL CHECK(method IN ('scripted_policy','model_call','participant')),
    model_call_id         INTEGER REFERENCES llm_calls(id),
    read_context_key      TEXT,
    reasoning_fingerprint TEXT NOT NULL CHECK(length(reasoning_fingerprint)=64),
    CHECK((method='model_call') = (model_call_id IS NOT NULL)),
    UNIQUE(tick, agent_id, purpose)
);

CREATE TABLE IF NOT EXISTS causal_links (
    id               INTEGER PRIMARY KEY,
    dedupe_key       TEXT NOT NULL UNIQUE CHECK(length(dedupe_key)=64),
    created_tick     INTEGER NOT NULL CHECK(created_tick >= 0),
    source_kind      TEXT NOT NULL CHECK(source_kind IN
                       ('message','memory','belief','decision','action_proposal','event',
                        'contract','case','article','ledger_transaction')),
    source_id        TEXT NOT NULL,
    source_tick      INTEGER NOT NULL CHECK(source_tick >= 0),
    source_order_key TEXT NOT NULL,
    target_kind      TEXT NOT NULL CHECK(target_kind IN
                       ('message','memory','belief','decision','action_proposal','event',
                        'contract','case','article','ledger_transaction')),
    target_id        TEXT NOT NULL,
    target_tick      INTEGER NOT NULL CHECK(target_tick >= 0),
    target_order_key TEXT NOT NULL,
    relation         TEXT NOT NULL CHECK(relation IN
                       ('observed','cited','motivated','triggered','settled','inferred')),
    authority        TEXT NOT NULL CHECK(authority IN
                       ('engine','actor_claim','model_inference')),
    actor_agent_id   INTEGER REFERENCES agents(id),
    confidence       REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
    method           TEXT,
    model_call_id    INTEGER REFERENCES llm_calls(id),
    provenance_json  TEXT NOT NULL,
    evidence_json    TEXT NOT NULL DEFAULT '{}',
    CHECK(NOT (source_kind=target_kind AND source_id=target_id)),
    CHECK(created_tick >= source_tick AND created_tick >= target_tick),
    CHECK(authority='model_inference' OR source_order_key < target_order_key),
    CHECK(
      (authority='engine' AND relation <> 'inferred' AND confidence=1.0
       AND actor_agent_id IS NULL AND model_call_id IS NULL)
      OR
      (authority='actor_claim' AND relation IN ('cited','motivated')
       AND actor_agent_id IS NOT NULL AND method IS NOT NULL)
      OR
      (authority='model_inference' AND relation='inferred'
       AND method IS NOT NULL AND model_call_id IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS projection_commits (
    cursor          INTEGER PRIMARY KEY AUTOINCREMENT,
    tick            INTEGER NOT NULL CHECK(tick >= 0),
    phase           TEXT NOT NULL,
    domains_json    TEXT NOT NULL DEFAULT '[]',
    created_event_id INTEGER REFERENCES events(id),
    UNIQUE(tick, phase)
);

CREATE INDEX IF NOT EXISTS ix_comm_messages_due
    ON comm_messages(status, deliver_at_tick, created_tick, id);
CREATE INDEX IF NOT EXISTS ix_comm_messages_thread ON comm_messages(thread_id, id);
CREATE INDEX IF NOT EXISTS ix_comm_audiences_resolution
    ON comm_audiences(resolution_status, message_id, audience_key);
CREATE INDEX IF NOT EXISTS ix_comm_deliveries_recipient
    ON comm_deliveries(recipient_agent_id, delivery_tick, id);
CREATE INDEX IF NOT EXISTS ix_comm_deliveries_message
    ON comm_deliveries(message_id, recipient_agent_id);
CREATE INDEX IF NOT EXISTS ix_comm_disclosures_case
    ON comm_disclosures(case_id, grantee_agent_id);
CREATE INDEX IF NOT EXISTS ix_agent_decisions_tick
    ON agent_decisions(tick, agent_id, id);
CREATE INDEX IF NOT EXISTS ix_causal_source
    ON causal_links(source_kind, source_id, relation, id);
CREATE INDEX IF NOT EXISTS ix_causal_target
    ON causal_links(target_kind, target_id, relation, id);
CREATE INDEX IF NOT EXISTS ix_causal_created
    ON causal_links(created_tick, id);
CREATE INDEX IF NOT EXISTS ix_causal_relation
    ON causal_links(relation, authority, id);

CREATE TRIGGER IF NOT EXISTS trg_comm_audience_visibility_insert
BEFORE INSERT ON comm_audiences
BEGIN
  SELECT CASE
    WHEN NEW.audience_kind='agent' AND
         (SELECT visibility FROM comm_messages WHERE id=NEW.message_id) <> 'participants'
      THEN RAISE(ABORT, 'direct audience requires participants visibility')
    WHEN NEW.audience_kind='organization' AND
         (SELECT visibility FROM comm_messages WHERE id=NEW.message_id) <> 'organization'
      THEN RAISE(ABORT, 'organization audience requires organization visibility')
    WHEN NEW.audience_kind='public' AND
         (SELECT visibility FROM comm_messages WHERE id=NEW.message_id) <> 'public'
      THEN RAISE(ABORT, 'public audience requires public visibility')
    WHEN EXISTS(
         SELECT 1 FROM comm_audiences
         WHERE message_id=NEW.message_id AND audience_kind<>NEW.audience_kind)
      THEN RAISE(ABORT, 'message audience kinds cannot be mixed')
  END;
END;

CREATE TRIGGER IF NOT EXISTS trg_comm_audience_resolution_immutable
BEFORE UPDATE ON comm_audiences
WHEN OLD.resolved_tick IS NOT NULL AND (
  NEW.audience_key<>OLD.audience_key
  OR NEW.audience_kind<>OLD.audience_kind
  OR COALESCE(NEW.audience_agent_id,-1)<>COALESCE(OLD.audience_agent_id,-1)
  OR COALESCE(NEW.organization_kind,'')<>COALESCE(OLD.organization_kind,'')
  OR COALESCE(NEW.organization_id,-1)<>COALESCE(OLD.organization_id,-1)
  OR NEW.resolved_tick<>OLD.resolved_tick
  OR NEW.resolution_status<>OLD.resolution_status
  OR NEW.resolved_recipient_count<>OLD.resolved_recipient_count
  OR COALESCE(NEW.membership_snapshot_hash,'')<>COALESCE(OLD.membership_snapshot_hash,'')
  OR COALESCE(NEW.failure_reason,'')<>COALESCE(OLD.failure_reason,'')
)
BEGIN
  SELECT RAISE(ABORT, 'resolved communication audience is immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_comm_delivery_grant_immutable
BEFORE UPDATE ON comm_deliveries
WHEN NEW.dedupe_key<>OLD.dedupe_key
  OR NEW.message_id<>OLD.message_id
  OR NEW.audience_id<>OLD.audience_id
  OR NEW.recipient_agent_id<>OLD.recipient_agent_id
  OR NEW.delivery_tick<>OLD.delivery_tick
  OR NEW.grant_basis<>OLD.grant_basis
  OR COALESCE(NEW.membership_ref_json,'')<>COALESCE(OLD.membership_ref_json,'')
  OR COALESCE(NEW.memory_id,-1)<>COALESCE(OLD.memory_id,-1)
  OR NEW.delivery_status<>OLD.delivery_status
  OR COALESCE(NEW.failure_reason,'')<>COALESCE(OLD.failure_reason,'')
BEGIN
  SELECT RAISE(ABORT, 'communication access grant is immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_comm_delivery_no_delete
BEFORE DELETE ON comm_deliveries
BEGIN
  SELECT RAISE(ABORT, 'communication access grant is immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_comm_disclosure_no_delete
BEFORE DELETE ON comm_disclosures
BEGIN
  SELECT RAISE(ABORT, 'communication disclosure grant is immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_comm_disclosure_case_insert
BEFORE INSERT ON comm_disclosures
BEGIN
  SELECT CASE WHEN
    (SELECT case_id FROM comm_disclosure_authorities WHERE id=NEW.authority_id) <> NEW.case_id
    THEN RAISE(ABORT, 'disclosure authority case mismatch')
  END;
END;
"""


REQUIRED_TABLES = {
    "comm_threads",
    "comm_messages",
    "comm_audiences",
    "comm_deliveries",
    "comm_disclosure_authorities",
    "comm_disclosures",
    "agent_decisions",
    "causal_links",
    "projection_commits",
}


def verify(conn) -> None:
    """Fail closed if schema-12 structure or cross-table invariants drift."""
    tables = {
        str(row[0]) for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")
    }
    missing = sorted(REQUIRED_TABLES - tables)
    if missing:
        raise RuntimeError(f"schema 12 missing tables: {','.join(missing)}")
    foreign_key_errors = list(conn.execute("PRAGMA foreign_key_check"))
    if foreign_key_errors:
        raise RuntimeError("schema 12 foreign-key verification failed")
    invalid_audiences = conn.execute(
        "SELECT COUNT(*) FROM comm_messages m WHERE "
        "(m.visibility='public' AND (SELECT COUNT(*) FROM comm_audiences a "
        " WHERE a.message_id=m.id AND a.audience_kind='public')<>1) OR "
        "(m.visibility='organization' AND (SELECT COUNT(*) FROM comm_audiences a "
        " WHERE a.message_id=m.id AND a.audience_kind='organization')<>1) OR "
        "(m.visibility='participants' AND (SELECT COUNT(*) FROM comm_audiences a "
        " WHERE a.message_id=m.id AND a.audience_kind='agent')<1) OR "
        "EXISTS(SELECT 1 FROM comm_audiences a WHERE a.message_id=m.id AND "
        " ((m.visibility='public' AND a.audience_kind<>'public') OR "
        "  (m.visibility='organization' AND a.audience_kind<>'organization') OR "
        "  (m.visibility='participants' AND a.audience_kind<>'agent')))"
    ).fetchone()[0]
    if invalid_audiences:
        raise RuntimeError("schema 12 audience invariant failed")
    invalid_outcomes = conn.execute(
        "SELECT COUNT(*) FROM comm_deliveries d WHERE "
        "d.delivery_status='delivered' AND NOT EXISTS ("
        " SELECT 1 FROM causal_links c WHERE c.source_kind='message' "
        " AND c.source_id=CAST(d.message_id AS TEXT) AND c.target_kind='memory' "
        " AND c.target_id=CAST(d.memory_id AS TEXT) AND c.relation='observed' "
        " AND c.authority='engine')"
    ).fetchone()[0]
    if invalid_outcomes:
        raise RuntimeError("schema 12 delivery provenance invariant failed")
