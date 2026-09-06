import { expect, test, type Page } from "@playwright/test";

const PRIVATE_CANARY = "PRIVATE-WORKSPACE-CANARY";
const FUTURE_CANARY = "FUTURE-WORKSPACE-CANARY";
const baseEnvelope = {
  run_id: "run-demo", fork_id: null, tick: 6, semantics_version: 12,
  projection_version: 1, policy_version: 1, view_key: "view-workspaces",
  snapshot_version: "s12-p1-t6-workspaces", event_cursor: 4,
};

async function installSocket(page: Page) {
  await page.addInitScript(() => {
    class WorkspaceSocket extends EventTarget {
      static OPEN = 1;
      static CLOSED = 3;
      readyState = WorkspaceSocket.OPEN;
      constructor(_url: string) {
        super();
        queueMicrotask(() => {
          this.dispatchEvent(new Event("open"));
          this.dispatchEvent(new MessageEvent("message", { data: JSON.stringify({
            type: "hello", run_id: "run-demo", fork_id: null, tick: 6,
            semantics_version: 12, projection_version: 1, policy_version: 1,
            view_key: "view-workspaces", event_cursor: 4, status: "paused",
          }) }));
        });
      }
      send(_value: string) {}
      close() { this.readyState = WorkspaceSocket.CLOSED; }
    }
    Object.defineProperty(window, "WebSocket", { value: WorkspaceSocket });
  });
}

function envelope(path: string, url: URL, data: unknown, projection = `workspace.${path}`) {
  const historical = url.searchParams.get("tick") === "3";
  return {
    ...baseEnvelope,
    tick: historical ? 3 : 6,
    fork_id: url.searchParams.get("fork_id"),
    projection,
    snapshot_version: `s12-p1-t${historical ? 3 : 6}-workspaces`,
    data,
  };
}

function priceLabData(url: URL) {
  const tick = url.searchParams.get("tick") === "3" ? 3 : 6;
  const firm = Number(url.searchParams.get("firm_id") || 1);
  const firms = [{ id: 1, name: "Northstar Foods", sector: "food", currency_code: "CAD" },
    { id: 2, name: "City Tools", sector: "manufacturing", currency_code: "CAD" }];
  const observation = (value: number | null, evidence: Array<{ type: string; id: number }> = []) => ({
    value, reason: value === null ? "no_execution" : null, evidence, observed_tick: value === null ? null : 3,
    age_ticks: value === null ? null : tick - 3,
  });
  const goods = firm === 1 ? 200 : 300;
  return { contract: "price-lab-projection-v1", firms, firms_truncated: false,
    selected_firm: firms[firm - 1], tick, start_tick: 0, window_ticks: Number(url.searchParams.get("window") || 30),
    observation: { firm_id: firm, tick, start_tick: 0, currency: "CAD", limitations: ["Within-firm comparable product units."],
      goods: { posted_price: observation(goods + 10), executed_price: observation(goods, [{ type: "event", id: 9 }]),
        last_execution: observation(goods), quantity: 4, sale_count: 1, demand: { reason: "intended_and_unmet_demand_not_recorded" } },
      equities: { last_execution: observation(null), executed_price: observation(null), quantity: 0, trade_count: 0,
        excluded_self_trade_ids: [], book: { status: "unavailable", reason: "historical_book_state_not_recorded",
          best_bid_cents: null, best_ask_cents: null, spread_cents: null, bid_quantity: null, ask_quantity: null } },
      series: { points: [{ tick: 2, goods_vwap: null, goods_volume: 0, goods_reason: "no_execution", equity_vwap: null, equity_volume: 0 },
        { tick: 3, goods_vwap: goods, goods_volume: 4, goods_reason: null, equity_vwap: null, equity_volume: 0 }] },
    } };
}

