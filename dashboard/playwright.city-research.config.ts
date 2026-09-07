import { defineConfig, devices } from "@playwright/test";
import { readFileSync } from "node:fs";
import path from "node:path";

const fixturePath = process.env.AE_CITY_ACCEPTANCE_FIXTURE;
if (!fixturePath) throw new Error("Run python scripts/city_research_acceptance.py to create an isolated backend.");
const fixture = JSON.parse(readFileSync(fixturePath, "utf8"));

export default defineConfig({
  testDir: "./tests/real-backend",
  testMatch: "city-research.spec.ts",
  outputDir: path.join(fixture.output_root, "browser-results"),
  timeout: 540_000,
  expect: { timeout: 15_000 },
  workers: 1,
  retries: 0,
  reporter: "line",
  use: {
    ...devices["Desktop Chrome"], baseURL: fixture.base_url,
    viewport: { width: 1440, height: 1000 },
    actionTimeout: 15_000, navigationTimeout: 30_000,
    trace: "retain-on-failure", screenshot: "only-on-failure",
  },
});
