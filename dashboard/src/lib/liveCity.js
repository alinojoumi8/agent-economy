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
 * the straight ramp gives ease'(0) = ease'(1) = the blend against a mid-leg
 * 1.5 - blend/2, while keeping enough S that a departure and an arrival are
 * still legible as such.
 *
 * ROUND THREE RAISED THE BLEND TO 0.94. The peak matters twice over now, and in
 * opposite directions. A critic measured median chip displacement at 4.8-7.5 px
 * against a median neighbour spacing of 7.6-11.4 px and could not follow one
 * chip through the dense core; the mid-leg spike is what sets that worst case.
 * At 0.94 the quietest tenth of a leg covers 9.6 % of it and the busiest 10.4 %
 * — a 1.09 ratio against the bars' own 1.6 — which lifts the FLOOR of the
 * frame-to-frame change while cutting the PEAK displacement by 11 %.
 *
 * A trace of S survives, and it has to: the blend cannot reach 1 without the
 * departure and the arrival losing the acceleration that makes them legible as
 * a departure and an arrival rather than as a conveyor.
 *
 * Easing changes WHEN a chip is somewhere along its segment, never WHERE the
 * segment runs, so none of this touches what is claimed.
 */
export const GLIDE_LINEARITY = 0.94;

/*
 * DE-COLLISION. Position is the *place's* coordinate, so every agent at one
 * firm shares one pixel unless they are spread. The spread is a golden-angle
 * spiral: rank k of n sits at radius sqrt((k + 1/2) / n), which fills a disc
 * evenly, at angle k * the golden angle, which never repeats a direction. The
 * disc grows as sqrt(n) so a crowd of 42 stays a crowd and does not become a
 * district. A place with a single occupant gets no offset at all, so 205 of
 * this run's 252 occupied places draw exactly on their recorded coordinate.
 *
 * The pitch fixes the spacing and nothing else: points laid on this spiral sit
 * pitch * sqrt(pi) apart whatever n is, so 4.8 buys an 8.5 px gap between
 * neighbours at every crowd size. Round two ran at 4.2 — a 7.4 px gap under a
 * 7 px chip, which is a chip touching its neighbour on both sides.
 */
export const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));
export const DECOLLISION_PITCH_PX = 4.8;
export const MAX_DECOLLISION_RADIUS_PX = 40;

/*
 * A cluster of this many or more is drawn with a ring at its de-collision
 * radius and its own count. Below it the dots are individually countable and a
 * badge is noise; above it a starburst of 6 and a starburst of 42 are the same
 * smudge unless the number is written down.
 */
export const CROWD_MIN = 4;

/*
 * At and above this cohort the chip is drawn down a size. The spiral's gap is
 * fixed at 8.5 px, so the only remaining lever on whether two neighbours touch
 * is the dot itself: 7 px leaves 1.5 px of sky between them, 5 px leaves 3.5.
 * Below this threshold the crowd is not dense enough for the trade to be worth
 * the loss of presence.
 */
export const DENSE_COHORT = 16;

/*
 * THE DETAIL WINDOW. Three of this run's places — a public commons holding 42,
 * and two residential districts holding 24 and 23 — sit 34 and 47 px apart at
 * whole-city zoom. Their de-collision discs therefore overlap, and the merge is
 * the "roughly 90 chips fused into one unresolvable mass" a critic measured. It
 * is not one place with ninety people in it; it is three places whose people
 * cannot be told apart at this scale, which no amount of spreading fixes
 * without moving somebody off their recorded coordinate.
 *
 * The camera is a free choice, so the answer is a second camera: an inset on
 * the densest crowd and its neighbours, at this magnification, drawn from the
 * same placements by the same rules. At 2.6x the commons' 42 sit 22 px apart.
 */
export const DETAIL_ZOOM = 2.6;

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
 *
 * `destX`/`destY` are the pixel of the RECORDED PLACEMENT the chip is bound
 * for, and `remainingPx` is the stretch of the same segment still ahead of it.
 * A cross-border chip otherwise glides into black with nothing at the far end,
 * and a reader cannot tell a journey from a drift. The destination is recorded;
 * the line to it is the rest of the one straight segment already disclosed as
 * interpolated. Nothing here is a route, and no waypoint is invented.
 */
