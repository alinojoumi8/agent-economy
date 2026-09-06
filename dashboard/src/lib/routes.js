export function workspaceFallbackPath(runId) {
  return runId ? `/runs/${encodeURIComponent(runId)}/overview` : "/";
}

const LEGACY_CITY_PARAMS = [
  "view", "agent", "firm", "place", "project", "camera", "population", "layer", "activeOnly", "q", "region",
];

export function legacyCityRedirectPath(runId, search = "", hash = "") {
  if (!runId) return null;
  const normalizedSearch = search
    ? search.startsWith("?") ? search : `?${search}`
    : "";
  const params = new URLSearchParams(normalizedSearch);
  if (!LEGACY_CITY_PARAMS.some(key => params.has(key))) return null;
  const normalizedHash = hash
    ? hash.startsWith("#") ? hash : `#${hash}`
    : "";
  return `/runs/${encodeURIComponent(runId)}/world${normalizedSearch}${normalizedHash}`;
}

export function recordedCityRedirectPath(runId, search = "", hash = "") {
  const params = new URLSearchParams(search);
  params.set("view", "recorded");
  if (!params.has("population")) params.set("population", "all");
  return `/runs/${encodeURIComponent(runId)}/world?${params}${hash}`;
}
