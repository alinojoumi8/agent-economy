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
      enabled: true,
      agents: [1, 2].map(id => ({ id, name: `Resident ${id} at tick ${tick}`, role: "citizen",
        population_tier: "core", region_id: 1, x: 0.2, y: 0.2, alive: true })),
      organizations: [{ id: 1, name: "Recorded business", sector: "goods", region_id: 1, place_id: 2, x: 0.7, y: 0.6 }],
      places,
      presence: [1, 2].flatMap(id => ["morning", "business", "evening"].map(slot => {
        const place = slot === "business" ? places[1] : places[0];
        return {
          tick, slot, agent_id: id, name: `Resident ${id} at tick ${tick}`, role: "citizen",
          place_id: place.id, place_name: place.name, place_kind: place.kind,
          x: place.x, y: place.y, source_type: slot === "business" ? "routine_work" : "routine_home",
        };
      })),
    },
  };
}

async function mockCity(page: Page, options: {
  beforeMap?: (tick: number) => Promise<void>;
  wrongTick?: boolean;
  wrongConversation?: boolean;
  liveTick?: () => number;
  empty?: boolean;
  withheld?: boolean;
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
    const tick = url.searchParams.get("tick") === "live" ? options.liveTick?.() ?? 3 : Number(url.searchParams.get("tick"));
    const base = cityFrame(tick, url.searchParams.get("fork_id"));
    if (url.pathname === "/api/v2/world-map") {
      await options.beforeMap?.(tick);
      const frame = cityFrame(options.wrongTick ? tick + 1 : tick, url.searchParams.get("fork_id"));
      if (options.empty) frame.data.presence = [];
      if (options.withheld) frame.data.agents.push({ id: 3, name: "Peripheral resident", role: "citizen",
        population_tier: "periphery", region_id: 1, x: 0.2, y: 0.2, alive: true });
      return route.fulfill({ json: frame });
    }
    if (url.pathname === "/api/v2/city/conversations") return route.fulfill({ json: {
      ...base, fork_id: options.wrongConversation ? "foreign" : base.fork_id, projection: "city.conversations",
      data: { tick, source: "recorded_small_talk", items: [{ id: 1, tick, participants: [1, 2],
        topic: "This day's recorded topic", messages: [{ agent_id: 1, seq: 0, text: "Words from this day" }] }],
        has_more: false, content_truncated: false },
    } });
    if (url.pathname === "/api/v2/civic/summary") return route.fulfill({ json: {
      ...base, projection: "civic.summary", data: { tick, enabled: true },
    } });
    if (url.pathname === "/api/v2/snapshot") return route.fulfill({ json: {
      ...base, projection: "world.snapshot", data: { summary: { tick, status: "paused", phase: "idle" }, events: { items: [] } },
    } });
    if (url.pathname === "/api/v2/workspaces/world") return route.fulfill({ json: { ...base, projection: "workspace.world" } });
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
  await expect(page).toHaveURL(/\/world\?.*view=recorded/);
  await expect(page.getByRole("navigation", { name: "Civic Atlas workspaces" }).getByRole("link", { name: "City", exact: true })).toHaveAttribute("aria-current", "page");
  await expect(page.getByLabel("Keyboard explorer")).toHaveValue("agent:1");
  await page.getByLabel("Playback speed").selectOption("4");
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
  expect(evidence.requests.find(url => url.pathname === "/api/v2/city/conversations")?.searchParams.get("tick")).toBe("3");
  expect(await page.evaluate(() => (window as any).__citySockets)).toBe(0);
});

test("a delayed new tick never borrows old placements or overwrites a newer selection", async ({ page }) => {
  let release: () => void = () => {};
  const holdSix = new Promise<void>(resolve => { release = resolve; });
  await mockCity(page, { beforeMap: tick => tick === 6 ? holdSix : Promise.resolve() });
  await page.goto("/runs/run-demo/world?tick=3&view=recorded");
  await expect(page.getByRole("button", { name: "Play recorded day", exact: true })).toBeEnabled();
  await page.evaluate(() => {
    history.pushState(null, "", "/runs/run-demo/world?tick=6&view=recorded");
    dispatchEvent(new PopStateEvent("popstate"));
  });
  await expect(page.getByText("Surveying the recorded day", { exact: true })).toBeVisible();
  await expect(page.locator(".live-city [data-agent-id='1']")).toHaveCount(0);
  await page.evaluate(() => {
    history.pushState(null, "", "/runs/run-demo/world?tick=3&view=recorded");
    dispatchEvent(new PopStateEvent("popstate"));
  });
  release();
  await expect(page.getByRole("button", { name: "Play recorded day", exact: true })).toBeEnabled();
  await expect.poll(async () => (await cityProbe(page))?.tick).toBe(3);
  await expect(page.getByText("Resident 1 at tick 6", { exact: true })).toHaveCount(0);
});

test("wrong projection context fails closed and does not request transcripts", async ({ page }) => {
  const evidence = await mockCity(page, { wrongTick: true });
  await page.goto("/runs/run-demo/world?tick=3&view=recorded");
  await expect(page.getByRole("alert").first()).toContainText("does not match the selected run, fork, tick or projection");
  await expect(page.locator(".live-city [data-agent-id='1']")).toHaveCount(0);
  expect(evidence.requests.filter(url => url.pathname === "/api/v2/city/conversations")).toEqual([]);
});

