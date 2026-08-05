import { expect, test, type Page } from "@playwright/test";

const TENANT_ID = "10000000-0000-4000-8000-000000000001";
const USER_ID = "20000000-0000-4000-8000-000000000002";
const RUN_ID = "50000000-0000-4000-8000-000000000005";
const CONNECTION_ID = "70000000-0000-4000-8000-000000000007";

type Connection = {
  id: string;
  run_id: string;
  display_name: string;
  tier: string;
  scopes: string[];
  status: string;
  actor_id: number | null;
  last_seen_at: string | null;
  lease_expires_at: string | null;
};

async function installSocket(page: Page) {
  await page.addInitScript(() => {
    class HostedSocket extends EventTarget {
      static OPEN = 1;
      static CLOSED = 3;
      readyState = HostedSocket.OPEN;
      constructor(_url: string) {
        super();
        queueMicrotask(() => this.dispatchEvent(new Event("open")));
      }
      send(_value: string) {}
      close() {
        this.readyState = HostedSocket.CLOSED;
        this.dispatchEvent(new Event("close"));
      }
    }
    Object.defineProperty(window, "WebSocket", { value: HostedSocket });
  });
}

async function mockHostedApi(page: Page) {
  const state: {
    connections: Connection[];
    createdPayload: Record<string, unknown> | null;
    quota: number;
    credentialActions: string[];
  } = {
    connections: [{
      id: CONNECTION_ID,
      run_id: RUN_ID,
      display_name: "Seeded Hermes",
      tier: "actor",
      scopes: ["world.read", "world.act", "commons.read", "commons.write"],
      status: "active",
      actor_id: 42,
      last_seen_at: "2026-07-18T12:00:00Z",
      lease_expires_at: "2099-07-18T12:01:00Z",
    }],
    createdPayload: null,
    quota: 100,
    credentialActions: [],
  };

  await page.route("**/auth/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/auth/login") {
      return route.fulfill({ json: { tenant_id: TENANT_ID } });
    }
    if (path === "/auth/logout") return route.fulfill({ json: { ok: true } });
    return route.fulfill({ status: 404, json: { detail: "not mocked" } });
  });

  await page.route("**/api/v2/**", async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const method = request.method();
    const tenantRoot = `/api/v2/tenants/${TENANT_ID}`;

    if (path === "/api/v2/mode") return route.fulfill({ json: {
      hosted: true,
      mode: "hosted",
      api_base: "/api/v2",
      csrf_cookie_name: "ae_csrf",
      csrf_header_name: "X-AE-CSRF",
      profiles: ["small-town"],
    } });
    if (path === `${tenantRoot}/session`) return route.fulfill({ json: {
      tenant_id: TENANT_ID, user_id: USER_ID, role: "admin",
    } });
    if (path === `${tenantRoot}/runs` && method === "GET") return route.fulfill({ json: {
      runs: [{
        tenant_id: TENANT_ID, run_id: RUN_ID, run_key: "run-hosted-demo",
        display_name: "Hosted Demo", status: "paused",
      }],
    } });
    if (path === `${tenantRoot}/members`) return route.fulfill({ json: { members: [] } });
    if (path === `${tenantRoot}/agent-connections` && method === "GET") {
      return route.fulfill({ json: { connections: state.connections } });
    }
    if (path === `${tenantRoot}/agent-connections` && method === "POST") {
      state.createdPayload = request.postDataJSON();
      state.connections.push({
        id: "80000000-0000-4000-8000-000000000008",
        run_id: RUN_ID,
        display_name: String(state.createdPayload?.display_name),
        tier: String(state.createdPayload?.tier),
        scopes: state.createdPayload?.scopes as string[],
        status: "active",
        actor_id: null,
        last_seen_at: null,
        lease_expires_at: null,
      });
      return route.fulfill({ status: 201, json: {
        connection: state.connections.at(-1),
        credential: {
          token: "ae_pat_created_once",
          expires_at: "2026-08-17T12:00:00Z",
        },
      } });
    }
    if (path === `${tenantRoot}/agent-policy` && method === "GET") {
      return route.fulfill({ json: { max_external_agents_per_run: state.quota } });
    }
    if (path === `${tenantRoot}/agent-policy` && method === "PATCH") {
      state.quota = Number(request.postDataJSON().max_external_agents_per_run);
      return route.fulfill({ json: { max_external_agents_per_run: state.quota } });
    }
    if (path === `${tenantRoot}/agent-connections/${CONNECTION_ID}/credentials`) {
      const action = String(request.postDataJSON().action);
      state.credentialActions.push(action);
      if (action === "rotate") return route.fulfill({ json: {
        token: "ae_pat_rotated_once",
        expires_at: "2026-08-17T12:00:00Z",
      } });
      return route.fulfill({ json: { ok: true, revoked: 1 } });
    }

    // The Observatory mounts beneath the connection panel. Its read-only
    // requests are intentionally isolated from this control-plane test.
    if (path.includes(`/runs/${RUN_ID}/world/`)) {
      return route.fulfill({ status: 404, json: { detail: "world view not mocked" } });
    }
    return route.fulfill({ status: 404, json: { detail: "not mocked" } });
  });
  return state;
}

