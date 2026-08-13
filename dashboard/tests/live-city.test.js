import assert from "node:assert/strict";
import test from "node:test";
import {
  BEAT_MS,
  DAY_MS,
  DAY_SLOTS,
  DWELL_MS,
  MAX_DECOLLISION_RADIUS_PX,
  chipScreenPoint,
  cityBounds,
  dayClock,
  decollisionLayout,
  distanceToRecordedPath,
  easeTravel,
  fitProjection,
  normalizeLiveCity,
  offsetFor,
  segmentDistance,
} from "../src/lib/liveCity.js";

/*
 * A miniature of the real payload's shapes: a commuter, a person who never
 * leaves one place, a person with no business row, two people sharing a
 * workplace, and an anonymised licensing-office row with a null agent id.
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
  regions: [{ id: 1, name: "Northstar", currency_code: "NSD", x: 0.25, y: 0.35, population: 4 }],
  places: [
    { id: 1, name: "Home", kind: "residential_district", region_id: 1, x: 0.2, y: 0.2 },
    { id: 2, name: "Works", kind: "firm_workplace", region_id: 1, x: 0.6, y: 0.5 },
    { id: 3, name: "Commons", kind: "public_commons", region_id: 1, x: 0.4, y: 0.8 },
    { id: 4, name: "Permit Office", kind: "licensing_office", region_id: 1, x: 0.5, y: 0.3 },
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
    /* anonymised occupancy: a count at a place, with no agent */
    row(null, "business", 4, 0.5, 0.3, "privacy_aggregate", { occupancy: 3, place_kind: "licensing_office" }),
  ],
};

const model = normalizeLiveCity(fixture);
const agentById = id => model.agents.find(agent => agent.id === id);

test("the recorded day is read from presence and nothing is invented", () => {
  assert.equal(model.tick, 349);
  assert.equal(model.agents.length, 4);
  assert.equal(model.counts.recordedPlacements, 11);
  assert.deepEqual(model.counts.slots, { morning: 4, business: 3, evening: 4 });

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
  assert.equal(model.counts.commuters, 2);
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

test("the day clock paces three beats of dwell-then-travel across the tick", () => {
  assert.equal(DAY_MS, BEAT_MS * DAY_SLOTS.length);

  const start = dayClock(0);
  assert.equal(start.beatIndex, 0);
  assert.equal(start.slot, "morning");
  assert.equal(start.travelling, false);

  const dwelling = dayClock(DWELL_MS - 1);
  assert.equal(dwelling.travelling, false);

  const leaving = dayClock(DWELL_MS + 1);
  assert.equal(leaving.travelling, true);
  assert.ok(leaving.t > 0 && leaving.t < 0.01);

  const arriving = dayClock(BEAT_MS - 1);
  assert.ok(arriving.t > 0.99);

  const business = dayClock(BEAT_MS);
  assert.equal(business.slot, "business");
  assert.equal(business.travelling, false);

  const evening = dayClock(BEAT_MS * 2 + 10);
  assert.equal(evening.slot, "evening");

  /* The day loops, and the loop is a loop: the same phase of the next cycle. */
  const wrapped = dayClock(DAY_MS + 25);
  assert.equal(wrapped.cycle, 1);
  assert.equal(wrapped.beatIndex, 0);
  assert.equal(wrapped.slot, "morning");
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
});

test("someone whose consecutive placements name the same place does not move", () => {
  const offsets = decollisionLayout(model.agents);
  const projection = fitProjection(model.bounds, 1440, 900, { top: 0, right: 0, bottom: 0, left: 0 });
  const resident = agentById(3);
  const held = agentById(4);

  for (const agent of [resident, held]) {
    const seen = new Set();
    for (let ms = 0; ms < DAY_MS; ms += 250) {
      const point = chipScreenPoint(agent, dayClock(ms), projection, offsets);
      seen.add(`${point.x.toFixed(9)},${point.y.toFixed(9)}`);
    }
    assert.equal(seen.size, 1, `agent ${agent.id} moved without a recorded change of place`);
  }
});

test("a commuter's rendered pixel is always on a segment between recorded points", () => {
  const offsets = decollisionLayout(model.agents);
  const projection = fitProjection(model.bounds, 1440, 900, { top: 104, right: 72, bottom: 116, left: 72 });
  const commuter = agentById(1);
  let travelled = 0;

  for (let ms = 0; ms < DAY_MS * 2; ms += 97) {
    const clock = dayClock(ms);
    const chip = chipScreenPoint(commuter, clock, projection, offsets);

    /* Undo the projection and the declared offset, then measure against the
       recorded path. Zero means the position came from recorded placements. */
    const dataX = (chip.x - chip.offsetX - projection.left) / projection.scaleX + projection.minX;
    const dataY = (chip.y - chip.offsetY - projection.top) / projection.scaleY + projection.minY;
    const residual = distanceToRecordedPath(commuter, dataX, dataY);
    assert.ok(residual < 1e-9,
      `at ${ms}ms the position was ${residual} off the recorded path`);
    if (chip.point.moving) travelled += 1;
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
  assert.equal(bounds.maxX, 0.6);
  assert.equal(bounds.minY, 0.2);
  assert.equal(bounds.maxY, 0.8);
  assert.deepEqual(cityBounds([], []), { minX: 0, minY: 0, maxX: 1, maxY: 1 });
});

test("an empty or malformed payload yields an empty city, not a guessed one", () => {
  const empty = normalizeLiveCity(null);
  assert.deepEqual(empty.agents, []);
  assert.equal(empty.counts.agents, 0);

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
});
