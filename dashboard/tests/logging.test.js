import assert from "node:assert/strict";
import test from "node:test";

import { api, budgetState } from "../src/api.js";
import { clientLog, safeFields } from "../src/logging.js";


test("safeFields redacts credential keys and secret-shaped text", () => {
  const fields = safeFields({
    api_key: "sk-visible",
    in_tokens: 120,
    error: "Bearer abc123 api_key=visible-secret",
  });

  assert.deepEqual(fields, {
    api_key: "[REDACTED]",
    in_tokens: 120,
    error: "[REDACTED] api_key=[REDACTED]",
  });
});


test("clientLog emits one structured JSON record", () => {
  const messages = [];
  const original = console.warn;
  console.warn = message => messages.push(message);
  try {
    const payload = clientLog("dashboard.test.warning", { path: "/api/test" }, "warn");
    assert.equal(payload.event, "dashboard.test.warning");
    assert.equal(payload.level, "WARN");
    assert.equal(messages.length, 1);
    assert.deepEqual(JSON.parse(messages[0]), payload);
  } finally {
    console.warn = original;
  }
});


test("api logs network and HTTP failures with request context", async () => {
  const messages = [];
  const originalFetch = globalThis.fetch;
  const originalError = console.error;
  console.error = message => messages.push(JSON.parse(message));
  try {
    globalThis.fetch = async () => { throw new TypeError("network offline"); };
    await assert.rejects(
      api("/api/network?q=private-user-entry#private-fragment"),
      /network offline/,
    );

    globalThis.fetch = async () => ({
      ok: false, status: 503, statusText: "Unavailable",
      json: async () => ({ error: "provider unavailable" }),
    });
    await assert.rejects(api("/api/provider", { method: "POST" }), /provider unavailable/);
  } finally {
    globalThis.fetch = originalFetch;
    console.error = originalError;
  }

  assert.deepEqual(messages.map(message => message.event), [
    "dashboard.api.network_failed", "dashboard.api.http_failed",
  ]);
  assert.equal(messages[0].path, "/api/network");
  assert.equal(messages[1].method, "POST");
  assert.equal(messages[1].status_code, 503);
});


test("api logs malformed JSON instead of swallowing it silently", async () => {
  const messages = [];
  const originalFetch = globalThis.fetch;
  const originalWarn = console.warn;
  console.warn = message => messages.push(JSON.parse(message));
  globalThis.fetch = async () => ({
    ok: true, status: 200, statusText: "OK",
    json: async () => { throw new SyntaxError("bad JSON"); },
  });
  try {
    assert.deepEqual(await api("/api/malformed"), {});
  } finally {
    globalThis.fetch = originalFetch;
    console.warn = originalWarn;
  }

  assert.equal(messages.length, 1);
  assert.equal(messages[0].event, "dashboard.api.invalid_json");
  assert.equal(messages[0].path, "/api/malformed");
  assert.equal(messages[0].status_code, 200);
});


test("api preserves structured HTTP error messages", async () => {
  const originalFetch = globalThis.fetch;
  const originalError = console.error;
  console.error = () => {};
  globalThis.fetch = async () => ({
    ok: false, status: 422, statusText: "Unprocessable Content",
    json: async () => ({ detail: { message: "Investigation title is invalid." } }),
  });
  try {
    await assert.rejects(api("/api/structured-error"), /Investigation title is invalid\./);
  } finally {
    globalThis.fetch = originalFetch;
    console.error = originalError;
  }
});


test("budgetState distinguishes an uncapped run from the default cap", () => {
  assert.deepEqual(budgetState({ total_spend_usd: 321.5, cap_usd: null }), {
    spend: 321.5, cap: null, capped: false, fraction: 0,
  });
  assert.deepEqual(budgetState({ total_spend_usd: 50, cap_usd: 200 }), {
    spend: 50, cap: 200, capped: true, fraction: 25,
  });
});
