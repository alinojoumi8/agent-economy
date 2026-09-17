import { CITY_DISTRICTS, humanize } from "./civicCity.js";

const DISTRICT_COLORS = {
  institutions: [87, 131, 125, 72],
  communications: [87, 111, 148, 64],
  markets: [156, 117, 72, 70],
  health: [109, 142, 116, 64],
  work: [143, 105, 79, 66],
  commons: [118, 119, 103, 54],
};

const BUILDING_COLORS = {
  licensing_office: [201, 121, 76, 235],
  public_commons: [103, 143, 132, 225],
  firm_workplace: [181, 151, 91, 230],
  workplace: [181, 151, 91, 230],
  residence: [116, 126, 136, 218],
  organization: [126, 142, 162, 225],
};

const CONSTRUCTION_COLORS = {
  site: [128, 132, 124, 150],
  foundation: [171, 109, 72, 220],
  frame: [220, 145, 69, 225],
  shell: [219, 177, 92, 230],
  completed: [103, 155, 126, 225],
  cancelled: [175, 89, 76, 190],
};

function numeric(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function coordinate(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return null;
  const percentage = Math.abs(number) <= 1 ? number * 100 : number;
  return Math.max(2, Math.min(98, percentage));
}

function stableHash(value) {
  const text = String(value ?? "");
  let hash = 2166136261;
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function square(x, y, size) {
  const half = size / 2;
  return [
    [x - half, y - half],
    [x + half, y - half],
    [x + half, y + half],
    [x - half, y + half],
  ];
}

function constructionStage(status, workUnits, requiredWorkUnits) {
  if (status === "completed" || (requiredWorkUnits > 0 && workUnits >= requiredWorkUnits)) {
    return "completed";
  }
  if (workUnits <= 0 && status !== "building") return "site";
  const frameThreshold = Math.max(1, Math.ceil(requiredWorkUnits / 3));
  const shellThreshold = Math.max(frameThreshold, Math.ceil((requiredWorkUnits * 2) / 3));
  if (workUnits >= shellThreshold) return "shell";
  if (workUnits >= frameThreshold) return "frame";
  return "foundation";
}

function framePathsFor(x, y, size, elevation, item) {
  const half = size / 2;
  const corners = [
    [x - half, y - half],
    [x + half, y - half],
    [x + half, y + half],
    [x - half, y + half],
  ];
  const posts = corners.map(([px, py], index) => ({
    ...item,
    key: `${item.key}:post:${index}`,
    path: [[px, py, 0.2], [px, py, elevation]],
  }));
  const beams = corners.map(([px, py], index) => {
    const [nx, ny] = corners[(index + 1) % corners.length];
    return {
      ...item,
      key: `${item.key}:beam:${index}`,
      path: [[px, py, elevation], [nx, ny, elevation]],
    };
  });
  return [...posts, ...beams];
}

export function constructionStageGeometry(project = {}) {
  const status = String(project.status || "proposed").toLowerCase();
  const workUnits = Math.max(0, numeric(
    project.contributedWorkUnits ?? project.contributed?.work_units,
  ));
  const requiredWorkUnits = Math.max(0, numeric(
    project.requiredWorkUnits ?? project.requirements?.work_units,
  ));
  const fundingCents = Math.max(0, numeric(
    project.contributedFundingCents ?? project.contributed?.funding_cents,
  ));
  const requiredFundingCents = Math.max(0, numeric(
    project.requiredFundingCents ?? project.requirements?.funding_cents,
  ));
  const aggregateCount = Math.max(1, numeric(project.aggregateCount ?? project.aggregate_count, 1));
  const stage = constructionStage(status, workUnits, requiredWorkUnits);
  const x = numeric(project.x ?? project.site?.x);
  const y = numeric(project.y ?? project.site?.y);
  const size = 2.6 + Math.min(2.4, Math.sqrt(aggregateCount) * 0.45);
  const cappedWork = requiredWorkUnits > 0
    ? Math.min(requiredWorkUnits, workUnits)
    : workUnits;
  const elevations = {
    site: 0.12,
    foundation: 0.45 + Math.min(0.55, cappedWork * 0.08),
    frame: 2.4 + Math.min(2.4, cappedWork * 0.18),
    shell: 4.8 + Math.min(3.2, cappedWork * 0.2),
    completed: 7 + Math.min(5, cappedWork * 0.22),
  };
  const elevation = elevations[stage];
  const privacyAggregate = project.privacy === "aggregated_private";
  const aggregatePrefix = privacyAggregate && aggregateCount > 1
    ? `${aggregateCount} HOMES · `
    : "";
  const stageLabel = stage === "site" ? humanize(status).toUpperCase() : stage.toUpperCase();
  const cancelledPrefix = status === "cancelled" ? "CANCELLED · " : "";
  const label = `${aggregatePrefix}${cancelledPrefix}${stageLabel} · ${workUnits}/${requiredWorkUnits} WORK`;
  const item = {
    ...project,
    entityKind: "construction",
    id: project.project_id ?? project.id,
    key: `construction:${project.project_id ?? project.id}`,
    stage,
    status,
    position: [x, y, elevation + 0.45],
    polygon: square(x, y, size),
    elevation,
    color: status === "cancelled"
      ? CONSTRUCTION_COLORS.cancelled
      : CONSTRUCTION_COLORS[stage],
    lineColor: stage === "frame" ? [255, 219, 147, 245] : [72, 52, 42, 225],
    label,
    operationalPlace: stage === "completed" && project.place_id != null,
    privacyAggregate,
    tooltip: [
      project.name || `Construction project ${project.project_id ?? project.id}`,
      `${humanize(status)} · ${humanize(stage)}`,
      `Work: ${workUnits}/${requiredWorkUnits} units`,
      `Funding: ${fundingCents}/${requiredFundingCents} cents`,
      `Milestones: ${numeric(project.milestone_count)}`,
      privacyAggregate
        ? `${aggregateCount} private homes aggregated by district; owner and exact sites withheld.`
        : "Exact public or policy-authorized site.",
    ].join("\n"),
  };
  return {
    ...item,
    framePaths: stage === "frame"
      ? framePathsFor(x, y, size, elevation, item)
      : [],
  };
}

function ownerLabel(place, firms) {
  if (!place?.owner_type || place?.owner_id == null) return "Ownership not exposed";
  if (place.owner_type === "firm") {
    const firm = firms.find(item => String(item.id) === String(place.owner_id));
    return firm?.name || `Firm #${place.owner_id}`;
  }
  return `${humanize(place.owner_type)} #${place.owner_id}`;
}

/*
 * Two producers feed this scene in two vocabularies. /api/v2/world-map emits
 * origin/destination region ids with a shipment's quantity, invoice and the
 * migrant's agent id; /api/v2/map — the Observatory's path — aliases the same
 * columns to source/target and carries only a magnitude. Both are the committed
 * row, so both must draw; a flow whose endpoints match no public region is
 * still dropped rather than guessed.
 */
function flowOriginId(flow) {
  return flow.origin_region_id ?? flow.source_region_id;
}

function flowDestinationId(flow) {
  return flow.destination_region_id ?? flow.target_region_id;
}

function flowTooltip(flow) {
  if (flow.kind === "trade") {
    const invoice = flow.invoice_cents != null
      ? ` · ${numeric(flow.invoice_cents)} ${flow.invoice_currency || "minor units"}`
      : "";
    return [
      `Trade shipment #${flow.id}`,
      `${flow.originLabel} → ${flow.destinationLabel}`,
      `${numeric(flow.quantity ?? flow.magnitude)} units${invoice}`,
      `Status: ${humanize(flow.status)}`,
    ].join("\n");
  }
  const agent = flow.agent_id != null ? `Agent #${flow.agent_id} · ` : "";
  return [
    `Migration #${flow.id}`,
    `${agent}${flow.originLabel} → ${flow.destinationLabel}`,
    `Status: ${humanize(flow.status)}`,
  ].join("\n");
}

export function buildDioramaScene(
  model = {},
  visibleAgents = [],
  { showClusters = false } = {},
) {
  const firms = Array.isArray(model.firms) ? model.firms : [];
  const regions = (Array.isArray(model.regions) ? model.regions : [])
    .map(region => ({
      ...region,
      x: coordinate(region.x),
      y: coordinate(region.y),
    }))
    .filter(region => region.x !== null && region.y !== null);
  const regionById = new Map(regions.map(region => [String(region.id), region]));
  const districts = Object.values(CITY_DISTRICTS).map(district => {
    const { x, y, width, height } = district.bounds;
    return {
      ...district,
      entityKind: "district",
      color: DISTRICT_COLORS[district.id] || DISTRICT_COLORS.commons,
      polygon: [[x, y], [x + width, y], [x + width, y + height], [x, y + height]],
      center: [x + width / 2, y + height / 2, 0.12],
      elevation: 0.18,
      tooltip: `${district.name}\n${district.note}\nDistrict geometry is a derived civic layout.`,
    };
  });

  const placeIds = new Set();
  const buildings = (Array.isArray(model.places) ? model.places : []).map(place => {
    placeIds.add(String(place.id));
    const capacity = Math.max(0, numeric(place.capacity));
    const occupancy = Math.max(0, numeric(place.businessOccupancy));
    const queue = Math.max(0, numeric(place.queueDepth));
    const scaleEvidence = Math.max(capacity, occupancy, queue);
    const size = 1.7 + Math.min(2.8, Math.sqrt(scaleEvidence) / 3.5);
    const elevation = 1.8 + Math.min(16, Math.sqrt(scaleEvidence) * 1.35);
    const occupants = Array.isArray(place.occupants) ? place.occupants : [];
    const occupantCopy = occupants.length
      ? occupants.map(item => item.name || `Agent #${item.agent_id}`).join(", ")
      : place.privacyOccupancy > 0
        ? `${place.privacyOccupancy} occupants (privacy aggregate)`
        : "No public occupant identities at this tick";
    const owner = ownerLabel(place, firms);
    return {
      ...place,
      entityKind: "place",
      key: `place:${place.id}`,
      position: [numeric(place.x), numeric(place.y), elevation],
      polygon: square(numeric(place.x), numeric(place.y), size),
      elevation,
      color: BUILDING_COLORS[place.kind] || BUILDING_COLORS.organization,
      ownerLabel: owner,
      occupantCopy,
      evidenceBasis: scaleEvidence
        ? "Height derives from exposed capacity, occupancy, and queue magnitude."
        : "Minimum marker height; no scale evidence is exposed.",
      tooltip: [
        place.name || `Place #${place.id}`,
        humanize(place.kind),
        `Owner: ${owner}`,
        `Present: ${occupancy}/${capacity || "unbounded"} · queue ${queue}`,
        occupantCopy,
      ].join("\n"),
    };
  });

  firms
    .filter(firm => firm.place_id == null || !placeIds.has(String(firm.place_id)))
    .forEach(firm => {
      const employees = Math.max(0, numeric(firm.employees));
      const elevation = 2 + Math.min(16, Math.sqrt(employees) * 1.5);
      const size = 1.9 + Math.min(2.5, Math.sqrt(employees) / 3.5);
      buildings.push({
        ...firm,
        entityKind: "organization",
        key: `organization:${firm.id}`,
        position: [numeric(firm.x), numeric(firm.y), elevation],
        polygon: square(numeric(firm.x), numeric(firm.y), size),
        elevation,
        color: BUILDING_COLORS.organization,
        ownerLabel: firm.name || `Firm #${firm.id}`,
        occupantCopy: employees ? `${employees} employees` : "Employee count not exposed",
        evidenceBasis: employees
          ? "Height derives from the committed employee count."
          : "Minimum marker height; employee count is not exposed.",
        tooltip: [
          firm.name || `Firm #${firm.id}`,
          humanize(firm.sector || firm.status),
          employees ? `${employees} employees` : "Employee count not exposed",
        ].join("\n"),
      });
    });

  const constructions = (Array.isArray(model.constructionProjects)
    ? model.constructionProjects
    : [])
    .map(constructionStageGeometry);
  const constructionFrames = constructions.flatMap(item => item.framePaths);

  const agents = visibleAgents.map(agent => ({
    ...agent,
    entityKind: "agent",
    position: [numeric(agent.x), numeric(agent.y), 0.8],
    tooltip: [
      agent.name || `Agent #${agent.id}`,
      humanize(agent.role || agent.occupation || agent.kind),
      humanize(agent.activityState),
      agent.place_name || agent.district,
    ].join("\n"),
  }));
  const clusters = showClusters
    ? (Array.isArray(model.clusters) ? model.clusters : []).map(cluster => ({
      ...cluster,
      entityKind: "cluster",
      position: [numeric(cluster.x), numeric(cluster.y), 0.5],
      tooltip: `${cluster.count} ${cluster.label}\nAggregated peripheral residents; individual placement is withheld.`,
    }))
    : [];

  const flows = (Array.isArray(model.flows) ? model.flows : []).flatMap(flow => {
    const origin = regionById.get(String(flowOriginId(flow)));
    const destination = regionById.get(String(flowDestinationId(flow)));
    if (!origin || !destination) return [];
    const dx = destination.x - origin.x;
    const dy = destination.y - origin.y;
    const length = Math.max(1, Math.hypot(dx, dy));
    const direction = stableHash(`${flow.kind}:${flow.id}`) % 2 ? 1 : -1;
    const bend = Math.min(6, length * 0.14) * direction;
    const midpoint = [
      (origin.x + destination.x) / 2 - (dy / length) * bend,
      (origin.y + destination.y) / 2 + (dx / length) * bend,
      1.2,
    ];
    const item = {
      ...flow,
      entityKind: "flow",
      originLabel: origin.name || `Region #${origin.id}`,
      destinationLabel: destination.name || `Region #${destination.id}`,
      path: [[origin.x, origin.y, 1.2], midpoint, [destination.x, destination.y, 1.2]],
      color: flow.kind === "trade" ? [226, 172, 82, 205] : [100, 181, 171, 205],
    };
    return [{ ...item, tooltip: flowTooltip(item) }];
  });

  return {
    districts,
    regions,
    buildings,
    constructions,
    constructionFrames,
    agents,
    clusters,
    flows,
  };
}