async function mockWorkspaceApis(
  page: Page,
  servedBodies: string[] = [],
  servedHistoricalBodies: string[] = [],
) {
  await page.route("**/api/v2/**", async route => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const historical = url.searchParams.get("tick") === "3";
    if (path === "/api/v2/operator/session") {
      return route.fulfill({ json: { owner_id: "local-operator", csrf_token: "test" } });
    }
    if (path === "/api/v2/operator/investigations" && request.method() === "GET") {
      return route.fulfill({ json: { items: [] } });
    }
    let body: unknown;
    if (path === "/api/v2/mode") {
      body = { hosted: false, mode: "local" };
    } else if (path === "/api/v2/workspaces/commons") {
      body = envelope("commons", url, {
        version: "ae.commons.public.v1", tick: historical ? 3 : 6,
        feed: {
          feed_kind: url.searchParams.get("kind") || "chronological",
          candidate_set_hash: "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
          policy: { id: 1, key: "public-hot", version: 1, algorithm: "hot" },
          entries: [{
            id: 1, body: "Bounded historical commons post", author_agent_id: 1,
            author_name: "Supplier Officer", author_connected_status: null,
            community_name: null, created_tick: 3, reaction_count: 0, reply_count: 0,
            moderation_label: null, position: 1,
            causal_observatory: { source_kind: "commons_entry", source_id: 1 },
          }],
        },
        communities: [], profiles: [], moderation: { action_count: 0, open_appeals: 0 },
      });
    } else if (path === "/api/v2/workspaces/world") {
      body = envelope("world", url, {
        enabled: true,
        regions: [
          { id: 1, name: "North", currency_code: "CAD", population_target: 2, x: 0.2, y: 0.3, legal_ruleset: "north-rules" },
          { id: 2, name: "South", currency_code: "USD", population_target: 1, x: 0.7, y: 0.6, legal_ruleset: "south-rules" },
        ],
        agents: [{ id: 1, name: "Supplier Officer", role: "supplier_officer", occupation: "trader", region_id: 1 }],
        organizations: [{
          id: 1, name: "Northstar Foods", sector: "food", status: "listed",
          active: true, region_id: 1,
          ...(historical ? {} : { owner_id: PRIVATE_CANARY }),
        }],
        places: [{ id: 1, name: "North Exchange", kind: "market", region_id: 1, region_name: "North", x: 0.3, y: 0.4, capacity: 20 }],
        presence: [{ id: 1, tick: historical ? 3 : 6, agent_id: 1, place_id: 1 }],
        flows: [{ id: 1, kind: "trade", origin_region_id: 1, destination_region_id: 2, tick: 3 }],
      });
    } else if (path === "/api/v2/workspaces/organizations") {
      body = envelope("organizations", url, {
        organizations: [
          { id: 1, type: "firm", name: "Northstar Foods", sector: "food", region_id: 1, region_name: "North", status: "listed", active: true, employees: 2, balance_cents: 1200, currency_code: "CAD", founded_tick: 1, ...(historical ? {} : { owner_id: PRIVATE_CANARY }) },
          { id: 1, type: "agency", name: "Northstar Markets Commission", status: "active", active: true, mandate: "markets" },
          { id: 2, type: "bank", name: "Civic Bank", status: "open", active: true, reserve_cents: 900, equity_cents: 300, currency_code: "USD" },
        ],
        institutions: { legal_enabled: !historical, politics_enabled: !historical, agencies: [] },
        contracts: [{ id: 1, title: "Public charter", contract_type: "charter", jurisdiction: "North", offered_tick: 2, status: "executed" }],
        disclosures: [{ id: 1, tick: 3, firm_id: 1, disclosure_type: "earnings", facts: { revenue_cents: 100 } }],
      });
    } else if (path === "/api/v2/workspaces/price-lab") {
      body = envelope("price_lab", url, priceLabData(url));
    } else if (path === "/api/v2/workspaces/markets") {
      body = envelope("markets", url, historical ? {
        orders: [], trades: [], fx_orders: [], fx_trades: [], circuit_breakers: [], currencies: [],
      } : {
        orders: [{ id: 1, tick: 6, firm_id: 1, side: "buy", qty: 3, qty_remaining: 3, limit_price_cents: 125, status: "open" }],
        trades: [{ id: 1, tick: 6, firm_id: 1, firm_name: "Northstar Foods", qty: 2, price_cents: 120 }],
        fx_orders: [{ id: 2, tick: 6, pair: "USD/CAD", base_currency: "USD", quote_currency: "CAD", side: "buy", qty: 4, qty_remaining: 4, limit_rate_ppm: 1300000, status: "open" }],
        fx_trades: [{ id: 3, tick: 6, pair: "USD/CAD", side: "buy", base_qty: 2, quote_qty: 3, rate_ppm: 1500000 }],
        circuit_breakers: [{ id: 9, tick: 6, kind: "market_circuit_breaker", importance: 3 }],
        currencies: [{ code: "CAD", name: "Canadian dollar", minor_unit: 2 }, { code: "USD", name: "Dollar", minor_unit: 2 }],
      });
    } else if (path === "/api/v2/workspaces/politics-law") {
      body = envelope("politics-law", url, historical ? {
        politics: { enabled: false, institutional_actions_enabled: false }, legal: { enabled: false },
        bills: [{ id: 99, title: "retained disabled canary" }], matters: [{ id: 99, claim_type: "retained disabled canary" }],
      } : {
        politics: { enabled: true, institutional_actions_enabled: true }, legal: { enabled: true },
        bills: [{ id: 1, title: "Market Safety Act", origin_chamber: "assembly", introduced_tick: 2, status: "enacted", current_version: 1 }],
        votes: [{ id: 1, bill_id: 1, version: 1, legislator_id: 1, stage: "floor", vote: "yes", tick: 3 }],
        rules: [{ id: 1, bill_id: 1, rule_key: "market_safety", enacted_tick: 3, effective_tick: 4, status: "active" }],
        lobbying: [], contracts: [], obligations: [], matters: [], mergers: [], merger_reviews: [], bill_versions: [],
      });
    } else if (path === "/api/v2/workspaces/experiments") {
      body = envelope("experiments", url, {
        run: { run_id: "run-demo", parent_run_id: null, fork_tick: null, status: "paused" },
        checkpoints: [{ id: 1, tick: 3, created_at: "2026-08-05", ...(historical ? {} : { path: PRIVATE_CANARY }) }],
        shocks: historical ? [] : [{ id: 1, kind: "test", params: { private: PRIVATE_CANARY, future: FUTURE_CANARY } }],
        predictions: [],
        acceptance: [{ id: 1, scheduled_tick: 3, question: "Replay integrity", status: "passed", detail: "Exact replay receipt stored" }],
        datasets: [{ id: 1, dataset_key: "macro-public", vintage_date: "2026-07", status: "ready" }],
        scenarios: [{ id: 1, scenario_key: "baseline", version: "1", title: "Baseline" }],
        experiments: historical ? [] : [{ id: 1, experiment_key: "price-shock", scenario_key: "baseline", status: "complete", checkpoint_hash: "abc" }],
        results: historical ? [] : [{ id: 1, experiment_id: 1, arm: "control", seed: 7, run_id: "child", replay_hash: "def", metrics: { output: 1 } }],
        current_only_artifacts_omitted: historical,
      });
    } else if (path === "/api/v2/snapshot") {
      body = envelope("snapshot", url, {
        summary: { status: "paused", phase: "FINALIZE", active_tick: null, agents_alive: 1, active_firms: 1, ledger_balance: 0 },
        communications: { total: 0, published: 0, private_total: 0 }, alerts: [], events: { items: [] },
      }, "world.snapshot");
    } else if (path === "/api/v2/world-map") {
      body = envelope("map", url, {
        regions: [], agents: [], organizations: [],
        places: [{
          id: 1, name: "North Exchange", kind: "market", region_id: 1,
          region_name: "North", x: 0.3, y: 0.4, capacity: 20,
        }],
        presence: [],
      }, "world.map");
    } else if (path === "/api/v2/civic/summary") {
      body = envelope("civic", url, {
        enabled: false, tick: historical ? 3 : 6,
        queue: { depth: 0, oldest_age_ticks: 0 }, offices: [],
      }, "civic.summary");
    } else if (path === "/api/v2/events") {
      body = envelope("events", url, {
        items: [], next_after_id: null, truncated: false,
      }, "events.page");
    } else if (path.startsWith("/api/v2/causal/")) {
      const root = {
        kind: "commons_entry", id: "1", tick: historical ? 3 : 6,
        order_key: "commons-entry-1",
      };
      body = envelope("causal", url, {
        root, truncated: false, cycles: [], nodes: [root], edges: [],
        semantic_rows: [{
          stable_ref: root, kind: "commons_entry", id: 1,
          tick: historical ? 3 : 6, label: "Bounded historical commons post",
        }],
      }, "causal.neighborhood");
    } else if (path === "/api/v2/search") {
      body = envelope("search", url, { groups: [
        { kind: "agent", items: [], truncated: false }, { kind: "firm", items: [], truncated: false },
        { kind: "event", items: [], truncated: false }, { kind: "communication_thread", items: [], truncated: false },
      ] }, "search.results");
    } else {
      return route.fulfill({ status: 404, json: { detail: "not mocked" } });
    }
    const serialized = JSON.stringify(body);
    servedBodies.push(serialized);
    if (historical) {
      servedHistoricalBodies.push(serialized);
    }
    return route.fulfill({ contentType: "application/json", body: serialized });
  });
  await page.route("**/api/agents", route => route.fulfill({ json: [] }));
  await page.route("**/api/firms", route => route.fulfill({ json: [] }));
  await page.route("**/api/run/status", route => route.fulfill({ json: {
    status: "paused", running: false,
  } }));
  await page.route("**/api/llm/runtime", route => route.fulfill({ json: {
    live_only: true, global: { capacity: 1, in_flight: 0, queue_depth: 0, peak_in_flight: 0, peak_queue_depth: 0, logical_deadline_s: 90 },
    simulated_days: { samples: 0, p50_wall_ms: null, p95_wall_ms: null }, providers: [],
  } }));
}

