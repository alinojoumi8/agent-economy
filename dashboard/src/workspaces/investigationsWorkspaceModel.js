const ROOT_KIND = /^[a-z][a-z0-9_-]*$/i;

function positiveInteger(value) {
  const text = String(value ?? "").trim();
  if (!/^\d+$/.test(text)) return null;
  const parsed = Number(text);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null;
}

/**
 * Default root inside a window of committed events: the newest goods_sale, else
 * the newest event. Null when the window is empty, so nothing is invented.
 */
export function defaultRootEventId(items) {
  const events = (Array.isArray(items) ? items : [])
    .map(item => ({ id: positiveInteger(item?.id), kind: String(item?.kind ?? "") }))
    .filter(item => item.id !== null)
    .sort((left, right) => left.id - right.id);
  if (!events.length) return null;
  const sale = [...events].reverse().find(item => item.kind === "goods_sale");
  return (sale || events[events.length - 1]).id;
}

/**
 * Resolve the causal root from the URL. A stable reference (`kind` + `id`) wins;
 * `kind` without `id` is ignored so an event id is never sent as another kind's
 * id. Then the observer `event` parameter, then the caller's fallback (the newest
 * committed event), then no root at all.
 */
export function resolveCausalRoot(params, fallbackEventId) {
  const id = positiveInteger(params.get("id"));
  if (id !== null) {
    const kind = String(params.get("kind") ?? "").trim();
    return { kind: ROOT_KIND.test(kind) ? kind : "event", id, source: "reference" };
  }
  const event = positiveInteger(params.get("event"));
  if (event !== null) return { kind: "event", id: event, source: "event" };
  const fallback = positiveInteger(fallbackEventId);
  return { kind: "event", id: fallback ?? 0, source: fallback === null ? "none" : "recent" };
}

/**
 * Root input: a typed event id replaces any stable-reference root (`kind`/`id`)
 * instead of being shadowed by it, so the field cannot snap back.
 */
export function rootEventSearch(params, rawValue) {
  const next = new URLSearchParams(params);
  next.delete("kind");
  next.delete("id");
  const event = positiveInteger(String(rawValue ?? "").replace(/\D/g, ""));
  if (event === null) next.delete("event");
  else next.set("event", String(event));
  return next;
}

/** Keep a graph selection only while the current graph still contains that node. */
export function validSelection(selected, nodes) {
  if (!selected || !Array.isArray(nodes)) return null;
  const key = `${selected.kind}:${selected.id}`;
  return nodes.some(node => node && `${node.kind}:${node.id}` === key) ? selected : null;
}
