import assert from "node:assert/strict";
import test from "node:test";

import {
  eventMatchesRegion,
  firmIdsForRegion,
  inspectionPresentation,
  makeInspection,
  nextRegionFocus,
  normalizeRegion,
  resolveInspection,
} from "../src/observatoryInteraction.js";

test("region focus normalizes valid regions and toggles by numeric id", () => {
  const northstar = { id: "1", region_key: "northstar", name: "Northstar Federation" };
  assert.deepEqual(normalizeRegion(northstar), {
    regionId: 1, regionKey: "northstar", regionName: "Northstar Federation",
  });
  assert.equal(normalizeRegion({ id: "bad" }), null);
  const selected = nextRegionFocus(null, northstar);
  assert.equal(selected.regionId, 1);
  assert.equal(nextRegionFocus(selected, northstar), null);
});

test("firm membership uses only active firm ids explicitly mapped to the region", () => {
  assert.deepEqual([...firmIdsForRegion({ firms: [
    { id: 8, region_id: 1 }, { id: "9", region_id: "1" },
    { id: 10, region_id: 2 }, { id: "bad", region_id: 1 },
  ] }, 1)], [8, 9]);
  assert.deepEqual([...firmIdsForRegion({ firms: null }, 1)], []);
});

test("event matching accepts only explicit top-level region keys", () => {
  assert.equal(eventMatchesRegion({ payload: { origin_region_id: "2" } }, 2), true);
  assert.equal(eventMatchesRegion({ payload: { destination_region_id: 2 } }, 2), true);
  assert.equal(eventMatchesRegion({ payload: { agent_id: 2 } }, 2), false);
  assert.equal(eventMatchesRegion({ payload: { nested: { region_id: 2 } } }, 2), false);
  assert.equal(eventMatchesRegion({ payload: null }, 2), false);
});

test("inspection resolves the newest record and retains a last-observed fallback", () => {
  const reference = makeInspection(
    { kind: "firm", id: 7, title: "Anchor Works" },
    { id: 7, name: "Anchor Works", cash_cents: 10 },
  );
  const current = resolveInspection(reference, {
    firms: [{ id: 7, name: "Anchor Works", cash_cents: 25 }],
  });
  assert.equal(current.record.cash_cents, 25);
  assert.equal(current.lastObserved, false);

  const missing = resolveInspection(reference, { firms: [] });
  assert.equal(missing.record.cash_cents, 10);
  assert.equal(missing.lastObserved, true);
});

test("inspection presentation is safe for unsupported and malformed snapshots", () => {
  const known = inspectionPresentation(makeInspection(
    { kind: "news", id: 3 },
    { id: 3, headline: "A verified headline", body: "Full story", tick: 92 },
  ), { news: [] });
  assert.equal(known.title, "A verified headline");
  assert.equal(known.narrative, "Full story");
  assert.equal(known.lastObserved, true);
  assert.ok(known.fields.some(field => field.label === "Day" && field.value === "92"));

  const unknown = inspectionPresentation(makeInspection(
    { kind: "mystery", id: null }, { circular: null },
  ), {});
  assert.equal(unknown.title, "Unsupported inspection item");
  assert.deepEqual(unknown.fields, []);
});
