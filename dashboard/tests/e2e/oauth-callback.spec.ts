import { expect, test } from "@playwright/test";
import { spawn, type ChildProcess } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { createServer, type Server } from "node:http";
import { tmpdir } from "node:os";
import { resolve } from "node:path";

test.describe("real browser OAuth callback", () => {
  test.describe.configure({ mode: "serial" });
  let app: ChildProcess;
  let directory: string;
  let base: string;
  let callback: Server;
  let redirect: string;
  const arrivals: URL[] = [];

  test.beforeAll(async ({ request }) => {
    directory = await mkdtemp(resolve(tmpdir(), "ae-oauth-browser-"));
    app = spawn(process.env.AE_TEST_PYTHON || "python", [
      "scripts/oauth_browser_fixture.py", "--directory", directory,
    ], { cwd: resolve(process.cwd(), ".."), stdio: "ignore", windowsHide: true });
    let startupError: Error | undefined;
    app.on("error", error => { startupError = error; });
    await expect.poll(async () => {
      if (startupError) throw startupError;
      if (app.exitCode !== null) throw new Error(`OAuth fixture exited ${app.exitCode}`);
      try {
        base = JSON.parse(await readFile(resolve(directory, "ready.json"), "utf8")).url;
        return (await request.get(`${base}/.well-known/oauth-authorization-server`)).status();
      } catch { return 0; }
    }, { timeout: 25_000 }).toBe(200);
    callback = createServer((req, res) => {
      arrivals.push(new URL(req.url!, redirect));
      res.writeHead(200, { "Content-Type": "text/plain" });
      res.end("Callback received");
    });
    await new Promise<void>(done => callback.listen(0, "127.0.0.1", done));
    const address = callback.address();
    if (!address || typeof address === "string") throw new Error("No callback port");
    redirect = `http://127.0.0.1:${address.port}/callback`;
  });

  test.afterAll(async () => {
    if (callback) await new Promise<void>(done => callback.close(() => done()));
    if (app && app.exitCode === null && app.pid) {
      const exited = new Promise<void>(done => app.once("exit", () => done()));
      await writeFile(resolve(directory, "stop"), "stop");
      await exited;
    }
    if (directory) await rm(directory, { recursive: true, force: true });
  });

  for (const decision of ["approve", "deny"] as const) {
    test(`${decision} reaches the registered loopback callback`, async ({ page, request }) => {
      const registration = await request.post(`${base}/oauth/register`, { data: {
        client_name: "Browser regression", redirect_uris: [redirect],
        grant_types: ["authorization_code", "refresh_token"], response_types: ["code"],
        token_endpoint_auth_method: "none", scope: "world.read world.act",
      } });
      expect(registration.status()).toBe(201);
      const clientId = (await registration.json()).client_id;
      const verifier = "v".repeat(64);
      const state = randomUUID();
      const params = new URLSearchParams({ response_type: "code", client_id: clientId,
        redirect_uri: redirect, code_challenge: createHash("sha256").update(verifier).digest("base64url"),
        code_challenge_method: "S256", state, resource: `${base}/mcp`, scope: "world.read world.act" });
      await page.goto(`${base}/oauth/authorize?${params}`);
      if (decision === "approve") {
        await page.locator('[name="handle"]').fill(`browser-${state.slice(0, 8)}`);
        await page.locator('[name="display_name"]').fill("Browser citizen");
      }
      await page.locator(`button[value="${decision}"]`).click();
      await expect(page).toHaveURL(url => url.origin === new URL(redirect).origin && url.pathname === "/callback");
      const arrived = new URL(page.url());
      expect(arrived.searchParams.get("state")).toBe(state);
      expect(arrived.searchParams.get("iss")).toBe(base);
      expect(arrivals.some(url => url.searchParams.get("state") === state)).toBe(true);
      if (decision === "deny") {
        expect(arrived.searchParams.get("error")).toBe("access_denied");
        expect(arrived.searchParams.has("code")).toBe(false);
      } else {
        const token = await request.post(`${base}/oauth/token`, { form: {
          grant_type: "authorization_code", code: arrived.searchParams.get("code")!,
          client_id: clientId, redirect_uri: redirect, code_verifier: verifier, resource: `${base}/mcp`,
        } });
        expect(token.status()).toBe(200);
        expect((await token.json()).access_token).toBeTruthy();
      }
      params.set("redirect_uri", `${redirect}/unregistered`);
      const rejected = await page.goto(`${base}/oauth/authorize?${params}`);
      expect(rejected!.status()).toBeGreaterThanOrEqual(400);
      expect(rejected!.headers()["content-security-policy"]).toContain("form-action 'self';");
      expect(page.url()).toContain(`${base}/oauth/authorize`);
    });
  }
});
