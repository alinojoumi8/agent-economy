export function validatedSelectedId(value) {
  const text = String(value ?? "");
  if (!/^[1-9]\d*$/.test(text)) return null;
  const parsed = Number(text);
  return Number.isSafeInteger(parsed) ? parsed : null;
}

export function normalizeWorkspaceFilters(filters, allowedKeys) {
  const allowed = new Set(allowedKeys);
  return Object.fromEntries(Object.entries(filters || {}).filter(([key, value]) => (
    allowed.has(key) && value !== null && value !== undefined && String(value) !== ""
  )));
}

export function workspaceRouteUrl(runId, path, state, extra = {}) {
  const params = new URLSearchParams();
  if (state?.fork) params.set("fork", String(state.fork));
  if (state?.tick !== null && state?.tick !== undefined
      && state.tick !== "" && state.tick !== "live") {
    params.set("tick", String(state.tick));
  }
  for (const [key, value] of Object.entries(extra)) {
    if (value !== null && value !== undefined && value !== "" && value !== false) {
      params.set(key, String(value));
    }
  }
  const query = params.toString();
  return `/runs/${encodeURIComponent(runId)}/${path}${query ? `?${query}` : ""}`;
}

export const workspaceUrl = workspaceRouteUrl;

export function validatedOrganizationType(value) {
  const type = String(value ?? "").trim().toLowerCase();
  return /^[a-z][a-z0-9_-]*$/.test(type) ? type : null;
}

export function organizationIdentity(type, id) {
  const selectedType = validatedOrganizationType(type);
  const selectedId = validatedSelectedId(id);
  return selectedType === null || selectedId === null
    ? null
    : `${selectedType}:${selectedId}`;
}

export function organizationWorkspaceUrl(runId, type, id, state) {
  const identity = organizationIdentity(type, id);
  if (identity === null) return null;
  const separator = identity.lastIndexOf(":");
  const selectedType = identity.slice(0, separator);
  const selectedId = identity.slice(separator + 1);
  return workspaceRouteUrl(
    runId,
    `organizations/${encodeURIComponent(selectedType)}/${selectedId}`,
    state,
  );
}
