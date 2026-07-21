import assert from "node:assert/strict";
import test from "node:test";

import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { act as rendererAct, create as createRenderer } from "react-test-renderer";
import { createServer } from "vite";

import {
  eventMatchesRegion,
  firmIdsForRegion,
  inspectionPresentation,
  makeInspection,
  nextRegionFocus,
  normalizeRegion,
  resolveInspection,
} from "../src/observatoryInteraction.js";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

async function mountComponent(element) {
  const originalError = console.error;
  const rendererWarnings = [];
  let renderer;
  console.error = (message, ...args) => {
    if (String(message).includes("react-test-renderer is deprecated")) {
      rendererWarnings.push([message, ...args]);
      return;
    }
    originalError(message, ...args);
  };
  try {
    await rendererAct(async () => { renderer = createRenderer(element); });
  } finally {
    console.error = originalError;
  }
  assert.equal(rendererWarnings.length, 1, "expected only the renderer deprecation notice to be captured");
  return renderer;
}

const buttonsByLabel = (root, label) => root.findAll(
  node => node.type === "button" && node.props["aria-label"] === label,
);
const buttonByLabel = (root, label) => buttonsByLabel(root, label)[0];

function textContent(node) {
  return node.children.map(child => typeof child === "string" ? child : textContent(child)).join("");
}

const buttonByText = (root, text) => root.findAll(
  node => node.type === "button" && textContent(node) === text,
)[0];

test("region focus normalizes valid regions and toggles by numeric id", () => {
  const northstar = { id: "1", region_key: "northstar", name: "Northstar Federation" };
  assert.deepEqual(normalizeRegion(northstar), {
    regionId: 1, regionKey: "northstar", regionName: "Northstar Federation",
  });
  assert.equal(normalizeRegion({ id: "bad" }), null);
  const selected = nextRegionFocus(null, northstar);
  assert.equal(selected.regionId, 1);
  assert.equal(nextRegionFocus(selected, northstar), null);
});

test("firm membership uses only active firm ids explicitly mapped to the region", () => {
  assert.deepEqual([...firmIdsForRegion({ firms: [
    { id: 8, region_id: 1 }, { id: "9", region_id: "1" },
    { id: 10, region_id: 2 }, { id: "bad", region_id: 1 },
  ] }, 1)], [8, 9]);
  assert.deepEqual([...firmIdsForRegion({ firms: null }, 1)], []);
});

test("event matching accepts only explicit top-level region keys", () => {
  assert.equal(eventMatchesRegion({ payload: { origin_region_id: "2" } }, 2), true);
  assert.equal(eventMatchesRegion({ payload: { destination_region_id: 2 } }, 2), true);
  assert.equal(eventMatchesRegion({ payload: { agent_id: 2 } }, 2), false);
  assert.equal(eventMatchesRegion({ payload: { nested: { region_id: 2 } } }, 2), false);
  assert.equal(eventMatchesRegion({ payload: null }, 2), false);
});

test("inspection resolves the newest record and retains a last-observed fallback", () => {
  const reference = makeInspection(
    { kind: "firm", id: 7, title: "Anchor Works" },
    { id: 7, name: "Anchor Works", cash_cents: 10 },
  );
  const current = resolveInspection(reference, {
    firms: [{ id: 7, name: "Anchor Works", cash_cents: 25 }],
  });
  assert.equal(current.record.cash_cents, 25);
  assert.equal(current.lastObserved, false);

  const missing = resolveInspection(reference, { firms: [] });
  assert.equal(missing.record.cash_cents, 10);
  assert.equal(missing.lastObserved, true);
});

