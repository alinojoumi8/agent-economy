import React from "react";
import { createRoot } from "react-dom/client";

import "../../../src/design/tokens.css";
import "../../../src/index.css";
import "../../../src/civic-weather-room.css";
import { CivicCity } from "../../../src/components/CivicCity.jsx";
import { EventsPanel, NewsPanel, ConversationsPanel } from "../../../src/components/InformationPanels.jsx";
import { RunHeader } from "../../../src/components/RunHeader.jsx";
import { BanksPanel, FirmsPanel } from "../../../src/components/WorldPanels.jsx";

const firms = Array.from({ length: 24 }, (_, index) => ({
  id: index + 1,
  name: `Firm ${index + 1}`,
  sector: index % 2 ? "services" : "manufacturing",
  status: index < 3 ? "listed" : "private",
  employees: 3,
  price_cents: 500 + index,
  last_stock_price: index < 3 ? 700 + index : null,
  cash_cents: 10_000 + index,
}));

const events = Array.from({ length: 40 }, (_, index) => ({
  id: index + 1,
  tick: index + 1,
  kind: "public_statement",
  importance: index % 5 === 0 ? 3 : 1,
  payload: { actor_id: 1 },
}));

function AccessibilityHarness() {
  return <div className="civic-observatory">
    <RunHeader
      status={{
        run_id: "accessibility-test",
        tick: 1,
        status: "running",
        running: true,
        active_tick: 2,
        next_phase: "NEWSROOM",
        target_tick: 90,
        remaining_ticks: 89,
        speed_delay_s: 0,
        governor: { cap_usd: 100, total_spend_usd: 0.11, level: 0 },
        provider_readiness: {
          ready: true,
          mode: "network",
          providers: [{ name: "minimax" }],
        },
        navigation: {
          run_id: "accessibility-test",
          world_slug: "local-sandbox",
          observatory: "/",
          world_os: "/runs/accessibility-test/overview",
          commons: "/runs/accessibility-test/commons",
          join: "/join/local-sandbox",
          my_agents: "/my-agents",
        },
      }}
      participant={{}}
      connected
      loading={false}
      statusFresh
      act={async () => ({})}
      onShock={() => {}}
      onReplay={() => {}}
    />
    <main className="grid grid-cols-12 gap-3 p-3">
      <CivicCity
        variant="observatory"
        status="running"
        phase="NEWSROOM"
        tick={1}
        agents={[
          { id: 1, name: "Governor Vale", role: "central_banker", alive: 1, population_tier: "core" },
          { id: 2, name: "Dr. Amara Osei", occupation: "doctor", alive: 1, population_tier: "core" },
        ]}
        firms={firms.slice(0, 2)}
        map={{
          population_summary: { total: 2, core: 2, periphery: 0, rendered_agents: 2, clustered_agents: 0 },
          core_agents: [
            { id: 1, name: "Governor Vale", role: "central_banker", x: 0.2, y: 0.3 },
            { id: 2, name: "Dr. Amara Osei", occupation: "doctor", x: 0.7, y: 0.6 },
          ],
          firms: [],
        }}
      />
      <BanksPanel banks={[{
        id: 1,
        name: "Civic Bank",
        deposits_cents: 100_000,
        reserves_cents: 25_000,
        reserve_ratio: 0.25,
        avg_trust: 0.8,
        status: "open",
      }]} />
      <FirmsPanel firms={firms} />
      <NewsPanel news={Array.from({ length: 20 }, (_, index) => ({
        id: index + 1,
        tick: index + 1,
        outlet_name: "The Ledger",
        headline: `Story ${index + 1}`,
        body: "Grounded public information.",
      }))} />
      <ConversationsPanel conversations={Array.from({ length: 12 }, (_, index) => ({
        id: index + 1,
        tick: index + 1,
        topic: `Topic ${index + 1}`,
        messages: [{ agent_id: 1, name: "Governor Vale", text: "Stored message." }],
      }))} />
      <EventsPanel events={events} />
    </main>
  </div>;
}

export function mountAccessibilityHarness(container) {
  return createRoot(container).render(<AccessibilityHarness />);
}
