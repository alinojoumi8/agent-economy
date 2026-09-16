import assert from "node:assert/strict";
import test from "node:test";
import { priceLabFrameMatches, priceLabSelection, priceNumber } from "../src/workspaces/priceLabModel.js";

test("price selection rejects malformed IDs and unsupported windows", () => {
  assert.deepEqual(priceLabSelection(new URLSearchParams()), { firmId: undefined, window: 30, invalid: false });
  assert.deepEqual(priceLabSelection(new URLSearchParams("price_firm=12&price_window=90")), { firmId: 12, window: 90, invalid: false });
  for (const value of ["0", "-1", "1.2", "NaN", "9999999999999999999", "01", "1e3"]) {
    assert.equal(priceLabSelection(new URLSearchParams({ price_firm: value })).invalid, true);
  }
  assert.equal(priceLabSelection(new URLSearchParams("price_window=31")).invalid, true);
});

test("a price frame must match run, fork, tick, selected instrument, window and currency", () => {
  const frame = { run_id: "r", fork_id: "f", tick: 3, projection: "workspace.price_lab",
    data: { contract: "price-lab-projection-v1", tick: 3, start_tick: 0, window_ticks: 30,
      selected_firm: { id: 2, currency_code: "USD" },
      observation: { firm_id: 2, tick: 3, start_tick: 0, currency: "USD" } } };
  const context = { runId: "r", fork: "f", tick: 3, firmId: 2, window: 30 };
  assert.equal(priceLabFrameMatches(frame, context), true);
  assert.equal(priceLabFrameMatches(frame, { ...context, tick: "3" }), true);
  assert.equal(priceLabFrameMatches(frame, { ...context, tick: "invalid" }), false);
  assert.equal(priceLabFrameMatches(frame, { ...context, tick: "live" }), true);
  for (const changed of [{ runId: "other" }, { fork: null }, { tick: 2 }, { firmId: 1 }, { window: 7 }]) {
    assert.equal(priceLabFrameMatches(frame, { ...context, ...changed }), false);
  }
  const mixed = structuredClone(frame);
  mixed.data.observation.currency = "CAD";
  assert.equal(priceLabFrameMatches(mixed, context), false);
  mixed.data.observation.currency = "USD";
  mixed.data.observation.tick = 4;
  assert.equal(priceLabFrameMatches(mixed, context), false);
});

test("a truly empty frame is allowed but cannot satisfy a requested firm", () => {
  const frame = { run_id: "r", fork_id: null, tick: 0, projection: "workspace.price_lab",
    data: { contract: "price-lab-projection-v1", tick: 0, window_ticks: 7, selected_firm: null, observation: null } };
  const context = { runId: "r", fork: null, tick: 0, window: 7 };
  assert.equal(priceLabFrameMatches(frame, context), true);
  assert.equal(priceLabFrameMatches(frame, { ...context, firmId: 1 }), false);
  assert.equal(priceNumber(null), "Unavailable");
  assert.equal(priceNumber(Number.NaN), "Unavailable");
  assert.equal(priceNumber(0), "0");
});
