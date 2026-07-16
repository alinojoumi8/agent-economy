# PRD delivery tasks

These are independently gated workstreams. Dependencies inside a workstream are
sequential, but completed extensions do not imply completion of the separate
long-horizon acceptance campaign. Live inference requires explicit operator
approval; the acceptance profile is uncapped and records actual spend while
provider rate limits control throughput.

P0/P1 and the R18–R22 functional surfaces are complete. The active pull
request remains draft while release evidence is rebuilt; do not merge, tag,
publish, or deploy publicly until the pending live gates and final provenance
audit pass under separate authorization.

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

- [x] Historical semantics-7 closure gates passed 86 tests before final hardening; a
  93-test integrated adversarial gate passed afterward, and the semantics-7
  closure suite passed 280 in 165.73 seconds. The post-merge
  compatibility/replay cleanup suite passes 303 in 178.22 seconds, with
  compilation and dataset verification green.
- [x] Preceding replay-integrity revision: 590 Python tests passed with 8 skipped, 23
  dashboard tests and a fresh 603-module build passed, and pinned
  FRED/BLS/SCF/SUSB verification passed.
- [x] Final v3 receipt-hardening tree: 599 Python tests passed with 8 skipped in
  1,618.07 seconds; compilation, documentation tests, and `git diff --check`
  passed.
- [x] Historical closure dashboard gate: 80 packages installed with zero vulnerabilities, 16 tests
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
- [x] Bind all six Oracle latency samples to their scheduled predictions across
  planning and answer validation; reject unsupported rules and dangling,
  malformed, or duplicate completion provenance without changing old replays.
- [x] Add a versioned explicit-manifest Oracle calibration evaluator plus ten
  predeclared control/rumor seed profiles. Enforce immutable floors of ten
  eligible runs, 60 resolved forecasts, both outcome classes, end-to-end p90
  below 60 seconds, and aggregate Brier score below the naive 0.25 baseline.
- [x] Add research-valid public information boundaries, dynamic depositor-targeted
  rumors, bounded/provenance-bearing beliefs, and fail-closed relative trust evidence.
- [x] Separate final-goods output from labor income and expose correctly windowed
  30-day and year-over-year inflation without changing legacy replay semantics.
- [ ] With explicit approval, pass the capped 30-day live rumor pilot before
  authorizing a new full production acceptance run.
- [x] Rehearse both 335-tick Oracle arms for free: six control negatives and six
  treatment positives resolved with zero operational failures, exact ledger
  reconciliation, and a combined scripted Brier score of `0.19469025`.
- [x] Preserve `oracle-calibration-v1-s7301` as failed diagnostic evidence. Its
  source completed tick 335 with valid live-provider provenance, but replay
  diverged at the first arrival because staged genesis reset an uncheckpointed
  persona RNG stream; checkpoint inspection also retained SQLite sidecars. It
  is not acceptance evidence and no v1 sample may enter the replacement corpus.
- [x] Land and verify the current-branch fixes for persona RNG checkpoint and
  restore, standalone SQLite checkpoint finalization, and replay target-tick
  enforcement. Column-specific genesis/checkpoint RNG validation, focused
  regressions, representative aggregate receipts, and the full suite pass.
- [x] Preserve `oracle-calibration-v2-s7311` and its generated replay as
  immutable diagnostic evidence. Both reached tick 335 and crossed the first
  arrival without the v1 divergence; canonical verification returned
  `exact: true` with `differences: []`. Receipt generation exposed a census bug:
  the checkpoint audit required exactly 100 stored agent rows even after a
  deceased row was preserved and its replacement arrival restored 100 living
  agents. Do not resume, rewrite, or reuse the v2 evidence.
- [x] Verify the corrected checkpoint receipt contract, which validates the
  bounded living population and reconciles living plus deceased rows to the
  stored total; authenticates chronological death/schedule/arrival linkage and
  `NIGHT_CLOSE` subject provenance; consumes each due schedule exactly once;
  and enforces the fixed 5–20-tick replacement delay.
- [x] Retain v3 seed 7321 as excluded diagnostic evidence. Its original receipt
  records the pre-inspection source hash and four of six forecasts as eligible;
  diagnosis later write-opened the local source artifact, so it is not
  admissible and no v3 response, claim, checkpoint, replay, or seed is reused.
- [x] Retire v4 from release eligibility. Seeds 7331 and 7332 completed with
  exact companion replays but remain diagnostic only. Seed 7333 exposed an
  advertised `gov` ledger target that mapped to the wrong account-owner
  representation; its state-dependent execution failure was mislabeled as a
  preflight rejection, so the receipt correctly excluded the run. Do not reuse
  any v4 source, response, claim, initialized marker, checkpoint, replay,
  profile, commitment, manifest entry, or seed in the replacement campaign.
