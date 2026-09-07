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
  semantics?: number;
  publicEvents?: boolean;
  viewKey?: () => string;
  workspaceWriteStatus?: () => number;
  beforeObservationWrite?: () => Promise<void>;
  beforeMap?: (tick: number) => Promise<void>;
  wrongTick?: boolean;
  wrongConversation?: boolean;
  liveTick?: () => number;
  empty?: boolean;
  withheld?: boolean;
  editFrame?: (frame: ReturnType<typeof cityFrame>) => void;
} = {}) {
  const requests: URL[] = [];
  const mutations: string[] = [];
  const observations = new Map<string, { context: Record<string, unknown>; version: number; entries: string[] }>();
  const workspaceWrites: unknown[] = [];
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
    if (request.method() !== "GET" && !url.pathname.startsWith("/api/v2/operator/")) mutations.push(request.method());
    if (url.pathname === "/api/v2/operator/session") return route.fulfill({ json: { owner_id: "local-operator", csrf_token: "test-csrf" } });
    if (url.pathname === "/api/v2/operator/city-observations") {
      const body = request.method() === "PUT" ? request.postDataJSON() : null;
      const context = body?.context ?? JSON.parse(url.searchParams.get("context")!);
      const key = JSON.stringify(context);
      const current = observations.get(key) ?? { context, version: 0, entries: [] };
      if (body) {
        workspaceWrites.push(body);
        await options.beforeObservationWrite?.();
        const status = options.workspaceWriteStatus?.() ?? 200;
        if (status !== 200) return route.fulfill({ status, json: { detail: "Workspace write failed" } });
        if (body.expected_version !== current.version) return route.fulfill({ status: 409, json: { detail: "Version conflict" } });
        expect(request.headers()["x-csrf-token"]).toBe("test-csrf");
        observations.set(key, { context, version: current.version + 1, entries: body.entries });
      }
      return route.fulfill({ json: observations.get(key) ?? current });
    }
    const tick = url.searchParams.get("tick") === "live" ? options.liveTick?.() ?? 3 : Number(url.searchParams.get("tick"));
    const base = cityFrame(tick, url.searchParams.get("fork_id"));
    base.semantics_version = options.semantics ?? base.semantics_version;
    base.view_key = options.viewKey?.() ?? base.view_key;
    if (url.pathname === "/api/v2/world-map") {
      await options.beforeMap?.(tick);
      const frame = cityFrame(options.wrongTick ? tick + 1 : tick, url.searchParams.get("fork_id"));
      frame.semantics_version = options.semantics ?? frame.semantics_version;
      frame.view_key = options.viewKey?.() ?? frame.view_key;
      if (options.empty) frame.data.presence = [];
      if (options.withheld) frame.data.agents.push({ id: 3, name: "Peripheral resident", role: "citizen",
        population_tier: "periphery", region_id: 1, x: 0.2, y: 0.2, alive: true });
      options.editFrame?.(frame);
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
      ...base, projection: "world.snapshot", data: { summary: { tick, status: "paused", phase: "idle" }, events: { items: options.publicEvents
        ? [{ id: tick + 40, tick, kind: "work", actor_type: "agent", actor_id: 1,
          payload: { agent_id: 1, private_marker: "DO-NOT-PERSIST-EVENT-BODY" } }] : [] } },
    } });
    if (url.pathname === "/api/v2/workspaces/world") return route.fulfill({ json: { ...base, projection: "workspace.world" } });
    if (url.pathname === "/api/v2/mode") return route.fulfill({ json: { mode: "local", hosted: false } });
    return route.fulfill({ json: {} });
  });
  return { requests, mutations, observations, workspaceWrites };
}

async function cityProbe(page: Page) {
  return page.evaluate(() => (window as any).__liveCityProbe?.());
}

