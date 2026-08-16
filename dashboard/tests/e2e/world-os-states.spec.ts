import { expect, test, type Page } from "@playwright/test";

const baseEnvelope = {
  run_id: "run-demo", fork_id: null, tick: 6, semantics_version: 8,
  projection_version: 1, policy_version: 1, view_key: "view-demo",
  snapshot_version: "s8-p1-t6-e2-demo", event_cursor: 2,
};

const agents = [
  { id: 1, name: "Supplier Officer", kind: "staff", role: "supplier_officer", occupation: "trader", health: "healthy", alive: 1, employer_id: 1, model_tier: "premium" },
  { id: 2, name: "Editor Northstar", kind: "staff", role: "editor", occupation: "editor", health: "healthy", alive: 1, employer_id: null, model_tier: "flash" },
  { id: 3, name: "Dr. Amara Osei", kind: "person", role: null, occupation: "doctor", health: "healthy", alive: 1, employer_id: null, model_tier: "local" },
];

async function installSocket(page: Page, status = "running") {
  await page.addInitScript((runStatus) => {
    class ScriptedSocket extends EventTarget {
      static OPEN = 1;
      static CLOSED = 3;
      readyState = ScriptedSocket.OPEN;
      constructor(_url: string) {
        super();
        queueMicrotask(() => {
          this.dispatchEvent(new Event("open"));
          this.dispatchEvent(new MessageEvent("message", { data: JSON.stringify({
            type: "hello", run_id: "run-demo", fork_id: null, tick: 6,
            semantics_version: 8, projection_version: 1, policy_version: 1,
            view_key: "view-demo", event_cursor: 2, status: runStatus,
          }) }));
        });
      }
      send(_value: string) {}
      close() {
        this.readyState = ScriptedSocket.CLOSED;
        this.dispatchEvent(new CloseEvent("close", { wasClean: true }));
      }
    }
    Object.defineProperty(window, "WebSocket", { value: ScriptedSocket });
  }, status);
}

async function mockCommonApis(page: Page, options: {
  status?: string;
  agents?: typeof agents | [];
  mapAgents?: Array<Record<string, unknown>>;
  agentsError?: boolean;
} = {}) {
  const status = options.status ?? "running";
  const cityAgents = options.agents ?? agents;
  const mapAgents = options.mapAgents ?? cityAgents.map(agent => ({
    ...agent, x: null, y: null,
  }));

  await page.route("**/api/v2/**", async route => {
    const requestUrl = new URL(route.request().url());
    const path = requestUrl.pathname;
    if (path === "/api/v2/snapshot") {
      return route.fulfill({ json: {
        ...baseEnvelope, projection: "world.snapshot", data: {
          summary: {
            status, phase: "FINALIZE", active_tick: null,
            agents_alive: cityAgents.length, active_firms: cityAgents.length ? 1 : 0,
            ledger_balance: 0,
          },
          communications: { total: 0, published: 0, private_total: 0 },
          alerts: [],
          events: { items: cityAgents.length ? [{
            id: 9, tick: 6, phase: "MARKET", kind: "goods_sale", importance: 2,
            payload: { buyer_id: 1, qty: 5 },
          }] : [] },
        },
      } });
    }
    if (path === "/api/v2/map") {
      return route.fulfill({ json: {
        regions: [],
        core_agents: mapAgents,
        firms: cityAgents.length ? [{ id: 1, name: "Northstar Foods", sector: "food", status: "private", x: null, y: null }] : [],
        flows: [],
      } });
    }
    if (path === "/api/v2/world-map") {
      if (options.agentsError) {
        return route.fulfill({ status: 503, json: { detail: "world map offline" } });
      }
      return route.fulfill({ json: {
        ...baseEnvelope, projection: "world.map", data: {
          regions: [],
          agents: mapAgents,
          organizations: cityAgents.length
            ? [{ id: 1, name: "Northstar Foods", sector: "food", status: "private", x: null, y: null }]
            : [],
          places: [],
          presence: [],
        },
      } });
    }
    if (path === "/api/v2/civic/summary") {
      return route.fulfill({ json: {
        ...baseEnvelope, projection: "civic.summary", data: {
          enabled: false, tick: 6, queue: { depth: 0, oldest_age_ticks: 0 }, offices: [],
        },
      } });
    }
    if (path === "/api/v2/workspaces/world") {
      return route.fulfill({ json: {
        ...baseEnvelope, tick: requestUrl.searchParams.get("tick") === "4" ? 4 : 6,
        projection: "workspace.world", data: {
          enabled: true, regions: [], agents: mapAgents, organizations: [], places: [], presence: [], flows: [],
        },
      } });
    }
    if (path === "/api/v2/mode") return route.fulfill({ status: 404, json: {} });
    if (path === "/api/v2/operator/session") {
      return route.fulfill({ json: { owner_id: "local-operator", csrf_token: "test" } });
    }
    if (path === "/api/v2/operator/investigations") {
      return route.fulfill({ json: { items: [] } });
    }
    return route.fulfill({ status: 404, json: { detail: "not mocked" } });
  });

  await page.route("**/api/agents", route => {
    if (options.agentsError) {
      return route.fulfill({ status: 503, json: { error: "agents offline" } });
    }
    return route.fulfill({ json: cityAgents });
  });
  await page.route("**/api/firms", route => route.fulfill({ json: cityAgents.length ? [
    { id: 1, name: "Northstar Foods", sector: "food", status: "private", employees: 1 },
  ] : [] }));
  await page.route("**/api/llm/runtime", route => route.fulfill({ json: {
    live_only: true,
    global: { capacity: 3, in_flight: 0, queue_depth: 0, peak_in_flight: 0, peak_queue_depth: 0, logical_deadline_s: 90 },
    simulated_days: { samples: 0, p50_wall_ms: null, p95_wall_ms: null },
    providers: [],
  } }));
}