test("inspection presentation is safe for unsupported and malformed snapshots", () => {
  const known = inspectionPresentation(makeInspection(
    { kind: "news", id: 3 },
    { id: 3, headline: "A verified headline", body: "Full story", tick: 92 },
  ), { news: [] });
  assert.equal(known.title, "A verified headline");
  assert.equal(known.narrative, "Full story");
  assert.equal(known.lastObserved, true);
  assert.ok(known.fields.some(field => field.label === "Day" && field.value === "92"));

  const unknown = inspectionPresentation(makeInspection(
    { kind: "mystery", id: null }, { circular: null },
  ), {});
  assert.equal(unknown.title, "Unsupported inspection item");
  assert.deepEqual(unknown.fields, []);
});

test("inspection presentation safely formats circular objects in allowlisted arrays", () => {
  const circular = {};
  circular.self = circular;
  let presentation;

  assert.doesNotThrow(() => {
    presentation = inspectionPresentation(makeInspection(
      { kind: "news", id: 4 },
      { id: 4, headline: "Circular evidence", slant_tags: [circular] },
    ), { news: [] });
  });
  assert.equal(
    presentation.fields.find(field => field.label === "Slant tags")?.value,
    "Unable to serialize value",
  );
});

test("focus bar names exactly the three region-filtered panels", async () => {
  const vite = await createServer({ appType: "custom", logLevel: "silent", server: { middlewareMode: true } });
  try {
    const { RegionFocusBar } = await vite.ssrLoadModule("/src/components/ObservatoryInteraction.jsx");
    const markup = renderToStaticMarkup(React.createElement(RegionFocusBar, {
      regionFocus: { regionId: 1, regionKey: "northstar", regionName: "Northstar Federation" },
      onClear: () => {},
    }));
    assert.match(markup, /Northstar Federation/);
    assert.match(markup, /Firms, agents, and region-tagged events/);
    assert.match(markup, /aria-label="Clear Northstar Federation region filter"/);
    assert.doesNotMatch(markup, /banks are filtered/i);
  } finally { await vite.close(); }
});

test("drawer is modeless, labelled, and exposes last-observed state", async () => {
  const vite = await createServer({ appType: "custom", logLevel: "silent", server: { middlewareMode: true } });
  try {
    const { InspectorDrawer } = await vite.ssrLoadModule("/src/components/ObservatoryInteraction.jsx");
    const snapshot = { id: 4, name: "Northstar Reserve", status: "open", deposits_cents: 500 };
    snapshot.self = snapshot;
    const inspection = makeInspection({ kind: "bank", id: 4 }, snapshot);
    const markup = renderToStaticMarkup(React.createElement(InspectorDrawer, {
      inspection, data: { banks: [] }, onClose: () => {}, headingRef: { current: null },
    }));
    assert.match(markup, /aria-label="Observatory inspector"/);
    assert.doesNotMatch(markup, /aria-modal="true"/);
    assert.match(markup, /Northstar Reserve/);
    assert.match(markup, /Last observed/);
    assert.match(markup, /Close inspector/);
    assert.match(markup, /Unable to serialize this snapshot/);
  } finally { await vite.close(); }
});

test("agent directory encodes region after search and tier and before cursor", async () => {
  const vite = await createServer({ appType: "custom", logLevel: "silent", server: { middlewareMode: true } });
  try {
    const { agentDirectoryPath } = await vite.ssrLoadModule("/src/components/AgentsPanel.jsx");
    assert.equal(
      agentDirectoryPath({ filter: "Ada Core", tier: "core", regionId: 2, afterId: 100 }),
      "/api/agents?limit=100&q=Ada+Core&population_tier=core&region_id=2&after_id=100",
    );
    const { readFile } = await import("node:fs/promises");
    const source = await readFile(new URL("../src/components/AgentsPanel.jsx", import.meta.url), "utf8");
    assert.match(source, /useEffect\(\(\) => \{\s*setCursors\(\[null\]\);\s*setPageIndex\(0\);\s*\}, \[regionId\]\)/);
    assert.doesNotMatch(source, /loadOlderAgentOutputs|onLoadOlderOutputs/);
    const observatorySource = await readFile(new URL("../src/hooks/useObservatory.js", import.meta.url), "utf8");
    assert.doesNotMatch(observatorySource, /api\("\/api\/agents"\)/);
  } finally { await vite.close(); }
});

