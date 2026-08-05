import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router";
import { projectionApi, workspaceApi, WorkspaceApiError } from "../app/api";
import { parseObserverViewState, projectionScopeParams } from "../app/observerViewState";
import { FreshnessBadge, useWorkspaceOutletContext } from "../components/FreshnessBadge";
import { InvestigationTitleEditor } from "../components/InvestigationTitleEditor";
import { InvestigationConflictDialog } from "../components/InvestigationConflictDialog";
import type { CausalEdge, CausalNode, StableReference } from "../generated/worldOs";
import { CausalGraph } from "../visualizations/CausalGraph";
import {
  acceptSavedInvestigation,
  cancelInvestigationEdit,
  continueInvestigationConflict,
  createInvestigationDraft,
  editInvestigationTitle,
  openInvestigationConflict,
  reloadInvestigationConflict,
  reopenInvestigationConflict,
  saveInvestigationAsNewPayload,
} from "./investigationState";

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
  run_id?: string; fork_id?: string | null; pinned_tick?: number | null;
  query?: Record<string, any>; layout?: Record<string, any> | null;
};

function refKey(ref: StableReference | null): string | null {
  return ref ? `${ref.kind}:${ref.id}` : null;
}

export function InvestigationsWorkspace() {
  const { runId = "run", investigationId } = useParams();
  const [search, setSearch] = useSearchParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const observerState = useMemo(() => parseObserverViewState(search), [search]);
  const { transport } = useWorkspaceOutletContext();
  const tick = observerState.tick;
  const relation = search.get("relation") || "";
  const authority = search.get("authority") || "";
  const [selected, setSelected] = useState<StableReference | null>(null);
  const [hypothesis, setHypothesis] = useState("");
  const [draft, setDraft] = useState<any>(null);
  const [pendingInvestigationId, setPendingInvestigationId] = useState<string | null>(null);
  const navigationDialogHeading = useRef<HTMLHeadingElement>(null);
  const titleInputRef = useRef<HTMLInputElement>(null);

  const events = useQuery({
    queryKey: ["world-os", runId, observerState.fork, "investigation-events", tick],
    queryFn: ({ signal }) => {
      const params = projectionScopeParams(observerState);
      params.set("limit", "200");
      return projectionApi<EventPage>(`/api/v2/events?${params}`, signal);
    },
  });
  const requestedEvent = Number(search.get("event") || 0);
  const fallbackEvent = [...(events.data?.data.items || [])].reverse().find(
    item => item.kind === "goods_sale") || events.data?.data.items.at(-1);
  const rootKind = search.get("kind") || "event";
  const rootId = Number(search.get("id") || requestedEvent || fallbackEvent?.id || 0);
  const causal = useQuery({
    queryKey: ["world-os", runId, observerState.fork, "causal", rootKind, rootId, tick, relation, authority],
    queryFn: ({ signal }) => {
      const params = projectionScopeParams(observerState);
      params.set("depth", "5");
      params.set("truth", "true");
      params.set("relations", relation);
      params.set("authority", authority);
      return projectionApi<CausalData>(
        `/api/v2/causal/${encodeURIComponent(rootKind)}/${rootId}?${params}`,
        signal,
      );
    },
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
  useEffect(() => {
    if (!currentInvestigation) {
      if (!investigationId) setDraft(null);
      return;
    }
    setDraft((current: any) => {
      if (!current || current.server.id !== currentInvestigation.id) {
        return createInvestigationDraft(currentInvestigation);
      }
      if (!current.dirty && !current.conflict
          && current.server.version !== currentInvestigation.version) {
        return createInvestigationDraft(currentInvestigation);
      }
      return current;
    });
  }, [currentInvestigation, investigationId]);
  useEffect(() => {
    if (pendingInvestigationId) navigationDialogHeading.current?.focus();
  }, [pendingInvestigationId]);
  const refreshWorkspace = () => queryClient.invalidateQueries({ queryKey: ["world-os", runId, "investigations"] });
  const replaceCachedInvestigation = (record: Investigation) => queryClient.setQueryData<{ items: Investigation[] }>(
    ["world-os", runId, "investigations"],
    current => current ? {
      ...current,
      items: current.items.map(item => item.id === record.id ? record : item),
    } : current,
  );
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
  const updateInvestigation = useMutation({
    mutationFn: (activeDraft: any) => workspaceApi<Investigation>(
      `/api/v2/operator/investigations/${activeDraft.server.id}`, {
        method: "PATCH", headers: { "X-CSRF-Token": session.data?.csrf_token || "" },
        body: JSON.stringify({
          expected_version: draft.server.version,
          title: activeDraft.titleDraft.trim(),
        }),
      },
    ),
    onSuccess: record => {
      setDraft((current: any) => acceptSavedInvestigation(current, record));
      replaceCachedInvestigation(record);
      refreshWorkspace();
    },
    onError: async (reason, submittedDraft) => {
      if (reason instanceof WorkspaceApiError && reason.status === 409) {
        try {
          const serverRecord = await workspaceApi<Investigation>(
            `/api/v2/operator/investigations/${submittedDraft.server.id}`,
          );
          setDraft((current: any) => current
            ? openInvestigationConflict(current, serverRecord) : current);
          return;
        } catch (refreshReason) {
          setDraft((current: any) => current ? {
            ...current,
            error: refreshReason instanceof Error
              ? refreshReason.message : "Current server version could not be loaded.",
          } : current);
          return;
        }
      }
      setDraft((current: any) => current ? {
        ...current,
        error: reason instanceof Error ? reason.message : "Workspace request failed",
      } : current);
    },
  });
  const saveInvestigationAsNew = useMutation({
    mutationFn: (activeDraft: any) => workspaceApi<Investigation>(
      "/api/v2/operator/investigations", {
        method: "POST", headers: { "X-CSRF-Token": session.data?.csrf_token || "" },
        body: JSON.stringify(saveInvestigationAsNewPayload(activeDraft)),
      },
    ),
    onSuccess: record => {
      refreshWorkspace();
      navigate(investigationPath(record.id));
    },
    onError: reason => setDraft((current: any) => current ? {
      ...current,
      error: reason instanceof Error ? reason.message : "Workspace request failed",
    } : current),
  });

  const investigationPath = (id: string) => `/runs/${encodeURIComponent(runId)}/investigations/${encodeURIComponent(id)}?${search}`;
  const chooseInvestigation = (id: string) => {
    if (id === investigationId) return;
    if (draft?.dirty) {
      setPendingInvestigationId(id);
      return;
    }
    navigate(investigationPath(id));
  };

  const setFilter = (key: string, value: string) => {
    const next = new URLSearchParams(search);
    if (value) next.set(key, value); else next.delete(key);
    setSearch(next);
  };
  return <section>
    <div className="world-os-heading">
      <div><p className="world-os-kicker">Evidence, authority, consequence</p><h2>Investigations</h2></div>
      <div className="world-os-heading-actions">
        <FreshnessBadge transport={transport} tick={tick} envelope={causal.data || events.data} sourceLabel="Causal evidence projection" />
        <div className="world-os-investigation-actions">
          {!currentInvestigation && <button className="button" disabled={!rootId || createInvestigation.isPending} onClick={() => createInvestigation.mutate()}>Create investigation</button>}
          {currentInvestigation && <button className="button" disabled={!selectedKey || pinEvidence.isPending} onClick={() => pinEvidence.mutate()}>Pin selected evidence</button>}
        </div>
      </div>
    </div>
    <div className="world-os-filters" aria-label="Causal filters">
      <label>Relation <select value={relation} onChange={event => setFilter("relation", event.target.value)}><option value="">All</option><option>observed</option><option>triggered</option><option>motivated</option><option>settled</option><option>cited</option></select></label>
      <label>Authority <select value={authority} onChange={event => setFilter("authority", event.target.value)}><option value="">All</option><option>engine</option><option>actor_claim</option><option>model_inference</option></select></label>
      <label>Root event <input inputMode="numeric" value={rootId || ""} onChange={event => {
        const next = new URLSearchParams(search); next.set("event", event.target.value.replace(/\D/g, "")); setSearch(next);
      }} /></label>
    </div>
    {investigations.data?.items.length ? <nav className="world-os-investigation-list" aria-label="Saved investigations">
      {investigations.data.items.map(item => <button type="button" key={item.id}
        className={item.id === investigationId ? "selected" : ""}
        onClick={() => chooseInvestigation(item.id)}>{item.title}<small>v{item.version}</small></button>)}
    </nav> : null}
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
      {draft && <InvestigationTitleEditor title={draft.titleDraft}
        serverTitle={draft.server.title} version={draft.server.version}
        pending={updateInvestigation.isPending} blocked={Boolean(draft.conflict)}
        error={draft.error} inputRef={titleInputRef}
        onChange={title => setDraft((current: any) => editInvestigationTitle(current, title))}
        onSave={() => updateInvestigation.mutate(draft)}
        onCancel={() => setDraft((current: any) => cancelInvestigationEdit(current))} />}
      {draft?.conflict && !draft.conflict.open && <div className="world-os-conflict-reminder" role="status">
        This draft is based on stale server version {draft.conflict.submittedVersion}.
        <button className="button" type="button" onClick={() => setDraft((current: any) => reopenInvestigationConflict(current))}>Review version conflict</button>
      </div>}
      <ul>{currentInvestigation.hypotheses.map(item => <li key={item.id}><span>{item.status}</span>{item.statement}</li>)}</ul>
      <form onSubmit={event => { event.preventDefault(); if (hypothesis.trim()) addHypothesis.mutate(); }}>
        <label htmlFor="hypothesis">New hypothesis</label><textarea id="hypothesis" value={hypothesis} onChange={event => setHypothesis(event.target.value)} maxLength={2000} />
        <button className="button" disabled={!hypothesis.trim() || addHypothesis.isPending}>Add hypothesis</button>
      </form>
    </article>}
    {draft?.conflict?.open && <InvestigationConflictDialog
      draftTitle={draft.titleDraft} serverTitle={draft.conflict.server.title}
      serverVersion={draft.conflict.server.version}
      pending={saveInvestigationAsNew.isPending} returnFocusRef={titleInputRef}
      onReload={() => {
        replaceCachedInvestigation(draft.conflict.server);
        setDraft((current: any) => reloadInvestigationConflict(current));
        refreshWorkspace();
      }}
      onSaveAsNew={() => saveInvestigationAsNew.mutate(draft)}
      onContinue={() => setDraft((current: any) => continueInvestigationConflict(current))} />}
    {pendingInvestigationId && <div className="world-os-dialog-backdrop">
      <section className="world-os-dialog" role="dialog" aria-modal="true" aria-labelledby="discard-draft-title">
        <h3 id="discard-draft-title" ref={navigationDialogHeading} tabIndex={-1}>Discard unsaved title draft?</h3>
        <p>Your title edit has not been saved. Stay here or discard it before opening another investigation.</p>
        <div className="world-os-dialog-actions">
          <button className="button button-primary" type="button" onClick={() => setPendingInvestigationId(null)}>Stay</button>
          <button className="button" type="button" onClick={() => {
            const nextId = pendingInvestigationId;
            setPendingInvestigationId(null);
            setDraft((current: any) => cancelInvestigationEdit(current));
            navigate(investigationPath(nextId));
          }}>Discard draft and continue</button>
        </div>
      </section>
    </div>}
  </section>;
}
