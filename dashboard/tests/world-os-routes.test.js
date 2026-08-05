import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  normalizeWorkspaceFilters,
  validatedSelectedId,
  workspaceRouteUrl,
} from "../src/workspaces/workspaceRouteState.js";
import { normalizeWorldWorkspace } from "../src/workspaces/worldWorkspaceModel.js";
import {
  filterOrganizations,
  normalizeOrganizationsWorkspace,
} from "../src/workspaces/organizationsWorkspaceModel.js";
import {
  filterMarketRows,
  normalizeMarketsWorkspace,
} from "../src/workspaces/marketsWorkspaceModel.js";

test("workspace URLs preserve only validated observer and route state", () => {
    assert.equal(
      workspaceRouteUrl(
        "run/id", "markets", { fork: "fork-1", tick: "7" }, { side: "buy" },
      ),
      "/runs/run%2Fid/markets?fork=fork-1&tick=7&side=buy",
    );
    assert.equal(
      workspaceRouteUrl("run", "world", { fork: null, tick: "live" }, {}),
      "/runs/run/world",
    );
    assert.deepEqual(
      normalizeWorkspaceFilters(
        { side: "buy", selected: "12", future_canary: "private" },
        ["side", "selected"],
      ),
      { side: "buy", selected: "12" },
    );
    assert.equal(validatedSelectedId("12"), 12);
    assert.equal(validatedSelectedId("0"), null);
    assert.equal(validatedSelectedId("1.5"), null);
    assert.equal(validatedSelectedId("private"), null);
});

test("world workspace normalizes public map data without inventing coordinates", () => {
  const normalized = normalizeWorldWorkspace({
    enabled: false,
    regions: [
      { id: 2, name: "North", currency_code: "CAD", x: "not-a-coordinate", y: 0.7 },
      { id: 1, name: "South", currency_code: "USD", x: 0.2, y: 0.3 },
    ],
    agents: [
      { id: 2, name: "Unknown", region_id: 99, x: Infinity, y: 0 },
      { id: 1, name: "Known", region_id: 1 },
    ],
    organizations: [
      { id: 3, name: "Closed", region_id: 1, active: false },
      { id: 2, name: "Open", region_id: 1, active: true },
    ],
    places: [
      { id: 4, name: "Square", region_id: 1, x: 0.5, y: 0.5 },
      { id: 3, name: "Archives", region_id: 1, x: Number.NaN, y: 0.4 },
    ],
    presence: [{ id: 8, agent_id: 1, place_id: 4 }],
    flows: [
      { id: 9, kind: "migration", origin_region_id: 1, destination_region_id: 2 },
      { id: 9, kind: "migration", origin_region_id: 1, destination_region_id: 2 },
      { id: 10, kind: "trade", origin_region_id: 1, destination_region_id: 999 },
      { id: 11, kind: "trade", origin_region_id: 2, destination_region_id: 1 },
    ],
    currentTelemetry: { capacity: 999 },
  });

  assert.equal(normalized.enabled, false);
  assert.deepEqual(normalized.regions.map(region => region.id), [1, 2]);
  assert.deepEqual(normalized.places.map(place => place.id), [3, 4]);
  assert.equal(normalized.regions[1].x, undefined);
  assert.equal(normalized.places[0].x, undefined);
  assert.equal(normalized.agents[1].x, undefined);
  assert.deepEqual(normalized.flows.map(flow => `${flow.kind}:${flow.id}`), ["migration:9", "trade:11"]);
  assert.deepEqual(normalized.summary, {
    population: 2,
    activeOrganizations: 1,
    currencies: ["CAD", "USD"],
    migrationCount: 1,
    tradeCount: 1,
  });
  assert.equal("currentTelemetry" in normalized, false);
});

test("world workspace has stable empty and historical normalization", () => {
  assert.deepEqual(normalizeWorldWorkspace({}), {
    enabled: false,
    regions: [],
    agents: [],
    organizations: [],
    places: [],
    presence: [],
    flows: [],
    summary: {
      population: 0,
      activeOrganizations: 0,
      currencies: [],
      migrationCount: 0,
      tradeCount: 0,
    },
  });
  const historical = normalizeWorldWorkspace({
    enabled: true,
    as_of_tick: 4,
    regions: [{ id: 1, name: "Only", currency_code: "USD" }],
    current_runtime: { queue_depth: 7 },
  });
  assert.equal(historical.enabled, true);
  assert.equal("current_runtime" in historical, false);
  assert.equal("as_of_tick" in historical, false);
});

