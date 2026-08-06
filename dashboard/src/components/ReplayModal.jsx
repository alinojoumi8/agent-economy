import { useEffect, useMemo, useState } from "react";
import { api, formatMetricValue, money, shortKind } from "../api";
import { clientLog } from "../logging.js";
import { replayRequestWasCancelled } from "../lib/replayRequests.js";
import { Badge, Empty, Modal } from "./ui";

export function ReplayModal({ onClose }) {
  const [runs, setRuns] = useState([]);
  const [runId, setRunId] = useState("");
  const [tick, setTick] = useState(0);
  const [view, setView] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const selected = useMemo(() => runs.find(run => run.file === runId || run.run_id === runId), [runs, runId]);

  useEffect(() => {
    const controller = new AbortController();
    api("/api/replay/runs", { signal: controller.signal }).then(items => {
      if (controller.signal.aborted) return;
      setRuns(items);
      if (items.length) { setRunId(items[0].file); setTick(items[0].ticks); }
    }).catch(reason => {
      if (replayRequestWasCancelled(reason, controller.signal)) return;
      const message = reason instanceof Error ? reason.message : String(reason);
      setError(message);
      clientLog("dashboard.replay.catalog_failed", {
        error_type: reason?.constructor?.name || typeof reason, error: message,
      }, "error");
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!runId || tick < 0) return;
    const controller = new AbortController();
    const path = `/api/replay/${encodeURIComponent(runId)}/tick/${tick}`;
    const timer = window.setTimeout(() => api(path, { signal: controller.signal }).then(value => {
      if (controller.signal.aborted) return;
      setView(value);
      setError("");
    }).catch(reason => {
      if (replayRequestWasCancelled(reason, controller.signal)) return;
      const message = reason instanceof Error ? reason.message : String(reason);
      setError(message);
      clientLog("dashboard.replay.tick_failed", {
        path, run_id: runId, tick,
        error_type: reason?.constructor?.name || typeof reason, error: message,
      }, "error");
    }), 80);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [runId, tick]);

  function selectRun(value) {
    setRunId(value);
    const run = runs.find(item => item.file === value || item.run_id === value);
    setTick(run?.ticks || 0);
  }

  return <Modal title="Replay a stored run" onClose={onClose} wide>
    {error && <div className="mb-3 rounded-lg border border-coral-300/30 bg-coral-300/10 px-3 py-2 text-xs text-coral-300" role="alert">{error}</div>}
    {loading ? <Empty>Loading run catalogue…</Empty> : !runs.length ? <Empty>No stored runs are available.</Empty> : <>
      <div className="mb-4 grid gap-3 rounded-xl border border-mint-300/10 bg-ink-950/40 p-3 md:grid-cols-[240px_1fr_auto] md:items-center">
        <label className="text-[10px] uppercase tracking-wider text-slate-500">Run<select className="field mt-1" value={runId} onChange={event => selectRun(event.target.value)}>{runs.map(run => <option key={run.file} value={run.file}>{run.run_id} · {run.ticks} days</option>)}</select></label>
        <label className="text-[10px] uppercase tracking-wider text-slate-500">Timeline<input className="mt-3 w-full accent-mint-300" type="range" min="0" max={selected?.ticks || 0} value={tick} onChange={event => setTick(Number(event.target.value))} /></label>
        <div className="text-center"><div className="eyebrow">Day</div><div className="tabular text-3xl font-semibold text-mint-300">{tick}</div></div>
      </div>
      <div className="mb-4 flex gap-2 overflow-x-auto pb-1">{view?.ticker?.map(item => <div key={item.firm_id} className="whitespace-nowrap rounded-lg border border-mint-300/10 px-3 py-2 text-xs"><span className="text-slate-500">{item.name}</span><strong className="ml-2 tabular text-mint-300">{money(item.price_cents, false)}</strong></div>)}</div>
      <div className="mb-4 grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-8">{Object.entries(view?.metrics || {}).slice(0, 8).map(([key, value]) => <div key={key} className="rounded-lg border border-mint-300/10 bg-ink-950/30 p-2"><div className="truncate text-[9px] uppercase tracking-wider text-slate-600">{shortKind(key)}</div><div className="tabular text-sm font-semibold">{formatMetricValue(key, value)}</div></div>)}</div>
      <div className="grid gap-4 md:grid-cols-3">
        <section><div className="eyebrow mb-2">Events</div><div className="scrollbar max-h-80 overflow-y-auto rounded-xl border border-mint-300/10 px-3">{view?.events?.length ? view.events.map(event => <div key={event.id} className="border-b border-mint-300/10 py-2 text-xs last:border-0"><span className="text-slate-300">{shortKind(event.kind)}</span>{event.importance >= 3 && <span className="ml-2"><Badge tone="warn">material</Badge></span>}</div>) : <Empty />}</div></section>
        <section><div className="eyebrow mb-2">News</div><div className="scrollbar max-h-80 overflow-y-auto rounded-xl border border-mint-300/10 px-3">{view?.news?.length ? view.news.map((article, index) => <article key={index} className="border-b border-mint-300/10 py-2 last:border-0"><div className="flex items-center gap-2 text-[10px] text-slate-600"><span>{article.outlet}</span>{article.numeric_claims_redacted && <Badge tone="warn">unsupported number removed</Badge>}</div><div className="text-xs text-slate-300">{article.headline}</div></article>) : <Empty />}</div></section>
        <section><div className="eyebrow mb-2">Conversations</div><div className="scrollbar max-h-80 overflow-y-auto rounded-xl border border-mint-300/10 px-3">{view?.conversations?.length ? view.conversations.map(conversation => <article key={conversation.id} className="border-b border-mint-300/10 py-2 last:border-0">{conversation.messages.map((message, index) => <p key={index} className="mb-1 text-xs"><strong className="mr-1 text-mint-300">{message.name}</strong><span className="text-slate-500">{message.text}</span></p>)}</article>) : <Empty />}</div></section>
      </div>
    </>}
  </Modal>;
}
