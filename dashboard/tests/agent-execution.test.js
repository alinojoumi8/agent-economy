import assert from "node:assert/strict";
import test from "node:test";

import { agentExecutionPresentation } from "../src/lib/agentExecution.js";

test("native execution is only live when a call receipt exists", () => {
  const live = agentExecutionPresentation({
    state: "live",
    provider: "kimi",
    model: "kimi-for-coding",
    latest_receipt: { kind: "llm_call", id: 41, status: "recorded" },
  });
  assert.equal(live.label, "Live AI");
  assert.equal(live.route, "kimi · kimi-for-coding");
  assert.equal(live.proof, "LLM receipt 41 · recorded");

  const awaiting = agentExecutionPresentation({ state: "awaiting_live" });
  assert.equal(awaiting.label, "Awaiting live wake");
  assert.equal(awaiting.proof, "No receipt yet");
});

test("external execution distinguishes lease and safe fallback", () => {
  assert.equal(
    agentExecutionPresentation({ state: "hermes_connected" }).label,
    "Hermes connected",
  );
  assert.equal(
    agentExecutionPresentation({ state: "offline_fallback" }).label,
    "Offline fallback",
  );
});

test("external action receipts remain visible", () => {
  const view = agentExecutionPresentation({
    state: "hermes_connected",
    latest_receipt: {
      kind: "external_action",
      id: "submission-1",
      status: "executed",
    },
  });
  assert.equal(view.proof, "Action receipt submission-1 · executed");
});
