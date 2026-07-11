"""SQLite schema for a run store.

One SQLite file per run (TECH-SPEC §2, §4). The `events` table is the append-only
spine of the simulation — "anything not in events didn't happen". Money is stored
as integer cents everywhere; a trigger enforces that every transaction's ledger
entries sum to zero (double-entry / conservation of money, PRD R1).
"""

SCHEMA_VERSION = 3

SCHEMA_SQL = r"""
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA synchronous = NORMAL;

-- ─────────────────────────────────────────────────────────────────────────────
-- Run metadata: a single row keyed by id=1 holds live run state (tick, status,
-- PRNG state, governor counters). Config + seed live here for reproducibility.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS run_meta (
    id            INTEGER PRIMARY KEY CHECK (id = 1),
    run_id        TEXT NOT NULL,
    seed          INTEGER NOT NULL,
    schema_version INTEGER NOT NULL,
    config_json   TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'created',   -- created|running|paused|halted|finished
    tick          INTEGER NOT NULL DEFAULT 0,
    phase         TEXT,
    active_tick   INTEGER,
    next_phase    TEXT NOT NULL DEFAULT 'NIGHT_CLOSE',
    phase_state_json TEXT NOT NULL DEFAULT '{}',
    legacy_partial INTEGER NOT NULL DEFAULT 0,
    prng_state    TEXT,                              -- JSON of random.Random.getstate()
    lifecycle_prng_state TEXT,
    governor_json TEXT,                              -- degradation level, spend counters
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    parent_run_id TEXT,                              -- set when forked from a checkpoint
    fork_tick     INTEGER
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Agents & firms
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS agents (
    id             INTEGER PRIMARY KEY,
    name           TEXT NOT NULL,
    kind           TEXT NOT NULL,                    -- citizen|staff|firm_ai
    occupation     TEXT,
    employer_id    INTEGER,                          -- firm id or NULL
    role           TEXT,                             -- institutional role: central_banker|credit_officer|editor|reporter|vc_partner|exchange|teller|oracle|NULL
    age            INTEGER NOT NULL DEFAULT 30,
    health         TEXT NOT NULL DEFAULT 'healthy',  -- healthy|sick|critical
    dependents     INTEGER NOT NULL DEFAULT 0,
    personality_json TEXT,
    political_lean  REAL DEFAULT 0.0,                -- -1 left .. +1 right
    media_diet_json TEXT,                            -- list of outlet ids
    risk_tolerance  REAL DEFAULT 0.5,                -- 0 averse .. 1 seeking
    cadence_json    TEXT,                            -- {shop:1, portfolio:7, career:30}
    model_tier      TEXT DEFAULT 'citizen',          -- citizen|strong
    alive           INTEGER NOT NULL DEFAULT 1,
    retired         INTEGER NOT NULL DEFAULT 0,
    died_tick       INTEGER,
    arrived_tick    INTEGER NOT NULL DEFAULT 0,
    sick_since_tick INTEGER,
    checking_account_id INTEGER,                     -- convenience pointer to primary account
    savings_account_id  INTEGER
);
CREATE INDEX IF NOT EXISTS ix_agents_alive ON agents(alive);
CREATE INDEX IF NOT EXISTS ix_agents_employer ON agents(employer_id);

CREATE TABLE IF NOT EXISTS firms (
    id             INTEGER PRIMARY KEY,
    name           TEXT NOT NULL,
    sector         TEXT,
    founder_agent_id INTEGER,
    status         TEXT NOT NULL DEFAULT 'private',  -- private|listed|bankrupt
    product_json   TEXT,                             -- {product, unit_price_cents, input_cost_cents, labor_per_unit}
    account_id     INTEGER,                          -- firm operating account
    founded_tick   INTEGER NOT NULL DEFAULT 0,
    listed_tick    INTEGER,
    bankrupt_tick  INTEGER,
    shares_outstanding INTEGER NOT NULL DEFAULT 0,
    inventory      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS banks (
    id             INTEGER PRIMARY KEY,
    name           TEXT NOT NULL,
    reserve_account_id INTEGER,
    equity_account_id  INTEGER,
    risk_policy_json TEXT,                           -- max_ltv, min_rate_bps, ...
    reserve_requirement_bps INTEGER NOT NULL DEFAULT 1000,  -- 10%
    status         TEXT NOT NULL DEFAULT 'open',     -- open|failed
    failed_tick    INTEGER
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Ledger (double-entry, integer cents). accounts + ledger_entries.
-- balance_cents is a materialised running balance; it MUST equal the sum of the
-- account's ledger deltas (checked every tick by reconciliation).
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS accounts (
    id            INTEGER PRIMARY KEY,
    owner_type    TEXT NOT NULL,                     -- agent|firm|bank|gov|central_bank|system
    owner_id      INTEGER,
    bank_id       INTEGER,                           -- which bank holds this deposit (NULL for reserve/system)
    kind          TEXT NOT NULL,                     -- checking|savings|reserve|equity|inflow|external|loss|gov
    label         TEXT,
    balance_cents INTEGER NOT NULL DEFAULT 0,
    is_external   INTEGER NOT NULL DEFAULT 0         -- money "outside" the household/firm circulation (endowment/commodity/void)
);
CREATE INDEX IF NOT EXISTS ix_accounts_owner ON accounts(owner_type, owner_id);
CREATE INDEX IF NOT EXISTS ix_accounts_bank ON accounts(bank_id);

CREATE TABLE IF NOT EXISTS transactions (
    id      INTEGER PRIMARY KEY,
    tick    INTEGER NOT NULL,
    kind    TEXT NOT NULL,
    memo    TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS ledger_entries (
    id                 INTEGER PRIMARY KEY,
    tick               INTEGER NOT NULL,
    txn_id             INTEGER NOT NULL,
    account_id         INTEGER NOT NULL,
    delta_cents        INTEGER NOT NULL,
    counter_account_id INTEGER,
    memo               TEXT,
    FOREIGN KEY (txn_id) REFERENCES transactions(id)
);
CREATE INDEX IF NOT EXISTS ix_ledger_account ON ledger_entries(account_id);
CREATE INDEX IF NOT EXISTS ix_ledger_txn ON ledger_entries(txn_id);
CREATE INDEX IF NOT EXISTS ix_ledger_tick ON ledger_entries(tick);

-- ─────────────────────────────────────────────────────────────────────────────
-- Credit
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS loans (
    id           INTEGER PRIMARY KEY,
    bank_id      INTEGER NOT NULL,
    borrower_type TEXT NOT NULL,                     -- agent|firm
    borrower_id  INTEGER NOT NULL,
    principal_cents INTEGER NOT NULL,
    outstanding_cents INTEGER NOT NULL,
    rate_bps     INTEGER NOT NULL,
    term_ticks   INTEGER NOT NULL,
    origin_tick  INTEGER NOT NULL,
    payment_cents INTEGER NOT NULL,                  -- per scheduled payment
    payment_interval_ticks INTEGER NOT NULL DEFAULT 30,
    next_due_tick INTEGER NOT NULL,
    missed_payments INTEGER NOT NULL DEFAULT 0,
    collateral_json TEXT,
    purpose      TEXT,
    status       TEXT NOT NULL DEFAULT 'active'      -- active|paid|default
);
CREATE INDEX IF NOT EXISTS ix_loans_borrower ON loans(borrower_type, borrower_id);
CREATE INDEX IF NOT EXISTS ix_loans_status ON loans(status);

-- ─────────────────────────────────────────────────────────────────────────────
-- Equity / exchange
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS loan_applications (
    id           INTEGER PRIMARY KEY,
    tick         INTEGER NOT NULL,
    bank_id      INTEGER NOT NULL,
    borrower_type TEXT NOT NULL,
    borrower_id  INTEGER NOT NULL,
    amount_cents INTEGER NOT NULL,
    purpose      TEXT,
    collateral_json TEXT,
    status       TEXT NOT NULL DEFAULT 'pending',    -- pending|approved|denied|expired
    decided_tick INTEGER,
    rate_bps     INTEGER,
    term_ticks   INTEGER,
    loan_id      INTEGER
);
CREATE INDEX IF NOT EXISTS ix_loanapp_bank ON loan_applications(bank_id, status);

CREATE TABLE IF NOT EXISTS shares (
    id        INTEGER PRIMARY KEY,
    firm_id   INTEGER NOT NULL,
    holder_type TEXT NOT NULL,                       -- agent|firm|system
    holder_id INTEGER NOT NULL,
    qty       INTEGER NOT NULL,
    UNIQUE (firm_id, holder_type, holder_id)
);
CREATE INDEX IF NOT EXISTS ix_shares_holder ON shares(holder_type, holder_id);

CREATE TABLE IF NOT EXISTS orders (
    id            INTEGER PRIMARY KEY,
    tick          INTEGER NOT NULL,
    agent_id      INTEGER NOT NULL,
    firm_id       INTEGER NOT NULL,
    side          TEXT NOT NULL,                     -- buy|sell
    order_type    TEXT NOT NULL DEFAULT 'limit',     -- limit|market
    qty           INTEGER NOT NULL,
    qty_remaining INTEGER NOT NULL,
    limit_price_cents INTEGER,
    seq           INTEGER NOT NULL,                  -- deterministic time priority
    status        TEXT NOT NULL DEFAULT 'open'       -- open|filled|partial|cancelled|expired
);
CREATE INDEX IF NOT EXISTS ix_orders_book ON orders(firm_id, side, status);

CREATE TABLE IF NOT EXISTS trades (
    id           INTEGER PRIMARY KEY,
    tick         INTEGER NOT NULL,
    firm_id      INTEGER NOT NULL,
    buy_order_id INTEGER NOT NULL,
    sell_order_id INTEGER NOT NULL,
    buyer_id     INTEGER NOT NULL,
    seller_id    INTEGER NOT NULL,
    qty          INTEGER NOT NULL,
    price_cents  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_trades_firm ON trades(firm_id, tick);

-- ─────────────────────────────────────────────────────────────────────────────
-- VC / private funding (P1 R13): pitch → term sheet → equity → follow-on/write-off
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS pitches (
    id               INTEGER PRIMARY KEY,
    tick             INTEGER NOT NULL,
    firm_id          INTEGER NOT NULL,
    founder_agent_id INTEGER NOT NULL,
    ask_cents        INTEGER NOT NULL,
    summary          TEXT,
    status           TEXT NOT NULL DEFAULT 'pending', -- pending|funded|declined|expired|written_off
    decided_tick     INTEGER,
    vc_agent_id      INTEGER,
    invested_cents   INTEGER,
    equity_bps       INTEGER,
    shares_issued    INTEGER,
    term_sheet_json  TEXT,
    follow_on        INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_pitches_status ON pitches(status);

-- ─────────────────────────────────────────────────────────────────────────────
-- Health insurance (P1 R17): premium-funded coverage of medical costs
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS insurance_policies (
    id                INTEGER PRIMARY KEY,
    agent_id          INTEGER NOT NULL,
    insurer_firm_id   INTEGER NOT NULL,
    premium_cents     INTEGER NOT NULL,
    coverage_bps      INTEGER NOT NULL,
    start_tick        INTEGER NOT NULL,
    next_premium_tick INTEGER NOT NULL,
    premium_interval_ticks INTEGER NOT NULL DEFAULT 30,
    status            TEXT NOT NULL DEFAULT 'active',  -- active|lapsed|cancelled
    end_tick          INTEGER
);
CREATE INDEX IF NOT EXISTS ix_policies_agent ON insurance_policies(agent_id, status);

-- ─────────────────────────────────────────────────────────────────────────────
-- Labor
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS jobs (
    id         INTEGER PRIMARY KEY,
    tick       INTEGER NOT NULL,
    firm_id    INTEGER NOT NULL,
    title      TEXT NOT NULL,
    wage_cents INTEGER NOT NULL,
    status     TEXT NOT NULL DEFAULT 'open'          -- open|filled|closed
);

CREATE TABLE IF NOT EXISTS applications (
    id      INTEGER PRIMARY KEY,
    tick    INTEGER NOT NULL,
    job_id  INTEGER NOT NULL,
    agent_id INTEGER NOT NULL,
    state   TEXT NOT NULL DEFAULT 'pending'          -- pending|hired|rejected|withdrawn
);

CREATE TABLE IF NOT EXISTS employments (
    id        INTEGER PRIMARY KEY,
    firm_id   INTEGER NOT NULL,
    agent_id  INTEGER NOT NULL,
    title     TEXT,
    wage_cents INTEGER NOT NULL,
    start_tick INTEGER NOT NULL,
    end_tick  INTEGER,
    status    TEXT NOT NULL DEFAULT 'active',        -- active|ended
    pay_interval_ticks INTEGER NOT NULL DEFAULT 30,
    next_pay_tick INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_emp_agent ON employments(agent_id, status);
CREATE INDEX IF NOT EXISTS ix_emp_firm ON employments(firm_id, status);

-- ─────────────────────────────────────────────────────────────────────────────
-- Cognition: memory, beliefs, social graph
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS memories (
    id            INTEGER PRIMARY KEY,
    agent_id      INTEGER NOT NULL,
    tick          INTEGER NOT NULL,
    kind          TEXT NOT NULL,                     -- observation|summary|belief
    text          TEXT NOT NULL,
    importance    REAL NOT NULL DEFAULT 1.0,
    entities_json TEXT,                              -- entity keys for keyword retrieval
    last_accessed_tick INTEGER NOT NULL DEFAULT 0,
    demoted       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_mem_agent ON memories(agent_id, kind);

CREATE TABLE IF NOT EXISTS beliefs (
    id          INTEGER PRIMARY KEY,
    agent_id    INTEGER NOT NULL,
    key         TEXT NOT NULL,                       -- 'trust:bank:2', 'inflation_expectation', 'sentiment'
    value       REAL NOT NULL,
    updated_tick INTEGER NOT NULL,
    UNIQUE (agent_id, key)
);
CREATE INDEX IF NOT EXISTS ix_beliefs_key ON beliefs(key);

CREATE TABLE IF NOT EXISTS social_ties (
    id       INTEGER PRIMARY KEY,
    agent_a  INTEGER NOT NULL,
    agent_b  INTEGER NOT NULL,
    weight   REAL NOT NULL DEFAULT 0.5,
    UNIQUE (agent_a, agent_b)
);
CREATE INDEX IF NOT EXISTS ix_ties_a ON social_ties(agent_a);

-- ─────────────────────────────────────────────────────────────────────────────
-- Information layer
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS news_articles (
    id            INTEGER PRIMARY KEY,
    tick          INTEGER NOT NULL,
    outlet_id     INTEGER NOT NULL,
    outlet_name   TEXT,
    headline      TEXT NOT NULL,
    body          TEXT NOT NULL,
    slant_tags    TEXT,
    source_event_ids TEXT,                           -- JSON list for the distortion index
    tone          REAL NOT NULL DEFAULT 0.0,         -- -1 negative .. +1 positive (belief channel)
    truthful      INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS ix_news_tick ON news_articles(tick);

CREATE TABLE IF NOT EXISTS conversations (
    id            INTEGER PRIMARY KEY,
    tick          INTEGER NOT NULL,
    participant_ids TEXT NOT NULL,                   -- JSON [a,b]
    topic         TEXT
);
CREATE TABLE IF NOT EXISTS messages (
    id       INTEGER PRIMARY KEY,
    conv_id  INTEGER NOT NULL,
    tick     INTEGER NOT NULL,
    agent_id INTEGER NOT NULL,
    text     TEXT NOT NULL,
    seq      INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_msg_conv ON messages(conv_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- Event spine + metrics
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS events (
    id           INTEGER PRIMARY KEY,
    tick         INTEGER NOT NULL,
    phase        TEXT,
    kind         TEXT NOT NULL,
    subject_type TEXT,
    subject_id   INTEGER,
    importance   REAL NOT NULL DEFAULT 1.0,
    payload_json TEXT,
    created_at   TEXT
);
CREATE INDEX IF NOT EXISTS ix_events_tick ON events(tick);
CREATE INDEX IF NOT EXISTS ix_events_kind ON events(kind);

CREATE TABLE IF NOT EXISTS metrics (
    id    INTEGER PRIMARY KEY,
    tick  INTEGER NOT NULL,
    name  TEXT NOT NULL,
    value REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_metrics_tick ON metrics(tick);
CREATE INDEX IF NOT EXISTS ix_metrics_name ON metrics(name);

-- ─────────────────────────────────────────────────────────────────────────────
-- Oracle
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS predictions (
    id             INTEGER PRIMARY KEY,
    asked_tick     INTEGER NOT NULL,
    question       TEXT NOT NULL,
    p              REAL,
    reasoning      TEXT,
    drivers_json   TEXT,
    confidence     TEXT,
    resolution_rule_json TEXT,
    deadline_tick  INTEGER,
    resolved_tick  INTEGER,
    outcome        INTEGER,                          -- 0/1/NULL
    brier          REAL,
    status         TEXT NOT NULL DEFAULT 'open'      -- open|resolved|insufficient_data
);

-- ─────────────────────────────────────────────────────────────────────────────
-- LLM call log (powers inspector, replay, prompt debugging) + cost accounting
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS llm_calls (
    id           INTEGER PRIMARY KEY,
    tick         INTEGER NOT NULL,
    agent_id     INTEGER,
    role         TEXT,
    provider     TEXT,
    model        TEXT,
    purpose      TEXT,                               -- decision|conversation|memory|newsroom|oracle|persona
    cache_key    TEXT,
    request_json TEXT,
    response_json TEXT,
    in_tokens    INTEGER NOT NULL DEFAULT 0,
    out_tokens   INTEGER NOT NULL DEFAULT 0,
    cached       INTEGER NOT NULL DEFAULT 0,
    cost_usd     REAL NOT NULL DEFAULT 0.0,
    latency_ms   INTEGER,
    created_at   TEXT
);
CREATE INDEX IF NOT EXISTS ix_llm_tick ON llm_calls(tick);
CREATE INDEX IF NOT EXISTS ix_llm_cache ON llm_calls(cache_key);

-- ─────────────────────────────────────────────────────────────────────────────
-- Control plane: checkpoints + shocks
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS checkpoints (
    id         INTEGER PRIMARY KEY,
    tick       INTEGER NOT NULL,
    path       TEXT NOT NULL,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS shocks (
    id            INTEGER PRIMARY KEY,
    kind          TEXT NOT NULL,                     -- policy_rate|oil|rumor|slant|scandal
    trigger_type  TEXT NOT NULL,                     -- shock|trend|conditional
    trigger_json  TEXT,                              -- {tick:N} | {start,duration} | {metric,op,threshold}
    duration_ticks INTEGER NOT NULL DEFAULT 0,
    params_json   TEXT,
    label         TEXT,
    fired         INTEGER NOT NULL DEFAULT 0,
    fired_tick    INTEGER,
    active_until_tick INTEGER
);
"""


