import assert from "node:assert/strict";
import test from "node:test";
import {
  classifyAgentLayer,
  classifyEventLayer,
  deriveCityModel,
  eventActorIds,
  resolveCityFilterPatch,
  semanticReceiptForEvent,
} from "../src/lib/civicCity.js";

test("city layers map civic roles and committed events to named evidence families", () => {
  assert.equal(classifyAgentLayer({ role: "legislator_house" }), "institutions");
  assert.equal(classifyAgentLayer({ occupation: "reporter" }), "communications");
  assert.equal(classifyAgentLayer({ occupation: "insurance broker" }), "markets");
  assert.equal(classifyAgentLayer({ occupation: "nurse" }), "health");
  assert.equal(classifyAgentLayer({ occupation: "construction" }), "work");

  assert.equal(classifyEventLayer({ kind: "belief_updated" }), "communications");
  assert.equal(classifyEventLayer({ kind: "goods_sale" }), "markets");
  assert.equal(classifyEventLayer({ kind: "job_posted" }), "work");
});

test("event actor extraction ignores entity ids that are not people", () => {
  const ids = eventActorIds({
    payload: {
      buyer_id: 7,
      seller_id: 11,
      firm_id: 2,
      job_id: 9,
      nested: { recipient_agent_id: 13 },
    },
  });

  assert.deepEqual(ids.sort((left, right) => left - right), [7, 11, 13]);
});

test("semantic receipts never fall back to a different selected event", () => {
  const receipts = [{ eventId: 11, tick: 4, semantic: "matched" }];

  assert.deepEqual(
    semanticReceiptForEvent({ id: 11, tick: 4, payload: {} }, receipts),
    receipts[0],
  );
  assert.equal(
    semanticReceiptForEvent({ id: 12, tick: 4, payload: {} }, receipts),
    null,
  );
  assert.deepEqual(
    semanticReceiptForEvent({
      id: 13,
      tick: 5,
      payload: {
        semantic_receipt: { eventId: 999, tick: 999, semantic: "embedded" },
      },
    }, receipts),
    { eventId: 13, tick: 5, semantic: "embedded" },
  );
});

test("derived city layout is deterministic and labels actor-linked activity", () => {
  const input = {
    agents: [
      { id: 1, name: "Governor Vale", role: "central_banker", alive: 1 },
      { id: 2, name: "Dr. Amara Osei", occupation: "doctor", alive: 1 },
    ],
    firms: [{ id: 4, name: "General Hospital", sector: "health" }],
    events: [{
      id: 22,
      tick: 4,
      phase: "EXECUTION",
      kind: "public_statement",
      payload: { actor_id: 1, firm_id: 4 },
    }],
    map: { core_agents: [], firms: [] },
  };

  const first = deriveCityModel(input);
  const second = deriveCityModel(input);

  assert.equal(first.coordinateMode, "derived");
  assert.equal(first.counts.active, 1);
  assert.equal(first.agents[0].event.id, 22);
  assert.equal(first.agents[1].event, null);
  assert.deepEqual(
    first.agents.map(agent => [agent.id, agent.x, agent.y]),
    second.agents.map(agent => [agent.id, agent.x, agent.y]),
  );
});

test("projected coordinates are retained and normalized from unit space", () => {
  const model = deriveCityModel({
    agents: [{ id: 3, name: "Editor", occupation: "editor" }],
    map: { core_agents: [{ id: 3, name: "Editor", occupation: "editor", x: 0.25, y: 0.7 }] },
  });

  assert.equal(model.coordinateMode, "observed");
  assert.equal(model.agents[0].x, 25);
  assert.equal(model.agents[0].y, 70);
  assert.equal(model.agents[0].coordinateSource, "observed");
});

test("city instrumentation excludes firms that are not operating", () => {
  const model = deriveCityModel({
    agents: [],
    firms: [
      { id: 1, name: "Open Works", status: "private" },
      { id: 2, name: "Closed Works", status: "closed" },
      { id: 3, name: "Failed Works", status: "bankrupt" },
    ],
  });

  assert.equal(model.counts.firms, 1);
});

test("empty and failed city inputs invent no agents", () => {
  const empty = deriveCityModel({ agents: [], firms: [], events: [], map: null });
  assert.equal(empty.agents.length, 0);
  assert.equal(empty.counts.active, 0);

  const failed = deriveCityModel({
    agents: undefined,
    firms: undefined,
    events: undefined,
    map: { core_agents: null, firms: null },
  });
  assert.equal(failed.agents.length, 0);
});

test("city filter transitions select the matching mark atomically", () => {
  const agents = [
    { id: 1, name: "Supplier Officer", layer: "markets", eventLayer: "markets", event: { id: 9 } },
    { id: 2, name: "Editor Northstar", layer: "communications", eventLayer: null, event: null },
    { id: 3, name: "Dr. Amara Osei", layer: "health", eventLayer: null, event: null },
  ];

  assert.deepEqual(resolveCityFilterPatch(agents, {
    layer: "all", q: "", activeOnly: false, agent: 3,
  }, { q: "Supplier Officer" }), {
    q: "Supplier Officer",
    agent: 1,
  });
});

test("mixed coordinate provenance is reported when projected and derived coexist", () => {
  const model = deriveCityModel({
    agents: [
      { id: 1, name: "Projected", occupation: "editor", alive: 1 },
      { id: 2, name: "Derived", occupation: "doctor", alive: 1 },
    ],
    map: {
      core_agents: [
        { id: 1, name: "Projected", occupation: "editor", x: 0.1, y: 0.2 },
      ],
    },
  });
  assert.equal(model.coordinateMode, "mixed");
  assert.equal(model.agents.find(agent => agent.id === 1).coordinateSource, "observed");
  assert.equal(model.agents.find(agent => agent.id === 2).coordinateSource, "derived");
});

