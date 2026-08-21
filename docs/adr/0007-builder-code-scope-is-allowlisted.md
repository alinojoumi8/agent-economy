# ADR 0007: Builder code scope is allowlisted

- **Status:** Accepted
- **Date:** 2026-08-20

## Context

Accepting arbitrary patches, commands, or validation output from an agent would
expose the ledger, replay kernel, authentication, secrets, and deployment
surfaces. The repository needs a useful proposal artifact without granting code
application or infrastructure authority.

## Decision

Accept exactly one non-authoritative operation: `proposal.create`. Validate
declared and patch-embedded paths against the versioned
`civic-builder-proposal-v1` allowlist. Permit only persona/cohort generation,
city-expansion policy and commands, configuration, projections, focused tests,
documentation, and necessary migration proposals. Exclude the ledger,
checkpoint/replay kernel, authentication/authorization, credential handling,
and deployment infrastructure.

Build an immutable deterministic proposal ZIP containing the patch, rationale,
affected invariants, allowlisted check evidence, replay evidence, and policy.
Store it under a tenant-scoped key and verify the stored bytes before returning
a receipt. The sink cannot apply, push, merge, deploy, or invoke arbitrary
commands.

## Consequences

- A proposal is reviewable and content-addressed without becoming authority.
- Fixed check identifiers and output digests avoid storing arbitrary commands
  or raw potentially sensitive output.
- Broader changes require a separately approved human-led task.
- The implemented sink is a narrow storage seam; authenticated Builder facade,
  mandate, sandbox execution, independent review, and release integration
  remain unimplemented.

See [Buzz-derived architecture boundaries](../buzz-derived-architecture.md#proposal-only-civic-builder-support).
