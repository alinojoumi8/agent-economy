import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const civicCitySource = readFileSync(
  new URL("../src/components/CivicCity.jsx", import.meta.url),
  "utf8",
);
const overviewSource = readFileSync(
  new URL("../src/workspaces/OverviewWorkspace.tsx", import.meta.url),
  "utf8",
);
const macroSource = readFileSync(
  new URL("../src/components/MacroOverview.jsx", import.meta.url),
  "utf8",
);
const workspaceSharedSource = readFileSync(
  new URL("../src/workspaces/workspaceShared.tsx", import.meta.url),
  "utf8",
);

test("labeled World OS summary groups expose a valid semantic role", () => {
  assert.match(
    civicCitySource,
    /className="civic-city__legend" role="group" aria-label="City map legend"/,
  );
  assert.match(
    overviewSource,
    /className="world-os-metrics" role="group" aria-label="World summary"/,
  );
});

test("workspace projection loading state is announced as status", () => {
  assert.match(
    workspaceSharedSource,
    /className="world-os-loading" role="status" aria-label="Loading workspace projection"/,
  );
});

test("city instrumentation keeps supporting copy inside each definition", () => {
  const instruments = civicCitySource.match(
    /<dl className="civic-city__instruments"[\s\S]*?<\/dl>/,
  )?.[0];

  assert.ok(instruments, "city instrumentation definition list is present");
  const definitions = [...instruments.matchAll(/<dd(?:\s[^>]*)?>([\s\S]*?)<\/dd>/g)];
  assert.equal(definitions.length, 9);
  for (const [, content] of definitions) {
    assert.match(content, /<span className="civic-city__instrument-value">[\s\S]*?<small>[\s\S]*?<\/small>/);
  }
  assert.doesNotMatch(instruments, /<\/dd>\s*<small>/);
});

test("construction marks are selectable and the lens states its observer-only boundary", () => {
  assert.match(civicCitySource, /aria-label=\{`Select \$\{project\.name\}/);
  assert.match(civicCitySource, /Stage geometry is derived from stored work units/);
  assert.match(civicCitySource, /cannot assign work, fund a project, or mutate the simulation/);
  assert.match(civicCitySource, /Owners and exact sites withheld/);
});

test("decorative metric sparklines do not duplicate accessible labels and values", () => {
  assert.match(macroSource, /className="mt-2 h-10" aria-hidden="true"/);
  assert.match(macroSource, /<AreaChart[^>]*accessibilityLayer=\{false\}/);
  assert.match(macroSource, /const gradientPrefix = useId\(\)/);
  assert.match(macroSource, /macroGradientId\(gradientPrefix, key\)/);
  assert.doesNotMatch(macroSource, /aria-label=\{`\$\{label\} history`\}/);
});

test("the Living Agents search shows keyboard focus on the drawn field", () => {
  const indexStyles = readFileSync(
    new URL("../src/index.css", import.meta.url),
    "utf8",
  );
  // The input's own ring is suppressed because the label is the visible field...
  assert.match(indexStyles, /\.world-os-agent-search input:focus \{ border: 0; outline: 0; \}/);
  // ...so the label must show focus-within in its place.
  assert.match(
    indexStyles,
    /\.world-os-people-list > label\.world-os-agent-search:focus-within \{[^}]*outline: 2px solid var\(--ae-focus\)/,
  );
});