- [ ] Run the ten fresh v5 live-Kimi Oracle profiles (seeds 7341–7350,
  `kimi-for-coding-highspeed`, conservative 3x metering, $25 per-run cap) through
  `--oracle-campaign-run`. V5 uses one shared state-aware preflight for runtime
  and receipt verification, advertises only historical executable entity/range
  targets, maps `gov` to the system-owned treasury account, and keeps genuine
  post-preflight execution failures out of the retry provenance channel. Each
  arm finalizes its source and exact offline companion and hashes those
  artifacts plus the checked-in profile; pass the emitted entries through
  `--oracle-calibration-report` using `runs/oracle/manifest-v5.template.yaml`
  without exclusions.
- [ ] Produce machine-readable JSON and reviewer-readable Markdown evidence
  covering run completion, provider route, spend, reconciliation, Oracle p90,
  shock effects, the rumor pilot, and three documented emergent phenomena.
- [x] Run the five-seed rumor treatment/control experiment and attach its
  reconciled comparison artifact.
- [x] Pass focused tests, the full Python suite, dashboard tests/build, live
  dashboard/API smoke, autoreview, and diff checks.
- [x] Complete free 365-tick production-workflow rehearsal `881ed41994`: 100
  living agents, zero spend, balanced ledger state, zero operational failures,
  six completed/resolved Oracle checkpoints, all five shock traces, the
  five-seed experiment, and three run-bound reviewed phenomena. Its acceptance
  receipt passed 19/20 checks; only scripted `real_providers` was intentionally
  false, so this is mechanics evidence rather than live acceptance.
- [x] Finalize and record companion replay
  `replay-881ed41994-3465cb3101`: source/replay tick 365 and hash
  `37d18cf4…498786ed` matched, every deterministic table was exact, and
  `differences: []`.
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
- [x] Persist the semantics-7 `population.baseline_citizens_core` opt-in for
  maintained non-regional profiles so household decisions stay scheduled while
  markerless semantics-7 and stored semantics 1–6 remain replay-identical.
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
- [x] Merge PR #18 at
  `21bbf30051e3de8c9b5b7a50e48a0e342d94676a` after all five PR jobs pass;
  confirm post-merge main run `29403186283` also passes all five.

## Task 6 — R22 Hosted multi-user deployment

- [x] Add invitation-based authentication, observer/admin roles, run ownership, and strict
  cross-run tenant isolation.
- [x] Add a PostgreSQL control plane with forced RLS while keeping one SQLite
  schema-v11 world per run and preserving local mode.
- [x] Move hosted snapshots to immutable local/S3-compatible artifact services while retaining local
  single-user mode and reproducible run exports.
- [x] Add a lease-based single-writer supervisor, hosted dashboard, Docker
  Compose/Caddy/Prometheus configuration, migrations, health/readiness,
  backup/verify/restore operations, and security/authorization integration tests.
- [x] Add a bounded, credential-redacted HTTPS load/isolation probe with
  per-tenant own-scope reads, cross-tenant denial checks, and sanitized JSON
  evidence output.
- [x] Record the final real-container image/Compose smoke and multi-user load
  receipt at `53081f2`, then pass all six exact-head hosted CI jobs in run
  `29409250171` at `1cf1d0a`.
- [x] Pass the complete local hosted acceptance gate and merge PR #19 as
  `1806294d4fecbe13ddbdf615c459755c74293599`. Post-merge run `29411023992`
  executed zero repository steps because GitHub blocked the account for
  billing/spending-limit reasons; this is external to the code gate.
- [ ] Before public release, repeat the final provenance/license/dependency/
  secret audit and validate the separately authorized public deployment. No
  public production deployment, tag, or publication is currently claimed.

## Closure merge receipt

- [x] Re-audit PRD promises against routes, workers, persistence, tests, docs,
  runtime evidence, licenses, dependencies, and secrets; classify R21/R22 and
  long-horizon acceptance as separate work rather than hidden merge blockers.
- [x] Confirm that P0/P1 and R18–R22 leave no additional functional PRD feature
  gap; the release-gate tooling and pending live campaigns are evidence work.
- [ ] Keep the release pull request draft until the successful v5 Oracle
  campaign, capped 30-day rumor pilot, 365-day/$200 acceptance run, and final
  provenance/license/dependency/secret audit are complete. Merge, tag,
  publication, and public deployment require separate authorization.
