# Paused study recovery: implementation contract

Status: planned; no resumable study executor is delivered by this document.
Source checkpoint inspected: `0b454b1`. This closes the implementation-design
gap in [S1](2026-09-06-research-city-specs.md#s1-research-contract-and-experiment-integrity)
before further household, school, production or banking expansion. It does not
replace the [five-part roadmap](2026-09-06-research-city-roadmap.md).

## Existing behavior and compatibility boundary

`research/attempts.py::execute_attempt` exclusively creates a cell directory,
then publishes source and result receipts even when execution pauses. Those
version-1 attempts are finalized artifacts. `research/study_runner.py::run_study`
also publishes the enclosing results and publication receipt after a pause.
Neither artifact may become writable through a new resume command. Retrying a
legacy finalized attempt requires a new attempt identity.

`run.py::open_run` already restores persisted configuration, world status and
PRNG state for ordinary simulation resume. It opens a writable Store, which may
run additive migrations. Research compatibility checks must therefore finish
with a read-only Store before calling it. Do not use its ordinary operational
configuration overrides to alter a research contract.

`research/process_lock.py::process_lock` supplies a portable process-owned
lock. `research/artifacts.py::publish_json` and `publish_bytes` deliberately
refuse replacement. Reuse them for manifests, segment records and final
receipts. Do not weaken their immutable publication semantics to make progress
updates convenient.

## Delivery order

1. Introduce an explicit working-attempt protocol alongside version 1. Bind
   the claim to the study manifest, code identity, resolved arm configuration,
   input and model-description hashes, seed, horizon, behavior policy and
   schema/semantics. Persist operational progress separately from this claim.
2. Support a clean pause at a committed day boundary, with an append-only
   segment receipt binding the closed source database, canonical state, PRNG,
   phase, genesis and claim hashes. A paused working attempt has pending
   eligibility and no final source/replay/result receipt.
3. Add read-only resume validation and an exclusive writer lock held through
   execution and receipt publication. Recheck the bound database after taking
   the lock. Validate all declared inputs and current code before opening a
   writable Store. Refuse changed files, aliases outside the owned namespace,
   missing segment receipts, incompatible schema/semantics, invalid ledger or
   references, external-agent influence, terminal/finalized attempts and an
   already active owner. Rejections must preserve every scientific byte.
4. Resume from the remaining horizon using restored engine/persona PRNG state;
   never reinitialize genesis, reseed the world or replay settled actions.
   Add partial-phase recovery only after proving phase-specific idempotence and
   recorded-input handling. Until then, refuse an unfinished active tick with
   a named reason rather than treating it as a clean pause.
5. Integrate batch recovery into the study runner and CLI. A resume command
   selects an existing working batch and verifies the same specification and
   configuration. Already completed cells retain their original receipts;
   only the compatible paused cell and remaining planned cells execute.
   Preserve every segment and exclusion. Publish aggregate results once all
   assigned cells have reached their declared terminal disposition.
6. Extend evidence verification, portable exports, the saved-study library
   and local operator jobs together. Working studies must remain discoverable
   with their actual completed horizon and pending eligibility. UI recovery
   retains run/fork authorization, CSRF, path confinement, supervisor locks
   and orphan-worker termination. Show a Resume action only when its checked
   contract is compatible. Both goods and equity studies use the same path.

## Operational and publication rules

- Track cumulative active execution time, provider calls/tokens/spend and
  artifact bytes across segments. Resuming must not reset a study's declared
  limits. Exclude operator idle time only under an explicit versioned timing
  definition. Exhausting a fixed protocol budget cannot authorize a larger
  budget; a changed protocol requires a new study/attempt identity.
- Distinguish a cooperative, receipted pause from a killed or crashed worker.
  An unmatched segment-start record or unverifiable SQLite/WAL state is not
  resumable merely because its process disappeared. Preserve it as failed or
  pending evidence, with a named recovery disposition.
- Close the source before hashing and publish final evidence in the existing
  source -> independent recorded replay -> verified result order. A crash
  between stages stays pending/ineligible. The existence of a database or a
  `completed` label alone cannot authorize a complete-window comparison.
- A study result may refer only to frozen attempt receipts. Once published,
  source/replay/result artifacts remain immutable. New analyses create new
  artifacts with explicit lineage rather than replacing an earlier report.

## Required acceptance evidence

- A scripted three-day pause followed by resume to day 30 equals an
  uninterrupted source and its independent recorded replay across canonical
  tables, realized decisions, ledger, PRNG state and measurements.
- The day-three working state cannot enter a day-30 effect. A paused batch
  retains all assigned arms and seeds, including cells not yet started.
- Manifest, code, policy, config, input, source, PRNG, phase and schema changes
  each refuse resume before any scientific write. Legacy finalized paused
  attempts, completed attempts and failed attempts also refuse in-place resume.
- Concurrent resume calls admit exactly one writer. Supervisor termination
  cannot leave an unbudgeted worker or convert an interrupted segment into
  successful evidence. No resume path resets cumulative operational limits.
- Export/import verification retains segment provenance and detects altered
  ancestry. Historical results remain unchanged and visible after a later
  resume, rejection, failure or new attempt.
- Run bounded focused tests under a short Windows temporary root with a
  40 GiB free-space preflight. Use CI shards for the complete Python suite;
  record interrupted or disk-exhausted checks as inconclusive.
