import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { projectionApi, workspaceApi } from "../app/api";
import worldOsAtlas from "../assets/world-os-atlas.webp";

type EventItem = {
  id: number; tick: number; phase: string; kind: string; importance: number;
  payload: Record<string, unknown>;
};
type Overview = {
  summary?: { status: string; phase: string; active_tick: number | null; agents_alive: number; active_firms: number; ledger_balance: number };
  alerts?: EventItem[];
  communications?: { total: number; published: number; private_total: number };
  events?: { items: EventItem[] };
};
type ProviderRuntime = {
  live_only: boolean;
  global: { capacity: number; in_flight: number; queue_depth: number; peak_in_flight: number; peak_queue_depth: number; logical_deadline_s: number };
  simulated_days: { samples: number; p50_wall_ms: number | null; p95_wall_ms: number | null };
  providers: Array<{
    provider: string; capacity: number; in_flight: number; queue_depth: number; peak_in_flight: number;
    p50_queue_ms: number | null; p95_queue_ms: number | null;
    p50_response_ms: number | null; p95_response_ms: number | null;
    attempts: number; failures: number; rate_limits: number; fallbacks: number; cooldown_remaining_s: number;
  }>;
};

function title(value: string) {
  return value.replaceAll("_", " ").replace(/\b\w/g, letter => letter.toUpperCase());
}

