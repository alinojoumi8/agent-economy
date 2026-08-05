import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router";
import { projectionApi } from "../app/api";
import { commonObserverSearchParams, parseObserverViewState, projectionScopeParams } from "../app/observerViewState";
import { FreshnessBadge, useWorkspaceOutletContext } from "../components/FreshnessBadge";
import type { CommunicationMessage, CommunicationThread } from "../generated/worldOs";

type ThreadPage = { items: CommunicationThread[]; next_after_thread_id: number | null; truncated: boolean };
type ViewMode = "ordinary" | "agent" | "truth";

export function NewsCommunicationsWorkspace() {
  const { runId = "run", threadId } = useParams();
  const [search] = useSearchParams();
  const navigate = useNavigate();
  const observerState = useMemo(() => parseObserverViewState(search), [search]);
  const { transport } = useWorkspaceOutletContext();
  const tick = observerState.tick;
  const [mode, setMode] = useState<ViewMode>("ordinary");
  const [agentId, setAgentId] = useState("");
  const [threadQuery, setThreadQuery] = useState("");
  const [selectedMessageId, setSelectedMessageId] = useState<number | null>(null);
  const threads = useQuery({
    queryKey: ["world-os", runId, observerState.fork, "communications", tick, mode, agentId],
    queryFn: ({ signal }) => {
      const params = projectionScopeParams(observerState);
      if (mode === "truth") params.set("truth", "true");
      if (mode === "agent" && Number(agentId) > 0) params.set("agent_id", String(Number(agentId)));
      return projectionApi<ThreadPage>(`/api/v2/communications/threads?${params}`, signal);
    },
  });
  const selectedThread = useMemo(() => threads.data?.data.items.find(
    item => item.thread_id === Number(threadId)), [threadId, threads.data]);
  const visibleThreads = useMemo(() => {
    const items = threads.data?.data.items || [];
    const value = threadQuery.trim().toLowerCase();
    if (!value) return items;
    return items.filter(item => (item.subject + " " + item.status).toLowerCase().includes(value));
  }, [threadQuery, threads.data]);
  useEffect(() => {
    setSelectedMessageId(selectedThread?.messages.at(-1)?.id || null);
  }, [selectedThread]);
  const message = useQuery({
    queryKey: ["world-os", runId, observerState.fork, "message", selectedMessageId, tick, mode, agentId],
    queryFn: ({ signal }) => {
      const params = projectionScopeParams(observerState);
      if (mode === "truth") params.set("truth", "true");
      if (mode === "agent" && Number(agentId) > 0) params.set("agent_id", String(Number(agentId)));
      return projectionApi<CommunicationMessage>(
        `/api/v2/communications/messages/${selectedMessageId}?${params}`,
        signal,
      );
    },
    enabled: selectedMessageId !== null,
  });

  const changeMode = (next: ViewMode) => {
    setMode(next);
    setSelectedMessageId(null);
    const common = commonObserverSearchParams(search);
    navigate(`/runs/${encodeURIComponent(runId)}/news-communications${common.toString() ? `?${common}` : ""}`);
  };
  const openThread = (id: number) => {
    const common = commonObserverSearchParams(search);
    navigate(`/runs/${encodeURIComponent(runId)}/news-communications/${id}${common.toString() ? `?${common}` : ""}`);
  };

  return <section>
    <div className="world-os-heading">
      <div><p className="world-os-kicker">Authorized chronology</p><h2>News & Communications</h2></div>
      <div className="world-os-heading-actions">
        <FreshnessBadge transport={transport} tick={tick} envelope={threads.data} sourceLabel="Authorized communication projection" />
        <div className="world-os-view-switch" role="group" aria-label="Communication access view">
          <button aria-pressed={mode === "ordinary"} onClick={() => changeMode("ordinary")}>Ordinary</button>
          <button aria-pressed={mode === "agent"} onClick={() => changeMode("agent")}>Agent view</button>
          <button aria-pressed={mode === "truth"} onClick={() => changeMode("truth")}>Truth inspector</button>
        </div>
      </div>
    </div>
    {mode === "agent" && <label className="world-os-agent-input">
      Agent ID <input inputMode="numeric" value={agentId} onChange={event => setAgentId(event.target.value.replace(/\D/g, ""))} placeholder="e.g. 12" />
      <span>Only sender, delivered, public, or disclosed fields are returned.</span>
    </label>}
    {mode === "truth" && <div className="world-os-alert world-os-alert--truth" role="status">
      Truth inspection is explicit. Every private field read commits a body-free audit record outside world replay.
    </div>}
    {threads.isLoading && <div className="world-os-loading" aria-label="Loading communications" />}
    {threads.error && <div className="world-os-error" role="alert">{threads.error.message}</div>}
    <div className="world-os-communications">
      <aside className="world-os-thread-list" aria-label="Authorized threads">
        <div className="world-os-thread-tools">
          <label><span className="world-os-visually-hidden">Filter authorized threads</span><input aria-label="Filter authorized threads" value={threadQuery} onChange={event => setThreadQuery(event.target.value)} placeholder="Filter threads…" /></label>
          <span>{visibleThreads.length}</span>
        </div>
        {visibleThreads.map(thread => <button
          key={thread.thread_id}
          className={thread.thread_id === Number(threadId) ? "active" : ""}
          onClick={() => openThread(thread.thread_id)}
        >
          <span>t{thread.created_tick} · {thread.status}</span>
          <strong>{thread.subject}</strong>
          <small>{thread.authorized_message_count} authorized message{thread.authorized_message_count === 1 ? "" : "s"}</small>
        </button>)}
        {!threads.isLoading && !visibleThreads.length && <p className="muted">{threadQuery ? "No authorized threads match this filter." : "No message-specific records are authorized in this view."}</p>}
      </aside>
      <div className="world-os-thread-detail">
        {!selectedThread && <div className="world-os-empty"><h3>Select an authorized thread</h3><p>Private existence and URLs remain absent until the selected view has a valid access basis.</p></div>}
        {selectedThread && <>
          <header><div><p className="world-os-kicker">Thread {selectedThread.thread_id}</p><h3>{selectedThread.subject}</h3></div><span>{selectedThread.status}</span></header>
          <ol className="world-os-message-chronology">
            {selectedThread.messages.map(item => <li key={item.id}>
              <button onClick={() => setSelectedMessageId(item.id)} aria-pressed={selectedMessageId === item.id}>
                <span>t{item.created_tick}</span><strong>{item.sender?.name || `Agent ${item.sender_agent_id}`}</strong><small>{item.status} · {item.access_basis}</small>
              </button>
            </li>)}
          </ol>
          {message.isLoading && <div className="world-os-loading" aria-label="Loading authorized message" />}
          {message.error && <div className="world-os-error" role="alert">{message.error.message}</div>}
          {message.data && <article className="world-os-message-inspector">
            <header><div><p className="world-os-kicker">Field policy inspector</p><h4>{message.data.data.subject}</h4></div><span>{message.data.data.access_basis}</span></header>
            <p className="world-os-untrusted-label">Untrusted simulated communication</p>
            <p className="world-os-message-body">{message.data.data.body_text}</p>
            <dl>
              <div><dt>Sender</dt><dd>{message.data.data.sender?.name || message.data.data.sender_agent_id} ({message.data.data.sender?.role || "unknown"})</dd></div>
              <div><dt>Created / due</dt><dd>t{message.data.data.created_tick} / t{message.data.data.deliver_at_tick}</dd></div>
              <div><dt>Visibility</dt><dd>{message.data.data.visibility}</dd></div>
              <div><dt>Audience</dt><dd>{message.data.data.audience.map(value => JSON.stringify(value)).join(", ") || "withheld"}</dd></div>
              <div><dt>Deliveries</dt><dd>{message.data.data.deliveries.length || "withheld"}</dd></div>
              <div><dt>Disclosures</dt><dd>{message.data.data.disclosures.length || "none"}</dd></div>
            </dl>
          </article>}
        </>}
      </div>
    </div>
  </section>;
}
