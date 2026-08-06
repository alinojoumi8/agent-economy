import { useEffect, useRef, useState } from "react";
import { api, formatBeliefValue, money, number, shortKind } from "../api";
import { agentExecutionPresentation } from "../lib/agentExecution";
import { appendParticipantHistory } from "../participant";
import { Badge, Empty, Modal, Panel } from "./ui";

const AGENT_PAGE_SIZE = 100;
const EMPTY_DIRECTORY = {
  items: [], total: 0, population_total: 0, limit: AGENT_PAGE_SIZE, next_after_id: null,
};

export function agentDirectoryPath({ filter = "", tier = "", afterId = null } = {}) {
  const params = new URLSearchParams({ limit: String(AGENT_PAGE_SIZE) });
  if (filter.trim()) params.set("q", filter.trim());
  if (tier) params.set("population_tier", tier);
  if (afterId !== null && afterId !== undefined) params.set("after_id", String(afterId));
  return `/api/agents?${params.toString()}`;
}

export function scheduleAgentDirectoryRefresh({
  setLoading, schedule, load,
}) {
  setLoading(true);
  return schedule(load, 180);
}

export function handleAgentRowKeyDown(event, inspect, agentId) {
  if (event.key !== "Enter" && event.key !== " ") return;
  event.preventDefault();
  inspect(agentId);
}

export function applyAgentDetailFailure(
  reason, setDetail, setError, { clearDetail = false } = {},
) {
  const message = reason instanceof Error ? reason.message : String(reason);
  if (clearDetail) setDetail(null);
  setError(message || "Agent details could not be loaded.");
  return message || "Agent details could not be loaded.";
}

