import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  organizationWorkspaceUrl,
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
import { normalizePoliticsLawWorkspace } from "../src/workspaces/politicsLawWorkspaceModel.js";
import {
  classifyEvidence,
  experimentActionState,
  normalizeExperimentsWorkspace,
} from "../src/workspaces/experimentsWorkspaceModel.js";
import { terminalWorkspaceStatus } from "../src/workspaces/workspacePolling.js";
import { worldOSIndexWorkspace } from "../src/app/worldOSRouting.js";

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
    assert.equal(
      workspaceRouteUrl("run", "world", { fork: null, tick: 0 }, {}),
      "/runs/run/world?tick=0",
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
    assert.equal(
      organizationWorkspaceUrl("run/id", "12", { tick: 0 }),
      "/runs/run%2Fid/organizations/12?tick=0",
    );
    for (const invalid of [0, -1, "1.5", "private", Number.MAX_SAFE_INTEGER + 1]) {
      assert.equal(organizationWorkspaceUrl("run", invalid, {}), null);
    }
});

test("workspace polling stops for every terminal run status", () => {
  for (const status of ["halted", "completed", "failed", "stopped"]) {
    assert.equal(terminalWorkspaceStatus({ status }), true);
    assert.equal(terminalWorkspaceStatus({ summary: { status } }), true);
  }
  assert.equal(terminalWorkspaceStatus({ status: "running" }), false);
});

test("legacy Commons aliases select Commons instead of overview", () => {
  assert.equal(worldOSIndexWorkspace("/commons"), "commons");
  assert.equal(worldOSIndexWorkspace("/commons/feed"), "commons");
  assert.equal(worldOSIndexWorkspace("/runs/run-demo"), "overview");
});

