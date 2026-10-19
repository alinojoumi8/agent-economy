# Incremental checkpoint evaluation

## Capability
- An explicitly versioned format stores an immutable base and verified changed
  chunks. Legacy standalone SQLite checkpoints keep their existing semantics.
- Measure total save time, including writer exclusion, logical image capture,
  reused-object verification, SQLite integrity/schema/state/ledger evidence,
  durable object writes and atomic publication. Keep the five-second target.
- Report base creation, incremental saves, restore time, storage growth and
  peak RSS separately. Do not turn copied-data diagnostics into full-run proof.

## Regression and failure graders
- WAL commits, uncommitted tails, reset generations, page-size differences,
  database growth/shrinkage and same-tick replacement restore exact SQL data.
- Source rows and PRNG evidence remain unchanged. Capture excludes concurrent
  writers; async serving remains responsive.
- Corrupt/missing chunks, invalid roots, traversal/symlinks, invalid sizes and
  malformed manifests fail closed. Interrupted publication preserves the prior
  checkpoint. Recovery never edits stored source artifacts.
- Retention preserves pinned checkpoints and every referenced immutable object.
  Legacy restore/fork/replay remain compatible; new readers explicitly resolve
  versioned artifacts. No silent format migration.
- Required repository gates, current-commit CI and actual-base CodeRabbit pass.

## Boundaries
Use private copies of retained late-run data and bounded simulations/tests.
No new full 1,000-tick run, live provider calls, merges or observatory work.

- Large plans exercise real spawned verification, including worker corruption
  exceptions and aggregate parent-plus-descendant memory accounting. Spawned
  work must finish before publication and remain inside total checkpoint time.
