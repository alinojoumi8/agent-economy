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

test("live macro inspection recomputes the latest delta from the current series", () => {
  const reference = makeInspection(
    { kind: "macro_metric", id: "cpi", title: "Price level" },
    {
      id: "cpi", title: "Price level", help: "Goods-price index",
      latest: 1.2, delta: 0.2, series: [{ tick: 1, value: 1 }, { tick: 2, value: 1.2 }],
    },
  );
  const current = resolveInspection(reference, {
    metrics: { cpi: [{ tick: 3, value: 1.5 }, { tick: 4, value: 1.8 }] },
  });

  assert.equal(current.record.latest, 1.8);
  assert.ok(Math.abs(current.record.delta - 0.3) < 1e-12);
  assert.deepEqual(current.record.series, [
    { tick: 3, value: 1.5 }, { tick: 4, value: 1.8 },
  ]);
  assert.equal(current.lastObserved, false);
});

test("inspection presentation is safe for unsupported and malformed snapshots", () => {
  const known = inspectionPresentation(makeInspection(
    { kind: "news", id: 3 },
    { id: 3, headline: "A verified headline", body: "Full story", tick: 92 },
  ), { news: [] });
  assert.equal(known.title, "A verified headline");
  assert.equal(known.narrative, "Full story");
  assert.equal(known.lastObserved, true);
  assert.deepEqual(known.raw, {
    id: 3, headline: "A verified headline", body: "Full story", tick: 92,
  });
  assert.ok(known.fields.some(field => field.label === "Day" && field.value === "92"));

  const unknown = inspectionPresentation(makeInspection(
    { kind: "mystery", id: null }, { circular: null },
  ), {});
  assert.equal(unknown.title, "Unsupported inspection item");
  assert.deepEqual(unknown.fields, []);
});

function labelledFields(presentation) {
  return Object.fromEntries(presentation.fields.map(field => [field.label, field.value]));
}

test("inspection presentation exposes explicit bank and institution details", () => {
  const bankSnapshot = {
    id: 4, name: "Northstar Reserve", loans_outstanding_cents: 7300,
    internal_password: "not a labelled field",
  };
  const bank = inspectionPresentation(
    makeInspection({ kind: "bank", id: 4 }, bankSnapshot),
    { banks: [bankSnapshot] },
  );
  assert.deepEqual(labelledFields(bank), { "Loans outstanding": "7300" });
  assert.deepEqual(bank.raw, bankSnapshot);

  const institutions = {
    government: {
      enabled: true, tax_rate_bps: 1250, unemployment_benefit_cents: 4500,
      treasury_cents: 99000, last_election: { winner: "Civic Party" },
    },
    vc: { exists: true, fund_cents: 88000, portfolio: [{ firm_id: 7 }] },
    health: {
      epidemic_multiplier: 1.25, hospital: { name: "Central Clinic" },
      insurer: { name: "Mutual" }, insured_count: 42,
    },
  };
  assert.deepEqual(labelledFields(inspectionPresentation(
    makeInspection({ kind: "institution", id: "government", title: "Government" }, institutions.government),
    { institutions },
  )), {
    Enabled: "Yes", "Tax rate": "1250", "Unemployment benefit": "4500",
    Treasury: "99000", "Last election": '{"winner":"Civic Party"}',
  });
  assert.deepEqual(labelledFields(inspectionPresentation(
    makeInspection({ kind: "institution", id: "vc", title: "Venture capital" }, institutions.vc),
    { institutions },
  )), {
    Available: "Yes", "Fund balance": "88000", Portfolio: '{"firm_id":7}',
  });
  assert.deepEqual(labelledFields(inspectionPresentation(
    makeInspection({ kind: "institution", id: "health", title: "Health economy" }, institutions.health),
    { institutions },
  )), {
    Hospital: '{"name":"Central Clinic"}', Insurer: '{"name":"Mutual"}',
    "Insured agents": "42", "Epidemic multiplier": "1.25",
  });
});

