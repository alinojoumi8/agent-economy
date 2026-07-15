import { clientLog } from "./logging.js";
import {
  apiRouting,
  hostedFetchOptions,
  resolveApiRequest,
} from "./hostedRouting.js";

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
  delete fetchOptions.cookieString;
  let response;
  try {
    response = await fetch(resolved.path, fetchOptions);
  } catch (reason) {
    clientLog("dashboard.api.network_failed", {
      path: resolved.path, method, error_type: reason?.constructor?.name || typeof reason,
      error: reason instanceof Error ? reason.message : String(reason),
    }, "error");
    throw reason;
  }
  let body = {};
  if (response.status !== 204) {
    try {
      body = await response.json();
    } catch (reason) {
      clientLog("dashboard.api.invalid_json", {
        path: resolved.path, method, status_code: response.status,
        error_type: reason?.constructor?.name || typeof reason,
        error: reason instanceof Error ? reason.message : String(reason),
      }, "warn");
    }
  }
  if (!response.ok) {
    const detail = typeof body.detail === "object" ? body.detail?.code : body.detail;
    const message = body.error || detail || `${response.status} ${response.statusText}`;
    clientLog("dashboard.api.http_failed", {
      path: resolved.path, method, status_code: response.status, error: message,
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

export const budgetState = (governor = {}) => {
  const spend = Number(governor?.total_spend_usd || 0);
  const rawCap = governor?.cap_usd;
  const capped = rawCap !== null && rawCap !== undefined && Number.isFinite(Number(rawCap));
  const cap = capped ? Number(rawCap) : null;
  const fraction = capped && cap > 0 ? Math.min(100, spend / cap * 100) : 0;
  return { spend, cap, capped, fraction };
};

export const shortKind = (kind = "") => kind.replaceAll("_", " ");
