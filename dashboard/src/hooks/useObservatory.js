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

const RECONNECT_BASE_MS = 500;
const RECONNECT_MAX_MS = 10_000;
const TICK_REFRESH_DEBOUNCE_MS = 750;
const TICK_REFRESH_MAX_WAIT_MS = 3_000;
const REFRESH_TIMEOUT_MS = 15_000;

export function observatoryReconnectDelay(attempt) {
  const safeAttempt = Math.max(0, Math.min(Number(attempt) || 0, 30));
  return Math.min(RECONNECT_BASE_MS * (2 ** safeAttempt), RECONNECT_MAX_MS);
}

export function observatoryRefreshDeadline(timeoutMs = REFRESH_TIMEOUT_MS) {
  const controller = new AbortController();
  const timer = globalThis.setTimeout(() => controller.abort(), timeoutMs);
  return {
    signal: controller.signal,
    cancel: () => globalThis.clearTimeout(timer),
  };
}

export async function settleObservatoryRequests(requests) {
  const entries = Object.entries(requests);
  const settled = await Promise.allSettled(entries.map(([, request]) => request));
  const values = {};
  const errors = [];
  settled.forEach((result, index) => {
    const key = entries[index][0];
    if (result.status === "fulfilled") {
      values[key] = result.value;
      return;
    }
    errors.push({
      key,
      message: result.reason instanceof Error ? result.reason.message : String(result.reason),
    });
  });
  return { values, errors };
}

