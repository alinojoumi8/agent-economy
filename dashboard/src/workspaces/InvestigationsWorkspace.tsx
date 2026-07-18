import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { projectionApi, workspaceApi } from "../app/api";
import type { CausalEdge, CausalNode, StableReference } from "../generated/worldOs";
import { CausalGraph } from "../visualizations/CausalGraph";

type EventPage = { items: Array<{ id: number; tick: number; kind: string; phase: string }> };
type CausalData = {
  root: StableReference;
  nodes: CausalNode[];
  edges: CausalEdge[];
  semantic_rows: Array<Record<string, any>>;
  truncated: boolean;
};
type Investigation = {
  id: string; title: string; version: number; items: Array<Record<string, any>>;
  hypotheses: Array<{ id: string; statement: string; status: string }>;
};

function refKey(ref: StableReference | null): string | null {
  return ref ? `${ref.kind}:${ref.id}` : null;
}

export function InvestigationsWorkspace() {
  const { runId = "run", investigationId } = useParams();
  const [search, setSearch] = useSearchParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const tick = search.get("tick") || "live";
  const relation = search.get("relation") || "";
  const authority = search.get("authority") || "";
  const [selected, setSelected] = useState<StableReference | null>(null);
  const [hypothesis, setHypothesis] = useState("");

  const events = useQuery({
    queryKey: ["world-os", runId, "investigation-events", tick],
    queryFn: ({ signal }) => projectionApi<EventPage>(
      `/api/v2/events?tick=${encodeURIComponent(tick)}&limit=200`, signal),
  });
  const requestedEvent = Number(search.get("event") || 0);
  const fallbackEvent = [...(events.data?.data.items || [])].reverse().find(
    item => item.kind === "goods_sale") || events.data?.data.items.at(-1);
  const rootKind = search.get("kind") || "event";
  const rootId = Number(search.get("id") || requestedEvent || fallbackEvent?.id || 0);
  const causal = useQuery({
    queryKey: ["world-os", runId, "causal", rootKind, rootId, tick, relation, authority],
    queryFn: ({ signal }) => projectionApi<CausalData>(
      `/api/v2/causal/${encodeURIComponent(rootKind)}/${rootId}?tick=${encodeURIComponent(tick)}&depth=5&truth=true&relations=${encodeURIComponent(relation)}&authority=${encodeURIComponent(authority)}`,
      signal),
    enabled: rootId > 0,
  });
  const selectedKey = refKey(selected || causal.data?.data.root || null);
  const selectedRow = useMemo(() => causal.data?.data.semantic_rows.find(
    row => refKey(row.stable_ref) === selectedKey), [causal.data, selectedKey]);
  const selectedEdges = causal.data?.data.edges.filter(edge =>
    refKey(edge.source) === selectedKey || refKey(edge.target) === selectedKey) || [];

  const session = useQuery({
    queryKey: ["world-os", "operator-session"],
    queryFn: () => workspaceApi<{ owner_id: string; csrf_token: string }>("/api/v2/operator/session"),
  });
  const investigations = useQuery({
    queryKey: ["world-os", runId, "investigations"],
    queryFn: () => workspaceApi<{ items: Investigation[] }>("/api/v2/operator/investigations"),
  });
  const currentInvestigation = investigations.data?.items.find(item => item.id === investigationId);
  const refreshWorkspace = () => queryClient.invalidateQueries({ queryKey: ["world-os", runId, "investigations"] });
  const createInvestigation = useMutation({
    mutationFn: () => workspaceApi<Investigation>("/api/v2/operator/investigations", {
      method: "POST", headers: { "X-CSRF-Token": session.data?.csrf_token || "" },
      body: JSON.stringify({ title: `Investigation at ${rootKind}:${rootId}`, pinned_tick: causal.data?.tick }),
    }),
    onSuccess: record => { refreshWorkspace(); navigate(`/runs/${runId}/investigations/${record.id}?${search}`); },
  });
  const pinEvidence = useMutation({
    mutationFn: () => workspaceApi(
      `/api/v2/operator/investigations/${investigationId}/items`, {
        method: "POST", headers: { "X-CSRF-Token": session.data?.csrf_token || "" },
        body: JSON.stringify({
          item_kind: selected?.kind || causal.data?.data.root.kind,
          stable_ref: selected || causal.data?.data.root,
          note: "Pinned from synchronized causal graph and semantic table",
        }),
      }),
    onSuccess: refreshWorkspace,
  });
  const addHypothesis = useMutation({
    mutationFn: () => workspaceApi(
      `/api/v2/operator/investigations/${investigationId}/hypotheses`, {
        method: "POST", headers: { "X-CSRF-Token": session.data?.csrf_token || "" },
        body: JSON.stringify({ statement: hypothesis, status: "open" }),
      }),
    onSuccess: () => { setHypothesis(""); refreshWorkspace(); },
  });

  const setFilter = (key: string, value: string) => {
    const next = new URLSearchParams(search);
    if (value) next.set(key, value); else next.delete(key);
    setSearch(next);
  };
  return <section>
    <div className="world-os-heading">
      <div><p className="world-os-kicker">Evidence, authority, consequence</p><h2>Investigations</h2></div>
      <div className="world-os-investigation-actions">
        {!currentInvestigation && <button className="button" disabled={!rootId || createInvestigation.isPending} onClick={() => createInvestigation.mutate()}>Create investigation</button>}
        {currentInvestigation && <button className="button" disabled={!selectedKey || pinEvidence.isPending} onClick={() => pinEvidence.mutate()}>Pin selected evidence</button>}
      </div>
    </div>
    <div className="world-os-filters" aria-label="Causal filters">
      <label>Relation <select value={relation} onChange={event => setFilter("relation", event.target.value)}><option value="">All</option><option>observed</option><option>triggered</option><option>motivated</option><option>settled</option><option>cited</option></select></label>
      <label>Authority <select value={authority} onChange={event => setFilter("authority", event.target.value)}><option value="">All</option><option>engine</option><option>actor_claim</option><option>model_inference</option></select></label>
      <label>Root event <input inputMode="numeric" value={rootId || ""} onChange={event => {
        const next = new URLSearchParams(search); next.set("event", event.target.value.replace(/\D/g, "")); setSearch(next);
      }} /></label>
    </div>
    {!rootId && !events.isLoading && <div className="world-os-empty"><h3>No causal root yet</h3><p>Run the world or enter an event ID to begin a bounded trace.</p></div>}
    {causal.isLoading && <div className="world-os-loading" aria-label="Loading causal graph" />}
    {causal.error && <div className="world-os-error" role="alert">{causal.error.message}</div>}
    {causal.data && <div className="world-os-investigation-grid">
      <article className="world-os-panel world-os-graph-panel">
        <header><div><p className="world-os-kicker">Bounded trace</p><h3>Causal graph</h3></div><span>{causal.data.data.nodes.length} nodes</span></header>
        <CausalGraph nodes={causal.data.data.nodes} edges={causal.data.data.edges} selected={selectedKey} onSelect={setSelected} />
        {causal.data.data.truncated && <p className="world-os-alert">Traversal reached its safety bound. Narrow filters or choose a closer root.</p>}
      </article>
      <article className="world-os-panel world-os-semantic-panel">
        <header><div><p className="world-os-kicker">Same selection, precise values</p><h3>Semantic table</h3></div></header>
        <div className="world-os-table-wrap"><table><thead><tr><th>Tick</th><th>Kind</th><th>ID</th><th>Label</th></tr></thead><tbody>
          {causal.data.data.semantic_rows.map(row => <tr key={refKey(row.stable_ref) || row.id} className={refKey(row.stable_ref) === selectedKey ? "selected" : ""}>
            <td>{row.tick}</td><td><button onClick={() => setSelected(row.stable_ref)}>{row.kind}</button></td><td>{row.id}</td><td>{row.label}</td>
          </tr>)}
        </tbody></table></div>
      </article>
      <aside className="world-os-evidence">
        <p className="world-os-kicker">Evidence inspector</p><h3>{selectedKey || "Select evidence"}</h3>
        {selectedRow && <pre>{JSON.stringify(selectedRow, null, 2)}</pre>}
        {selectedEdges.map(edge => <div className="world-os-edge-card" key={edge.id}><strong>{edge.relation}</strong><span>{edge.authority} · confidence {edge.confidence}</span><small>{edge.method || "engine-recorded"}</small></div>)}
        <p className="world-os-policy-note">Truth-mode message reads are audit-gated. Analyst notes remain in the separate operator workspace and never mutate replay truth.</p>
      </aside>
    </div>}
    {currentInvestigation && <article className="world-os-panel world-os-hypotheses">
      <header><div><p className="world-os-kicker">Observer-owned workspace</p><h3>{currentInvestigation.title}</h3></div><span>v{currentInvestigation.version}</span></header>
      <ul>{currentInvestigation.hypotheses.map(item => <li key={item.id}><span>{item.status}</span>{item.statement}</li>)}</ul>
      <form onSubmit={event => { event.preventDefault(); if (hypothesis.trim()) addHypothesis.mutate(); }}>
        <label htmlFor="hypothesis">New hypothesis</label><textarea id="hypothesis" value={hypothesis} onChange={event => setHypothesis(event.target.value)} maxLength={2000} />
        <button className="button" disabled={!hypothesis.trim() || addHypothesis.isPending}>Add hypothesis</button>
      </form>
    </article>}
  </section>;
}