function assertButtonsContainOnlyPhrasingContent(markup) {
  const buttons = [...markup.matchAll(/<button\b[^>]*>([\s\S]*?)<\/button>/g)];
  assert.ok(buttons.length > 0, "expected at least one native button");
  for (const [, content] of buttons) {
    assert.doesNotMatch(content, /<(?:article|div|dl|dt|dd|h[1-6]|p|pre|section|table|tr|td)\b/);
  }
}

test("inspection triggers use native button semantics and preserve exact inspection data", async () => {
  const vite = await createServer({ appType: "custom", logLevel: "silent", server: { middlewareMode: true } });
  try {
    const { inspectionButtonProps } = await vite.ssrLoadModule("/src/components/ObservatoryInteraction.jsx");
    assert.equal(typeof inspectionButtonProps, "function");
    const reference = { kind: "firm", id: 7, title: "Anchor Works" };
    const snapshot = { id: 7, name: "Anchor Works", cash_cents: 25 };
    const calls = [];
    const props = inspectionButtonProps((...args) => calls.push(args), reference, snapshot, "Inspect firm Anchor Works");

    assert.equal(props.type, "button");
    assert.equal(props.role, undefined);
    assert.equal(props.tabIndex, undefined);
    assert.equal(props.onKeyDown, undefined);
    assert.equal(props["aria-label"], "Inspect firm Anchor Works");

    props.onClick({ type: "click" });
    assert.deepEqual(calls, [[reference, snapshot]]);
  } finally { await vite.close(); }
});

