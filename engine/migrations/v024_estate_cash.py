"""Cash inventory and bank-principal settlement receipts for Semantics 19."""

NAME = "estate_cash_and_bank_principal"
TABLES = ("cash_estates", "estate_cash_assets", "estate_loan_claims", "estate_cash_transfers")
SQL = """
CREATE TABLE cash_estates (
    id INTEGER PRIMARY KEY,
    deceased_agent_id INTEGER NOT NULL UNIQUE REFERENCES agents(id),
    tick INTEGER NOT NULL CHECK(tick>=0),
    heir_id INTEGER REFERENCES agents(id),
    policy TEXT NOT NULL CHECK(policy='positive_cash_bank_principal_v1'),
    cash_account_count INTEGER NOT NULL CHECK(cash_account_count>=0),
    loan_count INTEGER NOT NULL CHECK(loan_count>=0),
    completed_event_id INTEGER UNIQUE REFERENCES events(id),
    CHECK(heir_id IS NULL OR heir_id<>deceased_agent_id)
);
CREATE TABLE estate_cash_assets (
    id INTEGER PRIMARY KEY,
    estate_id INTEGER NOT NULL REFERENCES cash_estates(id),
    account_id INTEGER NOT NULL UNIQUE REFERENCES accounts(id),
    currency_code TEXT NOT NULL,
    opening_cents INTEGER NOT NULL,
    loan_paid_cents INTEGER NOT NULL CHECK(loan_paid_cents>=0),
    residual_cents INTEGER NOT NULL CHECK(residual_cents>=0),
    CHECK(loan_paid_cents+residual_cents=MAX(0,opening_cents))
);
CREATE INDEX ix_estate_cash_inventory ON estate_cash_assets(estate_id,currency_code,account_id);
CREATE TABLE estate_loan_claims (
    id INTEGER PRIMARY KEY,
    estate_id INTEGER NOT NULL REFERENCES cash_estates(id),
    loan_id INTEGER NOT NULL UNIQUE REFERENCES loans(id),
    bank_id INTEGER NOT NULL REFERENCES banks(id),
    currency_code TEXT NOT NULL,
    principal_cents INTEGER NOT NULL CHECK(principal_cents>=0),
    paid_cents INTEGER NOT NULL CHECK(paid_cents>=0),
    written_off_cents INTEGER NOT NULL CHECK(written_off_cents>=0),
    reserve_account_id INTEGER NOT NULL REFERENCES accounts(id),
    equity_account_id INTEGER NOT NULL REFERENCES accounts(id),
    loss_account_id INTEGER REFERENCES accounts(id),
    chargeoff_transaction_id INTEGER UNIQUE REFERENCES transactions(id),
    CHECK(paid_cents+written_off_cents=principal_cents),
    CHECK((written_off_cents=0 AND chargeoff_transaction_id IS NULL AND loss_account_id IS NULL)
       OR (written_off_cents>0 AND chargeoff_transaction_id IS NOT NULL AND loss_account_id IS NOT NULL))
);
CREATE INDEX ix_estate_creditors ON estate_loan_claims(estate_id,loan_id);
CREATE TABLE estate_cash_transfers (
    id INTEGER PRIMARY KEY,
    estate_id INTEGER NOT NULL REFERENCES cash_estates(id),
    source_account_id INTEGER NOT NULL REFERENCES accounts(id),
    destination_account_id INTEGER NOT NULL REFERENCES accounts(id),
    currency_code TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('loan','inheritance','escheat')),
    loan_id INTEGER REFERENCES loans(id),
    amount_cents INTEGER NOT NULL CHECK(amount_cents>0),
    transaction_id INTEGER NOT NULL UNIQUE REFERENCES transactions(id),
    CHECK((kind='loan' AND loan_id IS NOT NULL) OR (kind<>'loan' AND loan_id IS NULL)),
    CHECK(source_account_id<>destination_account_id)
);
CREATE INDEX ix_estate_transfer_source ON estate_cash_transfers(estate_id,source_account_id);
CREATE INDEX ix_estate_transfer_loan ON estate_cash_transfers(loan_id);
CREATE TRIGGER cash_estate_terms_immutable BEFORE UPDATE OF
    id,deceased_agent_id,tick,heir_id,policy,cash_account_count,loan_count ON cash_estates
BEGIN SELECT RAISE(ABORT,'cash estate terms are immutable'); END;
CREATE TRIGGER cash_estate_completion_once BEFORE UPDATE OF completed_event_id ON cash_estates
WHEN OLD.completed_event_id IS NOT NULL OR NEW.completed_event_id IS NULL
BEGIN SELECT RAISE(ABORT,'cash estate completion is permanent'); END;
CREATE TRIGGER cash_estate_no_delete BEFORE DELETE ON cash_estates
BEGIN SELECT RAISE(ABORT,'cash estate is permanent'); END;
"""
for _table in TABLES[1:]:
    SQL += f"""
CREATE TRIGGER {_table}_immutable BEFORE UPDATE ON {_table}
BEGIN SELECT RAISE(ABORT,'estate receipt is immutable'); END;
CREATE TRIGGER {_table}_no_delete BEFORE DELETE ON {_table}
BEGIN SELECT RAISE(ABORT,'estate receipt is permanent'); END;
"""


def verify(conn) -> None:
    objects = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master")}
    required = set(TABLES) | {"ix_estate_cash_inventory", "ix_estate_creditors",
        "ix_estate_transfer_source", "ix_estate_transfer_loan", "cash_estate_terms_immutable",
        "cash_estate_completion_once", "cash_estate_no_delete"}
    required |= {f"{table}_{suffix}" for table in TABLES[1:] for suffix in ("immutable", "no_delete")}
    if not required <= objects:
        raise RuntimeError("estate cash inventory or immutable receipts are missing")
