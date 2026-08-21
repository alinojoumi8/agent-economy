# Architecture decision records

These records preserve durable design decisions and proposed successor
direction. They do not replace the implementation-status ledger.

## Status meanings

- **Accepted** — the stated boundary is implemented and is the current design.
- **Proposed** — direction under consideration; no implementation or release
  claim follows from the record.
- **Superseded** — replaced by a later ADR, which must be linked from both
  records.
- **Rejected** — considered and deliberately not selected.

An accepted ADR may describe a deliberately narrow seam. Its consequences must
state any adjacent runtime or governance surface that remains unimplemented.

## Index

| ADR | Status | Decision |
|---|---|---|
| [0001](0001-owner-run-citizens-use-external-runtimes.md) | Accepted | Owner-run citizens use external runtimes |
| [0002](0002-offline-owner-run-citizens-are-not-impersonated.md) | Accepted | Offline owner-run citizens are not impersonated |
| [0003](0003-owner-run-citizen-profiles-are-generated-per-city.md) | Proposed | Generate owner-run profiles per city |
| [0004](0004-civic-builder-authority-stops-at-the-world-boundary.md) | Proposed | Bound future Civic Builder authority |
| [0005](0005-city-expansion-is-threshold-triggered-and-bounded.md) | Proposed | Threshold-triggered city expansion |
| [0006](0006-city-scale-uses-a-strategic-core-and-deterministic-periphery.md) | Proposed | Strategic launch core and deterministic periphery |
| [0007](0007-builder-code-scope-is-allowlisted.md) | Accepted | Proposal-only Builder scope is allowlisted |
| [0008](0008-each-city-has-an-isolated-civic-builder.md) | Proposed | Isolate one future Civic Builder per city |
| [0009](0009-builder-authority-has-independent-safety-and-governance-revocation.md) | Proposed | Independent Builder revocation and succession |
| [0010](0010-cohort-personas-use-deterministic-bases-and-bounded-enrichment.md) | Proposed | Deterministic cohort bases with bounded enrichment |

## Record format

Each ADR contains:

- **Status** and **Date**;
- **Context** — the problem and constraints;
- **Decision** — the chosen or proposed rule;
- **Consequences** — benefits, costs, limitations, and follow-up work.

Change a proposed ADR to accepted only in the implementation branch that
delivers and verifies the stated contract. Prefer a new superseding ADR over
silently rewriting an accepted architectural decision.

Current implementation and release labels remain authoritative in
[implementation-status.md](../implementation-status.md). The implemented
external-attendance and proposal-only boundaries are explained in
[buzz-derived-architecture.md](../buzz-derived-architecture.md).
