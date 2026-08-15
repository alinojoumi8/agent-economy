import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  LOCAL_ONLY_DOCUMENT_ROUTES,
  presumedDeploymentMode,
} from "../src/lib/deploymentMode.js";

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
