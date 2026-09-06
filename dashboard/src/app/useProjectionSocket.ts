import { useEffect, useReducer, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { announcedCursor, initialCursorState, reduceCursorState } from "./cursorReducer";

function socketUrl(): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws`;
}

export function useProjectionSocket(historical: boolean, enabled = true) {
  const queryClient = useQueryClient();
  const [state, dispatch] = useReducer(
    (current: typeof initialCursorState, action: { message: any; historical: boolean }) =>
      reduceCursorState(current, action.message, { historical: action.historical }),
    initialCursorState,
  );
  const cursor = useRef(0);
  const cursorState = useRef(initialCursorState);
  const legacyTick = useRef<number | null>(null);
  const projectionProtocol = useRef(false);
  const lineageRecovery = useRef(false);

  useEffect(() => {
    if (!enabled) return;
    let socket: WebSocket | null = null;
    let stopped = false;
    let retry = 0;
    let timer = 0;
    const connect = () => {
      if (stopped) return;
      socket = new WebSocket(socketUrl());
      socket.addEventListener("open", () => {
        retry = 0;
        // The server's mandatory first frame is the authoritative hello; a
        // client hello only asks for backfill after a cursor it already holds.
        // On the very first connection there is no such cursor: a hello with
        // event_cursor 0 asked the server to replay the whole commit log, and on
        // any run older than the replay window it answered
        // projection_invalidated(backfill_truncated), so every fresh load began
        // stale. Wait for the server hello instead. Reconnects still resume
        // from the last cursor, and lineage recovery waits for the new hello so
        // an old-lineage cursor is never sent against the new run or fork.
        if (projectionProtocol.current && !lineageRecovery.current) {
          socket?.send(JSON.stringify({ type: "hello", event_cursor: cursor.current }));
        }
      });
      socket.addEventListener("message", event => {
        try {
          const message = JSON.parse(event.data);
          const before = cursor.current;
          const nextCursor = Number(message.event_cursor);
          if (message.type === "hello") {
            const reconnect = projectionProtocol.current;
            const recoveringLineage = lineageRecovery.current;
            const helloCursor = Number(message.event_cursor);
            projectionProtocol.current = true;
            if (Number.isFinite(helloCursor)) cursor.current = helloCursor;
            if (!historical && (recoveringLineage
                || (reconnect && helloCursor > before))) {
              queryClient.invalidateQueries({ queryKey: ["world-os"] });
            }
            if (recoveringLineage) {
              lineageRecovery.current = false;
              socket?.send(JSON.stringify({
                type: "hello",
                event_cursor: cursor.current,
              }));
            }
          }
          const previousState = cursorState.current;
          const nextState = reduceCursorState(
            previousState,
            message,
            { historical },
          );
          cursorState.current = nextState;
          dispatch({ message, historical });
          if (message.type === "projection_delta"
              && nextState.staleReason === "lineage_mismatch") {
            lineageRecovery.current = true;
            queryClient.invalidateQueries({ queryKey: ["world-os"] });
            socket?.close();
            return;
          }
          if (message.type === "projection_delta"
              && nextState.staleReason === "cursor_gap") {
            queryClient.invalidateQueries({ queryKey: ["world-os"] });
            socket?.send(JSON.stringify({ type: "hello", event_cursor: before }));
            return;
          }
          if (message.type === "error" && message.code === "cursor_ahead") {
            const recovered = Number(message.event_cursor);
            if (Number.isFinite(recovered)) cursor.current = recovered;
            if (!historical) {
              queryClient.invalidateQueries({ queryKey: ["world-os"] });
            }
          }
          if (message.type === "tick") {
            const nextTick = Number(message.tick);
            const previousTick = legacyTick.current;
            legacyTick.current = Number.isFinite(nextTick) ? nextTick : previousTick;
            if (!historical && !projectionProtocol.current && previousTick !== null
                && Number.isFinite(nextTick) && nextTick > previousTick) {
              queryClient.invalidateQueries({ queryKey: ["world-os"] });
            }
          }
          const deltaAccepted = (
            message.type === "projection_delta"
            && nextState !== previousState
            && nextState.status === "live"
            && nextState.staleReason === null
            && nextState.cursor === nextCursor
          );
          if (deltaAccepted) {
            cursor.current = nextCursor;
            queryClient.invalidateQueries({ queryKey: ["world-os"] });
          }
          if (message.type === "projection_invalidated") {
            // A truncated same-socket recovery names the cursor the server is
            // at. Adopt it so the next delta is contiguous instead of reopening
            // the gap the refetch below is already closing.
            const invalidatedCursor = announcedCursor(message);
            if (invalidatedCursor !== null) cursor.current = invalidatedCursor;
            queryClient.invalidateQueries({ queryKey: ["world-os"] });
          }
        } catch {
          // Malformed transport data is ignored and never enters query state.
        }
      });
      socket.addEventListener("close", () => {
        if (stopped) return;
        if (!lineageRecovery.current) {
          const message = { type: "transport_closed", reason: "socket_closed" };
          cursorState.current = reduceCursorState(
            cursorState.current,
            message,
            { historical },
          );
          dispatch({ message, historical });
        }
        // Reconnect even while preserving lineage_mismatch in the UI. The new
        // socket clears lineageRecovery when its server-first hello arrives.
        retry += 1;
        timer = window.setTimeout(connect, Math.min(10_000, 250 * (2 ** retry)));
      });
    };
    connect();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
      socket?.close();
    };
  }, [historical, enabled, queryClient]);
  return state;
}
