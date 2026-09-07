import { parseObserverViewState, patchObserverViewState } from "../app/observerViewStateCore.js";

export const OBSERVATION_LIMIT = 20;
const integer = value => Number.isSafeInteger(value) && value >= 0;

export function observationScope(frame, runId) {
  if (!frame || frame.run_id !== runId || !runId || frame.projection !== "world.map"
    || !integer(frame.tick) || !(frame.fork_id === null || typeof frame.fork_id === "string")
    || typeof frame.view_key !== "string" || !frame.view_key
    || ["semantics_version", "policy_version", "projection_version"].some(key => !integer(frame[key]) || frame[key] < 1)) return null;
  const context = Object.fromEntries(["run_id", "fork_id", "view_key", "policy_version", "semantics_version", "projection_version"].map(key => [key, frame[key]]));
  return { runId, fork: frame.fork_id, tick: frame.tick, context, key: JSON.stringify(context) };
}

export function observationRecord(data, scope) {
  if (!scope || !data || !integer(data.version)
    || Object.keys(data.context || {}).length !== Object.keys(scope.context).length
    || Object.entries(scope.context).some(([key, value]) => data.context?.[key] !== value)) {
    throw new Error("Saved observations do not match this city context.");
  }
  return { version: data.version, entries: readObservations(JSON.stringify({ version: 1, entries: data.entries }), scope) };
}

function displayPatch(state) {
  const { tick, fork, event, agent, firm, place, project, household, institution, camera,
    follow, layer, q, population, activeOnly, view } = state;
  return { tick, fork, event, agent, firm, place, project, household, institution, camera,
    follow, layer, q, population, activeOnly, view };
}

export function observationParams(scope, state, event = null) {
  if (!scope || (state.tick !== "live" && state.tick !== String(scope.tick))
    || (state.fork != null && state.fork !== scope.fork)
    || (event !== null && (!integer(event.id) || event.id < 1 || !integer(event.tick) || event.tick > scope.tick))) {
    throw new Error("Wait for the selected city frame before saving an observation.");
  }
  return patchObserverViewState(new URLSearchParams(), { ...displayPatch(state),
    tick: String(scope.tick), fork: scope.fork, event: event?.id ?? null }).toString();
}

export function observationState(params, scope) {
  if (!scope || typeof params !== "string" || params.length > 2048) return null;
  const state = parseObserverViewState(new URLSearchParams(params));
  if (state.tick === "live" || state.fork !== scope.fork
    || patchObserverViewState(new URLSearchParams(), displayPatch(state)).toString() !== params) return null;
  return displayPatch(state);
}

export function readObservations(raw, scope) {
  if (raw === null) return [];
  if (typeof raw !== "string" || raw.length > 65536) throw new Error("Saved observations could not be read.");
  let data;
  try { data = JSON.parse(raw); } catch { throw new Error("Saved observations could not be read."); }
  if (!data || Object.keys(data).sort().join(",") !== "entries,version" || data.version !== 1
    || !Array.isArray(data.entries) || data.entries.length > OBSERVATION_LIMIT
    || new Set(data.entries).size !== data.entries.length || data.entries.some(item => !observationState(item, scope))) {
    throw new Error("Saved observations do not match this city context.");
  }
  return data.entries;
}

export function addObservation(entries, params) {
  if (entries.includes(params)) return [params, ...entries.filter(item => item !== params)];
  if (entries.length >= OBSERVATION_LIMIT) throw new Error("20 observations are saved. Remove one before adding another.");
  return [params, ...entries];
}

export function cityObjectLabel(state) {
  if (state.institution) return `Bank #${state.institution.split(":")[1]}`;
  if (state.household) return `Household #${state.household}`;
  if (state.project) return `Project #${state.project}`;
  if (state.firm) return `Business #${state.firm}`;
  if (state.place) return `Place #${state.place}`;
  if (state.agent) return `Person #${state.agent}`;
  return "City overview";
}

export function observationLabel(state) {
  return `${state.event ? `Event #${state.event} · ` : ""}Tick ${state.tick} · ${cityObjectLabel(state)}`;
}