test("agent owner dashboard creates, copies, rotates, revokes, and reports status", async ({ page, context }) => {
  await context.addCookies([{ name: "ae_csrf", value: "test-csrf", url: "http://127.0.0.1:4174" }]);
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await installSocket(page);
  const state = await mockHostedApi(page);

  await page.goto("/");
  await page.getByLabel("Tenant UUID").fill(TENANT_ID);
  await page.getByLabel("Email").fill("admin@example.test");
  await page.getByLabel("Password").fill("correct horse battery staple");
  await page.locator("form").getByRole("button", { name: "Sign in", exact: true }).click();
  await page.getByRole("button", { name: /Hosted Demo/ }).click();

  await expect(page.getByRole("heading", { name: "Connect an outside agent" })).toBeVisible();
  const seeded = page.getByRole("row", { name: /Seeded Hermes/ });
  await expect(seeded.getByText("online", { exact: true })).toBeVisible();
  await expect(seeded).toContainText("Citizen 42");
  await expect(seeded).toContainText("2026-07-18T12:00:00Z");

  await page.getByLabel("Public name").fill("OpenClaw Founder");
  await page.getByLabel("Biography").fill("A user-owned outside agent.");
  await page.getByLabel("Preferred occupation").fill("builder");
  await page.getByLabel("Wake interval (ticks)").fill("3");
  await page.getByRole("button", { name: "Create dedicated connection" }).click();

  await expect(page.getByText("ae_pat_created_once", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Copy token" }).click();
  await expect(page.getByRole("status")).toHaveText("Credential copied.");
  await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe("ae_pat_created_once");
  expect(state.createdPayload).toMatchObject({
    run_id: RUN_ID,
    display_name: "OpenClaw Founder",
    preferred_occupation: "builder",
    tier: "actor",
    scopes: ["world.read", "world.act", "commons.read", "commons.write"],
    wake_interval_ticks: 3,
  });

  await seeded.getByRole("button", { name: "Rotate" }).click();
  await expect(page.getByText("ae_pat_rotated_once", { exact: true })).toBeVisible();
  await seeded.getByRole("button", { name: "Revoke token" }).click();
  await expect(page.getByRole("status")).toHaveText("All active credentials were revoked.");
  expect(state.credentialActions).toEqual(["rotate", "revoke"]);

  await page.getByLabel("Maximum connections per run").fill("150");
  await page.getByRole("button", { name: "Save tenant quota" }).click();
  await expect(page.getByRole("status")).toHaveText("Tenant external-agent quota updated.");
  expect(state.quota).toBe(150);
});
