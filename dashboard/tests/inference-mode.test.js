import assert from "node:assert/strict";
import test from "node:test";

import { inferenceMode } from "../src/lib/inferenceMode.js";

test("network providers are labeled as live AI", () => {
  assert.deepEqual(
    inferenceMode({
      ready: true,
      mode: "network",
      providers: [{ name: "minimax" }, { name: "kimi" }],
    }),
    {
      label: "Live AI · minimax + kimi",
      title: "Native agent decisions are routed to network LLM providers.",
      tone: "good",
      live: true,
    },
  );
});

test("scripted providers explicitly say that no LLM calls occur", () => {
  assert.equal(
    inferenceMode({ ready: true, mode: "scripted", providers: [] }).label,
    "Scripted AI · no LLM calls",
  );
});

test("invalid provider configuration is never labeled live", () => {
  const mode = inferenceMode({ ready: false, errors: ["missing API key"] });
  assert.equal(mode.live, false);
  assert.equal(mode.label, "AI unavailable");
  assert.equal(mode.title, "missing API key");
});
