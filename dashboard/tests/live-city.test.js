import assert from "node:assert/strict";
import test from "node:test";
import {
  CROWD_MIN,
  DAY_MS,
  DAY_SLOTS,
  GLIDE_LINEARITY,
  MAX_DECOLLISION_RADIUS_PX,
  chipScreenPoint,
  cityBounds,
  convexHull,
  crowdCensus,
  dayClock,
  decollisionLayout,
  distanceToRecordedPath,
  easeTravel,
  fitProjection,
  hullPath,
  legPlan,
  normalizeLiveCity,
  offsetFor,
  placeCohorts,
  segmentDistance,
  slotWeights,
} from "../src/lib/liveCity.js";

/*
 * A miniature of the real payload's shapes: a commuter, a person who never
 * leaves one place, a person with no business row, two people sharing a
 * workplace, someone whose day crosses a regional border, and an anonymised
 * licensing-office row with a null agent id.
 *
 * It also reproduces the run's most consequential shape: EVERY agent's evening
 * placement names the same place as its morning placement, so the third leg of
 * the day moves nobody at all.
 */
function row(agentId, slot, placeId, x, y, sourceType, extra = {}) {
  return {
    tick: 349,
    slot,
    agent_id: agentId,
    name: agentId === null ? null : `Agent ${agentId}`,
    role: agentId === null ? null : "resident",
    occupation: agentId === null ? null : "worker",
    place_id: placeId,
    place_name: `Place ${placeId}`,
    place_kind: sourceType === "routine_home" ? "residential_district" : "firm_workplace",
    x,
    y,
    source_type: sourceType,
    ...extra,
  };
}

const fixture = {
  enabled: true,
  civic: { tick: 349 },
  regions: [
    { id: 1, name: "Northstar", currency_code: "NSD", x: 0.25, y: 0.35, population: 5 },
    { id: 2, name: "Ironvale", currency_code: "IVC", x: 0.85, y: 0.55, population: 1 },
  ],
  places: [
    { id: 1, name: "Home", kind: "residential_district", region_id: 1, x: 0.2, y: 0.2 },
    { id: 2, name: "Works", kind: "firm_workplace", region_id: 1, x: 0.6, y: 0.5 },
    { id: 3, name: "Commons", kind: "public_commons", region_id: 1, x: 0.4, y: 0.8 },
    { id: 4, name: "Permit Office", kind: "licensing_office", region_id: 1, x: 0.5, y: 0.3 },
    { id: 5, name: "Far Works", kind: "firm_workplace", region_id: 2, x: 0.9, y: 0.6 },
  ],
  presence: [
    /* 1: home -> work -> home, the ordinary commute */
    row(1, "morning", 1, 0.2, 0.2, "routine_home"),
    row(1, "business", 2, 0.6, 0.5, "routine_work"),
    row(1, "evening", 1, 0.2, 0.2, "routine_home"),
    /* 2: shares the workplace with 1, so the two must be de-collided */
    row(2, "morning", 1, 0.2, 0.2, "routine_home"),
    row(2, "business", 2, 0.6, 0.5, "routine_work"),
    row(2, "evening", 1, 0.2, 0.2, "routine_home"),
    /* 3: never leaves the commons */
    row(3, "morning", 3, 0.4, 0.8, "public_commons"),
    row(3, "business", 3, 0.4, 0.8, "public_commons"),
    row(3, "evening", 3, 0.4, 0.8, "public_commons"),
    /* 4: no business placement was recorded */
    row(4, "morning", 1, 0.2, 0.2, "routine_home"),
    row(4, "evening", 1, 0.2, 0.2, "routine_home"),
    /* 5: works in the other region — the day crosses a border */
    row(5, "morning", 1, 0.2, 0.2, "routine_home"),
    row(5, "business", 5, 0.9, 0.6, "routine_work"),
    row(5, "evening", 1, 0.2, 0.2, "routine_home"),
    /* anonymised occupancy: a count at a place, with no agent */
    row(null, "business", 4, 0.5, 0.3, "privacy_aggregate", { occupancy: 3, place_kind: "licensing_office" }),
  ],
};

const model = normalizeLiveCity(fixture);
const plan = legPlan(model.agents);
const agentById = id => model.agents.find(agent => agent.id === id);

