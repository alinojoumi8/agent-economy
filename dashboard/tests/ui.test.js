import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";

import {
  formatBeliefValue,
  formatMetricDelta,
  formatMetricValue,
  formatTrust,
} from "../src/api.js";


test("engine metrics, cents, and trust retain their units and precision", () => {
  assert.equal(formatMetricValue("unemployment", 0.9699421965), "97.0%");
  assert.equal(formatMetricValue("policy_rate", 525), "525 bps");
  assert.equal(formatMetricValue("cpi", 69.5534138), "69.553");
  assert.equal(formatMetricDelta("unemployment", -0.002312), "−0.2 pp");
  assert.equal(formatMetricDelta("policy_rate", 25), "+25 bps");
  assert.equal(formatTrust(0.702131), "0.7021 (70.21%)");
  assert.equal(
    formatBeliefValue("trust:bank:1", 0.702131),
    "0.7021 (70.21%)",
  );
  assert.equal(formatBeliefValue("checking_balance_cents", 300000), "$3,000.00");
});


test("Empty renders text-prop guidance and gives children precedence", async () => {
  const vite = await createServer({ appType: "custom", logLevel: "silent", server: { middlewareMode: true } });
  try {
    const { Empty } = await vite.ssrLoadModule("/src/components/ui.jsx");

    assert.match(
      renderToStaticMarkup(React.createElement(Empty, { text: "Enable the living world." })),
      /Enable the living world\./,
    );
    assert.match(
      renderToStaticMarkup(React.createElement(Empty, { text: "ignored" }, "No disputes filed.")),
      /No disputes filed\./,
    );
  } finally {
    await vite.close();
  }
});


test("Observatory empty states distinguish disabled systems from quiet systems", async () => {
  const vite = await createServer({ appType: "custom", logLevel: "silent", server: { middlewareMode: true } });
  try {
    const { EconomicMap, InstitutionalPulse, LegalPoliticalPanels } = await vite.ssrLoadModule("/src/components/V2Observatory.jsx");
    const map = renderToStaticMarkup(React.createElement(EconomicMap, { map: { enabled: false, regions: [] } }));
    assert.match(map, /Regional economy disabled for this run profile/);

    const pulse = renderToStaticMarkup(React.createElement(InstitutionalPulse, {
      legal: { enabled: false, contracts: [], items: [] },
      politics: { enabled: true, institutional_actions_enabled: false, bills: [] },
      information: {},
      datasets: {},
    }));
    assert.match(pulse, /Legal institution disabled for this run profile/);
    assert.match(pulse, /Bills<\/div><div[^>]*>Off<\/div>/);

    const panels = renderToStaticMarkup(React.createElement(LegalPoliticalPanels, {
      legal: { contracts: [], obligations: [] },
      politics: { enabled: true, institutional_actions_enabled: false, bills: [], lobbying: { items: [] } },
      information: {},
      startups: {},
      markets: {},
    }));
    assert.match(panels, /Institutional role actions are disabled for this run profile/);
  } finally {
    await vite.close();
  }
});


test("Institutional pulse formats legal status and ruleset fields", async () => {
  const vite = await createServer({ appType: "custom", logLevel: "silent", server: { middlewareMode: true } });
  try {
    const { InstitutionalPulse } = await vite.ssrLoadModule("/src/components/V2Observatory.jsx");
    const pulse = renderToStaticMarkup(React.createElement(InstitutionalPulse, {
      legal: {
        enabled: true,
        contracts: [{ id: 1 }],
        items: [{ id: 1, status: "settlement_offered", matter_type: "civil", ruleset_key: "northstar-us-inspired-1.0" }],
      },
      politics: { enabled: true, institutional_actions_enabled: true, bills: [{ id: 1 }] },
      information: {},
      datasets: {},
    }));
    assert.match(pulse, /settlement offered/);
    assert.match(pulse, /northstar-us-inspired-1\.0/);
    assert.doesNotMatch(pulse, /settlement_offered/);
  } finally {
    await vite.close();
  }
});


