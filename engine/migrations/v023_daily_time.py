"""Daily physical time and non-cash wage claims for Semantics 18."""

NAME = "daily_time_and_earned_wages"
SQL = """
CREATE TABLE time_plans (
    id INTEGER PRIMARY KEY,
    agent_id INTEGER NOT NULL REFERENCES agents(id),
    request_key TEXT NOT NULL CHECK(length(request_key) BETWEEN 1 AND 96),
    created_tick INTEGER NOT NULL CHECK(created_tick>=0),
    effective_tick INTEGER NOT NULL CHECK(effective_tick=created_tick+1),
    work_minutes INTEGER NOT NULL CHECK(work_minutes BETWEEN 0 AND 1440),
    work_firm_id INTEGER REFERENCES firms(id),
    care_minutes INTEGER NOT NULL CHECK(care_minutes BETWEEN 0 AND 1440),
    care_targets_json TEXT,
    UNIQUE(agent_id,request_key)
);
CREATE INDEX ix_effective_time_plan ON time_plans(agent_id,effective_tick,id);
CREATE TRIGGER time_plan_immutable BEFORE UPDATE ON time_plans
BEGIN SELECT RAISE(ABORT,'time plan is immutable'); END;
CREATE TRIGGER time_plan_no_delete BEFORE DELETE ON time_plans
BEGIN SELECT RAISE(ABORT,'time plan is permanent'); END;
CREATE TABLE time_days (
    tick INTEGER NOT NULL CHECK(tick>=0),
    agent_id INTEGER NOT NULL REFERENCES agents(id),
    available_minutes INTEGER NOT NULL CHECK(available_minutes BETWEEN 0 AND 1440),
    allocated_minutes INTEGER NOT NULL DEFAULT 0 CHECK(allocated_minutes>=0 AND allocated_minutes<=available_minutes),
    plan_id INTEGER REFERENCES time_plans(id),
    PRIMARY KEY(tick,agent_id)
);
CREATE TABLE time_allocations (
    id INTEGER PRIMARY KEY,
    tick INTEGER NOT NULL,
    agent_id INTEGER NOT NULL,
    allocation_key TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('employment','owner_work','institution','care','care_received','study','construction','civic','travel')),
    minutes INTEGER NOT NULL CHECK(minutes>0 AND minutes<=1440),
    delivered_minutes INTEGER NOT NULL CHECK(delivered_minutes>=0 AND delivered_minutes<=minutes),
    reference_type TEXT NOT NULL,
    reference_id INTEGER,
    request_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT,
    UNIQUE(tick,agent_id,allocation_key),
    FOREIGN KEY(tick,agent_id) REFERENCES time_days(tick,agent_id)
);
CREATE INDEX ix_time_activity ON time_allocations(tick,kind,reference_type,reference_id);
CREATE INDEX ix_time_activity_key ON time_allocations(agent_id,allocation_key);
CREATE TRIGGER time_allocation_budget BEFORE INSERT ON time_allocations
WHEN NEW.minutes>COALESCE((SELECT available_minutes-allocated_minutes FROM time_days
                          WHERE tick=NEW.tick AND agent_id=NEW.agent_id),-1)
BEGIN SELECT RAISE(ABORT,'daily time budget exceeded'); END;
CREATE TRIGGER time_allocation_count AFTER INSERT ON time_allocations
BEGIN UPDATE time_days SET allocated_minutes=allocated_minutes+NEW.minutes
      WHERE tick=NEW.tick AND agent_id=NEW.agent_id; END;
CREATE TRIGGER time_allocation_terms_immutable
BEFORE UPDATE OF tick,agent_id,allocation_key,kind,minutes,reference_type,reference_id,request_json ON time_allocations
BEGIN SELECT RAISE(ABORT,'time allocation terms are immutable'); END;
CREATE TRIGGER time_allocation_no_delete BEFORE DELETE ON time_allocations
BEGIN SELECT RAISE(ABORT,'time allocation is permanent'); END;
CREATE TABLE child_care_days (
    tick INTEGER NOT NULL CHECK(tick>=0),
    child_id INTEGER NOT NULL REFERENCES agents(id),
    household_id INTEGER NOT NULL REFERENCES households(id),
    required_minutes INTEGER NOT NULL CHECK(required_minutes>=0),
    delivered_minutes INTEGER NOT NULL DEFAULT 0 CHECK(delivered_minutes>=0 AND delivered_minutes<=required_minutes),
    PRIMARY KEY(tick,child_id)
);
CREATE TABLE wage_claims (
    id INTEGER PRIMARY KEY,
    employment_id INTEGER NOT NULL UNIQUE REFERENCES employments(id),
    employee_id INTEGER NOT NULL REFERENCES agents(id),
    firm_id INTEGER NOT NULL REFERENCES firms(id),
    currency_code TEXT NOT NULL,
    payable_account_id INTEGER NOT NULL UNIQUE REFERENCES accounts(id),
    denominator INTEGER NOT NULL CHECK(denominator>0),
    remainder_numerator INTEGER NOT NULL DEFAULT 0 CHECK(remainder_numerator>=0 AND remainder_numerator<denominator),
    accrued_cents INTEGER NOT NULL DEFAULT 0 CHECK(accrued_cents>=0),
    paid_cents INTEGER NOT NULL DEFAULT 0 CHECK(paid_cents>=0),
    written_off_cents INTEGER NOT NULL DEFAULT 0 CHECK(written_off_cents>=0),
    opened_tick INTEGER NOT NULL CHECK(opened_tick>=0),
    closed_tick INTEGER CHECK(closed_tick>=opened_tick),
    CHECK(paid_cents+written_off_cents<=accrued_cents)
);
CREATE TABLE wage_claim_holders (
    id INTEGER PRIMARY KEY,
    claim_id INTEGER NOT NULL REFERENCES wage_claims(id),
    owner_type TEXT NOT NULL CHECK(owner_type IN ('agent','system')),
    owner_id INTEGER REFERENCES agents(id),
    receivable_account_id INTEGER NOT NULL UNIQUE REFERENCES accounts(id),
    started_tick INTEGER NOT NULL CHECK(started_tick>=0),
    ended_tick INTEGER CHECK(ended_tick>=started_tick),
    CHECK((owner_type='agent' AND owner_id IS NOT NULL) OR (owner_type='system' AND owner_id IS NULL))
);
CREATE UNIQUE INDEX ix_current_wage_claim_holder ON wage_claim_holders(claim_id) WHERE ended_tick IS NULL;
CREATE INDEX ix_wage_claim_firm ON wage_claims(firm_id,closed_tick);
CREATE INDEX ix_wage_holder_owner ON wage_claim_holders(owner_type,owner_id,ended_tick);
CREATE TABLE wage_accruals (
    id INTEGER PRIMARY KEY,
    tick INTEGER NOT NULL,
    allocation_id INTEGER NOT NULL UNIQUE REFERENCES time_allocations(id),
    claim_id INTEGER NOT NULL REFERENCES wage_claims(id),
    worked_minutes INTEGER NOT NULL CHECK(worked_minutes>0),
    period_wage_cents INTEGER NOT NULL CHECK(period_wage_cents>=0),
    earned_cents INTEGER NOT NULL CHECK(earned_cents>=0),
    remainder_numerator INTEGER NOT NULL CHECK(remainder_numerator>=0),
    transaction_id INTEGER UNIQUE REFERENCES transactions(id)
);
CREATE TABLE wage_settlements (
    id INTEGER PRIMARY KEY,
    tick INTEGER NOT NULL CHECK(tick>=0),
    claim_id INTEGER NOT NULL REFERENCES wage_claims(id),
    holder_id INTEGER NOT NULL REFERENCES wage_claim_holders(id),
    kind TEXT NOT NULL CHECK(kind IN ('payment','write_off')),
    gross_cents INTEGER NOT NULL CHECK(gross_cents>0),
    tax_cents INTEGER NOT NULL DEFAULT 0 CHECK(tax_cents>=0 AND tax_cents<=gross_cents),
    transaction_id INTEGER NOT NULL UNIQUE REFERENCES transactions(id)
);
CREATE TABLE firm_labor_days (
    tick INTEGER NOT NULL CHECK(tick>=0),
    firm_id INTEGER NOT NULL REFERENCES firms(id),
    productive_minutes INTEGER NOT NULL CHECK(productive_minutes>=0),
    management_minutes INTEGER NOT NULL CHECK(management_minutes>=0),
    desired_units INTEGER NOT NULL CHECK(desired_units>=0),
    produced_units INTEGER NOT NULL CHECK(produced_units>=0 AND produced_units<=desired_units),
    carry_numerator INTEGER NOT NULL CHECK(carry_numerator>=0),
    PRIMARY KEY(tick,firm_id)
);
CREATE INDEX ix_wage_accrual_claim ON wage_accruals(claim_id,tick);
CREATE INDEX ix_wage_settlement_claim ON wage_settlements(claim_id,kind);
"""