export function chipScreenPoint(agent, clock, projection, offsets) {
  const point = recordedPointAt(agent, clock);
  if (!point || !projection) return null;
  const base = projection.project(point.x, point.y);
  /*
   * The spread scales with the camera. The de-collision offset is a screen-space
   * displacement standing in for "these people share one coordinate", so a
   * camera 2.6x closer must show it 2.6x larger — otherwise the inset magnifies
   * the ground and leaves the crowd exactly as fused as it was, which is the
   * defect it exists to answer. In DATA terms this makes the inset the more
   * faithful of the two: the same 27 px disc is 2.6x less of the map.
   */
  const spread = finite(projection.offsetScale) ?? 1;
  const raw = { from: offsetFor(offsets, agent.id, point.from.placeId), to: offsetFor(offsets, agent.id, point.to.placeId) };
  const from = { x: raw.from.x * spread, y: raw.from.y * spread };
  const to = { x: raw.to.x * spread, y: raw.to.y * spread };
  const x = base.x + from.x + (to.x - from.x) * point.t;
  const y = base.y + from.y + (to.y - from.y) * point.t;
  const origin = projection.project(point.from.x, point.from.y);
  const target = projection.project(point.to.x, point.to.y);
  const startX = origin.x + from.x;
  const startY = origin.y + from.y;
  const destX = target.x + to.x;
  const destY = target.y + to.y;
  return {
    x,
    y,
    offsetX: from.x + (to.x - from.x) * point.t,
    offsetY: from.y + (to.y - from.y) * point.t,
    travelledPx: Math.hypot(x - startX, y - startY),
    destX,
    destY,
    remainingPx: point.stationary ? 0 : Math.hypot(destX - x, destY - y),
    headingDeg: point.moving ? (Math.atan2(y - startY, x - startX) * 180) / Math.PI : 0,
    bearingDeg: point.stationary ? 0 : (Math.atan2(destY - y, destX - x) * 180) / Math.PI,
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
 * A second camera on the same recorded points.
 *
 * The same affine form as `fitProjection`, so it carries segments to segments
 * exactly as the wide view does and the pixel check works identically inside
 * the inset. It is the wide camera scaled about one data coordinate: nothing is
 * re-laid-out, re-packed or re-placed for the detail view — the inset shows the
 * same chips at the same recorded placements, larger.
 */
export function zoomProjection(base, centre, zoom, panel) {
  const factor = Math.max(1e-6, finite(zoom) ?? 1);
  const width = Math.max(1, finite(panel?.width) ?? 1);
  const height = Math.max(1, finite(panel?.height) ?? 1);
  const cx = finite(centre?.x) ?? 0;
  const cy = finite(centre?.y) ?? 0;
  const scaleX = base.scaleX * factor;
  const scaleY = base.scaleY * factor;
  const left = width / 2 - (cx - base.minX) * scaleX;
  const top = height / 2 - (cy - base.minY) * scaleY;
  return {
    minX: base.minX,
    minY: base.minY,
    scaleX,
    scaleY,
    left,
    top,
    width,
    height,
    zoom: factor,
    /* The declared de-collision displacement is magnified with the ground. */
    offsetScale: factor,
    /* The data the panel can show, so a caller can say what is inside it. */
    window: {
      minX: cx - width / (2 * scaleX),
      maxX: cx + width / (2 * scaleX),
      minY: cy - height / (2 * scaleY),
      maxY: cy + height / (2 * scaleY),
    },
    project(x, y) {
      return { x: left + (x - base.minX) * scaleX, y: top + (y - base.minY) * scaleY };
    },
  };
}

/**
 * What the detail inset is aimed at, and what falls inside it.
 *
 * The busiest recorded place in the tick, plus every place whose coordinate is
 * inside the panel at this magnification. Both are read off the data: the
 * centre is a recorded coordinate and the membership is a containment test, so
 * the inset never claims a grouping the placements do not already make.
 */
export function detailWindow(crowds = [], places = [], projection, {
  zoom = DETAIL_ZOOM, panel = { width: 0, height: 0 }, anchorRadiusPx = 0,
  /* NaN reads as "no bound" through `finite`, and keeps the inferred shape a
     box of numbers so a caller can hand this the city's own bounds. */
  bounds = { minX: NaN, minY: NaN, maxX: NaN, maxY: NaN },
} = {}) {
  const busiest = [...crowds].sort((left, right) => right.peak - left.peak)[0];
  const box = panel || { width: 0, height: 0 };
  if (!busiest || !projection || !(box.width > 0) || !(box.height > 0)) return null;
  /*
   * The aim is the busiest recorded place; the FRAMING is then slid so the
   * panel holds map rather than void. The commons this run centres on sits
   * 0.012 from the western edge of the coordinate space, so an unclamped window
   * would spend half the panel on nothing — the very defect the inset exists to
   * answer. Sliding a camera is framing and changes no position: every chip in
   * the panel is still at the placement the wide view puts it at.
   */
  const halfX = box.width / (2 * projection.scaleX * zoom);
  const halfY = box.height / (2 * projection.scaleY * zoom);
  const slide = (value, min, max, half) => {
    if (!Number.isFinite(min) || !Number.isFinite(max) || max - min <= half * 2) return value;
    return Math.min(max - half, Math.max(min + half, value));
  };
  /*
   * ...but never so far that the crowd it is aimed at falls off its own edge.
   * The anchor's spread is magnified with the ground, so the room its disc needs
   * is the same fraction of the window whatever the zoom; the panel is slid back
   * until the whole of it fits.
   */
  const discX = anchorRadiusPx / projection.scaleX;
  const discY = anchorRadiusPx / projection.scaleY;
  const pin = (value, centrePoint, room) => (room <= 0
    ? centrePoint
    : Math.min(centrePoint + room, Math.max(centrePoint - room, value)));
  const centre = {
    x: pin(slide(busiest.x, finite(bounds?.minX), finite(bounds?.maxX), halfX),
      busiest.x, halfX - discX),
    y: pin(slide(busiest.y, finite(bounds?.minY), finite(bounds?.maxY), halfY),
      busiest.y, halfY - discY),
  };
  const camera = zoomProjection(projection, centre, zoom, box);
  const inside = item => item.x >= camera.window.minX && item.x <= camera.window.maxX
    && item.y >= camera.window.minY && item.y <= camera.window.maxY;
  const held = places.filter(inside);
  return {
    camera,
    zoom,
    centre,
    anchor: busiest,
    places: held,
    /* Only the places that carry a ring — a "crowd" on this surface is a place
       CROWD_MIN or more people share, and counting every occupied place as one
       would put a figure in the caption the panel does not draw. */
    crowds: crowds.filter(crowd => inside(crowd) && crowd.peak >= CROWD_MIN),
    /* How many recorded placements the panel actually holds, per slot. */
    headcount: DAY_SLOTS.map(slot => crowds
      .filter(inside)
      .reduce((total, crowd) => total + (crowd.slots?.[slot] ?? 0), 0)),
  };
}

/**
 * Which of the chips on screen are between two places at this instant.
 *
 * Read off the same anchors and the same clock the renderer draws from, so the
 * top line counts the chips actually in the frame rather than a property of the
 * tick. A person whose two consecutive placements name one place is at a place
 * for the whole leg and is counted as such; a person the leg does move is in
 * transit until the leg lands them.
 */
export function liveCounts(agents = [], clock) {
  const counts = { inTransit: 0, atPlace: 0, arrived: 0, held: 0 };
  if (!clock) return counts;
  const eased = clamp01(finite(clock.ease) ?? easeTravel(clock.t));
  const fromIndex = clock.beatIndex ?? 0;
  const toIndex = clock.nextIndex ?? (fromIndex + 1);
  for (const agent of agents) {
    const anchors = agent?.anchors;
    if (!anchors?.length) continue;
    const from = anchors[fromIndex % anchors.length];
    const to = anchors[toIndex % anchors.length];
    if (!from || !to) continue;
    if (!from.recorded || !to.recorded) counts.held += 1;
    if (from.placeId === to.placeId) { counts.atPlace += 1; continue; }
    if (eased >= 1) { counts.atPlace += 1; counts.arrived += 1; continue; }
    if (eased <= 0) { counts.atPlace += 1; continue; }
    counts.inTransit += 1;
  }
  return counts;
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

/* ------------------------------------------------- recorded conversation -- */

/**
 * Where a recorded conversation belongs on the map, and whether it belongs
 * there at all.
 *
 * The world records a conversation as a tick, a pair of participants, a topic
 * and the lines they exchanged. It does NOT record a coordinate — so the only
 * honest place to draw one is a place the map already puts BOTH people at, in
 * the slot the conversation was recorded in. Every gate below exists to refuse
 * rather than approximate:
 *
 *   · a participant the map does not carry is not drawn. That is what keeps an
 *     anonymised resident anonymous: they reach the city as a count at a place,
 *     never as an agent, so they can never be named by this layer.
 *   · a slot whose placement was HELD rather than recorded is not drawn, because
 *     "probably still there" is not evidence of being there.
 *   · a pair the map puts in two different places is not drawn at all. They may
 *     well have spoken; this surface simply cannot say where.
 *
 * What survives is a bubble whose position, participants and words are each a
 * recorded fact. The one presentational choice is WHEN inside the leg it shows,
 * and the city says so in its disclosure.
 */
export function conversationPlacements(conversations = [], agents = [], options = {}) {
  const slot = options.slot || "evening";
  const slotIndex = DAY_SLOTS.indexOf(slot);
  if (slotIndex < 0) return [];
  const byId = new Map((agents || []).map(agent => [Number(agent.id), agent]));
  const placements = [];
  for (const conversation of conversations || []) {
    const ids = Array.isArray(conversation?.participants)
      ? conversation.participants.map(Number).filter(Number.isFinite)
      : [];
    if (ids.length < 2) continue;
    const people = ids.map(id => byId.get(id));
    if (people.some(person => !person)) continue;
    const anchors = people.map(person => person.anchors?.[slotIndex]);
    if (anchors.some(anchor => !anchor || anchor.recorded !== true)) continue;
    const placeId = anchors[0].placeId;
    if (anchors.some(anchor => anchor.placeId !== placeId)) continue;
    const lines = (conversation.messages || [])
      .slice()
      .sort((a, b) => (a.seq ?? 0) - (b.seq ?? 0))
      .map(message => ({
        speaker: message.name || byId.get(Number(message.agent_id))?.name || "",
        text: String(message.text ?? ""),
      }))
      .filter(line => line.speaker && line.text);
    placements.push({
      id: Number(conversation.id),
      placeId,
      placeName: anchors[0].placeName,
      x: anchors[0].x,
      y: anchors[0].y,
      slot,
      people: people.map(person => person.name),
      topic: String(conversation.topic ?? ""),
      lines,
    });
  }
  /* Deterministic, and stacked so two conversations at one address do not draw
     on top of each other. */
  placements.sort((a, b) => (a.placeId - b.placeId) || (a.id - b.id));
  const seen = new Map();
  for (const placement of placements) {
    const rank = seen.get(placement.placeId) ?? 0;
    placement.stackIndex = rank;
    seen.set(placement.placeId, rank + 1);
  }
  return placements;
}

/**
 * Which conversations can actually be READ where they are.
 *
 * `conversationPlacements` decides where a bubble is entitled to sit; this
 * decides whether it can be drawn there without destroying its neighbour. Two
 * conversations at the same address stack, but two at different addresses can
 * still land a few pixels apart on screen, and a pile of half-covered quotes is
 * worse than a smaller number of legible ones — an earlier round of this map was
 * rejected for exactly that, labels destroyed by what was drawn over them.
 *
 * So bubbles are placed greedily in a deterministic order and any that would
 * overlap one already placed is dropped, not nudged: moving it would put a
 * recorded conversation at an address the world did not record. The caller is
 * told how many were dropped so the surface can say so.
 */
export function packBubbles(items = [], options = {}) {
  const width = options.width ?? 260;
  const height = options.height ?? 54;
  const gap = options.gap ?? 6;
  const bounds = options.bounds || null;
  const kept = [];
  let dropped = 0;
  for (const item of items) {
    const left = item.screenX;
    const top = item.screenY - height;
    if (bounds && (left < bounds.minX || left + width > bounds.maxX
        || top < bounds.minY || top + height > bounds.maxY)) {
      dropped += 1;
      continue;
    }
    const clash = kept.some(other => (
      left < other.left + width + gap
      && left + width + gap > other.left
      && top < other.top + height + gap
      && top + height + gap > other.top));
    if (clash) { dropped += 1; continue; }
    kept.push({ ...item, left, top });
  }
  return { kept, dropped };
}
