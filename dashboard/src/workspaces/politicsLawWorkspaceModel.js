const FIELDS = {
  bills: ["id", "bill_key", "title", "origin_chamber", "committee_id", "introduced_tick", "executive_action_tick", "effective_tick", "status", "current_version"],
  billVersions: ["id", "bill_id", "version", "tick", "summary"],
  votes: ["id", "bill_id", "version", "legislator_id", "stage", "vote", "tick"],
  rules: ["id", "bill_id", "rule_key", "value", "enacted_tick", "effective_tick", "status"],
  lobbying: ["id", "tick", "sponsor_type", "sponsor_id", "bill_id", "activity_type", "position", "amount_cents", "disclosure_tick", "disclosed"],
  contracts: ["id", "contract_type", "title", "jurisdiction", "ruleset_key", "offered_tick", "executed_tick", "expiry_tick", "terminated_tick", "status"],
  obligations: ["id", "contract_id", "obligation_type", "due_tick", "grace_ticks", "amount_cents", "currency_code", "performed_tick", "breached_tick", "status"],
  matters: ["id", "matter_type", "venue", "contract_id", "claim_type", "filed_tick", "response_due_tick", "resolved_tick", "status"],
  mergers: ["id", "proposed_tick", "acquirer_firm_id", "target_firm_id", "consideration_type", "price_cents", "currency_code", "target_approved_tick", "regulator_notified_tick", "closed_tick", "terminated_tick", "status"],
  mergerReviews: ["id", "merger_id", "tick", "pre_hhi", "post_hhi", "delta_hhi", "threshold_hhi", "threshold_delta", "outcome"],
};

function records(value) {
  return Array.isArray(value) ? value.filter(row => row && typeof row === "object") : [];
}

function normalize(value, fields, tickField) {
  return records(value).map(row => Object.fromEntries(
    fields.filter(field => row[field] !== undefined).map(field => [field, row[field]]),
  )).filter(row => row.id !== undefined).sort((left, right) => (
    Number(left[tickField] ?? 0) - Number(right[tickField] ?? 0)
    || Number(left.id ?? 0) - Number(right.id ?? 0)
  ));
}

export function normalizePoliticsLawWorkspace(data = {}) {
  const source = data && typeof data === "object" ? data : {};
  const politicsEnabled = source.politics?.enabled === true;
  const legalEnabled = source.legal?.enabled === true;
  const lobbying = (politicsEnabled ? normalize(source.lobbying, FIELDS.lobbying, "tick") : []).map(row => ({
    ...row,
    disclosure_state: row.disclosed === true || row.disclosed === 1 ? "disclosed" : "undisclosed",
  }));
  return {
    configuration: {
      politicsEnabled,
      institutionalActionsEnabled: source.politics?.institutional_actions_enabled === true,
      legalEnabled,
    },
    bills: politicsEnabled ? normalize(source.bills, FIELDS.bills, "introduced_tick") : [],
    billVersions: politicsEnabled ? normalize(source.bill_versions, FIELDS.billVersions, "tick") : [],
    votes: politicsEnabled ? normalize(source.votes, FIELDS.votes, "tick") : [],
    rules: politicsEnabled ? normalize(source.rules, FIELDS.rules, "enacted_tick") : [],
    lobbying,
    contracts: legalEnabled ? normalize(source.contracts, FIELDS.contracts, "offered_tick") : [],
    obligations: legalEnabled ? normalize(source.obligations, FIELDS.obligations, "due_tick") : [],
    matters: legalEnabled ? normalize(source.matters, FIELDS.matters, "filed_tick") : [],
    mergers: legalEnabled ? normalize(source.mergers, FIELDS.mergers, "proposed_tick") : [],
    mergerReviews: legalEnabled ? normalize(source.merger_reviews, FIELDS.mergerReviews, "tick") : [],
  };
}
