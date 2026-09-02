/* Page size requested from GET /api/v2/communications/threads (server allows 1..200). */
export const THREAD_PAGE_SIZE = 50;

function positiveInteger(value) {
  const text = String(value ?? "").trim();
  if (!/^\d+$/.test(text)) return null;
  const parsed = Number(text);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null;
}

/**
 * Resolve the communication access view. "Agent view" is only active once a
 * positive agent id is present: without one the server serves the ordinary
 * principal, so the UI must neither claim an agent view nor request one.
 */
export function agentViewState(mode, rawAgentId) {
  if (mode !== "agent") {
    return { inputValue: "", agentId: null, active: false, awaitingAgentId: false, ready: true };
  }
  const digits = String(rawAgentId ?? "").replace(/\D/g, "");
  const agentId = positiveInteger(digits);
  return {
    inputValue: digits,
    agentId: agentId === null ? null : String(agentId),
    active: agentId !== null,
    awaitingAgentId: agentId === null,
    ready: agentId !== null,
  };
}

/** The next `after` cursor for the thread list, or undefined once the server reports the end. */
export function nextThreadPageParam(page) {
  if (!page || typeof page !== "object" || page.truncated !== true) return undefined;
  if (page.next_after_thread_id === null || page.next_after_thread_id === undefined) return undefined;
  const next = Number(page.next_after_thread_id);
  return Number.isSafeInteger(next) && next >= 0 ? next : undefined;
}

/** Concatenate thread pages in server (ascending id) order, dropping duplicate ids. */
export function flattenThreadPages(pages) {
  const seen = new Set();
  const items = [];
  for (const page of Array.isArray(pages) ? pages : []) {
    for (const thread of Array.isArray(page?.items) ? page.items : []) {
      const id = Number(thread?.thread_id);
      if (!Number.isSafeInteger(id) || seen.has(id)) continue;
      seen.add(id);
      items.push(thread);
    }
  }
  return items;
}

/**
 * Relate a routed thread id to the loaded pages. When the thread is not loaded,
 * `after` is the cursor that asks the server for it directly: threads are ordered
 * by id, so `after = id - 1, limit = 1` yields that thread when it is authorized.
 */
export function routedThreadLookup(routedId, loadedThreads) {
  const threadId = positiveInteger(routedId);
  if (threadId === null) return { threadId: null, loaded: false, after: null };
  const loaded = (Array.isArray(loadedThreads) ? loadedThreads : [])
    .some(thread => Number(thread?.thread_id) === threadId);
  return { threadId, loaded, after: loaded ? null : threadId - 1 };
}
