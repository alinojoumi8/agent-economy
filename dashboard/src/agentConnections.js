export const TIER_SCOPES = Object.freeze({
  observer: Object.freeze(["world.read"]),
  commons: Object.freeze(["commons.read", "commons.write"]),
  actor: Object.freeze(["world.read", "world.act", "commons.read", "commons.write"]),
});

export function scopesForTier(tier) {
  return [...(TIER_SCOPES[tier] || [])];
}

export function connectionActivity(connection, now = Date.now()) {
  if (connection.status === "revoked") return "revoked";
  if (connection.status === "suspended") return "suspended";
  if (!connection.actor_id && connection.tier !== "observer") return "actor pending";
  const lease = connection.lease_expires_at ? Date.parse(connection.lease_expires_at) : 0;
  if (lease > now) return "online";
  return connection.last_seen_at ? "offline · safe policy" : "not connected";
}

export function createConnectionPayload(runId, draft) {
  return {
    run_id: runId,
    display_name: String(draft.displayName || "").trim(),
    biography: String(draft.biography || "").trim(),
    preferred_occupation: String(draft.occupation || "").trim(),
    tier: draft.tier,
    scopes: scopesForTier(draft.tier),
    wake_interval_ticks: Number(draft.wakeInterval || 1),
  };
}
