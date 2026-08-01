import assert from "node:assert/strict";
import test from "node:test";

import {
  commonObserverSearchParams,
  parseObserverViewState,
  patchObserverViewState,
  projectionScopeParams,
} from "../src/app/observerViewStateCore.js";

test("observer URL state restores valid city and common selections", () => {
  const state = parseObserverViewState(new URLSearchParams(
    "fork=fork-a&tick=004&event=7&layer=markets&q=Atlas&activeOnly=1&agent=9",
  ));

  assert.deepEqual(state, {
    fork: "fork-a",
    tick: "4",
    event: 7,
    layer: "markets",
    q: "Atlas",
    activeOnly: true,
    agent: 9,
  });
});

test("malformed observer URL values fail closed to safe defaults", () => {
  const state = parseObserverViewState(new URLSearchParams(
    "tick=999999999999999999999999&event=0&layer=private&q=x&activeOnly=true&agent=not-a-number",
  ));

  assert.equal(state.tick, "live");
  assert.equal(state.event, null);
  assert.equal(state.layer, "all");
  assert.equal(state.activeOnly, false);
  assert.equal(state.agent, null);
});

test("observer patches omit defaults and retain unrelated route state", () => {
  const current = new URLSearchParams(
    "fork=fork-a&tick=4&event=7&layer=markets&q=Atlas&activeOnly=1&agent=9&relation=cited",
  );
  const next = patchObserverViewState(current, {
    tick: "live",
    layer: "all",
    q: "",
    activeOnly: false,
    agent: null,
  });

  assert.equal(next.toString(), "fork=fork-a&event=7&relation=cited");
});

test("cross-workspace and projection scopes use different fork keys", () => {
  const source = new URLSearchParams(
    "fork=fork-a&tick=4&event=7&layer=markets&q=Atlas&activeOnly=1&agent=9&relation=cited",
  );
  assert.equal(commonObserverSearchParams(source).toString(), "fork=fork-a&tick=4&event=7");
  assert.equal(
    projectionScopeParams(parseObserverViewState(source)).toString(),
    "tick=4&fork_id=fork-a",
  );
});
