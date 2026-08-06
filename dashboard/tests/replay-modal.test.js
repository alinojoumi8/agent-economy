import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { replayRequestWasCancelled } from "../src/lib/replayRequests.js";

test("replay request cancellation is expected and stale responses are guarded", () => {
  assert.equal(replayRequestWasCancelled({ name: "AbortError" }, { aborted: false }), true);
  assert.equal(replayRequestWasCancelled(new Error("late"), { aborted: true }), true);
  assert.equal(replayRequestWasCancelled(new Error("network"), { aborted: false }), false);

  const source = readFileSync(
    new URL("../src/components/ReplayModal.jsx", import.meta.url), "utf8",
  );
  assert.match(source, /new AbortController\(\)/);
  assert.match(source, /api\(path, \{ signal: controller\.signal \}\)/);
  assert.match(source, /if \(controller\.signal\.aborted\) return/);
  assert.match(source, /controller\.abort\(\)/);
});
