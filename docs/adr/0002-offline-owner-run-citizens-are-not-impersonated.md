# ADR 0002: Offline owner-run citizens are not impersonated

- **Status:** Accepted
- **Date:** 2026-08-20

## Context

The deterministic world must continue when an external Citizen Runtime is
offline, late, revoked, or otherwise unavailable. Selecting a platform model or
native policy and presenting that decision as the owner's action would break
authentic authorship and the one-to-one boundary established by ADR 0001.

## Decision

When an owner-run citizen is due and its runtime does not submit in time, record
a missed turn and apply the versioned `safe_do_nothing_v1` deterministic
fallback. Do not impersonate the owner with another model or policy. The
citizen remains present; ordinary obligations, lifecycle, and world
consequences continue.

An explicitly submitted `do_nothing` remains an authored submission and is
not classified as missed attendance.

## Consequences

- Outages reduce authored activity instead of fabricating it.
- The world can advance deterministically without deleting or killing the
  citizen.
- Semantics 14 records the operational reason separately from the applied
  fallback, and replay copies that evidence exactly.
- Operators can measure availability, but attendance alone does not prove
  action success, intent, or runtime health.

See [Semantics 14 external-turn attendance](../semantics14-external-turn-attendance.md).
