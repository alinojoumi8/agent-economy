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
 * PACING — WHERE THE MOTION SITS INSIDE THE DAY.
 *
 * A tick takes 44-49 s of wall clock, so the city receives one frame of truth
 * roughly every 45 s and the recorded day is paced across that window. HOW that
 * window is divided is a presentation choice and carries no claim: the data
 * says only "recorded at A in the morning slot, at B in the business slot", not
 * "stood still for 9 s then moved for 6 s". Two choices follow from that, and
 * both exist to remove frozen wall time rather than to add movement:
 *
 *   1. NO DWELL. A leg's glide occupies the whole of its wall time. Earlier this
 *      surface held each placement for 9 s and glided for 6 s, so 60 % of every
 *      beat was a still frame — a filmstrip of it contains intervals that are
 *      identical dot for dot. The eased glide now runs edge to edge.
 *
 *   2. WALL TIME IN PROPORTION TO THE PEOPLE A LEG MOVES. In this run 296 of 300
 *      people move on morning->business, 296 on business->evening, and NOBODY
 *      moves on evening->morning: every agent's evening placement names the same
 *      place as its morning placement. Under equal thirds that last leg is 15 s
 *      in which the correct rendering of the recorded data is a completely
 *      static field. Weighting by movers gives it zero wall time, and skipping
 *      it is provably invisible — every agent's position at both ends of a
 *      zero-mover leg is identical, coordinate and de-collision offset alike, so
 *      the day loops without a single chip changing pixel. See the test
 *      "a leg that moves nobody is skipped, and skipping it moves nobody".
 *
 * The invariant is untouched by both: an agent whose consecutive placements name
 * the same place still does not move, on any leg, at any t.
 */
export const DAY_MS = 45000;

/*
 * The glide's shape, and it is chosen against a measurement rather than a taste.
 *
 * STEADY BEATS SPIKY. The two live-map bars this surface is judged against move
 * at 4.0-6.4 % and 4.9-7.9 % of the frame changed per interval: a ratio of about
 * 1.6 between their busiest and quietest moment, and never a still frame. Round
 * one of this surface peaked HIGHER than both (8.4 %) and still lost, because it
 * also touched 0.008 % — the burst was never the problem, the floor was.
 *
 * Pure smoothstep is flat at both ends and crosses only 2.8 % of a leg in its
 * first tenth, which is that floor rebuilt inside every leg. Blending it with
 * the straight ramp at 0.72 gives ease'(0) = ease'(1) = 0.72 against a mid-leg
 * 1.14, so the quietest tenth of a leg now covers 7.98 % of it and the busiest
 * tenth 11.4 % — a 1.43 ratio, tighter than the bars' own 1.6 — while keeping
 * enough S that a departure and an arrival are still legible as such.
 *
 * Easing changes WHEN a chip is somewhere along its segment, never WHERE the
 * segment runs, so none of this touches what is claimed.
 */
export const GLIDE_LINEARITY = 0.72;

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

/*
 * A cluster of this many or more is drawn with a ring at its de-collision
 * radius and its own count. Below it the dots are individually countable and a
 * badge is noise; above it a starburst of 6 and a starburst of 42 are the same
 * smudge unless the number is written down.
 */
export const CROWD_MIN = 4;

