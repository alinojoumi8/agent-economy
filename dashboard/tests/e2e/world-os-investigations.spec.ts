import { expect, test, type BrowserContext, type Page } from "@playwright/test";
import { readFile } from "node:fs/promises";

const PRIVATE_CANARY = "PRIVATE-EXPORT-INTERNAL-9f3c";
const baseEnvelope = {
  run_id: "run-demo", fork_id: null, tick: 6, semantics_version: 8,
  projection_version: 1, policy_version: 1, view_key: "view-demo",
  snapshot_version: "s8-p1-t6-e2-demo", event_cursor: 2,
};

type Investigation = {
  id: string; owner_id: string; title: string; run_id: string; fork_id: string | null;
  pinned_tick: number | null; query: Record<string, unknown>; layout: Record<string, unknown>;
  version: number; items: Array<Record<string, unknown>>;
  hypotheses: Array<Record<string, unknown>>;
  private_message_body?: string;
};

function initialState() {
  const original: Investigation = {
    id: "inv-1", owner_id: "local-operator", title: "Original", run_id: "run-demo",
    fork_id: null, pinned_tick: 6, query: { relation: "cited" }, layout: { left: 320 },
    version: 1,
    items: [{ id: "item-1", item_kind: "event", stable_ref: { kind: "event", id: 9 }, note: "Committed evidence" }],
    hypotheses: [{ id: "hyp-1", statement: "Delivery changed demand", status: "open" }],
    private_message_body: PRIVATE_CANARY,
  };
  return {
    records: new Map<string, Investigation>([[original.id, original]]),
    patchRequests: 0,
    createRequests: 0,
    delayNextListMs: 0,
    delayedListRequestsStarted: 0,
    delayedListResponsesCompleted: 0,
  };
}