test("agent audit reflects deterministic actions without claiming missing decisions", async () => {
  const vite = await createServer({ appType: "custom", logLevel: "silent", server: { middlewareMode: true } });
  try {
    const { AgentModal } = await vite.ssrLoadModule("/src/components/AgentsPanel.jsx");
    const markup = renderToStaticMarkup(React.createElement(AgentModal, {
      detail: {
        agent: {
          id: 23, name: "Iris Mensah", kind: "citizen", occupation: "nurse",
          role: null, age: 39, health: "healthy", alive: 1, risk_tolerance: 0.4,
        },
        accounts: [], loans: [], beliefs: {}, belief_history: [], memories: [],
        recent_decisions: [],
        recent_actions: [{
          id: 301, tick: 180, action_type: "buy_goods",
          validation_status: "accepted", payload: { quantity: 1 }, result: { ok: true },
        }],
        output_counts: {
          model_calls: 0, actions: 126, accepted_actions: 120,
          rejected_actions: 6, deterministic_actions: 126, messages: 19,
          memories: 474, belief_updates: 182, authored_information_items: 0,
        },
        output_cursors: { model: null, action: 301 },
      },
      participant: { enabled: false }, running: false, historyLoading: false,
      onLoadOlder: () => {}, onLoadOlderOutputs: () => {},
      onTakeControl: () => {}, onClose: () => {},
    }));

    assert.match(markup, /Output coverage/);
    assert.match(markup, /deterministic policy/);
    assert.match(markup, /Actions<\/dt><dd[^>]*>126<\/dd>/);
    assert.match(markup, /No model calls recorded; inspect the deterministic action audit\./);
    assert.match(markup, /buy goods/);
    assert.match(markup, /Historical agent recollections; numeric claims may be stale/);
    assert.match(markup, /Raw model I\/O for provenance; numeric claims are unverified/);
    assert.doesNotMatch(markup, /No decisions yet/);
  } finally {
    await vite.close();
  }
});


test("agent modal disables take-control when that citizen is already controlled", async () => {
  const vite = await createServer({ appType: "custom", logLevel: "silent", server: { middlewareMode: true } });
  try {
    const { AgentModal } = await vite.ssrLoadModule("/src/components/AgentsPanel.jsx");
    const markup = renderToStaticMarkup(React.createElement(AgentModal, {
      detail: {
        agent: { id: 23, name: "Iris Mensah", kind: "citizen", alive: 1 },
        accounts: [], loans: [], beliefs: {}, belief_history: [], memories: [],
        recent_decisions: [], recent_actions: [], output_counts: {}, output_cursors: {},
      },
      participant: { enabled: true, controlled_agent: { id: 23 } },
      running: false, historyLoading: false,
      onLoadOlder: () => {}, onLoadOlderOutputs: () => {},
      onTakeControl: () => {}, onClose: () => {},
    }));
    assert.match(markup, /disabled=""[^>]*>Currently controlled<\/button>/);
  } finally {
    await vite.close();
  }
});


