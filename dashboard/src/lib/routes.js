export function workspaceFallbackPath(runId) {
  return runId ? `/runs/${encodeURIComponent(runId)}/overview` : "/";
}
