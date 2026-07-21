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
        alerts: [{ id: 9, tick: 6, phase: "MARKET", kind: "goods_sale", importance: 2, payload: { qty: 5 } }],
        events: { items: [{ id: 9, tick: 6, phase: "MARKET", kind: "goods_sale", importance: 2, payload: { qty: 5 } }] },
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
}

test.beforeEach(async ({ page }) => { await installSocket(page); await mockApi(page); });

test("overview enters the exact causal chain", async ({ page }) => {
  await page.goto("/runs/run-demo/overview");
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
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