test("desktop city gives the map at least 65 percent of the visible workspace", async ({ page }) => {
  await mockCity(page);
  const measurements = [];
  for (const viewport of [{ width: 1280, height: 900 }, { width: 1440, height: 1000 }]) {
    await page.setViewportSize(viewport);
    await page.goto("/runs/run-demo/world?tick=3&agent=1");
    await expect(page.getByTestId("city-atlas-viewport")).toBeVisible();
    const measured = await page.evaluate(() => {
      const main = document.querySelector("#workspace-main")!.getBoundingClientRect();
      const map = document.querySelector(".civic-city__map-field")!.getBoundingClientRect();
      const field = document.querySelector(".civic-city__workfield")!.getBoundingClientRect();
      const inspector = document.querySelector(".civic-city__lens")!.getBoundingClientRect();
      const visibleHeight = (rect: DOMRect) => Math.max(0, Math.min(innerHeight, rect.bottom) - Math.max(0, rect.top));
      return { mapFraction: map.width * visibleHeight(map) / (main.width * visibleHeight(main)),
        fieldFraction: map.width / field.width, mainTop: main.top, mapTop: map.top, mapWidth: map.width,
        mainWidth: main.width, mapHeight: map.height, visibleMapHeight: visibleHeight(map),
        inspectorInside: inspector.left >= map.right && inspector.right <= innerWidth && inspector.bottom <= innerHeight };
    });
    measurements.push({ ...viewport, ...measured });
    if (process.env.AE_CAPTURE_CITY_WORKSPACE === "1" && viewport.width === 1440) {
      await page.screenshot({ path: "../docs/research/assets/city-workspace-desktop.png", animations: "disabled" });
    }
  }
  console.log("City area measurements", JSON.stringify(measurements));
  for (const measurement of measurements) {
    expect(measurement.mapFraction).toBeGreaterThanOrEqual(0.65);
    expect(measurement.inspectorInside).toBe(true);
  }
});

test("city toolbar controls remain visible around the desktop breakpoint", async ({ page }) => {
  await mockCity(page);
  for (const width of [390, 768, 980, 1101, 1199, 1200, 1279]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto("/runs/run-demo/world?tick=3&agent=1");
    await expect(page.getByRole("heading", { name: "The living city", exact: true })).toBeVisible();
    const bounds = await page.locator(".civic-city__toolbar").evaluate(toolbar =>
      [...toolbar.querySelectorAll(".civic-city__view-toggle button, .civic-city__statistics > summary, .civic-city__filter-panel > summary, select")]
        .map(control => { const rect = control.getBoundingClientRect(); return {
          label: control.textContent?.slice(0, 35), left: rect.left, right: rect.right,
        }; }));
    for (const control of bounds) {
      expect(control.left, `${width}: ${control.label}`).toBeGreaterThanOrEqual(0);
      expect(control.right, `${width}: ${control.label}`).toBeLessThanOrEqual(width);
    }
  }
});

test("city list paginates public records and searches banks without changing the historical scope", async ({ page }) => {
  const evidence = await mockCity(page, { semantics: 16, editFrame: frame => {
    addSociety(frame);
    for (let id = 3; id <= 100; id++) frame.data.agents.push({ ...frame.data.agents[0], id, name: `Resident ${id}` });
  } });
  await page.goto("/runs/run-demo/world?tick=4&household=7&view=list");
  const list = page.getByRole("region", { name: "Public city object list" });
  await expect(list.getByRole("listitem")).toHaveCount(40);
  await list.getByRole("button", { name: "Next objects", exact: true }).click();
  await expect(list.getByText("Page 2 of 3", { exact: true })).toBeVisible();
  await list.getByRole("searchbox", { name: "Search city objects" }).fill("Person");
  await expect(list.getByRole("listitem")).toHaveCount(40);
  await expect(list.getByText("Tick 4 · 100 matching records", { exact: true })).toBeVisible();
  await list.locator("li button").first().click();
  await expect(page.getByRole("complementary", { name: "Selected city evidence" })
    .getByRole("heading", { name: "Resident 1 at tick 4", exact: true })).toBeVisible();
  await list.getByRole("searchbox", { name: "Search city objects" }).fill("Community Bank");
  await expect(list.getByRole("listitem")).toHaveCount(1);
  await list.getByRole("button", { name: /Community Bank/ }).click();
  await expect(page).toHaveURL(/institution=bank%3A3/);
  const lens = page.getByRole("complementary", { name: "Selected city evidence" });
  await expect(lens.getByRole("heading", { name: "Community Bank", exact: true })).toBeVisible();
  expect(new URL(page.url()).searchParams.get("tick")).toBe("4");
  expect(new URL(page.url()).searchParams.get("view")).toBe("list");
  expect(evidence.mutations).toEqual([]);
});