def initialize_schema(conn) -> None:
    """Create all tables on a fresh connection (idempotent)."""
    conn.executescript(SCHEMA_SQL)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(run_meta)")}
    additions = {
        "active_tick": "INTEGER",
        "next_phase": "TEXT NOT NULL DEFAULT 'NIGHT_CLOSE'",
        "phase_state_json": "TEXT NOT NULL DEFAULT '{}'",
        "legacy_partial": "INTEGER NOT NULL DEFAULT 0",
    }
    migrated = False
    for name, declaration in additions.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE run_meta ADD COLUMN {name} {declaration}")
            migrated = True
    if migrated:
        _migrate_legacy_progress(conn)
    conn.execute(
        "UPDATE run_meta SET schema_version=? WHERE id=1 AND schema_version<?",
        (SCHEMA_VERSION, SCHEMA_VERSION))
    conn.commit()


def _migrate_legacy_progress(conn) -> None:
    """Flag old provider/budget pauses whose stored tick may be incomplete."""
    row = conn.execute(
        "SELECT tick, phase, status FROM run_meta WHERE id=1").fetchone()
    if not row or row[2] != "paused" or not row[0]:
        return
    pause = conn.execute(
        "SELECT kind, payload_json FROM events "
        "WHERE tick=? AND kind IN ('provider_pause','budget_pause') "
        "ORDER BY id DESC LIMIT 1", (int(row[0]),)).fetchone()
    if not pause:
        return
    import json
    payload = json.loads(pause[1] or "{}")
    phase = str(payload.get("phase") or row[1] or "NIGHT_CLOSE")
    next_phase = "MORNING" if pause[0] == "budget_pause" and phase == "NIGHT_CLOSE" else phase
    conn.execute(
        "UPDATE run_meta SET tick=?, active_tick=?, next_phase=?, "
        "phase_state_json='{}', legacy_partial=1 WHERE id=1",
        (max(0, int(row[0]) - 1), int(row[0]), next_phase))
