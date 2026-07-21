import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";

import { aggregateFlows, normalizeMapData } from "../src/components/livingEconomyMapModel.js";

const regionIds = new Set([1, 2, 3]);

test("aggregateFlows groups routes and preserves status counts", () => {
  const routes = aggregateFlows([
    { id: 1, source_region_id: 1, target_region_id: 2, kind: "trade", magnitude: 4, status: "completed" },
    { id: 2, source_region_id: 1, target_region_id: 2, kind: "trade", magnitude: 6, status: "in_transit" },
    { id: 3, source_region_id: 3, target_region_id: 1, kind: "migration", magnitude: 1, status: "completed" },
    { id: 4, source_region_id: 9, target_region_id: 1, kind: "trade", magnitude: 99, status: "completed" },
    { id: 5, source_region_id: 1, target_region_id: 2, kind: "unknown", magnitude: 99, status: "completed" },
  ], regionIds);

  assert.deepEqual(routes, [
    {
      id: "migration:3:1",
      kind: "migration",
      source_region_id: 3,
      target_region_id: 1,
      magnitude: 1,
      count: 1,
      statuses: { completed: 1 },
    },
    {
      id: "trade:1:2",
      kind: "trade",
      source_region_id: 1,
      target_region_id: 2,
      magnitude: 10,
      count: 2,
      statuses: { completed: 1, in_transit: 1 },
    },
  ]);
});

test("aggregateFlows balances trade and migration within a 100-row cap", () => {
  const tradeFlows = Array.from({ length: 80 }, (_, index) => ({
    id: index + 1,
    source_region_id: 1,
    target_region_id: 2,
    kind: "trade",
    magnitude: 1,
    status: index < 50 ? "selected" : "overflow",
  }));
  const migrationFlows = Array.from({ length: 80 }, (_, index) => ({
    id: index + 81,
    source_region_id: 2,
    target_region_id: 1,
    kind: "migration",
    magnitude: 1,
    status: index < 50 ? "selected" : "overflow",
  }));

  const routes = aggregateFlows([...tradeFlows, ...migrationFlows], regionIds);

  assert.deepEqual(routes, [
    {
      id: "migration:2:1",
      kind: "migration",
      source_region_id: 2,
      target_region_id: 1,
      magnitude: 50,
      count: 50,
      statuses: { selected: 50 },
    },
    {
      id: "trade:1:2",
      kind: "trade",
      source_region_id: 1,
      target_region_id: 2,
      magnitude: 50,
      count: 50,
      statuses: { selected: 50 },
    },
  ]);
  assert.equal(routes.reduce((total, route) => total + route.count, 0), 100);
});

test("aggregateFlows lets one flow kind fill the 100-row cap", () => {
  const migrationFlows = Array.from({ length: 120 }, (_, index) => ({
    id: index + 1,
    source_region_id: 2,
    target_region_id: 1,
    kind: "migration",
    magnitude: 1,
    status: index < 100 ? "selected" : "overflow",
  }));

  const routes = aggregateFlows(migrationFlows, regionIds);

  assert.deepEqual(routes, [
    {
      id: "migration:2:1",
      kind: "migration",
      source_region_id: 2,
      target_region_id: 1,
      magnitude: 100,
      count: 100,
      statuses: { selected: 100 },
    },
  ]);
});

test("normalizeMapData clamps coordinates and derives regional totals", () => {
  const scene = normalizeMapData({
    enabled: true,
    regions: [
      {
        id: 1, name: "Northstar Federation", region_key: "northstar",
        currency_code: "NSD", x: -4, y: 0.35, population: 650,
        population_target: 600, specialization: ["technology", "finance"], firms: 99,
      },
      {
        id: 2, name: "Ironvale Union", region_key: "ironvale",
        currency_code: "IVC", x: 4, y: "bad", population: 146,
        population_target: 220, specialization_json: "[\"energy\"]",
      },
    ],
    firms: [
      { id: 10, name: "Foundry", region_id: 1, sector: "manufacturing" },
      { id: 11, name: "Grid", region_id: 2, sector: "energy" },
      { id: 12, name: "Missing", region_id: 9, sector: "services" },
    ],
    core_agents: [
      { id: 20, name: "Governor Vale", region_id: 1, role: "central_banker" },
      { id: 21, name: "Unplaced", region_id: null, role: "editor" },
    ],
    flows: [
      { id: 30, source_region_id: 1, target_region_id: 2, kind: "trade", magnitude: 7, status: "completed" },
      { id: 31, source_region_id: 2, target_region_id: 1, kind: "migration", magnitude: 1, status: "completed" },
    ],
  });

  assert.equal(scene.enabled, true);
  assert.equal(scene.regions[0].x, 0.08);
  assert.equal(scene.regions[1].x, 0.92);
  assert.equal(scene.regions[1].y, 0.5);
  assert.deepEqual(scene.regions[1].specialization, ["energy"]);
  assert.equal(scene.firms.length, 2);
  assert.equal(scene.coreAgents.length, 1);
  assert.equal(scene.regions[0].firmItems.length, 1);
  assert.equal(scene.regions[0].coreAgentItems.length, 1);
  assert.deepEqual(scene.regions[0].flowTotals, {
    trade: { inbound: 0, outbound: 7 },
    migration: { inbound: 1, outbound: 0 },
  });
});