test("mobile city list, breadcrumbs and saved observations share one accessible inspector", async ({ page }) => {
  await mockCity(page, { semantics: 16, editFrame: addSociety });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/runs/run-demo/world?tick=4&agent=1&view=list");
  const list = page.getByRole("region", { name: "Public city object list" });
  const person = list.getByRole("button", { name: /Resident 2 at tick 4/ });
  await person.focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/agent=2/);
  await list.getByRole("button", { name: "Open selected evidence", exact: true }).click();
  const lens = page.getByRole("complementary", { name: "Selected city evidence" });
  const breadcrumb = lens.getByRole("navigation", { name: "Selected city object" });
  await expect(breadcrumb).toContainText("Person #2");
  await breadcrumb.getByRole("button", { name: "Household #7", exact: true }).click();
  await expect(lens.getByRole("heading", { name: "Household #7", exact: true })).toBeVisible();
  await expect(page.getByRole("complementary", { name: "Selected city evidence" })).toHaveCount(1);
  const history = page.getByRole("region", { name: "City observation history" });
  await history.getByRole("button", { name: "Save observation", exact: true }).click();
  await expect(history.locator("summary")).toHaveText("Saved observations (1)");
  await page.reload();
  await expect(page).toHaveURL(/view=list/);
  await expect(history.locator("summary")).toHaveText("Saved observations (1)");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  if (process.env.AE_CAPTURE_CITY_WORKSPACE === "1") {
    await page.setViewportSize({ width: 390, height: 1100 });
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: "../docs/research/assets/city-workspace-mobile-list.png", animations: "disabled" });
  }
});

test("event bookmarks restore a historical selection and camera without storing evidence bodies", async ({ page }) => {
  const evidence = await mockCity(page, { publicEvents: true });
  await page.goto("/runs/run-demo/world?tick=3&agent=1&view=diorama&camera=40,60,4&population=all&q=tick");
  const history = page.getByRole("region", { name: "City observation history" });
  await history.getByRole("button", { name: "Save event bookmark" }).click();
  await expect(history.locator("summary")).toHaveText("Saved observations (1)");
  const stored = [...evidence.observations.values()];
  expect(stored).toHaveLength(1);
  expect(JSON.stringify(stored)).not.toContain("DO-NOT-PERSIST");
  expect(JSON.stringify(stored)).not.toContain("Resident");
  await page.goto("/runs/run-demo/world?tick=4&agent=2");
  await history.locator("summary").click();
  await history.getByRole("button", { name: "Event #43 · Tick 3 · Person #1", exact: true }).click();
  await expect(page).toHaveURL(/tick=3/);
  for (const [key, value] of Object.entries({ agent: "1", event: "43", view: "diorama", camera: "40,60,4", population: "all", q: "tick" })) {
    expect(new URL(page.url()).searchParams.get(key)).toBe(value);
  }
  await page.reload();
  await expect(history.locator("summary")).toHaveText("Saved observations (1)");
  await history.locator("summary").click();
  await history.getByRole("button", { name: "Remove Event #43 · Tick 3 · Person #1", exact: true }).click();
  await expect(history.locator("summary")).toHaveText("Saved observations (0)");
  expect(evidence.mutations).toEqual([]);
  expect(evidence.workspaceWrites).toHaveLength(2);
  expect(evidence.requests.filter(url => url.pathname === "/api/llm/runtime" || url.pathname === "/api/status")).toEqual([]);
});

test("live bookmarks freeze the displayed tick and do not cross visibility or fork contexts", async ({ page }) => {
  let viewKey = "public";
  const evidence = await mockCity(page, { viewKey: () => viewKey });
  await page.goto("/runs/run-demo/world?agent=1");
  const history = page.getByRole("region", { name: "City observation history" });
  await history.getByRole("button", { name: "Save observation", exact: true }).click();
  await expect(history.locator("summary")).toHaveText("Saved observations (1)");
  const saved = [...evidence.observations.values()][0];
  expect(new URLSearchParams(saved.entries[0]).get("tick")).toBe("3");
  await page.goto("/runs/run-demo/world?tick=2&fork=child&agent=1");
  await expect(history.locator("summary")).toHaveText("Saved observations (0)");
  viewKey = "changed-visibility";
  await page.goto("/runs/run-demo/world?tick=2&agent=1");
  await expect(history.locator("summary")).toHaveText("Saved observations (0)");
  viewKey = "public";
  await page.reload();
  await expect(history.locator("summary")).toHaveText("Saved observations (1)");
});

