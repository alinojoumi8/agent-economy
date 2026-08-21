import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link } from "react-router";

import { post } from "../api.js";
import { projectionApi, workspaceApi } from "../app/api";
import {
  commonObserverParamsFromState,
  projectionScopeParams,
} from "../app/observerViewState";
import {
  WorkspaceState,
  workspaceUrl,
  useWorkspaceProjection,
} from "./workspaceShared";
import {
  buildPulseSignals,
  buildPulseTimeline,
  ledgerInvariantState,
  normalizePulseWorld,
  pulseViewMode,
} from "./worldPulseModel.js";
import "./world-pulse.css";

type PulseEvent = {
  id: number;
  tick: number;
  phase: string;
  kind: string;
  subject_type?: string | null;
  subject_id?: number | null;
  importance: number;
  payload?: unknown;
};

type PulseSnapshot = {
  summary?: {
    status?: string;
    phase?: string;
    ledger_balance?: number;
  };
  alerts?: PulseEvent[];
  events?: { items?: PulseEvent[] };
};

type PulseWorldProjection = {
  enabled?: boolean;
  regions?: Array<{
    id: number;
    region_key?: string;
    name?: string;
    currency_code?: string | null;
    x?: number | null;
    y?: number | null;
  }>;
  agents?: Array<{ id: number; region_id?: number | null }>;
  organizations?: Array<{ id: number; active?: boolean }>;
  construction_projects?: unknown[];
  summary?: {
    trade_count?: number;
    migration_count?: number;
    construction_projects?: number;
  };
};

type RunStatus = {
  status?: string;
  running?: boolean;
};

type PulseSignal = ReturnType<typeof buildPulseSignals>[number];

const TERMINAL_STATUSES = new Set(["completed", "failed", "finished", "halted", "stopped"]);

function formatNumber(value: unknown) {
  const number = Number(value);
  return Number.isFinite(number) ? new Intl.NumberFormat("en-US").format(number) : "—";
}

function eventTraceUrl(runId: string, observerState: Parameters<typeof commonObserverParamsFromState>[0], eventId: number) {
  const params = commonObserverParamsFromState(observerState);
  params.set("event", String(eventId));
  return `/runs/${encodeURIComponent(runId)}/investigations?${params}`;
}

function regionUrl(runId: string, observerState: Parameters<typeof workspaceUrl>[2], regionId: number) {
  const target = workspaceUrl(runId, "world", observerState);
  const [path, query = ""] = target.split("?");
  const params = new URLSearchParams(query);
  params.set("region", String(regionId));
  return `${path}?${params}`;
}

function PulseAtlas({
  runId,
  observerState,
  regions,
}: {
  runId: string;
  observerState: Parameters<typeof workspaceUrl>[2];
  regions: Array<{
    id: number;
    name: string;
    key: string;
    currency: string | null;
    population: number;
    x: number | null;
    y: number | null;
  }>;
}) {
  const positionedRegions = regions.filter(region => region.x !== null && region.y !== null);
  const omittedRegions = regions.length - positionedRegions.length;
  return <section className="world-pulse-atlas" aria-labelledby="world-pulse-atlas-title">
    <header>
      <div>
        <p className="world-pulse-kicker">Committed geography</p>
        <h3 id="world-pulse-atlas-title">Regional atlas</h3>
      </div>
      <span>{omittedRegions
        ? `${positionedRegions.length} positioned · ${omittedRegions} omitted without coordinates`
        : "Schematic overview · open a region for exact evidence"}</span>
    </header>
    <div className="world-pulse-map">
      <svg viewBox="0 0 100 64" preserveAspectRatio="none" aria-hidden="true">
        <path d="M0 10H100M0 22H100M0 34H100M0 46H100M0 58H100" />
        <path d="M12 0V64M28 0V64M44 0V64M60 0V64M76 0V64M92 0V64" />
        <path className="world-pulse-map-route" d="M5 49 C22 36 30 41 43 28 S72 18 96 8" />
        <path className="world-pulse-map-route world-pulse-map-route--quiet" d="M4 16 C28 12 47 47 67 42 S84 30 98 35" />
      </svg>
      {positionedRegions.slice(0, 12).map((region, index) => <Link
        key={region.id}
        className={`world-pulse-region world-pulse-region--${(index % 3) + 1}`}
        style={{ left: `${region.x}%`, top: `${region.y}%` }}
        to={regionUrl(runId, observerState, region.id)}
        aria-label={`Open ${region.name}, ${region.population} residents`}
      >
        <span>{index + 1}</span>
        <strong>{region.name}</strong>
        <small>{formatNumber(region.population)} residents{region.currency ? ` · ${region.currency}` : ""}</small>
      </Link>)}
      {!positionedRegions.length && <div className="world-pulse-map-empty">
        <strong>{regions.length ? "No committed coordinates at this cursor" : "No committed regions at this cursor"}</strong>
        <span>{regions.length
          ? `The projection exposed ${regions.length} region${regions.length === 1 ? "" : "s"}, but the atlas does not invent missing positions.`
          : "The atlas will appear when the world projection exposes geography."}</span>
      </div>}
    </div>
  </section>;
}

