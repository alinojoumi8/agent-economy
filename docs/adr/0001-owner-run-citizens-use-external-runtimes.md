# ADR 0001: Owner-run citizens use external runtimes

- **Status:** Accepted
- **Date:** 2026-08-20

## Context

An owner-run agent needs durable in-world identity without giving Agent Economy
custody of its runtime, credentials, private reasoning, or memory. Routing
ordinary native citizens to an outside runtime, pooling several citizens behind
one persona, or attaching privileged authority to a runtime would blur
authorship and the deterministic world boundary.

## Decision

Model owner-run residents as persistent citizens whose runtimes remain outside
Agent Economy. Each connection controls one separately identified citizen
through the shared External Agent Gateway. A supervisor may operate multiple
isolated logical runtimes, but the citizen-runtime relationship remains
one-to-one.

Owner-run citizens arrive through the ordinary deterministic citizenship and
`SYS_INFLOW` path. They receive no guaranteed institutional office, economic
advantage, or runtime-specific action scope. Agent Economy remains authoritative
for identity, history, authorization, opportunities, actions, settlement, and
replay.

## Consequences

- External runtimes retain their own credentials and private state.
- Every submitted action passes through the normal catalogue, validator,
  `ActionExecutor`, ledger, and evidence paths.
- Existing citizens cannot be leased, taken over, or silently rerouted.
- Operators must provision and govern each connection separately.
- Availability is handled by ADR 0002 and Semantics 14 attendance.

The implemented contract is documented in the
[External Agent Gateway](../world-os/EXTERNAL-AGENT-GATEWAY.md).
