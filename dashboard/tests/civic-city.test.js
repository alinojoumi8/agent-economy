import assert from "node:assert/strict";
import test from "node:test";
import {
  classifyAgentLayer,
  classifyEventLayer,
  deriveCityModel,
  eventActorIds,
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
