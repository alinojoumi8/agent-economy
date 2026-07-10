import { useState } from "react";
import { number } from "../api";
import { Badge, Empty, Panel } from "./ui";

const SUGGESTIONS = [
  "What is the probability of a bank run within 30 ticks?",
  "Will unemployment exceed 10% within 30 ticks?",
  "Will the market index fall by 15% within 30 ticks?",
];

export function OraclePanel({ oracle, act }) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState(null);
  const [asking, setAsking] = useState(false);
  const score = oracle?.scorecard || {};

  async function ask(event) {
    event.preventDefault();
    if (!question.trim()) return;
    setAsking(true);
    try { setAnswer(await act("/api/oracle/ask", { question: question.trim() })); }
    finally { setAsking(false); }
  }

  return (
    <Panel title="Ask the Oracle" eyebrow="Read-only · resolved · scored" className="col-span-full xl:col-span-8" action={<Badge tone={score.n_resolved ? "good" : "neutral"}>{score.n_resolved || 0} resolved</Badge>}>
      <div className="grid min-h-[330px] gap-0 md:grid-cols-[1fr_270px]">
        <div className="border-b border-mint-300/10 p-4 md:border-b-0 md:border-r">
          <div className="mb-4 min-h-32 rounded-xl border border-mint-300/10 bg-ink-950/50 p-4">
            {!answer ? <p className="text-sm leading-relaxed text-slate-500">Ask a probability question. The Oracle must return drivers and a machine-checkable resolution rule; it cannot alter the simulation.</p> : answer.insufficient_data ? <div><Badge tone="warn">insufficient data</Badge><p className="mt-3 text-sm text-slate-300">{answer.reason}</p></div> : <div>
              <div className="flex items-end gap-3"><span className="tabular text-4xl font-semibold text-mint-300">{number(Number(answer.p) * 100, 1)}%</span><span className="mb-1 text-xs uppercase tracking-wider text-slate-500">forecast</span></div>
              <p className="mt-3 text-sm leading-relaxed text-slate-300">{answer.reasoning}</p>
              {answer.drivers?.length > 0 && <div className="mt-3 flex flex-wrap gap-1.5">{answer.drivers.map(driver => <Badge key={String(driver)}>{typeof driver === "string" ? driver : driver.name || JSON.stringify(driver)}</Badge>)}</div>}
            </div>}
          </div>
          <form onSubmit={ask} className="flex flex-col gap-2 sm:flex-row">
            <label className="sr-only" htmlFor="oracle-question">Question for the Oracle</label>
            <input id="oracle-question" className="field flex-1" value={question} onChange={event => setQuestion(event.target.value)} placeholder="Probability of a bank run within 30 ticks?" />
            <button className="button button-primary" disabled={asking || !question.trim()}>{asking ? "Analyzing…" : "Ask Oracle"}</button>
          </form>
          <div className="mt-2 flex flex-wrap gap-1.5">{SUGGESTIONS.map(suggestion => <button key={suggestion} className="rounded-full border border-mint-300/10 px-2.5 py-1 text-[10px] text-slate-500 hover:border-mint-300/30 hover:text-mint-300" onClick={() => setQuestion(suggestion)}>{suggestion}</button>)}</div>
        </div>
        <div className="scrollbar max-h-[380px] overflow-y-auto p-4">
          <div className="mb-3 flex items-center justify-between"><span className="text-[10px] uppercase tracking-wider text-slate-500">Forecast ledger</span>{score.mean_brier !== undefined && <span className="tabular text-xs text-slate-400">Brier {number(score.mean_brier, 3)}</span>}</div>
          {oracle?.predictions?.length ? oracle.predictions.slice(0, 10).map(prediction => <article key={prediction.id} className="border-t border-mint-300/10 py-3 first:border-0">
            <div className="flex justify-between gap-3"><span className="tabular text-lg font-semibold text-mint-300">{prediction.p === null ? "—" : `${number(prediction.p * 100, 0)}%`}</span><Badge tone={prediction.status === "resolved" ? "good" : prediction.status === "insufficient_data" ? "warn" : "neutral"}>{prediction.status}</Badge></div>
            <p className="mt-1 text-xs leading-relaxed text-slate-400">{prediction.question}</p>
            <p className="mt-1 text-[10px] text-slate-600">asked d{prediction.asked_tick}{prediction.deadline_tick ? ` · resolves d${prediction.deadline_tick}` : ""}</p>
          </article>) : <Empty>No predictions yet.</Empty>}
        </div>
      </div>
    </Panel>
  );
}

export function CostPanel({ cost, readiness }) {
  const providers = readiness?.providers || [];
  return (
    <Panel title="Provider operations" eyebrow="Readiness · calls · spend" className="col-span-full xl:col-span-4">
      <div className="p-4">
        <div className="mb-4 rounded-xl border border-mint-300/10 bg-ink-950/50 p-3">
          <div className="mb-2 flex items-center justify-between"><span className="text-[10px] uppercase tracking-wider text-slate-500">Runtime readiness</span><Badge tone={readiness?.ready ? "good" : "bad"}>{readiness?.ready ? readiness.mode : "not ready"}</Badge></div>
          <div className="space-y-2">{providers.length ? providers.map(provider => <div key={provider.name} className="flex items-center justify-between text-xs"><span className="text-slate-300">{provider.name}</span><span className="text-slate-500">{provider.kind} · {provider.key_present ? "key present" : "no key required"}</span></div>) : <p className="text-xs text-slate-500">Built-in scripted provider; no network key required.</p>}</div>
        </div>
        <h3 className="mb-2 text-[10px] uppercase tracking-wider text-slate-500">By model</h3>
        {cost?.by_model?.length ? <div className="space-y-2">{cost.by_model.map(row => <div key={row.model} className="grid grid-cols-[1fr_auto_auto] gap-3 border-t border-mint-300/10 pt-2 text-xs first:border-0"><span className="truncate text-slate-300">{row.model}</span><span className="tabular text-slate-500">{row.calls} calls</span><span className="tabular text-mint-300">${number(row.cost_usd || 0, 4)}</span></div>)}</div> : <Empty>No provider calls recorded.</Empty>}
        <h3 className="mb-2 mt-5 text-[10px] uppercase tracking-wider text-slate-500">By purpose</h3>
        <div className="flex flex-wrap gap-1.5">{cost?.by_purpose?.map(row => <Badge key={row.purpose}>{row.purpose} · {row.calls}</Badge>)}</div>
        <h3 className="mb-2 mt-5 text-[10px] uppercase tracking-wider text-slate-500">Top agents</h3>
        {cost?.by_agent?.length ? <div className="space-y-2">{cost.by_agent.slice(0, 6).map((row, index) => <div key={`${row.agent_id ?? "shared"}-${row.role}-${index}`} className="grid grid-cols-[1fr_auto_auto] gap-3 border-t border-mint-300/10 pt-2 text-xs first:border-0"><span className="truncate text-slate-300">{row.agent_name}<small className="ml-1 text-slate-600">{row.role}</small></span><span className="tabular text-slate-500">{row.calls}</span><span className="tabular text-mint-300">${number(row.cost_usd || 0, 4)}</span></div>)}</div> : <Empty>No agent-level costs recorded.</Empty>}
      </div>
    </Panel>
  );
}
