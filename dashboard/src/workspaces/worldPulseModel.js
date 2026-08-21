const EXCEPTIONAL_EVENT = /reject|fail|denie|denied|bankrupt|default|halt|breach|violat/i;

const CATEGORY_RULES = [
  {
    key: "work",
    match: /employ|hire|job|wage|labor|work|skill/i,
    label: "Work & livelihoods",
    headline: "Work changed",
    why: "This committed event changes a recorded work, skill, or income relationship.",
  },
  {
    key: "housing",
    match: /rent|house|home|residen|lease|mortgage/i,
    label: "Housing",
    headline: "Housing changed",
    why: "This committed event changes a recorded housing or residence relationship.",
  },
  {
    key: "public",
    match: /elect|vote|policy|law|court|case|permit|tax|govern|coalition/i,
    label: "Civic life",
    headline: "Public direction changed",
    why: "This committed event changes a public rule, institution, or civic process.",
  },
  {
    key: "health",
    match: /health|ill|disease|epidem|hospital|care/i,
    label: "Health",
    headline: "Health conditions changed",
    why: "This committed event changes a recorded health or care condition.",
  },
  {
    key: "city",
    match: /construct|build|project|place|infrastructure/i,
    label: "City making",
    headline: "City work advanced",
    why: "This committed event changes a recorded place, project, or construction lifecycle.",
  },
  {
    key: "information",
    match: /message|article|news|publish|communicat|claim/i,
    label: "Public information",
    headline: "Information moved",
    why: "This committed event changes the public information available to authorized observers.",
  },
  {
    key: "exchange",
    match: /sale|trade|order|market|price|goods|bank|credit|loan|payment/i,
    label: "Exchange",
    headline: "Exchange changed",
    why: "This committed event changes a recorded market, payment, or financial relationship.",
  },
];

