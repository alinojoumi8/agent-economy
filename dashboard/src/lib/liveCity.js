/*
 * LIVE CITY — the recorded day, and nothing but the recorded day.
 *
 * THE ONE RULE. Every position this module produces is either exactly a
 * recorded placement or a point on the straight segment between two
 * consecutive recorded placements. The world records three placements per
 * agent per tick — its `morning`, `business` and `evening` place — and those
 * three points are the whole itinerary. There is no waypoint, no detour, no
 * drift, no milling, and no motion for an agent whose consecutive slots name
 * the same place. `distanceToRecordedPath` exists so that claim can be
 * asserted against rendered pixels rather than believed.
 *
 * WHAT IS INTERPOLATED, AND WHY THAT IS SAID OUT LOUD. The tick is the unit of
 * truth; the journey between two placements is not recorded and is drawn as a
 * straight glide. The surface states this permanently — see the disclosure
 * strip in LiveCity.tsx — because a moving chip otherwise reads as a tracked
 * position.
 *
 * WHAT IS NOT MODELLED HERE, DELIBERATELY. `privacy_aggregate` presence rows
 * carry `agent_id: null`; licensing-office occupants are anonymised on purpose
 * and surface as a count at the office, never as a person. Nothing in this
 * file invents a rumour path, a conversation, or a social edge: no transmitter
 * is recorded for any of them.
 */
import { stableHash } from "./civicCity.js";

/** The three placements the world records for an agent each tick, in order. */
export const DAY_SLOTS = ["morning", "business", "evening"];

/*
 * PACING. A tick takes 44-49 s of wall clock and MORNING alone is ~45 s of it,
 * so the city receives one frame of truth roughly every 45 s. The recorded day
 * is paced across that window: three beats of 15 s, each a 9 s dwell at a
 * recorded placement followed by a 6 s glide to the next one. The dwell is the
 * longer half on purpose — an agent's tick is mostly *at* a place.
 */
export const DWELL_MS = 9000;
export const TRAVEL_MS = 6000;
export const BEAT_MS = DWELL_MS + TRAVEL_MS;
export const DAY_MS = BEAT_MS * DAY_SLOTS.length;

/*
 * DE-COLLISION. Position is the *place's* coordinate, so every agent at one
 * firm shares one pixel unless they are spread. The spread is a golden-angle
 * spiral: rank k of n sits at radius sqrt((k + 1/2) / n), which fills a disc
 * evenly, at angle k * the golden angle, which never repeats a direction. The
 * disc grows as sqrt(n) so a crowd of 42 stays a crowd and does not become a
 * district. A place with a single occupant gets no offset at all, so 205 of
 * this run's 252 occupied places draw exactly on their recorded coordinate.
 */
export const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));
export const DECOLLISION_PITCH_PX = 4.2;
export const MAX_DECOLLISION_RADIUS_PX = 34;

