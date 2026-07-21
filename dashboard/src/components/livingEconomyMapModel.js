const asArray = value => Array.isArray(value) ? value : [];
const finite = (value, fallback = 0) => Number.isFinite(Number(value)) ? Number(value) : fallback;
const clamp = (value, minimum, maximum) => Math.min(maximum, Math.max(minimum, value));
const numericId = value => Number.isFinite(Number(value)) ? Number(value) : null;

function specializations(region) {
  if (Array.isArray(region.specialization)) return region.specialization.map(String);
  try {
    const parsed = JSON.parse(region.specialization_json || "[]");
    return Array.isArray(parsed) ? parsed.map(String) : [];
  } catch {
    return [];
  }
}

export function aggregateFlows(flows, regionIds) {
  const allowed = regionIds instanceof Set ? regionIds : new Set();
  const grouped = new Map();

  for (const flow of asArray(flows)) {
    const kind = flow?.kind === "trade" || flow?.kind === "migration" ? flow.kind : null;
    const sourceId = numericId(flow?.source_region_id);
    const targetId = numericId(flow?.target_region_id);
    if (!kind || !allowed.has(sourceId) || !allowed.has(targetId) || sourceId === targetId) continue;

    const id = `${kind}:${sourceId}:${targetId}`;
    const status = String(flow?.status || "unknown");
    const magnitude = Math.max(0, finite(flow?.magnitude, 1));
    const route = grouped.get(id) || {
      id,
      kind,
      source_region_id: sourceId,
      target_region_id: targetId,
      magnitude: 0,
      count: 0,
      statuses: {},
    };
    route.magnitude += magnitude;
    route.count += 1;
    route.statuses[status] = (route.statuses[status] || 0) + 1;
    grouped.set(id, route);
  }

  return [...grouped.values()].sort((left, right) => left.id.localeCompare(right.id));
}

export function normalizeMapData(map) {
  const payload = map && typeof map === "object" ? map : {};
  const baseRegions = asArray(payload.regions).map(region => {
    const id = numericId(region?.id);
    if (id === null) return null;
    return {
      ...region,
      id,
      name: String(region?.name || region?.region_key || `Region ${id}`),
      x: clamp(finite(region?.x, 0.5), 0.08, 0.92),
      y: clamp(finite(region?.y, 0.5), 0.08, 0.92),
      population: Math.max(0, finite(region?.population, 0)),
      population_target: Math.max(0, finite(region?.population_target, 0)),
      specialization: specializations(region || {}),
    };
  }).filter(Boolean);
  const regionIds = new Set(baseRegions.map(region => region.id));
  const firms = asArray(payload.firms)
    .map(firm => ({ ...firm, region_id: numericId(firm?.region_id) }))
    .filter(firm => regionIds.has(firm.region_id));
  const coreAgents = asArray(payload.core_agents)
    .map(agent => ({ ...agent, region_id: numericId(agent?.region_id) }))
    .filter(agent => regionIds.has(agent.region_id))
    .slice(0, 100);
  const routes = aggregateFlows(payload.flows, regionIds);

  const regions = baseRegions.map(region => ({
    ...region,
    firmItems: firms.filter(firm => firm.region_id === region.id),
    coreAgentItems: coreAgents.filter(agent => agent.region_id === region.id),
    flowTotals: {
      trade: { inbound: 0, outbound: 0 },
      migration: { inbound: 0, outbound: 0 },
    },
  }));
  const byId = new Map(regions.map(region => [region.id, region]));
  for (const route of routes) {
    byId.get(route.source_region_id).flowTotals[route.kind].outbound += route.magnitude;
    byId.get(route.target_region_id).flowTotals[route.kind].inbound += route.magnitude;
  }

  return { enabled: payload.enabled !== false, regions, routes, firms, coreAgents };
}
