import assert from "node:assert/strict";
import test from "node:test";

import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";

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

test("inspection presentation safely formats circular objects in allowlisted arrays", () => {
  const circular = {};
  circular.self = circular;
  let presentation;

  assert.doesNotThrow(() => {
    presentation = inspectionPresentation(makeInspection(
      { kind: "news", id: 4 },
      { id: 4, headline: "Circular evidence", slant_tags: [circular] },
    ), { news: [] });
  });
  assert.equal(
    presentation.fields.find(field => field.label === "Slant tags")?.value,
    "Unable to serialize value",
  );
});

test("focus bar names exactly the three region-filtered panels", async () => {
  const vite = await createServer({ appType: "custom", logLevel: "silent", server: { middlewareMode: true } });
  try {
    const { RegionFocusBar } = await vite.ssrLoadModule("/src/components/ObservatoryInteraction.jsx");
    const markup = renderToStaticMarkup(React.createElement(RegionFocusBar, {
      regionFocus: { regionId: 1, regionKey: "northstar", regionName: "Northstar Federation" },
      onClear: () => {},
    }));
    assert.match(markup, /Northstar Federation/);
    assert.match(markup, /Firms, agents, and region-tagged events/);
    assert.match(markup, /aria-label="Clear Northstar Federation region filter"/);
    assert.doesNotMatch(markup, /banks are filtered/i);
  } finally { await vite.close(); }
});

test("drawer is modeless, labelled, and exposes last-observed state", async () => {
  const vite = await createServer({ appType: "custom", logLevel: "silent", server: { middlewareMode: true } });
  try {
    const { InspectorDrawer } = await vite.ssrLoadModule("/src/components/ObservatoryInteraction.jsx");
    const snapshot = { id: 4, name: "Northstar Reserve", status: "open", deposits_cents: 500 };
    snapshot.self = snapshot;
    const inspection = makeInspection({ kind: "bank", id: 4 }, snapshot);
    const markup = renderToStaticMarkup(React.createElement(InspectorDrawer, {
      inspection, data: { banks: [] }, onClose: () => {}, headingRef: { current: null },
    }));
    assert.match(markup, /aria-label="Observatory inspector"/);
    assert.doesNotMatch(markup, /aria-modal="true"/);
    assert.match(markup, /Northstar Reserve/);
    assert.match(markup, /Last observed/);
    assert.match(markup, /Close inspector/);
    assert.match(markup, /Unable to serialize this snapshot/);
  } finally { await vite.close(); }
});

test("agent directory encodes region after search and tier and before cursor", async () => {
  const vite = await createServer({ appType: "custom", logLevel: "silent", server: { middlewareMode: true } });
  try {
    const { agentDirectoryPath } = await vite.ssrLoadModule("/src/components/AgentsPanel.jsx");
    assert.equal(
      agentDirectoryPath({ filter: "Ada Core", tier: "core", regionId: 2, afterId: 100 }),
      "/api/agents?limit=100&q=Ada+Core&population_tier=core&region_id=2&after_id=100",
    );
    const { readFile } = await import("node:fs/promises");
    const source = await readFile(new URL("../src/components/AgentsPanel.jsx", import.meta.url), "utf8");
    assert.match(source, /useEffect\(\(\) => \{\s*setCursors\(\[null\]\);\s*setPageIndex\(0\);\s*\}, \[regionId\]\)/);
    const observatorySource = await readFile(new URL("../src/hooks/useObservatory.js", import.meta.url), "utf8");
    assert.doesNotMatch(observatorySource, /api\("\/api\/agents"\)/);
  } finally { await vite.close(); }
});