for _journal in ("wage_accruals", "wage_settlements"):
    SQL += f"""
CREATE TRIGGER {_journal}_immutable BEFORE UPDATE ON {_journal}
BEGIN SELECT RAISE(ABORT,'wage journal is immutable'); END;
CREATE TRIGGER {_journal}_no_delete BEFORE DELETE ON {_journal}
BEGIN SELECT RAISE(ABORT,'wage journal is permanent'); END;
"""
SQL += """
CREATE TRIGGER time_day_terms_immutable BEFORE UPDATE OF tick,agent_id,available_minutes,plan_id ON time_days
BEGIN SELECT RAISE(ABORT,'daily time terms are immutable'); END;
CREATE TRIGGER time_delivery_monotonic BEFORE UPDATE OF delivered_minutes ON time_allocations
WHEN NEW.delivered_minutes<OLD.delivered_minutes
BEGIN SELECT RAISE(ABORT,'delivered time cannot be undone'); END;
CREATE TRIGGER wage_claim_terms_immutable
BEFORE UPDATE OF employment_id,employee_id,firm_id,currency_code,payable_account_id,denominator,opened_tick ON wage_claims
BEGIN SELECT RAISE(ABORT,'wage claim terms are immutable'); END;
CREATE TRIGGER wage_holder_identity_immutable
BEFORE UPDATE OF claim_id,owner_type,owner_id,receivable_account_id,started_tick ON wage_claim_holders
BEGIN SELECT RAISE(ABORT,'wage beneficiary identity is immutable'); END;
"""


def verify(conn) -> None:
    objects = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master")}
    required = {"time_plans", "time_days", "time_allocations", "child_care_days",
                "wage_claims", "wage_claim_holders", "wage_accruals", "wage_settlements",
                "firm_labor_days", "ix_effective_time_plan", "ix_time_activity",
                "ix_current_wage_claim_holder", "time_plan_immutable", "time_plan_no_delete",
                "time_allocation_budget", "time_allocation_count", "time_allocation_terms_immutable",
                "time_allocation_no_delete", "time_day_terms_immutable", "time_delivery_monotonic",
                "wage_claim_terms_immutable", "wage_holder_identity_immutable",
                "wage_accruals_immutable", "wage_accruals_no_delete",
                "wage_settlements_immutable", "wage_settlements_no_delete",
                "ix_time_activity_key", "ix_wage_claim_firm", "ix_wage_holder_owner",
                "ix_wage_accrual_claim", "ix_wage_settlement_claim"}
    if not required <= objects:
        raise RuntimeError("daily time or wage claim storage is missing")
