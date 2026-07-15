# PRD delivery tasks

These are independently gated workstreams. Dependencies inside a workstream are
sequential, but completed extensions do not imply completion of the separate
long-horizon acceptance campaign. Live inference requires explicit operator
approval; the acceptance profile is uncapped and records actual spend while
provider rate limits control throughput.

## Legal-Economy v2 semantics-7 closure

### Implementation

- [x] Checkpoint the pre-existing six-feature work and move maintained profiles
  to `engine_semantics_version: 7` without changing database schema v11.
- [x] Gate new economic, lifecycle, prompt, and policy behavior so markerless and
  stored semantics 1–6 retain their historical execution paths.
- [x] On default, seize eligible collateral before posting only unrecovered
  principal from the bank's currency-matched equity account to `SYS_LOSS` as a
  balanced `loan_loss_chargeoff` transaction.
- [x] Add retiree-only `withdraw_savings`; map lifecycle config
  `retirement_liquidity_target_cents` to public decision field
  `retirement_drawdown_target_cents`; apply retirement cadence at genesis and
  transition, no retiree job search, and stronger conversation participation.
- [x] Own the persona-library wrapper; spawn due arrivals deterministically at
  `NIGHT_CLOSE` with visible population inflow and a 70/30 checking/savings
  split; require one governed `role=persona,purpose=persona` call before the
  arrival's first morning decision.
- [x] Expose bounded regional wallet/FX facts, no more than five executable trade
  opportunities, and career-gated migration destinations; activate authorized
  scripted shipments and migration under semantics 7.
- [x] Preserve logical LLM-reference replay canonicalization, add the sanitized
  ten-tick `fd0adc5dc1` fixture, and fail closed on missing/dangling references.
  The recorded source is semantics 5, despite the earlier plan describing it as
  semantics 6.
- [x] Add `prompt_cache_mode` (`off`, `provider_automatic`, `openai_key`,
  `anthropic_ephemeral`), retain the legacy key alias, and make the additive
  memory-ranking formula authoritative.
- [x] Add paired `v2-spec-closure-rehearsal` and `v2-spec-closure-live` profiles
  with a near-defaulted loan, retiree, due arrival, shipment, and migration path.

### Evidence gates

- [x] Focused semantics-7 gate passed 86 tests before final hardening; a
  93-test integrated adversarial gate passed afterward, and the semantics-7
  closure suite passed 280 in 165.73 seconds. The post-merge
  compatibility/replay cleanup suite passes 303 in 178.22 seconds, with
  compilation and dataset verification green.
- [x] Dashboard gate: 80 packages installed with zero vulnerabilities, 16 tests
  passed, high-severity audit found zero vulnerabilities, the 599-module Vite
  build and committed static bundle matched, and `git diff --check` passed.
- [x] Free rehearsal `5a0d40d773` reached tick 5 at zero spend, exercised every
  targeted effect with zero rejection/provider failures, wrote six checkpoints,
  balanced all currencies, and replayed exactly as
  `replay-5a0d40d773-b45777cf29` with `differences: []`.
- [x] MiniMax-M3 preflight passed. Live pilot `b4832032ba` reached tick 5 under
  semantics 7/schema 11 for `$0.01121124`; all 42 proposals were accepted, all
  targeted effects fired, provenance/privacy checks found zero defects, six
  checkpoints and all currencies reconciled, and exact replay
  `replay-b4832032ba-8d99c25c56` returned `differences: []`.
- [x] The exact closure head passed every dashboard and Ubuntu/Windows Python
  3.11/3.12 job. PR #15 merged to `main` as
  `255555c2b24530c0bd39aed2f501277a468adc0a`, and post-merge CI run
  `29368193807` repeated all five jobs successfully. Tagging and publication
  remain separate.

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

- [x] Let an authorized participant select one agent and submit actions through
  the exact `ActionExecutor` validation/ledger path used by simulated agents.
- [x] Persist participant identity, prompt/action provenance, rejection reason,
  and replay-safe audit events without granting direct state mutation.
- [x] Add the participant controls and paginated inspector history to the dashboard.
- [x] Test valid, invalid, unauthorized, resume, and exact-replay scenarios;
  then pass the full live-test/autoreview/commit gate.

## Task 3 — R19 1,000-agent scaling

- [x] Implement a fully simulated core plus a statistically simulated periphery
  with deterministic seeded cohort transitions and conserved aggregate money.
- [x] Make promotion/demotion between tiers explicit, observable, and replayable.
- [x] Prove economic invariants and define a recorded 1,000-agent performance
  baseline before passing the full live-test/autoreview/commit gate.

## Task 4 — R20 Multi-region, trade, and FX

- [x] Add regional ownership and markets without weakening the existing single-
  region defaults.
- [x] Settle trade and FX through double-entry accounts with deterministic
  price/order rules and region-aware shocks.
- [x] Expose regional/FX state in API, dashboard, reports, and replay; then pass
  invariant, integration, live-test, autoreview, and commit gates.
- [x] Close the semantics-7 autonomy gap with engine-qualified trade and
  career-gated migration context plus deterministic scripted action policies.

## Task 5 — R21 Real-data calibration

- [x] Pin aggregate FRED/BLS calibration fixtures with checksums, precise source
  metadata/terms, deterministic refresh validation, and offline tests.
- [x] Add versioned, provenance-bearing dataset adapters for income, wealth, and
  firm-size distributions, with validation and an offline fixture.
- [x] Initialize deterministically from a pinned dataset snapshot and report
  calibration distance against synthetic mode.
- [x] Test malformed/missing data, deterministic sampling, provenance, and
  backward compatibility; then pass the full gate.

## Task 6 — R22 Hosted multi-user deployment

- [ ] Add authentication, observer/admin roles, run ownership, and strict
  cross-run tenant isolation.
- [ ] Move hosted state/artifacts to durable services while retaining local
  single-user mode and reproducible run exports.
- [ ] Add deployment configuration, migrations, security/authorization tests,
  operational observability, backups, and a recorded multi-user load test.
- [ ] Pass the complete local and hosted acceptance gate before release.

## Closure merge receipt

- [x] Re-audit PRD promises against routes, workers, persistence, tests, docs,
  runtime evidence, licenses, dependencies, and secrets; classify R21/R22 and
  long-horizon acceptance as separate work rather than hidden merge blockers.