async function setup(page: Page) {
  const consoleErrors: string[] = [];
  const requestFailures: string[] = [];
  page.on("console", message => { if (message.type() === "error") consoleErrors.push(message.text()); });
  page.on("pageerror", error => consoleErrors.push(error.message));
  page.on("requestfailed", request => {
    if (request.failure()?.errorText !== "net::ERR_ABORTED") {
      requestFailures.push(`${request.method()} ${request.url()} ${request.failure()?.errorText || "failed"}`);
    }
  });
  await installSocket(page);
  const bodies: string[] = [];
  const historicalBodies: string[] = [];
  await mockWorkspaceApis(page, bodies, historicalBodies);
  return { consoleErrors, requestFailures, bodies, historicalBodies };
}

test("workspace rail exposes every canonical destination with observer context", async ({ page }) => {
  const diagnostics = await setup(page);
  await page.goto("/runs/run-demo/overview?fork=fork-1&tick=3");

  const navigation = page.getByRole("navigation", { name: "Civic Atlas workspaces" });
  const destinations = [
    ["Pulse", "overview"],
    ["City", "live-city"],
    ["People", "people"],
    ["Commons", "commons"],
    ["Evidence Lab", "investigations"],
    ["City evidence", "world"],
    ["Institutions", "organizations"],
    ["Markets", "markets"],
    ["Politics & Law", "politics-law"],
    ["Communications", "news-communications"],
    ["Experiments", "experiments"],
  ] as const;

  await expect(navigation).toBeVisible();
  for (const [label, path] of destinations) {
    const link = navigation.getByRole("link", { name: label, exact: true });
    await expect(link).toBeAttached();
    await expect(link).toHaveAttribute(
      "href",
      `/runs/run-demo/${path}?fork=fork-1&tick=3`,
    );
  }

  await navigation.getByRole("link", { name: "Institutions", exact: true }).click();
  await expect(page).toHaveURL(/\/runs\/run-demo\/organizations\?fork=fork-1&tick=3$/);
  await expect(page.getByRole("heading", { name: "Organizations", exact: true }).last()).toBeVisible();
  expect(diagnostics.consoleErrors).toEqual([]);
  expect(diagnostics.requestFailures).toEqual([]);
});

