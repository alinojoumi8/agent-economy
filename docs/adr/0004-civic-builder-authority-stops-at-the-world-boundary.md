# ADR 0004: Civic Builder authority stops at the world boundary

- **Status:** Proposed
- **Date:** 2026-08-20

## Context

A future Civic Builder could make bounded in-world expansion decisions and
author improvements, but allowing a citizen to change the running engine,
validators, evidence, or deployment would let it rewrite the rules governing
its own authority.

## Decision

Add a separate eleventh launch citizen with a revocable Builder Mandate. The
mandate may authorize only a bounded, engine-validated catalogue of City
Expansion Actions. It attaches to the mandate, not permanently to the persona.

The Builder may author Code Proposals in an isolated workspace. It may not
apply, push, merge, or deploy them. Independent verification and human approval
must produce a later release or semantics version before proposal content can
affect a running world.

## Consequences

- Builder authority remains meaningful in-world and independently replaceable.
- Proposal authorship cannot bypass deterministic validation or release
  governance.
- The proposal-only artifact sink in `builder_workspace/` is implemented, but
  no Civic Builder runtime, mandate facade, or expansion authority currently
  exists.
- Mandate schema, authentication, action catalogue, review workflow, and
  acceptance evidence remain future work.
