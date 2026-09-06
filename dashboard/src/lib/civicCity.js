export const CITY_LAYERS = [
  { id: "all", label: "All activity", shortLabel: "All" },
  { id: "work", label: "Work & production", shortLabel: "Work" },
  { id: "communications", label: "Communications", shortLabel: "Comms" },
  { id: "markets", label: "Markets & capital", shortLabel: "Markets" },
  { id: "institutions", label: "Civic institutions", shortLabel: "Civic" },
  { id: "health", label: "Health & care", shortLabel: "Health" },
];

export function semanticReceiptForEvent(event, receipts = []) {
  if (!event || event.id === null || event.id === undefined) return null;
  const embedded = event.payload?.semantic_receipt;
  if (embedded && typeof embedded === "object") {
    return { ...embedded, eventId: event.id, tick: event.tick };
  }
  return receipts.find(receipt => String(receipt?.eventId) === String(event.id)) || null;
}

export const CITY_DISTRICTS = {
  institutions: {
    id: "institutions",
    name: "Civic Forum",
    note: "law, policy, and public institutions",
    bounds: { x: 7, y: 8, width: 31, height: 34 },
  },
  communications: {
    id: "communications",
    name: "Signal Ward",
    note: "news, memory, and communications",
    bounds: { x: 64, y: 7, width: 29, height: 29 },
  },
  markets: {
    id: "markets",
    name: "Exchange",
    note: "markets, credit, and insurance",
    bounds: { x: 60, y: 40, width: 34, height: 24 },
  },
  health: {
    id: "health",
    name: "Care Quarter",
    note: "health and human services",
    bounds: { x: 61, y: 69, width: 30, height: 23 },
  },
  work: {
    id: "work",
    name: "Works",
    note: "firms, labor, and production",
    bounds: { x: 8, y: 59, width: 47, height: 33 },
  },
  commons: {
    id: "commons",
    name: "Civic Commons",
    note: "households and shared life",
    bounds: { x: 39, y: 10, width: 20, height: 44 },
  },
};

const INSTITUTION_TERMS = [
  "central_banker", "credit_officer", "government", "gov_", "legislator",
  "executive", "president", "regulator", "lawyer", "judge", "lobbyist",
  "treasury", "minister", "secretary", "politic",
];
const COMMUNICATION_TERMS = [
  "editor", "reporter", "journal", "media", "news", "communications",
  "publisher", "oracle", "writer",
];
const MARKET_TERMS = [
  "exchange", "investor", "trader", "bank", "finance", "venture", "vc_",
  "insurance", "broker", "account", "economist",
];
const HEALTH_TERMS = [
  "doctor", "physician", "nurse", "hospital", "health", "care", "medical",
];

const EVENT_LAYER_TERMS = {
  communications: [
    "communication", "message", "news", "statement", "belief", "rumor",
    "conversation", "published", "broadcast", "memo",
  ],
  markets: [
    "order", "trade", "sale", "bought", "sold", "price", "ipo", "share",
    "loan", "credit", "deposit", "insurance", "policy", "market", "dividend",
  ],
  institutions: [
    "law", "bill", "vote", "court", "regulat", "government", "tax",
    "lobby", "election", "executive", "budget",
  ],
  health: ["health", "hospital", "patient", "medical", "care", "treatment"],
  work: [
    "job", "work", "hire", "wage", "production", "inventory", "firm",
    "labor", "startup", "business", "employ",
  ],
};

const ACTOR_KEY = /(agent|actor|buyer|seller|issuer|founder|borrower|lender|sender|recipient|receiver|publisher|candidate|member|voter|lobbyist|owner|person|worker|employee|proposer|controller)_ids?$/i;

function normalizeText(...values) {
  return values.filter(Boolean).join(" ").toLowerCase().replaceAll("-", "_");
}

function hasAny(value, terms) {
  return terms.some(term => value.includes(term));
}

function finiteNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function normalizedCoordinate(value) {
  const number = finiteNumber(value);
  if (number === null) return null;
  const percentage = Math.abs(number) <= 1 ? number * 100 : number;
  return Math.max(4, Math.min(96, percentage));
}

/**
 * FNV-1a over the string form of a value. Deterministic, dependency-free, and
 * stable across reloads, which is what makes it usable as the seed for any
 * layout decision that must not move between frames. Exported because the Live
 * City surface needs exactly the same guarantee for its de-collision scatter.
 */
