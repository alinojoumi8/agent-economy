"""Public-event boundary shared by news and end-of-run reporting.

The event spine also contains private beliefs, participant-control audit rows,
provider diagnostics, and other operational state.  Those records are valid
for local audit and replay, but they are never suitable inputs to a public
writer.  A positive allowlist keeps that boundary explicit as new event kinds
are added.
"""
from __future__ import annotations

from typing import Any


PUBLIC_REPORTABLE_EVENT_KINDS = frozenset({
    # World and exogenous public state.
    "genesis", "regions_initialized", "political_institutions_created",
    "institution_created", "quiet_day", "shock_fired", "shock_ended",
    "epidemic_started", "epidemic_ended",
    # Real-economy and firm outcomes.
    "production", "inventory_spoilage", "company_founded", "bankruptcy",
    "firm_bankruptcy", "firm_scandal", "firm_disclosure_published",
    "wage_missed", "benefits_paid", "death", "arrival",
    # Banking, credit, monetary policy, and markets.
    "bank_failure", "bank_run", "loan_default", "policy_rate_set",
    "liquidity_support_requested", "lolr_granted", "lolr_denied",
    "ipo", "ipo_book_opened", "ipo_book_closed", "ipo_listing_failed",
    "circuit_breaker", "currency_crisis", "fx_intervention",
    # Public law, politics, disclosure, and capital formation.
    "contract_executed", "obligation_breached", "legal_matter_filed",
    "legal_filing_submitted", "legal_decision_enforced", "matter_settled",
    "legal_notice_issued", "settlement_offered", "election_held",
    "federal_election_held", "bill_introduced", "bill_passed",
    "bill_enacted", "bill_vetoed", "lobbying_disclosed",
    "information_published", "claim_created", "rumor", "slant_directive",
    "vc_funded", "vc_writeoff", "merger_proposed", "merger_cleared",
    "merger_blocked",
})


# Even an allowed event may carry internal or personal fields.  Public writers
# receive only these bounded primitives; nested private state never crosses the
# boundary.  Names are limited to public firms/institutions/outlets.
PUBLIC_EVENT_PAYLOAD_KEYS = frozenset({
    "amount_cents", "awarded_cents", "bank_id", "bill_id", "candidate_id",
    "clearing_price_cents", "contract_id", "damages_cents", "disclosure_id",
    "duration_ticks", "election_id", "election_type", "equity_bps",
    "firm_id", "firm_name", "filing_id", "haircut_rate", "kind",
    "law_id", "matter_id", "multiplier", "notice_id", "offering_id",
    "outcome", "outlet", "outlet_id", "rate_bps", "remedy_type",
    "shares_issued", "shares_offered", "shares_sold", "shock_id", "status",
    "summary", "turnout", "units", "wage_cents", "winner_id",
    "winner_party_id",
})


def is_public_reportable_event(kind: str) -> bool:
    return str(kind) in PUBLIC_REPORTABLE_EVENT_KINDS


def public_event_payload(kind: str, payload: Any) -> dict:
    """Return a bounded public projection for an allowlisted event payload."""
    if not is_public_reportable_event(kind) or not isinstance(payload, dict):
        return {}
    out: dict[str, Any] = {}
    for key in sorted(PUBLIC_EVENT_PAYLOAD_KEYS):
        if key not in payload:
            continue
        value = payload[key]
        if value is None or isinstance(value, (bool, int, float)):
            out[key] = value
        elif isinstance(value, str):
            out[key] = value.replace("\x00", "")[:160]
    return out