test("mounted primary panels route each inspection button to its exact reference and snapshot", async () => {
  const vite = await createServer({ appType: "custom", logLevel: "silent", server: { middlewareMode: true } });
  let renderer;
  try {
    const { ObservatoryInteractionContext } = await vite.ssrLoadModule("/src/components/ObservatoryInteraction.jsx");
    assert.ok(ObservatoryInteractionContext, "expected a controlled interaction context export");
    const { BanksPanel, FirmsPanel, InstitutionsPanel } = await vite.ssrLoadModule("/src/components/WorldPanels.jsx");
    const { EventsPanel, NewsPanel } = await vite.ssrLoadModule("/src/components/InformationPanels.jsx");
    const { MacroOverview } = await vite.ssrLoadModule("/src/components/MacroOverview.jsx");

    const bank = { id: 4, name: "Northstar Reserve", deposits_cents: 500, reserves_cents: 100, reserve_ratio: 0.2, avg_trust: 0.8, status: "open" };
    const firm = { id: 7, name: "Anchor Works", status: "listed", last_stock_price: 12, employees: 3, price_cents: 40, cash_cents: 500 };
    const government = { enabled: true, tax_rate_bps: 1000, unemployment_benefit_cents: 20, treasury_cents: 100 };
    const vc = { exists: true, fund_cents: 200, portfolio: [] };
    const health = { epidemic_multiplier: 1, hospital: { name: "Clinic" }, insurer: { name: "Mutual" }, insured_count: 4 };
    const news = { id: 3, tick: 7, outlet_name: "Ledger", headline: "Verified headline", body: "Full story" };
    const event = { id: 11, tick: 4, kind: "regional_trade", importance: 2, payload: { origin_region_id: 2 } };
    const cpiSeries = [{ tick: 1, value: 1.2 }];
    const calls = [];
    const inspect = (...args) => calls.push(args);
    const regionFocus = { regionId: 2, regionKey: "northstar", regionName: "Northstar Federation" };
    const context = { regionFocus, inspect };

    renderer = await mountComponent(React.createElement(
      ObservatoryInteractionContext.Provider,
      { value: context },
      React.createElement(React.Fragment, null,
        React.createElement(BanksPanel, { banks: [bank] }),
        React.createElement(FirmsPanel, { firms: [firm], map: { firms: [{ id: 7, region_id: 2 }] } }),
        React.createElement(InstitutionsPanel, { institutions: {
          government, vc, health,
        } }),
        React.createElement(NewsPanel, { news: [news] }),
        React.createElement(EventsPanel, { events: [event] }),
        React.createElement(MacroOverview, { metrics: { cpi: cpiSeries } }),
      ),
    ));

    const controls = [
      ["Inspect bank Northstar Reserve", 0],
      ["Inspect firm Anchor Works", 0],
      ["Inspect firm Anchor Works", 1],
      ["Inspect institution Government", 0],
      ["Inspect institution Venture capital", 0],
      ["Inspect institution Health economy", 0],
      ["Inspect news article Verified headline", 0],
      ["Inspect event regional trade from day 4", 0],
      ["Inspect macro metric Price level", 0],
    ];
    for (const [label, occurrence] of controls) {
      const button = buttonsByLabel(renderer.root, label)[occurrence];
      assert.ok(button, `expected mounted button ${label}`);
      assert.equal(button.props.type, "button");
      await rendererAct(async () => { button.props.onClick({ type: "click" }); });
    }

    assert.deepEqual(calls.map(([reference]) => reference), [
      { kind: "bank", id: 4, title: "Northstar Reserve" },
      { kind: "firm", id: 7, title: "Anchor Works" },
      { kind: "firm", id: 7, title: "Anchor Works" },
      { kind: "institution", id: "government", title: "Government" },
      { kind: "institution", id: "vc", title: "Venture capital" },
      { kind: "institution", id: "health", title: "Health economy" },
      { kind: "news", id: 3, title: "Verified headline" },
      { kind: "event", id: 11, title: "regional trade" },
      { kind: "macro_metric", id: "cpi", title: "Price level" },
    ]);
    assert.strictEqual(calls[0][1], bank);
    assert.strictEqual(calls[1][1], firm);
    assert.strictEqual(calls[2][1], firm);
    assert.strictEqual(calls[3][1], government);
    assert.strictEqual(calls[4][1], vc);
    assert.strictEqual(calls[5][1], health);
    assert.strictEqual(calls[6][1], news);
    assert.strictEqual(calls[7][1], event);
    assert.deepEqual(calls[8][1], {
      id: "cpi", title: "Price level", help: "Goods-price index", latest: 1.2, delta: null,
      series: cpiSeries,
    });
  } finally {
    if (renderer) await rendererAct(async () => { renderer.unmount(); });
    await vite.close();
  }
});

test("mounted EventsPanel resets Related-only on region changes without resetting Raw", async () => {
  const vite = await createServer({ appType: "custom", logLevel: "silent", server: { middlewareMode: true } });
  let renderer;
  try {
    const { ObservatoryInteractionContext } = await vite.ssrLoadModule("/src/components/ObservatoryInteraction.jsx");
    assert.ok(ObservatoryInteractionContext, "expected a controlled interaction context export");
    const { EventsPanel } = await vite.ssrLoadModule("/src/components/InformationPanels.jsx");
    const inspect = () => {};
    const events = [
      { id: 11, tick: 4, kind: "north_trade", importance: 2, payload: { region_id: 2 } },
      { id: 12, tick: 5, kind: "south_trade", importance: 2, payload: { region_id: 3 } },
    ];
    const north = { regionId: 2, regionKey: "north", regionName: "North" };
    const south = { regionId: 3, regionKey: "south", regionName: "South" };
    const tree = regionFocus => React.createElement(
      ObservatoryInteractionContext.Provider,
      { value: { regionFocus, inspect } },
      React.createElement(EventsPanel, { events }),
    );

    renderer = await mountComponent(tree(north));
    await rendererAct(async () => { buttonByText(renderer.root, "Show all").props.onClick(); });
    await rendererAct(async () => { buttonByText(renderer.root, "Raw").props.onClick(); });
    assert.equal(buttonByText(renderer.root, "Related only").props["aria-pressed"], true);
    assert.ok(buttonByText(renderer.root, "Human"));
    assert.equal(renderer.root.findAllByType("pre").length, 2);

    await rendererAct(async () => { renderer.update(tree(south)); });
    assert.equal(buttonByText(renderer.root, "Show all").props["aria-pressed"], false);
    assert.ok(buttonByText(renderer.root, "Human"));
    assert.equal(renderer.root.findAllByType("pre").length, 1);
    assert.equal(buttonByLabel(renderer.root, "Inspect event north trade from day 4"), undefined);
    assert.ok(buttonByLabel(renderer.root, "Inspect event south trade from day 5"));
  } finally {
    if (renderer) await rendererAct(async () => { renderer.unmount(); });
    await vite.close();
  }
});