export function stableHash(value) {
  const text = String(value ?? "");
  let hash = 2166136261;
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function asArray(value) {
  if (Array.isArray(value)) return value;
  if (Array.isArray(value?.items)) return value.items;
  return [];
}

function mergeAgents(agents, map) {
  const merged = new Map();
  asArray(map?.core_agents).forEach(agent => merged.set(String(agent.id), { ...agent }));
  asArray(map?.agents).forEach(agent => merged.set(String(agent.id), {
    ...(merged.get(String(agent.id)) || {}),
    ...agent,
  }));
  asArray(map?.presence)
    .filter(item => item?.agent_id != null && item?.slot === "business")
    .filter(item => merged.get(String(item.agent_id))?.population_tier !== "periphery")
    .forEach(item => {
      const key = String(item.agent_id);
      merged.set(key, {
        ...(merged.get(key) || {}),
        id: item.agent_id,
        name: item.name,
        role: item.role,
        occupation: item.occupation,
        x: item.x,
        y: item.y,
        place_id: item.place_id,
        place_name: item.place_name,
        place_kind: item.place_kind,
        presence_source: item.source_type,
      });
    });
  asArray(agents).forEach(agent => {
    const key = String(agent.id);
    merged.set(key, { ...(merged.get(key) || {}), ...agent });
  });
  return [...merged.values()].filter(agent => agent?.id !== null && agent?.id !== undefined);
}

function pointInDistrict(agent, index, count, districtId) {
  const district = CITY_DISTRICTS[districtId] || CITY_DISTRICTS.commons;
  const { x, y, width, height } = district.bounds;
  const columns = Math.max(3, Math.ceil(Math.sqrt(count * (width / height))));
  const rows = Math.max(1, Math.ceil(count / columns));
  const column = index % columns;
  const row = Math.floor(index / columns);
  const hash = stableHash(agent.id);
  const jitterX = ((hash & 255) / 255 - 0.5) * Math.min(2.2, width / (columns + 1) * 0.38);
  const jitterY = (((hash >>> 8) & 255) / 255 - 0.5) * Math.min(2.2, height / (rows + 1) * 0.38);
  return {
    x: x + ((column + 1) * width) / (columns + 1) + jitterX,
    y: y + ((row + 1) * height) / (rows + 1) + jitterY,
  };
}

function classifyFirmLayer(firm) {
  const value = normalizeText(firm?.sector, firm?.name, firm?.kind);
  if (hasAny(value, HEALTH_TERMS)) return "health";
  if (hasAny(value, COMMUNICATION_TERMS)) return "communications";
  if (hasAny(value, MARKET_TERMS)) return "markets";
  if (hasAny(value, INSTITUTION_TERMS)) return "institutions";
  return "work";
}

export function classifyAgentLayer(agent) {
  const value = normalizeText(agent?.role, agent?.occupation, agent?.kind);
  if (hasAny(value, HEALTH_TERMS)) return "health";
  if (hasAny(value, COMMUNICATION_TERMS)) return "communications";
  if (hasAny(value, MARKET_TERMS)) return "markets";
  if (hasAny(value, INSTITUTION_TERMS)) return "institutions";
  return "work";
}

export function classifyEventLayer(event) {
  const value = normalizeText(event?.kind, event?.phase);
  for (const layer of ["communications", "markets", "institutions", "health", "work"]) {
    if (hasAny(value, EVENT_LAYER_TERMS[layer])) return layer;
  }
  return "work";
}

export function eventActorIds(event) {
  const ids = new Set();
  const visit = (value, key = "", depth = 0) => {
    if (depth > 3 || value === null || value === undefined) return;
    if (ACTOR_KEY.test(key)) {
      const candidates = Array.isArray(value) ? value : [value];
      candidates.forEach(candidate => {
        const id = finiteNumber(candidate);
        if (id !== null) ids.add(id);
      });
      return;
    }
    if (Array.isArray(value)) {
      value.forEach(item => visit(item, key, depth + 1));
      return;
    }
    if (typeof value === "object") {
      Object.entries(value).forEach(([childKey, child]) => visit(child, childKey, depth + 1));
    }
  };
  visit(event);
  return [...ids];
}

export function humanize(value, fallback = "Not reported") {
  if (value === null || value === undefined || value === "") return fallback;
  return String(value)
    .replaceAll("_", " ")
    .replace(/\b\w/g, letter => letter.toUpperCase());
}

export function filterCityAgents(agents = [], {
  layer = "all", q = "", activeOnly = false,
} = {}) {
  const needle = String(q || "").trim().toLowerCase();
  return agents.filter(agent => {
    const layerMatch = layer === "all" || agent.layer === layer || agent.eventLayer === layer;
    const activityMatch = !activeOnly || Boolean(agent.isActive);
    const textMatch = !needle || [
      agent.name, agent.role, agent.occupation, agent.kind, agent.district,
      agent.event?.kind,
    ].some(value => String(value || "").toLowerCase().includes(needle));
    return layerMatch && activityMatch && textMatch;
  });
}

export function resolveCityFilterPatch(agents, current, update) {
  const next = { ...current, ...update };
  const visible = filterCityAgents(agents, next);
  const selected = visible.find(agent => String(agent.id) === String(next.agent))
    || visible.find(agent => agent.isActive)
    || visible.find(agent => agent.event)
    || visible[0]
    || null;
  return { ...update, agent: selected?.id ?? null };
}

export function deriveCityModel({
  agents = [], firms = [], events = [], map = null, civic = null,
  runtime = null, tick = "live", historical = false,
} = {}) {
  const people = mergeAgents(agents, map);
  const eventItems = asArray(events)
    .slice()
    .sort((left, right) => (Number(right.tick) - Number(left.tick)) || (Number(right.id) - Number(left.id)));
  const latestByAgent = new Map();
  eventItems.forEach(event => {
    eventActorIds(event).forEach(id => {
      if (!latestByAgent.has(String(id))) latestByAgent.set(String(id), event);
    });
  });
  const selectedTick = Number(
    tick === "live" ? (civic?.tick ?? eventItems[0]?.tick ?? 0) : tick,
  );
  const runtimeByAgent = new Map(
    tick === "live" && !historical
      ? asArray(runtime?.active_agents).map(activity => [String(activity.agent_id), activity])
      : [],
  );

  const grouped = new Map();
  people.forEach(agent => {
    const layer = classifyAgentLayer(agent);
    if (!grouped.has(layer)) grouped.set(layer, []);
    grouped.get(layer).push(agent);
  });

  let observedCount = 0;
  const cityAgents = [];
  grouped.forEach((group, layer) => {
    group.forEach((agent, index) => {
      const observedX = normalizedCoordinate(agent.x);
      const observedY = normalizedCoordinate(agent.y);
      const observed = observedX !== null && observedY !== null;
      if (observed) observedCount += 1;
      const point = observed
        ? { x: observedX, y: observedY }
        : pointInDistrict(agent, index, group.length, layer);
      const event = latestByAgent.get(String(agent.id)) || null;
      const runtimeActivity = runtimeByAgent.get(String(agent.id)) || null;
      const transitionEvent = event && Number(event.tick) === selectedTick ? event : null;
      const transitionState = transitionEvent
        ? String(transitionEvent.kind || "").toLowerCase() === "action_rejected"
          ? "rejected"
          : "settled"
        : null;
      const activityState = runtimeActivity?.state
        || transitionState
        || (agent.employer_id != null || agent.role ? "assigned role" : "resident");
      cityAgents.push({
        ...agent,
        ...point,
        layer,
        district: CITY_DISTRICTS[layer]?.name || CITY_DISTRICTS.commons.name,
        event,
        transitionEvent,
        runtimeActivity,
        eventLayer: event ? classifyEventLayer(event) : null,
        activityState,
        isActive: Boolean(runtimeActivity || transitionEvent),
        coordinateSource: observed ? "observed" : "derived",
      });
    });
  });

  const mapFirms = [
    ...asArray(map?.firms),
    ...asArray(map?.organizations),
  ];
  const firmSource = asArray(firms).length ? asArray(firms) : mapFirms;
  const operatingFirms = firmSource.filter(firm =>
    !["bankrupt", "closed", "inactive"].includes(String(firm?.status || "").toLowerCase()),
  );
  const cityFirms = operatingFirms.map((firm, index, list) => {
    const layer = classifyFirmLayer(firm);
    const observedX = normalizedCoordinate(firm.x);
    const observedY = normalizedCoordinate(firm.y);
    const point = observedX !== null && observedY !== null
      ? { x: observedX, y: observedY }
      : pointInDistrict({ id: `firm-${firm.id}` }, index, list.length, layer);
    return { ...firm, ...point, layer,
      coordinateSource: observedX !== null && observedY !== null ? "observed" : "derived" };
  });

  const coordinateMode = observedCount === 0
    ? "derived"
    : observedCount === cityAgents.length
      ? "observed"
      : "mixed";

  const presence = asArray(map?.presence).map(item => ({ ...item }));
  const places = asArray(map?.places).map(place => {
    const placePresence = presence.filter(
      item => String(item?.place_id) === String(place?.id),
    );
    return {
      ...place,
      x: normalizedCoordinate(place.x),
      y: normalizedCoordinate(place.y),
      businessOccupancy: Number(place?.occupancy?.business || 0),
      capacity: Number(place?.capacity || 0),
      queueDepth: Number(place?.queue_depth || 0),
      occupants: placePresence
        .filter(item => item?.agent_id != null)
        .map(item => ({
          agent_id: item.agent_id,
          name: item.name,
          role: item.role,
          slot: item.slot,
          source_type: item.source_type,
        })),
      privacyOccupancy: placePresence
        .filter(item => item?.agent_id == null)
        .reduce((total, item) => total + Number(item?.occupancy || 0), 0),
    };
  }).filter(place => place.x !== null && place.y !== null);
  const constructionSource = asArray(map?.constructionProjects).length
    ? asArray(map?.constructionProjects)
    : asArray(map?.construction_projects);
  const constructionProjects = constructionSource.map(project => ({
    ...project,
    id: project?.project_id ?? project?.id,
    x: normalizedCoordinate(project?.x ?? project?.site?.x),
    y: normalizedCoordinate(project?.y ?? project?.site?.y),
    requiredFundingCents: Number(project?.requirements?.funding_cents || 0),
    contributedFundingCents: Number(project?.contributed?.funding_cents || 0),
    requiredWorkUnits: Number(project?.requirements?.work_units || 0),
    contributedWorkUnits: Number(project?.contributed?.work_units || 0),
    aggregateCount: Number(project?.aggregate_count || 1),
  })).filter(project =>
    project.id !== null
    && project.id !== undefined
    && project.x !== null
    && project.y !== null);
  const regions = asArray(map?.regions).map(region => ({
    ...region,
    x: normalizedCoordinate(region.x),
    y: normalizedCoordinate(region.y),
  })).filter(region => region.x !== null && region.y !== null);
  const flows = asArray(map?.flows).map(flow => ({ ...flow }));
  const receipts = eventItems
    .filter(event => event?.payload?.semantic_receipt)
    .map(event => ({ eventId: event.id, tick: event.tick, ...event.payload.semantic_receipt }));
  const clusters = asArray(map?.population_clusters).map((cluster, index, list) => {
    const observedX = normalizedCoordinate(cluster.x);
    const observedY = normalizedCoordinate(cluster.y);
    const point = observedX !== null && observedY !== null
      ? { x: observedX, y: observedY }
      : pointInDistrict({ id: cluster.id || `cluster-${index}` }, index, list.length, "commons");
    return {
      ...cluster,
      ...point,
      count: Number(cluster.count || 0),
      label: String(cluster.label || "Resident cluster"),
    };
  });
  const projectedPopulation = map?.population_summary || {};
  const coreCount = Number(projectedPopulation.core
    ?? cityAgents.filter(agent => agent.population_tier !== "periphery").length);
  const population = {
    mode: map?.population_mode || "core",
    total: Number(projectedPopulation.total ?? cityAgents.length),
    core: coreCount,
    periphery: Number(projectedPopulation.periphery
      ?? Math.max(0, cityAgents.length - coreCount)),
    renderedAgents: cityAgents.length,
    clusteredAgents: Number(projectedPopulation.clustered_agents
      ?? clusters.reduce((total, cluster) => total + cluster.count, 0)),
  };

  return {
    agents: cityAgents.sort((left, right) => Number(left.id) - Number(right.id)),
    firms: cityFirms,
    places,
    constructionProjects,
    regions,
    flows,
    presence,
    receipts,
    clusters,
    population,
    civic: civic || map?.civic || null,
    events: eventItems,
    selectedTick,
    coordinateMode,
    counts: {
      agents: cityAgents.length,
      residents: population.total,
      active: cityAgents.filter(agent => agent.isActive).length,
      queued: cityAgents.filter(agent => agent.activityState === "queued").length,
      thinking: cityAgents.filter(agent => agent.activityState === "thinking").length,
      settled: cityAgents.filter(agent => agent.activityState === "settled").length,
      rejected: cityAgents.filter(agent => agent.activityState === "rejected").length,
      assigned: cityAgents.filter(agent => agent.activityState === "assigned role").length,
      firms: operatingFirms.length,
      places: places.length,
      construction: constructionProjects.length,
      queue: Number(civic?.queue?.depth || map?.civic?.queue?.depth || 0),
    },
  };
}