test("live city paused status is truthful and does not invent agents", async ({ page }) => {
  await installSocket(page, "paused");
  await mockCommonApis(page, { status: "paused" });
  await page.goto("/runs/run-demo/world");
  await expect(page.getByText("Run paused", { exact: true })).toBeVisible();
  await expect(page.locator(".civic-city__agent")).toHaveCount(3);
  await expect(page.locator(".civic-city__weather-sweep")).toHaveCount(0);
  await expect(page.locator(".civic-city__instruments > div").filter({ hasText: "World time" }).locator(".civic-city__instrument-value")).toHaveText("Current");
});

test("live city failed status is truthful", async ({ page }) => {
  await installSocket(page, "failed");
  await mockCommonApis(page, { status: "failed" });
  await page.goto("/runs/run-demo/world");
  await expect(page.getByText("Run failed", { exact: true })).toBeVisible();
  await expect(page.getByText("Final inference fabric", { exact: true })).toBeVisible();
  await expect(page.locator(".civic-city__weather-sweep")).toHaveCount(0);
  await expect(page.locator(".civic-city__instruments > div").filter({ hasText: "World time" }).locator(".civic-city__instrument-value")).toHaveText("Current");
});

test("historical tick preserves run identity and label", async ({ page }) => {
  await installSocket(page, "running");
  await mockCommonApis(page, { status: "running" });
  await page.goto("/runs/run-demo/world?tick=4");
  await expect(page.getByText("Historical tick 4", { exact: true })).toBeVisible();
  await expect(page.getByText("Current inference fabric", { exact: true })).toBeVisible();
  await expect(page.getByText(
    "Provider capacity is current runtime telemetry, not a historical reconstruction.",
    { exact: true },
  )).toBeVisible();
  await expect(page.locator(".civic-city__weather-sweep")).toHaveCount(0);
  await expect(page).toHaveURL(/\/runs\/run-demo\/world\?tick=4/);
});

test("empty city invents no agents", async ({ page }) => {
  await installSocket(page, "running");
  await mockCommonApis(page, { agents: [], mapAgents: [] });
  await page.goto("/runs/run-demo/world");
  await expect(page.getByText("No city marks match this view.")).toBeVisible();
  await expect(page.locator(".civic-city__agent")).toHaveCount(0);
});

test("API error city invents no agents", async ({ page }) => {
  await installSocket(page, "running");
  await mockCommonApis(page, { agentsError: true });
  await page.goto("/runs/run-demo/world");
  await expect(page.getByText("City evidence is temporarily unavailable.")).toBeVisible();
  await expect(page.locator(".civic-city__agent")).toHaveCount(0);
});

test("mixed provenance, search clear, and navigation preserve selection", async ({ page }) => {
  await installSocket(page, "running");
  await mockCommonApis(page, {
    mapAgents: [
      { id: 1, name: "Supplier Officer", role: "supplier_officer", occupation: "trader", x: 0.2, y: 0.3 },
      { id: 2, name: "Editor Northstar", role: "editor", occupation: "editor", x: null, y: null },
      { id: 3, name: "Dr. Amara Osei", role: null, occupation: "doctor", x: 0.8, y: 0.7 },
    ],
  });
  await page.goto("/runs/run-demo/world");
  await expect(page.getByText("Mixed projected + derived layout", { exact: true }).first()).toBeVisible();
  await expect(page.locator(".civic-city__agent")).toHaveCount(3);
  await expect(page.locator(".civic-city__weather-sweep")).toHaveCount(0);
  await expect(page.locator(".civic-city__instruments > div").filter({ hasText: "World time" }).locator(".civic-city__instrument-value")).toHaveText("Live");

  await page.getByLabel("Find an agent").fill("zzz-no-match");
  await expect(page.locator(".civic-city__agent")).toHaveCount(0);
  await page.getByRole("button", { name: "Reset city view" }).click();
  await expect(page.locator(".civic-city__agent")).toHaveCount(3);

  await page.goto("/runs/run-demo/world?tick=4");
  await page.getByRole("link", { name: "Live City" }).first().click();
  await expect(page).toHaveURL(/\/runs\/run-demo\/world\?tick=4/);
});

