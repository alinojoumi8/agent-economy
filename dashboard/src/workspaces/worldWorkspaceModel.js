function rows(value) {
  return Array.isArray(value) ? value.filter(item => item && typeof item === "object") : [];
}

function stableId(value) {
  const numeric = Number(value);
  if (Number.isSafeInteger(numeric)) return [0, numeric];
  return [1, String(value ?? "")];
}

function compareRows(left, right) {
  const leftId = stableId(left.id);
  const rightId = stableId(right.id);
  if (leftId[0] !== rightId[0]) return leftId[0] - rightId[0];
  if (leftId[1] < rightId[1]) return -1;
  if (leftId[1] > rightId[1]) return 1;
  return String(left.name ?? "").localeCompare(String(right.name ?? ""));
}

function publicMapRow(row) {
  const normalized = { ...row };
  for (const coordinate of ["x", "y"]) {
    if (!Number.isFinite(normalized[coordinate])) delete normalized[coordinate];
  }
  return normalized;
}

function regionId(value) {
  const numeric = Number(value);
  return Number.isSafeInteger(numeric) && numeric > 0 ? numeric : null;
}

export function normalizeWorldWorkspace(data = {}) {
  const source = data && typeof data === "object" ? data : {};
  const regions = rows(source.regions).map(publicMapRow).sort(compareRows);
  const agents = rows(source.agents).map(publicMapRow).sort(compareRows);
  const organizations = rows(source.organizations).map(publicMapRow).sort(compareRows);
  const places = rows(source.places).map(publicMapRow).sort(compareRows);
  const presence = rows(source.presence).map(row => ({ ...row })).sort(compareRows);
  const knownRegions = new Set(regions.map(region => regionId(region.id)).filter(Boolean));
  const seenFlows = new Set();
  const flows = rows(source.flows)
    .filter(flow => {
      const origin = regionId(flow.origin_region_id);
      const destination = regionId(flow.destination_region_id);
      if (!origin || !destination || !knownRegions.has(origin) || !knownRegions.has(destination)) {
        return false;
      }
      const key = `${String(flow.kind ?? "")}:${String(flow.id ?? "")}`;
      if (seenFlows.has(key)) return false;
      seenFlows.add(key);
      return true;
    })
    .map(flow => ({ ...flow }))
    .sort((left, right) => String(left.kind ?? "").localeCompare(String(right.kind ?? "")) || compareRows(left, right));
  const currencies = [...new Set(regions
    .map(region => typeof region.currency_code === "string" ? region.currency_code : "")
    .filter(Boolean))].sort();

  return {
    enabled: source.enabled === true,
    regions,
    agents,
    organizations,
    places,
    presence,
    flows,
    summary: {
      population: agents.length,
      activeOrganizations: organizations.filter(organization => organization.active !== false).length,
      currencies,
      migrationCount: flows.filter(flow => flow.kind === "migration").length,
      tradeCount: flows.filter(flow => flow.kind === "trade").length,
    },
  };
}