test("the recorded day is read from presence and nothing is invented", () => {
  assert.equal(model.tick, 349);
  assert.equal(model.agents.length, 5);
  assert.equal(model.counts.recordedPlacements, 14);
  assert.deepEqual(model.counts.slots, { morning: 5, business: 4, evening: 5 });

  /* The anonymised row never becomes a person. */
  assert.equal(model.anonymous.length, 1);
  assert.equal(model.anonymous[0].occupancy, 3);
  assert.equal(model.counts.anonymised, 3);
  assert.ok(model.agents.every(agent => agent.id !== null && agent.id !== undefined));

  /* A missing slot is flagged and held, never filled with a guess. */
  const held = agentById(4);
  assert.deepEqual(held.missingSlots, ["business"]);
  assert.equal(held.anchors[1].recorded, false);
  assert.equal(held.anchors[1].placeId, 1);
  assert.equal(held.moves, false);
  assert.ok(model.agents.filter(agent => agent.id !== 4).every(agent =>
    agent.anchors.every(anchor => anchor.recorded)));
  assert.equal(model.counts.withoutFullDay, 1);
  assert.equal(model.counts.commuters, 3);

  /* The one person whose day crosses a border is the one whose placements sit
     in two different regions — read off place.region_id, never guessed. */
  assert.equal(model.counts.longHaul, 1);
  assert.equal(agentById(5).longHaul, true);
  assert.equal(agentById(1).longHaul, false);
});

test("anonymised occupancy is kept in the slot it was recorded in", () => {
  /* Every anonymised row in the real payload is a `business` row. Summing them
     across the day is what left a permanent label on the map asserting an
     evening occupancy the world never recorded. */
  assert.deepEqual(model.anonymous[0].slots, { morning: 0, business: 3, evening: 0 });
});

test("every anchor coordinate is a coordinate the payload recorded", () => {
  const recorded = new Set(fixture.presence
    .filter(item => item.agent_id !== null)
    .map(item => `${item.x},${item.y}`));
  for (const agent of model.agents) {
    for (const anchor of agent.anchors) {
      assert.ok(recorded.has(`${anchor.x},${anchor.y}`),
        `agent ${agent.id} anchor ${anchor.slot} is not a recorded coordinate`);
    }
  }
});

test("a leg's wall time is the share of the day's movement it carries", () => {
  assert.deepEqual(plan.movers, [3, 3, 0]);
  const [outbound, homeward, overnight] = plan.legs;
  assert.equal(overnight.movers, 0);
  assert.equal(overnight.ms, 0, "a leg that moves nobody is given no wall time");
  assert.ok(Math.abs(outbound.ms - DAY_MS / 2) < 1e-9);
  assert.ok(Math.abs(homeward.ms - DAY_MS / 2) < 1e-9);
  assert.equal(plan.walked.length, 2);
  assert.ok(Math.abs(plan.dayMs - DAY_MS) < 1e-9);

  /* A city in which nobody moves at all still has a clock that turns. */
  const still = legPlan([{ anchors: [{ placeId: 1 }, { placeId: 1 }, { placeId: 1 }] }]);
  assert.equal(still.weighted, false);
  assert.equal(still.walked.length, 3);
});

test("a leg that moves nobody is skipped, and skipping it moves nobody", () => {
  /*
   * THE LICENCE FOR THE PACING CHANGE. Dropping the zero-mover leg is only
   * honest if it is invisible — if every agent's position at the end of the leg
   * before it is identical to its position at the start of the leg after it.
   * Both ends name the same place, so both the coordinate AND the de-collision
   * offset are the same, and the day loops without one chip changing pixel.
   */
  const offsets = decollisionLayout(model.agents);
  const projection = fitProjection(model.bounds, 1440, 900, { top: 108, right: 268, bottom: 132, left: 72 });
  const endOfDay = dayClock(plan.dayMs - 1e-6, plan);
  const startOfDay = dayClock(0, plan);

  for (const agent of model.agents) {
    const last = chipScreenPoint(agent, endOfDay, projection, offsets);
    const first = chipScreenPoint(agent, startOfDay, projection, offsets);
    assert.ok(Math.hypot(last.x - first.x, last.y - first.y) < 1e-6,
      `agent ${agent.id} jumps across the skipped leg`);
  }
});

