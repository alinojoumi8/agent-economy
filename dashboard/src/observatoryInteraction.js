const arrays = value => Array.isArray(value) ? value : [];
const numericId = value => Number.isFinite(Number(value)) ? Number(value) : null;
const sameId = (left, right) => numericId(left) !== null && numericId(left) === numericId(right);

export const REGION_EVENT_KEYS = Object.freeze([
  "region_id", "origin_region_id", "destination_region_id",
  "source_region_id", "target_region_id", "issuer_region_id",
]);

export function normalizeRegion(region) {
  const regionId = numericId(region?.id ?? region?.regionId);
  if (regionId === null) return null;
  return {
    regionId,
    regionKey: String(region?.region_key ?? region?.regionKey ?? ""),
    regionName: String(region?.name ?? region?.regionName ?? `Region ${regionId}`),
  };
}

export function nextRegionFocus(current, region) {
  const normalized = normalizeRegion(region);
  if (!normalized) return current || null;
  return current?.regionId === normalized.regionId ? null : normalized;
}

export function firmIdsForRegion(map, regionId) {
  const selected = numericId(regionId);
  const ids = arrays(map?.firms)
    .filter(firm => selected !== null && sameId(firm?.region_id, selected))
    .map(firm => numericId(firm?.id))
    .filter(id => id !== null)
    .sort((left, right) => left - right);
  return new Set(ids);
}

export function eventMatchesRegion(event, regionId) {
  const selected = numericId(regionId);
  const payload = event?.payload;
  if (selected === null || !payload || typeof payload !== "object" || Array.isArray(payload)) return false;
  return REGION_EVENT_KEYS.some(key => sameId(payload[key], selected));
}

export function makeInspection(reference, fallbackSnapshot) {
  return {
    kind: String(reference?.kind || "unsupported"),
    id: reference?.id ?? null,
    collection: reference?.collection ? String(reference.collection) : null,
    title: reference?.title ? String(reference.title) : null,
    fallbackSnapshot: fallbackSnapshot && typeof fallbackSnapshot === "object"
      ? fallbackSnapshot : {},
  };
}

function recordsFor(reference, data) {
  const v2 = data?.v2 || {};
  const direct = {
    bank: data?.banks,
    firm: data?.firms,
    news: data?.news,
    event: data?.events,
    legal_matter: v2?.legal?.items,
    legal_obligation: v2?.legal?.obligations,
    bill: v2?.politics?.bills,
    acceptance_check: data?.acceptance?.checks,
  };
  if (reference.kind === "provider_cost") {
    return arrays(data?.cost?.[reference.collection]).map((record, index) => ({
      ...record,
      id: reference.collection === "by_model" ? record.model
        : reference.collection === "by_purpose" ? record.purpose
        : record.agent_id ?? `shared-${index}`,
    }));
  }
  if (reference.kind === "startup_record") return arrays(v2?.startups?.[reference.collection]);
  if (reference.kind === "institution") {
    const record = data?.institutions?.[reference.id];
    return record && typeof record === "object" ? [{ ...record, id: reference.id }] : [];
  }
  if (reference.kind === "macro_metric") {
    const series = arrays(data?.metrics?.[reference.id]);
    return series.length ? [{ id: reference.id, series, latest: series.at(-1)?.value }] : [];
  }
  if (reference.kind === "shock_trace") {
    const evidence = arrays(data?.acceptance?.checks)
      .find(check => check.id === "shock_traces")?.evidence;
    const trace = evidence?.[reference.id];
    return trace && typeof trace === "object" ? [{ ...trace, id: reference.id }] : [];
  }
  if (reference.kind === "startup_summary") return [];
  return arrays(direct[reference.kind]);
}

export function resolveInspection(reference, data) {
  if (!reference) return null;
  if (reference.id === null) {
    return { record: reference.fallbackSnapshot || {}, lastObserved: false };
  }
  const current = recordsFor(reference, data).find(record => sameId(record?.id, reference.id)
    || String(record?.id) === String(reference.id));
  return {
    record: current ? { ...(reference.fallbackSnapshot || {}), ...current }
      : reference.fallbackSnapshot || {},
    lastObserved: !current,
  };
}

const LABELS = {
  tick: "Day", status: "Status", kind: "Kind", phase: "Phase", importance: "Importance",
  outlet: "Outlet", outlet_name: "Outlet", tone: "Tone", truthful: "Truthful", sector: "Sector",
  slant_tags: "Slant tags", source_event_ids: "Source events", ruleset: "Ruleset",
  employees: "Employees", deposits_cents: "Deposits", reserves_cents: "Reserves",
  reserve_ratio: "Reserve ratio", loans: "Loans", loans_cents: "Loans", avg_trust: "Average trust",
  cash_cents: "Cash", price_cents: "Goods price", last_stock_price: "Stock price",
  inventory: "Inventory", inventory_qty: "Inventory", production: "Production", output: "Production",
  payroll_cents: "Payroll", revenue_cents: "Revenue",
  calls: "Calls", in_tokens: "Input tokens", out_tokens: "Output tokens", cost_usd: "Spend",
  latest: "Current value", delta: "Latest change", series: "Recent points", count: "Count",
};
const FIELD_KEYS = Object.keys(LABELS);

function scalar(value) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (Array.isArray(value)) return value.map(item => typeof item === "object"
    ? JSON.stringify(item) : String(item)).join(", ");
  if (typeof value === "object") return null;
  return String(value);
}

export function inspectionPresentation(reference, data) {
  const supported = new Set([
    "bank", "firm", "institution", "news", "macro_metric", "legal_matter",
    "legal_obligation", "bill", "startup_record", "startup_summary",
    "acceptance_check", "shock_trace", "provider_cost", "event",
  ]);
  const resolved = resolveInspection(reference, data) || { record: {}, lastObserved: false };
  const record = resolved.record && typeof resolved.record === "object" ? resolved.record : {};
  if (!supported.has(reference?.kind)) {
    return { title: "Unsupported inspection item", subtitle: "", narrative: "", fields: [], raw: record, lastObserved: resolved.lastObserved };
  }
  const title = String(reference?.title || record.headline || record.title || record.name
    || record.label || `${reference.kind.replaceAll("_", " ")} ${reference.id ?? "summary"}`);
  const subtitle = String(record.subtitle || record.model || record.purpose || record.agent_name || "");
  const narrative = String(record.body || record.reasoning || record.description || record.help || "");
  const fields = FIELD_KEYS
    .filter(key => Object.hasOwn(record, key))
    .map(key => ({ label: LABELS[key], value: scalar(record[key]) }))
    .filter(field => field.value !== null);
  return { title, subtitle, narrative, fields, raw: record, lastObserved: resolved.lastObserved };
}
