import { useQuery } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { projectionApi } from "../app/api";

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

export function OverviewWorkspace() {
  const { runId = "run" } = useParams();
  const [search] = useSearchParams();
  const tick = search.get("tick") || "live";
  const query = useQuery({
    queryKey: ["world-os", runId, "overview", tick],
    queryFn: ({ signal }) => projectionApi<Overview>(
      `/api/v2/snapshot?tick=${encodeURIComponent(tick)}&domains=summary,alerts,communications,events`, signal),
  });
  if (query.isLoading) return <div className="world-os-loading" aria-label="Loading overview" />;
  if (query.error) return <div className="world-os-error" role="alert">{query.error.message}</div>;
  const envelope = query.data!;
  const data = envelope.data;
  const recent = data.events?.items || [];
  return <section>
    <div className="world-os-heading">
      <div><p className="world-os-kicker">Operational picture</p><h2>Overview</h2></div>
      <dl className="world-os-lineage">
        <div><dt>Semantics</dt><dd>{envelope.semantics_version}</dd></div>
        <div><dt>Projection</dt><dd>{envelope.projection_version}</dd></div>
        <div><dt>Policy</dt><dd>{envelope.policy_version}</dd></div>
        <div><dt>Tick</dt><dd>{envelope.tick}</dd></div>
      </dl>
    </div>
    <div className="world-os-metrics">
      <article><span>World state</span><strong>{data.summary?.status || "unknown"}</strong><small>{data.summary?.phase || "No phase"}</small></article>
      <article><span>Living agents</span><strong>{data.summary?.agents_alive ?? 0}</strong><small>{data.summary?.active_firms ?? 0} active firms</small></article>
      <article><span>Communications</span><strong>{data.communications?.total ?? 0}</strong><small>{data.communications?.published ?? 0} public / {data.communications?.private_total ?? 0} private</small></article>
      <article><span>Ledger invariant</span><strong>{data.summary?.ledger_balance === 0 ? "Balanced" : "Review"}</strong><small>{data.summary?.ledger_balance ?? 0} cents net</small></article>
    </div>
    <div className="world-os-columns">
      <article className="world-os-panel">
        <header><div><p className="world-os-kicker">Pressure queue</p><h3>Alerts</h3></div><span>{data.alerts?.length || 0}</span></header>
        <ol className="world-os-timeline">
          {(data.alerts || []).map(event => <li key={event.id}>
            <span>t{event.tick}</span><div><strong>{event.kind.replaceAll("_", " ")}</strong><small>{event.phase}</small></div>
            <Link aria-label={`Investigate event ${event.id}`} to={`/runs/${runId}/investigations?event=${event.id}`}>Trace</Link>
          </li>)}
          {!data.alerts?.length && <li className="muted">No high-importance alerts at this tick.</li>}
        </ol>
      </article>
      <article className="world-os-panel">
        <header><div><p className="world-os-kicker">Committed event spine</p><h3>Recent activity</h3></div></header>
        <ol className="world-os-timeline">
          {recent.slice(-12).reverse().map(event => <li key={event.id}>
            <span>t{event.tick}</span><div><strong>{event.kind.replaceAll("_", " ")}</strong><small>event:{event.id} · {event.phase}</small></div>
            <Link aria-label={`Open causal trace for event ${event.id}`} to={`/runs/${runId}/investigations?event=${event.id}`}>Open</Link>
          </li>)}
        </ol>
      </article>
    </div>
  </section>;
}