async function installSocket(context: BrowserContext) {
  await context.addInitScript(() => {
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

function causalEnvelope() {
  return {
    ...baseEnvelope, projection: "causal.neighborhood", data: {
      root: { kind: "event", id: "9", tick: 6, order_key: "event-9" },
      truncated: false, cycles: [],
      nodes: [{ kind: "event", id: "9", tick: 6, order_key: "event-9" }],
      edges: [],
      semantic_rows: [{
        stable_ref: { kind: "event", id: "9", tick: 6, order_key: "event-9" },
        kind: "event", id: 9, tick: 6, label: "goods sale",
      }],
    },
  };
}

async function installApi(context: BrowserContext, state: ReturnType<typeof initialState>) {
  await context.route("**/api/**", async route => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (path === "/api/v2/mode") return route.fulfill({ json: {
      mode: "local", hosted: false, api_base: "/api/v2",
    } });
    if (path === "/api/v2/snapshot") return route.fulfill({ json: {
      ...baseEnvelope, projection: "world.snapshot", data: {
        summary: { status: "paused", phase: "FINALIZE", active_tick: null, agents_alive: 1, active_firms: 1, ledger_balance: 0 },
        communications: { total: 0, published: 0, private_total: 0 }, alerts: [],
        events: { items: [{ id: 9, tick: 6, phase: "MARKET", kind: "goods_sale", importance: 2, payload: {} }] },
      },
    } });
    if (path === "/api/v2/events") return route.fulfill({ json: {
      ...baseEnvelope, projection: "events.page", data: { items: [
        { id: 9, tick: 6, phase: "MARKET", kind: "goods_sale", importance: 2, payload: {} },
      ], next_after_id: null, truncated: false },
    } });
    if (path.startsWith("/api/v2/causal/")) return route.fulfill({ json: causalEnvelope() });
    if (path === "/api/v2/map") return route.fulfill({ json: { regions: [], core_agents: [], firms: [], flows: [] } });
    if (path === "/api/v2/world-map") return route.fulfill({ json: {
      ...baseEnvelope, projection: "world.map", data: { regions: [], agents: [], organizations: [], places: [], presence: [] },
    } });
    if (path === "/api/v2/civic/summary") return route.fulfill({ json: {
      ...baseEnvelope, projection: "civic.summary", data: { enabled: false, tick: 6, queue: { depth: 0, oldest_age_ticks: 0 }, offices: [] },
    } });
    if (path === "/api/v2/operator/session") {
      return route.fulfill({ json: { owner_id: "local-operator", csrf_token: "test" } });
    }
    if (path === "/api/v2/operator/investigations" && request.method() === "GET") {
      const items = [...state.records.values()].map(record => ({ ...record }));
      if (state.delayNextListMs) {
        const delay = state.delayNextListMs;
        state.delayNextListMs = 0;
        state.delayedListRequestsStarted += 1;
        await new Promise(resolve => setTimeout(resolve, delay));
        state.delayedListResponsesCompleted += 1;
      }
      return route.fulfill({ json: { items } });
    }
    if (path === "/api/v2/operator/investigations" && request.method() === "POST") {
      expect(request.headers()["x-csrf-token"]).toBe("test");
      state.createRequests += 1;
      const body = request.postDataJSON();
      const record: Investigation = {
        id: `inv-${state.records.size + 1}`, owner_id: "local-operator",
        title: body.title, run_id: "run-demo", fork_id: body.fork_id ?? null,
        pinned_tick: body.pinned_tick ?? null, query: body.query || {}, layout: body.layout || {},
        version: 1, items: [], hypotheses: [],
      };
      state.records.set(record.id, record);
      return route.fulfill({ json: record });
    }
    const investigationMatch = path.match(/^\/api\/v2\/operator\/investigations\/([^/]+)$/);
    if (investigationMatch) {
      const id = decodeURIComponent(investigationMatch[1]);
      const record = state.records.get(id);
      if (!record) return route.fulfill({ status: 404, json: { detail: "investigation not found" } });
      if (request.method() === "GET") return route.fulfill({ json: record });
      if (request.method() === "PATCH") {
        expect(request.headers()["x-csrf-token"]).toBe("test");
        state.patchRequests += 1;
        const body = request.postDataJSON();
        if (body.expected_version !== record.version) {
          return route.fulfill({ status: 409, json: { detail: "investigation version conflict" } });
        }
        const updated = { ...record, title: body.title, version: record.version + 1 };
        state.records.set(id, updated);
        return route.fulfill({ json: updated });
      }
    }
    const exportMatch = path.match(/^\/api\/v2\/operator\/investigations\/([^/]+)\/export$/);
    if (exportMatch) {
      const id = decodeURIComponent(exportMatch[1]);
      const record = state.records.get(id);
      if (!record) return route.fulfill({ status: 404, json: { detail: "investigation not found" } });
      const publicRecord = Object.fromEntries(
        Object.entries(record).filter(([key]) => key !== "private_message_body"),
      );
      return route.fulfill({ json: {
        json: {
          format: "world-os-investigation-v1", investigation: publicRecord,
          redaction_manifest: { private_message_bodies: "not_copied", operator_audit: "not_included" },
        },
        markdown: `# ${record.title}\n\nRun: \`${record.run_id}\`\n\n## Hypotheses\n\n- [open] Delivery changed demand\n\n## Evidence\n\n- \`{\"id\":9,\"kind\":\"event\"}\` Committed evidence\n`,
      } });
    }
    if (path === "/api/agents") return route.fulfill({ json: [] });
    if (path === "/api/firms") return route.fulfill({ json: [] });
    if (path === "/api/llm/runtime") return route.fulfill({ json: {
      live_only: true,
      global: { capacity: 1, in_flight: 0, queue_depth: 0, peak_in_flight: 0, peak_queue_depth: 0, logical_deadline_s: 90 },
      simulated_days: { samples: 0, p50_wall_ms: null, p95_wall_ms: null }, providers: [],
    } });
    return route.fulfill({ status: 404, json: { detail: "not mocked" } });
  });
}

function monitor(page: Page, errors: string[]) {
  page.on("console", message => {
    if (message.type() === "error" && !message.text().startsWith("Failed to load resource:")) {
      errors.push(`console:${message.text()}`);
    }
  });
  page.on("pageerror", error => errors.push(`page:${error.message}`));
  page.on("requestfailed", request => {
    if (request.failure()?.errorText !== "net::ERR_ABORTED") {
      errors.push(`request:${request.url()}:${request.failure()?.errorText}`);
    }
  });
  page.on("response", response => {
    const expectedConflict = response.status() === 409
      && response.request().method() === "PATCH"
      && new URL(response.url()).pathname.startsWith("/api/v2/operator/investigations/");
    if (response.status() >= 400 && !expectedConflict) {
      errors.push(`http:${response.status()}:${response.url()}`);
    }
  });
}

test("two analyst contexts resolve stale titles and download redacted evidence", async ({ browser }) => {
  const state = initialState();
  const contextA = await browser.newContext();
  const contextB = await browser.newContext();
  await installSocket(contextA);
  await installSocket(contextB);
  await installApi(contextA, state);
  await installApi(contextB, state);
  const pageA = await contextA.newPage();
  const pageB = await contextB.newPage();
  const errors: string[] = [];
  monitor(pageA, errors);
  monitor(pageB, errors);
  const route = "/runs/run-demo/investigations/inv-1?event=9";
  await Promise.all([pageA.goto(route), pageB.goto(route)]);
  const titleA = pageA.getByLabel("Investigation title");
  const titleB = pageB.getByLabel("Investigation title");
  await expect(titleA).toHaveValue("Original");
  await expect(titleB).toHaveValue("Original");

  await titleA.fill("Remote title");
  await pageA.getByRole("button", { name: "Save", exact: true }).click();
  await expect(pageA.getByText("Saved as version 2.")).toBeVisible();

  await titleB.fill("Local draft");
  await pageB.getByRole("button", { name: "Save", exact: true }).click();
  const conflict = pageB.getByRole("dialog", { name: "Investigation changed on the server" });
  await expect(conflict).toContainText("Your draft: Local draft");
  await expect(conflict).toContainText("Server version 2: Remote title");
  await expect(conflict.getByRole("heading")).toBeFocused();
  await pageB.waitForTimeout(200);
  expect(state.patchRequests).toBe(2);

  await pageB.keyboard.press("Escape");
  await expect(conflict).toBeHidden();
  await expect(titleB).toBeFocused();
  await expect(titleB).toHaveValue("Local draft");
  await expect(pageB.getByRole("button", { name: "Save", exact: true })).toBeEnabled();
  state.delayNextListMs = 10_000;
  await pageB.getByRole("button", { name: "Save", exact: true }).click();
  await expect(pageB.getByText("Saved as version 3.")).toBeVisible();
  await expect.poll(() => state.delayedListRequestsStarted).toBe(1);
  expect(state.patchRequests).toBe(3);

  await titleA.fill("Remote second");
  await pageA.getByRole("button", { name: "Save", exact: true }).click();
  const conflictA = pageA.getByRole("dialog", { name: "Investigation changed on the server" });
  await expect(conflictA).toContainText("Server version 3: Local draft");
  await conflictA.getByRole("button", { name: "Continue editing" }).click();
  await pageA.getByRole("button", { name: "Save", exact: true }).click();
  await expect(pageA.getByText("Saved as version 4.")).toBeVisible();
  await titleB.fill("Local copy");
  await pageB.getByRole("button", { name: "Save", exact: true }).click();
  await expect(conflict).toContainText("Server version 4: Remote second");
  await conflict.getByRole("button", { name: "Save draft as new investigation" }).click();
  await expect(pageB).toHaveURL(/\/investigations\/inv-2\?/);
  await expect(conflict).toBeHidden({ timeout: 500 });
  await expect(titleB).toHaveValue("Local copy", { timeout: 500 });
  expect(state.createRequests).toBe(1);
  expect(state.records.get("inv-1")?.title).toBe("Remote second");
  expect(state.records.get("inv-1")?.version).toBe(4);
  expect(state.records.get("inv-2")?.items).toEqual([]);
  expect(state.records.get("inv-2")?.hypotheses).toEqual([]);
  await expect.poll(
    () => state.delayedListResponsesCompleted,
    { timeout: 12_000 },
  ).toBe(1);
  await expect(pageB).toHaveURL(/\/investigations\/inv-2\?/);
  await expect(titleB).toHaveValue("Local copy");
  await expect(pageB.getByRole("navigation", { name: "Saved investigations" })
    .getByRole("button", { name: /Local copy/ })).toHaveClass(/selected/);

  await pageB.getByRole("navigation", { name: "Saved investigations" })
    .getByRole("button", { name: /Remote second/ }).click();
  await expect(pageB).toHaveURL(/\/investigations\/inv-1\?/);
  await expect(titleB).toHaveValue("Remote second");
  await titleB.fill("Unsaved navigation draft");
  const navigationTrigger = pageB.getByRole("navigation", { name: "Saved investigations" })
    .getByRole("button", { name: /Local copy/ });
  await navigationTrigger.click();
  const discardDialog = pageB.getByRole("dialog", { name: "Discard unsaved title draft?" });
  await expect(discardDialog.getByRole("heading")).toBeFocused();
  const stayButton = discardDialog.getByRole("button", { name: "Stay" });
  const discardButton = discardDialog.getByRole("button", { name: "Discard draft and continue" });
  await discardButton.focus();
  await pageB.keyboard.press("Tab");
  await expect(stayButton).toBeFocused();
  await pageB.keyboard.press("Shift+Tab");
  await expect(discardButton).toBeFocused();
  await pageB.keyboard.press("Escape");
  await expect(discardDialog).toBeHidden();
  await expect(navigationTrigger).toBeFocused();
  await pageB.getByRole("link", { name: "Live City" }).click();
  await expect(discardDialog).toBeVisible();
  await expect(pageB).toHaveURL(/\/investigations\/inv-1\?/);
  await discardDialog.getByRole("button", { name: "Stay" }).click();
  await expect(discardDialog).toBeHidden();
  await expect(pageB).toHaveURL(/\/investigations\/inv-1\?/);
  await pageB.evaluate(() => history.back());
  await expect(discardDialog).toBeVisible();
  await expect(pageB).toHaveURL(/\/investigations\/inv-1\?/);
  await discardDialog.getByRole("button", { name: "Stay" }).click();
  await expect(discardDialog).toBeHidden();
  await pageB.getByRole("button", { name: "Cancel", exact: true }).click();
  const jsonDownloadPromise = pageB.waitForEvent("download");
  await pageB.getByRole("button", { name: "Download JSON" }).click();
  const jsonDownload = await jsonDownloadPromise;
  expect(jsonDownload.suggestedFilename()).toBe("inv-1.json");
  const jsonPath = await jsonDownload.path();
  const jsonBytes = await readFile(jsonPath!, "utf8");
  expect(JSON.parse(jsonBytes).format).toBe("world-os-investigation-v1");
  expect(jsonBytes).toContain('"private_message_bodies": "not_copied"');
  expect(jsonBytes).not.toContain(PRIVATE_CANARY);

  const markdownDownloadPromise = pageB.waitForEvent("download");
  await pageB.getByRole("button", { name: "Download Markdown" }).click();
  const markdownDownload = await markdownDownloadPromise;
  expect(markdownDownload.suggestedFilename()).toBe("inv-1.md");
  const markdownPath = await markdownDownload.path();
  const markdownBytes = await readFile(markdownPath!, "utf8");
  expect(markdownBytes).toContain("# Remote second");
  expect(markdownBytes).toContain("Run: `run-demo`");
  expect(markdownBytes).toContain("## Evidence");
  expect(markdownBytes).not.toContain(PRIVATE_CANARY);

  await pageB.setViewportSize({ width: 390, height: 844 });
  expect(await pageB.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  const browserState = await pageB.evaluate(async () => ({
    url: location.href,
    local: { ...localStorage },
    session: { ...sessionStorage },
    databases: "databases" in indexedDB ? await indexedDB.databases() : [],
  }));
  expect(JSON.stringify(browserState)).not.toContain(PRIVATE_CANARY);
  expect(await pageB.locator("body").textContent()).not.toContain(PRIVATE_CANARY);
  expect(errors).toEqual([]);
  await contextA.close();
  await contextB.close();
});
