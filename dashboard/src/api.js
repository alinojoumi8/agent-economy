import { clientLog } from "./logging.js";

export async function api(path, options = {}) {
  const method = options.method || "GET";
  let response;
  try {
    response = await fetch(path, options);
  } catch (reason) {
    clientLog("dashboard.api.network_failed", {
      path, method, error_type: reason?.constructor?.name || typeof reason,
      error: reason instanceof Error ? reason.message : String(reason),
    }, "error");
    throw reason;
  }
  let body = {};
  try {
    body = await response.json();
  } catch (reason) {
    clientLog("dashboard.api.invalid_json", {
      path, method, status_code: response.status,
      error_type: reason?.constructor?.name || typeof reason,
      error: reason instanceof Error ? reason.message : String(reason),
    }, "warn");
  }
  if (!response.ok) {
    const message = body.error || `${response.status} ${response.statusText}`;
    clientLog("dashboard.api.http_failed", {
      path, method, status_code: response.status, error: message,
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
  });
}

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

export const shortKind = (kind = "") => kind.replaceAll("_", " ");
