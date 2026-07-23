"""Schema 15: compute subscriptions, learnable skills, and LLM attempt telemetry."""

NAME = "cognition_economy"

SQL = r"""
CREATE TABLE agent_skills (
    agent_id             INTEGER NOT NULL REFERENCES agents(id),
    skill_key            TEXT NOT NULL CHECK(skill_key IN
                         ('household_finance','labor','commerce','entrepreneurship',
                          'finance','law','media','governance')),
    xp                   INTEGER NOT NULL DEFAULT 0 CHECK(xp >= 0),
    level                INTEGER NOT NULL DEFAULT 0 CHECK(level BETWEEN 0 AND 5),
    last_practiced_tick  INTEGER CHECK(last_practiced_tick >= 0),
    source               TEXT NOT NULL CHECK(length(source) BETWEEN 1 AND 120),
    PRIMARY KEY(agent_id, skill_key)
);

CREATE TABLE agent_skill_history (
    id                   INTEGER PRIMARY KEY,
    tick                 INTEGER NOT NULL CHECK(tick >= 0),
    agent_id             INTEGER NOT NULL REFERENCES agents(id),
    skill_key            TEXT NOT NULL CHECK(skill_key IN
                         ('household_finance','labor','commerce','entrepreneurship',
                          'finance','law','media','governance')),
    old_level            INTEGER NOT NULL CHECK(old_level BETWEEN 0 AND 5),
    new_level            INTEGER NOT NULL CHECK(new_level BETWEEN 0 AND 5),
    xp_delta             INTEGER NOT NULL CHECK(xp_delta >= 0),
    new_xp               INTEGER NOT NULL CHECK(new_xp >= 0),
    source               TEXT NOT NULL CHECK(length(source) BETWEEN 1 AND 120)
);

CREATE TABLE compute_subscriptions (
    id                   INTEGER PRIMARY KEY,
    agent_id             INTEGER NOT NULL REFERENCES agents(id),
    tier                 TEXT NOT NULL CHECK(tier IN ('local','flash','premium')),
    payer_type           TEXT NOT NULL CHECK(payer_type IN
                         ('launch_grant','free','agent','firm','government')),
    payer_id             INTEGER,
    payer_account_id     INTEGER REFERENCES accounts(id),
    price_cents          INTEGER NOT NULL DEFAULT 0 CHECK(price_cents >= 0),
    created_tick         INTEGER NOT NULL CHECK(created_tick >= 0),
    effective_tick       INTEGER NOT NULL CHECK(effective_tick >= created_tick),
    expiry_tick          INTEGER NOT NULL CHECK(expiry_tick > effective_tick),
    status               TEXT NOT NULL CHECK(status IN
                         ('pending','active','expired','cancelled')),
    reason               TEXT NOT NULL DEFAULT '' CHECK(length(reason) <= 240)
);

-- Operational telemetry is intentionally excluded from deterministic state
-- hashing. Final successful responses remain authoritative in llm_calls.
CREATE TABLE llm_attempts (
    id                   INTEGER PRIMARY KEY,
    request_key          TEXT,
    llm_call_id          INTEGER REFERENCES llm_calls(id),
    tick                 INTEGER NOT NULL CHECK(tick >= 0),
    phase                TEXT,
    agent_id             INTEGER,
    role                 TEXT,
    purpose              TEXT NOT NULL,
    assigned_tier        TEXT NOT NULL CHECK(assigned_tier IN
                         ('local','flash','premium','legacy')),
    route_reason         TEXT NOT NULL,
    route_index          INTEGER NOT NULL CHECK(route_index BETWEEN 0 AND 1),
    provider             TEXT NOT NULL,
    model                TEXT NOT NULL,
    queue_wait_ms        REAL NOT NULL DEFAULT 0 CHECK(queue_wait_ms >= 0),
    provider_latency_ms  REAL NOT NULL DEFAULT 0 CHECK(provider_latency_ms >= 0),
    active_at_start      INTEGER NOT NULL DEFAULT 0 CHECK(active_at_start >= 0),
    queued_at_start      INTEGER NOT NULL DEFAULT 0 CHECK(queued_at_start >= 0),
    global_active_at_start INTEGER NOT NULL DEFAULT 0 CHECK(global_active_at_start >= 0),
    global_queued_at_start INTEGER NOT NULL DEFAULT 0 CHECK(global_queued_at_start >= 0),
    provider_peak_observed INTEGER NOT NULL DEFAULT 0 CHECK(provider_peak_observed >= 0),
    global_peak_observed INTEGER NOT NULL DEFAULT 0 CHECK(global_peak_observed >= 0),
    outcome              TEXT NOT NULL CHECK(outcome IN
                         ('success','timeout','rate_limited','provider_error','invalid_json','cancelled')),
    error_type           TEXT,
    error_message        TEXT,
    rate_limited         INTEGER NOT NULL DEFAULT 0 CHECK(rate_limited IN (0,1)),
    fallback_used        INTEGER NOT NULL DEFAULT 0 CHECK(fallback_used IN (0,1)),
    created_at           TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Completed simulated-day timings are operational acceptance evidence. They
-- are deliberately kept out of deterministic hashing so exact replay does not
-- depend on host speed or provider latency.
CREATE TABLE runtime_tick_stats (
    tick                 INTEGER PRIMARY KEY CHECK(tick >= 0),
    wall_ms              REAL NOT NULL CHECK(wall_ms >= 0),
    decisions            INTEGER NOT NULL DEFAULT 0 CHECK(decisions >= 0),
    llm_attempts          INTEGER NOT NULL DEFAULT 0 CHECK(llm_attempts >= 0),
    llm_successes         INTEGER NOT NULL DEFAULT 0 CHECK(llm_successes >= 0),
    llm_failures          INTEGER NOT NULL DEFAULT 0 CHECK(llm_failures >= 0),
    fallbacks             INTEGER NOT NULL DEFAULT 0 CHECK(fallbacks >= 0),
    rate_limits           INTEGER NOT NULL DEFAULT 0 CHECK(rate_limits >= 0),
    peak_live_in_flight   INTEGER NOT NULL DEFAULT 0 CHECK(peak_live_in_flight >= 0),
    peak_queue_depth      INTEGER NOT NULL DEFAULT 0 CHECK(peak_queue_depth >= 0),
    created_at            TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX ix_agent_skill_history_agent
    ON agent_skill_history(agent_id, skill_key, tick, id);
CREATE INDEX ix_compute_subscriptions_current
    ON compute_subscriptions(agent_id, status, effective_tick, expiry_tick, id);
CREATE INDEX ix_compute_subscriptions_payer
    ON compute_subscriptions(payer_type, payer_id, status, expiry_tick);
CREATE INDEX ix_llm_attempts_provider_time
    ON llm_attempts(provider, created_at, id);
CREATE INDEX ix_llm_attempts_call
    ON llm_attempts(llm_call_id, id);
CREATE INDEX ix_runtime_tick_stats_created
    ON runtime_tick_stats(created_at, tick);
"""


REQUIRED_TABLES = {
    "agent_skills",
    "agent_skill_history",
    "compute_subscriptions",
    "llm_attempts",
    "runtime_tick_stats",
}


def verify(conn) -> None:
    tables = {str(row[0]) for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    missing = sorted(REQUIRED_TABLES - tables)
    if missing:
        raise RuntimeError(f"schema 15 missing tables: {','.join(missing)}")
    if list(conn.execute("PRAGMA foreign_key_check")):
        raise RuntimeError("schema 15 foreign-key verification failed")
