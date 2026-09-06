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
    "fork=fork-a&tick=004&event=7&layer=markets&q=Atlas&activeOnly=1&agent=9&place=11&population=all&view=diorama",
  ));

  assert.deepEqual(state, {
    fork: "fork-a",
    tick: "4",
    event: 7,
    city: null,
    layer: "markets",
    q: "Atlas",
    activeOnly: true,
    agent: 9,
    firm: null,
    camera: null,
    place: null,
    project: null,
    population: "all",
    view: "diorama",
  });
});

test("malformed observer URL values fail closed to safe defaults", () => {
  const state = parseObserverViewState(new URLSearchParams(
    "tick=999999999999999999999999&event=0&layer=private&q=x&activeOnly=true&agent=not-a-number&population=private",
  ));

  assert.equal(state.tick, "live");
  assert.equal(state.event, null);
  assert.equal(state.layer, "all");
  assert.equal(state.activeOnly, false);
  assert.equal(state.agent, null);
  assert.equal(state.place, null);
  assert.equal(state.project, null);
  assert.equal(state.population, "core");
  assert.equal(state.view, "atlas");
});

test("observer patches omit defaults and retain unrelated route state", () => {
  const current = new URLSearchParams(
    "fork=fork-a&tick=4&event=7&layer=markets&q=Atlas&activeOnly=1&agent=9&population=clusters&view=diorama&relation=cited",
  );
  const next = patchObserverViewState(current, {
    tick: "live",
    layer: "all",
    q: "",
    activeOnly: false,
    agent: null,
    firm: null,
    camera: null,
    population: "core",
    view: "atlas",
  });

  assert.equal(next.toString(), "fork=fork-a&event=7&relation=cited");
});

test("agent and place selections remain mutually exclusive", () => {
  const place = patchObserverViewState(
    new URLSearchParams("agent=9"),
    { place: 11, view: "diorama" },
  );
  assert.equal(place.toString(), "place=11&view=diorama");
  assert.deepEqual(parseObserverViewState(place), {
    fork: null,
    tick: "live",
    event: null,
    city: null,
    layer: "all",
    q: "",
    activeOnly: false,
    agent: null,
    place: 11,
    firm: null,
    camera: null,
    project: null,
    population: "core",
    view: "diorama",
  });

  const agent = patchObserverViewState(place, { agent: 7 });
  assert.equal(agent.toString(), "view=diorama&agent=7");
});

test("project selection is stable, accepts aggregate ids, and is exclusive", () => {
  const project = patchObserverViewState(
    new URLSearchParams("agent=9&place=11&view=diorama"),
    { project: "private-homes:region:3:building:frame" },
  );
  assert.equal(
    project.toString(),
    "view=diorama&project=private-homes%3Aregion%3A3%3Abuilding%3Aframe",
  );
  assert.equal(
    parseObserverViewState(project).project,
    "private-homes:region:3:building:frame",
  );
  const place = patchObserverViewState(project, { place: 4 });
  assert.equal(place.toString(), "view=diorama&place=4");
  assert.equal(
    parseObserverViewState(new URLSearchParams("project=private%20reasoning")).project,
    null,
  );
});

test("cross-workspace and projection scopes use different fork keys", () => {
  const source = new URLSearchParams(
    "fork=fork-a&tick=4&event=7&layer=markets&q=Atlas&activeOnly=1&agent=9&population=all&relation=cited",
  );
  assert.equal(commonObserverSearchParams(source).toString(), "fork=fork-a&tick=4&event=7");
  assert.equal(
    projectionScopeParams(parseObserverViewState(source)).toString(),
    "tick=4&fork_id=fork-a",
  );
});