test("public panels expose metric units, partial days, and numeric redaction", async () => {
  const vite = await createServer({
    appType: "custom", logLevel: "silent", server: { middlewareMode: true },
  });
  try {
    const { MacroOverview } = await vite.ssrLoadModule("/src/components/MacroOverview.jsx");
    const { BanksPanel } = await vite.ssrLoadModule("/src/components/WorldPanels.jsx");
    const { NewsPanel } = await vite.ssrLoadModule("/src/components/InformationPanels.jsx");
    const { RunHeader } = await vite.ssrLoadModule("/src/components/RunHeader.jsx");
    const macro = renderToStaticMarkup(React.createElement(MacroOverview, {
      metrics: { unemployment: [{ tick: 368, value: 0.9699421965 }] },
    }));
    const banks = renderToStaticMarkup(React.createElement(BanksPanel, { banks: [{
      id: 1, name: "Northstar Bank", deposits_cents: 100, reserves_cents: 50,
      reserve_ratio: 0.5, avg_trust: 0.702131, status: "open",
    }] }));
    const news = renderToStaticMarkup(React.createElement(NewsPanel, { news: [{
      id: 3, tick: 7, outlet_name: "Ledger", headline: "Grounded headline",
      body: "Grounded body", numeric_claims_redacted: true,
    }] }));
    const header = renderToStaticMarkup(React.createElement(RunHeader, {
      status: {
        tick: 368, status: "paused", running: false,
        active_tick: 369, next_phase: "MORNING", governor: {},
      },
      participant: {}, connected: true, loading: false,
      act: async () => {}, onShock: () => {}, onReplay: () => {},
    }));

    assert.match(macro, /97\.0%/);
    assert.match(
      macro,
      /Living, non-retired working-age citizens without active employment or an operating firm/,
    );
    assert.match(banks, /0\.7021 \(70\.21%\)/);
    assert.match(news, /unsupported number removed/);
    assert.match(header, /partial day 369/);
    assert.match(header, /MORNING/);
    assert.match(header, />368</);
  } finally {
    await vite.close();
  }
});


test("agent directory renders a bounded population page and encodes server filters", async () => {
  const vite = await createServer({ appType: "custom", logLevel: "silent", server: { middlewareMode: true } });
  try {
    const { AgentsPanel, agentDirectoryPath } = await vite.ssrLoadModule("/src/components/AgentsPanel.jsx");
    assert.equal(
      agentDirectoryPath({ filter: "Ada Core", tier: "core", afterId: 100 }),
      "/api/agents?limit=100&q=Ada+Core&population_tier=core&after_id=100",
    );

    const markup = renderToStaticMarkup(React.createElement(AgentsPanel, {
      initialDirectory: {
        items: [{
          id: 101, name: "Ada Scale", kind: "citizen", occupation: "engineer",
          role: null, region_key: "northstar", population_tier: "core", age: 35,
          health: "healthy", alive: 1, retired: 0,
        }],
        total: 1000, population_total: 1000, limit: 100, next_after_id: 101,
      },
      participant: { enabled: false }, status: { tick: 0, running: false },
      act: async () => {},
    }));
    assert.match(markup, /Agents · 1000/);
    assert.match(markup, /1–1 of 1000 matching agents/);
    assert.match(markup, /Inspect Ada Scale/);
    assert.match(markup, /northstar/);
    assert.match(markup, /core/);
    assert.match(markup, />Next<\/button>/);
  } finally {
    await vite.close();
  }
});


test("agent detail failures clear stale data and render an alert", async () => {
  const vite = await createServer({ appType: "custom", logLevel: "silent", server: { middlewareMode: true } });
  try {
    const {
      AgentModal,
      applyAgentDetailFailure,
    } = await vite.ssrLoadModule("/src/components/AgentsPanel.jsx");
    const updates = [];
    const message = applyAgentDetailFailure(
      new Error("detail unavailable"),
      value => updates.push(["detail", value]),
      value => updates.push(["error", value]),
      { clearDetail: true },
    );
    assert.equal(message, "detail unavailable");
    assert.deepEqual(updates, [
      ["detail", null],
      ["error", "detail unavailable"],
    ]);

    const markup = renderToStaticMarkup(React.createElement(AgentModal, {
      detail: {
        agent: { id: 1, name: "Ada", kind: "citizen", alive: 1 },
        accounts: [], loans: [], beliefs: {}, belief_history: [], memories: [],
        recent_decisions: [], recent_actions: [], output_counts: {}, output_cursors: {},
      },
      error: "Older actions could not be loaded.",
      participant: { enabled: false }, running: false, historyLoading: false,
      onLoadOlder: () => {}, onLoadOlderOutputs: () => {},
      onTakeControl: () => {}, onClose: () => {},
    }));
    assert.match(markup, /role="alert"/);
    assert.match(markup, /Older actions could not be loaded\./);

    const source = await readFile(
      new URL("../src/components/AgentsPanel.jsx", import.meta.url), "utf8",
    );
    assert.ok((source.match(/catch \(reason\)/g) || []).length >= 3);
  } finally {
    await vite.close();
  }
});

