export function worldOSIndexWorkspace(pathname) {
  return /^\/commons(?:\/|$)/.test(String(pathname || ""))
    ? "commons"
    : "overview";
}

/**
 * The workspace segment of a World OS path: the segment after `/runs/:runId/`,
 * or `commons` for the bare Commons alias. Matching on the segment rather than
 * on `pathname.includes("/" + route)` keeps a run id such as
 * `world-os-v8-benchmark` from selecting the "world" workspace.
 */
export function workspaceRouteSegment(pathname) {
  const path = String(pathname || "");
  const run = /^\/runs\/[^/]+\/([^/?#]+)/.exec(path);
  if (run) return decodeURIComponent(run[1]);
  return worldOSIndexWorkspace(path) === "commons" ? "commons" : "";
}
