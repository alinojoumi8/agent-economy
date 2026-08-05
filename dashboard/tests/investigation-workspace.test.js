import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { workspaceErrorMessage } from "../src/app/api.ts";

test("workspace API preserves HTTP status without exposing response internals", async () => {
  const source = await readFile(new URL("../src/app/api.ts", import.meta.url), "utf8");
  assert.match(source, /export class WorkspaceApiError extends Error/);
  assert.match(source, /new WorkspaceApiError\(\s*response\.status/s);
  assert.doesNotMatch(source, /JSON\.stringify\(payload\)/);

  assert.equal(
    workspaceErrorMessage({ detail: "investigation version conflict" }, 409),
    "investigation version conflict",
  );
  assert.equal(workspaceErrorMessage({}, 503), "Workspace request failed (503)");
});