test("inspection presentation exposes explicit legal and startup details", () => {
  const matter = {
    id: 101, title: "Docket Alpha", status: "filed", matter_type: "breach",
    venue: "civil", claim_type: "contract", filed_tick: 8,
    requested_remedy: { type: "damages", amount_cents: 10000 },
  };
  const obligation = {
    id: 201, status: "pending", obligation_type: "payment", due_tick: 12,
    amount_cents: 10000, terms: { cadence: "once" },
  };
  const bill = {
    id: 301, title: "Civic Ledger Act", status: "introduced", origin_chamber: "house",
    current_version: 2, introduced_tick: 9, policy_changes: { "ai.audit": true },
  };
  const data = {
    v2: {
      legal: { items: [matter], obligations: [obligation] },
      politics: { bills: [bill] },
      startups: { term_sheets: [] },
    },
  };

  assert.deepEqual(labelledFields(inspectionPresentation(
    makeInspection({ kind: "legal_matter", id: 101 }, matter), data,
  )), {
    Status: "filed", "Matter type": "breach", Venue: "civil", "Claim type": "contract",
    "Filed day": "8", "Requested remedy": '{"type":"damages","amount_cents":10000}',
  });
  assert.deepEqual(labelledFields(inspectionPresentation(
    makeInspection({ kind: "legal_obligation", id: 201 }, obligation), data,
  )), {
    Status: "pending", "Obligation type": "payment", "Due day": "12", Amount: "10000",
    Terms: '{"cadence":"once"}',
  });
  assert.deepEqual(labelledFields(inspectionPresentation(
    makeInspection({ kind: "bill", id: 301 }, bill), data,
  )), {
    Status: "introduced", "Origin chamber": "house", "Current version": "2",
    "Introduced day": "9", "Policy changes": '{"ai.audit":true}',
  });

  const record = {
    id: 401, status: "offered", instrument_type: "safe", amount_cents: 50000,
    valuation_cap_cents: 500000, board_seat: false,
  };
  assert.deepEqual(labelledFields(inspectionPresentation(
    makeInspection({ kind: "startup_record", id: 401, collection: "term_sheets" }, record),
    { v2: { startups: { term_sheets: [record] } } },
  )), {
    Status: "offered", Instrument: "safe", Amount: "50000",
    "Valuation cap": "500000", "Board seat": "No",
  });
  const summarySnapshot = {
    title: "Term sheets", count: 3,
    description: "Summary from the current startup lifecycle payload.",
  };
  const summary = inspectionPresentation(
    makeInspection({ kind: "startup_summary", id: null, title: "Term sheets" }, summarySnapshot),
    {},
  );
  assert.equal(summary.title, "Term sheets");
  assert.equal(summary.narrative, "Summary from the current startup lifecycle payload.");
  assert.deepEqual(labelledFields(summary), { Count: "3" });
  assert.deepEqual(summary.raw, summarySnapshot);
  assert.equal(summary.lastObserved, false);
});

