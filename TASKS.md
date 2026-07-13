# PRD delivery tasks

These tasks are strictly sequential. A task may start only after every gate on
the preceding task has reproducible evidence. Live inference requires explicit
operator approval; the acceptance profile is uncapped and records actual spend
while provider rate limits control throughput.

## Task 1 — Production acceptance run and evidence package

- [x] Harden production execution: typed HTTP errors, provider-wide 429
  cooldown/retry, visible status, interruptible waits, and uncapped metering.
- [x] Persist completed tick vs active tick/next phase; reuse successful LLM
  responses and resume without duplicated actions, news, conversations, or memory.
- [x] Complete R6/R15 conformance with bounded Oracle evidence tools, persisted
  transcripts, and current-run/pooled calibration dashboard views.
- [x] Repair one rejected Oracle tool plan within the same bounded read-only
  contract, and replay recorded Oracle questions in exact historical replays.
- [x] Align the HTML/Markdown report contract and production documentation.
- [x] Treat explicit provider-overload responses (including MiniMax HTTP 529)
  as the same visible, interruptible, indefinite cooldown used for HTTP 429.
- [x] Resume post-fix run `da8032da59` from active tick 1 and prove its stored
  successful responses are reused without duplicate provider charges or writes.
- [x] Reconcile draft PR #10 without merging its competing acceptance stack:
  port only current, non-duplicative campaign or handbook improvements.
- [x] Publish the hardened branch as replacement PR #11 and pass fresh CI on
  the current Python/dashboard baseline.
- [x] Use one inherited production-acceptance config for 365 ticks, about 100
  agents, the five required shock types, and an automatically scored Oracle
  prediction; require six latency samples and a separate $200 efficiency gate.
- [x] Add research-valid public information boundaries, dynamic depositor-targeted
  rumors, bounded/provenance-bearing beliefs, and fail-closed relative trust evidence.
- [x] Separate final-goods output from labor income and expose correctly windowed
  30-day and year-over-year inflation without changing legacy replay semantics.
- [ ] With explicit approval, pass the capped 30-day live rumor pilot before
  authorizing a new full production acceptance run.
- [ ] Produce machine-readable JSON and reviewer-readable Markdown evidence
  covering run completion, provider route, spend, reconciliation, Oracle p90,
  shock effects, the rumor pilot, and three documented emergent phenomena.
- [x] Run the five-seed rumor treatment/control experiment and attach its
  reconciled comparison artifact.
- [x] Pass focused tests, the full Python suite, dashboard tests/build, live
  dashboard/API smoke, autoreview, and diff checks.
- [ ] With explicit live-inference approval, pass provider preflight and the
  uncapped 365-tick run with every evidence gate green.

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
