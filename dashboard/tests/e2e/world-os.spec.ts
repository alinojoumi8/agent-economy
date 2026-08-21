import { expect, test, type Page } from "@playwright/test";

const baseEnvelope = {
  run_id: "run-demo", fork_id: null, tick: 6, semantics_version: 8,
  projection_version: 1, policy_version: 1, view_key: "view-demo",
  snapshot_version: "s8-p1-t6-e2-demo", event_cursor: 2,
};

const livingConstructionProject = {
  project_id: "construction:41",
  kind: "construction",
  title: "Harbor Works Studio",
  owner_agent_id: 1,
  stage: "frame",
  status: "active",
  started_tick: 1,
  updated_tick: 4,
  completed_tick: null,
  milestone_count: 4,
  source: "committed",
  evidence_refs: [
    { kind: "construction_project", id: 41, tick: 1 },
    { kind: "construction_contribution", id: 8, tick: 4 },
  ],
  organization: { id: 3, name: "Atlas Works" },
  place: null,
  region: { id: 2, name: "Harbor Ward" },
  metrics: {
    target_place_type: "workplace",
    required_funding_cents: 60000,
    contributed_funding_cents: 60000,
    required_work_units: 8,
    contributed_work_units: 3,
    aggregate_count: 1,
  },
  privacy: "exact",
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
          this.dispatchEvent(new MessageEvent("message", { data: JSON.stringify({
            type: "projection_delta", domain: "cursor_advance",
            run_id: "run-demo", fork_id: null, tick: 5,
            semantics_version: 8, projection_version: 1, policy_version: 1,
            view_key: "view-demo", previous_event_cursor: 0, event_cursor: 1,
            payload: [],
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
    if (path === "/api/v2/mode") return route.fulfill({ json: {
      mode: "local", hosted: false, api_base: "/api/v2",
      navigation: {
        run_id: "run-demo", world_slug: "test-world", observatory: "/",
        world_os: "/runs/run-demo/overview", commons: "/runs/run-demo/commons",
        join: "/join/test-world", my_agents: "/my-agents",
      },
    } });
    if (path === "/api/v2/snapshot") return route.fulfill({ json: {
      ...baseEnvelope, projection: "world.snapshot", data: {
        summary: { status: "paused", phase: "FINALIZE", active_tick: null, agents_alive: 3, active_firms: 1, ledger_balance: 0 },
        communications: { total: 1, published: 0, private_total: 1 },
        alerts: [{ id: 9, tick: 6, phase: "MARKET", kind: "goods_sale", importance: 2, payload: { buyer_id: 1, qty: 5 } }],
        events: { items: [{ id: 9, tick: 6, phase: "MARKET", kind: "goods_sale", importance: 2, payload: { buyer_id: 1, qty: 5 } }] },
      },
    } });
    if (path === "/api/v2/map") return route.fulfill({ json: {
      regions: [],
      core_agents: [
        { id: 1, name: "Supplier Officer", role: "supplier_officer", occupation: "trader", x: null, y: null },
        { id: 2, name: "Editor Northstar", role: "editor", occupation: "editor", x: null, y: null },
        { id: 3, name: "Dr. Amara Osei", role: null, occupation: "doctor", x: null, y: null },
      ],
      firms: [{ id: 1, name: "Northstar Foods", sector: "food", status: "private", x: null, y: null }],
      flows: [],
    } });
    if (path === "/api/v2/world-map") return route.fulfill({ json: {
      ...baseEnvelope, projection: "world.map", data: {
        regions: [],
        agents: [
          { id: 1, name: "Supplier Officer", role: "supplier_officer", occupation: "trader", x: null, y: null },
          { id: 2, name: "Editor Northstar", role: "editor", occupation: "editor", x: null, y: null },
          { id: 3, name: "Dr. Amara Osei", role: null, occupation: "doctor", x: null, y: null },
        ],
        organizations: [{ id: 1, name: "Northstar Foods", sector: "food", status: "private", x: null, y: null }],
        places: [],
        presence: [],
      },
    } });
    /* The civic panel lives in the World workspace, so its atlas projection has
       to be answered too or the workspace renders its error state instead. */
    if (path === "/api/v2/workspaces/world") return route.fulfill({ json: {
      ...baseEnvelope, projection: "workspace.world", data: {
        enabled: true, regions: [], agents: [], organizations: [],
        places: [], presence: [], flows: [],
      },
    } });
    if (path === "/api/v2/civic/summary") return route.fulfill({ json: {
      ...baseEnvelope, projection: "civic.summary", data: {
        enabled: false, tick: 6, queue: { depth: 0, oldest_age_ticks: 0 }, offices: [],
      },
    } });
    if (path === "/api/v2/events") return route.fulfill({ json: {
      ...baseEnvelope, projection: "events.page", data: { items: [
        { id: 9, tick: 6, phase: "MARKET", kind: "goods_sale", importance: 2, payload: { qty: 5 } },
      ], next_after_id: null, truncated: false },
    } });
    if (path === "/api/v2/workspaces/living-agents") {
      const projectionTick = Number(url.searchParams.get("tick") || baseEnvelope.tick);
      return route.fulfill({ json: {
        ...baseEnvelope,
        semantics_version: 13,
        tick: projectionTick,
        fork_id: url.searchParams.get("fork_id"),
        projection: "workspace.living_agents",
        data: {
          summary: {
            tick: projectionTick,
            living_agents: 2,
            active_employments: 1,
            active_projects: 3,
            completed_projects: 1,
            public_outputs: 1,
            runtime_active: 0,
            projects_total: 4,
            projects_shown: 4,
          },
          agents: [{
            id: 1,
            name: "Atlas Builder",
            kind: "person",
            role: null,
            occupation: "carpenter",
            population_tier: "core",
            arrived_tick: 0,
            died_tick: null,
            alive: true,
            region: { id: 2, name: "Harbor Ward" },
            balance_cents: 12500,
            employment: {
              id: 8,
              firm_id: 3,
              firm_name: "Atlas Works",
              title: "Lead carpenter",
              wage_cents: 900,
              start_tick: 2,
            },
            compute: {
              tier: "local",
              payer_type: "self",
              price_cents: 0,
              effective_tick: 0,
              expiry_tick: null,
              evidence_ref: null,
            },
            skills: [{
              skill_key: "construction",
              level: 2,
              xp: 140,
              last_practiced_tick: projectionTick,
              milestone_count: 2,
              source: "committed",
              evidence_ref: { kind: "skill_progress", id: 14, tick: projectionTick },
            }],
            residence: {
              visibility: "public",
              id: 7,
              name: "Harbor House",
              kind: "home",
              region: { id: 2, name: "Harbor Ward" },
            },
            workplace: null,
            latest_committed_tick: projectionTick,
            runtime: null,
          }],
          projects: [{
            project_id: "skill:1:construction",
            kind: "skill",
            title: "Construction skill",
            owner_agent_id: 1,
            stage: "level_2",
            status: "active",
            started_tick: 2,
            updated_tick: projectionTick,
            completed_tick: null,
            milestone_count: 2,
            source: "committed",
            evidence_refs: [{ kind: "skill_progress", id: 14, tick: projectionTick }],
            organization: null,
            place: null,
            region: { id: 2, name: "Harbor Ward" },
            metrics: { level: 2, xp: 140 },
            privacy: "exact",
          }, {
            project_id: "employment:8",
            kind: "employment",
            title: "Lead carpenter at Atlas Works",
            owner_agent_id: 1,
            stage: "employed",
            status: "active",
            started_tick: 2,
            updated_tick: 2,
            completed_tick: null,
            milestone_count: 1,
            source: "committed",
            evidence_refs: [{ kind: "employment", id: 8, tick: 2 }],
            organization: { id: 3, name: "Atlas Works" },
            place: null,
            region: { id: 2, name: "Harbor Ward" },
            metrics: { wage_cents: 900 },
            privacy: "exact",
          }, {
            project_id: "residence:7",
            kind: "residence",
            title: "Established Harbor House",
            owner_agent_id: 1,
            stage: "established",
            status: "completed",
            started_tick: 3,
            updated_tick: 3,
            completed_tick: 3,
            milestone_count: 1,
            source: "committed",
            evidence_refs: [{ kind: "lease", id: 4, tick: 3 }],
            organization: null,
            place: { id: 7, name: "Harbor House", kind: "home" },
            region: { id: 2, name: "Harbor Ward" },
            metrics: {},
            privacy: "exact",
          }, livingConstructionProject],
          activity: {
            items: [{
              activity_id: "skill:14",
              tick: projectionTick,
              kind: "skill",
              stage: "level_2",
              title: "Reached construction level 2",
              agent_id: 1,
              project_id: "skill:1:construction",
              source: "committed",
              evidence_ref: { kind: "skill_progress", id: 14, tick: projectionTick },
            }],
            next_cursor: null,
            total: 1,
            cursor_kind: "offset",
          },
          source_legend: {
            committed: "Stored actions, transactions, cases, skills, and outcomes.",
            runtime: "Live-only activity that is never written into history.",
            derived: "Summaries calculated from committed evidence.",
          },
          privacy: {
            private_bodies_omitted: true,
            peripheral_locations: "aggregated_or_masked",
            civic_cases: "aggregate_only",
          },
        },
      } });
    }
    if (path === "/api/v2/agents/1/journey") {
      const projectionTick = Number(url.searchParams.get("tick") || baseEnvelope.tick);
      return route.fulfill({ json: {
        ...baseEnvelope,
        semantics_version: 13,
        tick: projectionTick,
        fork_id: url.searchParams.get("fork_id"),
        projection: "workspace.agent_journey",
        data: {
          profile: {
            id: 1,
            name: "Atlas Builder",
            kind: "person",
            role: null,
            occupation: "carpenter",
            population_tier: "core",
            arrived_tick: 0,
            died_tick: null,
          },
          current_state: {
            region: { id: 2, name: "Harbor Ward" },
            employment: {
              id: 8,
              firm_id: 3,
              firm_name: "Atlas Works",
              title: "Lead carpenter",
              wage_cents: 900,
              start_tick: 2,
            },
            balance_cents: 12500,
            compute: {
              tier: "local",
              payer_type: "self",
              price_cents: 0,
              effective_tick: 0,
              expiry_tick: null,
              evidence_ref: null,
            },
            residence: {
              visibility: "public",
              id: 7,
              name: "Harbor House",
              kind: "home",
              region: { id: 2, name: "Harbor Ward" },
            },
            workplace: null,
          },
          skills: [{
            skill_key: "construction",
            level: 2,
            xp: 140,
            last_practiced_tick: projectionTick,
            milestone_count: 2,
            source: "committed",
            evidence_ref: { kind: "skill_progress", id: 14, tick: projectionTick },
          }],
          projects: [livingConstructionProject],
          milestones: {
            items: [{
              activity_id: "skill:14",
              tick: projectionTick,
              kind: "skill",
              stage: "level_2",
              title: "Reached construction level 2",
              agent_id: 1,
              project_id: "skill:1:construction",
              source: "committed",
              evidence_ref: { kind: "skill_progress", id: 14, tick: projectionTick },
            }],
            next_cursor: null,
            total: 1,
            cursor_kind: "offset",
          },
          public_outputs: [],
          runtime: null,
          evidence_refs: [
            { kind: "employment", id: 8, tick: 2 },
            { kind: "skill_progress", id: 14, tick: projectionTick },
          ],
          source_legend: {
            committed: "Stored actions, transactions, cases, skills, and outcomes.",
            runtime: "Live-only activity that is never written into history.",
            derived: "Summaries calculated from committed evidence.",
          },
          privacy: {
            private_bodies_omitted: true,
            peripheral_locations: "aggregated_or_masked",
            civic_cases: "aggregate_only",
          },
        },
      } });
    }
    if (path === "/api/v2/search") return route.fulfill({ json: {
      ...baseEnvelope, projection: "search.results", data: { groups: [
        { kind: "agent", truncated: false, items: [{ kind: "agent", id: 12, label: "Atlas Researcher", sublabel: "researcher · Agent #12" }] },
        { kind: "firm", truncated: false, items: [{ kind: "firm", id: 3, label: "Atlas Foods", sublabel: "food · Firm #3" }] },
        { kind: "event", truncated: false, items: [{ kind: "event", id: 81, label: "goods sale", sublabel: "Event #81 · t4 · firm #3" }] },
        { kind: "communication_thread", truncated: false, items: [{ kind: "communication_thread", id: 6, label: "Atlas bulletin", sublabel: "Authorized communication · t4 · Thread #6" }] },
      ] },
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
  /* Run controls are current-only and mocked separately from observer projections. */
  await page.route("**/api/run/status", route => route.fulfill({ json: {
    status: "paused", running: false,
  } }));
  /* The evidence link is rendered per row, so the fixture keeps one event. */
  await page.route("**/api/events*", route => route.fulfill({ json: [
    { id: 9, tick: 6, phase: "MARKET", kind: "goods_sale", importance: 2, payload: { buyer_id: 1, qty: 5 } },
  ] }));
  await page.route("**/api/agents", route => route.fulfill({ json: [
    { id: 1, name: "Supplier Officer", kind: "staff", role: "supplier_officer", occupation: "trader", health: "healthy", alive: 1, employer_id: 1, model_tier: "premium" },
    { id: 2, name: "Editor Northstar", kind: "staff", role: "editor", occupation: "editor", health: "healthy", alive: 1, employer_id: null, model_tier: "flash" },
    { id: 3, name: "Dr. Amara Osei", kind: "person", role: null, occupation: "doctor", health: "healthy", alive: 1, employer_id: null, model_tier: "local" },
  ] }));
  await page.route("**/api/firms", route => route.fulfill({ json: [
    { id: 1, name: "Northstar Foods", sector: "food", status: "private", employees: 1 },
  ] }));
  await page.route("**/api/llm/runtime", route => route.fulfill({ json: {
    live_only: true,
    activity_revision: 0,
    active_agents: [],
    global: { capacity: 3, in_flight: 1, queue_depth: 0, peak_in_flight: 2, peak_queue_depth: 1, logical_deadline_s: 90 },
    simulated_days: { samples: 2, p50_wall_ms: 1200, p95_wall_ms: 1600 },
    providers: [],
  } }));
}

test.beforeEach(async ({ page }) => { await installSocket(page); await mockApi(page); });

test("initial projection handshake does not refetch stale backfill", async ({ page }) => {
  let snapshotRequests = 0;
  await page.route("**/api/v2/snapshot?*", async route => {
    snapshotRequests += 1;
    await route.fallback();
  });
  await page.goto("/runs/run-demo/overview");
  await expect(page.getByRole("heading", { name: "Pulse", exact: true })).toBeVisible();
  await page.waitForTimeout(200);
  expect(snapshotRequests).toBeLessThanOrEqual(2);
});

test("cursor_ahead recovery resets and resumes without looping", async ({ page }) => {
  let snapshotRequests = 0;

  await page.addInitScript(() => {
    class RecoverySocket extends EventTarget {
      static OPEN = 1;
      static CLOSED = 3;
      readyState = RecoverySocket.OPEN;
      constructor(_url: string) {
        super();
        (window as any).__recoverySocket = this;
        queueMicrotask(() => {
          this.dispatchEvent(new Event("open"));
          this.dispatchEvent(new MessageEvent("message", { data: JSON.stringify({
            type: "hello", run_id: "run-demo", fork_id: null, tick: 6,
            semantics_version: 8, projection_version: 1, policy_version: 1,
            view_key: "view-demo", event_cursor: 10, status: "running",
          }) }));
        });
      }
      send(_value: string) {}
      close() {
        this.readyState = RecoverySocket.CLOSED;
        this.dispatchEvent(new CloseEvent("close", { wasClean: true }));
      }
      emit(message: unknown) {
        this.dispatchEvent(new MessageEvent("message", { data: JSON.stringify(message) }));
      }
    }
    Object.defineProperty(window, "WebSocket", { value: RecoverySocket });
  });

  await page.route("**/api/v2/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/v2/snapshot") {
      snapshotRequests += 1;
      return route.fulfill({ json: {
        ...baseEnvelope, event_cursor: 4, projection: "world.snapshot", data: {
          summary: {
            status: "running", phase: "FINALIZE", active_tick: null,
            agents_alive: 1, active_firms: 1, ledger_balance: 0,
          },
          communications: { total: 0, published: 0, private_total: 0 },
          alerts: [],
          events: { items: [{
            id: 9, tick: 6, phase: "MARKET", kind: "goods_sale", importance: 2,
            payload: { qty: 5 },
          }] },
        },
      } });
    }
    if (path === "/api/v2/map") {
      return route.fulfill({ json: {
        regions: [],
        core_agents: [{ id: 1, name: "Supplier Officer", role: "supplier_officer", occupation: "trader", x: null, y: null }],
        firms: [], flows: [],
      } });
    }
    if (path === "/api/v2/world-map") {
      return route.fulfill({ json: {
        ...baseEnvelope, projection: "world.map", data: {
          regions: [],
          agents: [{ id: 1, name: "Supplier Officer", role: "supplier_officer", occupation: "trader", x: null, y: null }],
          organizations: [],
          places: [],
          presence: [],
        },
      } });
    }
    if (path === "/api/v2/workspaces/world") {
      return route.fulfill({ json: {
        ...baseEnvelope, projection: "workspace.world", data: {
          enabled: true, regions: [], agents: [], organizations: [],
          places: [], presence: [], flows: [],
        },
      } });
    }
    if (path === "/api/v2/civic/summary") {
      return route.fulfill({ json: {
        ...baseEnvelope, projection: "civic.summary", data: {
          enabled: false, tick: 6, queue: { depth: 0, oldest_age_ticks: 0 }, offices: [],
        },
      } });
    }
    if (path === "/api/v2/mode") return route.fulfill({ status: 404, json: {} });
    if (path === "/api/v2/operator/session") {
      return route.fulfill({ json: { owner_id: "local-operator", csrf_token: "test" } });
    }
    if (path === "/api/v2/operator/investigations") {
      return route.fulfill({ json: { items: [] } });
    }
    return route.fulfill({ status: 404, json: { detail: "not mocked" } });
  });
  /* Overview's event stream is the REST roster endpoint, not the v2 projection,
     and the trace link is rendered per row — so the row has to exist. */
  await page.route("**/api/events*", route => route.fulfill({ json: [
    { id: 9, tick: 6, phase: "MARKET", kind: "goods_sale", importance: 2, payload: { buyer_id: 1, qty: 5 } },
  ] }));
  await page.route("**/api/agents", route => route.fulfill({ json: [
    { id: 1, name: "Supplier Officer", kind: "staff", role: "supplier_officer", occupation: "trader", alive: 1 },
  ] }));
  await page.route("**/api/firms", route => route.fulfill({ json: [] }));
  await page.route("**/api/llm/runtime", route => route.fulfill({ json: {
    live_only: true,
    global: { capacity: 1, in_flight: 0, queue_depth: 0, peak_in_flight: 0, peak_queue_depth: 0, logical_deadline_s: 90 },
    simulated_days: { samples: 0, p50_wall_ms: null, p95_wall_ms: null },
    providers: [],
  } }));

  await page.goto("/runs/run-demo/overview");
  await expect(page.getByRole("heading", { name: "Pulse", exact: true })).toBeVisible();
  const beforeRecovery = snapshotRequests;

  await page.evaluate(() => {
    const recovery = (window as any).__recoverySocket;
    recovery.emit({
      type: "error", code: "cursor_ahead", event_cursor: 4,
    });
  });
  await expect(page.getByRole("alert")).toContainText("cursor_ahead");

  await page.evaluate(() => {
    const recovery = (window as any).__recoverySocket;
    recovery.emit({
      type: "projection_delta", domain: "cursor_advance",
      run_id: "run-demo", fork_id: null, tick: 6,
      semantics_version: 8, projection_version: 1, policy_version: 1,
      view_key: "view-demo", previous_event_cursor: 4, event_cursor: 5,
      payload: [],
    });
  });
  await page.waitForTimeout(300);
  // Recovery invalidates once; it must not enter a tight refetch loop.
  expect(snapshotRequests - beforeRecovery).toBeLessThanOrEqual(3);
  await expect(page.getByRole("heading", { name: "Pulse", exact: true })).toBeVisible();
});

test("cursor gaps request contiguous backfill and return live", async ({ page }) => {
  await page.addInitScript(() => {
    class GapSocket extends EventTarget {
      static OPEN = 1;
      static CLOSED = 3;
      readyState = GapSocket.OPEN;
      sent: unknown[] = [];
      constructor(_url: string) {
        super();
        (window as any).__gapSocket = this;
        queueMicrotask(() => {
          this.dispatchEvent(new Event("open"));
          this.emit({
            type: "hello", run_id: "run-demo", fork_id: null, tick: 6,
            semantics_version: 8, projection_version: 1, policy_version: 1,
            view_key: "view-demo", event_cursor: 0, status: "running",
          });
        });
      }
      send(value: string) { this.sent.push(JSON.parse(value)); }
      close() {
        this.readyState = GapSocket.CLOSED;
        this.dispatchEvent(new CloseEvent("close", { wasClean: true }));
      }
      emit(message: unknown) {
        this.dispatchEvent(new MessageEvent(
          "message", { data: JSON.stringify(message) }));
      }
    }
    Object.defineProperty(window, "WebSocket", { value: GapSocket });
  });

  await page.goto("/runs/run-demo/overview");
  await expect(page.getByRole("heading", { name: "Pulse", exact: true })).toBeVisible();
  await expect.poll(async () => page.evaluate(() => (
    (window as any).__gapSocket.sent
  ))).toContainEqual({ type: "hello", event_cursor: 0 });
  await page.evaluate(() => {
    (window as any).__gapSocket.sent.length = 0;
  });

  await page.evaluate(() => {
    (window as any).__gapSocket.emit({
      type: "projection_delta", domain: "observatory",
      run_id: "run-demo", fork_id: null, tick: 6,
      semantics_version: 8, projection_version: 1, policy_version: 1,
      view_key: "view-demo", previous_event_cursor: 3, event_cursor: 4,
      payload: {},
    });
  });

  await expect(page.getByRole("alert")).toContainText("cursor_gap");
  await expect.poll(async () => page.evaluate(() => (
    (window as any).__gapSocket.sent
  ))).toContainEqual({ type: "hello", event_cursor: 0 });

  await page.evaluate(() => {
    const socket = (window as any).__gapSocket;
    for (let cursor = 1; cursor <= 4; cursor += 1) {
      socket.emit({
        type: "projection_delta", domain: "cursor_advance",
        run_id: "run-demo", fork_id: null, tick: 6,
        semantics_version: 8, projection_version: 1, policy_version: 1,
        view_key: "view-demo", previous_event_cursor: cursor - 1,
        event_cursor: cursor, payload: [],
      });
    }
  });

  await expect(page.getByRole("alert")).toHaveCount(0);
  await expect(page.locator(".world-os-freshness--global summary")).toContainText("cursor 4");
});

test("lineage changes reconcile from the authoritative server hello", async ({ page }) => {
  await page.addInitScript(() => {
    class LineageSocket extends EventTarget {
      static OPEN = 1;
      static CLOSED = 3;
      static instances: LineageSocket[] = [];
      readyState = LineageSocket.OPEN;
      sent: unknown[] = [];
      closed = false;
      constructor(_url: string) {
        super();
        LineageSocket.instances.push(this);
        (window as any).__lineageSockets = LineageSocket.instances;
        queueMicrotask(() => {
          const forkId = (window as any).__lineageFork ?? "fork-a";
          this.dispatchEvent(new Event("open"));
          this.emit({
            type: "hello", run_id: "run-demo",
            fork_id: forkId,
            tick: 6, semantics_version: 8, projection_version: 1,
            policy_version: 1, view_key: "view-demo",
            event_cursor: forkId === "fork-a" ? 4 : 0, status: "running",
          });
        });
      }
      send(value: string) { this.sent.push(JSON.parse(value)); }
      close() {
        if (this.closed) return;
        this.closed = true;
        this.readyState = LineageSocket.CLOSED;
        this.dispatchEvent(new CloseEvent("close", { wasClean: true }));
      }
      emit(message: unknown) {
        this.dispatchEvent(new MessageEvent(
          "message", { data: JSON.stringify(message) }));
      }
    }
    Object.defineProperty(window, "WebSocket", { value: LineageSocket });
  });

  await page.goto("/runs/run-demo/overview");
  await expect(page.getByRole("heading", { name: "Pulse", exact: true })).toBeVisible();
  await expect(page.locator(".world-os-freshness--global summary")).toContainText("cursor 4");
  const initialConnections = await page.evaluate(() => (
    (window as any).__lineageSockets.length
  ));

  await page.evaluate(() => {
    (window as any).__lineageFork = "fork-b";
    (window as any).__lineageSockets.at(-1).emit({
      type: "projection_delta", domain: "cursor_advance",
      run_id: "run-demo", fork_id: "fork-b", tick: 6,
      semantics_version: 8, projection_version: 1, policy_version: 1,
      view_key: "view-demo", previous_event_cursor: 4, event_cursor: 5,
      payload: { summary: { status: "should-not-render" } },
    });
  });

  await expect(page.getByRole("alert")).toContainText("lineage_mismatch");
  await expect(page.getByText("should-not-render")).toHaveCount(0);
  await expect.poll(async () => page.evaluate(() => (
    (window as any).__lineageSockets.length
  ))).toBe(initialConnections + 1);
  await expect.poll(async () => page.evaluate(() => (
    (window as any).__lineageSockets.at(-1).sent
  ))).toContainEqual({ type: "hello", event_cursor: 0 });
  await expect(page.locator(".world-os-freshness--global summary")).toContainText("cursor 0");

  await page.evaluate(() => {
    (window as any).__lineageSockets.at(-1).emit({
      type: "projection_delta", domain: "cursor_advance",
      run_id: "run-demo", fork_id: "fork-b", tick: 6,
      semantics_version: 8, projection_version: 1, policy_version: 1,
      view_key: "view-demo", previous_event_cursor: 0, event_cursor: 1,
      payload: [],
    });
  });

  await expect(page.getByRole("alert")).toHaveCount(0);
  await expect(page.getByText("should-not-render")).toHaveCount(0);
  await expect(page.locator(".world-os-freshness--global summary")).toContainText("cursor 1");
});

test("live city layers, search, and evidence lens stay truthful and interactive", async ({ page }) => {
  await page.goto("/runs/run-demo/world");
  await expect(page.getByRole("heading", { name: "The living city" })).toBeVisible();
  await expect(page.getByText("Derived civic layout", { exact: true }).first()).toBeVisible();
  await expect(page.locator(".civic-city__agent")).toHaveCount(3);

  await page.getByRole("button", { name: /Health/ }).click();
  await expect(page.locator(".civic-city__agent")).toHaveCount(1);
  await page.locator(".civic-city__agent").click();
  await expect(page.getByRole("heading", { name: "Dr. Amara Osei" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Open citizen dossier" })).toHaveAttribute("href", "/runs/run-demo/people/3");

  const allLayer = page.locator(".civic-city__layers button").filter({ hasText: /^All/ });
  await allLayer.click();
  await expect(allLayer).toHaveAttribute("aria-pressed", "true");
  await page.getByLabel("Find an agent").fill("Supplier Officer");
  await expect(page).toHaveURL(/q=Supplier\+Officer/);
  await expect(page.locator(".civic-city__agent")).toHaveCount(1);
  await page.getByRole("button", { name: /^Supplier Officer,/ }).click();
  await expect(page).toHaveURL(/agent=1/);
  await expect(page.locator(".civic-city__agent")).toHaveCount(1);
  await expect(page.locator(".civic-city__activity strong")).toHaveText("Settled");
  await expect(page.getByRole("link", { name: "Trace this event" })).toHaveAttribute("href", "/runs/run-demo/investigations?event=9");
});

test("live AI activity coordinates map markers, dock, filters, and evidence", async ({ page }) => {
  await page.route("**/api/llm/runtime", route => route.fulfill({ json: {
    live_only: true,
    activity_revision: 4,
    active_agents: [{
      agent_id: 2, state: "thinking", active_calls: 2, tick: 6, oldest_elapsed_ms: 850,
    }],
    global: { capacity: 3, in_flight: 2, queue_depth: 0, peak_in_flight: 2, peak_queue_depth: 1, logical_deadline_s: 90 },
    simulated_days: { samples: 2, p50_wall_ms: 1200, p95_wall_ms: 1600 },
    providers: [],
  } }));

  await page.goto("/runs/run-demo/world");
  await expect(page.locator(".civic-city__agent.is-thinking")).toHaveCount(1);
  await expect(page.getByText("1 live · 1 changed this tick")).toBeVisible();
  await expect(page.getByRole("button", { name: "Select Editor Northstar, Thinking" })).toBeVisible();

  await page.getByRole("button", { name: /Editor Northstar, Editor, Thinking/ }).click();
  await expect(page.getByRole("heading", { name: "Editor Northstar" })).toBeVisible();
  await expect(page.getByText("Live runtime telemetry")).toBeVisible();
  await expect(page.locator(".civic-city__activity strong")).toHaveText("Thinking");
  await expect(page.getByText(/2 active calls/)).toBeVisible();

  await page.getByLabel("Live or changed this tick").focus();
  await page.getByLabel("Live or changed this tick").press("Space");
  await expect(page.getByLabel("Live or changed this tick")).toBeChecked();
  await expect(page.locator(".civic-city__agent")).toHaveCount(2);
  await expect(page.locator(".civic-city__agent.is-thinking")).toHaveCount(1);
  await expect(page.locator(".civic-city__agent.is-settled")).toHaveCount(1);
});

test("a copied Civic City URL restores filters and selection", async ({ page, context }) => {
  const url = "/runs/run-demo/world?fork=fork-a&tick=6&layer=markets&q=Supplier&activeOnly=1&agent=1";
  await page.goto(url);
  await expect(page.getByRole("button", { name: /Markets/ })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByLabel("Find an agent")).toHaveValue("Supplier");
  await expect(page.getByLabel("Live or changed this tick")).toBeChecked();
  await expect(page.getByRole("heading", { name: "Supplier Officer" })).toBeVisible();

  const fresh = await context.newPage();
  await installSocket(fresh);
  await mockApi(fresh);
  await fresh.goto(page.url());
  await expect(fresh.getByRole("button", { name: /Markets/ })).toHaveAttribute("aria-pressed", "true");
  await expect(fresh.getByLabel("Find an agent")).toHaveValue("Supplier");
  await expect(fresh.getByRole("heading", { name: "Supplier Officer" })).toBeVisible();
  await fresh.close();
});

test("Civic City discrete selections participate in browser history", async ({ page }) => {
  await page.goto("/runs/run-demo/world");
  await page.getByRole("button", { name: /Editor Northstar, Editor/ }).click();
  await expect(page).toHaveURL(/agent=2/);
  await page.getByRole("button", { name: /Dr\. Amara Osei, Doctor/ }).click();
  await expect(page).toHaveURL(/agent=3/);
  await page.goBack();
  await expect(page).toHaveURL(/agent=2/);
  await expect(page.getByRole("heading", { name: "Editor Northstar" })).toBeVisible();
});

test("Civic City scales from core agents to clusters and all 300 residents", async ({ page }) => {
  const requestedModes: string[] = [];
  const coreAgents = Array.from({ length: 100 }, (_, index) => ({
    id: index + 1,
    name: `Core Resident ${String(index + 1).padStart(3, "0")}`,
    occupation: index % 2 ? "engineer" : "teacher",
    population_tier: "core",
    x: null,
    y: null,
  }));
  const peripheralAgents = Array.from({ length: 200 }, (_, index) => ({
    id: index + 101,
    name: `Peripheral Resident ${String(index + 1).padStart(3, "0")}`,
    occupation: index % 2 ? "nurse" : "logistics worker",
    population_tier: "periphery",
    x: null,
    y: null,
    place_id: null,
    place_name: null,
  }));
  await page.route("**/api/v2/world-map*", route => {
    const mode = new URL(route.request().url()).searchParams.get("population") || "core";
    requestedModes.push(mode);
    const clusters = mode === "clusters" ? [
      { id: "region-1-periphery", region_id: 1, label: "Northstar", count: 170, x: .25, y: .35 },
      { id: "region-2-periphery", region_id: 2, label: "Ironvale", count: 15, x: .72, y: .28 },
      { id: "region-3-periphery", region_id: 3, label: "Suncoast", count: 15, x: .55, y: .78 },
    ] : [];
    return route.fulfill({ json: {
      ...baseEnvelope,
      projection: "world.map",
      data: {
        regions: [],
        agents: mode === "all" ? [...coreAgents, ...peripheralAgents] : coreAgents,
        organizations: [],
        places: [],
        presence: [],
        population_mode: mode,
        population_summary: {
          total: 300,
          core: 100,
          periphery: 200,
          rendered_agents: mode === "all" ? 300 : 100,
          clustered_agents: mode === "clusters" ? 200 : 0,
        },
        population_clusters: clusters,
      },
    } });
  });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/runs/run-demo/world?population=clusters");
  await expect(page.locator(".civic-city__population")).toBeVisible();
  await expect(page.locator(".civic-city__population button", { hasText: "Clusters" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".civic-city__cluster")).toHaveCount(3);
  await expect(page.getByText("100 core marks + 200 clustered residents")).toBeVisible();

  await page.locator(".civic-city__cluster").first().click();
  await expect(page).toHaveURL(/population=all/);
  await expect(page.locator(".civic-city__agent")).toHaveCount(300);

  await page.locator(".civic-city__population button", { hasText: "Core" }).click();
  await expect(page).not.toHaveURL(/population=/);
  await expect(page.locator(".civic-city__agent")).toHaveCount(100);
  await page.goBack();
  await expect(page).toHaveURL(/population=all/);
  await expect(page.locator(".civic-city__agent")).toHaveCount(300);
  expect(requestedModes).toEqual(expect.arrayContaining(["clusters", "all", "core"]));
});

test("citizen menu unifies app and onboarding links in the same tab", async ({ page }) => {
  await page.goto("/runs/run-demo/overview");
  await page.locator("summary", { hasText: "Citizen menu" }).click();
  const menu = page.getByRole("navigation", { name: "Agent Economy sections" });
  await expect(menu).toBeVisible();

  const expected = {
    Observatory: "/",
    "World OS": "/runs/run-demo/overview",
    Commons: "/runs/run-demo/commons",
    Join: "/join/test-world",
    "My Agents": "/my-agents",
  };
  for (const [label, href] of Object.entries(expected)) {
    const link = menu.getByRole("link", { name: label, exact: true });
    await expect(link).toHaveAttribute("href", href);
    await expect(link).not.toHaveAttribute("target", "_blank");
  }
});

test("overview enters the exact causal chain", async ({ page }) => {
  if (process.env.CAPTURE_CIVIC_ATLAS_SCREENSHOT === "1") {
    await page.setViewportSize({ width: 1536, height: 960 });
  }
  await page.goto("/runs/run-demo/overview");
  await expect(page.getByRole("heading", { name: "Pulse", exact: true })).toBeVisible();
  await expect(page.getByText("Balanced")).toBeVisible();
  if (process.env.CAPTURE_CIVIC_ATLAS_SCREENSHOT === "1") {
    await page.screenshot({
      path: "../docs/images/civic-atlas-world-pulse.png",
      fullPage: true,
    });
  }
  await page.getByRole("link", { name: "Investigate event 9" }).click();
  await expect(page).toHaveURL(/investigations\?event=9/);
  await expect(page.getByRole("heading", { name: "Causal graph" })).toBeVisible();
  await expect(page.locator(".world-os-causal-graph [role=button]")).toHaveCount(6);
});

test("World Pulse controls fail closed without authoritative run status", async ({ page }) => {
  await page.route("**/api/run/status", route => route.fulfill({
    status: 503,
    json: { detail: "status unavailable" },
  }));

  await page.goto("/runs/run-demo/overview");

  await expect(page.getByText("Run controls unavailable until authoritative status arrives.")).toBeVisible();
  const controls = page.getByRole("group", { name: "Run controls" });
  await expect(controls.getByRole("button", { name: "Run" })).toBeDisabled();
  await expect(controls.getByRole("button", { name: "Pause" })).toBeDisabled();
  await expect(controls.getByRole("button", { name: "Step" })).toBeDisabled();
});

test("World Pulse keeps historical evidence separate from current controls", async ({ page }) => {
  let runStatusRequests = 0;
  page.on("request", request => {
    if (new URL(request.url()).pathname === "/api/run/status") runStatusRequests += 1;
  });

  await page.setViewportSize({ width: 1536, height: 960 });
  await page.goto("/runs/run-demo/overview?tick=4");

  await expect(page.getByRole("heading", { name: "World Pulse", exact: true })).toBeVisible();
  await expect(page.getByText(/Historical context · read-only/)).toBeVisible();
  await expect(page.locator(".world-pulse-run-controls")).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Return to live" })).toHaveAttribute("href", "/runs/run-demo/overview");

  const main = await page.locator(".world-pulse-main").boundingBox();
  const inspector = await page.locator(".world-pulse-inspector").boundingBox();
  if (!main || !inspector) throw new Error("World Pulse review columns did not render");
  expect(main.x + main.width).toBeLessThanOrEqual(inspector.x + 1);
  expect(Math.abs(main.y - inspector.y)).toBeLessThan(4);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  expect(runStatusRequests).toBe(0);
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
  await expect(proposalNode).toHaveCSS("outline-style", "solid");
  await expect(proposalNode).toHaveCSS("outline-width", "2px");
  await expect(proposalNode).toHaveCSS("outline-color", /* --ae-accent. The token layer replaced civic-cobalt #2457d6 with #6ea8ff,
       which tokens.css records at 7.54:1 — a deliberate contrast raise, not drift. */
      "rgb(110, 168, 255)");
  await page.keyboard.press("Enter");
  await expect(page.locator(".world-os-semantic-panel tr.selected")).toContainText("buy_goods");
  await page.getByRole("button", { name: "Zoom in" }).click();
  await expect(page.locator(".world-os-graph-controls output")).toHaveText("120%");
  const duration = await page.locator(".world-os-nav a").first().evaluate(element => getComputedStyle(element).transitionDuration);
  expect(duration).toBe("0s");
});

test("390 pixel workflow keeps navigation, chronology, and evidence usable", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/runs/run-demo/news-communications");
  await expect(page.getByRole("navigation", { name: "Civic Atlas workspaces" })).toBeVisible();
  await page.getByRole("button", { name: "Truth inspector" }).click();
  await page.getByRole("button", { name: /Shipment notice/ }).click();
  await expect(page.getByText("Untrusted simulated communication")).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});

test("command navigation, tick travel, and rail controls stay interactive", async ({ page }) => {
  const pageErrors: string[] = [];
  page.on("pageerror", error => pageErrors.push(error.message));
  await page.goto("/runs/run-demo/overview");
  await expect(page.getByRole("heading", { name: "Pulse", exact: true })).toBeVisible();

  await page.keyboard.press("Control+K");
  const command = page.getByRole("dialog", { name: "Navigate and inspect" });
  await expect(command).toBeVisible();
  await expect(command.getByRole("group", { name: "Routes" })).toBeVisible();
  /* Eleven routes remain searchable even though the permanent rail shows five. */
  await expect(command.getByRole("option")).toHaveCount(11);
  const commandSearch = command.getByPlaceholder("Search routes, people, firms, events…");
  await commandSearch.fill("communications");
  await commandSearch.press("Enter");
  await expect(page).toHaveURL(/news-communications/);

  await page.goto("/runs/run-demo/overview");
  await page.getByLabel("Inspect tick").fill("4");
  await page.getByRole("button", { name: "Go to tick" }).click();
  await expect(page).toHaveURL(/tick=4/);
  await expect(page.locator(".world-os-freshness--global summary")).toContainText("Historical");

  const trigger = page.getByRole("button", { name: "Open command menu" });
  await trigger.click();
  const reopenedCommand = page.getByRole("dialog", { name: "Navigate and inspect" });
  await expect(reopenedCommand).toBeVisible();
  const reopenedSearch = reopenedCommand.getByPlaceholder("Search routes, people, firms, events…");
  const commandClose = reopenedCommand.locator('button[aria-label="Close command menu"]');
  await expect(reopenedSearch).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(commandClose).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(reopenedSearch).toBeFocused();
  await commandClose.evaluate(button => { button.tabIndex = -2; });
  await page.keyboard.press("Tab");
  await expect(reopenedSearch).toBeFocused();
  await commandClose.evaluate(button => { button.tabIndex = 0; });
  await reopenedCommand.evaluate(dialog => {
    const editor = document.createElement("div");
    editor.contentEditable = "true";
    editor.setAttribute("aria-label", "Inline command note");
    editor.textContent = "Editable note";
    dialog.append(editor);
  });
  await reopenedCommand.getByLabel("Inline command note").focus();
  await page.keyboard.press("Tab");
  await expect(commandClose).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(reopenedCommand.getByLabel("Inline command note")).toBeFocused();
  await reopenedCommand.evaluate(dialog => {
    const iframe = document.createElement("iframe");
    iframe.setAttribute("aria-label", "Embedded evidence");
    iframe.style.width = "40px";
    iframe.style.height = "20px";
    const details = document.createElement("details");
    details.open = true;
    const summary = document.createElement("summary");
    summary.setAttribute("aria-label", "Evidence summary");
    summary.textContent = "Evidence summary";
    details.append(summary);
    const audio = document.createElement("audio");
    audio.controls = true;
    audio.setAttribute("aria-label", "Audio evidence");
    const video = document.createElement("video");
    video.controls = true;
    video.setAttribute("aria-label", "Video evidence");
    video.style.width = "80px";
    video.style.height = "40px";
    dialog.append(iframe, details, audio, video);
  });
  await reopenedCommand.getByLabel("Inline command note").focus();
  await page.keyboard.press("Tab");
  await expect(reopenedCommand.getByLabel("Embedded evidence")).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(reopenedCommand.getByLabel("Evidence summary")).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(reopenedCommand.getByLabel("Audio evidence")).toBeFocused();
  await reopenedCommand.getByLabel("Audio evidence").evaluate(element => {
    element.tabIndex = -1;
  });
  await reopenedCommand.getByLabel("Evidence summary").focus();
  await page.keyboard.press("Tab");
  await expect(reopenedCommand.getByLabel("Video evidence")).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(trigger).toBeFocused();

  await page.getByRole("button", { name: "Collapse workspace rail" }).click();
  await expect(page.locator(".world-os-shell")).toHaveClass(/world-os-shell--collapsed/);
  await expect(page.getByRole("navigation", { name: "Civic Atlas workspaces" })).toBeVisible();
  expect(pageErrors).toEqual([]);
});

test("modal focus predicate excludes hidden and fieldset-disabled controls", async ({ page }) => {
  await page.goto("/runs/run-demo/overview");

  const focusability = await page.evaluate(async () => {
    const focusModule = await import("/src/components/useModalFocus.ts") as unknown as {
      isTabbableElement(element: HTMLElement): boolean;
    };
    const visible = document.createElement("button");
    visible.textContent = "Visible";
    document.body.append(visible);
    const displayNone = visible.cloneNode(true) as HTMLButtonElement;
    displayNone.style.display = "none";
    document.body.append(displayNone);
    const visibilityHidden = visible.cloneNode(true) as HTMLButtonElement;
    visibilityHidden.style.visibility = "hidden";
    document.body.append(visibilityHidden);
    const fieldset = document.createElement("fieldset");
    fieldset.disabled = true;
    const disabledDescendant = visible.cloneNode(true) as HTMLButtonElement;
    fieldset.append(disabledDescendant);
    document.body.append(fieldset);
    const contentEditable = document.createElement("div");
    contentEditable.contentEditable = "true";
    contentEditable.textContent = "Editable";
    document.body.append(contentEditable);
    return {
      visible: focusModule.isTabbableElement(visible),
      displayNone: focusModule.isTabbableElement(displayNone),
      visibilityHidden: focusModule.isTabbableElement(visibilityHidden),
      disabledDescendant: focusModule.isTabbableElement(disabledDescendant),
      contentEditable: focusModule.isTabbableElement(contentEditable),
    };
  });

  expect(focusability).toEqual({
    visible: true,
    displayNone: false,
    visibilityHidden: false,
    disabledDescendant: false,
    contentEditable: true,
  });
});

test("participant mutation failures render, recover controls, and reset across identity changes", async ({ page }) => {
  await page.goto("/runs/run-demo/overview");
  await page.evaluate(async () => {
    const { mountParticipantHarness } = await import("/tests/e2e/fixtures/participantHarness.jsx");
    const container = document.createElement("div");
    container.id = "participant-test-root";
    document.body.append(container);
    (window as any).__participantHarness = mountParticipantHarness(container, {
      enabled: true,
      active: true,
      running: false,
      completed_tick: 6,
      next_tick: 7,
      controlled_agent: {
        id: 1, name: "Ada Tester", occupation: "engineer", health: "healthy",
      },
      action_catalog: [{ type: "rest", label: "Rest", enabled: true, fields: [] }],
    });
  });
  const harness = page.locator("#participant-test-root");
  const queue = harness.getByRole("button", { name: "Queue action for next day" });
  await queue.click();
  await expect(harness.getByRole("alert")).toContainText("queue rejected");
  await expect(queue).toBeEnabled();

  await page.evaluate(() => (window as any).__participantHarness.update({
    controlled_agent: {
      id: 2, name: "Grace Tester", occupation: "analyst", health: "healthy",
    },
  }));
  await expect(harness.getByRole("alert")).toBeHidden();
  await expect(harness.getByText("Grace Tester")).toBeVisible();

  const release = harness.getByRole("button", { name: "Release citizen" });
  await release.click();
  await expect(harness.getByRole("alert")).toContainText("release rejected");
  await expect(release).toBeEnabled();
  await page.evaluate(() => (window as any).__participantHarness.update({ active: false }));
  await expect(harness.getByRole("alert")).toBeHidden();
  await expect(harness.getByText(/Take control/)).toBeVisible();

  const requests = await page.evaluate(() => (window as any).__participantHarness.requests);
  expect(requests).toEqual(["/api/participant/action", "/api/participant/release"]);
});

test("modal initial focus ignores a detached caller target", async ({ page }) => {
  await page.goto("/runs/run-demo/overview");
  await page.evaluate(async () => {
    const { mountModalFocusHarness } = await import("/tests/e2e/fixtures/modalFocusHarness.jsx");
    const container = document.createElement("div");
    container.id = "modal-focus-test-root";
    document.body.append(container);
    mountModalFocusHarness(container);
  });
  await expect(page.locator("#modal-focus-test-root")
    .getByRole("button", { name: "Fallback action" })).toBeFocused();
});

test("modal focus trap treats a named radio group as one tab stop", async ({ page }) => {
  await page.goto("/runs/run-demo/overview");
  await page.evaluate(async () => {
    const { mountModalFocusHarness } = await import("/tests/e2e/fixtures/modalFocusHarness.jsx");
    const container = document.createElement("div");
    container.id = "modal-radio-focus-test-root";
    document.body.append(container);
    mountModalFocusHarness(container);
  });
  const harness = page.locator("#modal-radio-focus-test-root");
  await harness.getByRole("radio", { name: "Primary choice" }).focus();
  await page.keyboard.press("Tab");
  await expect(harness.getByRole("button", { name: "Fallback action" })).toBeFocused();
});

test("modal focus trap wraps from a connected non-tabbable initial target", async ({ page }) => {
  await page.goto("/runs/run-demo/overview");
  await page.evaluate(async () => {
    const { mountModalFocusHarness } = await import("/tests/e2e/fixtures/modalFocusHarness.jsx");
    const container = document.createElement("div");
    container.id = "modal-heading-focus-test-root";
    document.body.append(container);
    mountModalFocusHarness(container, { connectedInitial: true });
  });
  const harness = page.locator("#modal-heading-focus-test-root");
  await expect(harness.getByRole("heading", { name: "Initial heading" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(harness.getByRole("button", { name: "Fallback action" })).toBeFocused();
});

test("modal cleanup falls back to the connected previous focus target", async ({ page }) => {
  await page.goto("/runs/run-demo/overview");
  await page.evaluate(async () => {
    const previous = document.createElement("button");
    previous.id = "modal-previous-focus";
    previous.textContent = "Previous focus";
    document.body.append(previous);
    previous.focus();
    const { mountModalFocusHarness } = await import("/tests/e2e/fixtures/modalFocusHarness.jsx");
    const container = document.createElement("div");
    container.id = "modal-return-focus-test-root";
    document.body.append(container);
    mountModalFocusHarness(container, { disconnectedReturn: true });
  });
  await expect(page.locator("#modal-return-focus-test-root")
    .getByRole("button", { name: "Fallback action" })).toBeFocused();
  await page.evaluate(async () => {
    const { unmountModalFocusHarness } = await import("/tests/e2e/fixtures/modalFocusHarness.jsx");
    unmountModalFocusHarness(document.querySelector("#modal-return-focus-test-root"));
  });
  await expect(page.getByRole("button", { name: "Previous focus" })).toBeFocused();
});

test("Oracle failures render an alert and restore the request control", async ({ page }) => {
  await page.goto("/runs/run-demo/overview");
  await page.evaluate(async () => {
    const { mountOracleHarness } = await import("/tests/e2e/fixtures/oracleHarness.jsx");
    const container = document.createElement("div");
    container.id = "oracle-test-root";
    document.body.append(container);
    mountOracleHarness(container);
  });
  const harness = page.locator("#oracle-test-root");
  await harness.getByLabel("Question for the Oracle").fill("Will demand recover?");
  const ask = harness.getByRole("button", { name: "Ask Oracle" });
  await ask.click();
  await expect(harness.getByRole("alert")).toContainText("oracle unavailable");
  await expect(ask).toBeEnabled();
});

test("Oracle failures clear a forecast from the previous request", async ({ page }) => {
  await page.goto("/runs/run-demo/overview");
  await page.evaluate(async () => {
    const { mountOracleHarness } = await import("/tests/e2e/fixtures/oracleHarness.jsx");
    const container = document.createElement("div");
    container.id = "oracle-stale-test-root";
    document.body.append(container);
    mountOracleHarness(container);
  });
  const harness = page.locator("#oracle-stale-test-root");
  const question = harness.getByLabel("Question for the Oracle");
  await question.fill("First forecast");
  await harness.getByRole("button", { name: "Ask Oracle" }).click();
  await expect(harness.getByText("60%")).toBeVisible();
  await question.fill("Second forecast fails");
  await harness.getByRole("button", { name: "Ask Oracle" }).click();
  await expect(harness.getByRole("alert")).toContainText("oracle unavailable");
  await expect(harness.getByText("60%")).toBeHidden();
});

test("authorized entity search preserves fork and historical tick", async ({ page }) => {
  let searchUrl = "";
  await page.route("**/api/v2/search?*", async route => {
    searchUrl = route.request().url();
    await route.fallback();
  });
  await page.goto("/runs/run-demo/overview?fork=fork-a&tick=4");
  await expect(page.getByRole("heading", { name: "Pulse", exact: true })).toBeVisible();
  await page.keyboard.press("Control+K");
  const command = page.getByRole("dialog", { name: "Navigate and inspect" });
  const input = command.getByPlaceholder("Search routes, people, firms, events…");
  await input.fill("Atlas");
  await expect(command.getByRole("option", { name: /Atlas Researcher/ })).toBeVisible();
  await input.press("Enter");

  await expect(page).toHaveURL(/\/people\/12\?fork=fork-a&tick=4$/);
  expect(searchUrl).toContain("tick=4");
  expect(searchUrl).toContain("fork_id=fork-a");
});

test("Living Agents reconstructs history and preserves Live City focus", async ({ page }) => {
  let workspaceUrl = "";
  let journeyUrl = "";
  await page.route("**/api/v2/workspaces/living-agents?*", async route => {
    workspaceUrl = route.request().url();
    await route.fallback();
  });
  await page.route("**/api/v2/agents/1/journey?*", async route => {
    journeyUrl = route.request().url();
    await route.fallback();
  });

  await page.goto("/runs/run-demo/people/1?fork=fork-a&tick=4");

  await expect(page.getByRole("heading", { name: "People", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Atlas Builder" })).toBeVisible();
  await expect(page.getByText("Lead carpenter", { exact: true })).toBeVisible();
  const constructionSkill = page.locator(".world-os-skill-card")
    .getByText("Construction", { exact: true });
  await constructionSkill.scrollIntoViewIfNeeded();
  await expect(constructionSkill).toBeVisible();
  await expect(page.getByText("Level 2 · 140 XP · 2 milestones")).toBeVisible();
  await expect(page.locator(".world-os-person-identity")
    .getByText("Historical", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Evidence source legend").getByText("Runtime", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Harbor Works Studio" })).toBeVisible();
  await expect(page.getByText("60,000 cents", { exact: true })).toBeVisible();
  await expect(page.getByText("of 8 stored", { exact: true })).toBeVisible();
  const storyboard = page.getByLabel("Construction storyboard");
  await expect(storyboard.getByRole("heading", { name: "Construction storyboard" })).toBeVisible();
  await expect(storyboard.locator('[data-stage="foundation"]')).toContainText("Observed");
  await expect(storyboard.locator('[data-stage="frame"]')).toContainText("Current stage");
  await expect(storyboard.locator('[data-stage="shell"]')).toContainText("Not reached");

  expect(workspaceUrl).toContain("tick=4");
  expect(workspaceUrl).toContain("fork_id=fork-a");
  expect(journeyUrl).toContain("tick=4");
  expect(journeyUrl).toContain("fork_id=fork-a");

  const cityLink = page.getByRole("link", { name: "Focus in Live City" });
  await expect(cityLink).toHaveAttribute(
    "href",
    "/runs/run-demo/world?fork=fork-a&tick=4&view=diorama&agent=1&population=all",
  );
  await expect(page.locator(".world-os-project-hero").getByRole("link", { name: /Open in Live City/ })).toHaveAttribute(
    "href",
    "/runs/run-demo/world?fork=fork-a&tick=4&view=diorama&project=41",
  );
});

test("Living Agents matches the three-column review composition without overflow", async ({ page }) => {
  await page.setViewportSize({ width: 1536, height: 960 });
  await page.goto("/runs/run-demo/people/1?tick=4");
  await expect(page.getByRole("heading", { name: "Harbor Works Studio" })).toBeVisible();

  const agentRail = await page.locator(".world-os-people-list").boundingBox();
  const journey = await page.locator(".world-os-person-detail").boundingBox();
  const projectRail = await page.locator(".world-os-project-rail").boundingBox();
  if (!agentRail || !journey || !projectRail) throw new Error("Living Agents columns did not render");

  expect(agentRail.x + agentRail.width).toBeLessThan(journey.x);
  expect(journey.x + journey.width).toBeLessThan(projectRail.x);
  expect(Math.abs(agentRail.y - journey.y)).toBeLessThan(4);
  expect(Math.abs(journey.y - projectRail.y)).toBeLessThan(4);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
});

test("Living Agents stacks into one readable column on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 430, height: 932 });
  await page.goto("/runs/run-demo/people/1?tick=4");
  await expect(page.getByRole("heading", { name: "Atlas Builder" })).toBeVisible();

  const agentRail = await page.locator(".world-os-people-list").boundingBox();
  const journey = await page.locator(".world-os-person-detail").boundingBox();
  const projectRail = await page.locator(".world-os-project-rail").boundingBox();
  if (!agentRail || !journey || !projectRail) throw new Error("Living Agents mobile sections did not render");

  expect(journey.y).toBeGreaterThan(agentRail.y + agentRail.height - 2);
  expect(projectRail.y).toBeGreaterThan(journey.y + journey.height - 2);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
});

test("superseded entity searches never replace the newest result", async ({ page }) => {
  await page.route("**/api/v2/search?*", async route => {
    const query = new URL(route.request().url()).searchParams.get("q");
    if (query === "atlas") await new Promise(resolve => setTimeout(resolve, 500));
    const label = query === "atlas" ? "Atlas stale result" : "Zephyr current result";
    await route.fulfill({ json: {
      ...baseEnvelope,
      projection: "search.results",
      data: { groups: [
        { kind: "agent", truncated: false, items: [{
          kind: "agent", id: query === "atlas" ? 12 : 13,
          label, sublabel: "researcher",
        }] },
        { kind: "firm", truncated: false, items: [] },
        { kind: "event", truncated: false, items: [] },
        { kind: "communication_thread", truncated: false, items: [] },
      ] },
    } });
  });
  await page.goto("/runs/run-demo/overview");
  await expect(page.getByRole("heading", { name: "Pulse", exact: true })).toBeVisible();
  await page.keyboard.press("Control+K");
  const command = page.getByRole("dialog", { name: "Navigate and inspect" });
  const input = command.getByPlaceholder("Search routes, people, firms, events…");
  const atlasRequest = page.waitForRequest(
    request => new URL(request.url()).searchParams.get("q") === "atlas",
  );
  await input.fill("Atlas");
  await expect(command.getByText("Searching authorized entities…")).toBeVisible();
  await atlasRequest;
  await input.fill("Zephyr");
  await expect(command.getByRole("option", { name: /Zephyr current result/ })).toBeVisible();
  await page.waitForTimeout(600);
  await expect(command.getByText("Atlas stale result")).toHaveCount(0);
});

test("entity-search failure leaves matching routes operable", async ({ page }) => {
  await page.route("**/api/v2/search?*", route => route.fulfill({
    status: 503,
    json: { detail: "search unavailable" },
  }));
  await page.goto("/runs/run-demo/overview");
  await expect(page.getByRole("heading", { name: "Pulse", exact: true })).toBeVisible();
  await page.keyboard.press("Control+K");
  const command = page.getByRole("dialog", { name: "Navigate and inspect" });
  const input = command.getByPlaceholder("Search routes, people, firms, events…");
  await input.fill("Living Agents");
  await expect(command.getByText("Entity search is unavailable. Route navigation remains available.")).toBeVisible();
  await expect(command.getByRole("option", { name: /People Living Agents, projects, and evidence/ })).toBeVisible();
  await input.press("Enter");
  await expect(page).toHaveURL(/\/people$/);
});

test("socket closure is visibly reconnecting before the next hello", async ({ page }) => {
  await page.addInitScript(() => {
    class ReconnectSocket extends EventTarget {
      static OPEN = 1;
      static CLOSED = 3;
      static instances: ReconnectSocket[] = [];
      readyState = ReconnectSocket.OPEN;
      closed = false;
      constructor(_url: string) {
        super();
        ReconnectSocket.instances.push(this);
        (window as any).__reconnectSockets = ReconnectSocket.instances;
        queueMicrotask(() => {
          this.dispatchEvent(new Event("open"));
          this.dispatchEvent(new MessageEvent("message", { data: JSON.stringify({
            type: "hello", run_id: "run-demo", fork_id: null, tick: 6,
            semantics_version: 8, projection_version: 1, policy_version: 1,
            view_key: "view-demo", event_cursor: 2, status: "running",
          }) }));
        });
      }
      send(_value: string) {}
      close() {
        if (this.closed) return;
        this.closed = true;
        this.readyState = ReconnectSocket.CLOSED;
        this.dispatchEvent(new CloseEvent("close", { wasClean: false }));
      }
    }
    Object.defineProperty(window, "WebSocket", { value: ReconnectSocket });
  });

  await page.goto("/runs/run-demo/overview");
  const freshness = page.locator(".world-os-freshness--global summary");
  await expect(freshness).toContainText("Live");
  const initialConnections = await page.evaluate(() => (
    (window as any).__reconnectSockets.length
  ));
  await page.evaluate(() => (window as any).__reconnectSockets.at(-1).close());
  await expect(freshness).toContainText("Reconnecting");
  await expect.poll(async () => page.evaluate(() => (
    (window as any).__reconnectSockets.length
  ))).toBeGreaterThan(initialConnections);
  await expect(freshness).toContainText("Live");
});