test("inspection presentation serializes allowlisted acceptance and shock evidence safely", () => {
  const check = {
    id: "efficiency", label: "Efficiency cap", passed: false,
    evidence: { spend_usd: 14.25, target_usd: 12 },
  };
  const acceptance = { checks: [check] };
  const checkView = inspectionPresentation(
    makeInspection({ kind: "acceptance_check", id: "efficiency" }, check),
    { acceptance },
  );
  assert.deepEqual(labelledFields(checkView), {
    Passed: "No", Evidence: '{"spend_usd":14.25,"target_usd":12}',
  });

  const trace = {
    passed: true, source: { tick: 5, event_id: 91 },
    downstream: [{ tick: 6, event_id: 92 }],
  };
  const shock = inspectionPresentation(
    makeInspection({ kind: "shock_trace", id: "demand_shock" }, { id: "demand_shock", ...trace }),
    { acceptance: { checks: [{ id: "shock_traces", evidence: { demand_shock: trace } }] } },
  );
  assert.deepEqual(labelledFields(shock), {
    Passed: "Yes", Source: '{"tick":5,"event_id":91}',
    "Downstream evidence": '{"tick":6,"event_id":92}',
  });

  const circular = {};
  circular.self = circular;
  const unsafe = inspectionPresentation(
    makeInspection({ kind: "acceptance_check", id: null }, { passed: false, evidence: circular }),
    {},
  );
  assert.equal(labelledFields(unsafe).Evidence, "Unable to serialize value");
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
    const { agentDirectoryEmptyMessage, agentDirectoryPath } = await vite.ssrLoadModule("/src/components/AgentsPanel.jsx");
    assert.equal(
      agentDirectoryPath({ filter: "Ada Core", tier: "core", regionId: 2, afterId: 100 }),
      "/api/agents?limit=100&q=Ada+Core&population_tier=core&region_id=2&after_id=100",
    );
    assert.equal(typeof agentDirectoryEmptyMessage, "function");
    assert.equal(agentDirectoryEmptyMessage({
      loading: false, error: "502 Bad Gateway", hasValidPage: false, regionFocus: null,
    }), "Agent directory is unavailable.");
    assert.equal(agentDirectoryEmptyMessage({
      loading: false, error: "502 Bad Gateway", hasValidPage: true,
      regionFocus: { regionName: "Northstar Federation" },
    }), "No agents match this search in Northstar Federation.");
    assert.equal(agentDirectoryEmptyMessage({
      loading: true, error: "", hasValidPage: false, regionFocus: null,
    }), "Loading agents…");
    const { readFile } = await import("node:fs/promises");
    const source = await readFile(new URL("../src/components/AgentsPanel.jsx", import.meta.url), "utf8");
    assert.match(source, /useEffect\(\(\) => \{\s*setCursors\(\[null\]\);\s*setPageIndex\(0\);\s*\}, \[regionId\]\)/);
    assert.doesNotMatch(source, /loadOlderAgentOutputs|onLoadOlderOutputs/);
    const observatorySource = await readFile(new URL("../src/hooks/useObservatory.js", import.meta.url), "utf8");
    assert.doesNotMatch(observatorySource, /api\("\/api\/agents"\)/);
  } finally { await vite.close(); }
});

