import { expect, test, type Page } from "@playwright/test";

function cityFrame(tick: number, fork: string | null = null) {
  const places = [
    { id: 1, name: "Home", kind: "residential_district", region_id: 1, x: 0.2, y: 0.2 },
    { id: 2, name: "Works", kind: "workplace", region_id: 1, x: 0.7, y: 0.6 },
  ];
  return {
    run_id: "run-demo", fork_id: fork, tick, semantics_version: 12,
    projection: "world.map", projection_version: 1, policy_version: 1,
    view_key: "public", snapshot_version: `t${tick}`, event_cursor: tick,
    data: {
      regions: [{ id: 1, name: "North", currency_code: "NSD", x: 0.4, y: 0.4 }],
      places,
      presence: ["morning", "business", "evening"].map(slot => {
        const place = slot === "business" ? places[1] : places[0];
        return {
          tick, slot, agent_id: 1, name: `Resident at tick ${tick}`, role: "citizen",
          place_id: place.id, place_name: place.name, place_kind: place.kind,
          x: place.x, y: place.y, source_type: slot === "business" ? "routine_work" : "routine_home",
        };
      }),
    },
  };
}

async function mockCity(page: Page, options: {
  beforeMap?: (tick: number) => Promise<void>;
  wrongTick?: boolean;
  empty?: boolean;
} = {}) {
  const requests: URL[] = [];
  const mutations: string[] = [];
  await page.addInitScript(() => {
    (window as any).__citySockets = 0;
    class QuietSocket extends EventTarget {
      readyState = 1;
      constructor(url: string) {
        super();
        // The Vite development client has its own hot-reload socket.
        if (new URL(url, location.href).pathname === "/ws") (window as any).__citySockets += 1;
      }
      send(_value: string) {}
      close() {}
    }
    Object.defineProperty(window, "WebSocket", { value: QuietSocket });
  });
  await page.route("**/api/**", async route => {
    const request = route.request();
    const url = new URL(request.url());
    requests.push(url);
    if (request.method() !== "GET") mutations.push(request.method());
    if (url.pathname === "/api/v2/world-map") {
      const tick = Number(url.searchParams.get("tick"));
      await options.beforeMap?.(tick);
      const frame = cityFrame(options.wrongTick ? tick + 1 : tick, url.searchParams.get("fork_id"));
      if (options.empty) frame.data.presence = [];
      return route.fulfill({ json: frame });
    }
    if (url.pathname === "/api/conversations") return route.fulfill({ json: [] });
    if (url.pathname === "/api/v2/mode") return route.fulfill({ json: { mode: "local", hosted: false } });
    return route.fulfill({ json: {} });
  });
  return { requests, mutations };
}

async function cityProbe(page: Page) {
  return page.evaluate(() => (window as any).__liveCityProbe?.());
}

test("historical city uses the requested fork/tick and independent playback", async ({ page }) => {
  const evidence = await mockCity(page);
  await page.goto("/runs/run-demo/live-city?tick=3&fork=fork-test&agent=1");
  await expect(page.getByRole("button", { name: "Play recorded day", exact: true })).toBeEnabled();
  expect((await cityProbe(page)).tick).toBe(3);
  await expect(page.getByText("Historical view", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: /Workspaces/ })).toHaveAttribute(
    "href", "/runs/run-demo/overview?tick=3&fork=fork-test&agent=1");
  await page.getByRole("button", { name: "Play recorded day", exact: true }).click();
  await expect.poll(async () => (await cityProbe(page)).clock.dayProgress).toBeGreaterThan(0);
  await page.getByRole("button", { name: "Pause playback", exact: true }).click();
  const paused = (await cityProbe(page)).clock.dayProgress;
  await page.waitForTimeout(150); // Verify the display clock stays stopped across frames.
  expect((await cityProbe(page)).clock.dayProgress).toBe(paused);
  expect((await cityProbe(page)).tick).toBe(3);
  expect(evidence.mutations).toEqual([]);
  expect(evidence.requests.filter(url => url.pathname === "/api/run/status")).toEqual([]);
  expect(evidence.requests.filter(url => url.pathname === "/api/v2/map")).toEqual([]);
  expect(evidence.requests.find(url => url.pathname === "/api/v2/world-map")?.searchParams.get("fork_id")).toBe("fork-test");
  expect(evidence.requests.find(url => url.pathname === "/api/conversations")?.searchParams.get("tick_to")).toBe("3");
  expect(await page.evaluate(() => (window as any).__citySockets)).toBe(0);
});

test("a delayed new tick never borrows old placements or overwrites a newer selection", async ({ page }) => {
  let release: () => void = () => {};
  const holdSix = new Promise<void>(resolve => { release = resolve; });
  await mockCity(page, { beforeMap: tick => tick === 6 ? holdSix : Promise.resolve() });
  await page.goto("/runs/run-demo/live-city?tick=3");
  await expect(page.getByRole("button", { name: "Play recorded day", exact: true })).toBeEnabled();
  await page.evaluate(() => {
    history.pushState(null, "", "/runs/run-demo/live-city?tick=6");
    dispatchEvent(new PopStateEvent("popstate"));
  });
  await expect(page.getByText("Surveying the recorded day", { exact: true })).toBeVisible();
  await expect(page.locator("[data-agent-id='1']")).toHaveCount(0);
  await page.evaluate(() => {
    history.pushState(null, "", "/runs/run-demo/live-city?tick=3");
    dispatchEvent(new PopStateEvent("popstate"));
  });
  release();
  await expect(page.getByRole("button", { name: "Play recorded day", exact: true })).toBeEnabled();
  await expect.poll(async () => (await cityProbe(page))?.tick).toBe(3);
  await expect(page.getByText("Resident at tick 6", { exact: true })).toHaveCount(0);
});

test("wrong projection context fails closed and does not request transcripts", async ({ page }) => {
  const evidence = await mockCity(page, { wrongTick: true });
  await page.goto("/runs/run-demo/live-city?tick=3");
  await expect(page.getByRole("alert")).toContainText("does not match the selected run, fork and tick");
  await expect(page.locator("[data-agent-id='1']")).toHaveCount(0);
  expect(evidence.requests.filter(url => url.pathname === "/api/conversations")).toEqual([]);
});

test("a profile without recorded presence explains the unavailable city", async ({ page }) => {
  await mockCity(page, { empty: true });
  await page.goto("/runs/run-demo/live-city?tick=3");
  await expect(page.getByText("No recorded placements at this tick", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Play recorded day", exact: true })).toBeDisabled();
});
