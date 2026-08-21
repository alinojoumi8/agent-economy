# ADR 0003: Owner-run citizen profiles are generated per city

- **Status:** Proposed
- **Date:** 2026-08-20

## Context

A future city launch needs varied owner-run residents without reusing a fixed
cast or letting generated biography control economic initialization, rights, or
authority.

## Decision

For each future city, generate a new ten-member Launch Cohort before its first
decision cycle. Each validated profile becomes one persistent owner-run citizen
identity in that city. Generation must satisfy a versioned Cohort Diversity
Contract across economic circumstances, life stages, occupations, values, and
dispositions.

Background and launch timing grant no office, privileged action, or exemption
from ordinary starting-state and accounting rules.

## Consequences

- Cities gain varied resident composition at the cost of cross-city character
  continuity and constrained sampling.
- The authoritative engine must assign economic state and civic standing.
- Manifests, validation, failure behavior, admission, and replay still require
  implementation and acceptance tests.
- This ADR makes no claim that cohort generation or automatic launch admission
  currently exists.
