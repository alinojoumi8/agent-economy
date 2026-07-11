# PRD delivery tasks

These tasks are strictly sequential. A task may start only after every gate on
the preceding task has reproducible evidence. The production acceptance run is
financially gated: tooling may be built and tested without approval, but no
paid provider run starts until the operator explicitly approves that spend.

## Task 1 — Production acceptance run and evidence package

- [ ] Use one inherited production-acceptance config for 365 ticks, about 100
  agents, the five required shock types, and an automatically scored Oracle
  prediction.
- [ ] Produce machine-readable JSON and reviewer-readable Markdown evidence
  covering run completion, provider route, spend, reconciliation, Oracle p90,
  shock effects, the rumor pilot, and three documented emergent phenomena.
- [ ] Run the five-seed rumor treatment/control experiment and attach its
  reconciled comparison artifact.
- [ ] Pass focused tests, the full Python suite, dashboard tests/build, live
  dashboard/API smoke, autoreview, and diff checks.
- [ ] With explicit cost approval, pass live provider preflight and the paid
  365-tick run with every evidence gate green.

## Task 2 — R18 Participant Mode

- [ ] Let an authorized participant select one agent and submit actions through
  the exact `ActionExecutor` validation/ledger path used by simulated agents.
- [ ] Persist participant identity, prompt/action provenance, rejection reason,
  and replay-safe audit events without granting direct state mutation.
- [ ] Add the participant controls and inspector history to the dashboard.
- [ ] Test valid, invalid, unauthorized, resume, and exact-replay scenarios;
  then pass the full live-test/autoreview/commit gate.

## Task 3 — R19 1,000-agent scaling

- [ ] Implement a fully simulated core plus a statistically simulated periphery
  with deterministic seeded cohort transitions and conserved aggregate money.
- [ ] Make promotion/demotion between tiers explicit, observable, and replayable.
- [ ] Prove economic invariants and define a recorded 1,000-agent performance
  baseline before passing the full live-test/autoreview/commit gate.

## Task 4 — R20 Multi-region, trade, and FX

- [ ] Add regional ownership and markets without weakening the existing single-
  region defaults.
- [ ] Settle trade and FX through double-entry accounts with deterministic
  price/order rules and region-aware shocks.
- [ ] Expose regional/FX state in API, dashboard, reports, and replay; then pass
  invariant, integration, live-test, autoreview, and commit gates.

## Task 5 — R21 Real-data calibration

- [ ] Add versioned, provenance-bearing dataset adapters for income, wealth, and
  firm-size distributions, with validation and an offline fixture.
- [ ] Initialize deterministically from a pinned dataset snapshot and report
  calibration distance against synthetic mode.
- [ ] Test malformed/missing data, deterministic sampling, provenance, and
  backward compatibility; then pass the full gate.

## Task 6 — R22 Hosted multi-user deployment

- [ ] Add authentication, observer/admin roles, run ownership, and strict
  cross-run tenant isolation.
- [ ] Move hosted state/artifacts to durable services while retaining local
  single-user mode and reproducible run exports.
- [ ] Add deployment configuration, migrations, security/authorization tests,
  operational observability, backups, and a recorded multi-user load test.
- [ ] Pass the complete local and hosted acceptance gate before release.

## Final gate

- [ ] Re-audit PRD promises against routes, workers, persistence, tests, docs,
  and runtime evidence; leave no unclassified gap.
