# ADR 0005: City expansion is threshold-triggered and bounded

- **Status:** Proposed
- **Date:** 2026-08-20

## Context

Unbounded growth or one-tick reactions could destabilize housing, services,
fiscal capacity, and inference spend. A future Builder needs measurable
conditions and limits rather than a general instruction to maximize population.

## Decision

Optimize for a versioned City Health Envelope. Monitor recorded population,
employment, housing, service queues, civic capacity, fiscal resources, and
runtime health. Permit an Expansion Plan only after configured thresholds
remain breached for a persistence window.

Plans must restore or preserve the envelope, fit pre-approved affordability and
infrastructure limits, observe cooldowns, and emit auditable completion
evidence. In-world capacity changes may execute only through validated actions.
Provisioning external runtimes, increasing real inference spend, or deploying
code still requires human approval.

## Consequences

- Expansion becomes measurable and reviewable rather than subjective.
- Persistent thresholds and cooldowns trade responsiveness for stability.
- Signals, thresholds, affordability rules, plan schema, action execution, and
  receipts require future implementation.
- Existing construction mechanics do not imply this autonomous expansion
  controller.
