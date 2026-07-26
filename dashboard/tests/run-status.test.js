import test from "node:test";
import assert from "node:assert/strict";

import { mergeRunPayload, workspaceSemanticsLabel } from "../src/runState.js";


test("tick payload advances the served countdown immediately", () => {
  const current = {
    tick: 4, status: "running", running: true,
    target_tick: 6, remaining_ticks: 2,
  };

  const next = mergeRunPayload(current, {
    type: "tick", tick: 5, status: "running", running: true,
    target_tick: 6, remaining_ticks: 1,
  });

  assert.equal(next.tick, 5);
  assert.equal(next.remaining_ticks, 1);
  assert.equal(next.running, true);
});


test("terminal run status clears running and reaches the served target", () => {
  const current = {
    tick: 5, status: "running", running: true,
    target_tick: 6, remaining_ticks: 1,
    pause_reason: { reason: "provider" }, report_path: "stale-report.html",
  };

  const next = mergeRunPayload(current, {
    type: "run_status", tick: 6, status: "paused", running: false,
    target_tick: 6, remaining_ticks: 0,
    pause_reason: null, report_path: null,
  });

  assert.equal(next.status, "paused");
  assert.equal(next.running, false);
  assert.equal(next.remaining_ticks, 0);
  assert.equal(next.pause_reason, null);
  assert.equal(next.report_path, null);
});


test("workspace label follows the authoritative run semantics", () => {
  assert.equal(
    workspaceSemanticsLabel({ semantics_version: 11 }),
    "Semantics 11 workspace.",
  );
  assert.equal(workspaceSemanticsLabel({}), "World workspace.");
});