const EMPTY_OFFSET = { x: 0, y: 0, cohort: 1, radius: 0 };

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function finite(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function clamp01(value) {
  return Math.min(1, Math.max(0, finite(value) ?? 0));
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
  /*
   * Anonymised occupancy is kept PER SLOT, not summed across the day. All three
   * of this run's rows are `business` rows, and folding them into one figure is
   * what made the office marker sit on the map through the evening claiming an
   * occupancy nobody recorded for the evening.
   */
  const anonymousByPlace = new Map();

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
  const regionOfPlace = new Map(places.map(place => [String(place.id), place.regionId]));

  for (const row of presence) {
    if (!row || !DAY_SLOTS.includes(row.slot)) continue;
    const placement = placementFromRow(row);
    if (!placement) continue;
    if (row.agent_id === null || row.agent_id === undefined) {
      /* Anonymised occupancy. A count at a place in a slot, never a person. */
      const key = String(placement.placeId);
      const occupancy = finite(row.occupancy) ?? 1;
      const current = anonymousByPlace.get(key) || {
        placeId: placement.placeId,
        placeName: placement.placeName,
        placeKind: placement.placeKind,
        x: placement.x,
        y: placement.y,
        slots: Object.fromEntries(DAY_SLOTS.map(slot => [slot, 0])),
        occupancy: 0,
      };
      current.slots[row.slot] += occupancy;
      current.occupancy += occupancy;
      anonymousByPlace.set(key, current);
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
      const anchors = DAY_SLOTS.map((_, index) => anchorAt(agent.placements, index))
        .map(anchor => (anchor
          ? { ...anchor, regionId: regionOfPlace.get(String(anchor.placeId)) ?? null }
          : anchor));
      if (anchors.some(anchor => anchor === null)) return null;
      const missingSlots = DAY_SLOTS.filter(slot => !agent.placements[slot]);
      const moves = anchors.some((anchor, index) =>
        anchor.placeId !== anchors[(index + 1) % anchors.length].placeId);
      /*
       * The 97 people whose day crosses a border. They are the only marks that
       * ever occupy the middle of the field — every other journey stays inside
       * one territory — so they are drawn a size up: at maximum spread there is
       * then something on screen whose identity survives a glance.
       */
      const regions = new Set(anchors.map(anchor => anchor.regionId).filter(id => id !== null));
      return { ...agent, anchors, missingSlots, moves, longHaul: moves && regions.size > 1 };
    })
    .filter(Boolean)
    .sort((left, right) => Number(left.id) - Number(right.id));

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
    crowds: crowdCensus(agents, places),
    civic: map?.civic || null,
    bounds: cityBounds(places, agents),
    counts: {
      agents: agents.length,
      places: places.length,
      recordedPlacements: agents.reduce(
        (total, agent) => total + DAY_SLOTS.filter(slot => agent.placements[slot]).length, 0),
      commuters: agents.filter(agent => agent.moves).length,
      longHaul: agents.filter(agent => agent.longHaul).length,
      withoutFullDay: agents.filter(agent => agent.missingSlots.length > 0).length,
      anonymised: anonymous.reduce((total, item) => total + item.occupancy, 0),
      slots: slotCounts,
      sources: sourceCounts,
    },
  };
}

/**
 * How many people the recorded data puts at each place, in each slot.
 *
 * A count, per slot, of the chips that are actually drawn there — not the
 * payload's own `place.occupancy`, which is a different population (it folds in
 * the anonymised rows) and would print a number the field does not show.
 */
export function crowdCensus(agents = [], places = []) {
  const byPlace = new Map();
  for (const agent of agents) {
    for (const slot of DAY_SLOTS) {
      const placement = agent.placements?.[slot];
      if (!placement) continue;
      const key = String(placement.placeId);
      const entry = byPlace.get(key) || {
        placeId: placement.placeId,
        name: placement.placeName,
        kind: placement.placeKind,
        x: placement.x,
        y: placement.y,
        slots: Object.fromEntries(DAY_SLOTS.map(item => [item, 0])),
        peak: 0,
      };
      entry.slots[slot] += 1;
      entry.peak = Math.max(entry.peak, entry.slots[slot]);
      byPlace.set(key, entry);
    }
  }
  const named = new Map(places.map(place => [String(place.id), place]));
  return [...byPlace.values()]
    .map(entry => ({ ...entry, name: entry.name || named.get(String(entry.placeId))?.name || null }))
    .sort((left, right) => right.peak - left.peak);
}

/**
 * How much of a leg's wall time each recorded slot owns, at parameter `t`.
 *
 * The leg leaves the `from` slot and arrives at the `to` slot, so the weight
 * moves from one to the other exactly as the chips do. Marks that belong to a
 * slot — a crowd's count, an anonymised office's occupancy — fade on this, so
 * a figure recorded only for `business` is never on screen during the evening.
 */
