# Paired studies from saved worlds

Status: implementation in progress under recommendations 1–2 of the research
city roadmap. Goods and equity studies have equal scope and acceptance gates.

## Current implementation

The backend now admits explicit closed sources, prepares version 2 study
manifests, runs paired continuations, and replays their new interval from
independent origin copies. Frozen, committed-day recovery and saved-phase
recovery use attempt version 4; existing attempt versions 1–3 retain their
genesis interpretation. Independent readers and private bundles verify the
origin, inherited input prefix, continuation outcomes and separate new costs.
Local recovery checks passed 55 tests; the expanded source, study, transport,
external-agent, participant and legacy replay regression passed 122 tests.
Those runs used short temporary paths and the 40 GiB free-space guard. CI and
the remaining operator interface work are tracked in the execution log.

The operator launcher now offers explicit saved-world selection, reviewed
origin details and the existing deliberate launch/recovery controls. Comparison
shows initial conditions and the new execution interval. Its operator/API
regression passed 68 tests; the full browser suite passed 108 tests with one
opt-in test skipped, and all 242 UI unit tests passed. See the execution log
and draft PR for exact commands, CI results and the remaining broader roadmap.

## Local operator interface

Choose **Create a study → Initial conditions → Saved worlds**. The local
operator-only catalog reads immediate `.db` children of
`operator_research.checkpoint_root` (default `data/checkpoints`). It never
recursively scans the project, creates a snapshot of the observed world, accepts
a browser-supplied path or copies a source during catalog/validation reads.

The initial interface retains the fixed `runs/price-lab-pilot.yaml` economic
profile, original source seeds, at most five initial worlds, a 30-day absolute
horizon, 300 active seconds and a 128 MiB evidence budget. Individual snapshots
are limited to 16 MiB. Catalog work is bounded by 500 entries, 128 MiB of source
sizes examined and 20 compatible choices; omissions/truncation are explicit.
The CLI remains available for other compatible profiles and explicit budgets.

Choose the same completed day from distinct seed/run identities. Source
selection binds both database and admission hashes. Validation, launch, the
supervisor and resume recheck the original sources and fixed configuration.
Storage planning includes the admitted context plus independent source/replay
copies for each arm and an explicitly uncalibrated growth allowance. Sources
and their original directory must remain available for operator recovery.

The reviewed protocol shows source identity, retained seeds, saved day,
continuation and measurement intervals before launch. Refreshing the source
catalog clears the selection. Historical/foreign contexts and hosted mode
cannot read it. Public origin details omit configuration, paths and recorded
input bodies; full scientific evidence remains in private bundles.

## Command-line drafting and execution

Use the configuration that produced the saved worlds. The economic settings,
policy, semantics and source seeds must match; only checkpoint/report output
paths, checkpoint frequency and delay are operational differences. Sources must
have the same completed day and distinct original seeds and run identities.
The current executor requires an explicitly scripted provider-free policy.

For example, replace the two example paths with compatible closed snapshots:

```powershell
.\.venv\Scripts\python.exe -m research.price_catalog G2 --config runs/price-lab-pilot.yaml --checkpoint checkpoints/research/seed-1.db --checkpoint checkpoints/research/seed-2.db --input-root . --ticks 30 --intervention-tick 12 --warmup-ticks 1 --pause-policy preserve_and_resume_phases --output reports/drafts/checkpoint-g2.json
.\.venv\Scripts\python.exe -m research.study_runner reports/drafts/checkpoint-g2.json --config runs/price-lab-pilot.yaml --input-root . --validate-only
.\.venv\Scripts\python.exe -m research.study_runner reports/drafts/checkpoint-g2.json --config runs/price-lab-pilot.yaml --input-root . --pause-after-phase MORNING
```

`--ticks` and `--intervention-tick` are absolute simulation days. In this
example each source must precede day 11. `--warmup-ticks` is an additional
duration after the saved day. The sources retain their seeds; do not supply
`--seeds` with `--checkpoint`. Drafting creates only the prospective JSON
declaration and does not execute worlds. It refuses an existing output file.
Use `F2` in the same command for the equity information treatment; both drafts
measure goods price/volume and equity price/volume.