test("mounted provider clears a missing selected region and announces its name", async () => {
  const vite = await createServer({ appType: "custom", logLevel: "silent", server: { middlewareMode: true } });
  let renderer;
  try {
    const {
      ObservatoryInteractionContext, ObservatoryInteractionProvider,
    } = await vite.ssrLoadModule("/src/components/ObservatoryInteraction.jsx");
    let interaction;
    function Probe() {
      interaction = React.useContext(ObservatoryInteractionContext);
      return null;
    }
    const northstar = { id: 2, region_key: "northstar", name: "Northstar Federation" };
    const tree = regions => React.createElement(
      ObservatoryInteractionProvider,
      { data: { v2: { map: { regions } } } },
      React.createElement(Probe),
    );

    renderer = await mountComponent(tree([northstar]));
    await rendererAct(async () => { interaction.selectRegion(northstar); });
    assert.equal(interaction.regionFocus?.regionName, "Northstar Federation");

    await rendererAct(async () => { renderer.update(tree([])); });
    assert.equal(interaction.regionFocus, null);
    const liveRegion = renderer.root.find(
      node => node.props["aria-live"] === "polite" && node.props["aria-atomic"] === "true",
    );
    assert.equal(
      textContent(liveRegion),
      "Northstar Federation is no longer available; the region filter was cleared.",
    );
  } finally {
    if (renderer) await rendererAct(async () => { renderer.unmount(); });
    await vite.close();
  }
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

test("mounted extended panels route every inspection button to its exact reference and snapshot", async () => {
  const vite = await createServer({ appType: "custom", logLevel: "silent", server: { middlewareMode: true } });
  let renderer;
  try {
    const { ObservatoryInteractionContext } = await vite.ssrLoadModule("/src/components/ObservatoryInteraction.jsx");
    const { InstitutionalPulse, LegalPoliticalPanels } = await vite.ssrLoadModule("/src/components/V2Observatory.jsx");
    const { AcceptancePanel } = await vite.ssrLoadModule("/src/components/AcceptancePanel.jsx");
    const { CostPanel } = await vite.ssrLoadModule("/src/components/OracleAndCost.jsx");

    const matter = { id: 101, title: "Docket Alpha", status: "open", matter_type: "contract_dispute", ruleset: "commercial" };
    const obligation = { id: 201, obligation_type: "delivery_term", status: "open" };
    const bill = { id: 301, title: "Civic Ledger Act", origin_chamber: "assembly", status: "introduced" };
    const termSheet = { id: 401, title: "Seed Accord", status: "proposed" };
    const fundingRound = { id: 402, name: "Series A", status: "closed" };
    const ipAsset = { id: 403, name: "Patent Delta", status: "filed" };
    const merger = { id: 404, title: "Northstar merger", status: "review" };
    const check = { id: "efficiency", label: "Efficiency cap", passed: false, evidence: {} };
    const shockCheck = {
      id: "shock_traces", label: "Shock traces", passed: true,
      evidence: {
        demand_shock: { passed: true, source: { tick: 5 }, downstream: [{ tick: 6 }] },
        supply_shock: { passed: false, source: { tick: 8 }, downstream: [] },
      },
    };
    const modelCost = { model: "MiniMax-M3", calls: 7, cost_usd: 1.25 };
    const purposeCost = { purpose: "decision", calls: 3, cost_usd: 0.5 };
    const agentCost = { agent_id: 77, agent_name: "Ada", role: "consumer", calls: 4, cost_usd: 0.75 };
    const sharedCost = { agent_id: null, agent_name: "Shared", role: "system", calls: 2, cost_usd: 0.25 };
    const legal = { contracts: [], items: [matter], obligations: [obligation] };
    const politics = { bills: [bill], lobbying: { items: [] } };
    const startups = {
      term_sheets: [termSheet], funding_rounds: [fundingRound], ip_assets: [ipAsset], mergers: [merger],
    };
    const acceptance = {
      configured: true, passed: false, checks: [check, shockCheck],
      progress: { fraction: 0.5, completed_ticks: 5, required_ticks: 10 }, orchestration: {},
    };
    const calls = [];
    const inspect = (...args) => calls.push(args);

    renderer = await mountComponent(React.createElement(
      ObservatoryInteractionContext.Provider,
      { value: { inspect } },
      React.createElement(React.Fragment, null,
        React.createElement(InstitutionalPulse, { legal, politics, information: {}, datasets: {} }),
        React.createElement(LegalPoliticalPanels, { legal, politics, information: {}, startups, markets: {} }),
        React.createElement(AcceptancePanel, { acceptance }),
        React.createElement(CostPanel, {
          cost: { by_model: [modelCost], by_purpose: [purposeCost], by_agent: [agentCost, sharedCost] },
          readiness: { providers: [] },
        }),
      ),
    ));

    const labels = [
      "Inspect legal matter Docket Alpha",
      "Inspect legal obligation 201",
      "Inspect bill Civic Ledger Act",
      "Inspect startup summary Term sheets",
      "Inspect startup summary Funding rounds",
      "Inspect startup summary IP assets",
      "Inspect startup summary M&A reviews",
      "Inspect startup record Seed Accord",
      "Inspect startup record Series A",
      "Inspect startup record Patent Delta",
      "Inspect startup record Northstar merger",
      "Inspect acceptance check Efficiency cap",
      "Inspect acceptance check Shock traces",
      "Inspect demand shock shock trace",
      "Inspect supply shock shock trace",
      "Inspect provider model cost MiniMax-M3",
      "Inspect provider purpose cost decision",
      "Inspect provider agent cost Ada",
      "Inspect provider agent cost Shared",
    ];
    for (const label of labels) {
      const button = buttonByLabel(renderer.root, label);
      assert.ok(button, `expected mounted button ${label}`);
      assert.equal(button.props.type, "button");
      await rendererAct(async () => { button.props.onClick({ type: "click" }); });
    }

    assert.equal(renderer.root.findAll(node => node.type === "button" && node.props["aria-label"]?.startsWith("Inspect ")).length, labels.length);
    assert.deepEqual(calls.map(([reference]) => reference), [
      { kind: "legal_matter", id: 101, title: "Docket Alpha" },
      { kind: "legal_obligation", id: 201, title: "delivery term" },
      { kind: "bill", id: 301, title: "Civic Ledger Act" },
      { kind: "startup_summary", id: null, title: "Term sheets" },
      { kind: "startup_summary", id: null, title: "Funding rounds" },
      { kind: "startup_summary", id: null, title: "IP assets" },
      { kind: "startup_summary", id: null, title: "M&A reviews" },
      { kind: "startup_record", id: 401, collection: "term_sheets", title: "Seed Accord" },
      { kind: "startup_record", id: 402, collection: "funding_rounds", title: "Series A" },
      { kind: "startup_record", id: 403, collection: "ip_assets", title: "Patent Delta" },
      { kind: "startup_record", id: 404, collection: "mergers", title: "Northstar merger" },
      { kind: "acceptance_check", id: "efficiency", title: "Efficiency cap" },
      { kind: "acceptance_check", id: "shock_traces", title: "Shock traces" },
      { kind: "shock_trace", id: "demand_shock", title: "demand shock shock trace" },
      { kind: "shock_trace", id: "supply_shock", title: "supply shock shock trace" },
      { kind: "provider_cost", id: "MiniMax-M3", collection: "by_model", title: "MiniMax-M3" },
      { kind: "provider_cost", id: "decision", collection: "by_purpose", title: "decision" },
      { kind: "provider_cost", id: 77, collection: "by_agent", title: "Ada" },
      { kind: "provider_cost", id: "shared-1", collection: "by_agent", title: "Shared" },
    ]);
    assert.strictEqual(calls[0][1], matter);
    assert.strictEqual(calls[1][1], obligation);
    assert.strictEqual(calls[2][1], bill);
    assert.deepEqual(calls.slice(3, 7).map(([, snapshot]) => snapshot), [
      { title: "Term sheets", count: 1, description: "Summary from the current startup lifecycle payload." },
      { title: "Funding rounds", count: 1, description: "Summary from the current startup lifecycle payload." },
      { title: "IP assets", count: 1, description: "Summary from the current startup lifecycle payload." },
      { title: "M&A reviews", count: 1, description: "Summary from the current startup lifecycle payload." },
    ]);
    assert.strictEqual(calls[7][1], termSheet);
    assert.strictEqual(calls[8][1], fundingRound);
    assert.strictEqual(calls[9][1], ipAsset);
    assert.strictEqual(calls[10][1], merger);
    assert.strictEqual(calls[11][1], check);
    assert.strictEqual(calls[12][1], shockCheck);
    assert.deepEqual(calls[13][1], { id: "demand_shock", kind: "demand_shock", ...shockCheck.evidence.demand_shock });
    assert.deepEqual(calls[14][1], { id: "supply_shock", kind: "supply_shock", ...shockCheck.evidence.supply_shock });
    assert.deepEqual(calls.slice(15).map(([, snapshot]) => snapshot), [
      { ...modelCost, id: "MiniMax-M3" },
      { ...purposeCost, id: "decision" },
      { ...agentCost, id: 77 },
      { ...sharedCost, id: "shared-1" },
    ]);
  } finally {
    if (renderer) await rendererAct(async () => { renderer.unmount(); });
    await vite.close();
  }
});

test("extended inspection controls preserve semantic wrappers and responsive shell styles", async () => {
  const vite = await createServer({ appType: "custom", logLevel: "silent", server: { middlewareMode: true } });
  try {
    const { ObservatoryInteractionContext } = await vite.ssrLoadModule("/src/components/ObservatoryInteraction.jsx");
    const { InstitutionalPulse, LegalPoliticalPanels } = await vite.ssrLoadModule("/src/components/V2Observatory.jsx");
    const { AcceptancePanel } = await vite.ssrLoadModule("/src/components/AcceptancePanel.jsx");
    const { CostPanel } = await vite.ssrLoadModule("/src/components/OracleAndCost.jsx");
    const context = { inspect: () => {} };
    const wrap = child => React.createElement(ObservatoryInteractionContext.Provider, { value: context }, child);
    const matter = { id: 1, title: "Matter One", status: "open", matter_type: "dispute", ruleset: "civil" };
    const obligation = { id: 2, obligation_type: "payment_due", status: "open" };
    const bill = { id: 3, title: "Bill Three", origin_chamber: "assembly", status: "draft" };
    const trace = { passed: true, source: { tick: 4 }, downstream: [] };
    const institutional = renderToStaticMarkup(wrap(React.createElement(InstitutionalPulse, {
      legal: { items: [matter] }, politics: { bills: [bill] }, information: {}, datasets: {},
    })));
    const legalPolitical = renderToStaticMarkup(wrap(React.createElement(LegalPoliticalPanels, {
      legal: { contracts: [], obligations: [obligation] }, politics: { bills: [bill], lobbying: { items: [] } },
      information: {}, markets: {}, startups: { term_sheets: [{ id: 4, title: "Term Four", status: "open" }] },
    })));
    const acceptance = renderToStaticMarkup(wrap(React.createElement(AcceptancePanel, { acceptance: {
      configured: true, checks: [
        { id: "shock_traces", label: "Shock traces", passed: true, evidence: { demand_shock: trace } },
      ], progress: {}, orchestration: {},
    } })));
    const cost = renderToStaticMarkup(wrap(React.createElement(CostPanel, {
      cost: {
        by_model: [{ model: "MiniMax-M3", calls: 1 }],
        by_purpose: [{ purpose: "decision", calls: 1 }],
        by_agent: [{ agent_id: 5, agent_name: "Ada", role: "consumer", calls: 1 }],
      }, readiness: { providers: [] },
    })));

    for (const markup of [institutional, legalPolitical, acceptance, cost]) {
      assert.doesNotMatch(markup, /role="button"|tabindex="0"/);
      assertButtonsContainOnlyPhrasingContent(markup);
    }
    assert.match(institutional, /<div\b[^>]*>[\s\S]*aria-label="Inspect legal matter Matter One"/);
    assert.match(legalPolitical, /<div\b[^>]*>[\s\S]*aria-label="Inspect legal obligation 2"/);
    assert.match(legalPolitical, /<div\b[^>]*>[\s\S]*aria-label="Inspect bill Bill Three"/);
    assert.match(acceptance, /<article\b[^>]*>[\s\S]*aria-label="Inspect acceptance check Shock traces"/);
    assert.match(acceptance, /<article\b[^>]*>[\s\S]*aria-label="Inspect demand shock shock trace"/);
    assert.match(acceptance, /<dl\b/);
    assert.doesNotMatch(acceptance, /<article\b[^>]*(?:role="button"|tabindex=)/);
    assert.match(cost, /<div\b[^>]*>[\s\S]*aria-label="Inspect provider model cost MiniMax-M3"/);
    assert.match(cost, /<div\b[^>]*>[\s\S]*aria-label="Inspect provider agent cost Ada"/);

    const { readFile } = await import("node:fs/promises");
    const css = await readFile(new URL("../src/index.css", import.meta.url), "utf8");
    assert.match(css, /\.inspectable-card/);
    assert.match(css, /\.observatory-focus-bar/);
    assert.match(css, /\.observatory-drawer/);
    assert.match(css, /@media \(max-width: 640px\)[\s\S]*\.observatory-drawer/);
    assert.match(css, /prefers-reduced-motion: reduce[\s\S]*\.observatory-drawer/);
  } finally { await vite.close(); }
});
