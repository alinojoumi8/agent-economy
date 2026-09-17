import { useEffect, useRef, useState } from "react";
import { workspaceApi } from "../app/api";
import { addObservation, cityObjectLabel, observationLabel, observationParams, observationScope,
  observationState, observationRecord } from "../lib/cityObservations.js";
import "./city-observations.css";

/** @param {any} props */
export function CityObservationBar({ frame, runId, state, event, disabled, onRestore }) {
  const scope = observationScope(frame, runId);
  const key = scope?.key || "";
  const [saved, setSaved] = useState({ key: "", entries: [], version: 0, ready: false, error: "" });
  const [reload, setReload] = useState(0);
  const requestId = useRef(0);
  const currentKey = useRef(key);
  currentKey.current = key;
  const entries = saved.key === key ? saved.entries : [];
  const error = saved.key === key ? saved.error : "";
  useEffect(() => {
    if (!scope) return;
    const id = ++requestId.current;
    const controller = new AbortController();
    setSaved({ key, entries: [], version: 0, ready: false, error: "" });
    workspaceApi(`/api/v2/operator/city-observations?context=${encodeURIComponent(key)}`, { signal: controller.signal })
      .then(data => {
        const record = observationRecord(data, scope);
        if (id === requestId.current && key === currentKey.current) setSaved({ key, ...record, ready: true, error: "" });
      }).catch(() => {
        if (!controller.signal.aborted && id === requestId.current && key === currentKey.current) {
          setSaved({ key, entries: [], version: 0, ready: false,
            error: "Saved observations are unavailable or invalid in the operator workspace." });
        }
      });
    return () => { controller.abort(); requestId.current += 1; };
  }, [key, reload]);
  const update = async transform => {
    if (!scope || disabled || saved.key !== key || !saved.ready) return;
    const id = ++requestId.current;
    setSaved(previous => ({ ...previous, ready: false, error: "" }));
    try {
      const next = transform(entries);
      const session = await workspaceApi("/api/v2/operator/session");
      if (!session?.csrf_token || typeof session.csrf_token !== "string") throw new Error("Operator session unavailable.");
      if (id !== requestId.current || key !== currentKey.current) return;
      const data = await workspaceApi("/api/v2/operator/city-observations", {
        method: "PUT", headers: { "X-CSRF-Token": session.csrf_token },
        body: JSON.stringify({ context: scope.context, expected_version: saved.version, entries: next }),
      });
      const record = observationRecord(data, scope);
      if (id === requestId.current && key === currentKey.current) setSaved({ key, ...record, ready: true, error: "" });
    } catch (error) {
      if (id !== requestId.current || key !== currentKey.current) return;
      const conflict = error?.status === 409;
      setSaved(previous => ({ ...previous, ready: !conflict, error: conflict
        ? "Saved observations changed or the city context is stale. Reload observations before saving."
        : error instanceof Error && error.message.startsWith("20 observations") ? error.message
          : "The observation could not be saved to the operator workspace. Try again or reload observations." }));
    }
  };
  return <section className="city-observations" aria-label="City observation history">
    <span>{scope ? `Observed tick ${scope.tick}` : "Observation unavailable"}</span>
    <button type="button" disabled={disabled || !scope || saved.key !== key || !saved.ready}
      onClick={() => update(current => addObservation(current, observationParams(scope, state, event)))}>
      {event ? "Save event bookmark" : "Save observation"}
    </button>
    <details><summary>Saved observations ({entries.length})</summary>
      <p>Saved in your local operator workspace for this run and visibility. Bookmarks restore the recorded tick, selection, filters and camera; they do not advance the world.</p>
      {entries.length ? <ol>{entries.map(params => {
        const selection = observationState(params, scope);
        if (!selection) return null;
        const label = observationLabel(selection);
        return <li key={params}>
          <button type="button" disabled={disabled} onClick={() => onRestore(selection, { onlyIfCurrent: true })}>{label}</button>
          <button type="button" disabled={disabled || !saved.ready} aria-label={`Remove ${label}`} onClick={() => update(current => current.filter(item => item !== params))}>Remove</button>
        </li>;
      })}</ol> : <p>No observations saved in this context.</p>}
    </details>
    {state.tick !== "live" && <button type="button" onClick={() => onRestore({ tick: "live", event: null })}>Return to live city</button>}
    <button type="button" disabled={!scope || disabled} onClick={() => setReload(value => value + 1)}>Reload observations</button>
    {error && <p role="alert">{error}</p>}
  </section>;
}

/** @param {any} props */
export function CitySelectionBreadcrumb({ state, household, workplace, onSelect }) {
  return <nav className="city-selection-breadcrumb" aria-label="Selected city object"><ol>
    <li>City</li>
    {state.agent && household && <li><button type="button" onClick={() => onSelect({ household: household.id })}>Household #{household.id}</button></li>}
    {state.firm && workplace && <li><button type="button" onClick={() => onSelect({ place: workplace.id })}>Workplace #{workplace.id}</button></li>}
    <li aria-current="location">{cityObjectLabel(state)}</li>
  </ol></nav>;
}
