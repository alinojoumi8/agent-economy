import assert from "node:assert/strict";
import test from "node:test";

import { searchResultPath, workspacePath } from "../src/app/commandNavigation.ts";

const source = new URLSearchParams(
  "fork=fork-a&tick=4&event=7&layer=markets&q=Atlas&activeOnly=1&agent=9",
);

test("workspace navigation preserves only shared observer context", () => {
  assert.equal(
    workspacePath("run/id", "people", source),
    "/runs/run%2Fid/people?fork=fork-a&tick=4&event=7",
  );
});

test("entity kinds map to their established route destinations", () => {
  assert.equal(searchResultPath("run-1", {
    kind: "agent", id: 12, label: "Atlas", sublabel: "Citizen",
  }, source), "/runs/run-1/people/12?fork=fork-a&tick=4&event=7");
  assert.equal(searchResultPath("run-1", {
    kind: "firm", id: 3, label: "Atlas Foods", sublabel: "Firm",
  }, source), "/runs/run-1/organizations/3?fork=fork-a&tick=4&event=7");
  assert.equal(searchResultPath("run-1", {
    kind: "event", id: 81, label: "goods sale", sublabel: "Event",
  }, source), "/runs/run-1/investigations?fork=fork-a&tick=4&event=81");
  assert.equal(searchResultPath("run-1", {
    kind: "communication_thread", id: 6, label: "Bulletin", sublabel: "Thread",
  }, source), "/runs/run-1/news-communications/6?fork=fork-a&tick=4&event=7");
});
