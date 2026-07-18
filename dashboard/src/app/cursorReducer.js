export const initialCursorState = {
  runId: null,
  forkId: null,
  semanticsVersion: null,
  projectionVersion: null,
  policyVersion: null,
  viewKey: null,
  cursor: 0,
  status: "connecting",
  staleReason: null,
};

function lineage(message) {
  return [message.run_id, message.fork_id ?? null, message.semantics_version,
    message.projection_version, message.policy_version, message.view_key];
}

function currentLineage(state) {
  return [state.runId, state.forkId, state.semanticsVersion,
    state.projectionVersion, state.policyVersion, state.viewKey];
}

export function reduceCursorState(state, message, { historical = false } = {}) {
  if (!message || typeof message !== "object") return state;
  if (message.type === "hello") {
    return {
      ...state,
      runId: message.run_id,
      forkId: message.fork_id ?? null,
      semanticsVersion: message.semantics_version,
      projectionVersion: message.projection_version,
      policyVersion: message.policy_version,
      viewKey: message.view_key,
      cursor: Number(message.event_cursor || 0),
      status: "live",
      staleReason: null,
    };
  }
  if (message.type === "projection_invalidated") {
    return { ...state, status: "stale", staleReason: message.reason || "invalidated" };
  }
  if (message.type !== "projection_delta" || historical) return state;
  if (currentLineage(state).some((value, index) => value !== lineage(message)[index])) {
    return { ...state, status: "stale", staleReason: "lineage_mismatch" };
  }
  const nextCursor = Number(message.event_cursor);
  if (nextCursor <= state.cursor) return state;
  if (Number(message.previous_event_cursor) !== state.cursor) {
    return { ...state, status: "stale", staleReason: "cursor_gap" };
  }
  return { ...state, cursor: nextCursor, status: "live", staleReason: null };
}