export function useObservatory({ hosted = false } = {}) {
  const [data, setData] = useState(INITIAL);
  const [connected, setConnected] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const refreshing = useRef(false);
  const refreshPending = useRef(false);

  const refresh = useCallback(async ({ quiet = false } = {}) => {
    if (refreshing.current) {
      refreshPending.current = true;
      return;
    }
    let nextQuiet = quiet;
    do {
      refreshing.current = true;
      refreshPending.current = false;
      const deadline = observatoryRefreshDeadline();
      const get = path => api(path, { signal: deadline.signal });
      if (!nextQuiet) setLoading(true);
      try {
        const { values, errors } = await settleObservatoryRequests({
          status: get("/api/run/status"),
          acceptance: get("/api/acceptance/status"),
          participant: get("/api/participant"),
          metrics: get("/api/metrics"),
          banks: get("/api/banks"),
          firms: get("/api/firms"),
          institutions: get("/api/institutions"),
          news: get("/api/news?limit=24"),
          conversations: get("/api/conversations?limit=16"),
          events: get("/api/events?limit=80&min_importance=0.5"),
          cost: get("/api/cost"),
          oracle: get("/api/oracle/predictions"),
          shocks: get("/api/shocks"),
          calibrationRun: hosted ? Promise.resolve(null) : get("/api/oracle/calibration?scope=run"),
          calibrationAll: hosted ? Promise.resolve(null) : get("/api/oracle/calibration?scope=all"),
          map: get("/api/v2/map"),
          legal: get("/api/v2/legal"),
          politics: get("/api/v2/politics"),
          information: get("/api/v2/information"),
          startups: get("/api/v2/startups"),
          markets: get("/api/v2/markets"),
          datasets: get("/api/v2/datasets"),
        });
        const calibrationErrors = errors
          .filter(item => item.key === "calibrationRun" || item.key === "calibrationAll")
          .map(item => `${item.key === "calibrationRun" ? "run" : "all"}: ${item.message}`);
        const requestErrors = errors.filter(
          item => item.key !== "calibrationRun" && item.key !== "calibrationAll",
        );
        const has = key => Object.prototype.hasOwnProperty.call(values, key);
        setData(current => ({
          status: has("status") ? values.status : current.status,
          acceptance: has("acceptance") ? values.acceptance : current.acceptance,
          participant: has("participant") ? values.participant : current.participant,
          metrics: has("metrics") ? values.metrics : current.metrics,
          banks: has("banks") ? values.banks : current.banks,
          firms: has("firms") ? values.firms : current.firms,
          institutions: has("institutions") ? values.institutions : current.institutions,
          news: has("news") ? values.news : current.news,
          conversations: has("conversations") ? values.conversations : current.conversations,
          events: has("events") ? values.events : current.events,
          cost: has("cost") ? values.cost : current.cost,
          oracle: has("oracle") ? values.oracle : current.oracle,
          shocks: has("shocks") ? values.shocks : current.shocks,
          calibration: {
            run: has("calibrationRun") ? values.calibrationRun : current.calibration.run,
            all: has("calibrationAll") ? values.calibrationAll : current.calibration.all,
            errors: calibrationErrors,
          },
          v2: {
            map: has("map") ? values.map : current.v2.map,
            legal: has("legal") ? values.legal : current.v2.legal,
            politics: has("politics") ? values.politics : current.v2.politics,
            information: has("information") ? values.information : current.v2.information,
            startups: has("startups") ? values.startups : current.v2.startups,
            markets: has("markets") ? values.markets : current.v2.markets,
            datasets: has("datasets") ? values.datasets : current.v2.datasets,
          },
        }));
        const message = requestErrors.map(item => `${item.key}: ${item.message}`).join("; ");
        setError(message);
        if (message) {
          clientLog("dashboard.refresh.partial_failure", {
            quiet: nextQuiet, failed_requests: requestErrors.map(item => item.key), error: message,
          }, "warn");
        }
      } catch (reason) {
        const message = reason instanceof Error ? reason.message : String(reason);
        setError(message);
        clientLog("dashboard.refresh.failed", {
          quiet: nextQuiet, error_type: reason?.constructor?.name || typeof reason, error: message,
        }, "error");
      } finally {
        deadline.cancel();
        refreshing.current = false;
        setLoading(false);
      }
      nextQuiet = true;
    } while (refreshPending.current);
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
    let disposed = false;
    let socket = null;
    let reconnectTimer = null;
    let reconnectAttempt = 0;
    let tickRefreshTimer = null;
    let tickRefreshMaxTimer = null;
    const flushTickRefresh = () => {
      if (tickRefreshTimer !== null) window.clearTimeout(tickRefreshTimer);
      if (tickRefreshMaxTimer !== null) window.clearTimeout(tickRefreshMaxTimer);
      tickRefreshTimer = null;
      tickRefreshMaxTimer = null;
      void refresh({ quiet: true });
    };
    const scheduleTickRefresh = () => {
      if (tickRefreshTimer !== null) window.clearTimeout(tickRefreshTimer);
      tickRefreshTimer = window.setTimeout(flushTickRefresh, TICK_REFRESH_DEBOUNCE_MS);
      if (tickRefreshMaxTimer === null) {
        tickRefreshMaxTimer = window.setTimeout(flushTickRefresh, TICK_REFRESH_MAX_WAIT_MS);
      }
    };
    const scheduleReconnect = () => {
      if (disposed || reconnectTimer !== null) return;
      const delay = observatoryReconnectDelay(reconnectAttempt);
      reconnectAttempt += 1;
      reconnectTimer = window.setTimeout(() => {
        reconnectTimer = null;
        connect();
      }, delay);
    };
    const connect = () => {
      if (disposed) return;
      let nextSocket;
      try {
        nextSocket = new WebSocket(observatoryWebSocketUrl(window.location));
      } catch (reason) {
        setConnected(false);
        clientLog("dashboard.websocket.failed", {
          error_type: reason?.constructor?.name || typeof reason,
          error: reason instanceof Error ? reason.message : String(reason),
        }, "error");
        scheduleReconnect();
        return;
      }
      socket = nextSocket;
      nextSocket.addEventListener("open", () => {
        if (disposed || socket !== nextSocket) return;
        reconnectAttempt = 0;
        if (reconnectTimer !== null) {
          window.clearTimeout(reconnectTimer);
          reconnectTimer = null;
        }
        setConnected(true);
        clientLog("dashboard.websocket.connected");
      });
      nextSocket.addEventListener("close", event => {
        if (disposed || socket !== nextSocket) return;
        setConnected(false);
        clientLog("dashboard.websocket.disconnected", {
          code: event.code, clean: event.wasClean, reason: event.reason,
        }, event.wasClean ? "info" : "warn");
        scheduleReconnect();
      });
      nextSocket.addEventListener("error", () => {
        if (disposed || socket !== nextSocket) return;
        setConnected(false);
        clientLog("dashboard.websocket.failed", {}, "error");
        scheduleReconnect();
        try { nextSocket.close(); } catch { /* reconnect timer remains authoritative */ }
      });
      nextSocket.addEventListener("message", (event) => {
        if (disposed || socket !== nextSocket) return;
        try {
          const payload = JSON.parse(event.data);
          if (payload.type === "tick" || payload.type === "run_status") {
            setData(current => ({
              ...current,
              status: mergeRunPayload(current.status, payload),
            }));
            if (payload.type === "tick") scheduleTickRefresh();
          }
        } catch (reason) {
          clientLog("dashboard.websocket.invalid_message", {
            error_type: reason?.constructor?.name || typeof reason,
            error: reason instanceof Error ? reason.message : String(reason),
          }, "warn");
        }
      });
    };
    connect();
    const keepalive = window.setInterval(() => {
      if (socket?.readyState === WebSocket.OPEN) socket.send("ping");
    }, 20_000);
    return () => {
      disposed = true;
      window.clearInterval(timer);
      window.clearInterval(keepalive);
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
      if (tickRefreshTimer !== null) window.clearTimeout(tickRefreshTimer);
      if (tickRefreshMaxTimer !== null) window.clearTimeout(tickRefreshMaxTimer);
      socket?.close();
    };
  }, [refresh]);

  return { data, connected, loading, error, refresh, act };
}
