# Paused study recovery: implementation contract

Status: scripted committed-day batch resume and CLI controls are implemented.
Finalized studies retain portable recovery evidence. Working-study library,
operator/UI integration and partial-phase recovery remain pending.
Source checkpoints inspected: `0b454b1` and `88f1e89`. This closes the implementation-design
gap in [S1](2026-09-06-research-city-specs.md#s1-research-contract-and-experiment-integrity)
before further household, school, production or banking expansion. It does not
replace the [five-part roadmap](2026-09-06-research-city-roadmap.md).

## Current executor

`research/working_attempts.py::execute_working_attempt` advances one declared
scripted cell under a process-owned batch lock. It requires the explicit
`preserve_and_resume` pause policy, a `working-attempt-v2` manifest and semantics
7 or later with persisted PRNG state. `prepare_study` binds this protocol and
its cumulative-active-time contract before execution. The ordinary study
runner dispatches that policy through `research/working_studies.py`; the local
operator interface still creates finalized version-1 studies and advertises
`resume: false` until its working-study integration is delivered.

An intact committed-day pause retains pending eligibility and append-only
segment receipts. It has no final source/replay/result receipt. Resume checks
the complete manifest, input snapshots, code/configuration, genesis, closed
source bytes, schema, phase, PRNG, references and ledger before opening a
writable Store. Source preflight uses an immutable SQLite reader only after
checking that the hash-bound source is closed and has no WAL/SHM/journal; it
does not apply that mode to live databases. Completed, failed, legacy finalized
or unreceipted attempts refuse in-place resume.

The cell executor accounts for accumulated active time across existing batch cells,
checks disk/time at committed days and before publication, and records
finalization time separately. These checks are cooperative: a single slow day
or evidence operation can exceed a sampled limit. The batch supervisor now
terminates its owned worker when a 200 ms poll detects time/disk exhaustion,
including during initialization and replay. A parent-process guard stops the
child if the supervisor dies. Sampling, the current write, process shutdown and
final diagnostic receipts can exceed a threshold; these are not filesystem quotas.
Operator idle time between calls is excluded by the new timing contract.
Closed results receive a hash seal before their timing can contribute to a
later cell's budget. A changed result or a missing finalization seal prevents
that continuation; failures retain their actual last completed day.

For a prepared 30-day scripted specification, the internal API is:

```python
from research.studies import prepare_study
from research.working_attempts import execute_working_attempt

batch = prepare_study(spec, config, input_root=".",
                      data_root="data/studies", out_dir="reports/out")
cell = dict(batch=batch, spec=spec, config=config, input_root=".",
            seed=spec.randomness.seeds[0], arm=spec.arms[0].key)
paused = execute_working_attempt(**cell, max_ticks=3)
completed = execute_working_attempt(**cell, resume=True)
```

Keep the checkout and declared inputs unchanged between these calls. The
working source is expected to advance; prior manifests and segment receipts
remain unchanged. Finalization reuses the existing independent replay and
receipt verifier, with added checks for working-segment lineage and PRNG state.
This cell API alone does not publish batch reports. Use the supervised runner
below for batch execution. Neither entry point resumes a partial active phase.

## Supervised runner and CLI

Set `operations.pause_policy: preserve_and_resume` in the study specification
before preparing a new study. Its resolved configuration hash must match the
selected config. Changing an existing manifest to enable recovery is refused.
Both goods and equity outcomes use this same execution path.

```powershell
# Use your validated study.yaml and its matching configuration.
.\.venv\Scripts\python.exe -m research.study_runner study.yaml --config runs/household-rehearsal.yaml --pause-after-ticks 3
# Set this to the exact data directory printed in the first command's batch field.
$batchDirectory = 'data/studies/<study-key>/<manifest-and-batch-id>'
.\.venv\Scripts\python.exe -m research.study_runner study.yaml --config runs/household-rehearsal.yaml --resume-batch $batchDirectory --validate-only
.\.venv\Scripts\python.exe -m research.study_runner study.yaml --config runs/household-rehearsal.yaml --resume-batch $batchDirectory
```

Keep any custom `--input-root`, `--data-root` and `--out-dir` arguments identical
across commands. `--pause-after-ticks` caps additional days per cell and stops
the batch at its first clean pause. Without that flag, resume finishes the
paused cell and remaining planned cells. The same API arguments are available
on `run_study`. CLI exit codes are 0 for completed execution, 1 for an incomplete
or paused study, and 2 for rejected validation; eligibility and missing outcomes
still require inspecting the resulting evidence.

Each invocation owns a separate supervisor lock, while its child owns the
working-attempt writer lock. Resume validates the full batch twice, including
under ownership, before creating its invocation record. Completed cells retain
their original bytes. Paused progress keeps every assigned cell and pending
eligibility; it writes `progress-NNNNNN.json`, never `results.json` or a study
publication receipt. Finalization publishes the existing result/report format
once, with the supervision contract in its operations metadata.

Append-only invocation start, end and seal records bind each progress report,
worker receipt, prior invocation and cumulative active wall time. Successful
invocations include preparation/validation, worker startup, source execution,
replay and report publication. The final timing receipt/seal has small recording
overhead; operator idle time is excluded. Resume uses the cumulative supervisor
time, which must also cover the cell executor's recorded time. It cannot raise
or reset the original budget. Missing starts, ends or seals leave crash accounting
unresolved and refuse continuation. The history limit is 1,024 invocations.

Finalized result loading and private ZIP export/import verify both supervisor
and attempt lineage, including prior pauses and result timing seals. Working
progress is currently inspectable through its JSON/CLI, with read-only
`--validate-only` compatibility checks. Working-state portable export, saved
library discovery and operator Resume controls remain the next delivery; the
existing UI job-slot release action does not resume scientific execution.

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