const EMPTY_OFFSET = { x: 0, y: 0, cohort: 1, radius: 0 };

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function finite(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

/** `agentId@placeId` — the key an offset is stable under. */
export function offsetKey(agentId, placeId) {
  return `${agentId}@${placeId}`;
}

function placementFromRow(row) {
  const x = finite(row.x);
  const y = finite(row.y);
  if (x === null || y === null) return null;
  return {
    slot: row.slot,
    placeId: row.place_id,
    placeName: row.place_name || null,
    placeKind: row.place_kind || null,
    sourceType: row.source_type || null,
    x,
    y,
  };
}

/**
 * The anchor an agent occupies during beat `index`.
 *
 * A recorded placement is used verbatim. When a slot has no recorded row — four
 * agents in this run have no `business` placement — the agent HOLDS at its last
 * recorded placement and is flagged `recorded: false`. Holding is not a claim
 * that the agent was there: it is the refusal to invent a position, and the
 * surface draws those agents dimmed and says so. Fabricating a plausible
 * workplace would have been the alternative, and it would have been a lie.
 */
function anchorAt(placements, index) {
  const slot = DAY_SLOTS[index];
  const recorded = placements[slot];
  if (recorded) return { ...recorded, slot, recorded: true };
  for (let back = 1; back < DAY_SLOTS.length; back += 1) {
    const earlier = placements[DAY_SLOTS[(index - back + DAY_SLOTS.length) % DAY_SLOTS.length]];
    if (earlier) return { ...earlier, slot, recorded: false };
  }
  return null;
}

/**
 * Turn `/api/v2/map` into the city's recorded day.
 *
 * Nothing is derived that the payload does not carry. Agents come only from
 * presence rows that have an id, a known slot, and both coordinates; a row
 * missing any of those is dropped rather than repaired.
 */
export function normalizeLiveCity(map) {
  const presence = asArray(map?.presence);
  const byAgent = new Map();
  const anonymousByPlace = new Map();

  for (const row of presence) {
    if (!row || !DAY_SLOTS.includes(row.slot)) continue;
    const placement = placementFromRow(row);
    if (!placement) continue;
    if (row.agent_id === null || row.agent_id === undefined) {
      /* Anonymised occupancy. A count at a place, never a person. */
      const key = String(placement.placeId);
      const current = anonymousByPlace.get(key);
      const occupancy = finite(row.occupancy) ?? 1;
      if (current) current.occupancy += occupancy;
      else anonymousByPlace.set(key, {
        placeId: placement.placeId,
        placeName: placement.placeName,
        placeKind: placement.placeKind,
        x: placement.x,
        y: placement.y,
        occupancy,
      });
      continue;
    }
    const key = String(row.agent_id);
    const agent = byAgent.get(key) || {
      id: row.agent_id,
      name: row.name || `Agent ${row.agent_id}`,
      role: row.role || null,
      occupation: row.occupation || null,
      placements: {},
    };
    agent.name = row.name || agent.name;
    agent.role = agent.role || row.role || null;
    agent.occupation = agent.occupation || row.occupation || null;
    agent.placements[row.slot] = placement;
    byAgent.set(key, agent);
  }

  const agents = [...byAgent.values()]
    .map(agent => {
      const anchors = DAY_SLOTS.map((_, index) => anchorAt(agent.placements, index));
      if (anchors.some(anchor => anchor === null)) return null;
      const missingSlots = DAY_SLOTS.filter(slot => !agent.placements[slot]);
      const moves = anchors.some((anchor, index) =>
        anchor.placeId !== anchors[(index + 1) % anchors.length].placeId);
      return { ...agent, anchors, missingSlots, moves };
    })
    .filter(Boolean)
    .sort((left, right) => Number(left.id) - Number(right.id));

  const places = asArray(map?.places)
    .map(place => {
      const x = finite(place.x);
      const y = finite(place.y);
      if (x === null || y === null) return null;
      return {
        id: place.id,
        name: place.name || `Place ${place.id}`,
        kind: place.kind || "place",
        regionId: place.region_id ?? null,
        capacity: finite(place.capacity),
        x,
        y,
        occupancy: place.occupancy && typeof place.occupancy === "object" ? place.occupancy : null,
      };
    })
    .filter(Boolean);

  const regions = asArray(map?.regions)
    .map(region => {
      const x = finite(region.x);
      const y = finite(region.y);
      if (x === null || y === null) return null;
      return {
        id: region.id,
        name: region.name || `Region ${region.id}`,
        currency: region.currency_code || null,
        population: finite(region.population),
        firms: finite(region.firms),
        x,
        y,
      };
    })
    .filter(Boolean);

  const anonymous = [...anonymousByPlace.values()];
  const slotCounts = Object.fromEntries(DAY_SLOTS.map(slot => [
    slot, agents.filter(agent => agent.placements[slot]).length,
  ]));
  const sourceCounts = {};
  for (const agent of agents) {
    for (const slot of DAY_SLOTS) {
      const placement = agent.placements[slot];
      if (!placement?.sourceType) continue;
      sourceCounts[placement.sourceType] = (sourceCounts[placement.sourceType] || 0) + 1;
    }
  }

  return {
    enabled: map?.enabled !== false,
    tick: finite(map?.civic?.tick) ?? finite(presence[0]?.tick),
    agents,
    places,
    regions,
    anonymous,
    civic: map?.civic || null,
    bounds: cityBounds(places, agents),
    counts: {
      agents: agents.length,
      places: places.length,
      recordedPlacements: agents.reduce(
        (total, agent) => total + DAY_SLOTS.filter(slot => agent.placements[slot]).length, 0),
      commuters: agents.filter(agent => agent.moves).length,
      withoutFullDay: agents.filter(agent => agent.missingSlots.length > 0).length,
      anonymised: anonymous.reduce((total, item) => total + item.occupancy, 0),
      slots: slotCounts,
      sources: sourceCounts,
    },
  };
}

/**
 * The extent the camera frames. Places are the stable geography — they outlive
 * any one tick's occupancy — so they set the bounds, with recorded agent points
 * folded in so nothing can ever fall outside the frame.
 */
export function cityBounds(places = [], agents = []) {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  const visit = (x, y) => {
    if (x < minX) minX = x;
    if (y < minY) minY = y;
    if (x > maxX) maxX = x;
    if (y > maxY) maxY = y;
  };
  for (const place of places) visit(place.x, place.y);
  for (const agent of agents) for (const anchor of agent.anchors || []) visit(anchor.x, anchor.y);
  if (!Number.isFinite(minX)) return { minX: 0, minY: 0, maxX: 1, maxY: 1 };
  return { minX, minY, maxX, maxY };
}

/**
 * A stable screen-space offset per (agent, place).
 *
 * Keyed on the PLACE and not on the slot, which is what makes "an agent whose
 * consecutive slots are the same place does not move" exactly true: the same
 * place yields the same offset in every beat, so the chip is pixel-identical
 * rather than nearly so. Membership is the union of every slot's occupants at
 * that place, so the disc is sized for the busiest moment of the day and a
 * cluster never re-packs mid-tick.
 */
export function decollisionLayout(agents = [], {
  pitch = DECOLLISION_PITCH_PX, maxRadius = MAX_DECOLLISION_RADIUS_PX,
} = {}) {
  const members = new Map();
  for (const agent of agents) {
    for (const slot of DAY_SLOTS) {
      const placement = agent.placements?.[slot];
      if (!placement) continue;
      const key = String(placement.placeId);
      const list = members.get(key) || [];
      if (!list.includes(agent.id)) list.push(agent.id);
      members.set(key, list);
    }
  }

  const offsets = new Map();
  for (const [placeKey, list] of members) {
    const ordered = [...list].sort((left, right) =>
      stableHash(`${placeKey}:${left}`) - stableHash(`${placeKey}:${right}`) || left - right);
    const cohort = ordered.length;
    const radius = cohort < 2 ? 0 : Math.min(maxRadius, pitch * Math.sqrt(cohort));
    const rotation = (stableHash(`place:${placeKey}`) / 4294967296) * Math.PI * 2;
    ordered.forEach((agentId, rank) => {
      const unit = cohort < 2 ? 0 : Math.sqrt((rank + 0.5) / cohort);
      const angle = rotation + rank * GOLDEN_ANGLE;
      offsets.set(offsetKey(agentId, placeKey), {
        x: Math.cos(angle) * unit * radius,
        y: Math.sin(angle) * unit * radius,
        cohort,
        radius,
      });
    });
  }
  return offsets;
}

export function offsetFor(offsets, agentId, placeId) {
  return offsets?.get(offsetKey(agentId, placeId)) || EMPTY_OFFSET;
}

/**
 * Where the recorded day has got to, `elapsedMs` after the tick's frame landed.
 *
 * Driven by wall clock, never by the transport. The socket is silent between
 * ticks and indefinitely while paused, so a city that waited for a push would
 * stand still for the ~45 s that matter — and forever on a paused run, which is
 * the normal development condition.
 */
export function dayClock(elapsedMs, { dayMs = DAY_MS } = {}) {
  const total = Math.max(0, finite(elapsedMs) ?? 0);
  const cycle = Math.floor(total / dayMs);
  const within = total - cycle * dayMs;
  const beatIndex = Math.min(DAY_SLOTS.length - 1, Math.floor(within / BEAT_MS));
  const inBeat = within - beatIndex * BEAT_MS;
  const travelling = inBeat >= DWELL_MS;
  return {
    cycle,
    within,
    beatIndex,
    slot: DAY_SLOTS[beatIndex],
    nextSlot: DAY_SLOTS[(beatIndex + 1) % DAY_SLOTS.length],
    travelling,
    t: travelling ? Math.min(1, (inBeat - DWELL_MS) / TRAVEL_MS) : 0,
    beatProgress: inBeat / BEAT_MS,
    dayProgress: within / dayMs,
  };
}

/**
 * Smoothstep. Monotonic on [0, 1] and fixed at both ends, so easing changes
 * WHEN a chip is somewhere along its segment and never WHERE the segment runs.
 */
export function easeTravel(t) {
  const clamped = Math.min(1, Math.max(0, finite(t) ?? 0));
  return clamped * clamped * (3 - 2 * clamped);
}

/**
 * The agent's position in the map's own normalised coordinates.
 *
 * Returns the two recorded anchors it lies between and the eased parameter, so
 * a caller can check the claim rather than take it.
 */
export function recordedPointAt(agent, clock) {
  const anchors = agent?.anchors;
  if (!anchors?.length) return null;
  const from = anchors[clock.beatIndex % anchors.length];
  const to = anchors[(clock.beatIndex + 1) % anchors.length];
  if (!from || !to) return null;
  const stationary = from.placeId === to.placeId;
  const t = stationary || !clock.travelling ? 0 : easeTravel(clock.t);
  return {
    x: from.x + (to.x - from.x) * t,
    y: from.y + (to.y - from.y) * t,
    from,
    to,
    t,
    moving: t > 0,
    stationary,
  };
}

/**
 * The pixel the chip is drawn at: the interpolated recorded point, plus the
 * de-collision offset interpolated between the same two places. Because the
 * offset is a property of (agent, place), a leg that starts and ends at one
 * place contributes exactly zero movement.
 */
export function chipScreenPoint(agent, clock, projection, offsets) {
  const point = recordedPointAt(agent, clock);
  if (!point || !projection) return null;
  const base = projection.project(point.x, point.y);
  const from = offsetFor(offsets, agent.id, point.from.placeId);
  const to = offsetFor(offsets, agent.id, point.to.placeId);
  return {
    x: base.x + from.x + (to.x - from.x) * point.t,
    y: base.y + from.y + (to.y - from.y) * point.t,
    offsetX: from.x + (to.x - from.x) * point.t,
    offsetY: from.y + (to.y - from.y) * point.t,
    point,
  };
}

/**
 * Fit the city's extent to the viewport.
 *
 * An affine map, per axis, with room reserved for the overlaid chrome. Affine
 * is the point: it carries segments to segments, so "this pixel is on the line
 * between two recorded placements" survives the projection and can be checked
 * on either side of it.
 */
export function fitProjection(bounds, width, height, inset = {}) {
  const top = finite(inset.top) ?? 0;
  const right = finite(inset.right) ?? 0;
  const bottom = finite(inset.bottom) ?? 0;
  const left = finite(inset.left) ?? 0;
  const minX = finite(bounds?.minX) ?? 0;
  const minY = finite(bounds?.minY) ?? 0;
  const spanX = Math.max(1e-9, (finite(bounds?.maxX) ?? 1) - minX);
  const spanY = Math.max(1e-9, (finite(bounds?.maxY) ?? 1) - minY);
  const usableWidth = Math.max(1, width - left - right);
  const usableHeight = Math.max(1, height - top - bottom);
  const scaleX = usableWidth / spanX;
  const scaleY = usableHeight / spanY;
  return {
    minX,
    minY,
    scaleX,
    scaleY,
    left,
    top,
    width,
    height,
    project(x, y) {
      return { x: left + (x - minX) * scaleX, y: top + (y - minY) * scaleY };
    },
  };
}

/** Shortest distance from a point to a segment, in whatever space it is given. */
export function segmentDistance(px, py, ax, ay, bx, by) {
  const dx = bx - ax;
  const dy = by - ay;
  const lengthSquared = dx * dx + dy * dy;
  if (lengthSquared === 0) return Math.hypot(px - ax, py - ay);
  const t = Math.min(1, Math.max(0, ((px - ax) * dx + (py - ay) * dy) / lengthSquared));
  return Math.hypot(px - (ax + dx * t), py - (ay + dy * t));
}

/**
 * THE ASSERTION, as a function.
 *
 * How far a claimed position is from the closed path through the agent's
 * recorded placements. Zero means the position is a recorded placement or lies
 * on a segment between two consecutive ones. Anything else is a fabricated
 * position, and this is what the frame-sequence check measures against rendered
 * pixels — with the de-collision offset removed first, since that offset is the
 * one deliberate, bounded, declared displacement on this surface.
 */
export function distanceToRecordedPath(agent, x, y) {
  const anchors = agent?.anchors || [];
  if (!anchors.length) return Infinity;
  let best = Infinity;
  for (let index = 0; index < anchors.length; index += 1) {
    const from = anchors[index];
    const to = anchors[(index + 1) % anchors.length];
    best = Math.min(best, segmentDistance(x, y, from.x, from.y, to.x, to.y));
  }
  return best;
}
