import test from "node:test";
import assert from "node:assert/strict";
import { cityRuntimeMatches, loadCityProjection } from "../src/app/cityProjection.js";

const scope = { runId: "run", fork: "fork-a", tick: "live", population: "all" };
const frame = (projection, data = {}) => ({ run_id: "run", fork_id: "fork-a", tick: 4,
  projection, view_key: "public", policy_version: 1, projection_version: 2, semantics_version: 13, data });

test("city supporting projections are pinned to the map's actual tick and fork", async () => {
  const requests = [];
  const city = await loadCityProjection(scope, async path => {
    const url = new URL(path, "http://local");
    requests.push(url);
    if (url.pathname.endsWith("world-map")) return frame("world.map", { agents: [{ id: 1 }] });
    assert.equal(url.searchParams.get("tick"), "4");
    assert.equal(url.searchParams.get("fork_id"), "fork-a");
    return url.pathname.endsWith("summary") ? frame("civic.summary", { tick: 4 }) : frame("world.snapshot");
  });
  assert.equal(requests[0].searchParams.get("tick"), "live");
  assert.equal(requests[0].searchParams.get("population"), "all");
  assert.equal(requests[0].searchParams.get("layers"), "regions,agents,organizations,places,construction_projects,presence,flows");
  assert.equal(city.civic.tick, 4);
  assert.deepEqual(city.agents, [{ id: 1 }]);
});

test("a mismatched map cannot release later city or runtime requests", async () => {
  for (const change of [{ run_id: "other" }, { fork_id: "other" }, { tick: -1 }, { tick: 1.5 }, { projection: "private.message" },
    { fork_id: undefined }, { view_key: "" }, { policy_version: undefined }, { semantics_version: -1 }, { projection_version: 0 }]) {
    let calls = 0;
    await assert.rejects(() => loadCityProjection(scope, async () => { calls++; return { ...frame("world.map"), ...change }; }), /does not match/);
    assert.equal(calls, 1);
  }
  await assert.rejects(() => loadCityProjection({ ...scope, tick: "3" }, async () => frame("world.map")), /does not match/);
});

test("mixed tick, fork, semantics or visibility never yields a partially coherent city", async () => {
  for (const change of [{ tick: 5 }, { fork_id: "other" }, { policy_version: 2 }, { view_key: "operator" }, { semantics_version: 14 }]) {
    await assert.rejects(() => loadCityProjection(scope, async path => {
      if (path.includes("world-map")) return frame("world.map");
      return path.includes("civic") ? { ...frame("civic.summary"), ...change } : frame("world.snapshot");
    }), /does not match|changed lineage/);
  }
});

test("a live fork resolved from the map remains bound even when no fork was in the URL", async () => {
  await assert.rejects(() => loadCityProjection({ ...scope, fork: null }, async path => {
    if (path.includes("world-map")) return frame("world.map");
    return path.includes("civic") ? { ...frame("civic.summary"), fork_id: null } : frame("world.snapshot");
  }), /does not match/);
});

test("historical and foreign runtime cannot enter a city frame", () => {
  const runtime = { context: { run_id: "run", fork_id: "fork-a", tick: "live" } };
  assert.equal(cityRuntimeMatches(runtime, frame("world.map"), "live"), true);
  assert.equal(cityRuntimeMatches(runtime, frame("world.map"), "4"), false);
  assert.equal(cityRuntimeMatches(runtime, { ...frame("world.map"), fork_id: "fork-b" }, "live"), false);
  assert.equal(cityRuntimeMatches(runtime, { ...frame("world.map"), run_id: "other" }, "live"), false);
  assert.equal(cityRuntimeMatches({}, frame("world.map"), "live"), false);
});
