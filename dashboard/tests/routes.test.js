import assert from "node:assert/strict";
import test from "node:test";

import { workspaceFallbackPath } from "../src/lib/routes.js";

test("unknown run routes redirect once to the absolute run overview", () => {
  assert.equal(
    workspaceFallbackPath("run/id"),
    "/runs/run%2Fid/overview",
  );
  assert.equal(workspaceFallbackPath(undefined), "/");
});
