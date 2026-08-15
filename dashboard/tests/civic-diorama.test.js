import assert from "node:assert/strict";
import test from "node:test";

import { buildDioramaScene } from "../src/lib/civicDiorama.js";

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
