import { useState } from "react";
import { number } from "../api";
import { calibrationView } from "../calibration.js";
import { clientLog } from "../logging.js";
import { Badge, Empty, Panel } from "./ui";

const SUGGESTIONS = [
  "What is the probability of a bank run within 30 ticks?",
  "Will unemployment exceed 10% within 30 ticks?",
  "Will the market index fall by 15% within 30 ticks?",
];

export function OraclePanel({ oracle, act, readOnly = false }) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState(null);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState("");
  const score = oracle?.scorecard || {};

  async function ask(event) {
    event.preventDefault();
    if (!question.trim()) return;
    setAsking(true);
    setError("");
    try { setAnswer(await act("/api/oracle/ask", { question: question.trim() })); }
    catch (reason) {
      const message = reason instanceof Error ? reason.message : String(reason);
      setError(message || "Oracle request failed.");
      clientLog("dashboard.oracle.failed", {
        error_type: reason?.constructor?.name || typeof reason,
        error: message,
      }, "error");
    }
    finally { setAsking(false); }
  }

  return (
    <Panel title="Ask the Oracle" eyebrow="Read-only · resolved · scored" className="col-span-full xl:col-span-8" action={<Badge tone={score.resolved ? "good" : "neutral"}>{score.resolved || 0} resolved</Badge>}>
      <div className="grid min-h-[330px] gap-0 md:grid-cols-[1fr_270px]">
        <div className="border-b border-mint-300/10 p-4 md:border-b-0 md:border-r">
          <div className="mb-4 min-h-32 rounded-xl border border-mint-300/10 bg-ink-950/50 p-4">
            {!answer ? <p className="text-sm leading-relaxed text-slate-500">Ask a probability question. The Oracle must return drivers and a machine-checkable resolution rule; it cannot alter the simulation.</p> : answer.insufficient_data ? <div><Badge tone="warn">insufficient data</Badge><p className="mt-3 text-sm text-slate-300">{answer.reason}</p></div> : <div>
              <div className="flex items-end gap-3"><span className="tabular text-4xl font-semibold text-mint-300">{number(Number(answer.p) * 100, 1)}%</span><span className="mb-1 text-xs uppercase tracking-wider text-slate-500">forecast</span></div>
              <p className="mt-3 text-sm leading-relaxed text-slate-300">{answer.reasoning}</p>
              {answer.drivers?.length > 0 && <div className="mt-3 flex flex-wrap gap-1.5">{answer.drivers.map(driver => <Badge key={String(driver)}>{typeof driver === "string" ? driver : driver.name || JSON.stringify(driver)}</Badge>)}</div>}
            </div>}
          </div>
          {readOnly ? <p className="rounded-xl border border-mint-300/10 bg-ink-950/45 p-3 text-xs text-slate-500">Hosted access exposes existing sanitized forecasts. New Oracle questions are disabled.</p> : <><form onSubmit={ask} className="flex flex-col gap-2 sm:flex-row">
            <label className="sr-only" htmlFor="oracle-question">Question for the Oracle</label>
            <input id="oracle-question" className="field flex-1" value={question} onChange={event => setQuestion(event.target.value)} placeholder="Probability of a bank run within 30 ticks?" />
            <button className="button button-primary" disabled={asking || !question.trim()}>{asking ? "Analyzing…" : "Ask Oracle"}</button>
          </form>
          {error && <p role="alert" className="mt-2 rounded-lg border border-coral-300/20 bg-coral-300/[.05] p-3 text-xs text-coral-300">Oracle request failed: {error}</p>}
          <div className="mt-2 flex flex-wrap gap-1.5">{SUGGESTIONS.map(suggestion => <button key={suggestion} className="rounded-full border border-mint-300/10 px-2.5 py-1 text-[10px] text-slate-500 hover:border-mint-300/30 hover:text-mint-300" onClick={() => setQuestion(suggestion)}>{suggestion}</button>)}</div></>}
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

export function CalibrationPanel({ calibration }) {
  const [scope, setScope] = useState("run");
  const view = calibrationView(calibration?.[scope]);
  const errors = calibration?.errors || [];

  return (
    <Panel title="Oracle calibration" eyebrow="Reliability · resolution · uncertainty" className="col-span-full">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-mint-300/10 px-4 py-3">
        <div className="flex gap-1.5" role="group" aria-label="Calibration scope">
          <button className={`button ${scope === "run" ? "button-primary" : ""}`} onClick={() => setScope("run")}>Current run</button>
          <button className={`button ${scope === "all" ? "button-primary" : ""}`} onClick={() => setScope("all")}>All runs</button>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <Badge tone={view.beatsNaive ? "good" : view.beatsNaive === false ? "warn" : "neutral"}>
            {view.beatsNaive === null ? "awaiting outcomes" : view.beatsNaive ? "beats p=0.5" : "below baseline"}
          </Badge>
          <Badge>{view.n} resolved</Badge>
          {view.runs !== null && <Badge>{view.runs} runs scanned</Badge>}
        </div>
      </div>
      {errors.length > 0 && <div className="border-b border-gold-300/15 bg-gold-300/[.04] px-4 py-2 text-xs text-gold-300">Calibration refresh warning: {errors.join(" · ")}</div>}
      {view.empty ? <div className="p-5"><Empty>No resolved forecasts in this scope yet. Calibration appears after outcomes resolve.</Empty></div> :
        <div className="grid gap-0 lg:grid-cols-[360px_1fr]">
          <div className="border-b border-mint-300/10 p-4 lg:border-b-0 lg:border-r">
            <svg viewBox="0 0 100 100" className="mx-auto aspect-square w-full max-w-[300px]" role="img" aria-label="Oracle forecast reliability curve">
              <rect x="0" y="0" width="100" height="100" rx="4" className="fill-ink-950 stroke-mint-300/10" />
              <line x1="0" y1="100" x2="100" y2="0" className="stroke-slate-600" strokeDasharray="3 3" />
              {view.points.map(point => <g key={point.label}>
                <line x1={point.forecast * 100} y1="100" x2={point.forecast * 100} y2={(1 - point.observed) * 100} className="stroke-mint-300/30" />
                <circle cx={point.forecast * 100} cy={(1 - point.observed) * 100} r={Math.min(5, 2 + Math.sqrt(point.n))} className="fill-mint-300 stroke-ink-950" />
              </g>)}
              <text x="50" y="98" textAnchor="middle" className="fill-slate-500 text-[5px]">mean forecast probability</text>
              <text x="3" y="50" transform="rotate(-90 3 50)" textAnchor="middle" className="fill-slate-500 text-[5px]">observed frequency</text>
            </svg>
          </div>
          <div className="p-4">
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
              {[
                ["Brier", view.brier],
                ["Naive p=0.5", view.naiveBrier],
                ["Reliability", view.reliability],
                ["Resolution", view.resolution],
                ["Uncertainty", view.uncertainty],
                ["Base rate", view.baseRate],
              ].map(([label, value]) => <div key={label} className="rounded-xl border border-mint-300/10 bg-ink-950/45 p-3">
                <div className="text-[10px] uppercase tracking-wider text-slate-500">{label}</div>
                <div className="tabular mt-1 text-xl text-mint-300">{number(value, 4)}</div>
              </div>)}
            </div>
            <div className="mt-4 overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="text-[10px] uppercase tracking-wider text-slate-500"><tr><th className="pb-2">Bin</th><th>Forecast</th><th>Observed</th><th>N</th></tr></thead>
                <tbody>{view.points.map(point => <tr key={point.label} className="border-t border-mint-300/10"><td className="py-2 text-slate-400">{point.label}</td><td className="tabular">{number(point.forecast, 3)}</td><td className="tabular">{number(point.observed, 3)}</td><td className="tabular">{point.n}</td></tr>)}</tbody>
              </table>
            </div>
          </div>
        </div>}
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
