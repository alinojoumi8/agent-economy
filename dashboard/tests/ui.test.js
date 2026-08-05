import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

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


test("agent directory starts loading before debounce and keyboard activation prevents scrolling", async () => {
  const vite = await createServer({ appType: "custom", logLevel: "silent", server: { middlewareMode: true } });
  try {
    const {
      scheduleAgentDirectoryRefresh,
      handleAgentRowKeyDown,
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

    const activation = [];
    handleAgentRowKeyDown({
      key: " ",
      preventDefault: () => activation.push("prevented"),
    }, id => activation.push(`inspected:${id}`), 17);
    assert.deepEqual(activation, ["prevented", "inspected:17"]);
  } finally {
    await vite.close();
  }
});