test("bookmark failures and concurrent edits stay visible until explicit reload", async ({ page }) => {
  let status = 500;
  const evidence = await mockCity(page, { workspaceWriteStatus: () => status });
  await page.goto("/runs/run-demo/world?tick=3&agent=1");
  const history = page.getByRole("region", { name: "City observation history" });
  await history.getByRole("button", { name: "Save observation", exact: true }).click();
  await expect(history.getByRole("alert")).toContainText("could not be saved");
  await expect(history.locator("summary")).toHaveText("Saved observations (0)");
  status = 200;
  await history.getByRole("button", { name: "Save observation", exact: true }).click();
  await expect(history.locator("summary")).toHaveText("Saved observations (1)");
  const record = [...evidence.observations.values()][0];
  record.version += 1;
  record.entries = ["tick=2&agent=2"];
  await history.getByRole("button", { name: "Save observation", exact: true }).click();
  await expect(history.getByRole("alert")).toContainText("Reload observations before saving");
  await expect(history.getByRole("button", { name: "Save observation", exact: true })).toBeDisabled();
  expect(record.entries).toEqual(["tick=2&agent=2"]);
  await history.getByRole("button", { name: "Reload observations", exact: true }).click();
  await expect(history.getByRole("alert")).toHaveCount(0);
  await history.locator("summary").click();
  await expect(history.getByRole("button", { name: "Tick 2 · Person #2", exact: true })).toBeVisible();
  expect(evidence.mutations).toEqual([]);
});

test("an observation save response cannot populate a newly selected fork", async ({ page }) => {
  let release!: () => void;
  const pending = new Promise<void>(resolve => { release = resolve; });
  const evidence = await mockCity(page, { beforeObservationWrite: () => pending });
  await page.goto("/runs/run-demo/world?tick=3&agent=1");
  const history = page.getByRole("region", { name: "City observation history" });
  await history.getByRole("button", { name: "Save observation", exact: true }).click();
  await expect.poll(() => evidence.workspaceWrites.length).toBe(1);
  await page.goto("/runs/run-demo/world?tick=2&fork=child&agent=2");
  release();
  await expect(history.getByRole("button", { name: "Save observation", exact: true })).toBeEnabled();
  await expect(history.locator("summary")).toHaveText("Saved observations (0)");
  expect(evidence.mutations).toEqual([]);
});

function addSociety(frame: ReturnType<typeof cityFrame>) {
  const tick = frame.tick;
  const members = [{ agent_id: 1, name: "Resident 1", age_years: 31, age_band: "adult",
    role: "adult", joined_tick: 0, origin: "genesis", origin_tick: 0, legacy_dependents: 2, guardian_agent_id: null },
  { agent_id: 2, name: "Resident 2", age_years: 0, age_band: "child",
    role: "dependent", joined_tick: 2, origin: "birth", origin_tick: 2, legacy_dependents: 0, guardian_agent_id: 1 }];
  Object.assign(frame.data, {
    households: { available: true, source: "recorded_household_membership", tick, visibility: "core_members_only",
      items: tick >= 2 ? [{ id: 7, name: "Household #7", formed_tick: 0, policy: "guardian_basic_needs_v1", members,
        child_needs: tick === 4 ? [{ child_agent_id: 2, currency_code: "USD", goods_sector: "food",
          required_units: 2, purchased_units: 1, spent_cents: 90, care_required_minutes: 120, care_status: "time_allocation_pending" }] : [] }] : [] },
    institutions: { available: true, source: "public_bank_status", tick, visibility: "public_status_only",
      items: [{ id: "bank:3", bank_id: 3, name: "Community Bank", kind: "bank", currency_code: "USD", status: tick >= 5 ? "failed" : "open" }] },
  });
}