test("all canonical workspace routes navigate with observer context and validated details", async ({ page }) => {
  const diagnostics = await setup(page);
  await page.goto("/runs/run-demo/world?fork=fork-1&tick=3");
  await expect(page.getByRole("heading", { name: "City evidence", exact: true })).toBeVisible();
  await expect(page.getByText("Historical tick 3", { exact: true }).first()).toBeVisible();

  for (const [routeName, heading] of [
    ["Institutions", "Organizations"], ["Markets", "Markets"],
    ["Politics & Law", "Politics & Law"], ["Experiments", "Experiments"],
  ] as const) {
    await page.keyboard.press("Control+K");
    const command = page.getByRole("dialog", { name: "Navigate and inspect" });
    await command.getByPlaceholder("Search routes, people, firms, events…").fill(routeName);
    await command.getByRole("option", { name: new RegExp(`^${routeName}`) }).click();
    await expect(page.getByRole("heading", { name: heading, exact: true }).last()).toBeVisible();
    await expect(page).toHaveURL(/fork=fork-1/);
    await expect(page).toHaveURL(/tick=3/);
  }

  await page.goto("/runs/run-demo/organizations/1?fork=fork-1&tick=3");
  await expect(page.getByText("This legacy ID matches multiple organization types. Choose a typed directory row.")).toBeVisible();
  await page.getByRole("link", { name: "Northstar Foods", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Northstar Foods" })).toBeVisible();
  await expect(page).toHaveURL(/organizations\/firm\/1\?fork=fork-1&tick=3/);
  await page.goto("/runs/run-demo/experiments/1?fork=fork-1");
  await page.getByRole("button", { name: "campaigns", exact: true }).click();
  await expect(page.getByRole("heading", { name: "price-shock" })).toBeVisible();
  await expect(page).toHaveURL(/experiments\/1\?fork=fork-1&view=campaigns/);

  expect(diagnostics.historicalBodies.length).toBeGreaterThan(0);
  const experimentBodies = diagnostics.bodies.filter(
    body => body.includes('"projection":"workspace.experiments"'),
  );
  expect(experimentBodies.join("\n")).toContain(PRIVATE_CANARY);
  expect(experimentBodies.join("\n")).toContain(FUTURE_CANARY);
  expect(diagnostics.historicalBodies.join("\n")).not.toContain(PRIVATE_CANARY);
  expect(diagnostics.historicalBodies.join("\n")).not.toContain(FUTURE_CANARY);
  await expect(page.locator("body")).not.toContainText(PRIVATE_CANARY);
  await expect(page.locator("body")).not.toContainText(FUTURE_CANARY);
  expect(diagnostics.consoleErrors).toEqual([]);
  expect(diagnostics.requestFailures).toEqual([]);
});

test("deep-dive menus expose every view and participate in browser history", async ({ page }) => {
  const diagnostics = await setup(page);

  await page.goto("/runs/run-demo/markets?fork=fork-1&tick=3");
  const marketMenu = page.getByRole("group", { name: "Market evidence view" });
  const orders = marketMenu.getByRole("button", { name: "orders", exact: true });
  const trades = marketMenu.getByRole("button", { name: "trades", exact: true });
  const fx = marketMenu.getByRole("button", { name: "fx", exact: true });
  const circuits = marketMenu.getByRole("button", { name: "Circuit breakers", exact: true });
  await expect(orders).toHaveAttribute("aria-pressed", "true");
  await trades.click();
  await expect(page.getByRole("heading", { name: "Trades", exact: true })).toBeVisible();
  await expect.poll(() => new URL(page.url()).searchParams.get("view")).toBe("trades");
  await page.reload();
  await expect(trades).toHaveAttribute("aria-pressed", "true");
  await fx.click();
  await expect(page.getByRole("heading", { name: "FX orders", exact: true })).toBeVisible();
  await page.getByLabel("Side").selectOption("buy");
  await page.getByLabel("Status").selectOption("open");
  await expect.poll(() => new URL(page.url()).searchParams.get("side")).toBe("buy");
  await page.goBack();
  await expect(trades).toHaveAttribute("aria-pressed", "true");
  await circuits.click();
  await expect(page.getByRole("heading", { name: "Circuit breakers", exact: true })).toBeVisible();
  await orders.click();
  await expect.poll(() => new URL(page.url()).searchParams.has("view")).toBe(false);

  await page.goto("/runs/run-demo/politics-law?fork=fork-1&tick=3");
  const institutionalMenu = page.getByRole("group", { name: "Institutional evidence view" });
  for (const [buttonName, view, heading] of [
    ["lobbying", "lobbying", "Lobbying"],
    ["legal", "legal", "Contracts"],
    ["M&A", "mergers", "Mergers & acquisitions"],
    ["legislation", null, "Bills"],
  ] as const) {
    const button = institutionalMenu.getByRole("button", { name: buttonName, exact: true });
    await button.click();
    await expect(button).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByRole("heading", { name: heading, exact: true, level: 3 })).toBeVisible();
    await expect.poll(() => new URL(page.url()).searchParams.get("view")).toBe(view);
  }

  await page.goto("/runs/run-demo/experiments?fork=fork-1&tick=3");
  const experimentMenu = page.getByRole("group", { name: "Experiment evidence view" });
  for (const [buttonName, view, heading] of [
    ["rehearsals", "rehearsals", "Checkpoints"],
    ["forecasts", "forecasts", "Predictions"],
    ["campaigns", "campaigns", "Experiments"],
    ["inputs", "inputs", "Datasets"],
    ["evidence", null, "Replay integrity"],
  ] as const) {
    const button = experimentMenu.getByRole("button", { name: buttonName, exact: true });
    await button.click();
    await expect(button).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByRole("heading", { name: heading, exact: true, level: 3 })).toBeVisible();
    await expect.poll(() => new URL(page.url()).searchParams.get("view")).toBe(view);
  }

  expect(diagnostics.consoleErrors).toEqual([]);
  expect(diagnostics.requestFailures).toEqual([]);
});

