import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { observationScope, observationParams, observationState, readObservations,
  addObservation, observationLabel, observationRecord } from "../src/lib/cityObservations.js";
import { parseObserverViewState } from "../src/app/observerViewStateCore.js";

const frame = { run_id: "world", fork_id: null, tick: 4, view_key: "ordinary",
  projection: "world.map", semantics_version: 16, projection_version: 2, policy_version: 1 };
const scope = observationScope(frame, "world");
const state = parseObserverViewState(new URLSearchParams("agent=2&camera=40,60,4&view=diorama&population=all&layer=work&q=Shop"));

test("event bookmarks freeze a committed observation and restore only observer fields", () => {
  const params = observationParams(scope, state, { id: 9, tick: 3, payload: { private: "NEVER-STORE" }, text: "PRIVATE-BODY" });
  const restored = observationState(params, scope);
  assert.equal(restored.tick, "4"); assert.equal(restored.agent, 2); assert.equal(restored.event, 9);
  assert.deepEqual(restored.camera, { x: 40, y: 60, zoom: 4 });
  assert.equal(restored.q, "Shop"); assert.equal(restored.layer, "work"); assert.equal(restored.view, "diorama");
  assert.equal(params.includes("PRIVATE"), false); assert.equal(params.includes("NEVER"), false);
  assert.equal(observationLabel(restored), "Event #9 · Tick 4 · Person #2");
  assert.equal(observationParams(scope, state).includes("event="), false);
});

test("bookmark admission binds run, fork, visible frame and event boundary", () => {
  assert.equal(observationScope(frame, "foreign"), null);
  for (const patch of [{ tick: -1 }, { projection: "operator.truth" }, { view_key: "" }, { semantics_version: null }]) {
    assert.equal(observationScope({ ...frame, ...patch }, "world"), null);
  }
  assert.notEqual(observationScope({ ...frame, view_key: "another-view" }, "world").key, scope.key);
  assert.notEqual(observationScope({ ...frame, fork_id: "child" }, "world").key, scope.key);
  for (const other of [{ ...state, tick: "3" }, { ...state, fork: "foreign" }]) {
    assert.throws(() => observationParams(scope, other), /selected city frame/);
  }
  assert.throws(() => observationParams(scope, state, { id: 1, tick: 5 }), /selected city frame/);
  assert.throws(() => observationParams(scope, state, { id: "1", tick: 4 }), /selected city frame/);
});

test("saved records reject injected routes, duplicate params and foreign or malformed state", () => {
  const params = observationParams(scope, state);
  assert.deepEqual(readObservations(JSON.stringify({ version: 1, entries: [params] }), scope), [params]);
  for (const value of [null, {}, "tick=live", `${params}&next=https://foreign`, `${params}&tick=4`,
    `${params}&fork=foreign`, "tick=999999999999999999999999", "x".repeat(2049)]) {
    assert.equal(observationState(value, scope), null);
  }
  for (const value of ["bad json", "null", JSON.stringify({ version: 2, entries: [] }),
    JSON.stringify({ version: 1, entries: [params, params] }),
    JSON.stringify({ version: 1, entries: [params], private: "unexpected" })]) {
    assert.throws(() => readObservations(value, scope));
  }
  assert.deepEqual(readObservations(null, scope), []);
});

test("observation capacity preserves older bookmarks and deduplicates explicit saves", () => {
  const entries = Array.from({ length: 20 }, (_, index) => `tick=${index}`);
  assert.throws(() => addObservation(entries, "tick=21"), /Remove one/);
  assert.equal(entries.length, 20);
  const repeated = addObservation(entries, "tick=4");
  assert.equal(repeated.length, 20); assert.equal(repeated[0], "tick=4");
});

test("operator response admission requires the exact context and bounded navigation records", () => {
  const good = { context: scope.context, version: 2, entries: ["tick=3&agent=1"] };
  assert.deepEqual(observationRecord(good, scope), { version: 2, entries: good.entries });
  for (const patch of [{ version: -1 }, { context: { ...scope.context, view_key: "foreign" } },
    { entries: ["tick=3&credentials=NO"] }, { entries: undefined }]) {
    assert.throws(() => observationRecord({ ...good, ...patch }, scope));
  }
});

test("server canonical examples round-trip through the actual observer URL parser", () => {
  const vectors = JSON.parse(readFileSync(new URL("./fixtures/city-observations.json", import.meta.url), "utf8"));
  for (const vector of vectors) {
    const result = observationState(vector.canonical, scope);
    assert.ok(result, vector.canonical);
    assert.equal(result.tick, "3");
    assert.equal(observationParams({ ...scope, tick: 3 },
      parseObserverViewState(new URLSearchParams(vector.input)), result.event ? { id: result.event, tick: 3 } : null), vector.canonical);
  }
});
