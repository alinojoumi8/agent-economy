import { projectionScopeParams } from "./observerViewStateCore.js";

/** @param {any} frame
 * @param {{runId: string, fork: string|null, tick: string}} scope
 * @param {string} projection */
function requireFrame(frame, scope, projection) {
  if (!frame || frame.run_id !== scope.runId || frame.projection !== projection
    || !Number.isSafeInteger(frame.tick) || frame.tick < 0
    || (scope.tick !== "live" && String(frame.tick) !== scope.tick)
    || (scope.fork !== null && frame.fork_id !== scope.fork)
    || !(frame.fork_id === null || typeof frame.fork_id === "string")
    || typeof frame.view_key !== "string" || !frame.view_key
    || ["semantics_version", "policy_version", "projection_version"].some(key => !Number.isSafeInteger(frame[key]) || frame[key] < 1)
    || !frame.data || typeof frame.data !== "object" || Array.isArray(frame.data)) {
    throw new Error("City evidence does not match the selected run, fork, tick or projection.");
  }
}

/** @param {{runId: string, fork: string|null, tick: string, population: string}} scope
 * @param {(path: string) => Promise<any>} read */
export async function loadCityProjection(scope, read) {
  const mapParams = projectionScopeParams(scope);
  mapParams.set("layers", "regions,agents,organizations,places,construction_projects,presence,flows");
  mapParams.set("population", scope.population);
  const map = await read(`/api/v2/world-map?${mapParams}`);
  requireFrame(map, scope, "world.map");
  const resolved = { ...scope, tick: String(map.tick), fork: map.fork_id ?? null };
  const pinned = projectionScopeParams(resolved);
  const [civic, overview] = await Promise.all([
    read(`/api/v2/civic/summary?${pinned}`),
    read(`/api/v2/snapshot?${pinned}&domains=summary,events`),
  ]);
  for (const [frame, projection] of [[civic, "civic.summary"], [overview, "world.snapshot"]]) {
    requireFrame(frame, resolved, projection);
    if ((frame.fork_id ?? null) !== resolved.fork || ["view_key", "policy_version", "semantics_version"]
      .some(key => frame[key] !== map[key])) {
      throw new Error("City projections changed lineage or visibility while loading. Refresh this frame.");
    }
  }
  if (civic.data.tick !== undefined && civic.data.tick !== map.tick) {
    throw new Error("Civic evidence does not belong to the map's recorded tick.");
  }
  return { envelope: map, map: map.data, civic: { ...civic.data, tick: map.tick }, overview,
    agents: map.data.agents || [], firms: map.data.organizations || [] };
}

/** Load optional transcripts only after the shared map has resolved its day.
 * @param {any} map @param {(path: string) => Promise<any>} read */
export async function loadCityConversations(map, read) {
  const scope = { runId: map.run_id, fork: map.fork_id, tick: String(map.tick) };
  requireFrame(map, scope, "world.map");
  const frame = await read(`/api/v2/city/conversations?${projectionScopeParams(scope)}&limit=60`);
  requireFrame(frame, scope, "city.conversations");
  if (frame.fork_id !== map.fork_id || ["view_key", "policy_version", "semantics_version"]
    .some(key => frame[key] !== map[key]) || frame.data.tick !== map.tick
    || frame.data.source !== "recorded_small_talk" || !Array.isArray(frame.data.items)
    || frame.data.items.some(item => item.tick !== map.tick)) {
    throw new Error("Recorded conversations do not belong to this city frame.");
  }
  return { ...frame, mapSnapshot: map.snapshot_version };
}

/** @param {any} runtime @param {any} frame @param {string} observerTick */
export function cityRuntimeMatches(runtime, frame, observerTick) {
  return Boolean(observerTick === "live" && frame && runtime?.context?.tick === "live"
    && runtime.context.run_id === frame.run_id
    && (runtime.context.fork_id ?? null) === (frame.fork_id ?? null));
}
