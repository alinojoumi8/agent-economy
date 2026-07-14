export function normalizeConversationQuery(value) {
  return String(value || "").trim().slice(0, 200);
}

export function conversationSearchPath(value, limit = 50) {
  const query = normalizeConversationQuery(value);
  const boundedLimit = Math.max(1, Math.min(200, Number(limit) || 50));
  const params = new URLSearchParams({ limit: String(boundedLimit) });
  if (query) params.set("q", query);
  return `/api/conversations?${params.toString()}`;
}
