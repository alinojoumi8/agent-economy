import { lazy, Suspense, useState } from "react";
import { useObservatory } from "./hooks/useObservatory";
import { AgentsPanel } from "./components/AgentsPanel";
import { ConversationsPanel, EventsPanel, NewsPanel } from "./components/InformationPanels";
import { CostPanel, OraclePanel } from "./components/OracleAndCost";
import { ReplayModal } from "./components/ReplayModal";
import { RunHeader } from "./components/RunHeader";
import { ShockModal } from "./components/ShockModal";
import { BanksPanel, FirmsPanel, InstitutionsPanel } from "./components/WorldPanels";
import { SectionTitle } from "./components/ui";

const MacroOverview = lazy(() => import("./components/MacroOverview"));

export default function App() {
  const { data, connected, loading, error, act, refresh } = useObservatory();
  const [shockOpen, setShockOpen] = useState(false);
  const [replayOpen, setReplayOpen] = useState(false);
  const [introDismissed, setIntroDismissed] = useState(false);
  const status = data.status;
  const dayZero = status?.tick === 0 && !status?.running && !introDismissed;

  return (
    <div className="min-h-screen">
      <RunHeader status={status} connected={connected} loading={loading} act={act}
        onShock={() => setShockOpen(true)} onReplay={() => setReplayOpen(true)} />

      {error && <div role="alert" className="mx-auto mt-3 flex max-w-[1760px] items-center justify-between gap-4 rounded-xl border border-coral-300/25 bg-coral-300/[.06] px-4 py-3 text-xs text-coral-300">
        <span><strong>Observatory warning:</strong> {error}</span>
        <button className="button" onClick={() => refresh()}>Retry</button>
      </div>}

      {dayZero && <aside className="mx-auto mt-3 flex max-w-[1760px] flex-col gap-3 rounded-xl border border-mint-300/20 bg-mint-300/[.055] px-4 py-3 sm:flex-row sm:items-center">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-mint-300/25 bg-mint-300/10 text-mint-300">01</div>
        <div className="flex-1"><strong className="text-sm text-slate-200">Genesis is ready at day 0.</strong><p className="mt-0.5 text-xs leading-relaxed text-slate-500">Run the world to establish a baseline, inject a rumor, then trace conversation → trust → deposit movement → reserves.</p></div>
        <button className="button" onClick={() => setShockOpen(true)}>Prepare a shock</button>
        <button className="button" onClick={() => setIntroDismissed(true)} aria-label="Dismiss getting started">Dismiss</button>
      </aside>}

      {status?.pause_reason && <aside className="mx-auto mt-3 max-w-[1760px] rounded-xl border border-gold-300/20 bg-gold-300/[.05] px-4 py-3 text-xs text-gold-300"><strong>Run paused safely.</strong> {status.pause_reason.detail || status.pause_reason.reason}</aside>}

      <main id="main-content" className="mx-auto grid max-w-[1800px] grid-cols-12 gap-3 px-3 pb-16 pt-3 sm:px-5">
        <SectionTitle index="1" title="Economy at a glance" description="Deterministic engine measurements after each night close. Every chart uses committed run data." />
        <Suspense fallback={<div className="panel col-span-full h-36 animate-pulse" aria-label="Loading charts" />}>
          <MacroOverview metrics={data.metrics} />
        </Suspense>

        <SectionTitle index="2" title="Markets and institutions" description="Balance sheets, production, labor, fiscal policy, health, and venture capital in one causal surface." />
        <BanksPanel banks={data.banks} />
        <FirmsPanel firms={data.firms} />
        <InstitutionsPanel institutions={data.institutions} />

        <SectionTitle index="3" title="Information layer" description="Compare what agents read and repeat against the event spine that records what actually happened." />
        <NewsPanel news={data.news} />
        <ConversationsPanel conversations={data.conversations} />
        <EventsPanel events={data.events} onShock={() => setShockOpen(true)} />

        <SectionTitle index="4" title="Forecasting and operations" description="Interrogate the read-only Oracle while monitoring provider readiness, caching, calls, and cost." />
        <OraclePanel oracle={data.oracle} act={act} />
        <CostPanel cost={data.cost} readiness={status?.provider_readiness} />

        <SectionTitle index="5" title="People" description="Audit any persona from identity through balances, beliefs, memory, and exact decision prompts." />
        <AgentsPanel agents={data.agents} />
      </main>

      {shockOpen && <ShockModal library={data.shocks?.library} tick={status?.tick || 0} act={act} onClose={() => setShockOpen(false)} />}
      {replayOpen && <ReplayModal onClose={() => setReplayOpen(false)} />}
    </div>
  );
}
