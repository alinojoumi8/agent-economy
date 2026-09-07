import test from "node:test";
import assert from "node:assert/strict";
import { operatorStudyFrameMatches, parseStudySeeds, priceStudyRequest, studyJobActive } from "../src/workspaces/studyLauncherModel.js";

test("study seed parsing preserves explicit zero and rejects duplicates or unsupported numbers", () => {
  assert.deepEqual(parseStudySeeds("0, 2 4"), [0, 2, 4]);
  for (const value of ["", "1,1", "1e2", "-2", "1.5", "2147483648", "1 2 3 4 5 6", "NaN"]) {
    assert.throws(() => parseStudySeeds(value), /unique whole-number seeds/);
  }
});

test("checkpoint choices bind current bytes, preserve independent origins and omit replacement seeds", () => {
  const items = [1, 2].map(seed => ({ id: String(seed).repeat(32), database_sha256: "b".repeat(64),
    receipt_sha256: String(seed).repeat(64), seed, tick: 2, run_id: `world-${seed}`, private: "not-in-request" }));
  const form = { origin: "verified_checkpoints", checkpoints: items, seeds: "77, 88", warmup_ticks: 1, intervention_tick: 4 };
  const request = priceStudyRequest(form, { items });
  assert.equal(request.seeds, null);
  assert.deepEqual(request.checkpoints, items.map(({ id, database_sha256, receipt_sha256 }) => ({ id, database_sha256, receipt_sha256 })));
  assert.throws(() => priceStudyRequest(form, undefined), /Choose one to five/);
  assert.throws(() => priceStudyRequest({ ...form, checkpoints: [] }, { items }), /Choose one to five/);
  assert.throws(() => priceStudyRequest(form, { items: [{ ...items[0], database_sha256: "changed" }, items[1]] }), /changed/);
  for (const change of [{ tick: 3 }, { seed: 1 }, { run_id: "world-1" }]) {
    const changed = [items[0], { ...items[1], ...change }];
    assert.throws(() => priceStudyRequest({ ...form, checkpoints: changed }, { items: changed }), /same saved day/);
  }
  assert.throws(() => priceStudyRequest({ ...form, intervention_tick: 3 }, { items }), /must follow/);
  const fresh = priceStudyRequest({ ...form, origin: "fresh_genesis" }, undefined);
  assert.deepEqual(fresh.seeds, [77, 88]);
  assert.equal(fresh.warmup_ticks, 0);
  assert.equal("checkpoints" in fresh, false);
});

test("operator draft and job frames require exact context and identity", () => {
  const scope = { runId: "run", fork: "fork", tick: "live" };
  const frame = { contract: "job", id: "job-1", context: { run_id: "run", fork_id: "fork", tick: "live" } };
  assert.equal(operatorStudyFrameMatches(frame, scope, "job", "job-1"), true);
  assert.equal(operatorStudyFrameMatches(frame, { ...scope, tick: "1" }, "job", "job-1"), false);
  assert.equal(operatorStudyFrameMatches(frame, { ...scope, fork: null }, "job", "job-1"), false);
  assert.equal(operatorStudyFrameMatches(frame, { ...scope, runId: "other" }, "job", "job-1"), false);
  assert.equal(operatorStudyFrameMatches(frame, scope, "draft", "job-1"), false);
  assert.equal(operatorStudyFrameMatches(frame, scope, "job", "other"), false);
  assert.equal(studyJobActive("interrupted"), false);
  assert.equal(studyJobActive("running"), true);
});
