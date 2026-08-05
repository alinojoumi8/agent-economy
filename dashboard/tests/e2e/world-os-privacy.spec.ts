import { expect, test, type Page } from "@playwright/test";

const CANARY = "PRIVACY-CANARY-9f3c-private-body";
const baseEnvelope = {
  run_id: "run-demo", fork_id: null, tick: 6, semantics_version: 8,
  projection_version: 1, policy_version: 1, view_key: "view-demo",
  snapshot_version: "s8-p1-t6-e2-demo", event_cursor: 2,
};

async function installSocket(page: Page) {
  await page.addInitScript(() => {
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
            view_key: "view-demo", event_cursor: 2, status: "paused",
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
  });
}

async function mockPrivacyApis(page: Page) {
  await page.route("**/api/v2/**", async route => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (path === "/api/v2/snapshot") {
      return route.fulfill({ json: {
        ...baseEnvelope, projection: "world.snapshot", data: {
          summary: { status: "paused", phase: "FINALIZE", active_tick: null, agents_alive: 2, active_firms: 1, ledger_balance: 0 },
          communications: { total: 1, published: 0, private_total: 1 },
          alerts: [],
          events: { items: [] },
        },
      } });
    }
    if (path === "/api/v2/communications/threads") {
      return route.fulfill({ json: {
        ...baseEnvelope, projection: "communications.threads", data: {
          items: [{
            thread_id: 4, created_tick: 5, status: "open", subject: "Authorized notice",
            authorized_message_count: 1, messages: [{
              id: 5, thread_id: 4, parent_message_id: null, forwarded_from_id: null,
              sender_agent_id: 1, created_tick: 5, deliver_at_tick: 6, visibility: "participants",
              status: "delivered", subject: "Authorized notice", access_basis: "operator_truth",
              sender: { id: 1, name: "Supplier Officer", role: "supplier_officer" },
              audience: [], deliveries: [], disclosures: [],
            }],
          }],
          next_after_thread_id: null, truncated: false,
        },
      } });
    }
    if (path === "/api/v2/communications/messages/5") {
      // Unauthorized principal: ordinary observer without truth flag would 404.
      // This suite asserts the unauthorized path never returns the canary body.
      if (url.searchParams.get("agent_id") === "99") {
        return route.fulfill({
          status: 404,
          json: { detail: "message not found" },
        });
      }
      return route.fulfill({ json: {
        ...baseEnvelope, projection: "communications.message", data: {
          id: 5, thread_id: 4, parent_message_id: null, forwarded_from_id: null,
          sender_agent_id: 1, created_tick: 5, deliver_at_tick: 6, visibility: "participants",
          status: "delivered", subject: "Authorized notice",
          body_text: `Public authorized summary only. ${CANARY}`,
          access_basis: "operator_truth",
          sender: { id: 1, name: "Supplier Officer", role: "supplier_officer" },
          audience: [], deliveries: [], disclosures: [],
        },
      } });
    }
    if (path === "/api/v2/communications/messages/77") {
      return route.fulfill({
        status: 404,
        json: { detail: "message not found" },
      });
    }
    if (path === "/api/v2/search") {
      return route.fulfill({ json: {
        ...baseEnvelope,
        projection: "search.results",
        data: { groups: [
          { kind: "agent", items: [], truncated: false },
          { kind: "firm", items: [], truncated: false },
          { kind: "event", items: [], truncated: false },
          { kind: "communication_thread", items: [], truncated: false },
        ] },
      } });
    }
    if (path === "/api/v2/map") {
      return route.fulfill({ json: { regions: [], core_agents: [], firms: [], flows: [] } });
    }
    if (path === "/api/v2/world-map") {
      return route.fulfill({ json: {
        ...baseEnvelope, projection: "world.map", data: {
          regions: [], agents: [], organizations: [], places: [], presence: [],
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
    if (path === "/api/v2/mode") return route.fulfill({ status: 404, json: {} });
    if (path === "/api/v2/operator/session") {
      return route.fulfill({ json: { owner_id: "local-operator", csrf_token: "test" } });
    }
    if (path === "/api/v2/operator/investigations") {
      return route.fulfill({ json: { items: [] } });
    }
    return route.fulfill({ status: 404, json: { detail: "not mocked" } });
  });
  await page.route("**/api/agents", route => route.fulfill({ json: [
    { id: 1, name: "Supplier Officer", kind: "staff", role: "supplier_officer", occupation: "trader", alive: 1 },
  ] }));
  await page.route("**/api/firms", route => route.fulfill({ json: [] }));
  await page.route("**/api/llm/runtime", route => route.fulfill({ json: {
    live_only: true,
    global: { capacity: 1, in_flight: 0, queue_depth: 0, peak_in_flight: 0, peak_queue_depth: 0, logical_deadline_s: 90 },
    simulated_days: { samples: 0, p50_wall_ms: null, p95_wall_ms: null },
    providers: [],
  } }));
}

async function assertNoCanaryLeak(page: Page) {
  await expect(page.locator("body")).not.toContainText(CANARY);
  expect(page.url()).not.toContain(CANARY);
  const storage = await page.evaluate(() => ({
    local: { ...localStorage },
    session: { ...sessionStorage },
  }));
  expect(JSON.stringify(storage)).not.toContain(CANARY);
}

test("unauthorized private message requests stay 404 and never leak canaries", async ({ page }) => {
  const consoleMessages: string[] = [];
  page.on("console", message => consoleMessages.push(message.text()));
  await installSocket(page);
  await mockPrivacyApis(page);

  await page.goto("/runs/run-demo/news-communications");
  const unauthorized = await page.evaluate(async () => {
    const response = await fetch("/api/v2/communications/messages/77");
    return { status: response.status, body: await response.text() };
  });
  expect(unauthorized.status).toBe(404);
  expect(unauthorized.body).not.toContain(CANARY);
  await assertNoCanaryLeak(page);

  await page.goto("/runs/run-demo/overview?tick=3");
  await assertNoCanaryLeak(page);
  await page.goto("/runs/run-demo/news-communications");
  await assertNoCanaryLeak(page);

  await page.goto("/runs/run-demo/overview");
  await expect(page.getByRole("heading", { name: "Live City" })).toBeVisible();
  await page.keyboard.press("Control+K");
  const command = page.getByRole("dialog", { name: "Navigate and inspect" });
  const responsePromise = page.waitForResponse(response => (
    new URL(response.url()).pathname === "/api/v2/search"
  ));
  await command.getByPlaceholder("Search routes, people, firms, events…").fill("Classified merger");
  const searchResponse = await responsePromise;
  expect(await searchResponse.text()).not.toContain(CANARY);
  await expect(command.getByText(/No route or authorized entity matches/)).toBeVisible();
  await assertNoCanaryLeak(page);
  expect(page.url()).not.toContain("Classified");
  const searchStorage = await page.evaluate(() => ({ ...localStorage, ...sessionStorage }));
  expect(JSON.stringify(searchStorage)).not.toContain("Classified");

  const joined = consoleMessages.join("\n");
  expect(joined).not.toContain(CANARY);
});
