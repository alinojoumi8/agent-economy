"""Bind run-scoped external citizens to persistent Agent Passports."""
from __future__ import annotations


NAME = "passport_bindings"

SQL = r"""
ALTER TABLE external_agent_connections
    ADD COLUMN passport_id TEXT
    CHECK(passport_id IS NULL OR length(passport_id) BETWEEN 16 AND 64);

CREATE UNIQUE INDEX ux_external_connections_passport
    ON external_agent_connections(passport_id)
    WHERE passport_id IS NOT NULL;
"""


def verify(conn) -> None:
    columns = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(external_agent_connections)")
    }
    if "passport_id" not in columns:
        raise RuntimeError("external_agent_connections.passport_id is missing")
    indexes = {
        str(row[1])
        for row in conn.execute("PRAGMA index_list(external_agent_connections)")
    }
    if "ux_external_connections_passport" not in indexes:
        raise RuntimeError("passport binding uniqueness index is missing")
