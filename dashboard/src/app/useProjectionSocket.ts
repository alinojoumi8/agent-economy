import { useEffect, useReducer, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { initialCursorState, reduceCursorState } from "./cursorReducer";

function socketUrl(): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws`;
}

export function useProjectionSocket(historical: boolean) {
  const queryClient = useQueryClient();
  const [state, dispatch] = useReducer(
    (current: typeof initialCursorState, action: { message: any; historical: boolean }) =>
      reduceCursorState(current, action.message, { historical: action.historical }),
    initialCursorState,
  );
  const cursor = useRef(0);
  const legacyTick = useRef<number | null>(null);
  const projectionProtocol = useRef(false);
  cursor.current = state.cursor;

  useEffect(() => {
    let socket: WebSocket | null = null;
    let stopped = false;
    let retry = 0;
    let timer = 0;
    const connect = () => {
      if (stopped) return;
      socket = new WebSocket(socketUrl());
      socket.addEventListener("open", () => {
        retry = 0;
        socket?.send(JSON.stringify({ type: "hello", event_cursor: cursor.current }));
      });
      socket.addEventListener("message", event => {
        try {
          const message = JSON.parse(event.data);
          const before = cursor.current;
          if (message.type === "hello") projectionProtocol.current = true;
          dispatch({ message, historical });
          if (message.type === "tick") {
            const nextTick = Number(message.tick);
            const previousTick = legacyTick.current;
            legacyTick.current = Number.isFinite(nextTick) ? nextTick : previousTick;
            if (!historical && !projectionProtocol.current && previousTick !== null
                && Number.isFinite(nextTick) && nextTick > previousTick) {
              queryClient.invalidateQueries({ queryKey: ["world-os"] });
            }
          }
          if (message.type === "projection_delta" && Number(message.event_cursor) > before) {
            cursor.current = Number(message.event_cursor);
            queryClient.invalidateQueries({ queryKey: ["world-os"] });
          }
          if (message.type === "projection_invalidated") {
            queryClient.invalidateQueries({ queryKey: ["world-os"] });
          }
        } catch {
          // Malformed transport data is ignored and never enters query state.
        }
      });
      socket.addEventListener("close", () => {
        if (stopped) return;
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
  }, [historical, queryClient]);
  return state;
}
