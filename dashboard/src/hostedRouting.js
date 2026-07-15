const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

const LOCAL = Object.freeze({
  hosted: false,
  tenantId: null,
  runId: null,
  csrfCookieName: null,
  csrfHeaderName: "X-AE-CSRF",
});

let routing = LOCAL;

export const HOSTED_MODE_PATH = "/api/v2/mode";

export function isUuid(value) {
  return UUID_RE.test(String(value || ""));
}

export function resetApiRouting() {
  routing = LOCAL;
  return routing;
}

export function configureHostedRouting({ tenantId = null, runId = null, csrfCookieName, csrfHeaderName }) {
  if (tenantId !== null && !isUuid(tenantId)) throw new Error("invalid hosted tenant id");
  if (runId !== null && !isUuid(runId)) throw new Error("invalid hosted run id");
  if (!csrfCookieName || /[;=\s]/.test(csrfCookieName)) throw new Error("invalid hosted CSRF cookie name");
  routing = Object.freeze({
    hosted: true,
    tenantId: tenantId ? String(tenantId).toLowerCase() : null,
    runId: runId ? String(runId).toLowerCase() : null,
    csrfCookieName,
    csrfHeaderName: csrfHeaderName || "X-AE-CSRF",
  });
  return routing;
}

export function apiRouting() {
  return routing;
}

export function tenantApiPath(path, tenantId = routing.tenantId) {
  if (!isUuid(tenantId)) throw new Error("a valid tenant id is required");
  if (routing.hosted && routing.tenantId
      && String(tenantId).toLowerCase() !== routing.tenantId) {
    throw new Error("cross-tenant API routing is denied");
  }
  const suffix = String(path || "");
  if (!suffix.startsWith("/")) throw new Error("tenant API path must be absolute");
  return `/api/v2/tenants/${String(tenantId).toLowerCase()}${suffix}`;
}

function worldApiPath(path) {
  if (!routing.tenantId || !routing.runId) throw new Error("select a hosted run first");
  if (!String(path).startsWith("/api/")) throw new Error("hosted world API path is unsupported");
  return `/api/v2/tenants/${routing.tenantId}/runs/${routing.runId}/world${path}`;
}

const CONTROLS = new Map([
  ["/api/run/start", "start"],
  ["/api/run/pause", "pause"],
  ["/api/run/stop", "stop"],
  ["/api/run/step", "step"],
  ["/api/run/speed", "speed"],
]);

export function resolveApiRequest(path, method = "GET", body = undefined, { bypass = false } = {}) {
  const verb = String(method || "GET").toUpperCase();
  if (routing.hosted && routing.tenantId && path.startsWith("/api/v2/tenants/")) {
    const tenant = path.split("/")[4]?.toLowerCase();
    if (tenant !== routing.tenantId) throw new Error("cross-tenant API routing is denied");
  }
  if (!routing.hosted || bypass || path === HOSTED_MODE_PATH || path.startsWith("/auth/")
      || path.startsWith("/api/v2/tenants/")) {
    return { path, method: verb, body };
  }
  if (verb === "GET" || verb === "HEAD") {
    return { path: worldApiPath(path), method: verb, body };
  }
  const action = CONTROLS.get(path);
  if (!action || verb !== "POST") {
    throw new Error("this mutation is unavailable in hosted mode");
  }
  if (!routing.tenantId || !routing.runId) throw new Error("select a hosted run first");
  const control = { action };
  if (action === "speed") control.delay_s = Number(body?.delay_s);
  if (action === "start" && body?.max_ticks !== undefined) control.max_ticks = Number(body.max_ticks);
  return {
    path: `/api/v2/tenants/${routing.tenantId}/runs/${routing.runId}/control`,
    method: "POST",
    body: control,
  };
}

export function readCookie(name, cookieString = globalThis.document?.cookie || "") {
  if (!name) return null;
  for (const part of String(cookieString).split(";")) {
    const [rawName, ...rawValue] = part.trim().split("=");
    if (rawName === name) {
      try { return decodeURIComponent(rawValue.join("=")); }
      catch { return rawValue.join("="); }
    }
  }
  return null;
}

export function hostedFetchOptions(options = {}, cookieString = globalThis.document?.cookie || "") {
  if (!routing.hosted) return { ...options };
  const next = { ...options, credentials: "same-origin" };
  const method = String(next.method || "GET").toUpperCase();
  if (!["GET", "HEAD", "OPTIONS"].includes(method)
      && !next.skipCsrf && next.path !== "/auth/login" && next.path !== "/auth/register") {
    const token = readCookie(routing.csrfCookieName, cookieString);
    if (!token) throw new Error("hosted CSRF cookie is missing");
    next.headers = { ...(next.headers || {}), [routing.csrfHeaderName]: token };
  }
  delete next.skipCsrf;
  delete next.path;
  return next;
}

export function observatoryWebSocketUrl(location = globalThis.location) {
  const protocol = location?.protocol === "https:" ? "wss:" : "ws:";
  const host = location?.host || "127.0.0.1";
  if (!routing.hosted) return `${protocol}//${host}/ws`;
  if (!routing.tenantId || !routing.runId) throw new Error("select a hosted run first");
  return `${protocol}//${host}/api/v2/tenants/${routing.tenantId}/runs/${routing.runId}/ws`;
}

export function hostedCapabilities(role) {
  const admin = role === "admin";
  return Object.freeze({
    administerTenant: admin,
    createRuns: admin,
    controlRuns: admin,
    observeRuns: role === "observer" || admin,
    mutateWorld: false,
  });
}