To continue a receipted pause, use the same study, configuration and input root
with `--resume-batch` and the exact data directory returned by the runner. The
original time/disk budget and source/code declarations remain binding. Public
reports describe the origin day and recorded continuation interval. Private
export/import uses the existing `research.study_bundle` commands and includes
the admitted origin files; the default bundle limit remains 2 GiB.

## Scientific contract

A saved world is an explicit initial condition. Admitting its database proves
its declared bytes, current schema, completed boundary, references, accounting
and persisted random states. It does not prove empirical realism or replay the
history that produced that initial condition.

The experiment and its independent recorded replay each start from a fresh copy
of that same admitted checkpoint. Continuation replay proves the newly executed
interval. Inherited history remains in both databases and in private evidence;
it cannot count as a post-treatment measurement or as new provider expenditure.

Flow totals and goods VWAP use only the declared post-intervention window.
The existing terminal equity-price contract can carry an older executed price
with its recorded execution day and age. That is an explicitly stale endpoint,
not a new execution or evidence of price discovery during the continuation.

Use a new study protocol for checkpoint origins. Preserve the exact serialized
form, interpretation and replay path of existing genesis study manifests. Bind
the source file hash, canonical state inventory, complete random-state digest,
actual simulation tick, source seed/run identity, admitted input prefix and
economic configuration. Store checkpoints in the study's immutable context.

Each independent initial-world seed supplies one source checkpoint. Both arms
of that pair use the same source. Repeated copies of one world are not separate
initial-world replications. The first implementation supports compatible
provider-free continuations; live policy comparisons remain a separate declared
execution capability, with no silent policy substitution.

All measurement and intervention ticks are absolute simulation ticks. Warmup
is a duration after the admitted origin. New interventions must occur after
that warmup; measurements cannot use pre-origin observations. Preserve inherited
schedules and append only the declared new interventions through world mechanics.
Retain the original seed and all three persisted random streams.

## Execution and evidence

1. Verify closed, standalone source files before claiming a batch. Refuse active
   or partial sources, changed bytes, incompatible schema/semantics/configuration,
   invalid references/random states, unreconciled accounts or external/participant influence.
2. Bound snapshot, arm-copy and replay-copy storage before allocation, and keep
   the existing supervised cumulative time/disk controls during execution.
3. Allocate every child exclusively. Preserve original source bytes, old study
   namespaces and earlier recovery receipts. A failed copy or branch remains
   diagnostic evidence; it must never become an eligible result.
4. Record the admitted origin separately from the child branch and its newly
   scheduled interventions. Recreate that branch from the admitted origin for
   recorded replay, without rebuilding genesis or trusting a copied final state.
5. Extend independent result verification, day/phase recovery and private bundle
   transport to verify origin identity as well as the existing source/replay
   receipts, input-prefix history and outcome measurements.
6. Expose reviewed source choices in the operator workflow with truthful
   capability refusals. Comparison shows the origin day, continuation interval,
   independent initial conditions, assignments, exclusions and measured windows.

## Acceptance

- Real G2 and F2 treatment/control continuations from at least two independent
  saved worlds, with all four goods/equity outcomes and exact continuation replay.
- Source files remain byte-identical, without new source-side SQLite sidecars.
- Changing an origin, inherited input, random state, schedule, accounting state
  or declared boundary refuses admission or later independent verification.
- Child initialization is exclusive; a second invocation cannot overwrite it.
- Day and phase pauses, repeat outages, cumulative budgets and portable evidence
  retain their current guarantees with checkpoint-derived origins.
- Pre-origin outcomes and inherited provider calls/spend are not counted as
  new study observations or execution costs.
- UI source review, deliberate launch, recovery, comparison and private export
  work for both domains, including historical/foreign-context refusals and mobile.
- Existing genesis studies, frozen manifests, historical replay and browser
  navigation continue to pass their established regression checks.

The first implementation seam is source admission plus independent checkpoint
branch/replay. Runner, analysis, portable evidence and UI integration follow as
part of this same deliverable; this document alone is not completion evidence.
