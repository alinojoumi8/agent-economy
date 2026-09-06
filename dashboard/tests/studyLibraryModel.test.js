import assert from "node:assert/strict";
import test from "node:test";
import { studyFrameMatches, studyNumber, studyOutcomeRows } from "../src/workspaces/studyLibraryModel.js";

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