test("normalizeMapData treats malformed optional collections as empty", () => {
  const scene = normalizeMapData({ enabled: false, regions: null, firms: {}, core_agents: "bad", flows: 4 });
  assert.deepEqual(scene, { enabled: false, regions: [], routes: [], firms: [], coreAgents: [] });
});

const renderedMap = {
  enabled: true,
  regions: [
    {
      id: 1, name: "Northstar Federation", region_key: "northstar", currency_code: "NSD",
      x: 0.25, y: 0.35, population: 650, population_target: 600,
      specialization: ["technology", "finance"],
    },
    {
      id: 2, name: "Ironvale Union", region_key: "ironvale", currency_code: "IVC",
      x: 0.72, y: 0.28, population: 146, population_target: 220,
      specialization: ["manufacturing", "energy"],
    },
  ],
  firms: [{ id: 10, name: "Foundry", sector: "manufacturing", status: "listed", region_id: 1 }],
  core_agents: [{ id: 20, name: "Governor Vale", role: "central_banker", region_id: 1 }],
  flows: [
    { id: 30, source_region_id: 1, target_region_id: 2, kind: "trade", magnitude: 7, status: "completed" },
    { id: 31, source_region_id: 1, target_region_id: 2, kind: "trade", magnitude: 3, status: "in_transit" },
    { id: 32, source_region_id: 2, target_region_id: 1, kind: "migration", magnitude: 1, status: "completed" },
  ],
};

test("EconomicMap renders an accessible isometric scene and controls", async () => {
  const vite = await createServer({ appType: "custom", logLevel: "silent", server: { middlewareMode: true } });
  try {
    const { EconomicMap } = await vite.ssrLoadModule("/src/components/V2Observatory.jsx");
    const markup = renderToStaticMarkup(React.createElement(EconomicMap, { map: renderedMap }));

    assert.match(markup, /Regional economy command table/);
    assert.match(markup, /Perspective economic topology/);
    assert.match(markup, /aria-label="Toggle trade routes"[^>]*aria-pressed="true"/);
    assert.match(markup, /aria-label="Toggle migration routes"[^>]*aria-pressed="true"/);
    assert.match(markup, /aria-label="Toggle actor markers"[^>]*aria-pressed="true"/);
    assert.match(markup, /data-region-id="1"/);
    assert.match(markup, /data-route-id="trade:1:2"/);
    assert.match(markup, /tabindex="0"/);
    assert.match(markup, /Select a region/);
    assert.match(markup, /2 aggregated routes/);
  } finally {
    await vite.close();
  }
});

test("EconomicMap exposes its interactive scene as a labelled group", async () => {
  const vite = await createServer({ appType: "custom", logLevel: "silent", server: { middlewareMode: true } });
  try {
    const { EconomicMap } = await vite.ssrLoadModule("/src/components/V2Observatory.jsx");
    const markup = renderToStaticMarkup(React.createElement(EconomicMap, { map: renderedMap }));

    assert.match(markup, /<svg[^>]*role="group"[^>]*aria-labelledby="[^"]+"/);
    assert.doesNotMatch(markup, /<svg[^>]*role="img"/);
    assert.match(markup, /role="button" tabindex="0" data-region-id="1" aria-label="[^"]+"/);
    assert.match(markup, /role="button" tabindex="0" data-route-id="trade:1:2" aria-label="[^"]+"/);
  } finally {
    await vite.close();
  }
});

test("EconomicMap preserves the disabled regional-economy guidance", async () => {
  const vite = await createServer({ appType: "custom", logLevel: "silent", server: { middlewareMode: true } });
  try {
    const { EconomicMap } = await vite.ssrLoadModule("/src/components/V2Observatory.jsx");
    const markup = renderToStaticMarkup(React.createElement(EconomicMap, {
      map: { enabled: false, regions: [] },
    }));
    assert.match(markup, /Regional economy disabled for this run profile/);
  } finally {
    await vite.close();
  }
});

test("economy map styles include motion and accessible reduced-motion behavior", async () => {
  const css = await readFile(new URL("../src/index.css", import.meta.url), "utf8");
  assert.match(css, /@keyframes economy-map-route-flow/);
  assert.match(css, /\.economy-map-region:focus-visible \.economy-map-focus-ring/);
  assert.match(css, /\.economy-map-route-line\.is-migration/);
  assert.match(css, /prefers-reduced-motion: reduce[\s\S]*\.economy-map-route-line/);
});