test("Commons feed changes preserve the complete observer query state", () => {
  const source = readFileSync(
    new URL("../src/workspaces/CommonsWorkspace.tsx", import.meta.url), "utf8",
  );
  assert.match(source, /const next = new URLSearchParams\(search\)/);
  assert.match(source, /next\.set\("feed", feed\)/);
  assert.match(source, /setSearch\(next\)/);
  assert.doesNotMatch(source, /setSearch\(\{ feed:/);
  assert.match(source, /useWorkspaceProjection<CommonsProjection>/);
  assert.match(source, /\/api\/v2\/workspaces\/commons\?kind=/);
  assert.doesNotMatch(source, /\/api\/commons/);
  assert.doesNotMatch(source, /useQuery/);
});

test("workspace projection keys and requests include path-specific parameters", () => {
  const source = readFileSync(
    new URL("../src/workspaces/workspaceShared.tsx", import.meta.url), "utf8",
  );
  assert.match(source, /projection, path, observerState\.tick/);
  assert.match(source, /path\.includes\("\?"\) \? "&" : "\?"/);
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

test("legacy organization rows cannot override their authoritative source type", () => {
  const model = normalizeOrganizationsWorkspace({
    firms: [{ id: 1, name: "Firm", type: "bank" }],
    banks: [{ id: 2, name: "Bank", type: "agency" }],
    institutions: { agencies: [{ id: 3, name: "Agency", type: "firm" }] },
  });

  assert.deepEqual(model.organizations.map(row => row.type), ["firm", "bank", "agency"]);
  assert.deepEqual(model.firms.map(row => row.id), [1]);
  assert.deepEqual(model.banks.map(row => row.id), [2]);
  assert.deepEqual(model.agencies.map(row => row.id), [3]);
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

test("politics and law keeps institutional record types and historical states separate", () => {
  const model = normalizePoliticsLawWorkspace({
    politics: { enabled: true, institutional_actions_enabled: false },
    legal: { enabled: true },
    bills: [{ id: 2, introduced_tick: 4, title: "Second", status: "introduced" }, { id: null, introduced_tick: 1, title: "Missing identity", status: "introduced" }, { id: 1, introduced_tick: 2, title: "First", status: "enacted" }],
    bill_versions: [{ id: 3, bill_id: 1, version: 1, tick: 2, summary: "Public" }],
    votes: [{ id: 4, bill_id: 1, tick: 3, vote: "yes", stage: "floor" }],
    rules: [{ id: 5, bill_id: 1, rule_key: "tax_rate", enacted_tick: 3, effective_tick: 4, status: "active" }],
    lobbying: [{ id: 6, tick: 3, bill_id: 1, position: "support", disclosed: 0, disclosure_tick: null, amount_cents: 100 }],
    contracts: [{ id: 7, title: "Supply", offered_tick: 2, status: "executed" }],
    obligations: [{ id: 8, contract_id: 7, obligation_type: "pay", due_tick: 6, amount_cents: 200, currency_code: "USD", status: "pending" }],
    matters: [{ id: 9, matter_type: "civil", filed_tick: 3, claim_type: "breach", status: "filed" }],
    mergers: [{ id: 10, proposed_tick: 3, status: "under_review", price_cents: 500, currency_code: "USD" }],
    merger_reviews: [{ id: 11, merger_id: 10, tick: 4, outcome: "review" }],
  });
  assert.deepEqual(model.configuration, { politicsEnabled: true, institutionalActionsEnabled: false, legalEnabled: true });
  assert.deepEqual(model.bills.map(row => row.id), [1, 2]);
  assert.equal(model.lobbying[0].disclosure_state, "undisclosed");
  assert.equal(model.contracts[0].title, "Supply");
  assert.equal(model.obligations[0].obligation_type, "pay");
  assert.equal(model.matters[0].status, "filed");
  assert.equal(model.mergers[0].status, "under_review");
  assert.equal(model.mergerReviews[0].merger_id, 10);
  assert.notStrictEqual(model.contracts, model.obligations);
});

test("politics and law model hides retained rows for disabled institutions", () => {
  const model = normalizePoliticsLawWorkspace({
    politics: { enabled: false }, legal: { enabled: false },
    bills: [{ id: 1, title: "retained politics canary" }],
    matters: [{ id: 2, claim_type: "retained legal canary" }],
  });
  assert.equal(model.configuration.politicsEnabled, false);
  assert.equal(model.configuration.legalEnabled, false);
  for (const key of ["bills", "votes", "rules", "lobbying", "contracts", "obligations", "matters", "mergers", "mergerReviews"]) {
    assert.deepEqual(model[key], []);
  }
});

test("World OS maps Politics and Law to the canonical workspace", () => {
  const source = readFileSync(new URL("../src/app/WorldOSApp.tsx", import.meta.url), "utf8");
  const workspace = readFileSync(new URL("../src/workspaces/PoliticsLawWorkspace.tsx", import.meta.url), "utf8");
  assert.match(source, /import \{ PoliticsLawWorkspace \}/);
  assert.match(source, /path="politics-law" element=\{<PoliticsLawWorkspace \/>\}/);
  assert.doesNotMatch(source, /LegacyWorkspace title="Politics & Law"/);
  assert.match(workspace, /row\.disclosure_state/);
  assert.doesNotMatch(workspace, /row\.disclosureState/);
});

test("experiment evidence classification fails closed across release gates", () => {
  assert.equal(classifyEvidence({ passed: true, real_providers: false }), "mechanics-only");
  assert.equal(classifyEvidence({ status: "running" }), "partial");
  assert.equal(classifyEvidence({ passed: true, exact_replay: true, eligible: true }), "eligible");
  assert.equal(classifyEvidence({ blocked: true }), "blocked");
  assert.equal(classifyEvidence({ passed: false }), "failed");
  assert.equal(classifyEvidence({ status: "not_run" }), "not-run");
  assert.equal(classifyEvidence({ passed: true, external_agent_contamination: true }), "blocked");
  assert.equal(classifyEvidence({ passed: true, participant_influence: true }), "blocked");
  assert.equal(classifyEvidence({ passed: true, stale_commit: true }), "blocked");
  assert.equal(classifyEvidence({ passed: true, dirty_tree: true }), "blocked");
  assert.equal(classifyEvidence({ passed: true, missing_artifacts: ["receipt.json"] }), "blocked");
  assert.equal(classifyEvidence({ passed: true, real_providers: true }), "live-evidence");
});

test("experiment workspace separates artifact families and omits private provider material", () => {
  const model = normalizeExperimentsWorkspace({
    run: { run_id: "run", parent_run_id: "parent", fork_tick: 3, status: "paused" },
    checkpoints: [{ id: 1, tick: 3, created_at: "now", path: "/private/path" }],
    shocks: [{ id: 2, kind: "oil", label: "Oil shock", fired: 1, fired_tick: 3, params: { api_key: "secret" } }],
    predictions: [{ id: 3, asked_tick: 2, question: "Growth?", status: "open", p: 0.6 }],
    acceptance: [{ id: 4, scheduled_tick: 3, question: "Replay?", status: "passed", passed: true, exact_replay: true, eligible: true }],
    datasets: [{ id: 5, dataset_key: "public", status: "ready", metadata: { token: "secret" } }],
    scenarios: [{ id: 6, scenario_key: "base", title: "Base" }],
    experiments: [{ id: 7, experiment_key: "exp", status: "complete", private_prompt: "drop" }],
    results: [{ id: 8, experiment_id: 7, arm: "control", seed: 1, run_id: "child", replay_hash: "abc", metrics: { score: 1 } }],
  });
  assert.equal(model.acceptance[0].classification, "eligible");
  assert.equal(model.checkpoints[0].path, undefined);
  assert.equal(model.shocks[0].params, undefined);
  assert.equal(model.datasets[0].metadata, undefined);
  assert.equal(model.experiments[0].private_prompt, undefined);
  assert.equal(model.results[0].experiment_id, 7);
});

test("experiment action state requires a paused live observer boundary", () => {
  assert.deepEqual(experimentActionState({ status: "paused" }, "live"), { canPrepareFork: true, canPrepareShock: true, reason: null });
  assert.equal(experimentActionState({ status: "running" }, "live").canPrepareFork, false);
  assert.equal(experimentActionState({ status: "paused" }, "4").canPrepareShock, false);
});

test("World OS maps experiment routes canonically and has no legacy placeholders", () => {
  const source = readFileSync(new URL("../src/app/WorldOSApp.tsx", import.meta.url), "utf8");
  assert.match(source, /import \{ ExperimentsWorkspace \}/);
  assert.match(source, /path="experiments" element=\{<ExperimentsWorkspace \/>\}/);
  assert.match(source, /path="experiments\/:experimentId" element=\{<ExperimentsWorkspace \/>\}/);
  assert.doesNotMatch(source, /LegacyWorkspace|Canonical route established/);
});