test("household and bank lenses preserve selection across renderers, history and member inspection", async ({ page }) => {
  const evidence = await mockCity(page, { editFrame: addSociety, semantics: 16 });
  await page.goto("/runs/run-demo/world?tick=4&fork=child&agent=1&camera=40,60,4");
  const lens = page.getByRole("complementary", { name: "Selected city evidence" });
  await lens.getByRole("button", { name: "Inspect household", exact: true }).click();
  await expect(page).toHaveURL(/household=7/);
  await expect(lens.getByRole("heading", { name: "Household #7", exact: true })).toBeVisible();
  await expect(lens.getByText("1 / 2 food units purchased", { exact: true })).toBeVisible();
  await expect(lens.getByText("120 care minutes required · Time Allocation Pending", { exact: true })).toBeVisible();
  for (const view of ["2.5D Diorama", "Recorded day", "Atlas"]) {
    await page.getByRole("button", { name: view, exact: true }).click();
    await expect(lens.getByRole("heading", { name: "Household #7", exact: true })).toBeVisible();
    expect(new URL(page.url()).searchParams.get("household")).toBe("7");
    expect(new URL(page.url()).searchParams.get("fork")).toBe("child");
  }
  await page.getByRole("combobox", { name: "Keyboard explorer" }).selectOption("institution:bank:3");
  await expect(lens.getByRole("heading", { name: "Community Bank", exact: true })).toBeVisible();
  await expect(lens.getByText("Open", { exact: true })).toBeVisible();
  expect(new URL(page.url()).searchParams.has("household")).toBe(false);
  await page.goBack();
  await expect(lens.getByRole("heading", { name: "Household #7", exact: true })).toBeVisible();
  await page.reload();
  await expect(lens.getByRole("heading", { name: "Household #7", exact: true })).toBeVisible();
  await lens.getByRole("button", { name: "Inspect Resident 2", exact: true }).click();
  expect(new URL(page.url()).searchParams.get("agent")).toBe("2");
  expect(new URL(page.url()).searchParams.has("household")).toBe(false);
  await expect(lens.getByRole("heading", { name: "Resident 2 at tick 4", exact: true })).toBeVisible();
  await lens.getByRole("button", { name: "Inspect household", exact: true }).click();
  expect(evidence.mutations).toEqual([]);
  expect(evidence.requests.filter(url => url.pathname === "/api/llm/runtime" || url.pathname === "/api/status")).toEqual([]);
});

test("unavailable household selection is retained at older and mismatched frames", async ({ page }) => {
  await mockCity(page, { semantics: 16, editFrame: frame => {
    addSociety(frame);
    if (frame.tick === 3) (frame.data as any).households.tick = 4;
  } });
  const lens = page.getByRole("complementary", { name: "Selected city evidence" });
  for (const tick of [1, 3]) {
    await page.goto(`/runs/run-demo/world?tick=${tick}&household=7`);
    await expect(lens.getByRole("region", { name: "Unavailable city record" })).toBeVisible();
    await expect(page).toHaveURL(/household=7/);
    await expect(lens.getByRole("button", { name: "Inspect Resident 2" })).toHaveCount(0);
    expect(new URL(page.url()).searchParams.has("agent")).toBe(false);
  }
  await page.goto("/runs/run-demo/world?tick=5&institution=bank:3");
  await expect(lens.getByText("Failed", { exact: true })).toBeVisible();
  await page.goto("/runs/run-demo/world?tick=2&household=7");
  await expect(lens.getByText(/No child-needs record is available/)).toBeVisible();
  await expect(lens.getByText("90 USD cents spent", { exact: true })).toHaveCount(0);
});

