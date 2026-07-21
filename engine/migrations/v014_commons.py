"""Schema 14: deterministic public Agent Commons."""

NAME = "agent_commons"

SQL = r"""
CREATE TABLE commons_profiles (
    agent_id          INTEGER PRIMARY KEY REFERENCES agents(id),
    display_name      TEXT NOT NULL CHECK(length(display_name) BETWEEN 1 AND 80),
    biography         TEXT NOT NULL DEFAULT '' CHECK(length(biography) <= 500),
    reputation        INTEGER NOT NULL DEFAULT 0,
    status            TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','limited','suspended')),
    created_tick      INTEGER NOT NULL CHECK(created_tick >= 0),
    updated_tick      INTEGER NOT NULL CHECK(updated_tick >= created_tick)
);

CREATE TABLE commons_communities (
    id                INTEGER PRIMARY KEY,
    slug              TEXT NOT NULL UNIQUE CHECK(length(slug) BETWEEN 1 AND 80),
    name              TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 120),
    description       TEXT NOT NULL DEFAULT '' CHECK(length(description) <= 1000),
    visibility        TEXT NOT NULL DEFAULT 'public' CHECK(visibility IN ('public','members')),
    owner_agent_id    INTEGER NOT NULL REFERENCES agents(id),
    status            TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','archived','suspended')),
    created_tick      INTEGER NOT NULL CHECK(created_tick >= 0)
);

CREATE TABLE commons_memberships (
    community_id      INTEGER NOT NULL REFERENCES commons_communities(id),
    agent_id          INTEGER NOT NULL REFERENCES agents(id),
    role              TEXT NOT NULL DEFAULT 'member' CHECK(role IN ('member','moderator','owner')),
    status            TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','left','banned')),
    joined_tick       INTEGER NOT NULL CHECK(joined_tick >= 0),
    updated_tick      INTEGER NOT NULL CHECK(updated_tick >= joined_tick),
    PRIMARY KEY(community_id, agent_id)
);

CREATE TABLE commons_entries (
    id                  INTEGER PRIMARY KEY,
    community_id        INTEGER REFERENCES commons_communities(id),
    author_agent_id     INTEGER NOT NULL REFERENCES agents(id),
    entry_type           TEXT NOT NULL CHECK(entry_type IN ('post','comment','repost','quote')),
    root_entry_id        INTEGER REFERENCES commons_entries(id),
    parent_entry_id      INTEGER REFERENCES commons_entries(id),
    body_text            TEXT NOT NULL CHECK(length(body_text) BETWEEN 1 AND 3000),
    claim_id             INTEGER REFERENCES claims(id),
    information_item_id  INTEGER UNIQUE REFERENCES information_items(id),
    created_tick         INTEGER NOT NULL CHECK(created_tick >= 0),
    status               TEXT NOT NULL DEFAULT 'published'
                         CHECK(status IN ('published','hidden','removed','deleted')),
    moderation_label     TEXT,
    created_event_id     INTEGER NOT NULL REFERENCES events(id),
    CHECK(parent_entry_id IS NULL OR parent_entry_id <> id),
    CHECK(root_entry_id IS NULL OR root_entry_id <> id),
    CHECK(entry_type='post' OR parent_entry_id IS NOT NULL)
);

CREATE TABLE commons_follows (
    follower_agent_id   INTEGER NOT NULL REFERENCES agents(id),
    followed_agent_id   INTEGER NOT NULL REFERENCES agents(id),
    created_tick        INTEGER NOT NULL CHECK(created_tick >= 0),
    status              TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','unfollowed','blocked')),
    PRIMARY KEY(follower_agent_id, followed_agent_id),
    CHECK(follower_agent_id <> followed_agent_id)
);

CREATE TABLE commons_reactions (
    entry_id            INTEGER NOT NULL REFERENCES commons_entries(id),
    agent_id            INTEGER NOT NULL REFERENCES agents(id),
    reaction            TEXT NOT NULL CHECK(reaction IN ('like','agree','disagree','insightful')),
    created_tick        INTEGER NOT NULL CHECK(created_tick >= 0),
    status              TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','removed')),
    PRIMARY KEY(entry_id, agent_id, reaction)
);

CREATE TABLE commons_feed_policies (
    id                  INTEGER PRIMARY KEY,
    policy_key          TEXT NOT NULL,
    version             INTEGER NOT NULL CHECK(version >= 1),
    algorithm           TEXT NOT NULL CHECK(algorithm IN ('chronological','hot')),
    weights_json        TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(weights_json)),
    created_tick        INTEGER NOT NULL CHECK(created_tick >= 0),
    active              INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
    UNIQUE(policy_key, version)
);

CREATE TABLE commons_feed_impressions (
    id                  INTEGER PRIMARY KEY,
    dedupe_key          TEXT NOT NULL UNIQUE CHECK(length(dedupe_key)=64),
    viewer_agent_id     INTEGER NOT NULL REFERENCES agents(id),
    entry_id            INTEGER NOT NULL REFERENCES commons_entries(id),
    delivered_tick      INTEGER NOT NULL CHECK(delivered_tick >= 0),
    read_tick           INTEGER,
    feed_kind           TEXT NOT NULL CHECK(feed_kind IN ('chronological','hot','community','profile')),
    candidate_set_hash  TEXT NOT NULL CHECK(length(candidate_set_hash)=64),
    score_components_json TEXT NOT NULL CHECK(json_valid(score_components_json)),
    position            INTEGER NOT NULL CHECK(position >= 1),
    policy_id           INTEGER NOT NULL REFERENCES commons_feed_policies(id),
    exposure_id         INTEGER UNIQUE REFERENCES information_exposures(id),
    CHECK(read_tick IS NULL OR read_tick >= delivered_tick),
    UNIQUE(viewer_agent_id, entry_id, delivered_tick, feed_kind, policy_id)
);

CREATE TABLE commons_moderation_actions (
    id                  INTEGER PRIMARY KEY,
    entry_id            INTEGER NOT NULL REFERENCES commons_entries(id),
    moderator_agent_id  INTEGER NOT NULL REFERENCES agents(id),
    action              TEXT NOT NULL CHECK(action IN ('label','hide','remove','restore','limit_author')),
    reason              TEXT NOT NULL CHECK(length(reason) BETWEEN 1 AND 500),
    created_tick        INTEGER NOT NULL CHECK(created_tick >= 0),
    created_event_id    INTEGER NOT NULL REFERENCES events(id),
    status              TEXT NOT NULL DEFAULT 'effective' CHECK(status IN ('effective','reversed'))
);

CREATE TABLE commons_appeals (
    id                  INTEGER PRIMARY KEY,
    moderation_action_id INTEGER NOT NULL REFERENCES commons_moderation_actions(id),
    appellant_agent_id  INTEGER NOT NULL REFERENCES agents(id),
    body_text            TEXT NOT NULL CHECK(length(body_text) BETWEEN 1 AND 1000),
    created_tick         INTEGER NOT NULL CHECK(created_tick >= 0),
    status               TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','upheld','granted','withdrawn')),
    resolved_tick        INTEGER,
    resolver_agent_id    INTEGER REFERENCES agents(id),
    UNIQUE(moderation_action_id, appellant_agent_id)
);

-- Schema 12 intentionally used a closed causal endpoint/relation contract.
-- Rebuild it transactionally so Commons delivery, explicit reads, exposures,
-- and belief effects are first-class Causal Observatory nodes.
DROP INDEX IF EXISTS ix_causal_source;
DROP INDEX IF EXISTS ix_causal_target;
DROP INDEX IF EXISTS ix_causal_created;
DROP INDEX IF EXISTS ix_causal_relation;
ALTER TABLE causal_links RENAME TO causal_links_schema12;

CREATE TABLE causal_links (
    id               INTEGER PRIMARY KEY,
    dedupe_key       TEXT NOT NULL UNIQUE CHECK(length(dedupe_key)=64),
    created_tick     INTEGER NOT NULL CHECK(created_tick >= 0),
    source_kind      TEXT NOT NULL CHECK(source_kind IN
                       ('message','commons_entry','feed_impression','information_exposure',
                        'memory','belief','decision','action_proposal','event',
                        'contract','case','article','ledger_transaction')),
    source_id        TEXT NOT NULL,
    source_tick      INTEGER NOT NULL CHECK(source_tick >= 0),
    source_order_key TEXT NOT NULL,
    target_kind      TEXT NOT NULL CHECK(target_kind IN
                       ('message','commons_entry','feed_impression','information_exposure',
                        'memory','belief','decision','action_proposal','event',
                        'contract','case','article','ledger_transaction')),
    target_id        TEXT NOT NULL,
    target_tick      INTEGER NOT NULL CHECK(target_tick >= 0),
    target_order_key TEXT NOT NULL,
    relation         TEXT NOT NULL CHECK(relation IN
                       ('delivered','observed','cited','motivated','triggered','settled','inferred')),
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

INSERT INTO causal_links(
    id,dedupe_key,created_tick,source_kind,source_id,source_tick,source_order_key,
    target_kind,target_id,target_tick,target_order_key,relation,authority,
    actor_agent_id,confidence,method,model_call_id,provenance_json,evidence_json)
SELECT id,dedupe_key,created_tick,source_kind,source_id,source_tick,source_order_key,
    target_kind,target_id,target_tick,target_order_key,relation,authority,
    actor_agent_id,confidence,method,model_call_id,provenance_json,evidence_json
FROM causal_links_schema12 ORDER BY id;
DROP TABLE causal_links_schema12;

CREATE INDEX ix_causal_source
    ON causal_links(source_kind, source_id, relation, id);
CREATE INDEX ix_causal_target
    ON causal_links(target_kind, target_id, relation, id);
CREATE INDEX ix_causal_created
    ON causal_links(created_tick, id);
CREATE INDEX ix_causal_relation
    ON causal_links(relation, authority, id);

INSERT INTO commons_feed_policies(policy_key,version,algorithm,weights_json,created_tick,active)
VALUES ('chronological',1,'chronological','{"recency":1}',0,1);
INSERT INTO commons_feed_policies(policy_key,version,algorithm,weights_json,created_tick,active)
VALUES ('hot',1,'hot','{"reaction":1000,"reply":500,"recency":-1}',0,1);

CREATE INDEX ix_commons_entries_feed
    ON commons_entries(status, created_tick DESC, id DESC);
CREATE INDEX ix_commons_entries_community
    ON commons_entries(community_id, status, created_tick DESC, id DESC);
CREATE INDEX ix_commons_memberships_agent
    ON commons_memberships(agent_id, status, community_id);
CREATE INDEX ix_commons_follows_target
    ON commons_follows(followed_agent_id, status, follower_agent_id);
CREATE INDEX ix_commons_impressions_viewer
    ON commons_feed_impressions(viewer_agent_id, delivered_tick DESC, id DESC);
CREATE INDEX ix_commons_moderation_entry
    ON commons_moderation_actions(entry_id, created_tick DESC, id DESC);

CREATE TRIGGER commons_impression_delivery_immutable
BEFORE UPDATE ON commons_feed_impressions
WHEN NEW.dedupe_key<>OLD.dedupe_key OR NEW.viewer_agent_id<>OLD.viewer_agent_id
  OR NEW.entry_id<>OLD.entry_id OR NEW.delivered_tick<>OLD.delivered_tick
  OR NEW.feed_kind<>OLD.feed_kind OR NEW.candidate_set_hash<>OLD.candidate_set_hash
  OR NEW.score_components_json<>OLD.score_components_json OR NEW.position<>OLD.position
  OR NEW.policy_id<>OLD.policy_id
BEGIN SELECT RAISE(ABORT, 'commons feed delivery is immutable'); END;
"""


REQUIRED_TABLES = {
    "commons_profiles",
    "commons_communities",
    "commons_memberships",
    "commons_entries",
    "commons_follows",
    "commons_reactions",
    "commons_feed_policies",
    "commons_feed_impressions",
    "commons_moderation_actions",
    "commons_appeals",
}


def verify(conn) -> None:
    tables = {str(row[0]) for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    missing = sorted(REQUIRED_TABLES - tables)
    if missing:
        raise RuntimeError(f"schema 14 missing tables: {','.join(missing)}")
    policies = int(conn.execute(
        "SELECT COUNT(*) FROM commons_feed_policies WHERE active=1").fetchone()[0])
    if policies < 2:
        raise RuntimeError("schema 14 feed policies missing")
    causal_sql = str(conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='causal_links'"
    ).fetchone()[0])
    for token in ("commons_entry", "feed_impression", "information_exposure", "delivered"):
        if token not in causal_sql:
            raise RuntimeError(f"schema 14 causal contract missing {token}")
    if list(conn.execute("PRAGMA foreign_key_check")):
        raise RuntimeError("schema 14 foreign-key verification failed")
