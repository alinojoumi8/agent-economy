import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  LOCAL_ONLY_DOCUMENT_ROUTES,
  presumedDeploymentMode,
} from "../src/lib/deploymentMode.js";
import {
  classifyModeProbe,
  MODE_PROBE_ATTEMPTS,
  modeProbeRetryDelay,
} from "../src/hooks/useHostedMode.js";

const appSource = readFileSync(
  new URL("../src/App.jsx", import.meta.url), "utf8",
);
const hookSource = readFileSync(
  new URL("../src/hooks/useHostedMode.js", import.meta.url), "utf8",
);
const bootShellSource = readFileSync(
  new URL("../src/components/BootShell.jsx", import.meta.url), "utf8",
);

test("run and commons documents are local before any network call", () => {
  assert.equal(presumedDeploymentMode("/runs/53f5b4ce8c/overview"), "local");
  assert.equal(presumedDeploymentMode("/runs/53f5b4ce8c"), "local");
  assert.equal(presumedDeploymentMode("/commons"), "local");
  assert.equal(presumedDeploymentMode("/commons/threads/7"), "local");
});

test("the hosted document path stays unknown until the probe answers", () => {
  // hosted/app.py serves the observatory document at "/" only, and so does the
  // local server, so the root path cannot be resolved from the URL alone.
  assert.equal(presumedDeploymentMode("/"), "unknown");
  assert.equal(presumedDeploymentMode(""), "unknown");
  assert.equal(presumedDeploymentMode(undefined), "unknown");
  assert.equal(presumedDeploymentMode(null), "unknown");
  assert.equal(presumedDeploymentMode(42), "unknown");
});

test("only exact local document routes are presumed, never lookalikes", () => {
  assert.deepEqual([...LOCAL_ONLY_DOCUMENT_ROUTES], ["/runs", "/commons"]);
  assert.equal(presumedDeploymentMode("/runsheet"), "unknown");
  assert.equal(presumedDeploymentMode("/commonsense"), "unknown");
  assert.equal(presumedDeploymentMode("/RUNS/abc"), "unknown");
  assert.equal(presumedDeploymentMode("//runs/abc"), "unknown");
  assert.equal(presumedDeploymentMode("https://evil.test/runs/abc"), "unknown");
});

test("first paint is not gated on the mode probe alone", () => {
  // A bare `mode.loading` gate is the blank-page regression this replaces.
  assert.doesNotMatch(appSource, /if\s*\(\s*mode\.loading\s*\)/);
  assert.match(appSource, /mode\.loading\s*&&\s*mode\.presumed\s*!==\s*"local"/);
  assert.match(appSource, /<BootShell\s*\/>/);
});

test("hosted mode still requires a confirmed hosted config", () => {
  // The presumption may only ever short-circuit to the local shell: hosted
  // routing needs the CSRF names and profile list that only the probe carries.
  assert.match(appSource, /if\s*\(mode\.hosted\)\s*return\s*<HostedShell config=\{mode\.config\}/);
  assert.match(hookSource, /validModeConfig\(value\)\s*\?\s*value\s*:\s*null/);
  assert.match(hookSource, /configureHostedRouting\(\{/);
  assert.doesNotMatch(hookSource, /hosted:\s*true[^}]*presumed/);
});

test("the boot shell announces a pending state without inventing data", () => {
  assert.match(bootShellSource, /aria-busy="true"/);
  assert.match(bootShellSource, /role="status"/);
  // No numeric placeholders standing in for world values.
  assert.doesNotMatch(bootShellSource, /">\s*(0|—|--)\s*</);
});

test("only a definite probe answer selects a deployment; failures are inconclusive and retried", () => {
  const hostedConfig = {
    hosted: true, mode: "hosted", api_base: "/api/v2",
    csrf_cookie_name: "__Host-ae_csrf", csrf_header_name: "X-AE-CSRF", profiles: [],
  };
  assert.deepEqual(
    classifyModeProbe({ ok: true, status: 200, body: hostedConfig }),
    { kind: "hosted", config: hostedConfig },
  );
  assert.deepEqual(
    classifyModeProbe({ ok: true, status: 200, body: {
      mode: "local", hosted: false, api_base: "/api/v2", navigation: null,
    } }),
    { kind: "local" },
  );
  // A network error, a 5xx, a 404, an empty or foreign body, or a hosted document
  // whose config is unusable prove nothing about which server served the page.
  for (const answer of [
    { ok: false, status: 502, body: null },
    { ok: false, status: 404, body: {} },
    { ok: false, status: 0, body: null },
    { ok: true, status: 200, body: null },
    { ok: true, status: 200, body: "<html>" },
    { ok: true, status: 200, body: { mode: "local" } },
    { ok: true, status: 200, body: { hosted: true, mode: "hosted", api_base: "/api/v2" } },
    { ok: true, status: 200, body: { ...hostedConfig, csrf_cookie_name: "bad name" } },
  ]) {
    assert.equal(classifyModeProbe(answer).kind, "inconclusive", JSON.stringify(answer));
  }
  assert.match(classifyModeProbe({ ok: false, status: 502 }).error, /HTTP 502/);
  assert.match(classifyModeProbe({ ok: true, status: 200, body: null }).error, /unrecognised/);

  assert.equal(MODE_PROBE_ATTEMPTS, 3);
  assert.equal(modeProbeRetryDelay(0), 500);
  assert.equal(modeProbeRetryDelay(1), 1_000);
  assert.equal(modeProbeRetryDelay(2), 2_000);
  assert.equal(modeProbeRetryDelay(9), 4_000);
  assert.equal(modeProbeRetryDelay(-1), 500);
});

test("an exhausted probe keeps the boot shell with an error instead of mounting the wrong app", () => {
  // The hook only resets to local routing on a definite "local" verdict and
  // never swallows a failed fetch into "not hosted".
  assert.match(hookSource, /verdict\.kind === "local"\) \{\s*resetApiRouting\(\);/);
  // The old probe swallowed every failure into "not hosted" with this chain.
  assert.doesNotMatch(hookSource, /\.catch\(\(\) => null\)\.then\(/);
  assert.match(hookSource, /attempt \+ 1 < MODE_PROBE_ATTEMPTS/);
  assert.match(hookSource, /error: verdict\.error/);
  // "/" cannot be resolved by presumption, so a failed probe shows the reason.
  assert.match(
    appSource,
    /if \(mode\.error && mode\.presumed !== "local"\) return <BootShell error=\{mode\.error\} \/>;/,
  );
  assert.match(bootShellSource, /export function BootShell\(\{ error = "" \}\)/);
  assert.match(bootShellSource, /role="alert"/);
  assert.match(bootShellSource, /Reload to ask again/);
});