test("firm views filter only mapped IDs and retain native table semantics", async () => {
  const vite = await createServer({ appType: "custom", logLevel: "silent", server: { middlewareMode: true } });
  try {
    const { BanksPanel, FirmsPanelView, InstitutionsPanel } = await vite.ssrLoadModule("/src/components/WorldPanels.jsx");
    assert.equal(typeof FirmsPanelView, "function");
    const regionFocus = { regionId: 2, regionKey: "northstar", regionName: "Northstar Federation" };
    const firms = [
      { id: 7, name: "Anchor Works", status: "listed", last_stock_price: 12, employees: 3, price_cents: 40, cash_cents: 500 },
      { id: 8, name: "South Foundry", status: "listed", last_stock_price: 9, employees: 4, price_cents: 35, cash_cents: 400 },
    ];
    const focused = renderToStaticMarkup(React.createElement(FirmsPanelView, {
      firms, map: { firms: [{ id: 7, region_id: 2 }, { id: 8, region_id: 3 }] },
      regionFocus, inspect: () => {},
    }));
    assert.match(focused, /1 firms in Northstar Federation/);
    assert.match(focused, /Anchor Works/);
    assert.doesNotMatch(focused, /South Foundry/);
    assert.match(focused, /<table\b/);
    assert.doesNotMatch(focused, /<tr\b[^>]*(?:role="button"|tabindex=)/);
    assert.match(focused, /<button\b[^>]*aria-label="Inspect firm Anchor Works"/);
    assertButtonsContainOnlyPhrasingContent(focused);

    const empty = renderToStaticMarkup(React.createElement(FirmsPanelView, {
      firms, map: { firms: [] }, regionFocus, inspect: () => {},
    }));
    assert.match(empty, /No active mapped firms are present in Northstar Federation\./);
    assert.doesNotMatch(empty, /South Foundry|Anchor Works/);

    const banks = renderToStaticMarkup(React.createElement(BanksPanel, { banks: [{
      id: 4, name: "Northstar Reserve", deposits_cents: 500, reserves_cents: 100,
      reserve_ratio: 0.2, avg_trust: 0.8, status: "open",
    }] }));
    assert.doesNotMatch(banks, /<tr\b[^>]*(?:role="button"|tabindex=)/);
    assert.match(banks, /<button\b[^>]*aria-label="Inspect bank Northstar Reserve"/);
    assertButtonsContainOnlyPhrasingContent(banks);

    const institutions = renderToStaticMarkup(React.createElement(InstitutionsPanel, { institutions: {
      government: { enabled: true, tax_rate_bps: 1000, unemployment_benefit_cents: 20, treasury_cents: 100 },
      vc: { exists: true, fund_cents: 200, portfolio: [] },
      health: { epidemic_multiplier: 1, hospital: { name: "Clinic" }, insurer: { name: "Mutual" }, insured_count: 4 },
    } }));
    assert.equal((institutions.match(/<article\b/g) || []).length, 3);
    assert.match(institutions, /<dl\b/);
    assert.match(institutions, /aria-label="Inspect institution Government"/);
    assertButtonsContainOnlyPhrasingContent(institutions);
  } finally { await vite.close(); }
});