test("Commons feed menu is selected, shareable, and reload-safe", async ({ page }) => {
  const diagnostics = await setup(page);
  await page.goto("/runs/run-demo/commons?fork=fork-1&tick=3");
  const chronological = page.getByRole("button", { name: "Chronological", exact: true });
  const hot = page.getByRole("button", { name: "Hot", exact: true });
  await expect(chronological).toHaveAttribute("aria-pressed", "true");
  await hot.click();
  await expect(hot).toHaveAttribute("aria-pressed", "true");
  await expect.poll(() => new URL(page.url()).searchParams.get("feed")).toBe("hot");
  await page.reload();
  await expect(hot).toHaveAttribute("aria-pressed", "true");
  await chronological.click();
  await expect(chronological).toHaveAttribute("aria-pressed", "true");
  await expect.poll(() => new URL(page.url()).searchParams.has("feed")).toBe(false);
  await page.goBack();
  await expect(hot).toHaveAttribute("aria-pressed", "true");
  expect(diagnostics.consoleErrors).toEqual([]);
  expect(diagnostics.requestFailures).toEqual([]);
});

test("organization filters survive selection, reload, and browser history", async ({ page }) => {
  const diagnostics = await setup(page);
  await page.goto("/runs/run-demo/organizations?fork=fork-1&tick=3");
  const filters = page.getByLabel("Organization filters");
  const type = filters.getByLabel("Type");
  const status = filters.getByLabel("Status");
  const activeOnly = filters.getByLabel("Active only");

  await type.selectOption("firm");
  await expect.poll(() => new URL(page.url()).searchParams.get("type")).toBe("firm");
  await status.selectOption("listed");
  await activeOnly.click();
  await expect.poll(() => new URL(page.url()).searchParams.get("active")).toBe("1");
  await expect(page.getByRole("heading", { name: "1 matching organizations", exact: true })).toBeVisible();
  await page.reload();
  await expect(type).toHaveValue("firm");
  await expect(status).toHaveValue("listed");
  await expect(activeOnly).toBeChecked();

  const organization = page.getByRole("link", { name: "Northstar Foods", exact: true });
  await expect(organization).toHaveAttribute(
    "href",
    "/runs/run-demo/organizations/firm/1?fork=fork-1&tick=3&type=firm&status=listed&active=1",
  );
  await organization.click();
  await expect(page.getByRole("heading", { name: "Northstar Foods", exact: true })).toBeVisible();
  await expect(type).toHaveValue("firm");
  await page.goBack();
  await expect(type).toHaveValue("firm");
  await page.goBack();
  await expect(activeOnly).not.toBeChecked();
  await expect(status).toHaveValue("listed");
  expect(diagnostics.consoleErrors).toEqual([]);
  expect(diagnostics.requestFailures).toEqual([]);
});

test("world selection URL gives a validated place precedence over region", async ({ page }) => {
  const diagnostics = await setup(page);
  await page.goto("/runs/run-demo/world?region=2&place=1&fork=fork-1&tick=3");
  await expect(page.getByLabel("Region")).toHaveValue("");
  await expect(page.getByLabel("Place")).toHaveValue("1");
  await expect(page.locator(".world-os-world-inspector").getByRole("heading", { name: "Place" })).toBeVisible();
  await expect.poll(() => new URL(page.url()).searchParams.has("region")).toBe(false);
  expect(new URL(page.url()).searchParams.get("place")).toBe("1");
  expect(diagnostics.consoleErrors).toEqual([]);
  expect(diagnostics.requestFailures).toEqual([]);
});

test("world selection removes unresolved region and place URL parameters", async ({ page }) => {
  const diagnostics = await setup(page);
  for (const parameter of ["region", "place"]) {
    await page.goto(`/runs/run-demo/world?${parameter}=999&fork=fork-1&tick=3`);
    await expect(page.getByRole("heading", { name: "City evidence", exact: true })).toBeVisible();
    await expect.poll(() => new URL(page.url()).searchParams.has(parameter)).toBe(false);
    const current = new URL(page.url());
    expect(current.searchParams.get("fork")).toBe("fork-1");
    expect(current.searchParams.get("tick")).toBe("3");
  }
  expect(diagnostics.consoleErrors).toEqual([]);
  expect(diagnostics.requestFailures).toEqual([]);
});

