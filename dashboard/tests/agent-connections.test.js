import assert from "node:assert/strict";
import test from "node:test";

import {
  connectionActivity,
  createConnectionPayload,
  scopesForTier,
} from "../src/agentConnections.js";

const RUN = "50000000-0000-4000-8000-000000000005";

test("connection creation binds one run and exact tier scopes", () => {
  const payload = createConnectionPayload(RUN, {
    displayName: "  Hermes Founder  ", biography: " Public bio ",
    occupation: "builder", tier: "actor", wakeInterval: "3",
  });
  assert.deepEqual(payload, {
    run_id: RUN, display_name: "Hermes Founder", biography: "Public bio",
    preferred_occupation: "builder", tier: "actor",
    scopes: ["world.read", "world.act", "commons.read", "commons.write"],
    wake_interval_ticks: 3,
  });
  assert.deepEqual(scopesForTier("observer"), ["world.read"]);
  assert.deepEqual(scopesForTier("commons"), ["commons.read", "commons.write"]);
});

test("connection status distinguishes leases and safe-policy fallback", () => {
  const now = Date.parse("2026-07-18T12:00:00Z");
  assert.equal(connectionActivity({ status: "active", tier: "actor", actor_id: null }, now), "actor pending");
  assert.equal(connectionActivity({
    status: "active", tier: "actor", actor_id: 10,
    lease_expires_at: "2026-07-18T12:00:30Z",
  }, now), "online");
  assert.equal(connectionActivity({
    status: "active", tier: "actor", actor_id: 10,
    lease_expires_at: "2026-07-18T11:59:30Z", last_seen_at: "2026-07-18T11:59:00Z",
  }, now), "offline · safe policy");
  assert.equal(connectionActivity({ status: "revoked", tier: "actor", actor_id: 10 }, now), "revoked");
});
