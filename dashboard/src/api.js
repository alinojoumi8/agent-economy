import { clientLog } from "./logging.js";
import {
  apiRouting,
  hostedFetchOptions,
  resolveApiRequest,
} from "./hostedRouting.js";

export function requestLogPath(path) {
  const value = String(path ?? "");
  const boundary = value.search(/[?#]/);
  return boundary < 0 ? value : value.slice(0, boundary);
}

export async function api(path, options = {}) {
  const method = options.method || "GET";
  const resolved = resolveApiRequest(
    path, method, options.routingBody,
    { bypass: Boolean(options.bypassHostedRouting) },
  );
  const requestOptions = { ...options, method: resolved.method };
  delete requestOptions.routingBody;
  delete requestOptions.bypassHostedRouting;
  if (resolved.body !== undefined) requestOptions.body = JSON.stringify(resolved.body);
  const fetchOptions = hostedFetchOptions(
    { ...requestOptions, path: resolved.path }, options.cookieString,
  );
  const logPath = requestLogPath(resolved.path);
  delete fetchOptions.cookieString;
  let response;
  try {
    response = await fetch(resolved.path, fetchOptions);
  } catch (reason) {
    if (reason?.name !== "AbortError") {
      clientLog("dashboard.api.network_failed", {
        path: logPath, method, error_type: reason?.constructor?.name || typeof reason,
        error: reason instanceof Error ? reason.message : String(reason),
      }, "error");
    }
    throw reason;
  }
  let body = {};
  if (response.status !== 204) {
    try {
      body = await response.json();
    } catch (reason) {
      clientLog("dashboard.api.invalid_json", {
        path: logPath, method, status_code: response.status,
        error_type: reason?.constructor?.name || typeof reason,
        error: reason instanceof Error ? reason.message : String(reason),
      }, "warn");
    }
  }
  if (!response.ok) {
    const detail = typeof body.detail === "object" ? body.detail?.code : body.detail;
    const message = body.error || detail || `${response.status} ${response.statusText}`;
    clientLog("dashboard.api.http_failed", {
      path: logPath, method, status_code: response.status, error: message,
    }, "error");
    throw new Error(message);
  }
  return body;
}

export function post(path, body) {
  return api(path, {
    method: "POST",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    routingBody: body,
  });
}

export function hostedApi(path, options = {}) {
  return api(path, { ...options, bypassHostedRouting: true });
}

export function hostedPost(path, body, options = {}) {
  return hostedApi(path, {
    ...options,
    method: "POST",
    headers: body === undefined ? options.headers : {
      "Content-Type": "application/json", ...(options.headers || {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
    routingBody: body,
  });
}

export { apiRouting };

export const money = (cents, compact = true) => {
  if (cents === null || cents === undefined || Number.isNaN(Number(cents))) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: compact ? 0 : 2,
    notation: compact && Math.abs(Number(cents)) >= 1_000_000_00 ? "compact" : "standard",
  }).format(Number(cents) / 100);
};

export const number = (value, digits = 2) => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return Number(value).toLocaleString(undefined, { maximumFractionDigits: digits });
};

export const percent = (value, digits = 1) => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return `${(Number(value) * 100).toFixed(digits)}%`;
};

const signed = (value, formatted) => {
  const numeric = Number(value);
  if (numeric > 0) return `+${formatted}`;
  if (numeric < 0) return `−${formatted.replace(/^-/, "")}`;
  return formatted;
};

const compactNumber = value => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return new Intl.NumberFormat("en-US", {
    notation: "compact", maximumFractionDigits: 1,
  }).format(Number(value));
};

export const formatMetricValue = (key, value) => {
  if (key === "unemployment") return percent(value, 1);
  if (key === "policy_rate") return `${number(value, 0)} bps`;
  if (["money_supply", "gdp_proxy", "gdp_proxy_30d", "labor_income"].includes(key)) {
    return compactNumber(value);
  }
  return number(value, ["cpi", "gini", "sentiment"].includes(key) ? 3 : 2);
};

export const formatMetricDelta = (key, value) => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  if (key === "unemployment") {
    const points = Number(value) * 100;
    return signed(points, `${Math.abs(points).toFixed(1)} pp`);
  }
  if (key === "policy_rate") {
    return signed(value, `${number(Math.abs(Number(value)), 0)} bps`);
  }
  if (["money_supply", "gdp_proxy", "gdp_proxy_30d", "labor_income"].includes(key)) {
    return signed(value, compactNumber(Math.abs(Number(value))));
  }
  return signed(value, number(Math.abs(Number(value)), 3));
};

export const formatTrust = value => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return `${Number(value).toFixed(4)} (${percent(value, 2)})`;
};

export const formatBeliefValue = (key, value) => {
  const normalized = String(key || "").toLowerCase();
  if (normalized.startsWith("trust")) return formatTrust(value);
  if (normalized.endsWith("_cents")) return money(value, false);
  return number(value, 3);
};

export const budgetState = (governor = {}) => {
  const spend = Number(governor?.total_spend_usd || 0);
  const rawCap = governor?.cap_usd;
  const capped = rawCap !== null && rawCap !== undefined && Number.isFinite(Number(rawCap));
  const cap = capped ? Number(rawCap) : null;
  const fraction = capped && cap > 0 ? Math.min(100, spend / cap * 100) : 0;
  return { spend, cap, capped, fraction };
};

export const shortKind = (kind = "") => kind.replaceAll("_", " ");
