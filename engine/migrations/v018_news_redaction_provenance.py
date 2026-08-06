"""Persist newsroom numeric-redaction provenance across public projections."""
from __future__ import annotations


NAME = "news_redaction_provenance"

SQL = r"""
ALTER TABLE news_articles
    ADD COLUMN numeric_claims_redacted INTEGER NOT NULL DEFAULT 0
    CHECK(numeric_claims_redacted IN (0,1));

ALTER TABLE news_articles
    ADD COLUMN numeric_claims_redaction_reason TEXT
    CHECK(
        (numeric_claims_redacted = 0 AND
         numeric_claims_redaction_reason IS NULL)
        OR
        (numeric_claims_redacted = 1 AND
         numeric_claims_redaction_reason IS NOT NULL AND
         numeric_claims_redaction_reason IN
         ('missing_source_citation','ungrounded_numeric_claim'))
    );
"""


def verify(conn) -> None:
    columns = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(news_articles)")
    }
    required = {
        "numeric_claims_redacted", "numeric_claims_redaction_reason",
    }
    missing = required - columns
    if missing:
        raise RuntimeError(
            f"news redaction provenance columns are missing: {sorted(missing)}")
