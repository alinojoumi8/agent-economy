import test from "node:test";
import assert from "node:assert/strict";
import { cityEvidenceParams, cityWorkspaceHref } from "../src/app/cityNavigation.js";
import { commonObserverSearchParams, parseObserverViewState, patchObserverViewState } from "../src/app/observerViewStateCore.js";
import { normalizeCityCamera, parseCityCamera, serializeCityCamera } from "../src/lib/cityCamera.js";

test("firm selections are exclusive with every older city object type", () => {
  for (const key of ["agent", "place", "project"]) {
    const next = patchObserverViewState(new URLSearchParams(`${key}=4`), { firm: 2 });
    assert.equal(next.toString(), "firm=2");
    assert.equal(parseObserverViewState(next).firm, 2);
    const previous = patchObserverViewState(next, { [key]: 4 });
    assert.equal(previous.has("firm"), false);
  }
  assert.equal(parseObserverViewState(new URLSearchParams("firm=2&agent=1&place=4")).agent, null);
  for (const value of ["-1", "0", "1.2", "NaN", "9007199254740993"]) {
    assert.equal(parseObserverViewState(new URLSearchParams(`firm=${value}`)).firm, null);
  }
});

test("city to market to evidence roundtrip preserves display state without taking over the destination", () => {
  const state = parseObserverViewState(new URLSearchParams("fork=child&tick=4&firm=2&view=diorama&camera=40,60,4&population=all&layer=work"));
  const market = cityEvidenceParams(state);
  market.set("view", "prices"); market.set("price_firm", "2");
  const evidence = commonObserverSearchParams(market);
  assert.equal(evidence.has("view"), false);
  assert.equal(evidence.get("tick"), "4");
  const returned = new URL(cityWorkspaceHref("run", parseObserverViewState(evidence)), "http://local");
  assert.equal(returned.pathname, "/runs/run/world");
  const restored = parseObserverViewState(returned.searchParams);
  assert.equal(restored.firm, 2);
  assert.equal(restored.view, "diorama");
  assert.equal(restored.population, "all");
  assert.equal(restored.layer, "work");
  assert.equal(restored.fork, "child");
  assert.deepEqual(restored.camera, { x: 40, y: 60, zoom: 4 });
});

test("a city return hint cannot change current scope, inject routes or retain arbitrary parameters", () => {
  const state = { fork: "current", tick: "7", event: 9,
    city: "fork=foreign&tick=100&view=private&firm=2&camera=Infinity,2,4&token=canary&city=recursive" };
  const url = new URL(cityWorkspaceHref("current/run", state, { firm: 3 }), "http://local");
  assert.equal(url.pathname, "/runs/current%2Frun/world");
  assert.deepEqual([...url.searchParams.entries()].sort(), [["event", "9"], ["firm", "3"], ["fork", "current"], ["tick", "7"]]);
});

test("camera bookmarks reject malformed values and roundtrip bounded coordinates", () => {
  for (const raw of ["NaN,20,4", "50,50,99", "-1,20,4", "50,101,4", "50,,3", "50,50,3,extra", "1e2,50,3"]) {
    assert.equal(parseCityCamera(raw), null);
  }
  const bounded = normalizeCityCamera({ x: -20, y: 180, zoom: 8 });
  assert.deepEqual(parseCityCamera(serializeCityCamera(bounded)), { x: 0, y: 100, zoom: 5.4 });
  const params = patchObserverViewState(new URLSearchParams("firm=2"), { camera: { x: 45, y: 55, zoom: 4.125 } });
  assert.deepEqual(parseObserverViewState(params).camera, { x: 45, y: 55, zoom: 4.125 });
  assert.equal(patchObserverViewState(params, { camera: null }).toString(), "firm=2");
  assert.equal(serializeCityCamera({ x: 50, y: 50, zoom: 3.05 }), "");
});
