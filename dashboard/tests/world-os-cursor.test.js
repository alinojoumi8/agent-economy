import assert from "node:assert/strict";
import test from "node:test";

import { initialCursorState, reduceCursorState } from "../src/app/cursorReducer.js";

const hello = {
  type: "hello", run_id: "run-1", fork_id: null, semantics_version: 8,
  projection_version: 1, policy_version: 1, view_key: "view-a", event_cursor: 4,
};

function delta(previous, cursor, changes = {}) {
  return {
    type: "projection_delta", run_id: "run-1", fork_id: null,
    semantics_version: 8, projection_version: 1, policy_version: 1,
    view_key: "view-a", previous_event_cursor: previous, event_cursor: cursor,
    ...changes,
  };
}

test("cursor reducer applies only contiguous full-lineage deltas", () => {
  const connected = reduceCursorState(initialCursorState, hello);
  assert.equal(connected.status, "live");
  assert.equal(connected.cursor, 4);
  const applied = reduceCursorState(connected, delta(4, 5));
  assert.equal(applied.cursor, 5);
  assert.equal(applied.status, "live");
  assert.deepEqual(reduceCursorState(applied, delta(4, 5)), applied);
});

test("legacy tick messages mark the transport live without inventing lineage", () => {
  const connected = reduceCursorState(initialCursorState, {
    type: "tick", tick: 0, status: "created",
  });

  assert.equal(connected.status, "live");
  assert.equal(connected.cursor, 0);
  assert.equal(connected.runId, null);
  assert.equal(connected.staleReason, null);
});

test("cursor reducer marks gaps and lineage conflicts stale", () => {
  const connected = reduceCursorState(initialCursorState, hello);
  const gap = reduceCursorState(connected, delta(7, 8));
  assert.equal(gap.status, "stale");
  assert.equal(gap.staleReason, "cursor_gap");
  const conflict = reduceCursorState(connected, delta(4, 5, { fork_id: "fork-2" }));
  assert.equal(conflict.status, "stale");
  assert.equal(conflict.staleReason, "lineage_mismatch");
});

test("historical views never apply live deltas and invalidations are explicit", () => {
  const connected = reduceCursorState(initialCursorState, hello);
  assert.deepEqual(
    reduceCursorState(connected, delta(4, 5), { historical: true }), connected);
  const invalidated = reduceCursorState(connected, {
    type: "projection_invalidated", reason: "backfill_truncated",
  });
  assert.equal(invalidated.status, "stale");
  assert.equal(invalidated.staleReason, "backfill_truncated");
  assert.deepEqual(reduceCursorState(connected, null), connected);
});