function SignalRow({
  index,
  signal,
  selected,
  onSelect,
}: {
  index: number;
  signal: PulseSignal;
  selected: boolean;
  onSelect: () => void;
}) {
  const importanceWidth = Math.max(10, Math.min(100, Number(signal.importance || 0) * 25));
  return <button
    type="button"
    className={`world-pulse-signal world-pulse-signal--${signal.tone}${selected ? " is-selected" : ""}`}
    onClick={onSelect}
    aria-pressed={selected}
  >
    <span className="world-pulse-signal-index">{index + 1}</span>
    <span className="world-pulse-signal-copy">
      <small>{signal.category}</small>
      <strong>{signal.headline}</strong>
      <span>{signal.summary}</span>
    </span>
    <span className="world-pulse-salience" aria-label={`Importance ${signal.importance.toFixed(1)}`}>
      <i style={{ width: `${importanceWidth}%` }} />
    </span>
    <span className="world-pulse-signal-ref">{signal.evidenceRef || "No evidence"}</span>
  </button>;
}

export function WorldPulseWorkspace() {
  const projection = useWorkspaceProjection<PulseWorldProjection>(
    "workspace.world",
    "/api/v2/workspaces/world",
  );
  const { observerState, runId } = projection;
  const live = observerState.tick === "live";
  const snapshot = useQuery({
    queryKey: ["world-os", runId, observerState.fork, "world-pulse", observerState.tick],
    queryFn: ({ signal }) => {
      const params = projectionScopeParams(observerState);
      params.set("domains", "summary,alerts,events");
      return projectionApi<PulseSnapshot>(`/api/v2/snapshot?${params}`, signal);
    },
    retry: false,
    refetchInterval: () => (live ? 5000 : false),
  });
  const run = useQuery({
    queryKey: ["world-pulse-run-status", runId],
    queryFn: ({ signal }) => workspaceApi<RunStatus>("/api/run/status", { signal }),
    enabled: live,
    retry: false,
    refetchInterval: () => (live ? 3000 : false),
  });
  const [selectedEventId, setSelectedEventId] = useState<number | null>(null);
  const [controlError, setControlError] = useState<string | null>(null);
  const [controlPending, setControlPending] = useState(false);

  const events = snapshot.data?.data.events?.items || [];
  const signals = useMemo(() => buildPulseSignals(events), [events]);
  const selectedSignal = signals.find(signal => signal.eventId === selectedEventId) || signals[0];
  const world = useMemo(() => normalizePulseWorld(projection.data || {}), [projection.data]);
  const viewMode = pulseViewMode(observerState.tick, snapshot.data?.tick ?? projection.envelope?.tick);
  const summary = snapshot.data?.data.summary;
  const ledgerInvariant = ledgerInvariantState(summary?.ledger_balance);
  const timeline = useMemo(() => buildPulseTimeline(events), [events]);
  const terminal = TERMINAL_STATUSES.has(String(run.data?.status || "").toLowerCase());
  const hasAuthoritativeRunStatus = run.isSuccess
    && typeof run.data?.status === "string"
    && run.data.status.trim() !== ""
    && typeof run.data.running === "boolean";
  const controlsUnavailable = !hasAuthoritativeRunStatus || controlPending || terminal;

  const control = async (path: string) => {
    setControlError(null);
    setControlPending(true);
    try {
      await post(path);
      await run.refetch();
    } catch (reason) {
      setControlError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setControlPending(false);
    }
  };

  return <section className={`world-pulse${viewMode.historical ? " world-pulse--historical" : ""}`}>
    <header className="world-pulse-hero">
      <div>
        <p className="world-pulse-kicker">{viewMode.eyebrow}</p>
        <h2>World Pulse</h2>
        <p className="world-pulse-deck">What changed at this cursor, why it deserves attention, and where the evidence begins.</p>
      </div>
      <div className="world-pulse-hero-actions">
        <span className={`world-pulse-mode${viewMode.historical ? " is-historical" : ""}`}>
          <i />{viewMode.historical ? "History" : "Live"} · {viewMode.cursor}
        </span>
        {live ? <div className="world-pulse-run-controls" role="group" aria-label="Run controls">
          <button type="button" onClick={() => control("/api/run/start")} disabled={controlsUnavailable || run.data?.running === true}>Run</button>
          <button type="button" onClick={() => control("/api/run/pause")} disabled={controlsUnavailable || run.data?.running !== true}>Pause</button>
          <button type="button" onClick={() => control("/api/run/step")} disabled={controlsUnavailable || run.data?.running === true}>Step</button>
        </div> : <Link className="world-pulse-return-live" to={workspaceUrl(runId, "overview", { ...observerState, tick: "live" })}>Return to live</Link>}
        {live && !run.isLoading && !hasAuthoritativeRunStatus && <p className="world-pulse-control-error" role="status">
          Run controls unavailable until authoritative status arrives.
        </p>}
        {controlError && <p className="world-pulse-control-error" role="alert">{controlError}</p>}
      </div>
    </header>

    {viewMode.historical && <p className="world-pulse-history-notice" role="status">
      Historical context · read-only. Current provider activity and other live-only telemetry are not reconstructed here.
    </p>}

    <WorkspaceState
      loading={projection.loading || snapshot.isLoading}
      error={projection.error || (snapshot.error instanceof Error ? snapshot.error : null)}
    >
      <dl className="world-pulse-summary" aria-label="World Pulse summary">
        <div><dt>Residents</dt><dd>{formatNumber(world.population)}</dd></div>
        <div><dt>Organizations</dt><dd>{formatNumber(world.activeOrganizations)}</dd></div>
        <div><dt>Regions</dt><dd>{formatNumber(world.regions.length)}</dd></div>
        <div><dt>Salient events</dt><dd>{formatNumber(snapshot.data?.data.alerts?.length || 0)}</dd></div>
        <div className={`is-${ledgerInvariant.state}`}>
          <dt>Ledger invariant</dt>
          <dd>{ledgerInvariant.balance === null
            ? "Not reported"
            : ledgerInvariant.balance === 0
              ? "Balanced"
              : `${formatNumber(ledgerInvariant.balance)} cents`}</dd>
        </div>
      </dl>

      <div className="world-pulse-layout">
        <div className="world-pulse-main">
          <PulseAtlas runId={runId} observerState={observerState} regions={world.regions} />

          <section className="world-pulse-stories" aria-labelledby="world-pulse-stories-title">
            <header>
              <div>
                <p className="world-pulse-kicker">Committed signals</p>
                <h3 id="world-pulse-stories-title">What changed</h3>
              </div>
              <span>{events.length} public event{events.length === 1 ? "" : "s"} in this window</span>
            </header>
            <div className="world-pulse-signal-list">
              {signals.map((signal, index) => <SignalRow
                key={signal.eventId ?? "fallback"}
                index={index}
                signal={signal}
                selected={selectedSignal === signal}
                onSelect={() => setSelectedEventId(signal.eventId)}
              />)}
            </div>
          </section>
        </div>

        <aside className="world-pulse-inspector" aria-labelledby="world-pulse-inspector-title" aria-live="polite">
          <header>
            <p className="world-pulse-kicker">Evidence briefing</p>
            <h3 id="world-pulse-inspector-title">Why it matters</h3>
          </header>
          <div className={`world-pulse-inspector-signal world-pulse-inspector-signal--${selectedSignal.tone}`}>
            <span>{selectedSignal.category}</span>
            <strong>{selectedSignal.headline}</strong>
            <p>{selectedSignal.why}</p>
          </div>
          <div className="world-pulse-causal-note">
            <span aria-hidden="true">01</span>
            <p><strong>Recorded event</strong>{selectedSignal.summary}</p>
          </div>
          <div className="world-pulse-causal-note">
            <span aria-hidden="true">02</span>
            <p><strong>Interpret with care</strong>This briefing ranks salience. It does not claim causation without a trace.</p>
          </div>

          <section className="world-pulse-scope" aria-labelledby="world-pulse-scope-title">
            <h4 id="world-pulse-scope-title">Visible scope</h4>
            <dl>
              <div><dt>Residents</dt><dd>{formatNumber(world.population)}</dd></div>
              <div><dt>Regions</dt><dd>{formatNumber(world.regions.length)}</dd></div>
              <div><dt>Trade flows</dt><dd>{formatNumber(world.tradeCount)}</dd></div>
              <div><dt>Migration flows</dt><dd>{formatNumber(world.migrationCount)}</dd></div>
              <div><dt>Construction</dt><dd>{formatNumber(world.constructionCount)}</dd></div>
            </dl>
          </section>

          {selectedSignal.eventId === null
            ? <p className="world-pulse-no-evidence">No event reference is available at this cursor.</p>
            : <Link className="world-pulse-open-evidence" aria-label={`Investigate event ${selectedSignal.eventId}`} to={eventTraceUrl(runId, observerState, selectedSignal.eventId)}>
              Open evidence <span>{selectedSignal.evidenceRef}</span>
            </Link>}
        </aside>
      </div>

      <section className="world-pulse-timeline" aria-labelledby="world-pulse-timeline-title">
        <header>
          <div>
            <p className="world-pulse-kicker">Committed spine</p>
            <h3 id="world-pulse-timeline-title">Event timeline</h3>
          </div>
          <span>{viewMode.historical ? "Historical boundary" : "Live boundary"} · {viewMode.cursor}</span>
        </header>
        <div className="world-pulse-timeline-track">
          {timeline.map(event => <Link
            key={event.eventId}
            className={`world-pulse-timeline-mark${event.importance >= 3 ? " is-critical" : event.importance >= 1.5 ? " is-notice" : ""}`}
            to={eventTraceUrl(runId, observerState, event.eventId)}
            title={`${event.kind} · tick ${event.tick} · event ${event.eventId}`}
            aria-label={`Investigate ${event.kind} event ${event.eventId} at tick ${event.tick}`}
          ><i style={{ height: `${Math.max(22, Math.min(76, 20 + event.importance * 16))}%` }} /></Link>)}
          {!timeline.length && <span className="world-pulse-timeline-empty">No committed events in this window</span>}
          <span className="world-pulse-timeline-boundary" aria-hidden="true" />
        </div>
      </section>
    </WorkspaceState>
  </section>;
}
