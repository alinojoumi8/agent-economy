import test from "node:test";
import assert from "node:assert/strict";
import { operatorStudyFrameMatches, parseStudySeeds, studyJobActive } from "../src/workspaces/studyLauncherModel.js";

test("study seed parsing preserves explicit zero and rejects duplicates or unsupported numbers", () => {
  assert.deepEqual(parseStudySeeds("0, 2 4"), [0, 2, 4]);
  for (const value of ["", "1,1", "1e2", "-2", "1.5", "2147483648", "1 2 3 4 5 6", "NaN"]) {
    assert.throws(() => parseStudySeeds(value), /unique whole-number seeds/);
  }
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
