/**
 * Synchronous deployment-mode signal.
 *
 * `/api/v2/mode` is authoritative, but it is a network call and on a live run it
 * can take tens of seconds (the simulation tick loop shares the server event
 * loop).  Blocking first paint on it renders a blank page.  The URL that served
 * the document already answers the question in one important case, with no
 * fetch at all:
 *
 *   - hosted (`hosted/app.py`) serves the observatory document at exactly one
 *     path, `"/"`.  Everything else on a hosted origin is an API route or a 404;
 *     there is no SPA history fallback (`deploy/Caddyfile` is a plain
 *     `reverse_proxy`, no `try_files`).
 *   - local (`server/app.py`) serves the same document at `"/"` *and* at
 *     `/runs/{run_id}`, `/runs/{run_id}/*`, `/commons` and `/commons/*`.
 *
 * So a document loaded at a `/runs` or `/commons` path cannot have come from a
 * hosted origin: the mode is `"local"` and is known before any fetch.  At `"/"`
 * the two deployments are byte-identical, so the mode stays `"unknown"` and the
 * caller must wait for the probe rather than guess.
 *
 * This is a presumption, not a replacement for the probe: callers keep running
 * `/api/v2/mode` and correct themselves if it ever disagrees.
 */

/** Document routes that only the local server serves. */
export const LOCAL_ONLY_DOCUMENT_ROUTES = Object.freeze(["/runs", "/commons"]);

/**
 * @param {string} [pathname] document path; defaults to the live location.
 * @returns {"local" | "unknown"} `"local"` only when the path proves it.
 */
export function presumedDeploymentMode(pathname = globalThis.location?.pathname) {
  if (typeof pathname !== "string" || !pathname.startsWith("/")) return "unknown";
  // Route matching on the server is case- and encoding-sensitive, so compare the
  // raw path: anything the local server would not have served stays "unknown".
  for (const route of LOCAL_ONLY_DOCUMENT_ROUTES) {
    if (pathname === route || pathname.startsWith(`${route}/`)) return "local";
  }
  return "unknown";
}