test("household evidence fits mobile and retains keyboard member navigation", async ({ page }) => {
  await mockCity(page, { editFrame: addSociety, semantics: 16 });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/runs/run-demo/world?tick=4&household=7");
  const lens = page.getByRole("complementary", { name: "Selected city evidence" });
  await page.getByRole("button", { name: /Household #7.*Open evidence/ }).click();
  await expect(lens.getByRole("heading", { name: "Household #7", exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  const member = lens.getByRole("button", { name: "Inspect Resident 2", exact: true });
  await member.focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/agent=2/);
  await lens.getByRole("button", { name: "Inspect household", exact: true }).click();
  if (process.env.AE_CAPTURE_SOCIETY_UI === "1") {
    await page.setViewportSize({ width: 390, height: 1800 });
    await lens.evaluate(node => node.scrollIntoView({ block: "center" }));
    await lens.screenshot({ path: "../docs/research/assets/city-household-mobile.png", animations: "disabled" });
    await page.setViewportSize({ width: 1440, height: 1400 });
    await page.locator(".civic-city__workfield").evaluate(node => node.scrollIntoView({ block: "center" }));
    await page.locator(".civic-city__workfield").screenshot({ path: "../docs/research/assets/city-household-desktop.png", animations: "disabled" });
  }
});

test("Atlas camera centers selections and restores keyboard pan and zoom through history", async ({ page }) => {
  const evidence = await mockCity(page);
  await page.goto("/runs/run-demo/world?tick=3&agent=1");
  const atlas = page.getByTestId("city-atlas-viewport");
  await expect(atlas).toHaveAttribute("data-camera", "50,50,3.05");
  await page.getByRole("button", { name: "Focus selection", exact: true }).click();
  await expect(atlas).toHaveAttribute("data-camera", "20,20,3.05");
  const centerError = await page.locator(".civic-city__agent[aria-pressed='true']").evaluate(node => {
    const field = node.closest(".city-atlas-viewport")!.getBoundingClientRect();
    const mark = node.getBoundingClientRect();
    return Math.hypot(mark.x + mark.width / 2 - field.x - field.width / 2,
      mark.y + mark.height / 2 - field.y - field.height / 2);
  });
  expect(centerError).toBeLessThan(1);
  const pan = page.getByRole("button", { name: "Pan city right", exact: true });
  await pan.focus(); await page.keyboard.press("Enter");
  await expect(atlas).toHaveAttribute("data-camera", "25,20,3.05");
  await page.getByRole("button", { name: "Zoom into city", exact: true }).click();
  await expect(atlas).toHaveAttribute("data-camera", "25,20,3.4");
  expect((await page.locator(".civic-city__agent[aria-pressed='true']").boundingBox())!.width).toBeLessThan(33);
  await page.goBack();
  await expect(atlas).toHaveAttribute("data-camera", "25,20,3.05");
  await page.reload();
  await expect(atlas).toHaveAttribute("data-camera", "25,20,3.05");
  expect(evidence.mutations).toEqual([]);
});

test("an Atlas background drag pans without changing selection and is one history action", async ({ page }) => {
  await mockCity(page);
  await page.goto("/runs/run-demo/world?tick=3&agent=1");
  const atlas = page.getByTestId("city-atlas-viewport");
  await expect(atlas).toHaveAttribute("data-camera", "50,50,3.05");
  await atlas.scrollIntoViewIfNeeded();
  const box = (await atlas.boundingBox())!;
  await page.mouse.move(box.x + box.width * .45, box.y + box.height * .5);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * .55, box.y + box.height * .55, { steps: 6 });
  await page.mouse.up();
  await expect.poll(async () => Number((await atlas.getAttribute("data-camera"))!.split(",")[0])).toBeCloseTo(40, 1);
  const camera = (await atlas.getAttribute("data-camera"))!.split(",").map(Number);
  expect(camera[0]).toBeCloseTo(40, 1); expect(camera[1]).toBeCloseTo(45, 1);
  await expect(page.getByLabel("Keyboard explorer")).toHaveValue("agent:1");
  await page.goBack();
  await expect(atlas).toHaveAttribute("data-camera", "50,50,3.05");
});

test("Atlas construction labels appear on selection and keyboard focus without covering the city", async ({ page }) => {
  await mockCity(page, { editFrame: frame => {
    (frame.data as any).construction_projects = [1, 2].map(id => ({ project_id: `site-${id}`, name: `Building ${id}`,
      x: .3 + id * .1, y: .4, status: "building", requirements: { work_units: 10 }, contributed: { work_units: 3 } }));
  } });
  await page.goto("/runs/run-demo/world?tick=3&agent=1&camera=40,40,4");
  const first = page.locator(".civic-city__construction").first();
  const second = page.locator(".civic-city__construction").nth(1);
  await expect(first.locator("span")).toBeHidden();
  await page.getByLabel("Keyboard explorer").selectOption("project:site-1");
  await expect(first.locator("span")).toBeVisible();
  await expect(second.locator("span")).toBeHidden();
  await second.focus();
  await expect(second.locator("span")).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(page.getByLabel("Keyboard explorer")).toHaveValue("project:site-2");
});

test("follow preserves identity across filters and ticks, pausing for absence, death or withheld coordinates", async ({ page }) => {
  const evidence = await mockCity(page, { editFrame: frame => {
    if (frame.tick === 4) frame.data.agents = frame.data.agents.filter(agent => agent.id !== 1);
    if ([4, 6].includes(frame.tick)) frame.data.presence = frame.data.presence.filter(row => row.agent_id !== 1);
    if (frame.tick === 5) frame.data.agents[0].alive = false;
    if (frame.tick === 6) { frame.data.agents[0].x = null as any; frame.data.agents[0].y = null as any; }
    if (frame.tick === 7) { frame.data.agents[0].x = .65; frame.data.agents[0].y = .45; }
  } });
  await page.goto("/runs/run-demo/world?tick=3&agent=1");
  await page.getByRole("button", { name: "Follow person", exact: true }).click();
  await expect(page).toHaveURL(/follow=1/);
  await expect(page.getByTestId("city-atlas-viewport")).toHaveAttribute("data-camera", "20,20,3.05");
  await page.getByText("Layers and agent filters", { exact: true }).click();
  await page.getByRole("searchbox", { name: "Find an agent" }).fill("Resident 2");
  await expect(page.locator(".city-follow")).toContainText("hidden by the current filters");
  await expect(page.getByLabel("Keyboard explorer")).toHaveValue("");
  await expect(page).toHaveURL(/agent=1/);
  await expect(page).toHaveURL(/follow=1/);
  await page.getByRole("searchbox", { name: "Find an agent" }).fill("");
  await expect(page.getByTestId("city-atlas-viewport")).toHaveAttribute("data-camera", "20,20,3.05");
  for (const [tick, message] of [[4, "absent"], [5, "no longer alive"], [6, "no public position"]] as const) {
    await page.evaluate(tick => {
      history.pushState(null, "", `/runs/run-demo/world?tick=${tick}&agent=1&follow=1`);
      dispatchEvent(new PopStateEvent("popstate"));
    }, tick);
    await expect(page.locator(".city-follow")).toContainText(message);
    await expect(page).toHaveURL(/agent=1&follow=1/);
  }
  await page.goto("/runs/run-demo/world?tick=7&agent=1&follow=1");
  await expect(page.getByTestId("city-atlas-viewport")).toHaveAttribute("data-camera", "65,45,3.05");
  expect(evidence.mutations).toEqual([]);
  expect(await page.evaluate(() => (window as any).__citySockets)).toBe(0);
});

test("follow survives renderer switches and reload; zoom preserves it and selecting another object stops it", async ({ page }) => {
  await mockCity(page);
  await page.goto("/runs/run-demo/world?tick=3&agent=1&follow=1");
  await page.getByRole("button", { name: "Zoom into city", exact: true }).click();
  await expect(page).toHaveURL(/follow=1/);
  await page.getByRole("button", { name: "2.5D Diorama", exact: true }).click();
  await expect(page.getByTestId("civic-diorama")).toHaveAttribute("data-camera", "20,20,3.4");
  await page.getByTestId("civic-diorama").scrollIntoViewIfNeeded();
  const field = (await page.getByTestId("civic-diorama").boundingBox())!;
  await page.mouse.move(field.x + field.width * .4, field.y + field.height * .3);
  await page.mouse.wheel(0, -80);
  await expect.poll(async () => Number((await page.getByTestId("civic-diorama").getAttribute("data-camera"))!.split(",")[2])).toBeGreaterThan(3.4);
  await expect(page).toHaveURL(/follow=1/);
  await page.getByRole("button", { name: "Recorded day", exact: true }).click();
  await expect(page.locator(".recorded-day__follow-status")).toContainText("Following person #1");
  await page.reload();
  await expect(page.locator(".recorded-day__follow-status")).toContainText("Following person #1");
  await page.getByLabel("Keyboard explorer").selectOption("firm:1");
  expect(new URL(page.url()).searchParams.has("follow")).toBe(false);
  await expect(page.getByRole("button", { name: "Follow person", exact: true })).toBeDisabled();
  await page.goBack();
  await expect(page.getByRole("button", { name: "Stop following", exact: true })).toBeEnabled();
});

test("recorded follow centers the moving chip without altering placement geometry or economic time", async ({ page }) => {
  const evidence = await mockCity(page);
  await page.goto("/runs/run-demo/world?tick=3&view=recorded&agent=1&follow=1");
  await expect(page.getByRole("button", { name: "Play recorded day", exact: true })).toBeEnabled();
  const first = await cityProbe(page);
  const originalHistoryLength = await page.evaluate(() => history.length);
  const firstPerson = first.chips.find((chip: any) => chip.id === 1);
  expect(firstPerson.screenX).toBeCloseTo(first.viewport.width / 2, 3);
  expect(firstPerson.screenY).toBeCloseTo(first.viewport.height / 2, 3);
  await page.getByLabel("Playback speed").selectOption("4");
  await page.getByRole("button", { name: "Play recorded day", exact: true }).click();
  await expect.poll(async () => (await cityProbe(page)).chips.find((chip: any) => chip.id === 1).x).toBeGreaterThan(firstPerson.x + 15);
  await page.getByRole("button", { name: "Pause playback", exact: true }).click();
  const moved = await cityProbe(page);
  const person = moved.chips.find((chip: any) => chip.id === 1);
  expect(person.screenX).toBeCloseTo(moved.viewport.width / 2, 3);
  expect(person.screenY).toBeCloseTo(moved.viewport.height / 2, 3);
  expect(person.anchors).toEqual(firstPerson.anchors);
  expect(moved.tick).toBe(3);
  expect(await page.evaluate(() => history.length)).toBe(originalHistoryLength);
  const geometry = await page.locator(".live-city [data-agent-id='1']").evaluate(node => {
    const stage = node.closest(".live-city")!.getBoundingClientRect();
    const chip = node.getBoundingClientRect();
    return { x: chip.x + chip.width / 2 - stage.x, y: chip.y + chip.height / 2 - stage.y };
  });
  expect(geometry.x).toBeCloseTo(person.screenX, 0);
  expect(geometry.y).toBeCloseTo(person.screenY, 0);
  await page.getByRole("button", { name: "Stop following", exact: true }).click();
  await expect.poll(async () => (await cityProbe(page)).viewport.trackingId).toBe(null);
  const stopped = await cityProbe(page);
  expect(stopped.viewport.trackingId).toBe(null);
  expect(stopped.chips.find((chip: any) => chip.id === 1).screenX).toBeCloseTo(person.screenX, 0);
  expect(evidence.mutations).toEqual([]);
});

test("recorded follow pauses for a withheld person and never substitutes an animated neighbor", async ({ page }) => {
  await mockCity(page, { withheld: true });
  await page.goto("/runs/run-demo/world?tick=3&view=recorded&agent=3&follow=3&population=all");
  await expect(page.locator(".recorded-day__follow-status")).toContainText("Follow paused for person #3");
  await expect(page.getByLabel("Keyboard explorer")).toHaveValue("agent:3");
  await expect.poll(async () => (await cityProbe(page))?.viewport.trackingId).toBe(null);
  await expect(page.locator(".live-city [data-agent-id='3']")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Focus selection", exact: true })).toBeDisabled();
});

test("camera controls and follow remain reachable on a reduced-motion phone without horizontal overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await mockCity(page);
  await page.goto("/runs/run-demo/world?tick=3&agent=1");
  const follow = page.getByRole("button", { name: "Follow person", exact: true });
  await follow.focus(); await page.keyboard.press("Enter");
  await expect(page.getByRole("button", { name: "Stop following", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Pan city right", exact: true }).click();
  expect(new URL(page.url()).searchParams.has("follow")).toBe(false);
  await page.getByRole("button", { name: "Recorded day", exact: true }).click();
  await page.getByRole("button", { name: "Follow person", exact: true }).click();
  await expect(page.locator(".recorded-day__follow-status")).toContainText("Following person #1");
  for (const width of [390, 768]) {
    await page.setViewportSize({ width, height: 844 });
    await expect(page.getByRole("button", { name: "Pan city left", exact: true })).toBeEnabled();
    expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(1);
  }
});

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
  // Keep the gap between browser navigation and React's commit observable.
  const timing = await page.context().newCDPSession(page);
  await timing.send("Emulation.setCPUThrottlingRate", { rate: 4 });
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
  await expect(page).toHaveURL(/tick=3(?:&|$)/);
  await expect(page.getByLabel("Keyboard explorer")).toHaveValue("agent:1");
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
