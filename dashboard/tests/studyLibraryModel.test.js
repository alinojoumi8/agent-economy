import assert from "node:assert/strict";
import test from "node:test";
import { studyFrameMatches, studyNumber, studyOutcomeRows, studyPhasePosition } from "../src/workspaces/studyLibraryModel.js";

test("study evidence is bound to local live run, fork, study and result identity", () => {
  const frame = { context: { run_id: "run", fork_id: "fork", tick: "live" },
    contract: "operator-study-comparison-v1", id: "study", verification: { result_sha256: "hash" } };
  const scope = { runId: "run", fork: "fork", tick: "live", studyId: "study", resultHash: "hash" };
  assert.equal(studyFrameMatches(frame, scope), true);
  for (const change of [{ runId: "other" }, { fork: null }, { tick: "1" }, { studyId: "other" }, { resultHash: "old" }]) {
    assert.equal(studyFrameMatches(frame, { ...scope, ...change }), false);
  }
});

test("domain comparisons keep missing values distinct from zero and retain pair exclusions", () => {
  const study = { outcomes: [{ key: "goods", domain: "goods" }, { key: "stock", domain: "equities" }],
    summary: { baseline_arm: "base", metrics: { goods: { base: { mean: 100 }, treatment: { mean: 100,
      paired_effect: { mean_difference: 0, ci95_bootstrap: [0, 0], n_pairs: 2, assigned_pairs: 3,
        pair_exclusions: [{ seed: 3, reason: "missing_price" }] } } }, stock: { base: { mean: null } } } } };
  const goods = studyOutcomeRows(study, "goods", "treatment")[0];
  assert.equal(goods.difference, 0);
  assert.equal(goods.pairs, 2);
  assert.deepEqual(goods.exclusions, [{ seed: 3, reason: "missing_price" }]);
  const equity = studyOutcomeRows(study, "equities", "treatment")[0];
  assert.equal(equity.baseline, null);
  assert.equal(equity.difference, null);
  assert.equal(equity.interval, null);
  assert.equal(studyNumber(0), "0");
  for (const value of [null, undefined, NaN, Infinity, "0"]) assert.equal(studyNumber(value), "Unavailable");
});

test("working progress cannot be accepted as a finalized comparison or stale checkpoint", () => {
  const frame = { context: { run_id: "run", fork_id: null, tick: "live" },
    contract: "operator-working-study-v1", id: "study", verification: { result_sha256: "pause" } };
  const scope = { runId: "run", fork: null, tick: "live", studyId: "study", resultHash: "pause", kind: "working" };
  assert.equal(studyFrameMatches(frame, scope), true);
  for (const change of [{ kind: "finalized" }, { resultHash: "old" }, { tick: "3" }, { runId: "other" }]) {
    assert.equal(studyFrameMatches(frame, { ...scope, ...change }), false);
  }
  assert.equal(studyFrameMatches({ ...frame, contract: "operator-study-comparison-v1" }, scope), false);
});

test("only a verified phase can be shown as the next unfinished-day step", () => {
  const row = { ticks: 0, expected_ticks: 3, execution_status: "paused",
    position: { completed_tick: 0, active_tick: 1, next_phase: "NEWSROOM" } };
  assert.equal(studyPhasePosition(row, true), "Day 1 · next: News publication");
  assert.equal(studyPhasePosition(row, false), "Not verified");
  for (const change of [{ active_tick: 2 }, { completed_tick: -1 }, { next_phase: "private-value" }, { active_tick: null }]) {
    assert.equal(studyPhasePosition({ ...row, position: { ...row.position, ...change } }, true), "Unavailable");
  }
  assert.equal(studyPhasePosition({ ticks: 1, execution_status: "paused" }, true), "Between days");
  assert.equal(studyPhasePosition({ execution_status: "planned" }, true), "Not started");
});
