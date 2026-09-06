import { commonObserverParamsFromState, parseObserverViewState, patchObserverViewState } from "./observerViewStateCore.js";

// A city bookmark contains display state only. A destination keeps its own
// renderer/view parameter, and the current run/fork/tick always takes precedence.
function displayParams(state) {
  const { agent, firm, place, project, view, layer, population, q, activeOnly, camera } = state;
  return patchObserverViewState(new URLSearchParams(), {
    agent, firm, place, project, view, layer, population, q, activeOnly, camera,
  });
}

export function cityEvidenceParams(state) {
  const params = commonObserverParamsFromState(state);
  const bookmark = displayParams(state).toString();
  if (bookmark) params.set("city", bookmark); else params.delete("city");
  return params;
}

export function cityWorkspaceHref(runId, state, selection = {}) {
  const restored = parseObserverViewState(new URLSearchParams(String(state.city || "").slice(0, 2048)));
  const params = patchObserverViewState(displayParams(restored), {
    fork: state.fork, tick: state.tick, event: state.event, ...selection,
  });
  return `/runs/${encodeURIComponent(runId)}/world${params.size ? `?${params}` : ""}`;
}