test("the day clock runs the glide edge to edge, with no dwell anywhere", () => {
  const legMs = plan.legs[0].ms;

  const start = dayClock(0, plan);
  assert.equal(start.slot, "morning");
  assert.equal(start.nextSlot, "business");
  assert.equal(start.t, 0);

  /* There is no held interval at the head of a leg: motion begins immediately
     and every sample inside the leg is strictly further along than the last. */
  let previous = -1;
  for (let ms = 0; ms <= legMs; ms += legMs / 40) {
    const clock = dayClock(Math.min(ms, legMs - 1e-6), plan);
    assert.ok(clock.ease > previous, `the glide stalled at ${ms} ms`);
    previous = clock.ease;
  }

  const second = dayClock(legMs + 10, plan);
  assert.equal(second.slot, "business");
  assert.equal(second.nextSlot, "evening");

  /* The phase the field most resembles hands over at the half-way point, so the
     sky and the label turn with the people rather than at them. */
  assert.equal(dayClock(legMs * 0.2, plan).nearIndex, 0);
  assert.equal(dayClock(legMs * 0.8, plan).nearIndex, 1);

  /* The day loops, and the loop is a loop: the same phase of the next cycle. */
  const wrapped = dayClock(plan.dayMs + 25, plan);
  assert.equal(wrapped.cycle, 1);
  assert.equal(wrapped.slot, "morning");
  assert.ok(wrapped.t > 0 && wrapped.t < 0.01);
});

test("no interval of the day is a still frame for the people it moves", () => {
  /*
   * The measured defect from round one, as an assertion. Sampled across a whole
   * day at the interval the frame sequence is captured at, every agent the
   * current leg moves must be somewhere new at every step.
   */
  const offsets = decollisionLayout(model.agents);
  const projection = fitProjection(model.bounds, 1440, 900, { top: 108, right: 268, bottom: 132, left: 72 });
  const step = 1500;
  let intervals = 0;

  for (let ms = 0; ms + step < plan.dayMs; ms += step) {
    const before = dayClock(ms, plan);
    const after = dayClock(ms + step, plan);
    /* Only compare inside one leg; a boundary is a legitimate change of heading. */
    if (before.legIndex !== after.legIndex) continue;
    intervals += 1;
    for (const agent of model.agents) {
      const from = agent.anchors[before.beatIndex];
      const to = agent.anchors[before.nextIndex];
      if (from.placeId === to.placeId) continue;
      const a = chipScreenPoint(agent, before, projection, offsets);
      const b = chipScreenPoint(agent, after, projection, offsets);
      assert.ok(Math.hypot(b.x - a.x, b.y - a.y) > 1,
        `agent ${agent.id} did not move between ${ms} ms and ${ms + step} ms`);
    }
  }
  assert.ok(intervals >= 20, "the sweep did not cover enough of the day");
});

test("easing changes when a chip is on its segment, never where the segment runs", () => {
  assert.equal(easeTravel(0), 0);
  assert.equal(easeTravel(1), 1);
  assert.equal(easeTravel(-4), 0);
  assert.equal(easeTravel(9), 1);
  let previous = -1;
  for (let step = 0; step <= 20; step += 1) {
    const value = easeTravel(step / 20);
    assert.ok(value >= previous, "easing must be monotonic");
    assert.ok(value >= 0 && value <= 1, "easing must stay inside the segment");
    previous = value;
  }

  /*
   * The floor under the velocity, which is the whole point of blending the
   * smoothstep with a straight ramp: the quietest tenth of a leg still covers a
   * substantial share of it, so no sampling interval can land on two identical
   * positions. Pure smoothstep manages 2.8 % here.
   */
  assert.ok(easeTravel(0.1) > 0.07, `the first tenth crossed only ${easeTravel(0.1)}`);
  assert.ok(1 - easeTravel(0.9) > 0.07, "the last tenth of a leg is near-frozen");
  const fastest = easeTravel(0.55) - easeTravel(0.45);
  const slowest = easeTravel(0.1) - easeTravel(0);
  assert.ok(fastest / slowest < 1.7, "the glide is spikier than the bars it is judged against");
  assert.ok(GLIDE_LINEARITY > 0 && GLIDE_LINEARITY < 1);
});

test("slot weight hands over from the leg's origin to its destination", () => {
  const legMs = plan.legs[0].ms;
  assert.deepEqual(slotWeights(dayClock(0, plan)).map(value => Number(value.toFixed(3))), [1, 0, 0]);
  const mid = slotWeights(dayClock(legMs / 2, plan));
  assert.ok(Math.abs(mid[0] - 0.5) < 0.01 && Math.abs(mid[1] - 0.5) < 0.01);
  const arriving = slotWeights(dayClock(legMs - 1e-6, plan));
  assert.ok(arriving[1] > 0.999);
  /* A slot no leg is touching carries no weight, so a mark that belongs to it is
     not on the field. */
  assert.equal(arriving[2], 0);
});

