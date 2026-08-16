import assert from "node:assert/strict";
import test from "node:test";

import {
  legacyCityRedirectPath,
  workspaceFallbackPath,
} from "../src/lib/routes.js";

test("unknown run routes redirect once to the absolute run overview", () => {
  assert.equal(
    workspaceFallbackPath("run/id"),
    "/runs/run%2Fid/overview",
  );
  assert.equal(workspaceFallbackPath(undefined), "/");
});

test("legacy overview city selections move to the canonical Live City route", () => {
  assert.equal(
    legacyCityRedirectPath("run/id", "?fork=f-1&tick=4&view=diorama&agent=7", "#evidence"),
    "/runs/run%2Fid/world?fork=f-1&tick=4&view=diorama&agent=7#evidence",
  );
  assert.equal(
    legacyCityRedirectPath("run/id", "?tick=4&agent=7"),
    "/runs/run%2Fid/world?tick=4&agent=7",
  );
  assert.equal(legacyCityRedirectPath("run/id", "?fork=f-1&tick=4"), null);
  assert.equal(legacyCityRedirectPath(undefined, "?view=diorama"), null);
});
