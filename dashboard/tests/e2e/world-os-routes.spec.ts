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

function envelope(path: string, url: URL, data: unknown) {
  const historical = url.searchParams.get("tick") === "3";
  return {
    ...baseEnvelope,
    tick: historical ? 3 : 6,
    fork_id: url.searchParams.get("fork_id"),
    projection: `workspace.${path}`,
    snapshot_version: `s12-p1-t${historical ? 3 : 6}-workspaces`,
    data,
  };
}

async function mockWorkspaceApis(page: Page, servedHistoricalBodies: string[] = []) {
  await page.route("**/api/v2/**", async route => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const historical = url.searchParams.get("tick") === "3";
    let body: unknown;
    if (path === "/api/v2/mode") {
      body = { hosted: false, mode: "local" };
    } else if (path === "/api/v2/workspaces/world") {
      body = envelope("world", url, {
        enabled: true,
        regions: [
          { id: 1, name: "North", currency_code: "CAD", population_target: 2, x: 0.2, y: 0.3, legal_ruleset: "north-rules" },
          { id: 2, name: "South", currency_code: "USD", population_target: 1, x: 0.7, y: 0.6, legal_ruleset: "south-rules" },
        ],
        agents: [{ id: 1, name: "Supplier Officer", role: "supplier_officer", occupation: "trader", region_id: 1 }],
        organizations: [{ id: 1, name: "Northstar Foods", sector: "food", status: "listed", active: true, region_id: 1 }],
        places: [{ id: 1, name: "North Exchange", kind: "market", region_id: 1, region_name: "North", x: 0.3, y: 0.4, capacity: 20 }],
        presence: [{ id: 1, tick: historical ? 3 : 6, agent_id: 1, place_id: 1 }],
        flows: [{ id: 1, kind: "trade", origin_region_id: 1, destination_region_id: 2, tick: 3 }],
      });
    } else if (path === "/api/v2/workspaces/organizations") {
      body = envelope("organizations", url, {
        organizations: [
          { id: 1, type: "firm", name: "Northstar Foods", sector: "food", region_id: 1, region_name: "North", status: "listed", active: true, employees: 2, balance_cents: 1200, currency_code: "CAD", founded_tick: 1 },
          { id: 2, type: "bank", name: "Civic Bank", status: "open", active: true, reserve_cents: 900, equity_cents: 300, currency_code: "USD" },
        ],
        institutions: { legal_enabled: !historical, politics_enabled: !historical, agencies: [] },
        contracts: [{ id: 1, title: "Public charter", contract_type: "charter", jurisdiction: "North", offered_tick: 2, status: "executed" }],
        disclosures: [{ id: 1, tick: 3, firm_id: 1, disclosure_type: "earnings", facts: { revenue_cents: 100 } }],
      });
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
        checkpoints: [{ id: 1, tick: 3, created_at: "2026-08-05" }], shocks: [], predictions: [],
        acceptance: [{ id: 1, scheduled_tick: 3, question: "Replay integrity", status: "passed", detail: "Exact replay receipt stored" }],
        datasets: [{ id: 1, dataset_key: "macro-public", vintage_date: "2026-07", status: "ready" }],
        scenarios: [{ id: 1, scenario_key: "baseline", version: "1", title: "Baseline" }],
        experiments: historical ? [] : [{ id: 1, experiment_key: "price-shock", scenario_key: "baseline", status: "complete", checkpoint_hash: "abc" }],
        results: historical ? [] : [{ id: 1, experiment_id: 1, arm: "control", seed: 7, run_id: "child", replay_hash: "def", metrics: { output: 1 } }],
        current_only_artifacts_omitted: historical,
      });
    } else if (path === "/api/v2/snapshot") {
      body = { ...baseEnvelope, projection: "world.snapshot", data: {
        summary: { status: "paused", phase: "FINALIZE", active_tick: null, agents_alive: 1, active_firms: 1, ledger_balance: 0 },
        communications: { total: 0, published: 0, private_total: 0 }, alerts: [], events: { items: [] },
      } };
    } else if (path === "/api/v2/world-map") {
      body = { ...baseEnvelope, projection: "world.map", data: { regions: [], agents: [], organizations: [], places: [], presence: [] } };
    } else if (path === "/api/v2/civic/summary") {
      body = { ...baseEnvelope, projection: "civic.summary", data: { enabled: false, tick: 6, queue: { depth: 0, oldest_age_ticks: 0 }, offices: [] } };
    } else if (path === "/api/v2/search") {
      body = { ...baseEnvelope, projection: "search.results", data: { groups: [
        { kind: "agent", items: [], truncated: false }, { kind: "firm", items: [], truncated: false },
        { kind: "event", items: [], truncated: false }, { kind: "communication_thread", items: [], truncated: false },
      ] } };
    } else {
      return route.fulfill({ status: 404, json: { detail: "not mocked" } });
    }
    const serialized = JSON.stringify(body);
    expect(serialized).not.toContain(PRIVATE_CANARY);
    if (historical) {
      expect(serialized).not.toContain(FUTURE_CANARY);
      servedHistoricalBodies.push(serialized);
    }
    return route.fulfill({ contentType: "application/json", body: serialized });
  });
  await page.route("**/api/agents", route => route.fulfill({ json: [] }));
  await page.route("**/api/firms", route => route.fulfill({ json: [] }));
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
  const historicalBodies: string[] = [];
  await mockWorkspaceApis(page, historicalBodies);
  return { consoleErrors, requestFailures, historicalBodies };
}