export function slotWeights(clock) {
  const weights = DAY_SLOTS.map(() => 0);
  if (!clock) return weights;
  const eased = clamp01(finite(clock.ease) ?? easeTravel(clock.t));
  const from = clock.beatIndex % DAY_SLOTS.length;
  const to = clock.nextIndex ?? (from + 1) % DAY_SLOTS.length;
  weights[from] += 1 - eased;
  weights[to] += eased;
  return weights;
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
export function placeCohorts(agents = [], {
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
  const discs = new Map();
  for (const [placeKey, list] of members) {
    const ordered = [...list].sort((left, right) =>
      stableHash(`${placeKey}:${left}`) - stableHash(`${placeKey}:${right}`) || left - right);
    const cohort = ordered.length;
    discs.set(placeKey, {
      members: ordered,
      cohort,
      radius: cohort < 2 ? 0 : Math.min(maxRadius, pitch * Math.sqrt(cohort)),
      rotation: (stableHash(`place:${placeKey}`) / 4294967296) * Math.PI * 2,
    });
  }
  return discs;
}

export function decollisionLayout(agents = [], options = {}) {
  const offsets = new Map();
  for (const [placeKey, disc] of placeCohorts(agents, options)) {
    disc.members.forEach((agentId, rank) => {
      const unit = disc.cohort < 2 ? 0 : Math.sqrt((rank + 0.5) / disc.cohort);
      const angle = disc.rotation + rank * GOLDEN_ANGLE;
      offsets.set(offsetKey(agentId, placeKey), {
        x: Math.cos(angle) * unit * disc.radius,
        y: Math.sin(angle) * unit * disc.radius,
        cohort: disc.cohort,
        radius: disc.radius,
      });
    });
  }
  return offsets;
}

export function offsetFor(offsets, agentId, placeId) {
  return offsets?.get(offsetKey(agentId, placeId)) || EMPTY_OFFSET;
}

/**
 * The day's legs, and how much wall time each one owns.
 *
 * A leg's share is the share of the day's movement it carries. A leg that moves
 * nobody is given none — see the pacing note at the top of this file — and a
 * day in which nobody moves at all falls back to equal shares so the clock
 * still turns and the phases still name themselves.
 */
export function legPlan(agents = [], { dayMs = DAY_MS } = {}) {
  const movers = DAY_SLOTS.map((_, index) => agents.filter(agent => {
    const from = agent.anchors?.[index];
    const to = agent.anchors?.[(index + 1) % DAY_SLOTS.length];
    return Boolean(from && to && from.placeId !== to.placeId);
  }).length);
  const total = movers.reduce((sum, count) => sum + count, 0);
  const share = total > 0
    ? movers.map(count => count / total)
    : DAY_SLOTS.map(() => 1 / DAY_SLOTS.length);

  let cursor = 0;
  const legs = share.map((fraction, index) => {
    const ms = fraction * dayMs;
    const leg = {
      index,
      fromIndex: index,
      toIndex: (index + 1) % DAY_SLOTS.length,
      fromSlot: DAY_SLOTS[index],
      toSlot: DAY_SLOTS[(index + 1) % DAY_SLOTS.length],
      movers: movers[index],
      ms,
      startMs: cursor,
      endMs: cursor + ms,
    };
    cursor += ms;
    return leg;
  });
  return {
    dayMs: cursor > 0 ? cursor : dayMs,
    legs,
    movers,
    walked: legs.filter(leg => leg.ms > 0),
    weighted: total > 0,
  };
}

let evenPlanCache = null;
function evenPlan() {
  if (!evenPlanCache) evenPlanCache = legPlan([], { dayMs: DAY_MS });
  return evenPlanCache;
}

/**
 * Where the recorded day has got to, `elapsedMs` after the tick's frame landed.
 *
 * Driven by wall clock, never by the transport. The socket is silent between
 * ticks and indefinitely while paused, so a city that waited for a push would
 * stand still for the ~45 s that matter — and forever on a paused run, which is
 * the normal development condition.
 *
 * There is no dwell: `t` runs the full width of the leg, so there is no wall
 * time in which the field is frozen.
 */
export function dayClock(elapsedMs, plan) {
  const active = plan?.walked?.length ? plan : evenPlan();
  const dayMs = Math.max(1, active.dayMs);
  const total = Math.max(0, finite(elapsedMs) ?? 0);
  const cycle = Math.floor(total / dayMs);
  const within = total - cycle * dayMs;

  const walked = active.walked;
  let leg = walked[walked.length - 1];
  for (const candidate of walked) {
    if (within < candidate.endMs) { leg = candidate; break; }
  }
  const t = leg.ms > 0 ? clamp01((within - leg.startMs) / leg.ms) : 0;
  const ease = easeTravel(t);
  return {
    cycle,
    within,
    legIndex: leg.index,
    legMs: leg.ms,
    legMovers: leg.movers,
    beatIndex: leg.fromIndex,
    nextIndex: leg.toIndex,
    slot: leg.fromSlot,
    nextSlot: leg.toSlot,
    /* The recorded slot the field most resembles right now — what the phase
       label and the sky name, so both turn with the people rather than at them. */
    nearIndex: ease < 0.5 ? leg.fromIndex : leg.toIndex,
    travelling: leg.movers > 0,
    t,
    ease,
    legProgress: t,
    dayProgress: within / dayMs,
  };
}

/**
 * The glide's shape. Monotonic on [0, 1] and fixed at both ends, so easing
 * changes WHEN a chip is somewhere along its segment and never WHERE the
 * segment runs. Blended with the straight ramp so its slowest moment still
 * covers ground — a flat-ended ease is a frozen frame at every boundary.
 */
export function easeTravel(t) {
  const clamped = clamp01(t);
  const smooth = clamped * clamped * (3 - 2 * clamped);
  return GLIDE_LINEARITY * clamped + (1 - GLIDE_LINEARITY) * smooth;
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
  const t = stationary ? 0 : clamp01(finite(clock.ease) ?? easeTravel(clock.t));
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
 *
 * `travelledPx` is how far along the leg the chip has come, in pixels. The wake
 * drawn behind the chip is exactly that stretch of the segment it has already
 * covered, so every pixel of the trail is itself on the recorded path.
 */
export function chipScreenPoint(agent, clock, projection, offsets) {
  const point = recordedPointAt(agent, clock);
  if (!point || !projection) return null;
  const base = projection.project(point.x, point.y);
  const from = offsetFor(offsets, agent.id, point.from.placeId);
  const to = offsetFor(offsets, agent.id, point.to.placeId);
  const x = base.x + from.x + (to.x - from.x) * point.t;
  const y = base.y + from.y + (to.y - from.y) * point.t;
  const origin = projection.project(point.from.x, point.from.y);
  const startX = origin.x + from.x;
  const startY = origin.y + from.y;
  return {
    x,
    y,
    offsetX: from.x + (to.x - from.x) * point.t,
    offsetY: from.y + (to.y - from.y) * point.t,
    travelledPx: Math.hypot(x - startX, y - startY),
    headingDeg: point.moving ? (Math.atan2(y - startY, x - startX) * 180) / Math.PI : 0,
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

/**
 * The convex hull of a set of points, by monotone chain.
 *
 * TERRITORY IS RECORDED DATA. Every place carries a `region_id` and a
 * coordinate, so the ground a polity holds is the hull of its own places — a
 * derivation, not an invention. Nothing is drawn outside the outermost place a
 * region actually owns.
 */
export function convexHull(points = []) {
  const sorted = points
    .filter(point => Number.isFinite(point?.x) && Number.isFinite(point?.y))
    .map(point => ({ x: point.x, y: point.y }))
    .sort((left, right) => left.x - right.x || left.y - right.y);
  const unique = sorted.filter((point, index) =>
    index === 0 || point.x !== sorted[index - 1].x || point.y !== sorted[index - 1].y);
  if (unique.length < 3) return unique;

  const cross = (o, a, b) => (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x);
  const lower = [];
  for (const point of unique) {
    while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], point) <= 0) {
      lower.pop();
    }
    lower.push(point);
  }
  const upper = [];
  for (let index = unique.length - 1; index >= 0; index -= 1) {
    const point = unique[index];
    while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], point) <= 0) {
      upper.pop();
    }
    upper.push(point);
  }
  lower.pop();
  upper.pop();
  return lower.concat(upper);
}

