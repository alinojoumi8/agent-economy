const nonnegative = value => Number.isSafeInteger(value) && value >= 0;
const positive = value => nonnegative(value) && value > 0;
const unique = values => new Set(values).size === values.length;
function householdRecord(item) {
  return item && positive(item.id) && typeof item.name === "string" && Array.isArray(item.members)
    && item.members.length > 0 && unique(item.members.map(member => member?.agent_id))
    && item.members.every(member => member && positive(member.agent_id) && typeof member.name === "string"
      && nonnegative(member.age_years) && nonnegative(member.joined_tick) && nonnegative(member.legacy_dependents)
      && ["child", "school_age", "adult"].includes(member.age_band) && ["adult", "dependent"].includes(member.role)
      && (member.guardian_agent_id === null || positive(member.guardian_agent_id)))
    && Array.isArray(item.child_needs) && unique(item.child_needs.map(need => need?.child_agent_id))
    && item.child_needs.every(need => need && item.members.some(member => member.agent_id === need.child_agent_id)
      && [need.required_units, need.purchased_units, need.spent_cents, need.care_required_minutes].every(nonnegative)
      && need.purchased_units <= need.required_units && typeof need.goods_sector === "string"
      && (need.currency_code === null || typeof need.currency_code === "string")
      && ["unassigned", "time_allocation_pending", "not_required"].includes(need.care_status));
}

function institutionRecord(item) {
  return item && positive(item.bank_id) && item.id === `bank:${item.bank_id}` && item.kind === "bank"
    && typeof item.name === "string" && ["open", "failed"].includes(item.status)
    && (item.currency_code === null || typeof item.currency_code === "string");
}

function section(value, tick, source, visibility, record) {
  const valid = value && value.tick === tick && value.source === source
    && value.visibility === visibility && typeof value.available === "boolean"
    && Array.isArray(value.items) && unique(value.items.map(item => item?.id)) && value.items.every(record)
    && (value.available || value.items.length === 0);
  return valid ? value : { available: false, items: [], reason: "Records are unavailable for this city frame." };
}

export function citySociety(map, tick) {
  return {
    households: section(map?.households, tick, "recorded_household_membership", "core_members_only", householdRecord),
    institutions: section(map?.institutions, tick, "public_bank_status", "public_status_only", institutionRecord),
  };
}

export function householdForPerson(households, personId) {
  return households.available && personId != null ? households.items.find(item =>
    item.members.some(member => String(member.agent_id) === String(personId))) || null : null;
}

export function childNeedsByCurrency(needs) {
  const totals = new Map();
  for (const need of needs) {
    const currency = need.currency_code || "Unspecified currency";
    totals.set(currency, (totals.get(currency) || 0) + need.spent_cents);
  }
  return [...totals].sort(([left], [right]) => left.localeCompare(right));
}
