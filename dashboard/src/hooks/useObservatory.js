import { useCallback, useEffect, useRef, useState } from "react";
import { api, post } from "../api";
import { clientLog } from "../logging.js";
import { mergeRunPayload } from "../runState.js";
import { observatoryWebSocketUrl } from "../hostedRouting.js";

const INITIAL = {
  status: null,
  acceptance: { configured: false, checks: [] },
  participant: { enabled: false, active: false },
  metrics: {},
  banks: [],
  firms: [],
  institutions: null,
  news: [],
  conversations: [],
  events: [],
  cost: null,
  oracle: { predictions: [], scorecard: {} },
  calibration: { run: null, all: null, errors: [] },
  shocks: { library: { kinds: [], trigger_types: [] }, scheduled: [] },
  v2: { map: null, legal: null, politics: null, information: null, startups: null, markets: null, datasets: null },
};

export function useObservatory({ hosted = false } = {}) {
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
      const calibrationErrors = [];
      const safeCalibration = async (path, scope) => {
        try { return await api(path); }
        catch (reason) {
          calibrationErrors.push(`${scope}: ${reason instanceof Error ? reason.message : String(reason)}`);
          return null;
        }
      };
      const [status, acceptance, participant, metrics, banks, firms, institutions, news, conversations,
        events, cost, oracle, shocks, calibrationRun, calibrationAll,
        map, legal, politics, information, startups, markets, datasets] = await Promise.all([
        api("/api/run/status"), api("/api/acceptance/status"),
        api("/api/participant"),
        api("/api/metrics"), api("/api/banks"),
        api("/api/firms"), api("/api/institutions"), api("/api/news?limit=24"),
        api("/api/conversations?limit=16"), api("/api/events?limit=80&min_importance=0.5"),
        api("/api/cost"), api("/api/oracle/predictions"),
        api("/api/shocks"),
        hosted ? Promise.resolve(null) : safeCalibration("/api/oracle/calibration?scope=run", "run"),
        hosted ? Promise.resolve(null) : safeCalibration("/api/oracle/calibration?scope=all", "all"),
        api("/api/v2/map"), api("/api/v2/legal"), api("/api/v2/politics"),
        api("/api/v2/information"), api("/api/v2/startups"), api("/api/v2/markets"),
        api("/api/v2/datasets"),
      ]);
      setData({ status, acceptance, participant, metrics, banks, firms, institutions, news, conversations,
        events, cost, oracle, shocks,
        calibration: { run: calibrationRun, all: calibrationAll, errors: calibrationErrors },
        v2: { map, legal, politics, information, startups, markets, datasets } });
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
  }, [hosted]);

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
    const socket = new WebSocket(observatoryWebSocketUrl(window.location));
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
        if (payload.type === "tick" || payload.type === "run_status") {
          setData(current => ({
            ...current,
            status: mergeRunPayload(current.status, payload),
          }));
          if (payload.type === "tick") refresh({ quiet: true });
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
