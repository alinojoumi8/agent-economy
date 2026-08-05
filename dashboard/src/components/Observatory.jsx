import { lazy, Suspense, useState } from "react";
import { useObservatory } from "../hooks/useObservatory";
import { AgentsPanel } from "./AgentsPanel";
import { AcceptancePanel } from "./AcceptancePanel";
import { ConversationsPanel, EventsPanel, NewsPanel } from "./InformationPanels";
import { CalibrationPanel, CostPanel, OraclePanel } from "./OracleAndCost";
import { ReplayModal } from "./ReplayModal";
import { RunHeader } from "./RunHeader";
import { ParticipantPanel } from "./ParticipantPanel";
import { ShockModal } from "./ShockModal";
import { BanksPanel, FirmsPanel, InstitutionsPanel } from "./WorldPanels";
import { EconomicMap, InstitutionalPulse, LegalPoliticalPanels } from "./V2Observatory";
import { SectionTitle } from "./ui";

const MacroOverview = lazy(() => import("./MacroOverview"));

export function Observatory({ hostedSession = null }) {
  const hosted = Boolean(hostedSession);
  const canControl = !hosted || hostedSession.role === "admin";
  const { data, connected, loading, error, act, refresh } = useObservatory({ hosted });
  const [shockOpen, setShockOpen] = useState(false);
  const [replayOpen, setReplayOpen] = useState(false);
  const [introDismissed, setIntroDismissed] = useState(false);
  const status = data.status;
  const dayZero = status?.tick === 0 && !status?.running && !introDismissed;
  const participant = hosted
    ? { enabled: false, active: false, action_catalog: [] }
    : data.participant;

  return <div className="min-h-screen">
    <RunHeader status={status} participant={participant} connected={connected} loading={loading} act={act}
      hosted={hosted} canControl={canControl}
      onShock={hosted ? null : () => setShockOpen(true)}
      onReplay={hosted ? null : () => setReplayOpen(true)} />

    {error && <div role="alert" className="mx-auto mt-3 flex max-w-[1760px] items-center justify-between gap-4 rounded-xl border border-coral-300/25 bg-coral-300/[.06] px-4 py-3 text-xs text-coral-300">
      <span><strong>Observatory warning:</strong> {error}</span>
      <button className="button" onClick={() => refresh()}>Retry</button>
    </div>}

    {dayZero && <aside className="mx-auto mt-3 flex max-w-[1760px] flex-col gap-3 rounded-xl border border-mint-300/20 bg-mint-300/[.055] px-4 py-3 sm:flex-row sm:items-center">
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-mint-300/25 bg-mint-300/10 text-mint-300">01</div>
      <div className="flex-1"><strong className="text-sm text-slate-200">Genesis is ready at day 0.</strong><p className="mt-0.5 text-xs leading-relaxed text-slate-500">{hosted ? "An administrator can advance this isolated tenant run; observers have read-only access." : "Run the world to establish a baseline, inject a rumor, then trace conversation → trust → deposit movement → reserves."}</p></div>
      {!hosted && <button className="button" onClick={() => setShockOpen(true)}>Prepare a shock</button>}
      <button className="button" onClick={() => setIntroDismissed(true)} aria-label="Dismiss getting started">Dismiss</button>
    </aside>}

    {hosted && !canControl && <aside className="mx-auto mt-3 max-w-[1760px] rounded-xl border border-mint-300/20 bg-mint-300/[.04] px-4 py-3 text-xs text-mint-300"><strong>Observer access.</strong> This run is read-only; an administrator owns simulation controls.</aside>}
    {status?.pause_reason && <aside className="mx-auto mt-3 max-w-[1760px] rounded-xl border border-gold-300/20 bg-gold-300/[.05] px-4 py-3 text-xs text-gold-300"><strong>Run paused safely.</strong> {status.pause_reason.detail || status.pause_reason.reason}</aside>}

    <main id="main-content" className="mx-auto grid max-w-[1800px] grid-cols-12 gap-3 px-3 pb-16 pt-3 sm:px-5">
      <SectionTitle index="0" title="The living legal-political economy" description="Watch regional production, trade, institutions, law, information, and capital move through one deterministic event spine." />
      <EconomicMap map={data.v2?.map} />
      <InstitutionalPulse legal={data.v2?.legal} politics={data.v2?.politics} information={data.v2?.information} datasets={data.v2?.datasets} />
      <LegalPoliticalPanels legal={data.v2?.legal} politics={data.v2?.politics} information={data.v2?.information} startups={data.v2?.startups} markets={data.v2?.markets} />

      <SectionTitle index="1" title="Economy at a glance" description="Deterministic engine measurements after each night close. Every chart uses committed run data." />
      <Suspense fallback={<div className="panel col-span-full h-36 animate-pulse" aria-label="Loading charts" />}><MacroOverview metrics={data.metrics} /></Suspense>

      <SectionTitle index="2" title="Markets and institutions" description="Balance sheets, production, labor, fiscal policy, health, and venture capital in one causal surface." />
      <BanksPanel banks={data.banks} /><FirmsPanel firms={data.firms} /><InstitutionsPanel institutions={data.institutions} />

      <SectionTitle index="3" title="Information layer" description="Compare what agents read and repeat against the event spine that records what actually happened." />
      <NewsPanel news={data.news} /><ConversationsPanel conversations={data.conversations} />
      <EventsPanel events={data.events} onShock={hosted ? null : () => setShockOpen(true)} />

      <SectionTitle index="4" title="Forecasting and operations" description={hosted ? "Review sanitized forecast and provider telemetry for this tenant run." : "Interrogate the read-only Oracle while monitoring provider readiness, caching, calls, and cost."} />
      <OraclePanel oracle={data.oracle} act={act} readOnly={hosted} />
      <CostPanel cost={data.cost} readiness={status?.provider_readiness} />
      {!hosted && <CalibrationPanel calibration={data.calibration} />}
      <AcceptancePanel acceptance={data.acceptance} />

      <SectionTitle index="5" title="People" description={hosted ? "Inspect sanitized persona, balance, belief, memory, and decision provenance." : "Audit any persona from identity through balances, beliefs, memory, and exact decision prompts."} />
      {!hosted && <ParticipantPanel participant={participant} act={act} />}
      <AgentsPanel participant={participant} status={status} act={act} />
    </main>

    {!hosted && shockOpen && <ShockModal library={data.shocks?.library} tick={status?.tick || 0} act={act} onClose={() => setShockOpen(false)} />}
    {!hosted && replayOpen && <ReplayModal onClose={() => setReplayOpen(false)} />}
  </div>;
}