test("Diorama shares place and agent evidence through browser history", async ({ page }) => {
  await installSocket(page, "running");
  await mockCommonApis(page, { status: "running" });
  await page.route("**/api/v2/world-map?*", route => route.fulfill({ json: {
    ...baseEnvelope,
    projection_version: 2,
    projection: "world.map",
    data: {
      regions: [
        { id: 1, name: "North", x: 0.2, y: 0.3 },
        { id: 2, name: "South", x: 0.8, y: 0.7 },
      ],
      agents: [
        { ...agents[0], x: 0.24, y: 0.34, population_tier: "core" },
        { ...agents[1], x: 0.68, y: 0.28, population_tier: "core" },
      ],
      organizations: [{
        id: 1, name: "Northstar Foods", sector: "food", status: "private",
        x: 0.65, y: 0.7, employees: 4,
      }],
      places: [{
        id: 4, name: "North Permit Office", kind: "licensing_office",
        owner_type: "agency", owner_id: 2, region_id: 1,
        x: 0.28, y: 0.36, capacity: 9,
        occupancy: { business: 3 }, queue_depth: 5,
        case_status_resolution: "exact",
      }],
      presence: [{
        tick: 6, slot: "business", agent_id: null, place_id: 4,
        place_name: "North Permit Office", place_kind: "licensing_office",
        x: 0.28, y: 0.36, source_type: "privacy_aggregate", occupancy: 3,
      }],
      flows: [{
        kind: "migration", id: 6, agent_id: 1,
        origin_region_id: 1, destination_region_id: 2,
        tick: 6, completed_tick: null, status: "pending",
      }],
      population_mode: "core",
      population_summary: {
        total: 2, core: 2, periphery: 0, rendered_agents: 2, clustered_agents: 0,
      },
    },
  } }));

  await page.goto("/runs/run-demo/overview?view=diorama");
  await expect(page.getByText(
    /2 buildings · 0 projects · 2 agents · 1 flows/,
  )).toBeVisible({ timeout: 15_000 });
  await expect.poll(() => new URL(page.url()).pathname).toBe("/runs/run-demo/world");

  const explorer = page.getByLabel("Keyboard explorer");
  await explorer.selectOption("place:4");
  await expect(page.getByRole("heading", { name: "North Permit Office" })).toBeVisible();
  await expect.poll(() => new URL(page.url()).searchParams.get("place")).toBe("4");
  await expect.poll(() => new URL(page.url()).searchParams.get("agent")).toBe(null);

  await explorer.selectOption("agent:2");
  await expect(page.getByRole("heading", { name: "Editor Northstar" })).toBeVisible();
  await expect.poll(() => new URL(page.url()).searchParams.get("agent")).toBe("2");
  await expect.poll(() => new URL(page.url()).searchParams.get("place")).toBe(null);

  await page.goBack();
  await expect(page.getByRole("heading", { name: "North Permit Office" })).toBeVisible();
  await expect.poll(() => new URL(page.url()).searchParams.get("place")).toBe("4");
});

test("historical Diorama explicitly disables live motion", async ({ page }) => {
  await installSocket(page, "running");
  await mockCommonApis(page, { status: "running" });
  await page.goto("/runs/run-demo/overview?tick=4&view=diorama");

  await expect(page.getByText(
    "Historical tick 4 · motion off",
    { exact: true },
  )).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("Live telemetry pulse", { exact: true })).toHaveCount(0);
});

test("Diorama offers Atlas when WebGL2 is unavailable", async ({ page }) => {
  await page.addInitScript(() => {
    const original = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function getContext(
      contextId: string,
      options?: unknown,
    ) {
      if (contextId === "webgl2") return null;
      return original.call(this, contextId, options as never);
    } as typeof HTMLCanvasElement.prototype.getContext;
  });
  await installSocket(page, "running");
  await mockCommonApis(page, { status: "running" });

  await page.goto("/runs/run-demo/overview?view=diorama");
  await expect(page.getByText(
    "2.5D rendering is unavailable in this browser.",
    { exact: true },
  )).toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: "Use Atlas" }).click();
  await expect(page.locator(".civic-city__map-field")).toBeVisible();
  await expect.poll(() => new URL(page.url()).searchParams.get("view")).toBe(null);
});
