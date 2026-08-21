# ADR 0010: Cohort personas use deterministic bases and bounded enrichment

- **Status:** Proposed
- **Date:** 2026-08-20

## Context

Generated personas can make cohorts expressive, but model output must not
silently determine wealth, accounts, housing, opportunities, rights, or civic
authority. Those are authoritative simulation inputs and outcomes.

## Decision

Begin every future City Cohort with a seeded deterministic demographic base.
Allow bounded enrichment of identity fields such as name, biography, goals,
personality, values, and preferred occupation. Validate the complete Cohort
Manifest against a schema and the versioned Cohort Diversity Contract before
admission.

The engine alone assigns economic initialization and civic standing.

## Consequences

- Same-seed base generation can be reproduced independently of model prose.
- Expressive identity is separated from material starting advantage.
- Enrichment failures can fall back to the deterministic base without
  fabricating economic state.
- Schema, diversity rules, enrichment provider policy, admission, provenance,
  replay, and privacy review remain future work.