test("all canonical workspace routes navigate with observer context and validated details", async ({ page }) => {
  const diagnostics = await setup(page);
  await page.goto("/runs/run-demo/world?fork=fork-1&tick=3");
  await expect(page.getByRole("heading", { name: "World", exact: true }).last()).toBeVisible();
  await expect(page.getByText("Historical tick 3", { exact: true }).first()).toBeVisible();

  for (const [linkName, heading] of [
    ["Organizations", "Organizations"], ["Markets", "Markets"],
    ["Politics & Law", "Politics & Law"], ["Experiments", "Experiments"],
  ] as const) {
    await page.getByRole("link", { name: linkName, exact: true }).click();
    await expect(page.getByRole("heading", { name: heading, exact: true }).last()).toBeVisible();
    await expect(page).toHaveURL(/fork=fork-1/);
    await expect(page).toHaveURL(/tick=3/);
  }

  await page.goto("/runs/run-demo/organizations/1?fork=fork-1&tick=3");
  await expect(page.getByRole("heading", { name: "Northstar Foods" })).toBeVisible();
  await expect(page).toHaveURL(/organizations\/1\?fork=fork-1&tick=3/);
  await page.goto("/runs/run-demo/experiments/1?fork=fork-1");
  await page.getByRole("button", { name: "campaigns", exact: true }).click();
  await expect(page.getByRole("heading", { name: "price-shock" })).toBeVisible();
  await expect(page).toHaveURL(/experiments\/1\?fork=fork-1&view=campaigns/);

  expect(diagnostics.historicalBodies.length).toBeGreaterThan(0);
  expect(diagnostics.historicalBodies.join("\n")).not.toContain(FUTURE_CANARY);
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
  expect(diagnostics.consoleErrors).toEqual([]);
  expect(diagnostics.requestFailures).toEqual([]);
});

test("narrow workspace tables stay contained and keyboard selection opens validated detail", async ({ page }) => {
  const diagnostics = await setup(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/runs/run-demo/organizations");
  const row = page.locator(".world-os-workspace-table tbody tr").first();
  await row.focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/organizations\/1$/);
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
  await page.goto("/runs/run-demo/not-a-workspace");
  await expect(page).toHaveURL(/\/runs\/run-demo\/overview$/);
  expect(diagnostics.consoleErrors).toEqual([]);
  expect(diagnostics.requestFailures).toEqual([]);
});
