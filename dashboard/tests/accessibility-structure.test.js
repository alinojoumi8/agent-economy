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

test("city instrumentation keeps supporting copy inside each definition", () => {
  const instruments = civicCitySource.match(
    /<dl className="civic-city__instruments"[\s\S]*?<\/dl>/,
  )?.[0];

  assert.ok(instruments, "city instrumentation definition list is present");
  assert.doesNotMatch(instruments, /<\/dd><small>/);
  assert.match(
    instruments,
    /<dd><span className="civic-city__instrument-value">[\s\S]*?<small>[\s\S]*?<\/small><\/dd>/,
  );
});

test("decorative metric sparklines do not duplicate accessible labels and values", () => {
  assert.match(macroSource, /className="mt-2 h-10" aria-hidden="true"/);
  assert.match(macroSource, /<AreaChart[^>]*accessibilityLayer=\{false\}/);
  assert.doesNotMatch(macroSource, /aria-label=\{`\$\{label\} history`\}/);
});
