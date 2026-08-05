const ORGANIZATION_FIELDS = [
  "id", "name", "type", "status", "active", "sector", "region_id", "region_name",
  "currency_code", "founded_tick", "listed_tick", "bankrupt_tick", "employees",
  "balance_cents", "reserve_cents", "equity_cents", "reserve_requirement_bps",
  "mandate", "capacity", "leader_agent_id",
];
const CONTRACT_FIELDS = [
  "id", "contract_type", "title", "jurisdiction", "ruleset_key", "offered_tick",
  "executed_tick", "effective_tick", "expiry_tick", "terminated_tick", "status",
];
const DISCLOSURE_FIELDS = [
  "id", "tick", "firm_id", "disclosure_type", "period_start_tick", "period_end_tick",
  "facts", "source_event_ids",
];

function records(value) {
  return Array.isArray(value) ? value.filter(row => row && typeof row === "object") : [];
}

function pick(row, fields) {
  return Object.fromEntries(fields.filter(field => row[field] !== undefined).map(field => [field, row[field]]));
}

function compareId(left, right) {
  const a = Number(left.id);
  const b = Number(right.id);
  if (Number.isSafeInteger(a) && Number.isSafeInteger(b)) return a - b;
  return String(left.id ?? "").localeCompare(String(right.id ?? ""));
}

function organizationSource(source) {
  if (Array.isArray(source.organizations)) return source.organizations;
  return [
    ...records(source.firms).map(row => ({ ...row, type: "firm" })),
    ...records(source.banks).map(row => ({ ...row, type: "bank" })),
    ...records(source.institutions?.agencies).map(row => ({ ...row, type: "agency" })),
  ];
}

export function normalizeOrganizationsWorkspace(data = {}) {
  const source = data && typeof data === "object" ? data : {};
  const organizations = records(organizationSource(source))
    .map(row => pick(row, ORGANIZATION_FIELDS))
    .filter(row => row.id !== undefined)
    .sort(compareId);
  return {
    organizations,
    firms: organizations.filter(row => row.type === "firm"),
    banks: organizations.filter(row => row.type === "bank"),
    agencies: organizations.filter(row => row.type === "agency"),
    institutions: {
      legalEnabled: source.institutions?.legal_enabled === true,
      politicsEnabled: source.institutions?.politics_enabled === true,
    },
    contracts: records(source.contracts).map(row => pick(row, CONTRACT_FIELDS)).sort(compareId),
    disclosures: records(source.disclosures).map(row => pick(row, DISCLOSURE_FIELDS)).sort((left, right) => (
      Number(left.tick ?? 0) - Number(right.tick ?? 0) || compareId(left, right)
    )),
  };
}

export function filterOrganizations(organizations, filters = {}) {
  const query = String(filters.q ?? "").trim().toLowerCase();
  const matches = (value, expected) => !expected || String(value ?? "").toLowerCase() === String(expected).toLowerCase();
  return records(organizations).filter(organization => {
    if (filters.activeOnly === true && organization.active !== true) return false;
    if (!matches(organization.type, filters.type)) return false;
    if (!matches(organization.sector, filters.sector)) return false;
    if (!matches(organization.status, filters.status)) return false;
    if (filters.region && ![
      String(organization.region_id ?? "").toLowerCase(),
      String(organization.region_name ?? "").toLowerCase(),
    ].includes(String(filters.region).toLowerCase())) return false;
    if (query && ![
      organization.name, organization.type, organization.sector,
      organization.region_name, organization.status,
    ].some(value => String(value ?? "").toLowerCase().includes(query))) return false;
    return true;
  }).sort(compareId);
}