test("shared support projections honor a requested historical tick", async ({ page }) => {
  const diagnostics = await setup(page);
  await page.goto("/runs/run-demo/world?tick=3");
  const payloads = await page.evaluate(async () => Promise.all([
    "/api/v2/snapshot?tick=3",
    "/api/v2/world-map?tick=3",
    "/api/v2/civic/summary?tick=3",
    "/api/v2/search?q=North&tick=3",
  ].map(async path => (await fetch(path)).json())));

  expect(payloads.map(payload => payload.projection)).toEqual([
    "world.snapshot", "world.map", "civic.summary", "search.results",
  ]);
  for (const payload of payloads) {
    expect(payload.tick).toBe(3);
    expect(payload.snapshot_version).toContain("-t3-");
  }
  expect(payloads[2].data.tick).toBe(3);
  expect(diagnostics.consoleErrors).toEqual([]);
  expect(diagnostics.requestFailures).toEqual([]);
});

test("Commons uses the selected run fork and historical tick without polling", async ({ page }) => {
  const diagnostics = await setup(page);
  const requests: string[] = [];
  await page.route("**/api/v2/workspaces/commons?*", async route => {
    requests.push(route.request().url());
    await route.fallback();
  });
  await page.goto("/runs/run-demo/commons?fork=fork-1&tick=3&feed=hot");
  await expect(page.getByRole("heading", { name: "Commons", exact: true })).toBeVisible();
  await expect(page.getByText("Bounded historical commons post")).toBeVisible();
  await expect.poll(() => requests.length).toBeGreaterThan(0);
  const first = new URL(requests[0]);
  expect(first.searchParams.get("fork_id")).toBe("fork-1");
  expect(first.searchParams.get("tick")).toBe("3");
  expect(first.searchParams.get("kind")).toBe("hot");
  const baseline = requests.length;
  await page.waitForTimeout(3_200);
  expect(requests).toHaveLength(baseline);
  await page.getByRole("link", { name: "Open causal trace" }).click();
  await expect(page).toHaveURL(
    /\/runs\/run-demo\/investigations\?fork=fork-1&tick=3&kind=commons_entry&id=1$/,
  );
  expect(diagnostics.consoleErrors).toEqual([]);
  expect(diagnostics.requestFailures).toEqual([]);
});

test("historical, empty, disabled, and current-only states are explicit", async ({ page }) => {
  const diagnostics = await setup(page);
  await page.goto("/runs/run-demo/markets?tick=3");
  await expect(page.getByText("The order book is empty at this tick; no activity is inferred.")).toBeVisible();
  await expect(page.getByText("Historical", { exact: true }).first()).toBeVisible();

  await page.goto("/runs/run-demo/politics-law?tick=3");
  await expect(page.getByText(/Politics is configured disabled/)).toBeVisible();
  await expect(page.getByText(/Legal systems are configured disabled/)).toBeVisible();
  await expect(page.locator("body")).not.toContainText("retained disabled canary");

  await page.goto("/runs/run-demo/experiments?tick=3");
  await expect(page.getByText(/Current-only campaign artifacts are intentionally omitted/)).toBeVisible();
  await expect(page.getByText(/Actions are unavailable in historical views/)).toBeVisible();
  await expect(page.locator("body")).not.toContainText(PRIVATE_CANARY);
  const historicalExperimentBodies = diagnostics.historicalBodies.filter(
    body => body.includes('"projection":"workspace.experiments"'),
  );
  expect(historicalExperimentBodies.length).toBeGreaterThan(0);
  expect(historicalExperimentBodies.join("\n")).not.toContain(PRIVATE_CANARY);
  expect(historicalExperimentBodies.join("\n")).not.toContain(FUTURE_CANARY);
  expect(diagnostics.consoleErrors).toEqual([]);
  expect(diagnostics.requestFailures).toEqual([]);
});

test("narrow workspace tables stay contained and keyboard selection opens validated detail", async ({ page }) => {
  const diagnostics = await setup(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/runs/run-demo/organizations");
  const selection = page.getByRole("button", {
    name: "Select Organization directory row firm:1",
  });
  await selection.focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/organizations\/firm\/1$/);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  const animationDuration = await page.locator(".world-os-workspace-card").first().evaluate(element => getComputedStyle(element).animationDuration);
  expect(["0s", "0ms", ""]).toContain(animationDuration);
  expect(diagnostics.consoleErrors).toEqual([]);
  expect(diagnostics.requestFailures).toEqual([]);
});

