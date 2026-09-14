import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router";
import { projectionApi } from "../app/api";
import { commonObserverSearchParams, parseObserverViewState, projectionScopeParams } from "../app/observerViewState";
import { FreshnessBadge, useWorkspaceOutletContext } from "../components/FreshnessBadge";
import type { CommunicationMessage, CommunicationThread } from "../generated/worldOs";
import {
  THREAD_PAGE_SIZE,
  agentViewState,
  flattenThreadPages,
  nextThreadPageParam,
  routedThreadLookup,
} from "./newsCommunicationsModel.js";

type ThreadPage = { items: CommunicationThread[]; next_after_thread_id: number | null; truncated: boolean };
type ViewMode = "ordinary" | "agent" | "truth";

export function NewsCommunicationsWorkspace() {
  const { runId = "run", threadId } = useParams();
  const [search] = useSearchParams();
  const navigate = useNavigate();
  const observerState = useMemo(() => parseObserverViewState(search), [search]);
  const { transport } = useWorkspaceOutletContext();
  const tick = observerState.tick;
  const requestedMode = search.get("view");
  const mode: ViewMode = requestedMode === "agent" || requestedMode === "truth"
    ? requestedMode : "ordinary";
  // "Agent view" only exists once a positive agent id is present. Without one
  // the server serves the ordinary principal, so the UI must neither claim an
  // agent view nor request one.
  const agentView = agentViewState(mode, search.get("agent_id"));
  const agentId: string = agentView.inputValue;
  const scopeKey = agentView.agentId ?? "";
  const [threadQuery, setThreadQuery] = useState("");
  const [selectedMessageId, setSelectedMessageId] = useState<number | null>(null);
  const scopedParams = () => {
    const params = projectionScopeParams(observerState);
    if (mode === "truth") params.set("truth", "true");
    if (agentView.agentId) params.set("agent_id", agentView.agentId);
    return params;
  };
  // The server pages threads oldest-first (`after` thread id, up to 200 per
  // page). Loading only the first page hid every later thread and any deep link
  // to one, so pages are followed on demand and the truncation is named.
  const threads = useInfiniteQuery({
    queryKey: ["world-os", runId, observerState.fork, "communications", tick, mode, scopeKey],
    initialPageParam: 0,
    queryFn: ({ signal, pageParam }) => {
      const params = scopedParams();
      params.set("after", String(pageParam));
      params.set("limit", String(THREAD_PAGE_SIZE));
      return projectionApi<ThreadPage>(`/api/v2/communications/threads?${params}`, signal);
    },
    getNextPageParam: lastPage => nextThreadPageParam(lastPage.data),
    enabled: agentView.ready,
    retry: false,
  });
  const loadedThreads = useMemo(
    () => flattenThreadPages((threads.data?.pages ?? []).map(page => page.data)) as CommunicationThread[],
    [threads.data],
  );
  const routed = routedThreadLookup(threadId, loadedThreads);
  // A deep link may name a thread beyond the loaded pages. Threads are ordered
  // by id, so `after = id - 1, limit = 1` is exactly that thread when it is
  // authorized; the lookup below filters by id so a different thread is never
  // shown in its place.
  const routedThread = useQuery({
    queryKey: [
      "world-os", runId, observerState.fork, "communication-thread", tick, mode, scopeKey,
      routed.threadId,
    ],
    queryFn: ({ signal }) => {
      const params = scopedParams();
      params.set("after", String(routed.after));
      params.set("limit", "1");
      return projectionApi<ThreadPage>(`/api/v2/communications/threads?${params}`, signal);
    },
    enabled: agentView.ready && routed.threadId !== null && !routed.loaded && !threads.isLoading,
    retry: false,
  });
  const selectedThread = useMemo(() => {
    if (routed.threadId === null) return undefined;
    return loadedThreads.find(item => item.thread_id === routed.threadId)
      ?? routedThread.data?.data.items.find(item => item.thread_id === routed.threadId);
  }, [loadedThreads, routed.threadId, routedThread.data]);
  const visibleThreads = useMemo(() => {
    const value = threadQuery.trim().toLowerCase();
    if (!value) return loadedThreads;
    return loadedThreads.filter(item => (item.subject + " " + item.status).toLowerCase().includes(value));
  }, [threadQuery, loadedThreads]);
  useEffect(() => {
    setSelectedMessageId(selectedThread?.messages.at(-1)?.id || null);
  }, [selectedThread]);
  const message = useQuery({
    queryKey: ["world-os", runId, observerState.fork, "message", selectedMessageId, tick, mode, scopeKey],
    queryFn: ({ signal }) => {
      const params = scopedParams();
      return projectionApi<CommunicationMessage>(
        `/api/v2/communications/messages/${selectedMessageId}?${params}`,
        signal,
      );
    },
    enabled: selectedMessageId !== null,
    retry: false,
  });

  const communicationParams = (nextMode: ViewMode, nextAgentId = "") => {
    const params = commonObserverSearchParams(search);
    if (nextMode !== "ordinary") params.set("view", nextMode);
    if (nextMode === "agent" && Number(nextAgentId) > 0) {
      params.set("agent_id", String(Number(nextAgentId)));
    }
    return params;
  };
  const communicationRoute = (params: URLSearchParams, id?: number) => {
    const path = `/runs/${encodeURIComponent(runId)}/news-communications${id ? `/${id}` : ""}`;
    return `${path}${params.toString() ? `?${params}` : ""}`;
  };
  const changeMode = (next: ViewMode) => {
    setSelectedMessageId(null);
    navigate(communicationRoute(communicationParams(next)));
  };
  const changeAgentId = (value: string) => {
    const nextAgentId = value.replace(/\D/g, "");
    setSelectedMessageId(null);
    navigate(communicationRoute(communicationParams("agent", nextAgentId)), { replace: true });
  };
  const openThread = (id: number) => {
    navigate(communicationRoute(communicationParams(mode, agentId), id));
  };
  const listEmptyCopy = agentView.awaitingAgentId
    ? "Enter an agent id to load that agent's authorized view."
    : threadQuery
      ? "No authorized threads match this filter."
      : "No message-specific records are authorized in this view.";

  return <section>
    <div className="world-os-heading">
      <div><p className="world-os-kicker">Authorized chronology</p><h2>News & Communications</h2></div>
      <div className="world-os-heading-actions">
        <FreshnessBadge transport={transport} tick={tick} envelope={threads.data?.pages[0]} sourceLabel="Authorized communication projection" />
        <div className="world-os-view-switch" role="group" aria-label="Communication access view">
          <button type="button" aria-pressed={mode === "ordinary"} onClick={() => changeMode("ordinary")}>Ordinary</button>
          <button type="button" aria-pressed={mode === "agent"} onClick={() => changeMode("agent")}>Agent view</button>
          <button type="button" aria-pressed={mode === "truth"} onClick={() => changeMode("truth")}>Truth inspector</button>
        </div>
      </div>
    </div>
    {mode === "agent" && <label className="world-os-agent-input">
      Agent ID <input inputMode="numeric" value={agentId} onChange={event => changeAgentId(event.target.value)} placeholder="e.g. 12" />
      <span>{agentView.awaitingAgentId
        ? "No agent view is active until a positive agent id is entered."
        : "Only sender, delivered, public, or disclosed fields are returned."}</span>
    </label>}
    {mode === "truth" && <div className="world-os-alert world-os-alert--truth" role="status">
      Truth inspection is explicit. Every private field read commits a body-free audit record outside world replay.
    </div>}
    {threads.isLoading && <div className="world-os-loading" aria-label="Loading communications" />}
    {threads.error && <div className="world-os-error" role="alert">{threads.error.message}</div>}
    {routedThread.error && <div className="world-os-error" role="alert">{routedThread.error.message}</div>}
    <div className="world-os-communications">
      <aside className="world-os-thread-list" aria-label="Authorized threads">
        <div className="world-os-thread-tools">
          <label><span className="world-os-visually-hidden">Filter authorized threads</span><input aria-label="Filter authorized threads" value={threadQuery} onChange={event => setThreadQuery(event.target.value)} placeholder="Filter threads…" /></label>
          <span>{visibleThreads.length}{threads.hasNextPage ? "+" : ""}</span>
        </div>
        {visibleThreads.map(thread => <button
          key={thread.thread_id}
          className={thread.thread_id === routed.threadId ? "active" : ""}
          aria-current={thread.thread_id === routed.threadId ? "true" : undefined}
          onClick={() => openThread(thread.thread_id)}
        >
          <span>t{thread.created_tick} · {thread.status}</span>
          <strong>{thread.subject}</strong>
          <small>{thread.authorized_message_count} authorized message{thread.authorized_message_count === 1 ? "" : "s"}</small>
        </button>)}
        {!threads.isLoading && !visibleThreads.length && <p className="muted">{listEmptyCopy}</p>}
        {threads.hasNextPage && <div className="world-os-thread-more">
          <p className="muted">Showing the oldest {loadedThreads.length} authorized threads; more exist.</p>
          <button type="button" className="button" onClick={() => threads.fetchNextPage()} disabled={threads.isFetchingNextPage}>
            {threads.isFetchingNextPage ? "Loading more threads…" : "Load more authorized threads"}
          </button>
        </div>}
      </aside>
      <div className="world-os-thread-detail">
        {!selectedThread && routedThread.isLoading && <div className="world-os-loading" aria-label="Loading the requested thread" />}
        {!selectedThread && !routedThread.isLoading && <div className="world-os-empty"><h3>Select an authorized thread</h3><p>Private existence and URLs remain absent until the selected view has a valid access basis.</p></div>}
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