test("agent modal requests ignore stale agent and cursor responses", async () => {
  const source = await readFile(
    new URL("../src/components/AgentsPanel.jsx", import.meta.url), "utf8",
  );
  assert.match(source, /const detailRequest = useRef\(0\)/);
  assert.match(source, /requestId !== detailRequest\.current/);
  assert.match(source, /current\?\.agent\?\.id !== agentId/);
  assert.match(source, /current\?\.participantHistory\?\.next_before_id !== cursor/);
  assert.match(source, /current\?\.output_cursors\?\.\[kind\] !== cursor/);
  // The inner button stops the click reaching the row, so one click inspects once.
  assert.match(source, /onClick=\{event => \{ event\.stopPropagation\(\); inspect\(agent\.id\); \}\}/);
  assert.match(source, /setDetail\(\{ \.\.\.agentDetail, participantHistory: null \}\)/);
  assert.match(source, /clearDetail: false/);
  assert.match(source, /async function takeControl\(agentId\) \{\s*const requestId = \+\+detailRequest\.current/);
  assert.match(source, /if \(requestId !== detailRequest\.current\) return;\s*setDetail\(null\)/);
});


test("run header distinguishes an enforced MiniMax M3 route from a hybrid run", async () => {
  const vite = await createServer({ appType: "custom", logLevel: "silent", server: { middlewareMode: true } });
  try {
    const { RunHeader } = await vite.ssrLoadModule("/src/components/RunHeader.jsx");
    const base = {
      tick: 0, status: "paused", governor: { level: 0, cap_usd: 5, total_spend_usd: 0 },
    };
    const props = {
      participant: { active: false }, connected: true, loading: false,
      act: async () => {}, onShock: () => {}, onReplay: () => {},
    };
    const live = renderToStaticMarkup(React.createElement(RunHeader, {
      ...props,
      status: { ...base, provider_readiness: {
        ready: true, mode: "network", routed_providers: ["minimax"],
        route_contract: {
          enforced: true, provider: "minimax", model: "MiniMax-M3",
          scope: "all_gateway_routes",
        },
      } },
    }));
    assert.match(live, /LIVE · MiniMax-M3/);
    assert.doesNotMatch(live, /HYBRID/);

    const hybrid = renderToStaticMarkup(React.createElement(RunHeader, {
      ...props,
      status: { ...base, provider_readiness: {
        ready: true, mode: "network", routed_providers: ["minimax", "scripted"],
        route_contract: { enforced: false },
      } },
    }));
    assert.match(hybrid, /HYBRID · minimax \+ scripted/);
  } finally {
    await vite.close();
  }
});


test("disabled institutional projections hide retained legal and political rows", async () => {
  const vite = await createServer({ appType: "custom", logLevel: "silent", server: { middlewareMode: true } });
  try {
    const { InstitutionalPulse, LegalPoliticalPanels } = await vite.ssrLoadModule("/src/components/V2Observatory.jsx");
    const pulse = renderToStaticMarkup(React.createElement(InstitutionalPulse, {
      legal: {
        enabled: false,
        contracts: [],
        items: [{ id: 9, title: "Retained docket entry", status: "filed" }],
      },
      politics: {
        enabled: false,
        institutional_actions_enabled: false,
        bills: [{ id: 10, title: "Retained bill" }],
      },
      information: {},
      datasets: {},
    }));
    assert.match(pulse, /Legal institution disabled for this run profile/);
    assert.doesNotMatch(pulse, /Retained docket entry/);

    const panels = renderToStaticMarkup(React.createElement(LegalPoliticalPanels, {
      legal: { contracts: [], obligations: [] },
      politics: {
        enabled: false,
        institutional_actions_enabled: false,
        bills: [{ id: 10, title: "Retained bill" }],
        lobbying: { items: [] },
      },
      information: {},
      startups: {},
      markets: {},
    }));
    assert.match(panels, /Institutional role actions are disabled for this run profile/);
    assert.doesNotMatch(panels, /Retained bill/);
  } finally {
    await vite.close();
  }
});


test("run header does not label incomplete network readiness as hybrid", async () => {
  const vite = await createServer({ appType: "custom", logLevel: "silent", server: { middlewareMode: true } });
  try {
    const { RunHeader } = await vite.ssrLoadModule("/src/components/RunHeader.jsx");
    const props = {
      participant: { active: false }, connected: true, loading: false,
      act: async () => {}, onShock: () => {}, onReplay: () => {},
    };
    const base = {
      tick: 0, status: "paused", governor: { level: 0, cap_usd: 5, total_spend_usd: 0 },
    };
    for (const providerReadiness of [
      { ready: false, mode: "network", routed_providers: ["minimax"] },
      { ready: true, mode: "network", routed_providers: [] },
    ]) {
      const markup = renderToStaticMarkup(React.createElement(RunHeader, {
        ...props,
        status: { ...base, provider_readiness: providerReadiness },
      }));
      assert.match(markup, /UNAVAILABLE · provider routing/);
      assert.doesNotMatch(markup, /HYBRID/);
    }
  } finally {
    await vite.close();
  }
});


test("agent directory starts loading before debounce and each row offers one keyboard stop", async () => {
  const vite = await createServer({ appType: "custom", logLevel: "silent", server: { middlewareMode: true } });
  try {
    const {
      AgentsPanel,
      scheduleAgentDirectoryRefresh,
    } = await vite.ssrLoadModule("/src/components/AgentsPanel.jsx");
    const order = [];
    let scheduledLoad = null;
    const timer = scheduleAgentDirectoryRefresh({
      setLoading: value => order.push(`loading:${value}`),
      schedule: (load, delay) => {
        order.push(`scheduled:${delay}`);
        scheduledLoad = load;
        return 42;
      },
      load: () => order.push("loaded"),
    });

    assert.equal(timer, 42);
    assert.deepEqual(order, ["loading:true", "scheduled:180"]);
    scheduledLoad();
    assert.deepEqual(order, ["loading:true", "scheduled:180", "loaded"]);

    // A focusable row plus its named "Inspect" button used to cost two tab stops
    // per agent, the first of them unnamed. The button is the only keyboard path.
    const markup = renderToStaticMarkup(React.createElement(AgentsPanel, {
      initialDirectory: {
        items: [
          { id: 17, name: "Ada Scale", kind: "citizen", occupation: "engineer", health: "healthy", alive: 1 },
          { id: 18, name: "Ben Ledger", kind: "citizen", occupation: "clerk", health: "healthy", alive: 1 },
        ],
        total: 2, population_total: 2, limit: 100, next_after_id: null,
      },
      participant: { enabled: false }, status: { tick: 0, running: false },
      act: async () => {},
    }));
    const rows = markup.match(/<tr[^>]*>/g).filter(row => !/<th/.test(markup.slice(markup.indexOf(row), markup.indexOf(row) + 40)));
    assert.equal((markup.match(/<tbody>[\s\S]*<\/tbody>/)[0].match(/<tr/g) || []).length, 2);
    for (const row of rows) assert.doesNotMatch(row, /tabindex|onkeydown/i);
    assert.equal((markup.match(/<button[^>]*>Inspect /g) || []).length, 2);
  } finally {
    await vite.close();
  }
});


test("every coded kind holds a unique code and every uncoded kind says so", async () => {
  const vite = await createServer({ appType: "custom", logLevel: "silent", server: { middlewareMode: true } });
  try {
    const {
      KIND_TRUNCATION_MARK,
      codedKinds,
      kindCode,
      kindCoding,
    } = await vite.ssrLoadModule("/src/ui/format.ts");
    const { KindCode } = await vite.ssrLoadModule("/src/ui/primitives.tsx");

    /* The registry may grow; it may not quietly shrink, and no two kinds may ever
       land on one glyph — that merge is the failure the old PRMT table shipped. */
    const kinds = codedKinds();
    assert.ok(kinds.length >= 164, `registry shrank to ${kinds.length} kinds`);
    const owner = new Map();
    for (const kind of kinds) {
      const { code, exact } = kindCoding(kind);
      assert.equal(exact, true, `${kind} is registered but reported inexact`);
      assert.match(code, /^[A-Z0-9]{2,4}$/, `${kind} carries a malformed code ${code}`);
      assert.equal(
        owner.get(code), undefined,
        `${code} is shared by ${owner.get(code)} and ${kind}`,
      );
      owner.set(code, kind);
    }
    assert.equal(owner.size, kinds.length);

    /* An unregistered kind is abbreviated, never coded, and the glyph carries the
       mark that says so — `CIV…`, which cannot be mistaken for a real code the way
       a bare `CIVI` could. */
    const uncoded = "civic_x_y";
    assert.ok(!kinds.includes(uncoded), `${uncoded} is now registered; pick another`);
    const abbreviated = kindCoding(uncoded);
    assert.equal(abbreviated.exact, false);
    assert.equal(abbreviated.code, `CIV${KIND_TRUNCATION_MARK}`);
    assert.ok(abbreviated.code.endsWith(KIND_TRUNCATION_MARK));

    /* Short enough to survive whole: nothing is lost, so nothing is marked —
       whether the kind is registered (`ipo`) or not (`halt`). */
    assert.deepEqual(kindCoding("ipo"), { code: "IPO", exact: true });
    assert.ok(!kinds.includes("halt"), "halt is now registered; pick another");
    assert.deepEqual(kindCoding("halt"), { code: "HALT", exact: true });
    for (const survivor of ["IPO", "HALT"]) {
      assert.ok(!survivor.includes(KIND_TRUNCATION_MARK));
    }

    /* Kinds separated on purpose stay separated: near-homonyms, one labour pair
       that means two different things, the two information channels, and all six
       permit outcomes that an earlier table collapsed onto a single glyph. */
    const disambiguated = {
      benefit_paid: "BENP",
      benefits_paid: "BENS",
      hired: "HIRD",
      job_offer_accepted: "JOFA",
      information_published: "IPUB",
      information_exposed: "IEXP",
      business_permit_applied: "PMAP",
      business_permit_approved: "PMOK",
      business_permit_denied: "PMNO",
      business_permit_referred: "PMRF",
      business_permit_case_transferred: "PMTR",
      business_permit_abandoned: "PMAB",
      construction_project_proposed: "CPRO",
      construction_permit_submitted: "CPSB",
      construction_funding_contributed: "CFCT",
      construction_work_contributed: "CWCT",
      construction_project_cancelled: "CCAN",
      construction_project_completed: "CCMP",
    };
    const assigned = [];
    for (const [kind, code] of Object.entries(disambiguated)) {
      assert.equal(kindCode(kind), code, `${kind} no longer codes as ${code}`);
      assigned.push(kindCode(kind));
    }
    assert.equal(new Set(assigned).size, assigned.length);

    /* And the cell reports the difference: a coded kind takes the normal ink, an
       abbreviated one drops to the quieter ink and explains itself on hover. */
    const coded = renderToStaticMarkup(React.createElement(KindCode, { kind: "business_permit_denied" }));
    assert.match(coded, />PMNO</);
    assert.doesNotMatch(coded, /is-approx/);
    const approx = renderToStaticMarkup(React.createElement(KindCode, { kind: uncoded }));
    assert.match(approx, /is-approx/);
    assert.match(approx, /No code is registered for this kind, so it is shown abbreviated\./);
  } finally {
    await vite.close();
  }
});


test("the kind registry covers every kind the engine and world packages emit", async t => {
  const roots = [
    fileURLToPath(new URL("../../engine", import.meta.url)),
    fileURLToPath(new URL("../../world", import.meta.url)),
  ];
  const sources = [];
  for (const root of roots) {
    let entries;
    try {
      entries = await readdir(root, { recursive: true });
    } catch {
      /* The dashboard is also built and tested apart from the Python packages.
         Absence is a reason to skip this check, never to silently pass it. */
      return t.skip(`engine sources unavailable at ${root}`);
    }
    for (const entry of entries) {
      if (entry.endsWith(".py")) sources.push(join(root, entry));
    }
  }

  /* Every event enters the spine through `store.log_event(tick, "<kind>", ...)`,
     usually across several lines. The first argument is always the tick, so it
     can hold no comma, no quote and no closing paren — which is what lets this
     read the kind literal without parsing Python. */
  const emitted = new Map();
  for (const source of sources) {
    const text = await readFile(source, "utf8");
    const calls = text.matchAll(
      /\blog_event\(\s*[^,)"']{0,80},\s*(?:kind\s*=\s*)?"([a-z][a-z0-9_]{2,60})"/g,
    );
    for (const [, kind] of calls) {
      if (!emitted.has(kind)) emitted.set(kind, source);
    }
  }

  /* A broken reader finds nothing and would then pass vacuously. The floor is far
     below the count this currently reads (147) so that adding or retiring kinds
     never trips it, while a reader that stops working does. */
  assert.ok(
    emitted.size >= 100,
    `only ${emitted.size} kind literals found; the log_event reader is broken`,
  );

  const vite = await createServer({ appType: "custom", logLevel: "silent", server: { middlewareMode: true } });
  try {
    const { codedKinds } = await vite.ssrLoadModule("/src/ui/format.ts");
    const coded = new Set(codedKinds());
    const uncoded = [...emitted]
      .filter(([kind]) => !coded.has(kind))
      .map(([kind, source]) => `${kind} (${source})`);
    assert.deepEqual(
      uncoded, [],
      `these emitted kinds have no designed code:\n${uncoded.join("\n")}`,
    );
  } finally {
    await vite.close();
  }
});

test("freshness badge does not claim to reconnect before any connection exists", async () => {
  const vite = await createServer({ appType: "custom", logLevel: "silent", server: { middlewareMode: true } });
  try {
    const { FreshnessBadge } = await vite.ssrLoadModule("/src/components/FreshnessBadge.tsx");
    const transport = {
      runId: null, forkId: null, semanticsVersion: null, projectionVersion: null,
      policyVersion: null, viewKey: null, cursor: 0, status: "connecting", staleReason: null,
    };
    const connecting = renderToStaticMarkup(React.createElement(FreshnessBadge, { transport, tick: "live" }));
    assert.match(connecting, /Connecting: waiting for the live feed/);
    assert.doesNotMatch(connecting, /reconnecting/);

    const reconnecting = renderToStaticMarkup(React.createElement(FreshnessBadge, {
      transport: { ...transport, status: "reconnecting", staleReason: "socket_closed" }, tick: "live",
    }));
    assert.match(reconnecting, /Reconnecting: connection dropped; reconnecting/);

    const live = renderToStaticMarkup(React.createElement(FreshnessBadge, {
      transport: { ...transport, status: "live", cursor: 4 }, tick: "live",
    }));
    assert.match(live, /Live: cursor 4/);
  } finally {
    await vite.close();
  }
});

test("shock modal offers every trigger mode before the shock library has loaded", async () => {
  const vite = await createServer({ appType: "custom", logLevel: "silent", server: { middlewareMode: true } });
  try {
    const { ShockModal, shockTriggerTypes } = await vite.ssrLoadModule("/src/components/ShockModal.jsx");
    // The hook's initial library is `{ kinds: [], trigger_types: [] }`, which is truthy.
    assert.deepEqual(shockTriggerTypes({ kinds: [], trigger_types: [] }), ["shock", "trend", "conditional"]);
    assert.deepEqual(shockTriggerTypes(undefined), ["shock", "trend", "conditional"]);
    assert.deepEqual(shockTriggerTypes({ trigger_types: ["shock", "trend"] }), ["shock", "trend"]);

    const markup = renderToStaticMarkup(React.createElement(ShockModal, {
      library: { kinds: [], trigger_types: [] }, tick: 3, act: async () => {}, onClose: () => {},
    }));
    assert.deepEqual(
      markup.match(/<option value="(?:shock|trend|conditional)"/g),
      ['<option value="shock"', '<option value="trend"', '<option value="conditional"'],
    );
  } finally {
    await vite.close();
  }
});

test("institutions panel never claims to be loading a summary it does not have", async () => {
  const vite = await createServer({ appType: "custom", logLevel: "silent", server: { middlewareMode: true } });
  try {
    const { InstitutionsPanel } = await vite.ssrLoadModule("/src/components/WorldPanels.jsx");
    const missing = renderToStaticMarkup(React.createElement(InstitutionsPanel, { institutions: null }));
    assert.match(missing, /Institution summary unavailable\./);
    assert.doesNotMatch(missing, /Loading/);

    const present = renderToStaticMarkup(React.createElement(InstitutionsPanel, { institutions: {
      government: { enabled: true, tax_rate_bps: 1250, unemployment_benefit_cents: 40000, treasury_cents: 900000 },
      vc: { exists: false },
      health: { epidemic_multiplier: 1, insured_count: 3 },
    } }));
    assert.match(present, /Government/);
    assert.match(present, /12\.5%/);
    assert.doesNotMatch(present, /unavailable/);
  } finally {
    await vite.close();
  }
});

test("the stored theme is applied to the document before the first render", async () => {
  const { applyStoredTheme } = await import("../src/ui/useTheme.ts");
  const root = {
    attributes: {},
    getAttribute(name) { return this.attributes[name] ?? null; },
    setAttribute(name, value) { this.attributes[name] = value; },
  };
  const previous = { document: globalThis.document, window: globalThis.window };
  try {
    globalThis.document = { documentElement: root };
    globalThis.window = { localStorage: { getItem: key => (key === "ae-theme" ? "light" : null) } };
    assert.equal(applyStoredTheme(), "light");
    assert.equal(root.getAttribute("data-theme"), "light");

    // Unavailable storage falls back to the dark default instead of throwing.
    root.attributes = {};
    globalThis.window = { localStorage: { getItem() { throw new Error("blocked"); } } };
    assert.equal(applyStoredTheme(), "dark");
    assert.equal(root.getAttribute("data-theme"), "dark");
  } finally {
    globalThis.document = previous.document;
    globalThis.window = previous.window;
  }

  const mainSource = await readFile(new URL("../src/main.jsx", import.meta.url), "utf8");
  assert.ok(mainSource.indexOf("applyStoredTheme();") < mainSource.indexOf("createRoot("));
  // The hosted CSP forbids inline scripts, so index.html must stay script-free
  // apart from the module entry.
  const indexHtml = await readFile(new URL("../index.html", import.meta.url), "utf8");
  assert.deepEqual(indexHtml.match(/<script[^>]*>/g), ['<script type="module" src="/src/main.jsx">']);
});