test("crowds are counted per slot from the people actually drawn", () => {
  const crowds = crowdCensus(model.agents, model.places);
  const home = crowds.find(crowd => crowd.placeId === 1);
  assert.deepEqual(home.slots, { morning: 4, business: 0, evening: 4 });
  assert.equal(home.peak, 4);
  assert.ok(home.peak >= CROWD_MIN, "the fixture must exercise the badge threshold");

  const works = crowds.find(crowd => crowd.placeId === 2);
  assert.deepEqual(works.slots, { morning: 0, business: 2, evening: 0 });

  /* The census counts chips, not the payload's own occupancy figure, which
     folds in the anonymised rows and would print a number the field cannot
     show. Place 4 holds only anonymised occupancy, so no crowd is claimed. */
  assert.equal(crowds.some(crowd => crowd.placeId === 4), false);
  assert.deepEqual(model.crowds.map(crowd => crowd.placeId).sort(), [1, 2, 3, 5]);
});

test("co-located people are de-collided deterministically and within the declared radius", () => {
  const offsets = decollisionLayout(model.agents);
  const first = offsetFor(offsets, 1, 2);
  const second = offsetFor(offsets, 2, 2);

  /* Two people at one workplace no longer share a pixel. */
  assert.notDeepEqual([first.x, first.y], [second.x, second.y]);
  assert.equal(first.cohort, 2);

  /* Bounded, so the offset can never carry a chip to another place. */
  for (const offset of offsets.values()) {
    assert.ok(Math.hypot(offset.x, offset.y) <= MAX_DECOLLISION_RADIUS_PX + 1e-9);
  }

  /* A place with a single occupant is drawn exactly on its coordinate. */
  assert.deepEqual([offsetFor(offsets, 3, 3).x, offsetFor(offsets, 3, 3).y], [0, 0]);

  /* Stable across rebuilds — the same input yields byte-identical offsets. */
  const rebuilt = decollisionLayout(normalizeLiveCity(fixture).agents);
  for (const [key, offset] of offsets) {
    assert.deepEqual(rebuilt.get(key), offset, `offset ${key} moved between builds`);
  }

  /* The ring a crowd is drawn with must be the radius the spiral occupies, or
     the number is attached to something other than the smudge it describes. */
  const discs = placeCohorts(model.agents);
  assert.equal(discs.get("1").cohort, 4);
  assert.equal(discs.get("1").radius, offsetFor(offsets, 1, 1).radius);
  assert.equal(discs.get("3").radius, 0);
});

test("someone whose consecutive placements name the same place does not move", () => {
  const offsets = decollisionLayout(model.agents);
  const projection = fitProjection(model.bounds, 1440, 900, { top: 0, right: 0, bottom: 0, left: 0 });
  const resident = agentById(3);
  const held = agentById(4);

  for (const agent of [resident, held]) {
    const seen = new Set();
    for (let ms = 0; ms < plan.dayMs; ms += 137) {
      const point = chipScreenPoint(agent, dayClock(ms, plan), projection, offsets);
      seen.add(`${point.x.toFixed(9)},${point.y.toFixed(9)}`);
    }
    assert.equal(seen.size, 1, `agent ${agent.id} moved without a recorded change of place`);
  }
});

test("a commuter's rendered pixel is always on a segment between recorded points", () => {
  const offsets = decollisionLayout(model.agents);
  const projection = fitProjection(model.bounds, 1440, 900, { top: 108, right: 268, bottom: 132, left: 72 });
  const commuter = agentById(1);
  let travelled = 0;

  for (let ms = 0; ms < plan.dayMs * 2; ms += 97) {
    const clock = dayClock(ms, plan);
    const chip = chipScreenPoint(commuter, clock, projection, offsets);

    /* Undo the projection and the declared offset, then measure against the
       recorded path. Zero means the position came from recorded placements. */
    const dataX = (chip.x - chip.offsetX - projection.left) / projection.scaleX + projection.minX;
    const dataY = (chip.y - chip.offsetY - projection.top) / projection.scaleY + projection.minY;
    const residual = distanceToRecordedPath(commuter, dataX, dataY);
    assert.ok(residual < 1e-9,
      `at ${ms}ms the position was ${residual} off the recorded path`);
    if (chip.point.moving) travelled += 1;

    /* The wake is the stretch of segment already covered, so it can never be
       longer than the distance from the leg's origin to the chip. */
    assert.ok(chip.travelledPx >= 0);
  }
  assert.ok(travelled > 0, "the commuter never travelled");
});

