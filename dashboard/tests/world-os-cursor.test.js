import assert from "node:assert/strict";
import test from "node:test";

import { readFileSync } from "node:fs";

import { announcedCursor, initialCursorState, reduceCursorState } from "../src/app/cursorReducer.js";

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

test("socket closure becomes reconnecting until an authoritative hello arrives", () => {
  const connected = reduceCursorState(initialCursorState, hello);
  const reconnecting = reduceCursorState(connected, {
    type: "transport_closed", reason: "socket_closed",
  });

  assert.equal(reconnecting.status, "reconnecting");
  assert.equal(reconnecting.staleReason, "socket_closed");
  assert.equal(reconnecting.cursor, connected.cursor);

  const recovered = reduceCursorState(reconnecting, { ...hello, event_cursor: 6 });
  assert.equal(recovered.status, "live");
  assert.equal(recovered.staleReason, null);
  assert.equal(recovered.cursor, 6);
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

test("cursor_ahead resets cursor below client N, marks stale, then accepts M to M+1", () => {
  const connected = reduceCursorState(initialCursorState, {
    ...hello, event_cursor: 10,
  });
  assert.equal(connected.cursor, 10);

  const recovered = reduceCursorState(connected, {
    type: "error", code: "cursor_ahead", event_cursor: 4,
  });
  assert.equal(recovered.cursor, 4);
  assert.equal(recovered.status, "stale");
  assert.equal(recovered.staleReason, "cursor_ahead");

  const delayedOldLineage = reduceCursorState(
    recovered, delta(4, 5, { fork_id: "fork-old" }));
  assert.equal(delayedOldLineage.status, "stale");
  assert.equal(delayedOldLineage.staleReason, "lineage_mismatch");
  assert.equal(delayedOldLineage.cursor, 4);

  const contiguous = reduceCursorState(recovered, delta(4, 5));
  assert.equal(contiguous.cursor, 5);
  assert.equal(contiguous.status, "live");
  assert.equal(contiguous.staleReason, null);
});

test("a truncated recovery adopts the announced cursor so the next delta is contiguous", () => {
  const connected = reduceCursorState(initialCursorState, hello);
  assert.equal(connected.cursor, 4);

  const invalidated = reduceCursorState(connected, {
    type: "projection_invalidated", reason: "backfill_truncated", event_cursor: 9,
  });
  assert.equal(invalidated.status, "stale");
  assert.equal(invalidated.staleReason, "backfill_truncated");
  assert.equal(invalidated.cursor, 9);
  const resumed = reduceCursorState(invalidated, delta(9, 10));
  assert.equal(resumed.status, "live");
  assert.equal(resumed.cursor, 10);

  // Same cursor: nothing moves. No cursor: nothing is invented.
  assert.equal(reduceCursorState(connected, {
    type: "projection_invalidated", reason: "backfill_truncated", event_cursor: 4,
  }).cursor, 4);
  assert.equal(reduceCursorState(connected, {
    type: "projection_invalidated", reason: "backfill_truncated", event_cursor: null,
  }).cursor, 4);
  assert.equal(reduceCursorState(connected, {
    type: "projection_invalidated", reason: "backfill_truncated",
  }).cursor, 4);

  assert.equal(announcedCursor({ event_cursor: 0 }), 0);
  assert.equal(announcedCursor({ event_cursor: "12" }), 12);
  assert.equal(announcedCursor({ event_cursor: null }), null);
  assert.equal(announcedCursor({ event_cursor: "later" }), null);
  assert.equal(announcedCursor({}), null);
  assert.equal(announcedCursor(null), null);
});

test("tick frames leave a pending recovery stale but still revive a fresh or reconnecting transport", () => {
  const connected = reduceCursorState(initialCursorState, hello);
  const tick = { type: "tick", tick: 7, status: "running" };

  const gap = reduceCursorState(connected, delta(7, 8));
  assert.equal(reduceCursorState(gap, tick), gap);
  const ahead = reduceCursorState(connected, { type: "error", code: "cursor_ahead", event_cursor: 2 });
  assert.equal(reduceCursorState(ahead, tick).staleReason, "cursor_ahead");
  const mismatch = reduceCursorState(connected, delta(4, 5, { fork_id: "fork-2" }));
  assert.equal(reduceCursorState(mismatch, tick).staleReason, "lineage_mismatch");
  const invalidated = reduceCursorState(connected, {
    type: "projection_invalidated", reason: "backfill_truncated", event_cursor: 9,
  });
  assert.equal(reduceCursorState(invalidated, tick).status, "stale");

  // Recovery still completes through the stream itself.
  const recovered = reduceCursorState(reduceCursorState(gap, tick), delta(4, 5));
  assert.equal(recovered.status, "live");
  assert.equal(recovered.staleReason, null);

  const reconnecting = reduceCursorState(connected, { type: "transport_closed", reason: "socket_closed" });
  const revived = reduceCursorState(reconnecting, tick);
  assert.equal(revived.status, "live");
  assert.equal(revived.staleReason, null);
  assert.equal(reduceCursorState(initialCursorState, tick).status, "live");
});

test("the client hello is only sent once a server hello has established the protocol", () => {
  const source = readFileSync(
    new URL("../src/app/useProjectionSocket.ts", import.meta.url), "utf8",
  );
  const open = source.match(/addEventListener\("open"[\s\S]*?\n {6}\}\);/)[0];
  assert.match(open, /if \(projectionProtocol\.current && !lineageRecovery\.current\) \{/);
  assert.match(open, /socket\?\.send\(JSON\.stringify\(\{ type: "hello", event_cursor: cursor\.current \}\)\)/);
  // Lineage recovery and cursor gaps keep their explicit hellos.
  assert.match(source, /if \(recoveringLineage\) \{[\s\S]*?type: "hello",\s*event_cursor: cursor\.current/);
  assert.match(source, /nextState\.staleReason === "cursor_gap"[\s\S]*?event_cursor: before/);
  // A truncated recovery's cursor is adopted by the socket as well as the reducer.
  assert.match(source, /message\.type === "projection_invalidated"[\s\S]*?announcedCursor\(message\)[\s\S]*?cursor\.current = invalidatedCursor/);
});
