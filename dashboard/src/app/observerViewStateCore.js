import { CITY_LAYERS } from "../lib/civicCity.js";
import { parseCityCamera, serializeCityCamera } from "../lib/cityCamera.js";

const CITY_LAYER_IDS = new Set(CITY_LAYERS.map(layer => layer.id));
const CITY_POPULATION_MODES = new Set(["core", "all", "clusters"]);
const CITY_VIEW_MODES = new Set(["atlas", "diorama", "recorded"]);

function positiveInteger(value) {
  if (!value || !/^\d+$/.test(value)) return null;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null;
}

function projectIdentifier(value) {
  const normalized = String(value || "").trim();
  if (!normalized || normalized.length > 180) return null;
  return /^[a-zA-Z0-9:_-]+$/.test(normalized) ? normalized : null;
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
  const population = params.get("population") || "core";
  const view = params.get("view") || "atlas";
  const project = projectIdentifier(params.get("project"));
  const firm = project ? null : positiveInteger(params.get("firm"));
  const requestedFollow = positiveInteger(params.get("follow"));
  const requestedAgent = positiveInteger(params.get("agent"));
  const place = positiveInteger(params.get("place"));
  const follow = project || firm || (!requestedAgent && place)
    || (requestedAgent && requestedAgent !== requestedFollow) ? null : requestedFollow;
  const agent = project || firm ? null : requestedAgent || follow;
  return {
    fork: params.get("fork")?.trim() || null,
    tick: normalizedTick(params.get("tick")),
    event: positiveInteger(params.get("event")),
    city: params.get("city")?.slice(0, 2048) || null,
    layer: CITY_LAYER_IDS.has(layer) ? layer : "all",
    q: (params.get("q") || "").slice(0, 100),
    activeOnly: params.get("activeOnly") === "1",
    agent,
    follow,
    firm,
    camera: parseCityCamera(params.get("camera")),
    place: project || firm || agent ? null : positiveInteger(params.get("place")),
    project,
    population: CITY_POPULATION_MODES.has(population) ? population : "core",
    view: CITY_VIEW_MODES.has(view) ? view : "atlas",
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
  if ("camera" in patch) setOrDelete("camera", serializeCityCamera(patch.camera));
  if ("firm" in patch) {
    const firm = Number(patch.firm);
    const selected = Number.isSafeInteger(firm) && firm > 0 ? String(firm) : null;
    setOrDelete("firm", selected);
    if (selected) {
      next.delete("agent");
      next.delete("place");
      next.delete("project");
    }
  }
  if ("agent" in patch) {
    const agent = Number(patch.agent);
    const selected = Number.isSafeInteger(agent) && agent > 0 ? String(agent) : null;
    setOrDelete("agent", selected);
    if (selected) {
      next.delete("firm");
      next.delete("place");
      next.delete("project");
    }
  }
  if ("place" in patch) {
    const place = Number(patch.place);
    const selected = Number.isSafeInteger(place) && place > 0 ? String(place) : null;
    setOrDelete("place", selected);
    if (selected) {
      next.delete("firm");
      next.delete("agent");
      next.delete("project");
    }
  }
  if ("project" in patch) {
    const project = projectIdentifier(patch.project);
    setOrDelete("project", project);
    if (project) {
      next.delete("firm");
      next.delete("agent");
      next.delete("place");
    }
  }
  if ("population" in patch) {
    const population = typeof patch.population === "string"
      && CITY_POPULATION_MODES.has(patch.population)
      ? patch.population
      : "core";
    setOrDelete("population", population === "core" ? null : population);
  }
  if ("view" in patch) {
    const view = typeof patch.view === "string" && CITY_VIEW_MODES.has(patch.view)
      ? patch.view
      : "atlas";
    setOrDelete("view", view === "atlas" ? null : view);
  }
  if ("follow" in patch) setOrDelete("follow", positiveInteger(String(patch.follow || ""))?.toString());
  // A selected object never inherits another person's follow identity.
  const follow = positiveInteger(next.get("follow"));
  if (follow && (next.has("firm") || next.has("place") || next.has("project")
    || ("agent" in patch && positiveInteger(next.get("agent")) !== follow))) next.delete("follow");
  else if (follow) next.set("agent", String(follow));
  return next;
}

/** @param {URLSearchParams} params */
export function commonObserverSearchParams(params) {
  return commonObserverParamsFromState(parseObserverViewState(params));
}

/** @param {{fork: string | null, tick: string, event: number | null, city?: string|null}} state */
export function commonObserverParamsFromState(state) {
  const common = new URLSearchParams();
  if (state.fork) common.set("fork", state.fork);
  if (state.tick !== "live") common.set("tick", state.tick);
  if (state.event) common.set("event", String(state.event));
  if (state.city) common.set("city", state.city.slice(0, 2048));
  return common;
}

/** @param {{fork: string | null, tick: string}} state */
export function projectionScopeParams(state) {
  const scope = new URLSearchParams({ tick: state.tick });
  if (state.fork) scope.set("fork_id", state.fork);
  return scope;
}
