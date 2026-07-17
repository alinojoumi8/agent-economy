"""SQLite schema for a run store.

One SQLite file per run (TECH-SPEC §2, §4). The `events` table is the append-only
spine of the simulation — "anything not in events didn't happen". Money is stored
as integer cents everywhere; Ledger.post rejects unbalanced batches before
insertion and tick reconciliation independently verifies every account (PRD R1).
"""

SCHEMA_VERSION = 11


class SchemaCompatibilityError(RuntimeError):
    """Raised when a run database requires a newer engine schema."""


def _existing_schema_version(conn) -> int | None:
    """Read an existing run's schema marker without changing the database."""
    table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='run_meta'"
    ).fetchone()
    if table is None:
        return None
    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(run_meta)")}
    if "schema_version" not in columns:
        return None
    row = conn.execute("SELECT schema_version FROM run_meta WHERE id=1").fetchone()
    if row is None:
        return None
    raw_version = row[0]
    try:
        version = int(raw_version)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SchemaCompatibilityError(
            f"run database has invalid schema_version {raw_version!r}") from exc
    if isinstance(raw_version, bool) or (
            isinstance(raw_version, float) and raw_version != version):
        raise SchemaCompatibilityError(
            f"run database has invalid schema_version {raw_version!r}")
    return version


def assert_schema_compatible(conn) -> None:
    """Reject future databases before any migration or cache rebuild runs."""
    stored_version = _existing_schema_version(conn)
    if stored_version is not None and stored_version > SCHEMA_VERSION:
        raise SchemaCompatibilityError(
            f"run database schema v{stored_version} is newer than this binary's "
            f"supported schema v{SCHEMA_VERSION}")


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
    participant_influenced INTEGER NOT NULL DEFAULT 0,
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
    status           TEXT NOT NULL DEFAULT 'pending', -- pending|term_sheeted|funded|declined|expired|written_off
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
    evidence_json  TEXT NOT NULL DEFAULT '[]',
    status         TEXT NOT NULL DEFAULT 'open'      -- open|resolved|insufficient_data
);

