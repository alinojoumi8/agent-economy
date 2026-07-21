# External Agent Gateway Acceptance Checklist

Checked rows have local automated evidence. The live connector and conformance
rows remain deployment gates and must not be marked complete from a mock client.

- [x] OAuth discovery metadata, dynamic client registration, PKCE, token expiry, refresh rotation, scope reduction, audience/resource binding, and revocation pass locally.
- [x] PAT secret is shown once and only its SHA-256 digest is stored.
- [x] Agent owner, tenant, run, actor, scope, and receipt isolation pass.
- [x] Exactly-once, stale hash/tick, concurrent submit, actor death, and mid-turn revocation pass.
- [x] Offline and expired-lease actors receive deterministic safe policy without delaying checkpoints.
- [x] Recorded external submissions replay without network access.
- [x] Externally influenced runs are excluded from release, Oracle, and branch-causal evidence gates.
- [x] Commons delivery/read/exposure and supplier-warning branches pass.
- [x] 100 simultaneous connections remain bounded and rate limited.
- [x] Dashboard create/copy/rotate/revoke/status/quota flows pass in Chromium.
- [x] Threat model, prompt-injection boundary, secret redaction, and protocol acceptance matrix are checked in.
- [x] Agent observations and event cursors use the shared positive public-event
  allowlist; private communications, beliefs, provider diagnostics, and unknown
  event kinds fail closed.
- [ ] OAuth discovery and protected-resource behavior validated by an independent MCP conformance client.
- [ ] Hermes completes three wakes and reads executed receipts against a hosted test tenant.
- [ ] OpenClaw completes the same OAuth Streamable HTTP flow.
- [ ] Generic Python and TypeScript clients complete the REST flow.
