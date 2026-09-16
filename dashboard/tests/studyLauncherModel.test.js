import test from "node:test";
import assert from "node:assert/strict";
import { operatorStudyFrameMatches, parseModelDraws, parseStudySeeds, policyStudyRequest, priceStudyRequest, studyJobActive } from "../src/workspaces/studyLauncherModel.js";

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

test("policy requests bind reviewed designs and draw labels without unrelated intervention controls", () => {
  const design = { id: "a".repeat(32), sha256: "b".repeat(64), private: "not-sent" };
  const form = { preset: "POLICY", origin: "fresh_genesis", design, seeds: "1, 2", horizon: 5,
    model_replicates: "draw1, draw2", intervention_tick: 3, goods_firm_id: 2, warmup_ticks: 1,
    max_provider_calls: 100, max_tokens: 10000, max_spend_usd: .1, max_wall_seconds: 60, max_disk_mib: 128,
    pause_after_ticks: null, pause_after_phase: "MORNING" };
  const request = policyStudyRequest(form, undefined, { items: [design] });
  assert.deepEqual(request.design, { id: design.id, sha256: design.sha256 });
  assert.deepEqual(request.model_replicates, ["draw1", "draw2"]);
  assert.deepEqual(request.seeds, [1, 2]);
  for (const key of ["intervention_tick", "warmup_ticks", "goods_firm_id", "checkpoints", "approve_live_inference"])
    assert.equal(key in request, false);
  assert.throws(() => policyStudyRequest(form, undefined, { items: [{ ...design, sha256: "changed" }] }), /reviewed policy/);
  for (const value of ["", "draw1,draw1", "a,b,c,d", "../a", "Draw1"])
    assert.throws(() => parseModelDraws(value), /distinct model draw/);
  const sources = [1, 2].map(seed => ({ id: String(seed), seed, tick: 2, run_id: String(seed), database_sha256: "db", receipt_sha256: "receipt" }));
  const saved = { ...form, origin: "verified_checkpoints", checkpoints: sources };
  assert.equal(policyStudyRequest(saved, { items: sources }, { items: [design] }).seeds, null);
  assert.throws(() => policyStudyRequest({ ...saved, horizon: 4 }, { items: sources }, { items: [design] }), /three new days/);
  const scripted = priceStudyRequest({ ...form, preset: "G2" }, undefined);
  for (const key of ["design", "model_replicates", "max_provider_calls", "max_tokens", "max_spend_usd"])
    assert.equal(key in scripted, false);
});
