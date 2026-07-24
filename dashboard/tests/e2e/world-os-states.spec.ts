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
    const path = new URL(route.request().url()).pathname;
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
  await page.goto("/runs/run-demo/overview");
  await expect(page.getByText("Run paused", { exact: true })).toBeVisible();
  await expect(page.locator(".civic-city__agent")).toHaveCount(3);
  await expect(page.locator(".civic-city__weather-sweep")).toHaveCount(0);
  await expect(page.locator(".civic-city__instruments > div").filter({ hasText: "World time" }).locator("dd")).toHaveText("Current");
});

test("live city failed status is truthful", async ({ page }) => {
  await installSocket(page, "failed");
  await mockCommonApis(page, { status: "failed" });
  await page.goto("/runs/run-demo/overview");
  await expect(page.getByText("Run failed", { exact: true })).toBeVisible();
  await expect(page.getByText("Final inference fabric", { exact: true })).toBeVisible();
  await expect(page.locator(".civic-city__weather-sweep")).toHaveCount(0);
  await expect(page.locator(".civic-city__instruments > div").filter({ hasText: "World time" }).locator("dd")).toHaveText("Current");
});

test("historical tick preserves run identity and label", async ({ page }) => {
  await installSocket(page, "running");
  await mockCommonApis(page, { status: "running" });
  await page.goto("/runs/run-demo/overview?tick=4");
  await expect(page.getByText("Historical tick 4", { exact: true })).toBeVisible();
  await expect(page.getByText("Current inference fabric", { exact: true })).toBeVisible();
  await expect(page.getByText(
    "Provider capacity is current runtime telemetry, not a historical reconstruction.",
    { exact: true },
  )).toBeVisible();
  await expect(page.locator(".civic-city__weather-sweep")).toHaveCount(0);
  await expect(page).toHaveURL(/\/runs\/run-demo\/overview\?tick=4/);
});

test("empty city invents no agents", async ({ page }) => {
  await installSocket(page, "running");
  await mockCommonApis(page, { agents: [], mapAgents: [] });
  await page.goto("/runs/run-demo/overview");
  await expect(page.getByText("No city marks match this view.")).toBeVisible();
  await expect(page.locator(".civic-city__agent")).toHaveCount(0);
});

test("API error city invents no agents", async ({ page }) => {
  await installSocket(page, "running");
  await mockCommonApis(page, { agentsError: true });
  await page.goto("/runs/run-demo/overview");
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
  await page.goto("/runs/run-demo/overview");
  await expect(page.getByText("Mixed projected + derived layout", { exact: true }).first()).toBeVisible();
  await expect(page.locator(".civic-city__agent")).toHaveCount(3);
  await expect(page.locator(".civic-city__weather-sweep")).toHaveCount(1);
  await expect(page.locator(".civic-city__instruments > div").filter({ hasText: "World time" }).locator("dd")).toHaveText("Live");

  await page.getByLabel("Find an agent").fill("zzz-no-match");
  await expect(page.locator(".civic-city__agent")).toHaveCount(0);
  await page.getByRole("button", { name: "Reset city view" }).click();
  await expect(page.locator(".civic-city__agent")).toHaveCount(3);

  await page.goto("/runs/run-demo/overview?tick=4");
  await page.getByRole("link", { name: /World state|World/ }).first().click();
  await expect(page).toHaveURL(/\/runs\/run-demo\/world\?tick=4/);
});
