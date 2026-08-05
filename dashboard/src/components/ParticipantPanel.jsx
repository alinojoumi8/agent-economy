import { useEffect, useMemo, useState } from "react";
import { shortKind } from "../api";
import {
  buildParticipantAction,
  initialParticipantValues,
  participantActionKey,
} from "../participant";
import { Badge, Empty, Panel } from "./ui";

export function ParticipantPanel({ participant, act }) {
  const catalog = participant?.action_catalog || [];
  const enabled = Boolean(participant?.enabled);
  const active = Boolean(participant?.active);
  const firstEnabled = catalog.find(item => item.enabled !== false);
  const queued = participant?.queued_action?.action;
  const queuedKey = queued ? `${queued.type}:${queued.variant || "default"}` : "";
  const [selected, setSelected] = useState(
    queuedKey || (firstEnabled ? participantActionKey(firstEnabled) : ""));
  const [values, setValues] = useState({});
  const [reasoning, setReasoning] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  const descriptor = useMemo(
    () => catalog.find(item => participantActionKey(item) === selected) || firstEnabled,
    [catalog, selected, firstEnabled],
  );

  useEffect(() => {
    if (!descriptor) return;
    setValues(initialParticipantValues(descriptor, queued));
    setReasoning(participant?.queued_action?.reasoning || "");
  }, [descriptor, participant?.queued_action?.id]);

  if (!enabled) return null;

  async function queue() {
    if (!descriptor) return;
    const action = buildParticipantAction(descriptor, values);
    setBusy("queue");
    setError("");
    try {
      await act("/api/participant/action", {
        expected_tick: participant.completed_tick,
        action,
        reasoning,
      });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally { setBusy(""); }
  }

  async function release() {
    setBusy("release");
    setError("");
    try {
      await act("/api/participant/release", { expected_tick: participant.completed_tick });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally { setBusy(""); }
  }

  return <Panel title="Participant Mode" eyebrow="Sandbox - one citizen - one action per day"
    className="col-span-full"
    action={<Badge tone={active ? "good" : "neutral"}>{active ? "Control active" : "Waiting for citizen"}</Badge>}>
    {error && <div role="alert" className="m-4 rounded-lg border border-coral-300/25 bg-coral-300/[.06] p-3 text-xs text-coral-300">Participant action failed: {error}</div>}
    {!active ? <Empty>Open a living citizen below and choose <strong>Take control</strong>.</Empty> :
      <div className="grid gap-4 xl:grid-cols-[.8fr_1.5fr_.9fr]">
        <section className="rounded-xl border border-mint-300/10 bg-ink-950/40 p-4">
          <div className="eyebrow">You are playing</div>
          <h3 className="mt-2 text-lg font-semibold text-mint-300">{participant.controlled_agent?.name}</h3>
          <p className="mt-1 text-xs text-slate-500">Agent {participant.controlled_agent?.id} - {participant.controlled_agent?.occupation || "citizen"}</p>
          <dl className="mt-4 grid grid-cols-2 gap-2 text-xs">
            <dt className="text-slate-500">Completed day</dt><dd>{participant.completed_tick}</dd>
            <dt className="text-slate-500">Command for</dt><dd>Day {participant.next_tick}</dd>
            <dt className="text-slate-500">Health</dt><dd>{participant.controlled_agent?.health}</dd>
            <dt className="text-slate-500">Status</dt><dd>{participant.controlled_agent?.retired ? "retired" : "active"}</dd>
          </dl>
          <button className="button mt-4" disabled={busy || participant.running} onClick={release}>Release citizen</button>
        </section>

        <section className="rounded-xl border border-mint-300/10 bg-ink-950/40 p-4">
          <label className="eyebrow" htmlFor="participant-action">Next action</label>
          <select id="participant-action" className="field mt-2" value={descriptor ? participantActionKey(descriptor) : ""}
            disabled={busy || participant.running}
            onChange={event => setSelected(event.target.value)}>
            {catalog.map(item => <option key={participantActionKey(item)} value={participantActionKey(item)} disabled={item.enabled === false}>
              {item.label}{item.enabled === false ? ` - ${item.disabled_reason}` : ""}
            </option>)}
          </select>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            {(descriptor?.fields || []).filter(field => field.kind !== "hidden").map(field =>
              <label key={field.name} className="text-xs text-slate-500">
                {field.label}
                {field.kind === "select" ? <select className="field mt-1" value={values[field.name] ?? ""}
                  onChange={event => {
                    const option = field.options.find(item => String(item.value) === event.target.value);
                    setValues(current => ({ ...current, [field.name]: option?.value ?? event.target.value }));
                  }}>
                  {(field.options || []).map(option => <option key={String(option.value)} value={String(option.value)}>{option.label}</option>)}
                </select> : <input className="field mt-1" type={field.kind === "number" ? "number" : "text"}
                  min={field.min} maxLength={field.max_length} value={values[field.name] ?? ""}
                  onChange={event => setValues(current => ({ ...current, [field.name]: event.target.value }))} />}
              </label>)}
          </div>
          <label className="mt-3 block text-xs text-slate-500">Reasoning (optional audit note)
            <input className="field mt-1" maxLength="500" value={reasoning}
              onChange={event => setReasoning(event.target.value)} placeholder="Why are you doing this?" />
          </label>
          <button className="button button-primary mt-4" disabled={!descriptor || busy || participant.running}
            onClick={queue}>{participant.queued_action ? "Replace queued action" : "Queue action for next day"}</button>
        </section>

        <section className="rounded-xl border border-mint-300/10 bg-ink-950/40 p-4">
          <div className="eyebrow">Command state</div>
          {participant.queued_action ? <div className="mt-3">
            <Badge tone="good">Day {participant.queued_action.target_tick} queued</Badge>
            <pre className="mt-3 overflow-x-auto whitespace-pre-wrap text-[10px] text-slate-400">{JSON.stringify(participant.queued_action.action, null, 2)}</pre>
            <p className="mt-3 text-xs text-slate-500">Press <strong className="text-slate-300">Step</strong> in the header to execute this command through the normal validator and ledger.</p>
          </div> : <Empty>Choose and queue an action before Step becomes available.</Empty>}
          {participant.last_result && <details className="mt-4 border-t border-mint-300/10 pt-3" open>
            <summary className="cursor-pointer text-xs text-slate-300">Last result - day {participant.last_result.target_tick} - {shortKind(participant.last_result.status)}</summary>
            <pre className="mt-2 overflow-x-auto whitespace-pre-wrap text-[10px] text-slate-500">{JSON.stringify(participant.last_result.result, null, 2)}</pre>
          </details>}
        </section>
      </div>}
  </Panel>;
}
