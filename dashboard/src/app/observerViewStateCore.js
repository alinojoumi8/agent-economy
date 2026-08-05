import { CITY_LAYERS } from "../lib/civicCity.js";

const CITY_LAYER_IDS = new Set(CITY_LAYERS.map(layer => layer.id));

function positiveInteger(value) {
  if (!value || !/^\d+$/.test(value)) return null;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null;
}

function normalizedTick(value) {
  if (!value || value === "live") return "live";
  if (!/^\d+$/.test(value)) return "live";
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed >= 0 ? String(parsed) : "live";
}

/** @param {URLSearchParams} params */
export function parseObserverViewState(params) {
  const layer = params.get("layer") || "all";
  return {
    fork: params.get("fork")?.trim() || null,
    tick: normalizedTick(params.get("tick")),
    event: positiveInteger(params.get("event")),
    layer: CITY_LAYER_IDS.has(layer) ? layer : "all",
    q: (params.get("q") || "").slice(0, 100),
    activeOnly: params.get("activeOnly") === "1",
    agent: positiveInteger(params.get("agent")),
  };
}

/** @param {URLSearchParams} params @param {Record<string, unknown>} patch */
export function patchObserverViewState(params, patch) {
  const next = new URLSearchParams(params);
  const setOrDelete = (key, value) => {
    if (value) next.set(key, value);
    else next.delete(key);
  };

  if ("fork" in patch) setOrDelete("fork", String(patch.fork || "").trim() || null);
  if ("tick" in patch) {
    const tick = patch.tick == null ? "live" : normalizedTick(String(patch.tick));
    setOrDelete("tick", tick === "live" ? null : tick);
  }
  if ("event" in patch) {
    const event = Number(patch.event);
    setOrDelete("event", Number.isSafeInteger(event) && event > 0 ? String(event) : null);
  }
  if ("layer" in patch) {
    const layer = typeof patch.layer === "string" && CITY_LAYER_IDS.has(patch.layer)
      ? patch.layer
      : "all";
    setOrDelete("layer", layer === "all" ? null : layer);
  }
  if ("q" in patch) {
    const query = typeof patch.q === "string" ? patch.q.slice(0, 100) : "";
    setOrDelete("q", query || null);
  }
  if ("activeOnly" in patch) setOrDelete("activeOnly", patch.activeOnly ? "1" : null);
  if ("agent" in patch) {
    const agent = Number(patch.agent);
    setOrDelete("agent", Number.isSafeInteger(agent) && agent > 0 ? String(agent) : null);
  }
  return next;
}

/** @param {URLSearchParams} params */
export function commonObserverSearchParams(params) {
  return commonObserverParamsFromState(parseObserverViewState(params));
}

/** @param {{fork: string | null, tick: string, event: number | null}} state */
export function commonObserverParamsFromState(state) {
  const common = new URLSearchParams();
  if (state.fork) common.set("fork", state.fork);
  if (state.tick !== "live") common.set("tick", state.tick);
  if (state.event) common.set("event", String(state.event));
  return common;
}

/** @param {{fork: string | null, tick: string}} state */
export function projectionScopeParams(state) {
  const scope = new URLSearchParams({ tick: state.tick });
  if (state.fork) scope.set("fork_id", state.fork);
  return scope;
}
