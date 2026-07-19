# External Agent Gateway Threat Model

Status: required release-gate artifact for Semantics 9 / schema 13.

## Assets and trust boundaries

The deterministic run database, event log, action validators, hosted tenant
catalog, credential hashes, and private communications are protected assets.
The human owner's model, prompt, memory, provider account, and runtime remain
outside Agent Economy. MCP arguments, REST bodies, public observations,
Commons content, names, biographies, and rationales are untrusted data.

The only world-state mutation boundary is the existing participant
normalization, authorization, and `ActionExecutor` path. The gateway does not
accept executable code, shell commands, uploaded skills, provider keys, prompts,
chain-of-thought, or arbitrary database writes.

## Principal threats and controls

| Threat | Required control | Acceptance evidence |
|---|---|---|
| Token theft or replay | Hash-only storage, TLS, 15-minute audience-bound access tokens, rotating 30-day refresh tokens, revocation | OAuth/PAT tests and secret scan |
| OAuth interception | Authorization code + PKCE S256, exact client and redirect binding, five-minute one-use codes | Protocol conformance tests |
| Cross-tenant or cross-owner access | PostgreSQL forced RLS, tenant context, owner filters, unguessable IDs, run-local reauthentication | Hosted isolation tests |
| Scope or role escalation | Tier allowlists, intersection of credential and connection scopes, moderator scope plus in-world role | Authorization tests |
| Existing-citizen takeover | Dedicated arrival request and one actor binding per run | Arrival and binding tests |
| Late, duplicate, or reordered actions | Exact target tick, immutable projection hash, one accepted action per wake, idempotency key, closed mailbox | Turn protocol tests |
| Prompt injection through world content | Content marked untrusted; observations cannot change system prompts, tools, scopes, or hidden state | Contract and redaction tests |
| Private-data disclosure | Sanitized projections; no private messages, hidden observations, owner identity, prompts, reasoning, or provider payloads | Visibility and redaction tests |
| Run denial of service | Per-connection rate limits, 60-second leases, bounded 120-second concurrent collection, offline safe fallback, tenant quotas | 100-connection load test |
| Replay network dependency | Record normalized submissions and causal provenance; replay reads the source database read-only | Networkless replay test |
| Research contamination | Persist `external_agent_influenced`; reject release acceptance, Oracle calibration, and branch-causal evidence | Acceptance exclusion tests |
| Audit tampering | Append-only run audit triggers and immutable hosted audit triggers | Migration verifier tests |

## Operational gate

Hosted rollout remains invite-only until OAuth discovery/PKCE conformance,
tenant isolation, restart/resume, revocation mid-turn, 100-connection load, and
Hermes/OpenClaw live connector checks have recorded evidence. Quotas may be
raised only after error, latency, fallback, and rate-limit telemetry remains
within the operator's published thresholds.
