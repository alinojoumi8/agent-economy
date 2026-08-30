import { expect, test } from "@playwright/test";

const realRunId = process.env.AE_REAL_RUN_ID || "";

test.describe("provider-free real backend menu smoke", () => {
  test.skip(!realRunId, "Set AE_REAL_RUN_ID to an active local deterministic run.");

  test("every workspace and internal view is operable against canonical projections", async ({ page, request }) => {
    test.setTimeout(120_000);
    const consoleErrors: string[] = [];
    const requestFailures: string[] = [];
    page.on("console", message => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });
    page.on("pageerror", error => consoleErrors.push(error.message));
    page.on("requestfailed", failed => {
      if (failed.failure()?.errorText !== "net::ERR_ABORTED") {
        requestFailures.push(`${failed.method()} ${failed.url()} ${failed.failure()?.errorText || "failed"}`);
      }
    });

    const runPath = `/runs/${encodeURIComponent(realRunId)}`;
    await page.goto(`${runPath}/overview`);
    await expect(page.locator(".world-os-context h1")).toHaveText("Pulse");

    const citizenMenu = page.locator("details.citizen-menu-dropdown");
    await citizenMenu.locator("summary").click();
    const productNavigation = page.getByRole("navigation", { name: "Agent Economy sections" });
    for (const [label, href] of [
      ["Observatory", "/"],
      ["World OS", `${runPath}/overview`],
      ["Commons", `${runPath}/commons`],
    ] as const) {
      await expect(productNavigation.getByRole("link", { name: label, exact: true })).toHaveAttribute("href", href);
    }
    await citizenMenu.locator("summary").click();

    const commandTrigger = page.getByRole("button", { name: "Open command menu" });
    await commandTrigger.click();
    const command = page.getByRole("dialog", { name: "Navigate and inspect" });
    await expect(command.getByRole("option", { name: /Markets/ })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(command).toBeHidden();
    await expect(commandTrigger).toBeFocused();

    const initialStatus = await request.get("http://127.0.0.1:4174/api/run/status");
    expect(initialStatus.ok()).toBe(true);
    const initial = await initialStatus.json() as { tick?: number; running?: boolean; status?: string };
    if (Number(initial.tick || 0) < 3 && initial.running !== true) {
      const run = page.getByRole("button", { name: "Run", exact: true });
      await expect(run).toBeEnabled();
      await run.click();
    }
    await expect.poll(async () => {
      const response = await request.get("http://127.0.0.1:4174/api/run/status");
      if (!response.ok()) return -1;
      const status = await response.json() as { tick?: number };
      return Number(status.tick || 0);
    }, { timeout: 60_000 }).toBeGreaterThanOrEqual(3);

    const destinations = [
      ["Pulse", "overview"],
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
    for (const [label, route] of destinations) {
      const navigation = page.getByRole("navigation", { name: "Civic Atlas workspaces" });
      const link = navigation.getByRole("link", { name: label, exact: true });
      await expect(link).toBeVisible();
      await link.click();
      await expect(page).toHaveURL(new RegExp(`${runPath}/${route}(?:\\?|$)`));
      await expect(page.locator(".world-os-context h1")).toHaveText(label);
      await expect(page.locator(".world-os-error")).toHaveCount(0);
    }

    await page.goto(`${runPath}/markets`);
    const marketMenu = page.getByRole("group", { name: "Market evidence view" });
    for (const label of ["trades", "fx", "Circuit breakers", "orders"]) {
      const button = marketMenu.getByRole("button", { name: label, exact: true });
      await button.click();
      await expect(button).toHaveAttribute("aria-pressed", "true");
    }

    await page.goto(`${runPath}/politics-law`);
    const institutionalMenu = page.getByRole("group", { name: "Institutional evidence view" });
    for (const label of ["lobbying", "legal", "M&A", "legislation"]) {
      const button = institutionalMenu.getByRole("button", { name: label, exact: true });
      await button.click();
      await expect(button).toHaveAttribute("aria-pressed", "true");
    }

    await page.goto(`${runPath}/experiments`);
    const experimentMenu = page.getByRole("group", { name: "Experiment evidence view" });
    for (const label of ["rehearsals", "forecasts", "campaigns", "inputs", "evidence"]) {
      const button = experimentMenu.getByRole("button", { name: label, exact: true });
      await button.click();
      await expect(button).toHaveAttribute("aria-pressed", "true");
    }

    await page.goto(`${runPath}/commons`);
    const hot = page.getByRole("button", { name: "Hot", exact: true });
    const chronological = page.getByRole("button", { name: "Chronological", exact: true });
    await hot.click();
    await expect(hot).toHaveAttribute("aria-pressed", "true");
    await chronological.click();
    await expect(chronological).toHaveAttribute("aria-pressed", "true");

    await page.goto(`${runPath}/news-communications`);
    const communicationMenu = page.getByRole("group", { name: "Communication access view" });
    for (const label of ["Agent view", "Truth inspector", "Ordinary"]) {
      const button = communicationMenu.getByRole("button", { name: label, exact: true });
      await button.click();
      await expect(button).toHaveAttribute("aria-pressed", "true");
    }

    await page.goto(`${runPath}/people`);
    const projectBrowser = page.locator("details.world-os-project-browser");
    await projectBrowser.locator("summary").click();
    await projectBrowser.getByLabel("Kind").selectOption("construction");
    await projectBrowser.getByLabel("Status").selectOption("active");
    await expect(projectBrowser).toHaveAttribute("open", "");

    await page.goto(`${runPath}/world`);
    await expect(page.getByRole("heading", { name: "The living city", exact: true })).toBeVisible();
    const cityView = page.getByRole("group", { name: "City view" });
    await cityView.getByRole("button", { name: "Atlas", exact: true }).click();
    const cityLayers = page.getByRole("group", { name: "City evidence layer" });
    for (const label of ["Work", "Comms", "Markets", "Civic", "Health", "All"]) {
      const button = cityLayers.getByRole("button", { name: new RegExp(`^${label}`) });
      await button.click();
      await expect(button).toHaveAttribute("aria-pressed", "true");
    }

    await page.goto(`${runPath}/live-city`);
    await expect(page.getByRole("heading", { name: "The recorded day", exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: /Workspaces/ })).toHaveAttribute(
      "href", `${runPath}/overview`,
    );

    await page.goto("/");
    await expect(page.getByText("The living legal-political economy", { exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "Open World OS", exact: true })).toHaveAttribute(
      "href", `${runPath}/overview`,
    );

    expect(consoleErrors).toEqual([]);
    expect(requestFailures).toEqual([]);
  });
});