test("a profile without recorded presence explains the unavailable city", async ({ page }) => {
  await mockCity(page, { empty: true });
  await page.goto("/runs/run-demo/world?tick=3&view=recorded");
  await expect(page.getByText("No recorded placements at this tick", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Play recorded day", exact: true })).toBeDisabled();
});

test("placement coverage never turns a visible roster into invented daily journeys", async ({ page }) => {
  await mockCity(page, { withheld: true });
  await page.goto("/runs/run-demo/world?tick=3&view=recorded&population=all");
  await expect(page.locator(".recorded-day__coverage")).toContainText("2 of 3");
  await expect(page.locator(".recorded-day__coverage")).toContainText("1 unavailable or withheld");
  await page.getByLabel("Keyboard explorer").selectOption("agent:3");
  await expect(page.getByRole("complementary", { name: "Selected city evidence" })).toContainText("Peripheral resident");
  await expect(page.locator(".live-city [data-agent-id='3']")).toHaveCount(0);
});


test("recorded day shares selection, filters and the business lens across renderers", async ({ page }) => {
  const evidence = await mockCity(page);
  await page.goto("/runs/run-demo/world?tick=3&view=recorded&population=all");
  const explorer = page.getByLabel("Keyboard explorer");
  await explorer.selectOption("agent:2");
  await expect(page.getByRole("complementary", { name: "Selected city evidence" })).toContainText("Resident 2 at tick 3");
  await page.getByRole("button", { name: "Atlas", exact: true }).click();
  await expect(explorer).toHaveValue("agent:2");
  await page.getByRole("button", { name: "Recorded day", exact: true }).click();
  await expect(explorer).toHaveValue("agent:2");
  await expect(page.getByRole("button", { name: "Play recorded day", exact: true })).toBeEnabled();
  await explorer.selectOption("firm:1");
  await expect(page.getByRole("link", { name: /Inspect goods and equity prices/ })).toHaveAttribute("href", /price_firm=1/);
  await page.getByText("Layers and agent filters", { exact: true }).click();
  await page.getByRole("searchbox", { name: "Find an agent" }).fill("Resident 1");
  await expect(page.locator(".live-city .live-city__chip[data-agent-id='2']")).toHaveCount(0);
  await expect(page.locator(".live-city .live-city__chip[data-agent-id='1']")).toHaveCount(1);
  expect(evidence.requests.filter(url => ["/api/llm/runtime", "/api/run/status", "/api/conversations"].includes(url.pathname))).toEqual([]);
  expect(evidence.mutations).toEqual([]);
});

test("foreign transcripts are withheld while valid recorded placements remain usable", async ({ page }) => {
  const evidence = await mockCity(page, { wrongConversation: true });
  await page.goto("/runs/run-demo/world?tick=3&view=recorded");
  await expect(page.getByText(/Recorded conversations unavailable:/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Play recorded day", exact: true })).toBeEnabled();
  await expect(page.getByText("Words from this day", { exact: true })).toHaveCount(0);
  expect(evidence.mutations).toEqual([]);
});

test("a new live frame pauses and resets playback; pinning keeps the recorded day", async ({ page }) => {
  let liveTick = 3;
  const evidence = await mockCity(page, { liveTick: () => liveTick });
  await page.goto("/runs/run-demo/world?view=recorded");
  await page.getByRole("button", { name: "Play recorded day", exact: true }).click();
  await expect.poll(async () => (await cityProbe(page))?.clock.dayProgress).toBeGreaterThan(0);
  liveTick = 4;
  await expect.poll(async () => (await cityProbe(page))?.tick, { timeout: 8000 }).toBe(4);
  await expect(page.getByRole("button", { name: "Play recorded day", exact: true })).toBeEnabled();
  expect((await cityProbe(page)).clock.dayProgress).toBe(0);
  await page.getByRole("button", { name: "Pin this day", exact: true }).click();
  await expect(page).toHaveURL(/tick=4/);
  liveTick = 5;
  await page.getByRole("button", { name: "Play recorded day", exact: true }).click();
  await page.getByRole("button", { name: "Restart playback", exact: true }).click();
  expect((await cityProbe(page)).clock.dayProgress).toBe(0);
  expect((await cityProbe(page)).tick).toBe(4);
  expect(evidence.requests.filter(url => ["/api/llm/runtime", "/api/run/status"].includes(url.pathname))).toEqual([]);
  expect(evidence.mutations).toEqual([]);
});

test("mobile recorded playback keeps geography and keyboard evidence usable", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await mockCity(page);
  await page.goto("/runs/run-demo/world?tick=3&view=recorded");
  await page.getByLabel("Keyboard explorer").selectOption("agent:2");
  await page.getByRole("button", { name: "Open selected evidence", exact: true }).click();
  await expect(page.getByRole("complementary", { name: "Selected city evidence" })).toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBe(0);
  await page.getByText("How this day is drawn", { exact: true }).click();
  await expect(page.getByText("Reduced motion: chips step between placements without gliding.")).toBeVisible();
});
