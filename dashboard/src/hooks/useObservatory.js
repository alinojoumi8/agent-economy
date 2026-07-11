import { useCallback, useEffect, useRef, useState } from "react";
import { api, post } from "../api";
import { clientLog } from "../logging.js";

const INITIAL = {
  status: null,
  metrics: {},
  banks: [],
  firms: [],
  institutions: null,
  news: [],
  conversations: [],
  events: [],
  agents: [],
  cost: null,
  oracle: { predictions: [], scorecard: {} },
  shocks: { library: { kinds: [], trigger_types: [] }, scheduled: [] },
};

export function useObservatory() {
  const [data, setData] = useState(INITIAL);
  const [connected, setConnected] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const refreshing = useRef(false);

  const refresh = useCallback(async ({ quiet = false } = {}) => {
    if (refreshing.current) return;
    refreshing.current = true;
    if (!quiet) setLoading(true);
    try {
      const [status, metrics, banks, firms, institutions, news, conversations,
        events, agents, cost, oracle, shocks] = await Promise.all([
        api("/api/run/status"), api("/api/metrics"), api("/api/banks"),
        api("/api/firms"), api("/api/institutions"), api("/api/news?limit=24"),
        api("/api/conversations?limit=16"), api("/api/events?limit=80&min_importance=0.5"),
        api("/api/agents"), api("/api/cost"), api("/api/oracle/predictions"),
        api("/api/shocks"),
      ]);
      setData({ status, metrics, banks, firms, institutions, news, conversations,
        events, agents, cost, oracle, shocks });
      setError("");
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : String(reason);
      setError(message);
      clientLog("dashboard.refresh.failed", {
        quiet, error_type: reason?.constructor?.name || typeof reason, error: message,
      }, "error");
    } finally {
      refreshing.current = false;
      setLoading(false);
    }
  }, []);

  const act = useCallback(async (path, body) => {
    try {
      setError("");
      const result = await post(path, body);
      await refresh({ quiet: true });
      return result;
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : String(reason);
      setError(message);
      clientLog("dashboard.action.failed", {
        path, error_type: reason?.constructor?.name || typeof reason, error: message,
      }, "error");
      throw reason;
    }
  }, [refresh]);

  useEffect(() => {
    refresh();
    const timer = window.setInterval(() => refresh({ quiet: true }), 10_000);
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(`${protocol}//${window.location.host}/ws`);
    socket.addEventListener("open", () => {
      setConnected(true);
      clientLog("dashboard.websocket.connected");
    });
    socket.addEventListener("close", event => {
      setConnected(false);
      clientLog("dashboard.websocket.disconnected", {
        code: event.code, clean: event.wasClean, reason: event.reason,
      }, event.wasClean ? "info" : "warn");
    });
    socket.addEventListener("error", () => {
      setConnected(false);
      clientLog("dashboard.websocket.failed", {}, "error");
    });
    socket.addEventListener("message", (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.type === "tick") {
          setData(current => ({
            ...current,
            status: current.status ? {
              ...current.status,
              tick: payload.tick,
              status: payload.status,
              governor: payload.governor,
              pause_reason: payload.pause_reason,
              report_path: payload.report_path,
            } : current.status,
          }));
          refresh({ quiet: true });
        }
      } catch (reason) {
        clientLog("dashboard.websocket.invalid_message", {
          error_type: reason?.constructor?.name || typeof reason,
          error: reason instanceof Error ? reason.message : String(reason),
        }, "warn");
      }
    });
    const keepalive = window.setInterval(() => {
      if (socket.readyState === WebSocket.OPEN) socket.send("ping");
    }, 20_000);
    return () => {
      window.clearInterval(timer);
      window.clearInterval(keepalive);
      socket.close();
    };
  }, [refresh]);

  return { data, connected, loading, error, refresh, act };
}
