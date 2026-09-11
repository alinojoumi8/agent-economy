import { expect, test } from "@playwright/test";
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";

const fixture = JSON.parse(readFileSync(process.env.AE_CITY_ACCEPTANCE_FIXTURE!, "utf8"));

test("a recorded city observation leads to two verified independent price studies", async ({ page }) => {
  const errors: string[] = [], mutations: string[] = [], liveReads: string[] = [];
  let historical = true;
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", request => {
    const url = new URL(request.url());
    if (url.pathname.startsWith("/api/") && !["GET", "HEAD"].includes(request.method())) {
      mutations.push(`${request.method()} ${url.pathname}`);
    }
    if (historical && ["/api/run/status", "/api/llm/runtime", "/api/conversations"].includes(url.pathname)) {
      liveReads.push(url.pathname);
    }
  });
  const run = `/runs/${fixture.run_id}`;
  const day = fixture.trade.tick;
  await page.goto(`${run}/world?tick=${day}&agent=${fixture.person.id}`);
  const explorer = page.getByLabel("Keyboard explorer");
  const lens = page.getByRole("complementary", { name: "Selected city evidence" });
  await expect(explorer).toHaveValue(`agent:${fixture.person.id}`);
  await expect(lens).toContainText(fixture.person.name);
  const history = page.getByRole("region", { name: "City observation history" });
  await history.getByRole("button", { name: /^Save (observation|event bookmark)$/ }).click();
  await expect(history.locator("summary")).toHaveText("Saved observations (1)");
  const savedURL = page.url();
  await page.getByRole("button", { name: "Recorded day", exact: true }).click();
  await expect(page.getByRole("button", { name: "Play recorded day", exact: true })).toBeEnabled();
  await expect(explorer).toHaveValue(`agent:${fixture.person.id}`);
  await explorer.selectOption(`firm:${fixture.trade.firm_id}`);
  const priceLink = page.getByRole("link", { name: /Inspect goods and equity prices/ });
  await expect(priceLink).toHaveAttribute("href", new RegExp(`tick=${day}`));
  await priceLink.click();
  await expect(page.getByRole("article", { name: "Goods price evidence" })).toBeVisible();
  await expect(page.getByRole("article", { name: "Equity price evidence" })).toContainText(fixture.trade.price_cents.toLocaleString("en-US"));
  await page.getByRole("link", { name: /Explore the city/ }).click();
  await expect(explorer).toHaveValue(`firm:${fixture.trade.firm_id}`);
  await page.goBack();
  await expect(page.getByRole("article", { name: "Equity price evidence" })).toBeVisible();
  await page.goto(savedURL);
  await page.reload();
  await expect(history.locator("summary")).toHaveText("Saved observations (1)");
  await history.locator("summary").click();
  await history.locator("ol li").first().getByRole("button").first().click();
  await expect(explorer).toHaveValue(`agent:${fixture.person.id}`);
  await expect(page).toHaveURL(new RegExp(`tick=${day}`));
  await history.locator("summary").click();
  await page.getByRole("heading", { name: "The living city", exact: true }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.join(fixture.output_root, "city-desktop.png") });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "List", exact: true }).click();
  const list = page.getByRole("region", { name: "Public city object list" });
  await list.getByRole("searchbox", { name: "Search city objects" }).fill(fixture.person.name);
  const person = list.getByRole("button", { name: new RegExp(fixture.person.name) });
  await person.focus();
  await page.keyboard.press("Enter");
  await expect(lens).toContainText(fixture.person.name);
  await expect(lens).toBeFocused();
  await expect(lens).toBeInViewport({ ratio: 0.5 });
  await expect(page).toHaveURL(new RegExp(`agent=${fixture.person.id}`));
  await page.screenshot({ path: path.join(fixture.output_root, "city-mobile.png") });
  expect(liveReads).toEqual([]);
  expect(mutations).toEqual(["PUT /api/v2/operator/city-observations"]);

  historical = false;
  await page.setViewportSize({ width: 1440, height: 1000 });
  await history.getByRole("button", { name: "Return to live city", exact: true }).click();
  const studies: Array<{ preset: string; id: string; sha256: string; bytes: number; eligible_attempts: number }> = [];
  for (const preset of ["G2", "F2"]) {
    await page.goto(`${run}/experiments?tick=live&view=price-studies&study_mode=create`);
    await page.getByRole("combobox", { name: "Research question", exact: true }).selectOption(preset);
    await page.getByLabel("World seeds", { exact: true }).fill("1, 2");
    await page.getByLabel("Horizon (days)", { exact: true }).fill("8");
    await page.getByLabel("Intervention day", { exact: true }).fill("3");
    await page.getByLabel("Wall-time limit (seconds)", { exact: true }).fill("180");
    await page.getByLabel("Evidence disk budget (MiB)", { exact: true }).fill("128");
    await page.getByRole("button", { name: "Validate draft", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Review the validated study", exact: true })).toBeVisible();
    await expect(page.getByRole("region", { name: "Validated study protocol" })).toContainText("1, 2");
    await page.reload();
    await expect(page.getByRole("button", { name: "Run independent study", exact: true })).toBeEnabled();
    await page.getByRole("button", { name: "Run independent study", exact: true }).click();
    await expect(page.getByRole("button", { name: "Open verified comparison", exact: true })).toBeVisible({ timeout: 210_000 });
    const comparisonResponse = page.waitForResponse(response => {
      const url = new URL(response.url());
      return /\/api\/v2\/operator\/research\/studies\/[a-f0-9]{32}$/.test(url.pathname)
        && response.request().method() === "GET" && response.ok();
    });
    await page.getByRole("button", { name: "Open verified comparison", exact: true }).click();
    const comparison = await (await comparisonResponse).json();
    expect(comparison.id).toMatch(/^[a-f0-9]{32}$/);
    await expect(page.getByText("Evidence verified", { exact: true })).toBeVisible();
    await expect(page.getByRole("article", { name: "Goods study comparison" })).toBeVisible();
    await expect(page.getByRole("article", { name: "Equities study comparison" })).toBeVisible();
    await expect(page.getByRole("table", { name: "Study attempt coverage" })).toBeVisible();
    expect(comparison.verification.status).toBe("verified");
    expect(comparison.verification.operations.provider_calls).toBe(0);
    expect(comparison.verification.operations.provider_spend_usd).toBe(0);
    expect(new Set(comparison.outcomes.map((outcome: { domain: string }) => outcome.domain))).toEqual(new Set(["goods", "equities"]));
    for (const arm of comparison.arms) {
      expect(comparison.summary.coverage[arm.key]).toMatchObject({ assigned: 2, completed: 2, eligible: 2 });
    }
    await page.getByText("Attempt and exclusion evidence", { exact: true }).click();
    await expect(page.getByRole("table", { name: "Preserved study attempts" }).getByRole("row")).toHaveCount(5);
    await page.screenshot({ path: path.join(fixture.output_root, `${preset}-comparison.png`), fullPage: true });
    const downloadPromise = page.waitForEvent("download");
    const exportResponse = page.waitForResponse(response => response.url().includes(`/studies/${comparison.id}/export`) && response.request().method() === "POST");
    await page.getByRole("button", { name: "Download private evidence", exact: true }).click();
    const download = await downloadPromise;
    const exported = await (await exportResponse).json();
    expect(download.suggestedFilename()).toBe(`study-${comparison.id}.zip`);
    mkdirSync(path.join(fixture.output_root, "downloads"), { recursive: true });
    const destination = path.join(fixture.output_root, "downloads", download.suggestedFilename());
    await download.saveAs(destination);
    expect(await download.failure()).toBeNull();
    const bytes = readFileSync(destination), sha256 = createHash("sha256").update(bytes).digest("hex");
    expect(sha256).toBe(exported.sha256);
    expect(bytes.length).toBe(exported.bytes);
    studies.push({ preset, id: comparison.id, sha256, bytes: bytes.length, eligible_attempts: 4 });
  }
  expect(errors).toEqual([]);
  expect(mutations.filter(value => !/^(PUT \/api\/v2\/operator\/city-observations|POST \/api\/v2\/operator\/research\/)/.test(value))).toEqual([]);
  writeFileSync(path.join(fixture.output_root, "browser-evidence.json"), JSON.stringify({ studies, mutations, liveReads, errors }, null, 2));
});