test("command navigation reaches canonical routes and unknown paths redirect once", async ({ page }) => {
  const diagnostics = await setup(page);
  await page.goto("/runs/run-demo/world");
  await page.getByRole("button", { name: "Open command menu" }).click();
  const command = page.getByRole("dialog", { name: "Navigate and inspect" });
  await command.getByPlaceholder("Search routes, people, firms, events…").fill("Politics");
  await command.getByRole("option", { name: /Politics & Law/ }).click();
  await expect(page).toHaveURL(/\/runs\/run-demo\/politics-law$/);
  const redirectNavigations: string[] = [];
  const historyBeforeRedirect = await page.evaluate(() => history.length);
  page.on("framenavigated", frame => {
    if (frame === page.mainFrame()) redirectNavigations.push(new URL(frame.url()).pathname);
  });
  await page.goto("/runs/run-demo/not-a-workspace");
  await expect(page).toHaveURL(/\/runs\/run-demo\/overview$/);
  const distinctNavigations = redirectNavigations.filter(
    (path, index) => index === 0 || path !== redirectNavigations[index - 1],
  );
  expect(distinctNavigations).toEqual([
    "/runs/run-demo/not-a-workspace",
    "/runs/run-demo/overview",
  ]);
  expect(await page.evaluate(() => history.length)).toBe(historyBeforeRedirect + 1);
  expect(diagnostics.consoleErrors).toEqual([]);
  expect(diagnostics.requestFailures).toEqual([]);
});