test("event views render related-only, show-all, empty, and reset states truthfully", async () => {
  const vite = await createServer({ appType: "custom", logLevel: "silent", server: { middlewareMode: true } });
  try {
    const { eventPanelReducer, EventsPanelView, NewsPanel } = await vite.ssrLoadModule("/src/components/InformationPanels.jsx");
    assert.equal(typeof EventsPanelView, "function");
    assert.equal(typeof eventPanelReducer, "function");
    const regionFocus = { regionId: 2, regionKey: "northstar", regionName: "Northstar Federation" };
    const events = [
      { id: 11, tick: 4, kind: "regional_trade", importance: 2, payload: { origin_region_id: 2 } },
      { id: 12, tick: 5, kind: "monetary_policy", importance: 3, payload: { agent_id: 2 } },
    ];
    const renderEvents = showAll => renderToStaticMarkup(React.createElement(EventsPanelView, {
      events, onShock: () => {}, regionFocus, inspect: () => {}, raw: true, showAll,
      onToggleRaw: () => {}, onToggleShowAll: () => {},
    }));
    const relatedOnly = renderEvents(false);
    assert.match(relatedOnly, />Human<\/button>/);
    assert.match(relatedOnly, /aria-pressed="false"[^>]*>Show all<\/button>/);
    assert.match(relatedOnly, />Shock<\/button>/);
    assert.match(relatedOnly, /regional trade/);
    assert.doesNotMatch(relatedOnly, /monetary policy/);
    assert.match(relatedOnly, /<article\b/);
    assert.doesNotMatch(relatedOnly, /<article\b[^>]*(?:role="button"|tabindex=)/);
    assert.match(relatedOnly, /<button\b[^>]*aria-label="Inspect event regional trade from day 4"/);
    assert.match(relatedOnly, /<pre\b/);
    assertButtonsContainOnlyPhrasingContent(relatedOnly);

    const all = renderEvents(true);
    assert.match(all, /aria-pressed="true"[^>]*>Related only<\/button>/);
    assert.match(all, /regional trade/);
    assert.match(all, /monetary policy/);

    const empty = renderToStaticMarkup(React.createElement(EventsPanelView, {
      events: [events[1]], onShock: null, regionFocus, inspect: () => {}, raw: false, showAll: false,
      onToggleRaw: () => {}, onToggleShowAll: () => {},
    }));
    assert.match(empty, /No region-tagged events for Northstar Federation appear in the current event window\./);

    assert.deepEqual(
      eventPanelReducer({ raw: true, showAll: true }, { type: "region-changed" }),
      { raw: true, showAll: false },
    );

    const news = renderToStaticMarkup(React.createElement(NewsPanel, { news: [{
      id: 3, tick: 7, outlet_name: "Ledger", headline: "Verified headline", body: "Full story",
    }] }));
    assert.match(news, /<article\b/);
    assert.match(news, /<h3\b/);
    assert.match(news, /<p\b/);
    assert.match(news, /aria-label="Inspect news article Verified headline"/);
    assertButtonsContainOnlyPhrasingContent(news);
  } finally { await vite.close(); }
});

test("macro metrics retain article and chart semantics around native inspection buttons", async () => {
  const vite = await createServer({ appType: "custom", logLevel: "silent", server: { middlewareMode: true } });
  try {
    const { MacroOverview } = await vite.ssrLoadModule("/src/components/MacroOverview.jsx");
    const markup = renderToStaticMarkup(React.createElement(MacroOverview, {
      metrics: { cpi: [{ tick: 1, value: 1.2 }] },
    }));
    assert.equal((markup.match(/<article\b/g) || []).length, 9);
    assert.doesNotMatch(markup, /<article\b[^>]*(?:role="button"|tabindex=)/);
    assert.match(markup, /<button\b[^>]*aria-label="Inspect macro metric Price level"/);
    assert.match(markup, /aria-label="Price level history"/);
    assertButtonsContainOnlyPhrasingContent(markup);
  } finally { await vite.close(); }
});