CREATE TABLE IF NOT EXISTS acceptance_checkpoints (
    id             INTEGER PRIMARY KEY,
    scheduled_tick INTEGER NOT NULL,
    question       TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'pending', -- pending|completed|missed
    prediction_id  INTEGER,
    detail         TEXT,
    completed_at   TEXT,
    UNIQUE (scheduled_tick, question)
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

CREATE TABLE IF NOT EXISTS participant_control (
    id            INTEGER PRIMARY KEY CHECK (id = 1),
    agent_id      INTEGER,
    active        INTEGER NOT NULL DEFAULT 0,
    acquired_tick INTEGER,
    updated_at    TEXT
);

CREATE TABLE IF NOT EXISTS participant_actions (
    id             INTEGER PRIMARY KEY,
    agent_id       INTEGER NOT NULL,
    target_tick    INTEGER NOT NULL,
    action_json    TEXT NOT NULL,
    reasoning      TEXT,
    status         TEXT NOT NULL DEFAULT 'queued', -- queued|executed|rejected|cancelled
    result_json    TEXT,
    source_action_id INTEGER,
    created_at     TEXT,
    executed_at    TEXT,
    UNIQUE (agent_id, target_tick)
);
CREATE INDEX IF NOT EXISTS ix_participant_actions_tick
    ON participant_actions(target_tick, status);

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


MIGRATION_6_SQL = r"""
-- Agent Economy v2 legal-institutional kernel.
CREATE TABLE IF NOT EXISTS legal_rulesets (
    id              INTEGER PRIMARY KEY,
    ruleset_key     TEXT NOT NULL,
    version         TEXT NOT NULL,
    jurisdiction    TEXT NOT NULL,
    effective_tick  INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'active',
    rules_json      TEXT NOT NULL,
    sources_json    TEXT NOT NULL DEFAULT '[]',
    disclaimer      TEXT NOT NULL,
    UNIQUE (ruleset_key, version)
);

CREATE TABLE IF NOT EXISTS contracts (
    id                  INTEGER PRIMARY KEY,
    contract_type       TEXT NOT NULL,
    title               TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'offered',
    jurisdiction        TEXT NOT NULL,
    ruleset_key         TEXT NOT NULL,
    version             INTEGER NOT NULL DEFAULT 1,
    parent_contract_id  INTEGER,
    drafter_agent_id    INTEGER NOT NULL,
    offered_tick        INTEGER NOT NULL,
    executed_tick       INTEGER,
    effective_tick      INTEGER,
    expiry_tick         INTEGER,
    terminated_tick     INTEGER,
    prose               TEXT NOT NULL DEFAULT '',
    metadata_json       TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_contracts_status ON contracts(status);
CREATE INDEX IF NOT EXISTS ix_contracts_parent ON contracts(parent_contract_id);

CREATE TABLE IF NOT EXISTS contract_parties (
    id          INTEGER PRIMARY KEY,
    contract_id INTEGER NOT NULL,
    party_type  TEXT NOT NULL,
    party_id    INTEGER NOT NULL,
    role        TEXT NOT NULL,
    UNIQUE (contract_id, party_type, party_id)
);
CREATE INDEX IF NOT EXISTS ix_contract_parties_party
    ON contract_parties(party_type, party_id);

CREATE TABLE IF NOT EXISTS contract_clauses (
    id          INTEGER PRIMARY KEY,
    contract_id INTEGER NOT NULL,
    clause_key  TEXT NOT NULL,
    clause_type TEXT NOT NULL,
    ordinal     INTEGER NOT NULL,
    terms_json  TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'active',
    UNIQUE (contract_id, clause_key)
);

CREATE TABLE IF NOT EXISTS contract_acceptances (
    id          INTEGER PRIMARY KEY,
    contract_id INTEGER NOT NULL,
    party_type  TEXT NOT NULL,
    party_id    INTEGER NOT NULL,
    accepted_tick INTEGER NOT NULL,
    actor_id    INTEGER NOT NULL,
    UNIQUE (contract_id, party_type, party_id)
);

CREATE TABLE IF NOT EXISTS obligations (
    id              INTEGER PRIMARY KEY,
    contract_id     INTEGER NOT NULL,
    clause_id       INTEGER NOT NULL,
    obligation_type TEXT NOT NULL,
    obligor_type    TEXT NOT NULL,
    obligor_id      INTEGER NOT NULL,
    obligee_type    TEXT NOT NULL,
    obligee_id      INTEGER NOT NULL,
    due_tick        INTEGER NOT NULL,
    grace_ticks     INTEGER NOT NULL DEFAULT 0,
    amount_cents    INTEGER,
    currency_code   TEXT NOT NULL DEFAULT 'USD',
    terms_json      TEXT NOT NULL DEFAULT '{}',
    status          TEXT NOT NULL DEFAULT 'pending',
    performed_tick  INTEGER,
    breached_tick   INTEGER,
    transaction_id  INTEGER
);
CREATE INDEX IF NOT EXISTS ix_obligations_due ON obligations(status, due_tick);
CREATE INDEX IF NOT EXISTS ix_obligations_contract ON obligations(contract_id);

CREATE TABLE IF NOT EXISTS legal_notices (
    id              INTEGER PRIMARY KEY,
    contract_id     INTEGER,
    matter_id       INTEGER,
    sender_type     TEXT NOT NULL,
    sender_id       INTEGER NOT NULL,
    recipient_type  TEXT NOT NULL,
    recipient_id    INTEGER NOT NULL,
    notice_type     TEXT NOT NULL,
    tick            INTEGER NOT NULL,
    detail          TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS legal_matters (
    id                  INTEGER PRIMARY KEY,
    matter_type         TEXT NOT NULL,
    venue               TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'filed',
    contract_id         INTEGER,
    claimant_type       TEXT NOT NULL,
    claimant_id         INTEGER NOT NULL,
    respondent_type     TEXT NOT NULL,
    respondent_id       INTEGER NOT NULL,
    claim_type          TEXT NOT NULL,
    filed_tick          INTEGER NOT NULL,
    response_due_tick   INTEGER NOT NULL,
    resolved_tick       INTEGER,
    counsel_agent_id    INTEGER,
    requested_remedy_json TEXT NOT NULL DEFAULT '{}',
    settlement_json     TEXT,
    metadata_json       TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_legal_matters_status ON legal_matters(status);

CREATE TABLE IF NOT EXISTS legal_filings (
    id                  INTEGER PRIMARY KEY,
    matter_id           INTEGER NOT NULL,
    tick                INTEGER NOT NULL,
    filer_type          TEXT NOT NULL,
    filer_id            INTEGER NOT NULL,
    filing_type         TEXT NOT NULL,
    body                TEXT NOT NULL DEFAULT '',
    evidence_event_ids_json TEXT NOT NULL DEFAULT '[]',
    admitted            INTEGER NOT NULL DEFAULT 0,
    model_call_id       INTEGER,
    rationale_summary   TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_legal_filings_matter ON legal_filings(matter_id);

CREATE TABLE IF NOT EXISTS legal_decisions (
    id                  INTEGER PRIMARY KEY,
    matter_id           INTEGER NOT NULL,
    tick                INTEGER NOT NULL,
    decision_maker_id   INTEGER NOT NULL,
    outcome             TEXT NOT NULL,
    findings_json       TEXT NOT NULL,
    evidence_event_ids_json TEXT NOT NULL DEFAULT '[]',
    remedy_json         TEXT NOT NULL DEFAULT '{}',
    validation_status   TEXT NOT NULL,
    validation_errors_json TEXT NOT NULL DEFAULT '[]',
    model_call_id       INTEGER,
    rationale_summary   TEXT NOT NULL DEFAULT '',
    enforcement_event_id INTEGER,
    UNIQUE (matter_id)
);

CREATE TABLE IF NOT EXISTS legal_restrictions (
    id              INTEGER PRIMARY KEY,
    matter_id       INTEGER NOT NULL,
    subject_type    TEXT NOT NULL,
    subject_id      INTEGER NOT NULL,
    restriction_type TEXT NOT NULL,
    params_json     TEXT NOT NULL DEFAULT '{}',
    effective_tick  INTEGER NOT NULL,
    expiry_tick     INTEGER,
    status          TEXT NOT NULL DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS action_proposals (
    id                  INTEGER PRIMARY KEY,
    tick                INTEGER NOT NULL,
    actor_id            INTEGER NOT NULL,
    action_type         TEXT NOT NULL,
    payload_json        TEXT NOT NULL,
    evidence_event_ids_json TEXT NOT NULL DEFAULT '[]',
    model_call_id       INTEGER,
    rationale_summary   TEXT NOT NULL DEFAULT '',
    validation_status   TEXT NOT NULL DEFAULT 'pending',
    result_json         TEXT
);
CREATE INDEX IF NOT EXISTS ix_action_proposals_tick ON action_proposals(tick, actor_id);
"""


MIGRATION_7_SQL = r"""
-- Typed startup funding, diligence, intellectual property, disclosures, and M&A.
CREATE TABLE IF NOT EXISTS term_sheets (
    id                  INTEGER PRIMARY KEY,
    tick                INTEGER NOT NULL,
    firm_id             INTEGER NOT NULL,
    proposer_agent_id   INTEGER NOT NULL,
    investor_agent_id   INTEGER NOT NULL,
    instrument_type     TEXT NOT NULL,
    amount_cents        INTEGER NOT NULL,
    currency_code       TEXT NOT NULL DEFAULT 'USD',
    pre_money_cents     INTEGER,
    valuation_cap_cents INTEGER,
    discount_bps        INTEGER,
    equity_bps          INTEGER,
    liquidation_preference_bps INTEGER NOT NULL DEFAULT 10000,
    pro_rata            INTEGER NOT NULL DEFAULT 0,
    board_seat          INTEGER NOT NULL DEFAULT 0,
    status              TEXT NOT NULL DEFAULT 'offered',
    founder_accepted_tick INTEGER,
    investor_accepted_tick INTEGER,
    contract_id         INTEGER,
    metadata_json       TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_term_sheets_firm ON term_sheets(firm_id, status);

CREATE TABLE IF NOT EXISTS due_diligence_checks (
    id              INTEGER PRIMARY KEY,
    tick            INTEGER NOT NULL,
    firm_id         INTEGER NOT NULL,
    term_sheet_id   INTEGER,
    reviewer_agent_id INTEGER NOT NULL,
    scope           TEXT NOT NULL,
    status          TEXT NOT NULL,
    findings_json   TEXT NOT NULL,
    source_ids_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS funding_rounds (
    id              INTEGER PRIMARY KEY,
    tick            INTEGER NOT NULL,
    firm_id         INTEGER NOT NULL,
    term_sheet_id   INTEGER NOT NULL,
    investor_agent_id INTEGER NOT NULL,
    round_type      TEXT NOT NULL,
    amount_cents    INTEGER NOT NULL,
    currency_code   TEXT NOT NULL DEFAULT 'USD',
    shares_issued   INTEGER NOT NULL,
    pre_money_cents INTEGER,
    post_money_cents INTEGER,
    transaction_id  INTEGER NOT NULL,
    status          TEXT NOT NULL DEFAULT 'closed'
);

CREATE TABLE IF NOT EXISTS ip_assets (
    id              INTEGER PRIMARY KEY,
    firm_id         INTEGER NOT NULL,
    creator_agent_id INTEGER,
    counsel_agent_id INTEGER,
    asset_type      TEXT NOT NULL,
    title           TEXT NOT NULL,
    scope           TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'registered',
    registered_tick INTEGER NOT NULL,
    valuation_cents INTEGER NOT NULL DEFAULT 0,
    metadata_json   TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_ip_assets_firm ON ip_assets(firm_id, status);

CREATE TABLE IF NOT EXISTS ip_licenses (
    id              INTEGER PRIMARY KEY,
    ip_asset_id     INTEGER NOT NULL,
    licensor_firm_id INTEGER NOT NULL,
    licensee_firm_id INTEGER NOT NULL,
    contract_id     INTEGER,
    start_tick      INTEGER NOT NULL,
    expiry_tick     INTEGER,
    royalty_bps     INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS firm_disclosures (
    id              INTEGER PRIMARY KEY,
    tick            INTEGER NOT NULL,
    firm_id         INTEGER NOT NULL,
    disclosure_type TEXT NOT NULL,
    period_start_tick INTEGER NOT NULL,
    period_end_tick INTEGER NOT NULL,
    facts_json      TEXT NOT NULL,
    source_event_ids_json TEXT NOT NULL DEFAULT '[]',
    published_by_agent_id INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_disclosures_firm ON firm_disclosures(firm_id, tick);

CREATE TABLE IF NOT EXISTS mergers (
    id              INTEGER PRIMARY KEY,
    proposed_tick   INTEGER NOT NULL,
    acquirer_firm_id INTEGER NOT NULL,
    target_firm_id  INTEGER NOT NULL,
    proposer_agent_id INTEGER NOT NULL,
    consideration_type TEXT NOT NULL DEFAULT 'cash',
    price_cents     INTEGER NOT NULL,
    currency_code   TEXT NOT NULL DEFAULT 'USD',
    status          TEXT NOT NULL DEFAULT 'proposed',
    target_approved_tick INTEGER,
    regulator_notified_tick INTEGER,
    closed_tick     INTEGER,
    terminated_tick INTEGER,
    agreement_contract_id INTEGER,
    metadata_json   TEXT NOT NULL DEFAULT '{}',
    UNIQUE (acquirer_firm_id, target_firm_id, status)
);

CREATE TABLE IF NOT EXISTS merger_reviews (
    id              INTEGER PRIMARY KEY,
    merger_id       INTEGER NOT NULL,
    tick            INTEGER NOT NULL,
    regulator_agent_id INTEGER NOT NULL,
    lookback_ticks  INTEGER NOT NULL DEFAULT 30,
    pre_hhi         REAL NOT NULL,
    post_hhi        REAL NOT NULL,
    delta_hhi       REAL NOT NULL,
    threshold_hhi   REAL NOT NULL,
    threshold_delta REAL NOT NULL,
    outcome         TEXT NOT NULL,
    remedy_json     TEXT NOT NULL DEFAULT '{}',
    rationale_summary TEXT NOT NULL DEFAULT '',
    UNIQUE (merger_id)
);

CREATE TABLE IF NOT EXISTS trader_profiles (
    agent_id        INTEGER PRIMARY KEY,
    archetype       TEXT NOT NULL,
    horizon_ticks   INTEGER NOT NULL,
    risk_budget_bps INTEGER NOT NULL,
    sentiment_weight REAL NOT NULL DEFAULT 0.0,
    fundamentals_weight REAL NOT NULL DEFAULT 0.0,
    momentum_weight REAL NOT NULL DEFAULT 0.0,
    updated_tick    INTEGER NOT NULL DEFAULT 0
);
"""


MIGRATION_8_SQL = r"""
-- Narrative information economy.
CREATE TABLE IF NOT EXISTS claims (
    id                  INTEGER PRIMARY KEY,
    tick                INTEGER NOT NULL,
    claim_key           TEXT NOT NULL,
    subject_type        TEXT NOT NULL,
    subject_id          INTEGER,
    predicate           TEXT NOT NULL,
    value_json          TEXT NOT NULL,
    truth_status        TEXT NOT NULL,
    source_event_ids_json TEXT NOT NULL DEFAULT '[]',
    creator_agent_id    INTEGER,
    correction_of_claim_id INTEGER
);
CREATE INDEX IF NOT EXISTS ix_claims_subject ON claims(subject_type, subject_id, tick);

CREATE TABLE IF NOT EXISTS information_items (
    id                  INTEGER PRIMARY KEY,
    tick                INTEGER NOT NULL,
    item_type           TEXT NOT NULL,
    author_agent_id     INTEGER,
    outlet_id           INTEGER,
    claim_id            INTEGER NOT NULL,
    parent_item_id      INTEGER,
    news_article_id     INTEGER,
    body                TEXT NOT NULL,
    slant               REAL NOT NULL DEFAULT 0.0,
    tone                REAL NOT NULL DEFAULT 0.0,
    distortion          REAL NOT NULL DEFAULT 0.0,
    novelty             REAL NOT NULL DEFAULT 0.5,
    virality            REAL NOT NULL DEFAULT 0.0,
    source_event_ids_json TEXT NOT NULL DEFAULT '[]',
    status              TEXT NOT NULL DEFAULT 'published'
);
CREATE INDEX IF NOT EXISTS ix_information_items_tick ON information_items(tick, item_type);

CREATE TABLE IF NOT EXISTS information_exposures (
    id                  INTEGER PRIMARY KEY,
    item_id             INTEGER NOT NULL,
    agent_id            INTEGER NOT NULL,
    tick                INTEGER NOT NULL,
    channel             TEXT NOT NULL,
    version             INTEGER NOT NULL DEFAULT 1,
    perceived_claim_json TEXT NOT NULL,
    distortion          REAL NOT NULL DEFAULT 0.0,
    UNIQUE (item_id, agent_id)
);
CREATE INDEX IF NOT EXISTS ix_exposures_agent ON information_exposures(agent_id, tick);

-- Federal-lite political institutions.
CREATE TABLE IF NOT EXISTS political_parties (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    platform_json   TEXT NOT NULL,
    treasury_account_id INTEGER
);

CREATE TABLE IF NOT EXISTS agencies (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    mandate         TEXT NOT NULL,
    capacity        REAL NOT NULL DEFAULT 1.0,
    leader_agent_id INTEGER
);

CREATE TABLE IF NOT EXISTS legislators (
    id              INTEGER PRIMARY KEY,
    agent_id        INTEGER NOT NULL UNIQUE,
    chamber         TEXT NOT NULL,
    seat_number     INTEGER NOT NULL,
    party_id        INTEGER NOT NULL,
    term_start_tick INTEGER NOT NULL,
    term_end_tick   INTEGER NOT NULL,
    active          INTEGER NOT NULL DEFAULT 1,
    UNIQUE (chamber, seat_number, active)
);
CREATE INDEX IF NOT EXISTS ix_legislators_chamber ON legislators(chamber, active);

CREATE TABLE IF NOT EXISTS committees (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    chamber         TEXT NOT NULL,
    jurisdiction    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS committee_members (
    committee_id    INTEGER NOT NULL,
    legislator_id   INTEGER NOT NULL,
    is_chair        INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (committee_id, legislator_id)
);

CREATE TABLE IF NOT EXISTS bills (
    id              INTEGER PRIMARY KEY,
    bill_key        TEXT NOT NULL UNIQUE,
    title           TEXT NOT NULL,
    sponsor_legislator_id INTEGER NOT NULL,
    origin_chamber  TEXT NOT NULL,
    committee_id    INTEGER NOT NULL,
    status          TEXT NOT NULL DEFAULT 'introduced',
    current_version INTEGER NOT NULL DEFAULT 1,
    introduced_tick INTEGER NOT NULL,
    executive_action_tick INTEGER,
    effective_tick  INTEGER,
    policy_changes_json TEXT NOT NULL,
    metadata_json   TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_bills_status ON bills(status);

CREATE TABLE IF NOT EXISTS bill_versions (
    id              INTEGER PRIMARY KEY,
    bill_id         INTEGER NOT NULL,
    version         INTEGER NOT NULL,
    tick            INTEGER NOT NULL,
    author_legislator_id INTEGER NOT NULL,
    summary         TEXT NOT NULL,
    text_json       TEXT NOT NULL,
    UNIQUE (bill_id, version)
);

CREATE TABLE IF NOT EXISTS legislative_votes (
    id              INTEGER PRIMARY KEY,
    bill_id         INTEGER NOT NULL,
    version         INTEGER NOT NULL,
    legislator_id   INTEGER NOT NULL,
    stage           TEXT NOT NULL,
    vote            TEXT NOT NULL,
    tick            INTEGER NOT NULL,
    UNIQUE (bill_id, version, legislator_id, stage)
);

CREATE TABLE IF NOT EXISTS bill_actions (
    id              INTEGER PRIMARY KEY,
    bill_id         INTEGER NOT NULL,
    tick            INTEGER NOT NULL,
    action_type     TEXT NOT NULL,
    actor_agent_id  INTEGER,
    detail_json     TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS lobbying_activities (
    id              INTEGER PRIMARY KEY,
    tick            INTEGER NOT NULL,
    sponsor_type    TEXT NOT NULL,
    sponsor_id      INTEGER NOT NULL,
    lobbyist_agent_id INTEGER NOT NULL,
    target_agent_id INTEGER,
    bill_id         INTEGER,
    activity_type   TEXT NOT NULL,
    position        TEXT NOT NULL,
    amount_cents    INTEGER NOT NULL,
    transaction_id  INTEGER NOT NULL,
    salience_effect REAL NOT NULL,
    disclosure_tick INTEGER NOT NULL,
    disclosed       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS elections (
    id              INTEGER PRIMARY KEY,
    tick            INTEGER NOT NULL,
    election_type   TEXT NOT NULL,
    results_json    TEXT NOT NULL,
    turnout         INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS policy_rules (
    id              INTEGER PRIMARY KEY,
    bill_id         INTEGER,
    rule_key        TEXT NOT NULL,
    value_json      TEXT NOT NULL,
    enacted_tick    INTEGER NOT NULL,
    effective_tick  INTEGER NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending'
);
CREATE INDEX IF NOT EXISTS ix_policy_rules_key ON policy_rules(rule_key, status, effective_tick);
"""


MIGRATION_9_SQL = r"""
CREATE TABLE IF NOT EXISTS regions (
    id              INTEGER PRIMARY KEY,
    region_key      TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    currency_code   TEXT NOT NULL,
    population_target INTEGER NOT NULL,
    specialization_json TEXT NOT NULL,
    x               REAL NOT NULL,
    y               REAL NOT NULL,
    legal_ruleset   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS currencies (
    code            TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    minor_unit      INTEGER NOT NULL DEFAULT 2,
    numeraire_rate_ppm INTEGER NOT NULL,
    issuer_region_id INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS fx_reserves (
    currency_code   TEXT PRIMARY KEY,
    account_id      INTEGER NOT NULL,
    target_inventory INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS fx_orders (
    id              INTEGER PRIMARY KEY,
    tick            INTEGER NOT NULL,
    actor_id        INTEGER NOT NULL,
    pair            TEXT NOT NULL,
    base_currency   TEXT NOT NULL,
    quote_currency  TEXT NOT NULL,
    side            TEXT NOT NULL,
    qty             INTEGER NOT NULL,
    qty_remaining   INTEGER NOT NULL,
    limit_rate_ppm  INTEGER,
    seq             INTEGER NOT NULL,
    status          TEXT NOT NULL DEFAULT 'open'
);
CREATE INDEX IF NOT EXISTS ix_fx_orders_book ON fx_orders(pair, status, seq);

CREATE TABLE IF NOT EXISTS fx_trades (
    id              INTEGER PRIMARY KEY,
    tick            INTEGER NOT NULL,
    order_id        INTEGER NOT NULL,
    actor_id        INTEGER NOT NULL,
    pair            TEXT NOT NULL,
    side            TEXT NOT NULL,
    base_qty        INTEGER NOT NULL,
    quote_qty       INTEGER NOT NULL,
    rate_ppm        INTEGER NOT NULL,
    base_account_id INTEGER NOT NULL,
    quote_account_id INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS trade_shipments (
    id              INTEGER PRIMARY KEY,
    created_tick    INTEGER NOT NULL,
    exporter_firm_id INTEGER NOT NULL,
    importer_firm_id INTEGER NOT NULL,
    origin_region_id INTEGER NOT NULL,
    destination_region_id INTEGER NOT NULL,
    contract_id     INTEGER,
    quantity        INTEGER NOT NULL,
    invoice_cents   INTEGER NOT NULL,
    invoice_currency TEXT NOT NULL,
    tariff_cents    INTEGER NOT NULL DEFAULT 0,
    transport_cents INTEGER NOT NULL DEFAULT 0,
    arrival_tick    INTEGER NOT NULL,
    status          TEXT NOT NULL DEFAULT 'in_transit',
    payment_transaction_id INTEGER
);

CREATE TABLE IF NOT EXISTS migrations (
    id              INTEGER PRIMARY KEY,
    agent_id        INTEGER NOT NULL,
    origin_region_id INTEGER NOT NULL,
    destination_region_id INTEGER NOT NULL,
    requested_tick  INTEGER NOT NULL,
    completed_tick  INTEGER,
    reason          TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS agent_tier_history (
    id              INTEGER PRIMARY KEY,
    tick            INTEGER NOT NULL,
    agent_id        INTEGER NOT NULL,
    old_tier        TEXT NOT NULL,
    new_tier        TEXT NOT NULL,
    score           REAL NOT NULL,
    reason_json     TEXT NOT NULL
);
"""


MIGRATION_10_SQL = r"""
-- Pinned research datasets, scenario packs, paired counterfactuals, and outputs.
CREATE TABLE IF NOT EXISTS dataset_manifests (
    id                  INTEGER PRIMARY KEY,
    dataset_key         TEXT NOT NULL UNIQUE,
    source_url          TEXT NOT NULL,
    retrieval_time      TEXT NOT NULL,
    release_date        TEXT NOT NULL,
    vintage_date        TEXT NOT NULL,
    checksum_sha256     TEXT NOT NULL,
    transform_version   TEXT NOT NULL,
    usage_terms         TEXT NOT NULL,
    snapshot_path       TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'verified',
    metadata_json       TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS calibration_targets (
    id                  INTEGER PRIMARY KEY,
    dataset_manifest_id INTEGER NOT NULL,
    target_key          TEXT NOT NULL,
    value_json          TEXT NOT NULL,
    unit                TEXT NOT NULL,
    dimensions_json     TEXT NOT NULL DEFAULT '{}',
    UNIQUE(dataset_manifest_id, target_key, dimensions_json)
);

CREATE TABLE IF NOT EXISTS scenario_packs (
    id                  INTEGER PRIMARY KEY,
    scenario_key        TEXT NOT NULL UNIQUE,
    version             TEXT NOT NULL,
    title               TEXT NOT NULL,
    manifest_path       TEXT NOT NULL,
    manifest_checksum   TEXT NOT NULL,
    limitations         TEXT NOT NULL,
    metadata_json       TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS counterfactual_experiments (
    id                  INTEGER PRIMARY KEY,
    experiment_key      TEXT NOT NULL UNIQUE,
    scenario_key        TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    checkpoint_hash     TEXT NOT NULL,
    paired_seeds_json   TEXT NOT NULL,
    treatment_variables_json TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'running',
    report_path         TEXT
);

CREATE TABLE IF NOT EXISTS counterfactual_results (
    id                  INTEGER PRIMARY KEY,
    experiment_id       INTEGER NOT NULL,
    arm                 TEXT NOT NULL,
    seed                INTEGER NOT NULL,
    run_id              TEXT,
    replay_hash         TEXT,
    metrics_json        TEXT NOT NULL,
    causal_trace_json   TEXT NOT NULL DEFAULT '[]',
    UNIQUE(experiment_id, arm, seed)
);
"""


MIGRATION_11_SQL = r"""
-- Agent-to-agent wage bargaining.  Each row is an immutable offer; a newer
-- counter supersedes the previous pending row, preserving the full audit trail.
CREATE TABLE IF NOT EXISTS job_offers (
    id                  INTEGER PRIMARY KEY,
    application_id      INTEGER NOT NULL,
    tick                INTEGER NOT NULL,
    proposer_agent_id   INTEGER NOT NULL,
    wage_cents          INTEGER NOT NULL,
    parent_offer_id     INTEGER,
    status              TEXT NOT NULL DEFAULT 'pending',
    decided_tick        INTEGER
);
CREATE INDEX IF NOT EXISTS ix_job_offers_application
    ON job_offers(application_id, id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_job_offers_pending
    ON job_offers(application_id) WHERE status='pending';

-- Primary-market book building.  The reserve and every bid are agent-authored;
-- the engine only applies a deterministic price/time allocation rule.
CREATE TABLE IF NOT EXISTS ipo_offerings (
    id                      INTEGER PRIMARY KEY,
    firm_id                 INTEGER NOT NULL,
    issuer_agent_id         INTEGER NOT NULL,
    opened_tick             INTEGER NOT NULL,
    shares_offered          INTEGER NOT NULL,
    reserve_price_cents     INTEGER NOT NULL,
    minimum_subscription_bps INTEGER NOT NULL DEFAULT 5000,
    status                  TEXT NOT NULL DEFAULT 'building',
    closed_tick             INTEGER,
    clearing_price_cents    INTEGER,
    shares_sold             INTEGER NOT NULL DEFAULT 0,
    proceeds_cents          INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_ipo_active_firm
    ON ipo_offerings(firm_id) WHERE status='building';

CREATE TABLE IF NOT EXISTS ipo_bids (
    id                  INTEGER PRIMARY KEY,
    offering_id         INTEGER NOT NULL,
    tick                INTEGER NOT NULL,
    bidder_agent_id     INTEGER NOT NULL,
    qty                 INTEGER NOT NULL,
    max_price_cents     INTEGER NOT NULL,
    qty_allocated       INTEGER NOT NULL DEFAULT 0,
    status              TEXT NOT NULL DEFAULT 'open'
);
CREATE INDEX IF NOT EXISTS ix_ipo_bids_book
    ON ipo_bids(offering_id, status, max_price_cents, tick, id);

-- Cap-table provenance for non-secondary equity movements.  A primary
-- issuance has no source holder; transaction_id links paid allocations to the
-- balanced cash ledger.  Genesis distributions are explicitly identified and
-- have no cash transaction.
CREATE TABLE IF NOT EXISTS share_movements (
    id                  INTEGER PRIMARY KEY,
    tick                INTEGER NOT NULL,
    firm_id             INTEGER NOT NULL,
    from_holder_type    TEXT,
    from_holder_id      INTEGER,
    to_holder_type      TEXT NOT NULL,
    to_holder_id        INTEGER NOT NULL,
    qty                 INTEGER NOT NULL,
    movement_type       TEXT NOT NULL,
    reference_type      TEXT,
    reference_id        INTEGER,
    price_cents         INTEGER,
    amount_cents        INTEGER NOT NULL DEFAULT 0,
    transaction_id      INTEGER
);
CREATE INDEX IF NOT EXISTS ix_share_movements_firm
    ON share_movements(firm_id, id);
CREATE INDEX IF NOT EXISTS ix_share_movements_reference
    ON share_movements(reference_type, reference_id);

-- Durable lender-of-last-resort workflow state.  The request event remains the
-- immutable public/audit record; this table provides an indexed state pointer
-- so scheduler and context reads never rescan every historical proposal JSON.
CREATE TABLE IF NOT EXISTS liquidity_support_requests (
    id                  INTEGER PRIMARY KEY,
    request_event_id    INTEGER NOT NULL UNIQUE,
    bank_id             INTEGER NOT NULL,
    requested_tick      INTEGER NOT NULL,
    status              TEXT NOT NULL DEFAULT 'pending',
    decided_tick        INTEGER
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_liquidity_support_pending_bank
    ON liquidity_support_requests(bank_id) WHERE status='pending';
CREATE INDEX IF NOT EXISTS ix_liquidity_support_status
    ON liquidity_support_requests(status, bank_id, request_event_id);
"""


# Idempotent physical-design additions. These do not change engine semantics or
# the public schema version; they bound history lookups and maintain an exact
# ledger aggregate through SQLite triggers for constant-time reconciliation.
PERFORMANCE_SQL = r"""
DROP INDEX IF EXISTS ix_mem_agent;
CREATE INDEX IF NOT EXISTS ix_mem_agent_kind_tick
    ON memories(agent_id, kind, tick, demoted);
CREATE INDEX IF NOT EXISTS ix_mem_tick_importance
    ON memories(tick, importance, agent_id);
CREATE INDEX IF NOT EXISTS ix_events_subject_tick
    ON events(subject_type, subject_id, tick);
CREATE INDEX IF NOT EXISTS ix_events_kind_subject_tick
    ON events(kind, subject_type, subject_id, tick, id);
CREATE INDEX IF NOT EXISTS ix_action_proposals_type_status
    ON action_proposals(action_type, validation_status, tick, id);
CREATE INDEX IF NOT EXISTS ix_firms_founder_status
    ON firms(founder_agent_id, status);
CREATE INDEX IF NOT EXISTS ix_legal_claimant
    ON legal_matters(claimant_type, claimant_id);
CREATE INDEX IF NOT EXISTS ix_legal_respondent
    ON legal_matters(respondent_type, respondent_id);
CREATE INDEX IF NOT EXISTS ix_information_status_tick
    ON information_items(status, tick, id);
CREATE INDEX IF NOT EXISTS ix_metrics_name_tick
    ON metrics(name, tick DESC);

CREATE TABLE IF NOT EXISTS account_ledger_totals (
    account_id  INTEGER PRIMARY KEY,
    total_cents INTEGER NOT NULL DEFAULT 0
);
CREATE TRIGGER IF NOT EXISTS trg_ledger_totals_insert
AFTER INSERT ON ledger_entries BEGIN
    INSERT INTO account_ledger_totals(account_id, total_cents)
    VALUES (NEW.account_id, NEW.delta_cents)
    ON CONFLICT(account_id) DO UPDATE
    SET total_cents=total_cents + NEW.delta_cents;
END;
CREATE TRIGGER IF NOT EXISTS trg_ledger_totals_delete
AFTER DELETE ON ledger_entries BEGIN
    UPDATE account_ledger_totals
    SET total_cents=total_cents - OLD.delta_cents
    WHERE account_id=OLD.account_id;
END;
CREATE TRIGGER IF NOT EXISTS trg_ledger_totals_update
AFTER UPDATE OF account_id, delta_cents ON ledger_entries BEGIN
    UPDATE account_ledger_totals
    SET total_cents=total_cents - OLD.delta_cents
    WHERE account_id=OLD.account_id;
    INSERT INTO account_ledger_totals(account_id, total_cents)
    VALUES (NEW.account_id, NEW.delta_cents)
    ON CONFLICT(account_id) DO UPDATE
    SET total_cents=total_cents + NEW.delta_cents;
END;
DELETE FROM account_ledger_totals;
INSERT INTO account_ledger_totals(account_id, total_cents)
SELECT account_id, SUM(delta_cents) FROM ledger_entries GROUP BY account_id;
"""


def initialize_schema(conn) -> None:
    """Create all tables on a fresh connection (idempotent)."""
    assert_schema_compatible(conn)
    conn.executescript(SCHEMA_SQL)
    conn.executescript(MIGRATION_6_SQL)
    conn.executescript(MIGRATION_7_SQL)
    conn.executescript(MIGRATION_8_SQL)
    conn.executescript(MIGRATION_9_SQL)
    conn.executescript(MIGRATION_10_SQL)
    conn.executescript(MIGRATION_11_SQL)
    conn.executescript(PERFORMANCE_SQL)
    _ensure_column(conn, "agents", "region_id", "INTEGER")
    _ensure_column(conn, "agents", "population_tier", "TEXT NOT NULL DEFAULT 'periphery'")
    _ensure_column(conn, "agents", "pinned_core", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "firms", "region_id", "INTEGER")
    _ensure_column(conn, "firms", "currency_code", "TEXT NOT NULL DEFAULT 'USD'")
    _ensure_column(conn, "banks", "region_id", "INTEGER")
    _ensure_column(conn, "banks", "currency_code", "TEXT NOT NULL DEFAULT 'USD'")
    _ensure_column(conn, "accounts", "currency_code", "TEXT NOT NULL DEFAULT 'USD'")
    _ensure_column(conn, "transactions", "currency_code", "TEXT NOT NULL DEFAULT 'USD'")
    columns = {row[1] for row in conn.execute("PRAGMA table_info(run_meta)")}
    additions = {
        "active_tick": "INTEGER",
        "next_phase": "TEXT NOT NULL DEFAULT 'NIGHT_CLOSE'",
        "phase_state_json": "TEXT NOT NULL DEFAULT '{}'",
        "legacy_partial": "INTEGER NOT NULL DEFAULT 0",
        "participant_influenced": "INTEGER NOT NULL DEFAULT 0",
    }
    migrated = False
    for name, declaration in additions.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE run_meta ADD COLUMN {name} {declaration}")
            migrated = True
    if migrated:
        _migrate_legacy_progress(conn)
    prediction_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(predictions)")}
    if "evidence_json" not in prediction_columns:
        conn.execute(
            "ALTER TABLE predictions ADD COLUMN "
            "evidence_json TEXT NOT NULL DEFAULT '[]'")
    conn.execute(
        "UPDATE run_meta SET schema_version=? WHERE id=1 AND schema_version<?",
        (SCHEMA_VERSION, SCHEMA_VERSION))
    conn.commit()


def _ensure_column(conn, table: str, name: str, declaration: str) -> None:
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if name not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")


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
