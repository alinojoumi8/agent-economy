import assert from "node:assert/strict";
import test from "node:test";
import {
  normalizeWorkspaceFilters,
  validatedSelectedId,
  workspaceRouteUrl,
} from "../src/workspaces/workspaceRouteState.js";

test("workspace URLs preserve only validated observer and route state", () => {
    assert.equal(
      workspaceRouteUrl(
        "run/id", "markets", { fork: "fork-1", tick: "7" }, { side: "buy" },
      ),
      "/runs/run%2Fid/markets?fork=fork-1&tick=7&side=buy",
    );
    assert.equal(
      workspaceRouteUrl("run", "world", { fork: null, tick: "live" }, {}),
      "/runs/run/world",
    );
    assert.deepEqual(
      normalizeWorkspaceFilters(
        { side: "buy", selected: "12", future_canary: "private" },
        ["side", "selected"],
      ),
      { side: "buy", selected: "12" },
    );
    assert.equal(validatedSelectedId("12"), 12);
    assert.equal(validatedSelectedId("0"), null);
    assert.equal(validatedSelectedId("1.5"), null);
    assert.equal(validatedSelectedId("private"), null);
});