export function OverviewWorkspace() {
  const { runId = "run" } = useParams();
  const [search] = useSearchParams();
  const [activityMode, setActivityMode] = useState<"alerts" | "recent">("alerts");
  const [selectedEventId, setSelectedEventId] = useState<number | null>(null);
  const tick = search.get("tick") || "live";
  const query = useQuery({
    queryKey: ["world-os", runId, "overview", tick],
    queryFn: ({ signal }) => projectionApi<Overview>(
      "/api/v2/snapshot?tick=" + encodeURIComponent(tick) + "&domains=summary,alerts,communications,events", signal),
  });
  const runtimeQuery = useQuery({
    queryKey: ["llm-runtime", runId],
    queryFn: ({ signal }) => workspaceApi<ProviderRuntime>("/api/llm/runtime", { signal }),
    refetchInterval: tick === "live" ? 2000 : false,
  });
  if (query.isLoading) return <div className="world-os-loading" aria-label="Loading overview" />;
  if (query.error) return <div className="world-os-error" role="alert">{query.error.message}</div>;

  const envelope = query.data!;
  const data = envelope.data;
  const alerts = data.alerts || [];
  const recent = [...(data.events?.items || [])].slice(-12).reverse();
  const activity = activityMode === "alerts" ? alerts : recent;
  const selectedEvent = activity.find(event => event.id === selectedEventId) || activity[0];
  const historicalSuffix = tick === "live" ? "" : "?tick=" + encodeURIComponent(tick);
  const traceUrl = (event: EventItem) =>
    "/runs/" + encodeURIComponent(runId) + "/investigations?event=" + event.id + (tick === "live" ? "" : "&tick=" + encodeURIComponent(tick));
  const switchActivity = (mode: "alerts" | "recent") => {
    setActivityMode(mode);
    const first = mode === "alerts" ? alerts[0] : recent[0];
    setSelectedEventId(first?.id ?? null);
  };

  return <section className="world-os-overview">
    <article className="world-os-hero">
      <img src={worldOsAtlas} alt="" aria-hidden="true" />
      <div className="world-os-hero-scrim" />
      <div className="world-os-hero-content">
        <div className="world-os-hero-status"><span className="world-os-live-dot" />{tick === "live" ? "Live world model" : "Historical world model · tick " + tick}</div>
        <p className="world-os-kicker">Operational picture</p>
        <h2>Overview</h2>
        <p className="world-os-hero-lede">See the world change, then follow the exact path from information to decision, event, and ledger.</p>
        <div className="world-os-hero-actions">
          <Link className="world-os-action-primary" to={"/runs/" + encodeURIComponent(runId) + "/investigations" + historicalSuffix}>Open causal explorer <span>↗</span></Link>
          <Link className="world-os-action-secondary" to={"/runs/" + encodeURIComponent(runId) + "/news-communications" + historicalSuffix}>Inspect communications</Link>
        </div>
      </div>
      <dl className="world-os-lineage">
        <div><dt>Semantics</dt><dd>{envelope.semantics_version}</dd></div>
        <div><dt>Projection</dt><dd>{envelope.projection_version}</dd></div>
        <div><dt>Policy</dt><dd>{envelope.policy_version}</dd></div>
        <div><dt>Tick</dt><dd>{envelope.tick}</dd></div>
      </dl>
    </article>

    <div className="world-os-metrics" aria-label="World summary">
      <Link to={"/runs/" + encodeURIComponent(runId) + "/world" + historicalSuffix}>
        <span className="world-os-metric-label"><i className="world-os-metric-signal world-os-metric-signal--mint" />World state</span>
        <strong>{title(data.summary?.status || "unknown")}</strong>
        <small>{title(data.summary?.phase || "No phase")}</small><b aria-hidden="true">↗</b>
      </Link>
      <Link to={"/runs/" + encodeURIComponent(runId) + "/people" + historicalSuffix}>
        <span className="world-os-metric-label"><i className="world-os-metric-signal" />Living agents</span>
        <strong>{data.summary?.agents_alive ?? 0}</strong>
        <small>{data.summary?.active_firms ?? 0} active firms</small><b aria-hidden="true">↗</b>
      </Link>
      <Link to={"/runs/" + encodeURIComponent(runId) + "/news-communications" + historicalSuffix}>
        <span className="world-os-metric-label"><i className="world-os-metric-signal world-os-metric-signal--amber" />Communications</span>
        <strong>{data.communications?.total ?? 0}</strong>
        <small>{data.communications?.published ?? 0} public · {data.communications?.private_total ?? 0} private</small><b aria-hidden="true">↗</b>
      </Link>
      <Link to={selectedEvent ? traceUrl(selectedEvent) : "/runs/" + encodeURIComponent(runId) + "/investigations" + historicalSuffix}>
        <span className="world-os-metric-label"><i className={"world-os-metric-signal " + (data.summary?.ledger_balance === 0 ? "world-os-metric-signal--mint" : "world-os-metric-signal--coral")} />Ledger invariant</span>
        <strong>{data.summary?.ledger_balance === 0 ? "Balanced" : "Review"}</strong>
        <small>{data.summary?.ledger_balance ?? 0} cents net</small><b aria-hidden="true">↗</b>
      </Link>
    </div>

    <section className="world-os-provider-deck" aria-label="Live AI provider lanes">
      <header>
        <div><p className="world-os-kicker">Live inference fabric</p><h3>Provider lanes</h3></div>
        {runtimeQuery.data && <div className="world-os-provider-global">
          <span>{runtimeQuery.data.live_only ? "Live only" : "Mixed mode"}</span>
          <strong>{runtimeQuery.data.global.in_flight}/{runtimeQuery.data.global.capacity}</strong>
          <small>
            {runtimeQuery.data.global.queue_depth} queued · peak {runtimeQuery.data.global.peak_in_flight}
            {runtimeQuery.data.simulated_days.p50_wall_ms == null ? "" : " · day p50 " + (runtimeQuery.data.simulated_days.p50_wall_ms / 1000).toFixed(1) + "s"}
          </small>
        </div>}
      </header>
      {runtimeQuery.error && <p className="world-os-policy-note">Runtime telemetry is temporarily unavailable.</p>}
      <div className="world-os-provider-lanes">
        {(runtimeQuery.data?.providers || []).filter(lane => !["scripted", "mock"].includes(lane.provider)).map(lane => {
          const utilization = Math.min(100, Math.round((lane.in_flight / Math.max(1, lane.capacity)) * 100));
          const state = lane.cooldown_remaining_s > 0 ? "cooldown" : lane.queue_depth > 0 ? "queued" : lane.in_flight > 0 ? "active" : "ready";
          return <article key={lane.provider} className={"world-os-provider-lane world-os-provider-lane--" + state}>
            <div className="world-os-provider-lane-head"><span className="world-os-live-dot" /><strong>{title(lane.provider)}</strong><em>{state}</em></div>
            <div className="world-os-provider-capacity"><span style={{ width: utilization + "%" }} /></div>
            <dl>
              <div><dt>Active</dt><dd>{lane.in_flight}/{lane.capacity}</dd></div>
              <div><dt>Queued</dt><dd>{lane.queue_depth}</dd></div>
              <div><dt>p50 wait</dt><dd>{lane.p50_queue_ms == null ? "—" : Math.round(lane.p50_queue_ms) + "ms"}</dd></div>
              <div><dt>p95 response</dt><dd>{lane.p95_response_ms == null ? "—" : (lane.p95_response_ms / 1000).toFixed(1) + "s"}</dd></div>
            </dl>
            <small>{lane.failures} failures · {lane.rate_limits} rate limits · {lane.fallbacks} fallback attempts</small>
          </article>;
        })}
        {runtimeQuery.isLoading && <div className="world-os-provider-loading">Loading live provider capacity…</div>}
      </div>
    </section>

    <div className="world-os-overview-grid">
      <article className="world-os-panel world-os-event-stream">
        <header>
          <div><p className="world-os-kicker">Committed event spine</p><h3>World activity</h3></div>
          <div className="world-os-segmented" role="group" aria-label="Activity view">
            <button aria-pressed={activityMode === "alerts"} onClick={() => switchActivity("alerts")}>Alerts <span>{alerts.length}</span></button>
            <button aria-pressed={activityMode === "recent"} onClick={() => switchActivity("recent")}>Recent <span>{recent.length}</span></button>
          </div>
        </header>
        <ol className="world-os-timeline">
          {activity.map(event => <li key={event.id} className={selectedEvent?.id === event.id ? "selected" : ""}>
            <button className="world-os-event-select" type="button" onClick={() => setSelectedEventId(event.id)} aria-pressed={selectedEvent?.id === event.id}>
              <span className="world-os-event-tick">t{event.tick}</span>
              <span className="world-os-event-copy"><strong>{title(event.kind)}</strong><small>event:{event.id} · {event.phase} · importance {event.importance}</small></span>
              <span className="world-os-event-pulse" aria-hidden="true" />
            </button>
            <Link aria-label={activityMode === "alerts" ? "Investigate event " + event.id : "Open causal trace for event " + event.id} to={traceUrl(event)}>Trace <span>→</span></Link>
          </li>)}
          {!activity.length && <li className="world-os-timeline-empty"><strong>No {activityMode} activity at this tick.</strong><small>Committed events will appear here as the world advances.</small></li>}
        </ol>
      </article>

      <aside className="world-os-event-inspector" aria-live="polite">
        <div className="world-os-inspector-orbit" aria-hidden="true"><span /><span /><i /></div>
        <p className="world-os-kicker">Event inspector</p>
        {selectedEvent ? <>
          <div className="world-os-inspector-title"><h3>{title(selectedEvent.kind)}</h3><span>#{selectedEvent.id}</span></div>
          <dl>
            <div><dt>Committed</dt><dd>Tick {selectedEvent.tick}</dd></div>
            <div><dt>Phase</dt><dd>{selectedEvent.phase}</dd></div>
            <div><dt>Importance</dt><dd>{selectedEvent.importance}</dd></div>
          </dl>
          <div className="world-os-payload"><span>Canonical payload</span><pre>{JSON.stringify(selectedEvent.payload, null, 2)}</pre></div>
          <Link className="world-os-inspector-action" to={traceUrl(selectedEvent)}>Trace causes and consequences <span>↗</span></Link>
        </> : <div className="world-os-inspector-empty"><h3>Waiting for a committed event</h3><p>The inspector never invents activity; it activates when the projection exposes an event.</p></div>}
        <p className="world-os-policy-note">Selections change only this observer view. Replay truth remains immutable.</p>
      </aside>
    </div>
  </section>;
}
