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

/** The cursor a server frame announces, or null when it carries none. */
export function announcedCursor(message) {
  const value = message?.event_cursor;
  if (value === null || value === undefined) return null;
  const cursor = Number(value);
  return Number.isFinite(cursor) ? cursor : null;
}

export function reduceCursorState(state, message, { historical = false } = {}) {
  if (!message || typeof message !== "object") return state;
  if (message.type === "transport_closed") {
    return {
      ...state,
      status: "reconnecting",
      staleReason: message.reason || "socket_closed",
    };
  }
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
  if (message.type === "error" && message.code === "cursor_ahead") {
    const recovered = Number(message.event_cursor);
    return {
      ...state,
      cursor: Number.isFinite(recovered) ? recovered : state.cursor,
      status: "stale",
      staleReason: "cursor_ahead",
    };
  }
  if (message.type === "tick") {
    // A tick frame only says the simulation advanced. While a recovery is still
    // outstanding (gap backfill, cursor reset, lineage reconnect, or a truncated
    // replay being refetched) the projection stream is behind, so the frame must
    // not declare it live; a contiguous delta or a hello does that.
    if (state.status === "stale") return state;
    return { ...state, status: "live", staleReason: null };
  }
  if (message.type === "projection_invalidated") {
    const cursor = announcedCursor(message);
    return {
      ...state,
      cursor: cursor === null ? state.cursor : cursor,
      status: "stale",
      staleReason: message.reason || "invalidated",
    };
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
