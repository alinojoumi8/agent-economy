"""Persistent, prospective geography and settlement history."""
NAME = "frontier_geography"
SQL = r"""
ALTER TABLE regions ADD COLUMN created_tick INTEGER NOT NULL DEFAULT 0;
CREATE TABLE frontier_sites (
 id INTEGER PRIMARY KEY, x INTEGER NOT NULL, y INTEGER NOT NULL,
 terrain TEXT NOT NULL, resource TEXT NOT NULL, capacity INTEGER NOT NULL,
 discovered_tick INTEGER, discovered_by INTEGER REFERENCES agents(id),
 UNIQUE(x,y)
);
CREATE TABLE frontier_settlements (
 id INTEGER PRIMARY KEY, site_id INTEGER NOT NULL UNIQUE REFERENCES frontier_sites(id),
 name TEXT NOT NULL, name_key TEXT NOT NULL UNIQUE,
 founder_id INTEGER REFERENCES agents(id), founded_tick INTEGER NOT NULL,
 work_units INTEGER NOT NULL DEFAULT 0, completed_tick INTEGER,
 region_id INTEGER NOT NULL REFERENCES regions(id), charter_tick INTEGER
);
CREATE TABLE frontier_residences (
 agent_id INTEGER NOT NULL REFERENCES agents(id), tick INTEGER NOT NULL,
 settlement_id INTEGER NOT NULL REFERENCES frontier_settlements(id),
 region_id INTEGER NOT NULL REFERENCES regions(id), PRIMARY KEY(agent_id,tick)
);
CREATE TABLE frontier_tasks (
 id INTEGER PRIMARY KEY, agent_id INTEGER NOT NULL REFERENCES agents(id),
 kind TEXT NOT NULL, site_id INTEGER NOT NULL REFERENCES frontier_sites(id),
 started_tick INTEGER NOT NULL, due_tick INTEGER NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending', completed_tick INTEGER,
 transaction_id INTEGER REFERENCES transactions(id)
);
CREATE UNIQUE INDEX frontier_one_task ON frontier_tasks(agent_id) WHERE status='pending';
CREATE TABLE frontier_votes (
 settlement_id INTEGER NOT NULL REFERENCES frontier_settlements(id),
 agent_id INTEGER NOT NULL REFERENCES agents(id), tick INTEGER NOT NULL,
 PRIMARY KEY(settlement_id,agent_id)
);
CREATE TABLE frontier_history (
 id INTEGER PRIMARY KEY, tick INTEGER NOT NULL, data_json TEXT NOT NULL
);
CREATE INDEX frontier_history_tick ON frontier_history(tick,id);
"""


def verify(conn):
    for name in ("frontier_sites", "frontier_settlements", "frontier_residences",
                 "frontier_tasks", "frontier_votes", "frontier_history"):
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone():
            raise RuntimeError(f"missing {name}")
