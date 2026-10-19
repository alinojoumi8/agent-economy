# Checkpoint performance evaluation

## Capability
- Reproduce late checkpoint and same-tick overwrite timings on private copies of retained 1,000-tick data. Preserve source hashes.
- Reduce measured backup/manifest work without weakening the unchanged 5-second total checkpoint p95 target. Report any residual failure.
- A checkpoint remains a complete, standalone SQLite snapshot with its existing canonical manifest, PRNG/state binding, integrity and ledger evidence.

## Regression
- Restore full tables and random state from WAL-backed sources; no source mutation.
- Repeated same-tick checkpoints refresh contents, retain one catalog row, and preserve retention behavior.
- Failed writes preserve prior valid artifacts; no premature catalog update.
- Async checkpoint I/O stays off the serving event loop.
- Historical replay and manifest verification remain exact.

## Validation
Focused correctness/failure tests, copied full-size checkpoint benchmark, restore/integrity/hash checks, required repository local gates and CI, full-diff CodeRabbit against actual PR base. No full simulation rerun or increased limits.

## Review compatibility regression
Reference indexing accepts historical non-finite and surrogate values; strict
comparison still rejects them. Cache-hit and scratch-read paths agree; finite
reference fragments keep exact historical bytes and bounded expansion.