function finiteNumber(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function strictInteger(value, minimum) {
  if (typeof value !== "number" && typeof value !== "string") return null;
  if (typeof value === "string" && value.trim() === "") return null;
  const number = Number(value);
  return Number.isSafeInteger(number) && number >= minimum ? number : null;
}

function humanize(value) {
  const words = String(value || "event")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replaceAll("_", " ")
    .replaceAll("-", " ")
    .replace(/\s+/g, " ")
    .trim();
  return words ? words[0].toUpperCase() + words.slice(1) : "Event";
}

function categoryFor(kind) {
  const text = String(kind || "");
  return CATEGORY_RULES.find(rule => rule.match.test(text)) || {
    key: "other",
    label: "World event",
    headline: humanize(text),
    why: "The event is committed, but this briefing does not infer effects that are not present in the public evidence.",
  };
}

function toneFor(event) {
  const kind = String(event?.kind || "");
  const importance = finiteNumber(event?.importance);
  if (EXCEPTIONAL_EVENT.test(kind) || importance >= 3) return "critical";
  if (importance >= 1.5) return "notice";
  return "quiet";
}

function normalizeEvent(event) {
  const id = strictInteger(event?.id, 1);
  const tick = strictInteger(event?.tick, 0);
  const subjectType = event?.subject_type ? humanize(event.subject_type) : "World";
  const subjectId = strictInteger(event?.subject_id, 1);
  const category = categoryFor(event?.kind);
  const phase = event?.phase ? humanize(event.phase) : "Phase not exposed";
  const subject = subjectId === null ? subjectType : `${subjectType} #${subjectId}`;
  return {
    eventId: id,
    tick,
    category: category.label,
    categoryKey: category.key,
    headline: category.headline,
    kind: humanize(event?.kind),
    summary: `${subject} · ${phase}${tick === null ? "" : ` · committed at tick ${tick}`}`,
    why: category.why,
    importance: finiteNumber(event?.importance),
    tone: toneFor(event),
    evidenceRef: id === null ? null : `EV-${id}`,
  };
}

/**
 * Build a small editorial briefing from privacy-safe event envelope fields.
 * Event payloads are deliberately ignored: this function has no code path that
 * can copy a private body, URL, rationale, or provider output into the UI.
 */
export function buildPulseSignals(events, limit = 3) {
  const ranked = (Array.isArray(events) ? events : [])
    .map(normalizeEvent)
    .sort((left, right) => (
      right.importance - left.importance
      || finiteNumber(right.tick, -1) - finiteNumber(left.tick, -1)
      || finiteNumber(right.eventId, -1) - finiteNumber(left.eventId, -1)
    ));

  const selected = [];
  const seenCategories = new Set();
  for (const signal of ranked) {
    if (selected.length >= limit) break;
    if (seenCategories.has(signal.categoryKey)) continue;
    selected.push(signal);
    seenCategories.add(signal.categoryKey);
  }
  for (const signal of ranked) {
    if (selected.length >= limit) break;
    if (!selected.includes(signal)) selected.push(signal);
  }
  if (selected.length) return selected;

  return [{
    eventId: null,
    tick: null,
    category: "World event",
    categoryKey: "other",
    headline: "No committed change at this cursor",
    kind: "No event",
    summary: "The public event projection returned no committed events.",
    why: "Nothing is inferred from missing evidence. Move the cursor or return to live to inspect another state.",
    importance: 0,
    tone: "quiet",
    evidenceRef: null,
  }];
}

export function buildPulseTimeline(events, limit = 36) {
  return (Array.isArray(events) ? events : [])
    .map(event => {
      const eventId = strictInteger(event?.id, 1);
      const tick = strictInteger(event?.tick, 0);
      if (eventId === null || tick === null) return null;
      return {
        eventId,
        tick,
        kind: humanize(event?.kind),
        importance: finiteNumber(event?.importance),
      };
    })
    .filter(event => event !== null)
    .sort((left, right) => left.tick - right.tick || left.eventId - right.eventId)
    .slice(-limit);
}

function coordinate(value) {
  if (typeof value !== "number" && typeof value !== "string") return null;
  if (typeof value === "string" && value.trim() === "") return null;
  const number = Number(value);
  if (Number.isFinite(number)) {
    const percent = Math.abs(number) <= 1 ? number * 100 : number;
    return Math.max(6, Math.min(94, Math.round(percent * 10) / 10));
  }
  return null;
}

export function normalizePulseWorld(data = {}) {
  const regions = Array.isArray(data.regions) ? data.regions : [];
  const agents = Array.isArray(data.agents) ? data.agents : [];
  const organizations = Array.isArray(data.organizations) ? data.organizations : [];
  const populations = new Map();
  for (const agent of agents) {
    const regionId = strictInteger(agent?.region_id, 1);
    if (regionId === null) continue;
    populations.set(regionId, (populations.get(regionId) || 0) + 1);
  }
  const normalizedRegions = [];
  for (const region of regions) {
    const id = strictInteger(region?.id, 1);
    if (id === null) continue;
    normalizedRegions.push({
      id,
      name: String(region?.name || region?.region_key || `Region ${id}`),
      key: String(region?.region_key || id),
      currency: region?.currency_code ? String(region.currency_code) : null,
      population: populations.get(id) || 0,
      x: coordinate(region?.x),
      y: coordinate(region?.y),
    });
  }

  return {
    enabled: Boolean(data.enabled || regions.length),
    regions: normalizedRegions,
    population: agents.length,
    activeOrganizations: organizations.filter(row => row?.active !== false).length,
    tradeCount: finiteNumber(data.summary?.trade_count),
    migrationCount: finiteNumber(data.summary?.migration_count),
    constructionCount: finiteNumber(
      data.summary?.construction_projects,
      Array.isArray(data.construction_projects) ? data.construction_projects.length : 0,
    ),
  };
}

export function pulseViewMode(observerTick, envelopeTick) {
  const historical = observerTick !== "live";
  const cursorTick = historical ? observerTick : envelopeTick;
  const numericTick = Number(cursorTick);
  return {
    historical,
    eyebrow: historical ? "Historical observer briefing" : "Live observer briefing",
    cursor: Number.isFinite(numericTick) ? `Tick ${numericTick}` : "Cursor pending",
  };
}

export function ledgerInvariantState(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return { state: "unreported", balance: null };
  }
  return { state: value === 0 ? "balanced" : "exceptional", balance: value };
}
