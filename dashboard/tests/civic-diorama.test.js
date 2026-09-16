import assert from "node:assert/strict";
import test from "node:test";

import {
  buildDioramaScene,
  constructionStageGeometry,
} from "../src/lib/civicDiorama.js";

test("diorama scene uses only projected entities and labels derived encodings", () => {
  const model = {
    regions: [
      { id: 1, name: "North", x: 20, y: 30 },
      { id: 2, name: "South", x: 80, y: 70 },
    ],
    places: [{
      id: 4,
      name: "Permit Office",
      kind: "licensing_office",
      owner_type: "agency",
      owner_id: 2,
      x: 25,
      y: 35,
      capacity: 9,
      businessOccupancy: 3,
      queueDepth: 5,
      occupants: [],
      privacyOccupancy: 3,
    }],
    firms: [{
      id: 8,
      name: "Workshop",
      sector: "manufacturing",
      x: 72,
      y: 65,
      employees: 4,
    }],
    clusters: [{ id: "south-periphery", label: "South", count: 200, x: 80, y: 70 }],
    flows: [{
      kind: "migration",
      id: 6,
      agent_id: 12,
      origin_region_id: 1,
      destination_region_id: 2,
      status: "pending",
    }],
    constructionProjects: [{
      project_id: 31,
      name: "Public Hall",
      target_place_type: "public_facility",
      status: "building",
      stage: "frame",
      x: 52,
      y: 46,
      requiredWorkUnits: 6,
      contributedWorkUnits: 2,
      requiredFundingCents: 1200,
      contributedFundingCents: 1200,
      milestone_count: 4,
      privacy: "public",
    }],
  };
  const visibleAgents = [{
    id: 12,
    name: "Ari",
    x: 24,
    y: 34,
    activityState: "thinking",
    district: "Works",
  }];

  const first = buildDioramaScene(model, visibleAgents, { showClusters: true });
  const second = buildDioramaScene(model, visibleAgents, { showClusters: true });

  assert.deepEqual(first, second);
  assert.equal(first.agents.length, 1);
  assert.equal(first.clusters[0].count, 200);
  assert.equal(first.flows[0].path.length, 3);
  assert.equal(first.buildings[0].ownerLabel, "Agency #2");
  assert.match(first.buildings[0].occupantCopy, /privacy aggregate/);
  assert.match(first.buildings[0].evidenceBasis, /Height derives/);
  assert.equal(first.buildings[1].entityKind, "organization");
  assert.equal(first.constructions[0].stage, "frame");
  assert.equal(first.constructionFrames.length, 8);
  assert.match(first.constructions[0].label, /2\/6 WORK/);
});

test("diorama drops flow paths whose public region endpoints are absent", () => {
  const scene = buildDioramaScene({
    regions: [{ id: 1, name: "North", x: 20, y: 30 }],
    flows: [{
      kind: "trade",
      id: 3,
      origin_region_id: 1,
      destination_region_id: 999,
    }],
  });

  assert.deepEqual(scene.flows, []);
});

test("construction geometry uses exact stored work stages without invented percentages", () => {
  const base = {
    project_id: 9,
    name: "Civic Workshop",
    status: "building",
    x: 40,
    y: 60,
    requirements: { funding_cents: 900, work_units: 6 },
    contributed: { funding_cents: 900, work_units: 1 },
    milestone_count: 3,
    privacy: "public",
  };
  const foundation = constructionStageGeometry(base);
  const frame = constructionStageGeometry({
    ...base,
    contributed: { funding_cents: 900, work_units: 2 },
  });
  const shell = constructionStageGeometry({
    ...base,
    contributed: { funding_cents: 900, work_units: 4 },
  });
  const completed = constructionStageGeometry({
    ...base,
    status: "completed",
    place_id: 18,
    contributed: { funding_cents: 900, work_units: 6 },
  });

  assert.equal(foundation.stage, "foundation");
  assert.equal(frame.stage, "frame");
  assert.equal(shell.stage, "shell");
  assert.equal(completed.stage, "completed");
  assert.equal(frame.framePaths.length, 8);
  assert.equal(shell.framePaths.length, 0);
  assert.equal(completed.operationalPlace, true);
  assert.ok(foundation.elevation < frame.elevation);
  assert.ok(frame.elevation < shell.elevation);
  assert.ok(shell.elevation < completed.elevation);
  assert.match(shell.label, /^SHELL · 4\/6 WORK$/);
  assert.doesNotMatch(shell.label, /%/);
  assert.match(shell.tooltip, /Funding: 900\/900 cents/);
});

test("private home construction remains an explicit district aggregate", () => {
  const aggregate = constructionStageGeometry({
    project_id: "private-homes:region:2:building:foundation",
    name: "Private home construction in South",
    status: "building",
    x: 70,
    y: 70,
    aggregate_count: 12,
    requirements: { funding_cents: 2400, work_units: 24 },
    contributed: { funding_cents: 2400, work_units: 4 },
    privacy: "aggregated_private",
  });

  assert.equal(aggregate.privacyAggregate, true);
  assert.match(aggregate.label, /^12 HOMES · FOUNDATION · 4\/24 WORK$/);
  assert.match(aggregate.tooltip, /owner and exact sites withheld/);
});

test("diorama flows accept both the world-map and the economic-map region field names", () => {
  const model = {
    regions: [
      { id: 1, name: "North", x: 20, y: 30 },
      { id: 2, name: "South", x: 80, y: 70 },
    ],
    places: [],
    presence: [],
    organizations: [],
    constructionProjects: [],
    clusters: [],
    flows: [
      { id: 1, kind: "trade", source_region_id: 1, target_region_id: 2, magnitude: 5, status: "delivered" },
      { id: 2, kind: "migration", origin_region_id: 2, destination_region_id: 1, agent_id: 7, status: "completed" },
      { id: 3, kind: "trade", source_region_id: 1, target_region_id: 99, magnitude: 1, status: "delivered" },
    ],
  };
  const scene = buildDioramaScene(model, [], { showClusters: false });
  assert.equal(scene.flows.length, 2, "flows with a known origin and destination draw; unknown regions are dropped");
  assert.match(scene.flows[0].tooltip, /5 units/);
  assert.match(scene.flows[1].tooltip, /Agent #7/);
});
