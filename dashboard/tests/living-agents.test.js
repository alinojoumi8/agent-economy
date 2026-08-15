import { readFileSync } from "node:fs";
import test from "node:test";
import assert from "node:assert/strict";

const workspace = readFileSync(
  new URL("../src/workspaces/PeopleWorkspace.tsx", import.meta.url),
  "utf8",
);
const shell = readFileSync(
  new URL("../src/app/WorkspaceShell.tsx", import.meta.url),
  "utf8",
);
const routes = readFileSync(
  new URL("../src/app/WorldOSApp.tsx", import.meta.url),
  "utf8",
);

test("Living Agents replaces current-roster polling with historical-safe projections", () => {
  assert.match(workspace, /\/api\/v2\/workspaces\/living-agents/);
  assert.match(workspace, /\/api\/v2\/agents\/\$\{selectedId\}\/journey/);
  assert.match(workspace, /projectionScopeParams\(observerState\)/);
  assert.match(workspace, /sourceMode="projection"/);
  assert.doesNotMatch(workspace, /\/api\/agents/);
  assert.doesNotMatch(workspace, /current-roster/);
});

test("Living Agents exposes evidence classes and privacy-safe states", () => {
  assert.match(workspace, /"committed", "runtime", "derived"/);
  assert.match(workspace, /Runtime activity appears only while viewing live/);
  assert.match(workspace, /Exact peripheral location is protected/);
  assert.match(workspace, /private bodies omitted/i);
  assert.match(workspace, /No projects match these filters/);
  assert.match(workspace, /role="alert"/);
  assert.match(workspace, /aria-label="Projects and progress streams"/);
  assert.match(workspace, /\["construction", "Construction"\]/);
  assert.match(workspace, /contributed_work_units/);
  assert.match(workspace, /required_work_units/);
  assert.doesNotMatch(workspace, /construction[^\n]{0,100}percent/i);
});

test("Living Agents keeps People URLs and creates stable Live City focus links", () => {
  assert.match(routes, /path="people"/);
  assert.match(routes, /path="people\/:agentId"/);
  assert.match(shell, /path: "people", label: "Living Agents"/);
  assert.match(workspace, /params\.set\("view", "diorama"\)/);
  assert.match(workspace, /params\.set\("agent", String\(agent\)\)/);
  assert.match(workspace, /params\.set\("place", String\(place\)\)/);
  assert.match(workspace, /params\.set\("project", project\)/);
  assert.match(workspace, /replace\(\/\^construction:\//);
  assert.match(workspace, /params\.set\("layer", "organizations"\)/);
  assert.match(workspace, /commonObserverParamsFromState\(observerState\)/);
});