test("the projection is affine, so segments survive it", () => {
  const projection = fitProjection({ minX: 0.1, minY: 0.2, maxX: 0.9, maxY: 0.8 }, 1000, 500,
    { top: 10, right: 20, bottom: 30, left: 40 });
  const a = projection.project(0.1, 0.2);
  const b = projection.project(0.9, 0.8);
  assert.deepEqual([a.x, a.y], [40, 10]);
  assert.deepEqual([b.x, b.y], [1000 - 20, 500 - 30]);

  /* The midpoint of two recorded points projects to the midpoint of their
     projections. That property is what lets the pixel check be trusted. */
  const midpoint = projection.project(0.5, 0.5);
  assert.ok(Math.abs(midpoint.x - (a.x + b.x) / 2) < 1e-9);
  assert.ok(Math.abs(midpoint.y - (a.y + b.y) / 2) < 1e-9);
});

test("a territory is the hull of its own places and never reaches past them", () => {
  const own = model.places.filter(place => place.regionId === 1);
  const hull = convexHull(own);
  assert.ok(hull.length >= 3);

  /* Every vertex is a place the region actually owns — no smoothing, padding or
     rounding is allowed to put a corner where there is no place. */
  for (const vertex of hull) {
    assert.ok(own.some(place => place.x === vertex.x && place.y === vertex.y),
      "a hull vertex is not one of the region's places");
  }
  /* And every place is inside the hull's own bounding box. */
  const xs = hull.map(point => point.x);
  const ys = hull.map(point => point.y);
  for (const place of own) {
    assert.ok(place.x >= Math.min(...xs) - 1e-9 && place.x <= Math.max(...xs) + 1e-9);
    assert.ok(place.y >= Math.min(...ys) - 1e-9 && place.y <= Math.max(...ys) + 1e-9);
  }

  assert.deepEqual(convexHull([{ x: 0, y: 0 }]), [{ x: 0, y: 0 }]);
  assert.equal(hullPath([{ x: 0, y: 0 }, { x: 1, y: 1 }]), "");
  const path = hullPath([{ x: 0, y: 0 }, { x: 10, y: 0 }, { x: 10, y: 10 }, { x: 0, y: 10 }], { pad: 2 });
  assert.match(path, /^M [\d.-]+ [\d.-]+( Q [\d.-]+ [\d.-]+ [\d.-]+ [\d.-]+)+ Z$/);
});

test("distance to the recorded path detects a fabricated position", () => {
  const commuter = agentById(1);
  assert.ok(distanceToRecordedPath(commuter, 0.2, 0.2) < 1e-12);
  assert.ok(distanceToRecordedPath(commuter, 0.4, 0.35) < 1e-12);
  /* A plausible-looking detour is not on any segment, and is caught. */
  assert.ok(distanceToRecordedPath(commuter, 0.4, 0.6) > 0.1);
  assert.equal(segmentDistance(0, 5, 0, 0, 10, 0), 5);
  assert.equal(segmentDistance(-5, 0, 0, 0, 10, 0), 5);
});

test("bounds frame every place and every recorded person", () => {
  const bounds = cityBounds(model.places, model.agents);
  assert.equal(bounds.minX, 0.2);
  assert.equal(bounds.maxX, 0.9);
  assert.equal(bounds.minY, 0.2);
  assert.equal(bounds.maxY, 0.8);
  assert.deepEqual(cityBounds([], []), { minX: 0, minY: 0, maxX: 1, maxY: 1 });
});

test("an empty or malformed payload yields an empty city, not a guessed one", () => {
  const empty = normalizeLiveCity(null);
  assert.deepEqual(empty.agents, []);
  assert.equal(empty.counts.agents, 0);
  assert.deepEqual(empty.crowds, []);

  const malformed = normalizeLiveCity({
    presence: [
      { slot: "morning", agent_id: 7, place_id: 1, x: null, y: 0.2 },
      { slot: "brunch", agent_id: 8, place_id: 1, x: 0.2, y: 0.2 },
      { slot: "morning", agent_id: 9, place_id: 1, x: 0.2, y: 0.2, source_type: "routine_home" },
    ],
  });
  /* Only the well-formed row survives, and a lone morning is still a day. */
  assert.deepEqual(malformed.agents.map(agent => agent.id), [9]);
  assert.deepEqual(malformed.agents[0].missingSlots, ["business", "evening"]);
  assert.equal(malformed.agents[0].moves, false);
  assert.equal(malformed.agents[0].longHaul, false);

  /* And a city where nobody moves still has DAY_SLOTS legs and a turning clock. */
  const stillPlan = legPlan(malformed.agents);
  assert.equal(stillPlan.walked.length, DAY_SLOTS.length);
  assert.equal(dayClock(0, stillPlan).slot, "morning");
});
