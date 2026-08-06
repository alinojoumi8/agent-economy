import { expect, test } from "@playwright/test";

test("Pause and Stop interrupt one pending request once", async ({ page }) => {
  await page.goto("/tests/e2e/fixtures/run-header.html");
  const pause = page.getByRole("button", { name: "Pause" });
  const stop = page.getByRole("button", { name: "Stop + report" });

  await page.getByLabel("Simulation speed").selectOption("1");
  await expect.poll(() => page.evaluate(
    () => (window as any).__runHeaderHarness.requests.filter(
      (path: string) => path === "/api/run/speed").length,
  )).toBe(1);
  await expect(pause).toBeEnabled();
  await pause.click();
  await expect.poll(() => page.evaluate(
    () => (window as any).__runHeaderHarness.requests.filter(
      (path: string) => path === "/api/run/pause").length,
  )).toBe(1);
  await expect(pause).toBeDisabled();
  await expect(stop).toBeDisabled();
  await page.evaluate(() => (window as any).__runHeaderHarness.resolve("/api/run/pause"));
  await expect(pause).toBeDisabled();
  await page.evaluate(() => (window as any).__runHeaderHarness.resolve("/api/run/speed"));
  await expect(pause).toBeEnabled();

  await page.getByRole("button", { name: "Generate report" }).click();
  await expect.poll(() => page.evaluate(
    () => (window as any).__runHeaderHarness.requests.filter(
      (path: string) => path === "/api/report").length,
  )).toBe(1);
  await stop.click();
  await expect.poll(() => page.evaluate(
    () => (window as any).__runHeaderHarness.requests.filter(
      (path: string) => path === "/api/run/stop").length,
  )).toBe(1);
  await page.evaluate(() => (window as any).__runHeaderHarness.resolve("/api/run/stop"));
  await expect(stop).toBeDisabled();
  await page.evaluate(() => (window as any).__runHeaderHarness.resolve("/api/report"));
  await expect(stop).toBeEnabled();

  const counts = await page.evaluate(() => Object.fromEntries(
    ["/api/run/speed", "/api/run/pause", "/api/report", "/api/run/stop"].map(
      path => [path, (window as any).__runHeaderHarness.requests.filter(
        (requestPath: string) => requestPath === path).length],
    ),
  ));
  expect(counts).toEqual({
    "/api/run/speed": 1,
    "/api/run/pause": 1,
    "/api/report": 1,
    "/api/run/stop": 1,
  });
});
