import { expect, test, type Page } from "@playwright/test";

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
          this.dispatchEvent(new MessageEvent("message", { data: JSON.stringify({
            type: "projection_delta", domain: "cursor_advance",
            run_id: "run-demo", fork_id: null, tick: 5,
            semantics_version: 8, projection_version: 1, policy_version: 1,
            view_key: "view-demo", previous_event_cursor: 0, event_cursor: 1,
            payload: [],
          }) }));
        });
      }
      send(_value: string) {}
      close() { this.readyState = ScriptedSocket.CLOSED; this.dispatchEvent(new CloseEvent("close", { wasClean: true })); }
    }
    Object.defineProperty(window, "WebSocket", { value: ScriptedSocket });
  });
}

async function mockApi(page: Page) {
  await page.route("**/api/v2/**", async route => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (path === "/api/v2/mode") return route.fulfill({ status: 404, json: {} });
    if (path === "/api/v2/snapshot") return route.fulfill({ json: {
      ...baseEnvelope, projection: "world.snapshot", data: {
        summary: { status: "paused", phase: "FINALIZE", active_tick: null, agents_alive: 3, active_firms: 1, ledger_balance: 0 },
        communications: { total: 1, published: 0, private_total: 1 },
        alerts: [{ id: 9, tick: 6, phase: "MARKET", kind: "goods_sale", importance: 2, payload: { buyer_id: 1, qty: 5 } }],
        events: { items: [{ id: 9, tick: 6, phase: "MARKET", kind: "goods_sale", importance: 2, payload: { buyer_id: 1, qty: 5 } }] },
      },
    } });
    if (path === "/api/v2/map") return route.fulfill({ json: {
      regions: [],
      core_agents: [
        { id: 1, name: "Supplier Officer", role: "supplier_officer", occupation: "trader", x: null, y: null },
        { id: 2, name: "Editor Northstar", role: "editor", occupation: "editor", x: null, y: null },
        { id: 3, name: "Dr. Amara Osei", role: null, occupation: "doctor", x: null, y: null },
      ],
      firms: [{ id: 1, name: "Northstar Foods", sector: "food", status: "private", x: null, y: null }],
      flows: [],
    } });
    if (path === "/api/v2/world-map") return route.fulfill({ json: {
      ...baseEnvelope, projection: "world.map", data: {
        regions: [],
        agents: [
          { id: 1, name: "Supplier Officer", role: "supplier_officer", occupation: "trader", x: null, y: null },
          { id: 2, name: "Editor Northstar", role: "editor", occupation: "editor", x: null, y: null },
          { id: 3, name: "Dr. Amara Osei", role: null, occupation: "doctor", x: null, y: null },
        ],
        organizations: [{ id: 1, name: "Northstar Foods", sector: "food", status: "private", x: null, y: null }],
        places: [],
        presence: [],
      },
    } });
    if (path === "/api/v2/civic/summary") return route.fulfill({ json: {
      ...baseEnvelope, projection: "civic.summary", data: {
        enabled: false, tick: 6, queue: { depth: 0, oldest_age_ticks: 0 }, offices: [],
      },
    } });
    if (path === "/api/v2/events") return route.fulfill({ json: {
      ...baseEnvelope, projection: "events.page", data: { items: [
        { id: 9, tick: 6, phase: "MARKET", kind: "goods_sale", importance: 2, payload: { qty: 5 } },
      ], next_after_id: null, truncated: false },
    } });
    if (path === "/api/v2/communications/threads") return route.fulfill({ json: {
      ...baseEnvelope, projection: "communications.threads", data: { items: [{
        thread_id: 4, created_tick: 5, status: "open", subject: "Shipment notice",
        authorized_message_count: 1, messages: [{
          id: 5, thread_id: 4, parent_message_id: null, forwarded_from_id: null,
          sender_agent_id: 1, created_tick: 5, deliver_at_tick: 6, visibility: "participants",
          status: "delivered", subject: "Shipment notice", access_basis: "operator_truth",
          sender: { id: 1, name: "Supplier Officer", role: "supplier_officer" },
          audience: [], deliveries: [], disclosures: [],
        }],
      }], next_after_thread_id: null, truncated: false },
    } });
    if (path === "/api/v2/communications/messages/5") return route.fulfill({ json: {
      ...baseEnvelope, projection: "communications.message", data: {
        id: 5, thread_id: 4, parent_message_id: null, forwarded_from_id: null,
        sender_agent_id: 1, created_tick: 5, deliver_at_tick: 6, visibility: "participants",
        status: "delivered", subject: "Shipment notice",
        body_text: "Batch 2026-07 may be contaminated. Limit the scheduled purchase to 5 units.",
        access_basis: "operator_truth", sender: { id: 1, name: "Supplier Officer", role: "supplier_officer" },
        audience: [{ kind: "direct", agent_id: 2 }], deliveries: [{ recipient_agent_id: 2 }], disclosures: [],
      },
    } });
    if (path.startsWith("/api/v2/causal/")) return route.fulfill({ json: {
      ...baseEnvelope, projection: "causal.neighborhood", data: {
        root: { kind: "event", id: "9", tick: 6, order_key: "event-9" }, truncated: false, cycles: [],
        nodes: [
          { kind: "message", id: "5", tick: 5, order_key: "1" },
          { kind: "memory", id: "6", tick: 6, order_key: "2" },
          { kind: "belief", id: "7", tick: 6, order_key: "3" },
          { kind: "action_proposal", id: "8", tick: 6, order_key: "4" },
          { kind: "event", id: "9", tick: 6, order_key: "5" },
          { kind: "ledger_transaction", id: "10", tick: 6, order_key: "6" },
        ],
        edges: [
          [1, "message", "5", "memory", "6", "observed", "engine"],
          [2, "memory", "6", "belief", "7", "triggered", "engine"],
          [3, "belief", "7", "action_proposal", "8", "motivated", "actor_claim"],
          [4, "action_proposal", "8", "event", "9", "triggered", "engine"],
          [5, "event", "9", "ledger_transaction", "10", "settled", "engine"],
        ].map(([id, sk, sid, tk, tid, relation, authority]) => ({
          id, source: { kind: sk, id: sid }, target: { kind: tk, id: tid }, relation,
          authority, confidence: 1, method: authority === "actor_claim" ? "supplier-warning-policy-v1" : null,
          provenance: {}, evidence: {},
        })),
        semantic_rows: [
          { stable_ref: { kind: "message", id: "5", tick: 5 }, kind: "message", id: 5, tick: 5, label: "message" },
          { stable_ref: { kind: "memory", id: "6", tick: 6 }, kind: "memory", id: 6, tick: 6, label: "communication memory" },
          { stable_ref: { kind: "belief", id: "7", tick: 6 }, kind: "belief", id: 7, tick: 6, label: "contamination belief" },
          { stable_ref: { kind: "action_proposal", id: "8", tick: 6 }, kind: "action_proposal", id: 8, tick: 6, label: "buy_goods" },
          { stable_ref: { kind: "event", id: "9", tick: 6 }, kind: "event", id: 9, tick: 6, label: "goods_sale" },
          { stable_ref: { kind: "ledger_transaction", id: "10", tick: 6 }, kind: "ledger_transaction", id: 10, tick: 6, label: "goods_purchase" },
        ],
      },
    } });
    if (path === "/api/v2/operator/session") return route.fulfill({ json: { owner_id: "local-operator", csrf_token: "test" } });
    if (path === "/api/v2/operator/investigations") return route.fulfill({ json: { items: [] } });
    return route.fulfill({ status: 404, json: { detail: "not mocked" } });
  });
  await page.route("**/api/agents", route => route.fulfill({ json: [
    { id: 1, name: "Supplier Officer", kind: "staff", role: "supplier_officer", occupation: "trader", health: "healthy", alive: 1, employer_id: 1, model_tier: "premium" },
    { id: 2, name: "Editor Northstar", kind: "staff", role: "editor", occupation: "editor", health: "healthy", alive: 1, employer_id: null, model_tier: "flash" },
    { id: 3, name: "Dr. Amara Osei", kind: "person", role: null, occupation: "doctor", health: "healthy", alive: 1, employer_id: null, model_tier: "local" },
  ] }));
  await page.route("**/api/firms", route => route.fulfill({ json: [
    { id: 1, name: "Northstar Foods", sector: "food", status: "private", employees: 1 },
  ] }));
  await page.route("**/api/llm/runtime", route => route.fulfill({ json: {
    live_only: true,
    global: { capacity: 3, in_flight: 1, queue_depth: 0, peak_in_flight: 2, peak_queue_depth: 1, logical_deadline_s: 90 },
    simulated_days: { samples: 2, p50_wall_ms: 1200, p95_wall_ms: 1600 },
    providers: [],
  } }));
}

