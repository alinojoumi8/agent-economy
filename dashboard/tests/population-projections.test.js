import assert from "node:assert/strict";
import test from "node:test";
import { deriveCityModel } from "../src/lib/civicCity.js";
import { metricAvailabilityText, metricDelta } from "../src/lib/metricSeries.js";

test("selected-day map membership wins over current agents, runtime and stale presence", () => {
  const model = deriveCityModel({
    agents: [{ id: 1, name: "Returned today", x: .9, y: .9, modeled_residence: { state: "resident" } },
      { id: 2, name: "Outside today", modeled_residence: { state: "outside" } }],
    map: {
      agents: [{ id: 2, name: "Resident then", x: .2, y: .3, modeled_residence: { state: "resident" } }],
      core_agents: [{ id: 1, name: "Stale marker" }],
      presence: [{ agent_id: 1, tick: 1, slot: "business", x: .8, y: .8 }],
      population_summary: { total: 1, resident_population: 1, known_living_outside: 1 },
    },
    runtime: { active_agents: [{ agent_id: 1, state: "thinking" }] }, tick: 1, historical: true,
  });
  assert.deepEqual(model.agents.map(row => row.id), [2]);
  assert.equal(model.agents[0].name, "Resident then");
  assert.equal(model.agents[0].runtimeActivity, null);
  assert.equal(model.agents[0].x, 20);
  assert.equal(model.population.knownLivingOutside, 1);
});

test("a valid empty-resident map never falls back to living financial owners", () => {
  const model = deriveCityModel({ agents: [{ id: 1 }], map: {
    agents: [], population_summary: { total: 0, resident_population: 0, known_living_outside: 1 },
  } });
  assert.equal(model.agents.length, 0);
  assert.equal(model.counts.residents, 0);
});

test("missing rates cannot produce a zero-valued change", () => {
  assert.equal(metricDelta([{ tick: 0, value: .4 }, { tick: 1, value: null }]), null);
  assert.equal(metricDelta([{ tick: 0, value: null }, { tick: 1, value: .4 }]), null);
  assert.equal(metricDelta([{ tick: 0, value: .4 }, { tick: 1, value: 0 }]), -.4);
  assert.match(metricAvailabilityText({ tick: 4, value: null, status: "unavailable", reason: "empty_resident_labor_force" }), /No eligible resident workers/);
  assert.equal(metricAvailabilityText({ tick: 2, value: 0, status: "available" }), null);
});
