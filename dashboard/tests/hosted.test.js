import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";

import { api } from "../src/api.js";
import {
  configureHostedRouting,
  hostedCapabilities,
  hostedFetchOptions,
  observatoryWebSocketUrl,
  readCookie,
  resetApiRouting,
  resolveApiRequest,
  tenantApiPath,
} from "../src/hostedRouting.js";

const TENANT = "10000000-0000-4000-8000-000000000001";
const OTHER_TENANT = "20000000-0000-4000-8000-000000000002";
const RUN = "50000000-0000-4000-8000-000000000005";

function hosted(runId = RUN) {
  configureHostedRouting({
    tenantId: TENANT,
    runId,
    csrfCookieName: "__Host-ae_csrf",
    csrfHeaderName: "X-AE-CSRF",
  });
}

test("local API and WebSocket routes remain byte-for-byte compatible", () => {
  resetApiRouting();
  assert.deepEqual(resolveApiRequest("/api/run/status"), {
    path: "/api/run/status", method: "GET", body: undefined,
  });
  assert.deepEqual(resolveApiRequest("/api/run/speed", "POST", { delay_s: 1 }), {
    path: "/api/run/speed", method: "POST", body: { delay_s: 1 },
  });
  assert.equal(
    observatoryWebSocketUrl({ protocol: "https:", host: "example.test" }),
    "wss://example.test/ws",
  );
});

test("hosted reads and only the five run controls receive scoped routes", () => {
  hosted();
  assert.equal(
    resolveApiRequest("/api/agents?limit=10").path,
    `/api/v2/tenants/${TENANT}/runs/${RUN}/world/api/agents?limit=10`,
  );
  assert.deepEqual(resolveApiRequest("/api/run/start", "POST", { max_ticks: 3 }), {
    path: `/api/v2/tenants/${TENANT}/runs/${RUN}/control`,
    method: "POST", body: { action: "start", max_ticks: 3 },
  });
  assert.deepEqual(resolveApiRequest("/api/run/speed", "POST", { delay_s: 0.25 }), {
    path: `/api/v2/tenants/${TENANT}/runs/${RUN}/control`,
    method: "POST", body: { action: "speed", delay_s: 0.25 },
  });
  for (const [path, action] of [
    ["/api/run/pause", "pause"], ["/api/run/stop", "stop"], ["/api/run/step", "step"],
  ]) {
    assert.deepEqual(resolveApiRequest(path, "POST"), {
      path: `/api/v2/tenants/${TENANT}/runs/${RUN}/control`,
      method: "POST", body: { action },
    });
  }
  assert.throws(
    () => resolveApiRequest("/api/shocks", "POST", {}),
    /mutation is unavailable/,
  );
  assert.equal(
    observatoryWebSocketUrl({ protocol: "https:", host: "hosted.test" }),
    `wss://hosted.test/api/v2/tenants/${TENANT}/runs/${RUN}/ws`,
  );
});

test("CSRF uses only the readable CSRF cookie and is attached to mutations", () => {
  hosted();
  const cookie = "theme=dark; __Host-ae_csrf=csrf-value_123; ignored=value";
  assert.equal(readCookie("__Host-ae_csrf", cookie), "csrf-value_123");
  const mutation = hostedFetchOptions({
    path: tenantApiPath("/runs"), method: "POST", headers: { "Content-Type": "application/json" },
  }, cookie);
  assert.equal(mutation.credentials, "same-origin");
  assert.equal(mutation.headers["X-AE-CSRF"], "csrf-value_123");
  const query = hostedFetchOptions({ path: tenantApiPath("/runs"), method: "GET" }, cookie);
  assert.equal(query.credentials, "same-origin");
  assert.equal(query.headers, undefined);
  assert.throws(
    () => hostedFetchOptions({ path: tenantApiPath("/runs"), method: "POST" }, ""),
    /CSRF cookie is missing/,
  );
});

test("API fetch applies hosted control routing and CSRF without exposing a token", async () => {
  hosted();
  const originalFetch = globalThis.fetch;
  let captured;
  globalThis.fetch = async (path, options) => {
    captured = { path, options };
    return { ok: true, status: 200, statusText: "OK", json: async () => ({ status: "paused" }) };
  };
  try {
    await api("/api/run/pause", {
      method: "POST",
      routingBody: undefined,
      cookieString: "__Host-ae_csrf=only-csrf-material",
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
  assert.equal(captured.path, `/api/v2/tenants/${TENANT}/runs/${RUN}/control`);
  assert.equal(captured.options.headers["X-AE-CSRF"], "only-csrf-material");
  assert.deepEqual(JSON.parse(captured.options.body), { action: "pause" });
  assert.equal("cookieString" in captured.options, false);
});

test("client refuses inferred or cross-tenant identifiers", () => {
  hosted();
  assert.throws(() => tenantApiPath("/runs", OTHER_TENANT), /cross-tenant/);
  assert.throws(
    () => resolveApiRequest(`/api/v2/tenants/${OTHER_TENANT}/runs`, "GET", undefined, { bypass: true }),
    /cross-tenant/,
  );
  configureHostedRouting({
    csrfCookieName: "__Host-ae_csrf", csrfHeaderName: "X-AE-CSRF",
  });
  assert.throws(() => resolveApiRequest("/api/run/status"), /select a hosted run/);
});

test("hosted roles present exactly the bounded control surface", () => {
  assert.deepEqual(hostedCapabilities("observer"), {
    administerTenant: false, createRuns: false, controlRuns: false,
    observeRuns: true, mutateWorld: false,
  });
  assert.deepEqual(hostedCapabilities("admin"), {
    administerTenant: true, createRuns: true, controlRuns: true,
    observeRuns: true, mutateWorld: false,
  });
});

test("dashboard source contains no persistent browser credential storage", () => {
  const root = new URL("../src/", import.meta.url);
  const files = [];
  function visit(path) {
    for (const name of readdirSync(path)) {
      const candidate = join(path, name);
      if (statSync(candidate).isDirectory()) visit(candidate);
      else if (/\.(js|jsx)$/.test(name)) files.push(candidate);
    }
  }
  visit(root.pathname.replace(/^\/(.:\/)/, "$1"));
  const source = files.map(file => readFileSync(file, "utf8")).join("\n");
  assert.doesNotMatch(source, /\b(?:localStorage|sessionStorage|indexedDB)\b/);
  assert.doesNotMatch(source, /setItem\s*\(/);
});

