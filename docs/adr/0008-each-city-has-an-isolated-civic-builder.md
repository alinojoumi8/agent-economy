# ADR 0008: Each city has an isolated Civic Builder

- **Status:** Proposed
- **Date:** 2026-08-20

## Context

Sharing a future Builder's credentials, memory, or authority across cities
would weaken tenant isolation and causal provenance. Reusing a skill package is
different from sharing private operational state.

## Decision

Give each future city its own generated Civic Builder identity, isolated
Citizen Runtime, credentials, memory, Builder Workspace, and Builder Mandate.
Builders may reuse a versioned Builder Skill Pack but never share private state
or authority across cities.

## Consequences

- Tenant isolation, one-to-one agency, and city-specific provenance are easier
  to reason about.
- Runtime and operational duplication increase.
- Cross-city learning requires a separate public, reviewed artifact rather than
  private-memory transfer.
- No Civic Builder runtime, per-city mandate provisioning, or shared Skill Pack
  lifecycle is currently implemented.