test("World OS maps the World route to its canonical workspace", () => {
  const source = readFileSync(new URL("../src/app/WorldOSApp.tsx", import.meta.url), "utf8");
  assert.match(source, /import \{ WorldWorkspace \}/);
  assert.match(source, /path="world" element=\{<WorldWorkspace \/>\}/);
  assert.doesNotMatch(source, /path="world" element=\{<LegacyWorkspace/);
});

test("organization workspace preserves public lifecycle and currency while dropping private ownership", () => {
  const model = normalizeOrganizationsWorkspace({
    organizations: [
      { id: 3, type: "agency", name: "Civic Office", status: "active", active: true, mandate: "permits" },
      { id: 1, type: "firm", name: "North Foods", sector: "food", region_id: 2, region_name: "North", status: "listed", active: true, employees: 4, balance_cents: 1200, currency_code: "CAD", private_owner: "canary", owner_id: 99 },
      { id: 2, type: "bank", name: "South Bank", region_name: "South", status: "failed", active: false, reserve_cents: 500, equity_cents: -10, currency_code: "USD", tenant_id: "other-run" },
      { id: 4, type: "cooperative", name: "Open Guild", status: "custom_state", active: true },
    ],
    institutions: { legal_enabled: false, politics_enabled: true, agencies: [] },
    contracts: [{ id: 8, title: "Public charter", offered_tick: 2, status: "executed", metadata: { private_note: "drop" } }],
    disclosures: [{ id: 9, tick: 4, firm_id: 1, disclosure_type: "earnings", facts: { revenue_cents: 100 } }],
  });

  assert.deepEqual(model.organizations.map(item => item.id), [1, 2, 3, 4]);
  assert.equal(model.organizations[0].currency_code, "CAD");
  assert.equal(model.organizations[0].balance_cents, 1200);
  assert.equal("private_owner" in model.organizations[0], false);
  assert.equal("owner_id" in model.organizations[0], false);
  assert.equal("tenant_id" in model.organizations[1], false);
  assert.deepEqual(model.institutions, { legalEnabled: false, politicsEnabled: true });
  assert.equal(model.contracts[0].metadata, undefined);
  assert.equal(model.disclosures[0].tick, 4);
});

test("organization filters are deterministic across search, type, region, sector, status, and active state", () => {
  const organizations = normalizeOrganizationsWorkspace({ organizations: [
    { id: 3, type: "firm", name: "Dormant Foods", sector: "food", region_name: "North", status: "bankrupt", active: false },
    { id: 2, type: "firm", name: "Active Foods", sector: "food", region_name: "North", status: "listed", active: true },
    { id: 1, type: "bank", name: "Active Bank", region_name: "South", status: "open", active: true },
  ] }).organizations;
  assert.deepEqual(filterOrganizations(organizations, { q: "active", activeOnly: true }).map(item => item.id), [1, 2]);
  assert.deepEqual(filterOrganizations(organizations, { type: "firm", sector: "food", region: "North", status: "listed" }).map(item => item.id), [2]);
  assert.deepEqual(filterOrganizations(organizations, { type: "missing" }), []);
});

test("World OS maps organization list and detail routes to the canonical workspace", () => {
  const source = readFileSync(new URL("../src/app/WorldOSApp.tsx", import.meta.url), "utf8");
  assert.match(source, /import \{ OrganizationsWorkspace \}/);
  assert.match(source, /path="organizations" element=\{<OrganizationsWorkspace \/>\}/);
  assert.match(source, /path="organizations\/:organizationId" element=\{<OrganizationsWorkspace \/>\}/);
  assert.doesNotMatch(source, /LegacyWorkspace title="Organizations"/);
});

test("market workspace keeps books, executions, FX direction, and units distinct", () => {
  const model = normalizeMarketsWorkspace({
    orders: [
      { id: 2, tick: 4, firm_id: 8, side: "sell", qty: 5, qty_remaining: 5, limit_price_cents: 250, status: "open" },
      { id: 1, tick: 3, firm_id: 8, side: "buy", qty: 3, qty_remaining: 0, limit_price_cents: 125, status: "filled" },
    ],
    trades: [
      { id: 2, tick: 4, firm_id: 8, qty: Infinity, price_cents: 250 },
      { id: 1, tick: 3, firm_id: 8, qty: 3, price_cents: 125 },
    ],
    fx_orders: [{ id: 4, tick: 4, pair: "USD/CAD", base_currency: "USD", quote_currency: "CAD", side: "buy", qty: 10, qty_remaining: 4, limit_rate_ppm: 1350000, status: "partial" }],
    fx_trades: [{ id: 5, tick: 4, pair: "USD/CAD", side: "buy", base_qty: 6, quote_qty: 8, rate_ppm: 1333333 }],
    circuit_breakers: [{ id: 9, tick: 4, kind: "market_circuit_breaker", importance: 3 }],
    currencies: [{ code: "CAD", name: "Canadian dollar", minor_unit: 2 }, { code: "USD", name: "Dollar", minor_unit: 2 }],
  });
  assert.deepEqual(model.orders.map(row => row.id), [1, 2]);
  assert.deepEqual(model.trades.map(row => row.id), [1, 2]);
  assert.equal(model.trades[1].qty, undefined);
  assert.equal(model.fxTrades[0].baseCurrency, "USD");
  assert.equal(model.fxTrades[0].quoteCurrency, "CAD");
  assert.equal(model.fxTrades[0].rate_ppm, 1333333);
  assert.equal(model.circuitBreakers[0].kind, "market_circuit_breaker");
  assert.deepEqual(model.totals, { tradeCount: 2, tradeVolume: 3, fxTradeCount: 1 });
  assert.deepEqual(filterMarketRows(model.orders, { side: "buy", status: "filled" }).map(row => row.id), [1]);
});

test("empty market books are empty evidence, not measured zero activity", () => {
  const model = normalizeMarketsWorkspace({});
  assert.deepEqual(model.orders, []);
  assert.deepEqual(model.trades, []);
  assert.deepEqual(model.fxOrders, []);
  assert.deepEqual(model.fxTrades, []);
  assert.deepEqual(model.totals, { tradeCount: 0, tradeVolume: null, fxTradeCount: 0 });
});

test("World OS maps Markets to the canonical workspace", () => {
  const source = readFileSync(new URL("../src/app/WorldOSApp.tsx", import.meta.url), "utf8");
  assert.match(source, /import \{ MarketsWorkspace \}/);
  assert.match(source, /path="markets" element=\{<MarketsWorkspace \/>\}/);
  assert.doesNotMatch(source, /LegacyWorkspace title="Markets"/);
});
