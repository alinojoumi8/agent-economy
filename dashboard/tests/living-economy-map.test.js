import assert from "node:assert/strict";
import test from "node:test";

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