/**
 * A closed path around a hull, pushed `pad` pixels outward from its centroid
 * and rounded at the corners. The pad is why no place mark sits exactly on the
 * boundary line; the rounding is why a 24-vertex hull does not read as a saw.
 */
export function hullPath(points = [], { pad = 0, round = true } = {}) {
  const list = points.filter(point => Number.isFinite(point?.x) && Number.isFinite(point?.y));
  if (list.length < 3) return "";
  const cx = list.reduce((sum, point) => sum + point.x, 0) / list.length;
  const cy = list.reduce((sum, point) => sum + point.y, 0) / list.length;
  const grown = list.map(point => {
    const dx = point.x - cx;
    const dy = point.y - cy;
    const length = Math.hypot(dx, dy) || 1;
    return { x: point.x + (dx / length) * pad, y: point.y + (dy / length) * pad };
  });
  const fix = value => Math.round(value * 100) / 100;
  if (!round) return `M ${grown.map(point => `${fix(point.x)} ${fix(point.y)}`).join(" L ")} Z`;

  const mid = (a, b) => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 });
  const start = mid(grown[grown.length - 1], grown[0]);
  let path = `M ${fix(start.x)} ${fix(start.y)}`;
  for (let index = 0; index < grown.length; index += 1) {
    const corner = grown[index];
    const next = grown[(index + 1) % grown.length];
    const seam = mid(corner, next);
    path += ` Q ${fix(corner.x)} ${fix(corner.y)} ${fix(seam.x)} ${fix(seam.y)}`;
  }
  return `${path} Z`;
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