test("population projection preserves totals and normalizes regional clusters", () => {
  const model = deriveCityModel({
    agents: [{ id: 1, name: "Core resident", population_tier: "core" }],
    map: {
      population_mode: "clusters",
      population_summary: {
        total: 300,
        core: 100,
        periphery: 200,
        rendered_agents: 100,
        clustered_agents: 200,
      },
      population_clusters: [
        { id: "region-1-periphery", label: "Northstar", count: 175, x: 0.25, y: 0.35 },
        { id: "region-2-periphery", label: "Ironvale", count: 25, x: 0.72, y: 0.28 },
      ],
    },
  });

  assert.deepEqual(model.population, {
    mode: "clusters",
    total: 300,
    core: 100,
    periphery: 200,
    renderedAgents: 1,
    clusteredAgents: 200,
  });
  assert.equal(model.counts.residents, 300);
  assert.deepEqual(
    model.clusters.map(cluster => [
      cluster.label, cluster.count, Math.round(cluster.x), Math.round(cluster.y),
    ]),
    [["Northstar", 175, 25, 35], ["Ironvale", 25, 72, 28]],
  );
});

test("peripheral presence cannot restore private placement into an all-resident map", () => {
  const model = deriveCityModel({
    agents: [
      { id: 1, name: "Core", population_tier: "core", x: null, y: null },
      { id: 2, name: "Peripheral", population_tier: "periphery", x: null, y: null },
    ],
    map: {
      population_mode: "all",
      agents: [
        { id: 1, name: "Core", population_tier: "core", x: null, y: null },
        { id: 2, name: "Peripheral", population_tier: "periphery", x: null, y: null },
      ],
      presence: [{
        agent_id: 2,
        name: "Peripheral",
        slot: "business",
        place_id: 99,
        place_name: "Private office",
        x: .88,
        y: .77,
      }],
    },
  });

  const peripheral = model.agents.find(agent => agent.id === 2);
  assert.equal(peripheral.place_id, undefined);
  assert.equal(peripheral.place_name, undefined);
  assert.equal(peripheral.coordinateSource, "derived");
  assert.notDeepEqual([peripheral.x, peripheral.y], [88, 77]);
});

test("live runtime activity takes precedence over current-tick settlement", () => {
  const model = deriveCityModel({
    agents: [
      { id: 1, name: "Queued", role: "citizen" },
      { id: 2, name: "Thinking", role: "citizen" },
      { id: 3, name: "Rejected", role: "citizen" },
      { id: 4, name: "Old event", role: "citizen" },
    ],
    events: [
      { id: 10, tick: 8, kind: "goods_sale", payload: { actor_id: 1 } },
      { id: 11, tick: 8, kind: "action_rejected", payload: { agent_id: 3 } },
      { id: 12, tick: 7, kind: "goods_sale", payload: { actor_id: 4 } },
    ],
    civic: { tick: 8 },
    runtime: { active_agents: [
      { agent_id: 1, state: "queued", active_calls: 1, tick: 8, oldest_elapsed_ms: 20 },
      { agent_id: 2, state: "thinking", active_calls: 2, tick: 8, oldest_elapsed_ms: 40 },
    ] },
    tick: "live",
  });

  assert.deepEqual(
    model.agents.map(agent => [agent.id, agent.activityState, agent.isActive]),
    [
      [1, "queued", true],
      [2, "thinking", true],
      [3, "rejected", true],
      [4, "assigned role", false],
    ],
  );
  assert.deepEqual(
    {
      active: model.counts.active,
      queued: model.counts.queued,
      thinking: model.counts.thinking,
      settled: model.counts.settled,
      rejected: model.counts.rejected,
    },
    { active: 3, queued: 1, thinking: 1, settled: 0, rejected: 1 },
  );
});

test("historical city views ignore current runtime activity", () => {
  const model = deriveCityModel({
    agents: [{ id: 1, name: "Historian", role: "citizen" }],
    events: [{ id: 3, tick: 4, kind: "goods_sale", payload: { actor_id: 1 } }],
    runtime: { active_agents: [
      { agent_id: 1, state: "thinking", active_calls: 1, tick: 9 },
    ] },
    tick: 4,
    historical: true,
  });

  assert.equal(model.agents[0].activityState, "settled");
  assert.equal(model.agents[0].runtimeActivity, null);
});

test("city construction preserves exact stored counters and aggregate privacy", () => {
  const model = deriveCityModel({
    map: {
      construction_projects: [{
        project_id: "private-homes:region:2:building:frame",
        name: "Private home construction in South",
        status: "building",
        stage: "frame",
        site: { x: 0.72, y: 0.64 },
        requirements: { funding_cents: 1800, work_units: 9 },
        contributed: { funding_cents: 1800, work_units: 3 },
        privacy: "aggregated_private",
        aggregate_count: 4,
      }],
    },
    tick: 6,
    historical: true,
  });

  assert.equal(model.counts.construction, 1);
  assert.deepEqual(
    {
      id: model.constructionProjects[0].id,
      x: model.constructionProjects[0].x,
      y: model.constructionProjects[0].y,
      funding: model.constructionProjects[0].contributedFundingCents,
      work: model.constructionProjects[0].contributedWorkUnits,
      count: model.constructionProjects[0].aggregateCount,
      privacy: model.constructionProjects[0].privacy,
    },
    {
      id: "private-homes:region:2:building:frame",
      x: 72,
      y: 64,
      funding: 1800,
      work: 3,
      count: 4,
      privacy: "aggregated_private",
    },
  );
});
