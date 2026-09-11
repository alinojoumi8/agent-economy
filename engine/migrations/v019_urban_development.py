"""Additive semantics-13 construction records and valid-time public state."""
NAME = "urban_development"
SQL = r"""
CREATE TABLE urban_parcels (
 id INTEGER PRIMARY KEY, parcel_key TEXT NOT NULL UNIQUE, region_id INTEGER NOT NULL REFERENCES regions(id),
 x REAL NOT NULL, y REAL NOT NULL, zone_key TEXT NOT NULL, blocked INTEGER NOT NULL DEFAULT 0 CHECK(blocked IN (0,1)),
 owner_firm_id INTEGER REFERENCES firms(id), created_tick INTEGER NOT NULL
);
CREATE TABLE construction_projects (
 id INTEGER PRIMARY KEY, actor_agent_id INTEGER NOT NULL REFERENCES agents(id), firm_id INTEGER NOT NULL REFERENCES firms(id),
 parcel_id INTEGER NOT NULL REFERENCES urban_parcels(id), template_key TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('building','completed','cancelled','demolished','closed')),
 requested_tick INTEGER NOT NULL, completion_tick INTEGER NOT NULL, cost_cents INTEGER NOT NULL CHECK(cost_cents>0),
 currency_code TEXT NOT NULL, capacity INTEGER NOT NULL CHECK(capacity>0), escrow_account_id INTEGER REFERENCES accounts(id),
 funding_transaction_id INTEGER REFERENCES transactions(id), settlement_transaction_id INTEGER REFERENCES transactions(id),
 refund_transaction_id INTEGER REFERENCES transactions(id), place_id INTEGER REFERENCES places(id),
 created_event_id INTEGER REFERENCES events(id), outcome_event_id INTEGER REFERENCES events(id)
);
CREATE UNIQUE INDEX construction_occupied_parcel ON construction_projects(parcel_id) WHERE status IN ('building','completed');
CREATE UNIQUE INDEX construction_active_firm ON construction_projects(firm_id) WHERE status IN ('building','completed');
CREATE TABLE construction_receipts (
 id INTEGER PRIMARY KEY, actor_agent_id INTEGER NOT NULL REFERENCES agents(id), request_key TEXT NOT NULL,
 payload_json TEXT NOT NULL, result_json TEXT NOT NULL, UNIQUE(actor_agent_id,request_key)
);
CREATE TABLE urban_projection_history (
 id INTEGER PRIMARY KEY, tick INTEGER NOT NULL, data_json TEXT NOT NULL
);
CREATE INDEX urban_projection_tick ON urban_projection_history(tick,id);
"""
def verify(conn):
    for table in ('urban_parcels','construction_projects','construction_receipts','urban_projection_history'):
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():
            raise RuntimeError(f"missing {table}")
