import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  normalizeWorkspaceFilters,
  validatedSelectedId,
  workspaceRouteUrl,
} from "../src/workspaces/workspaceRouteState.js";
import { normalizeWorldWorkspace } from "../src/workspaces/worldWorkspaceModel.js";

test("workspace URLs preserve only validated observer and route state", () => {
    assert.equal(
      workspaceRouteUrl(
        "run/id", "markets", { fork: "fork-1", tick: "7" }, { side: "buy" },
      ),
      "/runs/run%2Fid/markets?fork=fork-1&tick=7&side=buy",
    );
    assert.equal(
      workspaceRouteUrl("run", "world", { fork: null, tick: "live" }, {}),
      "/runs/run/world",
    );
    assert.deepEqual(
      normalizeWorkspaceFilters(
        { side: "buy", selected: "12", future_canary: "private" },
        ["side", "selected"],
      ),
      { side: "buy", selected: "12" },
    );
    assert.equal(validatedSelectedId("12"), 12);
    assert.equal(validatedSelectedId("0"), null);
    assert.equal(validatedSelectedId("1.5"), null);
    assert.equal(validatedSelectedId("private"), null);
});

test("world workspace normalizes public map data without inventing coordinates", () => {
  const normalized = normalizeWorldWorkspace({
    enabled: false,
    regions: [
      { id: 2, name: "North", currency_code: "CAD", x: "not-a-coordinate", y: 0.7 },
      { id: 1, name: "South", currency_code: "USD", x: 0.2, y: 0.3 },
    ],
    agents: [
      { id: 2, name: "Unknown", region_id: 99, x: Infinity, y: 0 },
      { id: 1, name: "Known", region_id: 1 },
    ],
    organizations: [
      { id: 3, name: "Closed", region_id: 1, active: false },
      { id: 2, name: "Open", region_id: 1, active: true },
    ],
    places: [
      { id: 4, name: "Square", region_id: 1, x: 0.5, y: 0.5 },
      { id: 3, name: "Archives", region_id: 1, x: Number.NaN, y: 0.4 },
    ],
    presence: [{ id: 8, agent_id: 1, place_id: 4 }],
    flows: [
      { id: 9, kind: "migration", origin_region_id: 1, destination_region_id: 2 },
      { id: 9, kind: "migration", origin_region_id: 1, destination_region_id: 2 },
      { id: 10, kind: "trade", origin_region_id: 1, destination_region_id: 999 },
      { id: 11, kind: "trade", origin_region_id: 2, destination_region_id: 1 },
    ],
    currentTelemetry: { capacity: 999 },
  });

  assert.equal(normalized.enabled, false);
  assert.deepEqual(normalized.regions.map(region => region.id), [1, 2]);
  assert.deepEqual(normalized.places.map(place => place.id), [3, 4]);
  assert.equal(normalized.regions[1].x, undefined);
  assert.equal(normalized.places[0].x, undefined);
  assert.equal(normalized.agents[1].x, undefined);
  assert.deepEqual(normalized.flows.map(flow => `${flow.kind}:${flow.id}`), ["migration:9", "trade:11"]);
  assert.deepEqual(normalized.summary, {
    population: 2,
    activeOrganizations: 1,
    currencies: ["CAD", "USD"],
    migrationCount: 1,
    tradeCount: 1,
  });
  assert.equal("currentTelemetry" in normalized, false);
});

test("world workspace has stable empty and historical normalization", () => {
  assert.deepEqual(normalizeWorldWorkspace({}), {
    enabled: false,
    regions: [],
    agents: [],
    organizations: [],
    places: [],
    presence: [],
    flows: [],
    summary: {
      population: 0,
      activeOrganizations: 0,
      currencies: [],
      migrationCount: 0,
      tradeCount: 0,
    },
  });
  const historical = normalizeWorldWorkspace({
    enabled: true,
    as_of_tick: 4,
    regions: [{ id: 1, name: "Only", currency_code: "USD" }],
    current_runtime: { queue_depth: 7 },
  });
  assert.equal(historical.enabled, true);
  assert.equal("current_runtime" in historical, false);
  assert.equal("as_of_tick" in historical, false);
});

test("World OS maps the World route to its canonical workspace", () => {
  const source = readFileSync(new URL("../src/app/WorldOSApp.tsx", import.meta.url), "utf8");
  assert.match(source, /import \{ WorldWorkspace \}/);
  assert.match(source, /path="world" element=\{<WorldWorkspace \/>\}/);
  assert.doesNotMatch(source, /path="world" element=\{<LegacyWorkspace/);
});
