import { useMemo, useState } from "react";
import { api, money, number, shortKind } from "../api";
import { Badge, Empty, Modal, Panel } from "./ui";

export function AgentsPanel({ agents }) {
  const [filter, setFilter] = useState("");
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(false);
  const visible = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    if (!needle) return agents;
    return agents.filter(agent => [agent.name, agent.occupation, agent.role, agent.kind, agent.health]
      .some(value => String(value || "").toLowerCase().includes(needle)));
  }, [agents, filter]);

  async function inspect(id) {
    setLoading(true);
    try { setDetail(await api(`/api/agents/${id}`)); } finally { setLoading(false); }
  }

  return <>
    <Panel title={`Agents · ${visible.length}/${agents.length}`} eyebrow="Click any row for a full audit" className="col-span-full" action={<input className="field !w-56 max-w-[46vw] !py-1.5" value={filter} onChange={event => setFilter(event.target.value)} placeholder="Filter people, roles…" aria-label="Filter agents" />}>
      <div className="scrollbar max-h-[520px] overflow-auto">
        {visible.length ? <table className="data-table">
          <thead><tr><th>#</th><th>Name</th><th>Occupation</th><th>Role</th><th>Age</th><th>Health</th><th>Status</th></tr></thead>
          <tbody>{visible.map(agent => <tr key={agent.id} className="cursor-pointer" tabIndex="0" onClick={() => inspect(agent.id)} onKeyDown={event => { if (event.key === "Enter" || event.key === " ") inspect(agent.id); }}>
            <td className="tabular text-slate-600">{agent.id}</td><td className="font-semibold"><button className="text-left text-slate-200 underline decoration-mint-300/20 underline-offset-4 hover:text-mint-300" onClick={event => { event.stopPropagation(); inspect(agent.id); }}>Inspect {agent.name}</button></td><td>{agent.occupation || "—"}</td><td>{agent.role ? <Badge>{shortKind(agent.role)}</Badge> : <span className="text-slate-600">citizen</span>}</td><td className="tabular">{agent.age}</td><td><Badge tone={agent.health === "healthy" ? "good" : agent.health === "critical" ? "bad" : "warn"}>{agent.health}</Badge></td><td><Badge tone={!agent.alive ? "bad" : agent.retired ? "warn" : "neutral"}>{!agent.alive ? "deceased" : agent.retired ? "retired" : "active"}</Badge></td>
          </tr>)}</tbody>
        </table> : <Empty>No agents match this filter.</Empty>}
      </div>
    </Panel>
    {loading && <div className="fixed bottom-4 right-4 z-50 rounded-lg bg-mint-300 px-3 py-2 text-xs font-semibold text-ink-950">Loading agent…</div>}
    {detail && <AgentModal detail={detail} onClose={() => setDetail(null)} />}
  </>;
}

function AgentModal({ detail, onClose }) {
  const agent = detail.agent;
  return <Modal title={`${agent.name} · agent ${agent.id}`} onClose={onClose} wide>
    <div className="grid gap-4 lg:grid-cols-3">
      <section className="rounded-xl border border-mint-300/10 bg-ink-950/40 p-4">
        <div className="eyebrow mb-3">Identity</div>
        <dl className="grid grid-cols-2 gap-x-3 gap-y-2 text-xs"><dt className="text-slate-500">Occupation</dt><dd>{agent.occupation || "—"}</dd><dt className="text-slate-500">Role</dt><dd>{agent.role || agent.kind}</dd><dt className="text-slate-500">Age</dt><dd>{agent.age}</dd><dt className="text-slate-500">Health</dt><dd>{agent.health}</dd><dt className="text-slate-500">Risk tolerance</dt><dd>{number(agent.risk_tolerance, 2)}</dd></dl>
      </section>
      <section className="rounded-xl border border-mint-300/10 bg-ink-950/40 p-4">
        <div className="eyebrow mb-3">Balance sheet</div>
        <div className="space-y-2">{detail.accounts.map(account => <div key={account.id} className="flex justify-between text-xs"><span className="text-slate-500">{account.kind} · bank {account.bank_id || "—"}</span><span className="tabular">{money(account.balance_cents, false)}</span></div>)}</div>
        {detail.loans.length > 0 && <div className="mt-4 border-t border-mint-300/10 pt-3 text-xs text-slate-400">{detail.loans.length} loan{detail.loans.length === 1 ? "" : "s"} · {money(detail.loans.reduce((sum, loan) => sum + Number(loan.outstanding_cents || 0), 0))} outstanding</div>}
      </section>
      <section className="rounded-xl border border-mint-300/10 bg-ink-950/40 p-4">
        <div className="eyebrow mb-3">Beliefs</div>
        <div className="space-y-2">{Object.entries(detail.beliefs).slice(0, 12).map(([key, value]) => <div key={key} className="flex justify-between gap-3 text-xs"><span className="truncate text-slate-500">{shortKind(key)}</span><span className="tabular">{number(value, 3)}</span></div>)}</div>
        {detail.belief_history?.length > 0 && <details className="mt-4 border-t border-mint-300/10 pt-3">
          <summary className="cursor-pointer text-xs text-mint-300">Belief provenance · {detail.belief_history.length} events</summary>
          <div className="scrollbar mt-2 max-h-44 space-y-2 overflow-y-auto pr-1">{detail.belief_history.slice(0, 30).map(update => <div key={update.event_id} className="text-[10px] text-slate-500"><span className="text-slate-300">Day {update.tick} · {shortKind(update.key || update.kind)}</span><br />{number(update.old_value, 3)} → {number(update.new_value, 3)} · {update.source || shortKind(update.kind)}</div>)}</div>
        </details>}
      </section>
      <section className="rounded-xl border border-mint-300/10 bg-ink-950/40 p-4 lg:col-span-2">
        <div className="eyebrow mb-3">Memory</div>
        <div className="scrollbar max-h-72 space-y-3 overflow-y-auto pr-2">{detail.memories.length ? detail.memories.map((memory, index) => <article key={`${memory.tick}-${index}`} className="border-t border-mint-300/10 pt-2 first:border-0"><div className="mb-1 text-[10px] uppercase tracking-wider text-slate-600">Day {memory.tick} · {shortKind(memory.kind)} · importance {number(memory.importance, 1)}</div><p className="text-xs leading-relaxed text-slate-400">{memory.text}</p></article>) : <Empty>No memories yet.</Empty>}</div>
      </section>
      <section className="rounded-xl border border-mint-300/10 bg-ink-950/40 p-4">
        <div className="eyebrow mb-3">Decision audit</div>
        <div className="scrollbar max-h-72 space-y-3 overflow-y-auto pr-2">{detail.recent_decisions.length ? detail.recent_decisions.map((decision, index) => <details key={`${decision.tick}-${index}`} className="border-t border-mint-300/10 pt-2 first:border-0"><summary className="cursor-pointer text-xs text-slate-300">Day {decision.tick} · {decision.purpose} · {decision.model}</summary><pre className="mt-2 overflow-x-auto whitespace-pre-wrap text-[10px] text-slate-500">{JSON.stringify(decision, null, 2)}</pre></details>) : <Empty>No decisions yet.</Empty>}</div>
      </section>
    </div>
  </Modal>;
}
