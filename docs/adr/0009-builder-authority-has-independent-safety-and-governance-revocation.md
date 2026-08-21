# ADR 0009: Builder authority has independent safety and governance revocation

- **Status:** Proposed
- **Date:** 2026-08-20

## Context

A future Builder must not become a single point of failure for either city
governance or platform safety. Revoking authority must not delete a citizen,
transfer private authorship, or rewrite historical evidence.

## Decision

Permit automatic mandate suspension after forbidden workspace access, invariant
failure, policy-envelope breach, or repeated invalid actions. Permit immediate
human operator revocation for emergencies. Handle ordinary performance review
and succession through in-world civic governance.

Suspension stops new Builder actions and quarantines unfinished expansion or
proposal work. Succession creates a newly identified citizen and isolated
runtime. Public mandate records may carry forward; private memory and
authorship do not. The former Builder remains an ordinary resident unless
separately governed under normal citizenship rules.

## Consequences

- Safety action does not depend on city politics, and civic succession does not
  depend on operator availability.
- Historical identity and evidence remain intact.
- Conflicting revocation channels need deterministic precedence and auditable
  state transitions.
- Mandates, automated suspension, quarantine, governance review, and succession
  are not currently implemented.