test.beforeEach(async ({ page }) => { await installSocket(page); await mockApi(page); });

test("initial projection handshake does not refetch stale backfill", async ({ page }) => {
  let snapshotRequests = 0;
  await page.route("**/api/v2/snapshot?*", async route => {
    snapshotRequests += 1;
    await route.fallback();
  });
  await page.goto("/runs/run-demo/overview");
  await expect(page.getByRole("heading", { name: "Live City" })).toBeVisible();
  await page.waitForTimeout(200);
  expect(snapshotRequests).toBeLessThanOrEqual(2);
});

test("cursor_ahead recovery resets and resumes without looping", async ({ page }) => {
  let snapshotRequests = 0;

  await page.addInitScript(() => {
    class RecoverySocket extends EventTarget {
      static OPEN = 1;
      static CLOSED = 3;
      readyState = RecoverySocket.OPEN;
      constructor(_url: string) {
        super();
        (window as any).__recoverySocket = this;
        queueMicrotask(() => {
          this.dispatchEvent(new Event("open"));
          this.dispatchEvent(new MessageEvent("message", { data: JSON.stringify({
            type: "hello", run_id: "run-demo", fork_id: null, tick: 6,
            semantics_version: 8, projection_version: 1, policy_version: 1,
            view_key: "view-demo", event_cursor: 10, status: "running",
          }) }));
        });
      }
      send(_value: string) {}
      close() {
        this.readyState = RecoverySocket.CLOSED;
        this.dispatchEvent(new CloseEvent("close", { wasClean: true }));
      }
      emit(message: unknown) {
        this.dispatchEvent(new MessageEvent("message", { data: JSON.stringify(message) }));
      }
    }
    Object.defineProperty(window, "WebSocket", { value: RecoverySocket });
  });

  await page.route("**/api/v2/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/v2/snapshot") {
      snapshotRequests += 1;
      return route.fulfill({ json: {
        ...baseEnvelope, event_cursor: 4, projection: "world.snapshot", data: {
          summary: {
            status: "running", phase: "FINALIZE", active_tick: null,
            agents_alive: 1, active_firms: 1, ledger_balance: 0,
          },
          communications: { total: 0, published: 0, private_total: 0 },
          alerts: [],
          events: { items: [{
            id: 9, tick: 6, phase: "MARKET", kind: "goods_sale", importance: 2,
            payload: { qty: 5 },
          }] },
        },
      } });
    }
    if (path === "/api/v2/map") {
      return route.fulfill({ json: {
        regions: [],
        core_agents: [{ id: 1, name: "Supplier Officer", role: "supplier_officer", occupation: "trader", x: null, y: null }],
        firms: [], flows: [],
      } });
    }
    if (path === "/api/v2/world-map") {
      return route.fulfill({ json: {
        ...baseEnvelope, projection: "world.map", data: {
          regions: [],
          agents: [{ id: 1, name: "Supplier Officer", role: "supplier_officer", occupation: "trader", x: null, y: null }],
          organizations: [],
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

  await page.goto("/runs/run-demo/overview");
  await expect(page.getByRole("heading", { name: "Live City" })).toBeVisible();
  const beforeRecovery = snapshotRequests;

  await page.evaluate(() => {
    const recovery = (window as any).__recoverySocket;
    recovery.emit({
      type: "error", code: "cursor_ahead", event_cursor: 4,
    });
  });
  await expect(page.getByRole("alert")).toContainText("cursor_ahead");

  await page.evaluate(() => {
    const recovery = (window as any).__recoverySocket;
    recovery.emit({
      type: "projection_delta", domain: "cursor_advance",
      run_id: "run-demo", fork_id: null, tick: 6,
      semantics_version: 8, projection_version: 1, policy_version: 1,
      view_key: "view-demo", previous_event_cursor: 4, event_cursor: 5,
      payload: [],
    });
  });
  await page.waitForTimeout(300);
  // Recovery invalidates once; it must not enter a tight refetch loop.
  expect(snapshotRequests - beforeRecovery).toBeLessThanOrEqual(3);
  await expect(page.getByRole("heading", { name: "Live City" })).toBeVisible();
});

test("cursor gaps request contiguous backfill and return live", async ({ page }) => {
  await page.addInitScript(() => {
    class GapSocket extends EventTarget {
      static OPEN = 1;
      static CLOSED = 3;
      readyState = GapSocket.OPEN;
      sent: unknown[] = [];
      constructor(_url: string) {
        super();
        (window as any).__gapSocket = this;
        queueMicrotask(() => {
          this.dispatchEvent(new Event("open"));
          this.emit({
            type: "hello", run_id: "run-demo", fork_id: null, tick: 6,
            semantics_version: 8, projection_version: 1, policy_version: 1,
            view_key: "view-demo", event_cursor: 0, status: "running",
          });
        });
      }
      send(value: string) { this.sent.push(JSON.parse(value)); }
      close() {
        this.readyState = GapSocket.CLOSED;
        this.dispatchEvent(new CloseEvent("close", { wasClean: true }));
      }
      emit(message: unknown) {
        this.dispatchEvent(new MessageEvent(
          "message", { data: JSON.stringify(message) }));
      }
    }
    Object.defineProperty(window, "WebSocket", { value: GapSocket });
  });

  await page.goto("/runs/run-demo/overview");
  await expect(page.getByRole("heading", { name: "Live City" })).toBeVisible();
  await expect.poll(async () => page.evaluate(() => (
    (window as any).__gapSocket.sent
  ))).toContainEqual({ type: "hello", event_cursor: 0 });
  await page.evaluate(() => {
    (window as any).__gapSocket.sent.length = 0;
  });

  await page.evaluate(() => {
    (window as any).__gapSocket.emit({
      type: "projection_delta", domain: "observatory",
      run_id: "run-demo", fork_id: null, tick: 6,
      semantics_version: 8, projection_version: 1, policy_version: 1,
      view_key: "view-demo", previous_event_cursor: 3, event_cursor: 4,
      payload: {},
    });
  });

  await expect(page.getByRole("alert")).toContainText("cursor_gap");
  await expect.poll(async () => page.evaluate(() => (
    (window as any).__gapSocket.sent
  ))).toContainEqual({ type: "hello", event_cursor: 0 });

  await page.evaluate(() => {
    const socket = (window as any).__gapSocket;
    for (let cursor = 1; cursor <= 4; cursor += 1) {
      socket.emit({
        type: "projection_delta", domain: "cursor_advance",
        run_id: "run-demo", fork_id: null, tick: 6,
        semantics_version: 8, projection_version: 1, policy_version: 1,
        view_key: "view-demo", previous_event_cursor: cursor - 1,
        event_cursor: cursor, payload: [],
      });
    }
  });

  await expect(page.getByRole("alert")).toHaveCount(0);
  await expect(page.getByText("live · cursor 4", { exact: true })).toBeVisible();
});

test("lineage changes reconcile from the authoritative server hello", async ({ page }) => {
  await page.addInitScript(() => {
    class LineageSocket extends EventTarget {
      static OPEN = 1;
      static CLOSED = 3;
      static instances: LineageSocket[] = [];
      readyState = LineageSocket.OPEN;
      sent: unknown[] = [];
      closed = false;
      constructor(_url: string) {
        super();
        LineageSocket.instances.push(this);
        (window as any).__lineageSockets = LineageSocket.instances;
        queueMicrotask(() => {
          const forkId = (window as any).__lineageFork ?? "fork-a";
          this.dispatchEvent(new Event("open"));
          this.emit({
            type: "hello", run_id: "run-demo",
            fork_id: forkId,
            tick: 6, semantics_version: 8, projection_version: 1,
            policy_version: 1, view_key: "view-demo",
            event_cursor: forkId === "fork-a" ? 4 : 0, status: "running",
          });
        });
      }
      send(value: string) { this.sent.push(JSON.parse(value)); }
      close() {
        if (this.closed) return;
        this.closed = true;
        this.readyState = LineageSocket.CLOSED;
        this.dispatchEvent(new CloseEvent("close", { wasClean: true }));
      }
      emit(message: unknown) {
        this.dispatchEvent(new MessageEvent(
          "message", { data: JSON.stringify(message) }));
      }
    }
    Object.defineProperty(window, "WebSocket", { value: LineageSocket });
  });

  await page.goto("/runs/run-demo/overview");
  await expect(page.getByRole("heading", { name: "Live City" })).toBeVisible();
  await expect(page.getByText(/live .* cursor 4/)).toBeVisible();
  const initialConnections = await page.evaluate(() => (
    (window as any).__lineageSockets.length
  ));

  await page.evaluate(() => {
    (window as any).__lineageFork = "fork-b";
    (window as any).__lineageSockets.at(-1).emit({
      type: "projection_delta", domain: "cursor_advance",
      run_id: "run-demo", fork_id: "fork-b", tick: 6,
      semantics_version: 8, projection_version: 1, policy_version: 1,
      view_key: "view-demo", previous_event_cursor: 4, event_cursor: 5,
      payload: { summary: { status: "should-not-render" } },
    });
  });

  await expect(page.getByRole("alert")).toContainText("lineage_mismatch");
  await expect(page.getByText("should-not-render")).toHaveCount(0);
  await expect.poll(async () => page.evaluate(() => (
    (window as any).__lineageSockets.length
  ))).toBe(initialConnections + 1);
  await expect.poll(async () => page.evaluate(() => (
    (window as any).__lineageSockets.at(-1).sent
  ))).toContainEqual({ type: "hello", event_cursor: 0 });
  await expect(page.getByText(/live .* cursor 0/)).toBeVisible();

  await page.evaluate(() => {
    (window as any).__lineageSockets.at(-1).emit({
      type: "projection_delta", domain: "cursor_advance",
      run_id: "run-demo", fork_id: "fork-b", tick: 6,
      semantics_version: 8, projection_version: 1, policy_version: 1,
      view_key: "view-demo", previous_event_cursor: 0, event_cursor: 1,
      payload: [],
    });
  });

  await expect(page.getByRole("alert")).toHaveCount(0);
  await expect(page.getByText("should-not-render")).toHaveCount(0);
  await expect(page.getByText(/live .* cursor 1/)).toBeVisible();
});

test("live city layers, search, and evidence lens stay truthful and interactive", async ({ page }) => {
  await page.goto("/runs/run-demo/overview");
  await expect(page.getByRole("heading", { name: "The living city" })).toBeVisible();
  await expect(page.getByText("Derived civic layout", { exact: true }).first()).toBeVisible();
  await expect(page.locator(".civic-city__agent")).toHaveCount(3);

  await page.getByRole("button", { name: /Health/ }).click();
  await expect(page.locator(".civic-city__agent")).toHaveCount(1);
  await page.locator(".civic-city__agent").click();
  await expect(page.getByRole("heading", { name: "Dr. Amara Osei" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Open citizen dossier" })).toHaveAttribute("href", "/runs/run-demo/people/3");

  await page.getByRole("button", { name: /All/ }).click();
  await page.getByLabel("Find an agent").fill("Supplier Officer");
  await expect(page.locator(".civic-city__agent")).toHaveCount(1);
  await page.locator(".civic-city__agent").click();
  await expect(page.locator(".civic-city__activity strong")).toHaveText("Goods Sale");
  await expect(page.getByRole("link", { name: "Trace this event" })).toHaveAttribute("href", "/runs/run-demo/investigations?event=9");
});

test("citizen menu unifies app and onboarding links in the same tab", async ({ page }) => {
  await page.goto("/runs/run-demo/overview");
  await page.locator("summary", { hasText: "Citizen menu" }).click();
  const menu = page.getByRole("navigation", { name: "Agent Economy sections" });
  await expect(menu).toBeVisible();

  const expected = {
    Observatory: "/",
    "World OS": "/runs/run-demo/overview",
    Commons: "/runs/run-demo/commons",
    Join: "/join/local-sandbox",
    "My Agents": "/my-agents",
  };
  for (const [label, href] of Object.entries(expected)) {
    const link = menu.getByRole("link", { name: label, exact: true });
    await expect(link).toHaveAttribute("href", href);
    await expect(link).not.toHaveAttribute("target", "_blank");
  }
});

test("overview enters the exact causal chain", async ({ page }) => {
  await page.goto("/runs/run-demo/overview");
  await expect(page.getByRole("heading", { name: "Live City" })).toBeVisible();
  await expect(page.getByText("Balanced")).toBeVisible();
  await page.getByRole("link", { name: "Investigate event 9" }).click();
  await expect(page).toHaveURL(/investigations\?event=9/);
  await expect(page.getByRole("heading", { name: "Causal graph" })).toBeVisible();
  await expect(page.locator(".world-os-causal-graph [role=button]")).toHaveCount(6);
});

test("truth inspection renders authorized fields without browser persistence", async ({ page }) => {
  await page.goto("/runs/run-demo/news-communications");
  await page.getByRole("button", { name: "Truth inspector" }).click();
  await page.getByRole("button", { name: /Shipment notice/ }).click();
  await expect(page.getByText("Batch 2026-07 may be contaminated", { exact: false })).toBeVisible();
  await expect(page.getByText("operator_truth", { exact: true })).toBeVisible();
  const storage = await page.evaluate(() => ({ ...localStorage, ...sessionStorage }));
  expect(JSON.stringify(storage)).not.toContain("contaminated");
});

test("graph and semantic table share keyboard selection with reduced motion", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/runs/run-demo/investigations?event=9");
  const proposalNode = page.locator('.world-os-causal-graph [role="button"][aria-label^="action_proposal 8"]');
  await proposalNode.focus();
  await page.keyboard.press("Enter");
  await expect(page.locator(".world-os-semantic-panel tr.selected")).toContainText("buy_goods");
  await page.getByRole("button", { name: "Zoom in" }).click();
  await expect(page.locator(".world-os-graph-controls output")).toHaveText("120%");
  const duration = await page.locator(".world-os-nav a").first().evaluate(element => getComputedStyle(element).transitionDuration);
  expect(duration).toBe("0s");
});

test("390 pixel workflow keeps navigation, chronology, and evidence usable", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/runs/run-demo/news-communications");
  await expect(page.getByRole("navigation", { name: "World OS workspaces" })).toBeVisible();
  await page.getByRole("button", { name: "Truth inspector" }).click();
  await page.getByRole("button", { name: /Shipment notice/ }).click();
  await expect(page.getByText("Untrusted simulated communication")).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});

test("command navigation, tick travel, and rail controls stay interactive", async ({ page }) => {
  const pageErrors: string[] = [];
  page.on("pageerror", error => pageErrors.push(error.message));
  await page.goto("/runs/run-demo/overview");
  await expect(page.getByRole("heading", { name: "Live City" })).toBeVisible();

  await page.keyboard.press("Control+K");
  const command = page.getByRole("dialog", { name: "Go to a workspace" });
  await expect(command).toBeVisible();
  const commandSearch = command.getByPlaceholder("Search people, markets, evidence…");
  await commandSearch.fill("communications");
  await commandSearch.press("Enter");
  await expect(page).toHaveURL(/news-communications/);

  await page.goto("/runs/run-demo/overview");
  await page.getByLabel("Inspect tick").fill("4");
  await page.getByRole("button", { name: "Go to tick" }).click();
  await expect(page).toHaveURL(/tick=4/);
  await expect(page.getByText("Historical", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Collapse workspace rail" }).click();
  await expect(page.locator(".world-os-shell")).toHaveClass(/world-os-shell--collapsed/);
  await expect(page.getByRole("navigation", { name: "World OS workspaces" })).toBeVisible();
  expect(pageErrors).toEqual([]);
});
