import { useEffect, useMemo, useState } from "react";
import { Modal } from "./ui";

const DEFAULTS = {
  policy_rate: { rate_bps: 750 },
  oil: { multiplier: 1.5 },
  rumor: { bank_id: 1, n_agents: 12, text: "A false rumor claims the bank may be insolvent." },
  slant: { outlet_id: 1, directive: "Frame financial stress as an imminent crisis." },
  scandal: { firm_id: 1, description: "Regulators opened an accounting investigation." },
  epidemic: { multiplier: 4 },
};

export function ShockModal({ library, tick, act, onClose }) {
  const kinds = library?.kinds?.length ? library.kinds : Object.keys(DEFAULTS);
  const [kind, setKind] = useState(kinds[0] || "rumor");
  const [triggerType, setTriggerType] = useState("shock");
  const [when, setWhen] = useState(Number(tick || 0) + 1);
  const [duration, setDuration] = useState(10);
  const [metric, setMetric] = useState("unemployment");
  const [operator, setOperator] = useState(">");
  const [threshold, setThreshold] = useState(.1);
  const [params, setParams] = useState(JSON.stringify(DEFAULTS[kinds[0]] || {}, null, 2));
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState("");

  useEffect(() => setParams(JSON.stringify(DEFAULTS[kind] || {}, null, 2)), [kind]);
  const trigger = useMemo(() => triggerType === "conditional"
    ? { metric, op: operator, threshold: Number(threshold) }
    : triggerType === "trend" ? { start: Number(when) } : { tick: Number(when) },
  [triggerType, metric, operator, threshold, when]);

  async function submit(event) {
    event.preventDefault();
    setSubmitting(true);
    setFormError("");
    try {
      const parsed = JSON.parse(params || "{}");
      await act("/api/shocks", { kind, trigger_type: triggerType, trigger,
        duration_ticks: triggerType === "trend" ? Number(duration) : 0,
        params: parsed, label: `${kind} injected from observatory` });
      onClose();
    } catch (reason) {
      setFormError(reason instanceof Error ? reason.message : String(reason));
    } finally { setSubmitting(false); }
  }

  return <Modal title="Inject a controlled shock" onClose={onClose}>
    <form onSubmit={submit} className="space-y-5">
      <div>
        <label className="mb-2 block text-[10px] uppercase tracking-wider text-slate-500">Shock channel</label>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">{kinds.map(item => <button type="button" key={item} onClick={() => setKind(item)} className={`rounded-xl border p-3 text-left text-xs font-semibold capitalize transition ${kind === item ? "border-mint-300 bg-mint-300/10 text-mint-300" : "border-mint-300/10 bg-ink-950/40 text-slate-400 hover:border-mint-300/30"}`}>{item.replaceAll("_", " ")}</button>)}</div>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-xs text-slate-500">Trigger mode<select className="field mt-1" value={triggerType} onChange={event => setTriggerType(event.target.value)}>{(library?.trigger_types || ["shock", "trend", "conditional"]).map(item => <option key={item} value={item}>{item === "shock" ? "One-time" : item}</option>)}</select></label>
        {triggerType !== "conditional" && <label className="text-xs text-slate-500">Start day<input className="field mt-1" type="number" min={Number(tick || 0) + 1} value={when} onChange={event => setWhen(event.target.value)} /></label>}
        {triggerType === "trend" && <label className="text-xs text-slate-500">Duration<input className="field mt-1" type="number" min="1" value={duration} onChange={event => setDuration(event.target.value)} /></label>}
      </div>
      {triggerType === "conditional" && <div className="grid grid-cols-[1fr_80px_1fr] gap-2"><select className="field" value={metric} onChange={event => setMetric(event.target.value)}><option>unemployment</option><option>cpi</option><option>index</option><option>sentiment</option><option>money_supply</option><option>gini</option></select><select className="field" value={operator} onChange={event => setOperator(event.target.value)}><option>&gt;</option><option>&lt;</option></select><input className="field" type="number" step="any" value={threshold} onChange={event => setThreshold(event.target.value)} /></div>}
      <label className="block text-xs text-slate-500">Parameters · JSON<textarea className="field mt-1 min-h-36 font-mono text-xs" value={params} onChange={event => setParams(event.target.value)} spellCheck="false" /></label>
      <div className="rounded-xl border border-gold-300/15 bg-gold-300/[.04] p-3 text-xs leading-relaxed text-slate-400">The shock is scheduled through the same deterministic event system used by experiment files. It cannot write money or state outside the validated engine path.</div>
      {formError && <p role="alert" className="text-xs text-coral-300">{formError}</p>}
      <div className="flex justify-end gap-2"><button type="button" className="button" onClick={onClose}>Cancel</button><button className="button button-primary" disabled={submitting}>{submitting ? "Scheduling…" : "Schedule shock"}</button></div>
    </form>
  </Modal>;
}