test("price lab gives goods and equities the same historical scope and preserves inspector links", async ({ page }) => {
  const diagnostics = await setup(page);
  const priceRequests: URL[] = [];
  const writes: string[] = [];
  page.on("request", request => {
    if (request.url().includes("/workspaces/price-lab")) priceRequests.push(new URL(request.url()));
    if (request.method() === "POST") writes.push(request.url());
  });
  await page.goto("/runs/run-demo/markets?view=prices&fork=fork-1&tick=3");
  await expect(page.getByRole("heading", { name: "Follow a business from goods to shares" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Goods", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Equities", exact: true })).toBeVisible();
  await expect(page.getByText("No equity executions to plot in this window.")).toBeVisible();
  await expect(page.getByText("Historical order-book state is unavailable. Current quotes are not shown here.")).toBeVisible();
  await page.getByLabel("Measurement window").selectOption("7");
  await page.getByLabel("Business", { exact: true }).selectOption("2");
  await expect(page.getByLabel("Business", { exact: true })).toHaveValue("2");
  await expect(page.getByRole("link", { name: "Inspect business" })).toHaveAttribute("href", "/runs/run-demo/organizations/firm/2?fork=fork-1&tick=3");
  const last = priceRequests.at(-1)!;
  expect(last.searchParams.get("tick")).toBe("3");
  expect(last.searchParams.get("fork_id")).toBe("fork-1");
  expect(last.searchParams.get("window")).toBe("7");
  expect(last.searchParams.get("firm_id")).toBe("2");
  const count = priceRequests.length;
  await page.waitForTimeout(3200);
  expect(priceRequests).toHaveLength(count);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByText("Daily execution data and missing observations", { exact: true }).click();
  await expect(page.getByRole("table", { name: "Daily price observations" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
  await page.getByText("1 sale evidence records", { exact: true }).click();
  await expect(page.getByRole("link", { name: "Sale event #9" })).toHaveAttribute("href", "/runs/run-demo/investigations?fork=fork-1&tick=3&event=9");
  expect(writes).toEqual([]);
  expect(diagnostics.consoleErrors).toEqual([]);
  expect(diagnostics.requestFailures).toEqual([]);
});

test("price lab hides a response from another cursor or instrument", async ({ page }) => {
  await setup(page);
  await page.route("**/api/v2/workspaces/price-lab?*", route => {
    const url = new URL(route.request().url());
    const data = priceLabData(url);
    data.observation.tick = 99;
    data.observation.goods.executed_price.value = 999999;
    return route.fulfill({ json: envelope("price_lab", url, data) });
  });
  await page.goto("/runs/run-demo/markets?view=prices&tick=3");
  await expect(page.getByRole("alert")).toHaveText("Price data does not match the selected run, fork, tick or instrument.");
  await expect(page.getByRole("heading", { name: "Goods", exact: true })).toHaveCount(0);
  await expect(page.locator("body")).not.toContainText("999,999");
});

const studyId = "a".repeat(32);
const studyHash = "b".repeat(64);

function comparisonFixture(fork: string | null = null) {
  return { contract: "operator-study-comparison-v1", id: studyId,
    context: { run_id: "run-demo", fork_id: fork, tick: "live" },
    title: "Goods and equity pilot", hypothesis: "Declared cost intervention", limitations: ["Synthetic small sample"],
    arms: [{ key: "base", label: "Baseline", role: "baseline" }, { key: "cost", label: "Higher cost", role: "treatment" }],
    measurement_window: [1, 8], verification_sha256: "c".repeat(64), manifest_sha256: "d".repeat(64),
    source_identity: { git_commit: "e".repeat(40) },
    outcomes: [
      { key: "goods", domain: "goods", label: "Goods execution VWAP", purpose: "primary", unit: "cents_per_unit", currency: "CAD", aggregation: "window_vwap", formula: "Notional / units", missingness: "No sale is unavailable", metric_version: "goods-sales-vwap-v1" },
      { key: "equity", domain: "equities", label: "Equity execution price", purpose: "exploratory", unit: "cents_per_share", currency: "CAD", aggregation: "terminal", formula: "Last qualified execution", missingness: "No trade is unavailable", metric_version: "qualified-last-execution-v1" },
    ],
    summary: { baseline_arm: "base", exclusions: [], coverage: {
      base: { assigned: 2, started: 2, completed: 2, eligible: 2 },
      cost: { assigned: 2, started: 2, completed: 1, eligible: 1 },
    }, metrics: {
      goods: { base: { mean: 200 }, cost: { mean: 200, paired_effect: { mean_difference: 0, ci95_bootstrap: null, n_pairs: 1, assigned_pairs: 2, pair_exclusions: [{ seed: 2, reason: "incomplete_horizon" }] } } },
      equity: { base: { mean: null }, cost: { mean: null, paired_effect: { mean_difference: null, ci95_bootstrap: null, n_pairs: 0, assigned_pairs: 2, pair_exclusions: [] } } },
    } },
    attempts: [
      { arm: "base", seed: 1, ticks: 8, expected_ticks: 8, execution_status: "completed", eligibility: { status: "eligible", reasons: [] } },
      { arm: "cost", seed: 2, ticks: 3, expected_ticks: 8, execution_status: "paused", eligibility: { status: "ineligible", reasons: ["incomplete_horizon"] } },
    ],
    measurements: { goods: [{ arm: "base", seed: 1, value: 200, status: "complete", age_ticks: null }],
      equity: [{ arm: "base", seed: 1, value: 150, status: "complete", age_ticks: 7 }] },
    verification: { status: "verified", result_sha256: studyHash, declared_context: "verified", issues: [],
      operations: { status: "partial", provider_calls: null, provider_spend_usd: null } },
  };
}

async function mockStudyLibrary(page: Page, mismatch = false) {
  const requests: Array<{ path: string; method: string }> = [];
  await page.route("**/api/v2/operator/research/**", route => {
    const url = new URL(route.request().url());
    requests.push({ path: url.pathname, method: route.request().method() });
    expect(route.request().headers()["x-csrf-token"]).toBe("test");
    if (url.pathname.endsWith("/export")) return route.fulfill({ json: { token: "archive", sha256: "f".repeat(64) } });
    if (url.pathname.includes("/exports/")) return route.fulfill({ contentType: "application/zip", body: "bundle-fixture" });
    if (url.pathname.endsWith("/studies")) return route.fulfill({ json: {
      contract: "operator-study-catalog-v1", context: { run_id: "run-demo", fork_id: url.searchParams.get("fork_id"), tick: "live" },
      items: [{ id: studyId, title: "Goods and equity pilot", domains: ["goods", "equities"], result_sha256: studyHash }], truncated: false, omitted: 0,
    } });
    const data = comparisonFixture(url.searchParams.get("fork_id"));
    if (mismatch) { data.context.run_id = "other-run"; data.hypothesis = "WRONG-STUDY-CANARY"; }
    return route.fulfill({ json: data });
  });
  return requests;
}

test("saved price studies show equal domains, coverage, missing values and private download", async ({ page }) => {
  const diagnostics = await setup(page);
  const requests = await mockStudyLibrary(page);
  await page.goto("/runs/run-demo/experiments?view=price-studies&fork=fork-1");
  await page.getByLabel("Saved study", { exact: true }).selectOption(studyId);
  await expect(page.getByText("Evidence verified", { exact: true })).toBeVisible();
  const goods = page.getByRole("article", { name: "Goods study comparison" });
  const equities = page.getByRole("article", { name: "Equities study comparison" });
  await expect(goods.getByText("0", { exact: true })).toBeVisible();
  await expect(equities.getByText("Unavailable", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("table", { name: "Study attempt coverage" })).toBeVisible();
  await equities.getByText("Values and execution age by seed", { exact: true }).click();
  await expect(equities.getByRole("table", { name: "Outcome evidence for Equity execution price" })).toContainText("7");
  await page.getByText("Attempt and exclusion evidence", { exact: true }).click();
  await expect(page.getByRole("table", { name: "Preserved study attempts" })).toContainText("incomplete horizon");
  await page.getByText("Protocol, costs and limitations", { exact: true }).click();
  await expect(page.getByText("partial", { exact: true })).toBeVisible();
  expect(requests.filter(request => request.method === "POST")).toEqual([]);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("button", { name: "Download private evidence" })).toBeVisible();
  const downloaded = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download private evidence" }).click();
  expect((await downloaded).suggestedFilename()).toBe(`study-${studyId}.zip`);
  await expect(page.getByText(/Download ready. SHA-256:/)).toBeVisible();
  expect(requests.filter(request => request.method === "POST").map(request => request.path)).toEqual([`/api/v2/operator/research/studies/${studyId}/export`]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
  expect(diagnostics.consoleErrors).toEqual([]);
  expect(diagnostics.requestFailures).toEqual([]);
});

test("historical price-study navigation does not fetch local study artifacts", async ({ page }) => {
  await setup(page);
  const requests = await mockStudyLibrary(page);
  await page.goto(`/runs/run-demo/experiments?view=price-studies&tick=3&study=${studyId}`);
  await expect(page.getByRole("heading", { name: "Saved studies use the current operator workspace" })).toBeVisible();
  expect(requests).toEqual([]);
});

test("study comparison refuses a response for a different run", async ({ page }) => {
  await setup(page);
  await mockStudyLibrary(page, true);
  await page.goto(`/runs/run-demo/experiments?view=price-studies&study=${studyId}`);
  await expect(page.getByRole("alert")).toContainText("Study evidence does not match");
  await expect(page.locator("body")).not.toContainText("WRONG-STUDY-CANARY");
  await expect(page.getByRole("button", { name: "Download private evidence" })).toHaveCount(0);
});