export function AgentsPanel({ agents = null, initialDirectory = null, participant, status, act }) {
  const [filter, setFilter] = useState("");
  const [tier, setTier] = useState("");
  const [cursors, setCursors] = useState([null]);
  const [pageIndex, setPageIndex] = useState(0);
  const [directory, setDirectory] = useState(() => initialDirectory || (
    Array.isArray(agents)
      ? { ...EMPTY_DIRECTORY, items: agents, total: agents.length, population_total: agents.length }
      : EMPTY_DIRECTORY
  ));
  const [directoryLoading, setDirectoryLoading] = useState(false);
  const [directoryError, setDirectoryError] = useState("");
  const [detail, setDetail] = useState(null);
  const [detailError, setDetailError] = useState("");
  const [loading, setLoading] = useState(false);
  const detailRequest = useRef(0);
  useEffect(() => {
    let active = true;
    const timer = scheduleAgentDirectoryRefresh({
      setLoading: setDirectoryLoading,
      schedule: (load, delay) => window.setTimeout(load, delay),
      load: async () => {
        try {
          const page = await api(agentDirectoryPath({
            filter, tier, afterId: cursors[pageIndex],
          }));
          if (active) {
            setDirectory(page);
            setDirectoryError("");
          }
        } catch (reason) {
          if (active) setDirectoryError(reason instanceof Error ? reason.message : String(reason));
        } finally {
          if (active) setDirectoryLoading(false);
        }
      },
    });
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [filter, tier, pageIndex, cursors, status?.tick]);

  function resetDirectory(nextFilter = filter, nextTier = tier) {
    setFilter(nextFilter);
    setTier(nextTier);
    setCursors([null]);
    setPageIndex(0);
  }

  function nextPage() {
    if (directory.next_after_id === null || directory.next_after_id === undefined) return;
    setCursors(current => [
      ...current.slice(0, pageIndex + 1), directory.next_after_id,
    ]);
    setPageIndex(current => current + 1);
  }

  async function inspect(id) {
    const requestId = ++detailRequest.current;
    setLoading(true);
    setDetail(null);
    setDetailError("");
    try {
      const agentDetail = await api(`/api/agents/${id}`);
      if (requestId !== detailRequest.current) return;
      setDetail({ ...agentDetail, participantHistory: null });
      if (participant?.enabled && agentDetail.agent?.kind === "citizen") {
        try {
          const participantHistory = await api(
            `/api/participant/history?agent_id=${id}&limit=50`);
          if (requestId !== detailRequest.current) return;
          setDetail({ ...agentDetail, participantHistory });
        } catch (reason) {
          if (requestId !== detailRequest.current) return;
          applyAgentDetailFailure(
            reason, setDetail, setDetailError, { clearDetail: false },
          );
        }
      }
    } catch (reason) {
      if (requestId !== detailRequest.current) return;
      applyAgentDetailFailure(
        reason, setDetail, setDetailError, { clearDetail: true },
      );
    } finally {
      if (requestId === detailRequest.current) setLoading(false);
    }
  }

  async function loadOlderParticipantActions() {
    const cursor = detail?.participantHistory?.next_before_id;
    if (!detail?.agent?.id || !cursor) return;
    const agentId = detail.agent.id;
    const requestId = detailRequest.current;
    setLoading(true);
    setDetailError("");
    try {
      const page = await api(
        `/api/participant/history?agent_id=${agentId}&limit=50&before_id=${cursor}`);
      setDetail(current => {
        if (requestId !== detailRequest.current
            || current?.agent?.id !== agentId
            || current?.participantHistory?.next_before_id !== cursor) return current;
        return {
          ...current,
          participantHistory: appendParticipantHistory(current.participantHistory, page),
        };
      });
    } catch (reason) {
      if (requestId !== detailRequest.current) return;
      applyAgentDetailFailure(reason, setDetail, setDetailError);
    } finally {
      if (requestId === detailRequest.current) setLoading(false);
    }
  }

  async function loadOlderAgentOutputs(kind) {
    const cursor = detail?.output_cursors?.[kind];
    if (!detail?.agent?.id || !cursor) return;
    const agentId = detail.agent.id;
    const requestId = detailRequest.current;
    setLoading(true);
    setDetailError("");
    try {
      const page = await api(
        `/api/agents/${agentId}/outputs?kind=${kind}&limit=20&before_id=${cursor}`);
      const field = kind === "model" ? "recent_decisions" : "recent_actions";
      setDetail(current => {
        if (requestId !== detailRequest.current
            || current?.agent?.id !== agentId
            || current?.output_cursors?.[kind] !== cursor) return current;
        const known = new Set((current?.[field] || []).map(item => item.id));
        return {
          ...current,
          [field]: [...(current?.[field] || []), ...page.items.filter(item => !known.has(item.id))],
          output_cursors: { ...current?.output_cursors, [kind]: page.next_before_id },
        };
      });
    } catch (reason) {
      if (requestId !== detailRequest.current) return;
      applyAgentDetailFailure(reason, setDetail, setDetailError);
    } finally {
      if (requestId === detailRequest.current) setLoading(false);
    }
  }

  async function takeControl(agentId) {
    const requestId = ++detailRequest.current;
    setLoading(true);
    setDetailError("");
    try {
      await act("/api/participant/control", {
        agent_id: agentId,
        expected_tick: status?.tick ?? 0,
      });
      if (requestId !== detailRequest.current) return;
      setDetail(null);
    } catch (reason) {
      if (requestId !== detailRequest.current) return;
      applyAgentDetailFailure(reason, setDetail, setDetailError);
    } finally {
      if (requestId === detailRequest.current) setLoading(false);
    }
  }

  const listed = directory.items || [];
  const start = listed.length ? pageIndex * AGENT_PAGE_SIZE + 1 : 0;
  const end = listed.length ? start + listed.length - 1 : 0;
  return <>
    <Panel title={`Agents · ${directory.population_total || directory.total}`} eyebrow="Server-paginated directory · click any row for an output audit" className="col-span-full" action={<div className="flex flex-wrap gap-2">
      <select className="field !w-auto !py-1.5" value={tier} onChange={event => resetDirectory(filter, event.target.value)} aria-label="Filter agents by tier">
        <option value="">All tiers</option><option value="core">Core</option><option value="periphery">Periphery</option>
      </select>
      <input className="field !w-56 max-w-[46vw] !py-1.5" value={filter} onChange={event => resetDirectory(event.target.value, tier)} placeholder="Search people, roles…" aria-label="Search agents" />
    </div>}>
      <div className="scrollbar max-h-[520px] overflow-auto">
        {listed.length ? <table className="data-table">
          <thead><tr><th>#</th><th>Name</th><th>Occupation</th><th>Execution</th><th>Role</th><th>Region</th><th>Tier</th><th>Age</th><th>Health</th><th>Status</th></tr></thead>
          <tbody>{listed.map(agent => {
            const execution = agentExecutionPresentation(agent.execution);
            return <tr key={agent.id} className="cursor-pointer" tabIndex="0" onClick={() => inspect(agent.id)} onKeyDown={event => handleAgentRowKeyDown(event, inspect, agent.id)}>
              <td className="tabular text-slate-600">{agent.id}</td><td className="font-semibold"><button className="text-left text-slate-200 underline decoration-mint-300/20 underline-offset-4 hover:text-mint-300" onKeyDown={event => event.stopPropagation()} onClick={event => { event.stopPropagation(); inspect(agent.id); }}>Inspect {agent.name}</button></td><td>{agent.occupation || "—"}</td><td title={execution.title}><Badge tone={execution.tone}>{execution.label}</Badge>{execution.route && <div className="mt-1 max-w-36 truncate text-[10px] text-slate-600">{execution.route}</div>}</td><td>{agent.role ? <Badge>{shortKind(agent.role)}</Badge> : <span className="text-slate-600">citizen</span>}</td><td>{shortKind(agent.region_key || "unassigned")}</td><td><Badge tone={agent.population_tier === "core" ? "good" : "neutral"}>{agent.population_tier || "periphery"}</Badge></td><td className="tabular">{agent.age}</td><td><Badge tone={agent.health === "healthy" ? "good" : agent.health === "critical" ? "bad" : "warn"}>{agent.health}</Badge></td><td><Badge tone={!agent.alive ? "bad" : agent.retired ? "warn" : "neutral"}>{!agent.alive ? "deceased" : agent.retired ? "retired" : "active"}</Badge></td>
            </tr>;
          })}</tbody>
        </table> : <Empty>{directoryLoading ? "Loading agents…" : "No agents match this search."}</Empty>}
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-mint-300/10 px-4 py-3 text-xs text-slate-500" aria-live="polite">
        <span>{directoryError ? <span className="text-coral-300">Directory unavailable: {directoryError}</span> : directoryLoading ? "Refreshing directory…" : `${start}–${end} of ${directory.total} matching agents`}</span>
        <div className="flex gap-2"><button className="button !min-h-8" disabled={pageIndex === 0 || directoryLoading} onClick={() => setPageIndex(current => Math.max(0, current - 1))}>Previous</button><button className="button !min-h-8" disabled={!directory.next_after_id || directoryLoading} onClick={nextPage}>Next</button></div>
      </div>
    </Panel>
    {detailError && !detail && <div role="alert" className="col-span-full rounded-lg border border-coral-300/25 bg-coral-300/[.06] p-3 text-xs text-coral-300">Agent details unavailable: {detailError}</div>}
    {loading && <div className="fixed bottom-4 right-4 z-50 rounded-lg bg-mint-300 px-3 py-2 text-xs font-semibold text-ink-950">Loading agent…</div>}
    {detail && <AgentModal detail={detail} participant={participant} running={status?.running}
      error={detailError}
      historyLoading={loading} onLoadOlder={loadOlderParticipantActions}
      onLoadOlderOutputs={loadOlderAgentOutputs}
      onTakeControl={takeControl} onClose={() => {
        detailRequest.current += 1;
        setDetail(null);
        setDetailError("");
        setLoading(false);
      }} />}
  </>;
}

export function AgentModal({ detail, error = "", participant, running, historyLoading, onLoadOlder, onLoadOlderOutputs, onTakeControl, onClose }) {
  const agent = detail.agent;
  const counts = detail.output_counts || {};
  const modelOutputs = detail.recent_decisions || [];
  const actions = detail.recent_actions || [];
  const selectable = participant?.enabled && agent.kind === "citizen" && Boolean(agent.alive);
  const controlledId = participant?.controlled_agent?.id;
  const execution = agentExecutionPresentation(detail.execution);
  return <Modal title={`${agent.name} · agent ${agent.id}`} onClose={onClose} wide>
    {error && <div role="alert" className="mb-4 rounded-lg border border-coral-300/25 bg-coral-300/[.06] p-3 text-xs text-coral-300">Agent detail request failed: {error}</div>}
    {selectable && <div className="mb-4 flex items-center justify-between rounded-xl border border-mint-300/15 bg-mint-300/[.05] p-3">
      <div><div className="eyebrow">Participant Mode</div><p className="mt-1 text-xs text-slate-400">Control this citizen one validated day at a time.</p></div>
      <button className="button button-primary" disabled={running || Boolean(controlledId)}
        onClick={() => onTakeControl(agent.id)}>{controlledId === agent.id ? "Currently controlled" : "Take control"}</button>
    </div>}
    <div className="grid gap-4 lg:grid-cols-3">
      <section className="rounded-xl border border-mint-300/10 bg-ink-950/40 p-4">
        <div className="eyebrow mb-3">Identity</div>
        <dl className="grid grid-cols-2 gap-x-3 gap-y-2 text-xs"><dt className="text-slate-500">Execution</dt><dd title={execution.title}><Badge tone={execution.tone}>{execution.label}</Badge></dd><dt className="text-slate-500">Evidence</dt><dd className="break-all text-[10px] text-slate-400">{execution.proof}</dd><dt className="text-slate-500">Occupation</dt><dd>{agent.occupation || "—"}</dd><dt className="text-slate-500">Role</dt><dd>{agent.role || agent.kind}</dd><dt className="text-slate-500">Age</dt><dd>{agent.age}</dd><dt className="text-slate-500">Health</dt><dd>{agent.health}</dd><dt className="text-slate-500">Risk tolerance</dt><dd>{number(agent.risk_tolerance, 2)}</dd></dl>
      </section>
      <section className="rounded-xl border border-mint-300/10 bg-ink-950/40 p-4">
        <div className="eyebrow mb-3">Balance sheet</div>
        <div className="space-y-2">{detail.accounts.map(account => <div key={account.id} className="flex justify-between text-xs"><span className="text-slate-500">{account.kind} · bank {account.bank_id || "—"}</span><span className="tabular">{money(account.balance_cents, false)}</span></div>)}</div>
        {detail.loans.length > 0 && <div className="mt-4 border-t border-mint-300/10 pt-3 text-xs text-slate-400">{detail.loans.length} loan{detail.loans.length === 1 ? "" : "s"} · {money(detail.loans.reduce((sum, loan) => sum + Number(loan.outstanding_cents || 0), 0))} outstanding</div>}
      </section>
      <section className="rounded-xl border border-mint-300/10 bg-ink-950/40 p-4">
        <div className="eyebrow mb-3">Beliefs</div>
        <div className="space-y-2">{Object.entries(detail.beliefs).slice(0, 12).map(([key, value]) => <div key={key} className="flex justify-between gap-3 text-xs"><span className="truncate text-slate-500">{shortKind(key)}</span><span className="tabular">{formatBeliefValue(key, value)}</span></div>)}</div>
        {detail.belief_history?.length > 0 && <details className="mt-4 border-t border-mint-300/10 pt-3">
          <summary className="cursor-pointer text-xs text-mint-300">Belief provenance · {detail.belief_history.length} events</summary>
          <div className="scrollbar mt-2 max-h-44 space-y-2 overflow-y-auto pr-1">{detail.belief_history.slice(0, 30).map(update => <div key={update.event_id} className="text-[10px] text-slate-500"><span className="text-slate-300">Day {update.tick} · {shortKind(update.key || update.kind)}</span><br />{formatBeliefValue(update.key || update.kind, update.old_value)} → {formatBeliefValue(update.key || update.kind, update.new_value)} · {update.source || shortKind(update.kind)}</div>)}</div>
        </details>}
      </section>
      <section className="rounded-xl border border-mint-300/10 bg-ink-950/40 p-4 lg:col-span-3">
        <div className="mb-3 flex items-start justify-between gap-3">
          <div><div className="eyebrow">Output coverage</div><p className="mt-1 text-xs text-slate-500">Exact persisted totals; histories below are cursor-paginated.</p></div>
          {Number(counts.model_calls || 0) === 0 && Number(counts.actions || 0) > 0 && <Badge tone="good">deterministic policy</Badge>}
        </div>
        <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-8">
          {[
            ["Model calls", counts.model_calls], ["Actions", counts.actions],
            ["Accepted", counts.accepted_actions], ["Rejected", counts.rejected_actions],
            ["Deterministic", counts.deterministic_actions], ["Messages", counts.messages],
            ["Memories", counts.memories], ["Published items", counts.authored_information_items],
          ].map(([label, value]) => <div key={label} className="rounded-lg border border-mint-300/10 bg-ink-950/50 p-2"><dt className="text-[10px] uppercase tracking-wide text-slate-600">{label}</dt><dd className="mt-1 text-sm font-semibold tabular text-slate-200">{number(value || 0, 0)}</dd></div>)}
        </dl>
        <p className="mt-3 text-[11px] text-slate-500">Belief updates: {number(counts.belief_updates || 0, 0)}. {Number(counts.model_calls || 0) === 0 && Number(counts.actions || 0) > 0 ? "This periphery agent follows deterministic policy, so its actions do not require model calls." : "Model calls include every recorded purpose for this agent."}</p>
      </section>
      <section className="rounded-xl border border-mint-300/10 bg-ink-950/40 p-4">
        <div className="eyebrow mb-3">Memory</div>
        <p className="mb-3 text-[10px] leading-relaxed text-amber-300">Historical agent recollections; numeric claims may be stale.</p>
        <div className="scrollbar max-h-72 space-y-3 overflow-y-auto pr-2">{detail.memories.length ? detail.memories.map((memory, index) => <article key={`${memory.tick}-${index}`} className="border-t border-mint-300/10 pt-2 first:border-0"><div className="mb-1 text-[10px] uppercase tracking-wider text-slate-600">Day {memory.tick} · {shortKind(memory.kind)} · importance {number(memory.importance, 1)}</div><p className="text-xs leading-relaxed text-slate-400">{memory.text}</p></article>) : <Empty>No memories yet.</Empty>}</div>
      </section>
      <section className="rounded-xl border border-mint-300/10 bg-ink-950/40 p-4">
        <div className="eyebrow mb-3">Model output audit</div>
        <p className="mb-3 text-[10px] leading-relaxed text-amber-300">Raw model I/O for provenance; numeric claims are unverified.</p>
        <div className="scrollbar max-h-72 space-y-3 overflow-y-auto pr-2">{modelOutputs.length ? modelOutputs.map(output => <details key={output.id} className="border-t border-mint-300/10 pt-2 first:border-0"><summary className="cursor-pointer text-xs text-slate-300">Day {output.tick} · {shortKind(output.purpose || output.role || "model output")} · {output.model || "model"}</summary><pre className="mt-2 overflow-x-auto whitespace-pre-wrap text-[10px] text-slate-500">{JSON.stringify(output, null, 2)}</pre></details>) : <Empty>{Number(counts.actions || 0) > 0 ? "No model calls recorded; inspect the deterministic action audit." : "No model outputs recorded for this agent."}</Empty>}</div>
        {detail.output_cursors?.model && <button className="button mt-3" disabled={historyLoading} onClick={() => onLoadOlderOutputs("model")}>{historyLoading ? "Loading..." : "Load older model outputs"}</button>}
      </section>
      <section className="rounded-xl border border-mint-300/10 bg-ink-950/40 p-4">
        <div className="eyebrow mb-3">Action audit</div>
        <div className="scrollbar max-h-72 space-y-3 overflow-y-auto pr-2">{actions.length ? actions.map(action => <details key={action.id} className="border-t border-mint-300/10 pt-2 first:border-0"><summary className="cursor-pointer text-xs text-slate-300">Day {action.tick} · {shortKind(action.action_type)} · <span className={action.validation_status === "accepted" ? "text-mint-300" : action.validation_status === "rejected" ? "text-red-300" : "text-amber-300"}>{shortKind(action.validation_status)}</span></summary><pre className="mt-2 overflow-x-auto whitespace-pre-wrap text-[10px] text-slate-500">{JSON.stringify(action, null, 2)}</pre></details>) : <Empty>No action proposals recorded for this agent.</Empty>}</div>
        {detail.output_cursors?.action && <button className="button mt-3" disabled={historyLoading} onClick={() => onLoadOlderOutputs("action")}>{historyLoading ? "Loading..." : "Load older actions"}</button>}
      </section>
      {detail.execution?.source === "external" && <section className="rounded-xl border border-mint-300/10 bg-ink-950/40 p-4 lg:col-span-3">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div><div className="eyebrow">Hermes wake evidence</div><p className="mt-1 text-xs text-slate-500">Durable decision windows and privacy-safe action receipts from the external gateway.</p></div>
          <Badge tone={execution.tone}>{execution.label}</Badge>
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="scrollbar max-h-72 space-y-2 overflow-y-auto">
            <div className="text-[10px] uppercase tracking-wider text-slate-600">Turns</div>
            {detail.external_activity?.turns?.length ? detail.external_activity.turns.map(turn =>
              <details key={`${turn.target_tick}-${turn.projection_hash}`} className="rounded-lg border border-mint-300/10 bg-ink-950/50 p-3">
                <summary className="cursor-pointer text-xs text-slate-300">Day {turn.target_tick} · <span className={turn.status === "submitted" ? "text-mint-300" : "text-amber-300"}>{shortKind(turn.status)}</span></summary>
                <pre className="mt-2 overflow-x-auto whitespace-pre-wrap text-[10px] text-slate-500">{JSON.stringify(turn, null, 2)}</pre>
              </details>) : <Empty>No Hermes turns recorded yet.</Empty>}
          </div>
          <div className="scrollbar max-h-72 space-y-2 overflow-y-auto">
            <div className="text-[10px] uppercase tracking-wider text-slate-600">Action receipts</div>
            {detail.external_activity?.receipts?.length ? detail.external_activity.receipts.map(receipt =>
              <details key={receipt.id} className="rounded-lg border border-mint-300/10 bg-ink-950/50 p-3">
                <summary className="cursor-pointer text-xs text-slate-300">Day {receipt.target_tick} · {shortKind(receipt.action_type || "action")} · <span className={receipt.status === "executed" ? "text-mint-300" : receipt.status === "rejected" ? "text-red-300" : "text-amber-300"}>{shortKind(receipt.status)}</span></summary>
                <pre className="mt-2 overflow-x-auto whitespace-pre-wrap text-[10px] text-slate-500">{JSON.stringify(receipt, null, 2)}</pre>
              </details>) : <Empty>No Hermes action receipts recorded yet.</Empty>}
          </div>
        </div>
      </section>}
      {detail.participantHistory && <section className="rounded-xl border border-mint-300/10 bg-ink-950/40 p-4 lg:col-span-3">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div><div className="eyebrow">Participant action history</div><p className="mt-1 text-xs text-slate-500">Durable operator inputs and validator results for this citizen.</p></div>
          <Badge tone={detail.participantHistory.items.length ? "good" : "neutral"}>{detail.participantHistory.items.length} loaded</Badge>
        </div>
        <div className="scrollbar max-h-80 space-y-3 overflow-y-auto pr-2">
          {detail.participantHistory.items.length ? detail.participantHistory.items.map(item =>
            <details key={item.id} className="rounded-lg border border-mint-300/10 bg-ink-950/50 p-3">
              <summary className="cursor-pointer text-xs text-slate-300">Day {item.target_tick} - {shortKind(item.action?.type || "action")} - <span className={item.status === "executed" ? "text-mint-300" : item.status === "rejected" ? "text-red-300" : "text-amber-300"}>{shortKind(item.status)}</span></summary>
              {item.reasoning && <p className="mt-2 text-xs text-slate-400">{item.reasoning}</p>}
              <pre className="mt-2 overflow-x-auto whitespace-pre-wrap text-[10px] text-slate-500">{JSON.stringify({ action: item.action, result: item.result, created_at: item.created_at, executed_at: item.executed_at, source_action_id: item.source_action_id }, null, 2)}</pre>
            </details>) : <Empty>No participant actions recorded for this citizen.</Empty>}
        </div>
        {detail.participantHistory.next_before_id && <button className="button mt-3" disabled={historyLoading} onClick={onLoadOlder}>{historyLoading ? "Loading..." : "Load older actions"}</button>}
      </section>}
    </div>
  </Modal>;
}
