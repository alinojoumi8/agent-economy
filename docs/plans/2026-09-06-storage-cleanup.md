# Agent Economy storage audit and cleanup status

Measured September 6, 2026, America/Toronto. The user approved both the temporary
test-database cleanup and the exact 282.47 GB checkpoint proposal below.
**Both deletion commands were rejected before execution by automatic approval
review with `blocked by policy`; no more specific reason was supplied. No files
were deleted during this audit, and no additional user approval is pending.**

A subsequent lossless NTFS compression fallback affected four approved older
checkpoint databases and was stopped because volume free space did not track the
reported file-allocation savings. All four checksums match their original
manifests. The protected primary run files and seven retained recovery snapshots
have unchanged size and timestamps. See the execution outcome below.

## Findings before the compression fallback

The accessible checkout contains **359.01 GB** of file payloads. Another
**20.34 GB** is in 44 Agent Economy `ae-*` test directories under
`C:\Users\matri\.codex\tmp`, for **at least 379.35 GB** across the audited scope.
Values below are decimal GB, not GiB. The major categories do not overlap.

| Category | Size | Recommendation |
| --- | ---: | --- |
| `data/checkpoints` | 319.41 GB | Retire selected older intermediate snapshots after approval and verification. |
| Checkout `tmp` | 21.90 GB | Keep current evidence and September 5–6 outputs for this proposal. |
| External `ae-*` test directories | 20.34 GB | The specific approved batch is a subset, listed below. |
| `data/runs` | 16.36 GB | Preserve all primary databases and their SQLite sidecars. |
| Remaining checkout files | 1.33 GB | Preserve source, Git, dependencies, studies and evidence. |

**318.60 GB of checkpoints were last modified before September 5.** The largest
local test root, `tmp/g-b039a1cf`, contains 19.71 GB from September 6. The older
`tmp/pytest-next-step-fe43aa4` test root contains 0.38 GB. Older tests are a much
smaller identified opportunity than the historical checkpoints; inaccessible
test directories may contain additional data.

The audit skips reparse points, does not follow pytest `current` aliases, and
deduplicates observed hardlink identities. It uses Windows
`GetCompressedFileSizeW` for file allocation. The reported payload totals here
equal logical file lengths; directory/filesystem overhead is excluded. Only a
verified free-space increase after deletion can establish actual space recovered.

Thirteen directories were inaccessible: twelve under `reports/out` and
`C:\Users\matri\AppData\Local\Temp\pytest-of-matri`. Their sizes are unknown and
are not included in these totals. No permissions were changed to inspect them.

## Already approved test cleanup

Exact root: `C:\Users\matri\.codex\tmp\ae-1ed5f10d`.

The audit identifies **6,418 regular `.db`, `.db-wal` and `.db-shm` files**, totaling
**10,536,866,687 bytes (10.54 GB)**. Links and all other file types are excluded.
The approved inventory is saved locally as
`tmp/storage-audit-20260906/approved-test-databases.csv`.

The full-suite failure log is retained at `tmp/households-full-python.log`, SHA-256
`020c6fe9ae770d0c56a14398e3a76a3237a76e211e8ada5369d5009b9cc13107`.
That full Python run exhausted C: and has no reliable successful completion or
final pass count. Its result remains inconclusive; the earlier focused results
must not be presented as a full-suite pass.

Automatic approval review rejected the batch deletion despite user approval.
No alternate tool, language or split batch was used to bypass that rejection.

## Approved additional scope: 282.47 GB

Start with only two large historical runs. Their checkpoints occupy 305.73 GB.
Retire **144 intermediate databases and their 144 matching manifests** that were
last modified before September 5. Preserve every other file in this proposal.

| Run | Existing snapshots | Keep these ticks | Delete databases | Candidate space |
| --- | ---: | --- | ---: | ---: |
| `7110a95923` | 135 | 10, 1330, 1340, 1350 | 131 | 246.65 GB |
| `53f5b4ce8c` | 16 | 30, 349, 377 | 13 | 35.82 GB |
| Total | 151 | Seven snapshots | 144 | **282.47 GB** |

The exact 288-file proposal is
`tmp/storage-audit-20260906/proposed-282gb-checkpoints.csv`. Its combined payload
is **282,466,846,055 bytes**. None of these artifacts have SQLite sidecars.

The retention set includes the earliest available snapshot for each run, the two
newest snapshots with matching manifests, and the newest snapshot even if its
manifest is missing. `7110a95923_t1350.db` lacks its manifest and is preserved as
an additional, unverified recovery artifact. Six retained snapshots passed fresh
SHA-256 comparisons against their manifests and SQLite `PRAGMA quick_check`.

All main run databases and their WAL/SHM files remain protected. The same applies
to saved studies, paid-provider evidence, checkpoints from other runs, September
5–6 artifacts, logs, the current implementation work, and Git history.

Deleting the listed intermediate snapshots removes the ability to restart or
fork directly from those exact saved database states. The primary run records
remain, but this proposal does **not** assert that every removed checkpoint can
be reconstructed exactly. The user separately approved this loss of intermediate
restart points, beyond the disposable test cleanup.

## Verification and execution conditions

1. The local candidate and retained manifests are the review boundary; do not
   replace them with a wildcard deletion of `data/checkpoints`.
2. Before deletion, recheck process ownership, exact resolved paths, absence of
   reparse points and sidecars, and candidate size/mtime/identity. Abort on drift.
3. Read-only queries across accessible primary run databases found no child run
   with either target as `parent_run_id` and no cross-run checkpoint-catalog
   references to these targets. Database/WAL size and modification time remained
   unchanged during those queries. The two saved configurations have no
   `checkpoint_keep_last` value. One saved run status is still `running`; that
   status is not proof of an active process. The process/listener inventory found
   no matching project execution, but must be refreshed before deletion.
4. Accessible code, documentation, configs and report/study JSON metadata contained
   no references to the 144 selected checkpoint filenames. Referenced checkpoints
   of other runs were preserved in the broader dry run. Inaccessible directories,
   arbitrary database text fields and external evidence were not exhaustively
   searched; resolve any additional user-specified pins before executing.
5. Fresh checksum and integrity verification succeeded for the six retained
   snapshots with manifests. The seventh is kept without making a validity claim.
6. Delete only approved manifest entries if tool policy permits. Preserve the
   manifest and log each result. Do not rewrite scientific run databases merely
   to erase their historical checkpoint-catalog rows; report pruned artifacts in
   a separate cleanup receipt.
7. Verify the remaining seven snapshot files, all primary DB/WAL files, retained
   evidence and failure-log hash. Measure C: free space before/after and report
   actual deletions and failures. Do not claim estimated bytes as recovered space.

The broader exploratory retention calculation found 284.66 GB of candidate
intermediate checkpoints across more runs. The recommended first scope above
recovers almost all of that with fewer affected runs. The additional 2.20 GB is
outside the first proposal and remains untouched.

## Prevent recurrence

The checkpoint writer copies a complete SQLite database. The checkpoint catalog
only calls retention when `checkpoint_keep_last` is a positive integer
(`world/loop.py`, `_checkpoint_record` and `_prune_checkpoints`). Retention support
already exists and is covered in `tests/test_checkpoint_retention.py`.

For future work:

- Set explicit retention for new operational profiles: keep two to four recent
  recovery points, plus separately pinned study checkpoints. Confirm the research
  requirements before applying this policy to existing scientific artifacts.
- Keep checkpoint creation in tests inside that test's temporary root. Review
  tests that inherit `runs/base.yaml`, whose checkpoint directory defaults to
  `data/checkpoints`; ensure they cannot populate the shared research directory.
- Give successful disposable test artifacts a bounded retention period while
  retaining result logs and required evidence. Keep failed-run evidence under a
  separate, size-limited policy. Do not automatically remove active pytest roots.
- Add a disk-space preflight and monitored storage budget to long local runs.
  Shard expensive validation and use isolated CI jobs where appropriate. Never
  launch another unbounded full local suite while C: has only about 4 GB free.
- Add an explicit pin registry and a previewable retention receipt so the UI can
  distinguish an intentionally pruned checkpoint from corruption or missing data.

These are proposed follow-up changes; no runtime settings or test behavior were
changed by this audit.

## Execution outcome and remaining blocker

The exact approved deletion passed a fresh read-only preflight: 288 unique files,
matching size/creation/modification times, no links or SQLite sidecars, no protected
September 5–6 artifacts, and no matching active simulation/test processes.
The mutation command was then rejected before its PowerShell process started.
Consequently neither its deletion receipt nor its before-deletion preservation
receipt was created. All 288 selected checkpoint artifacts remain present.

The non-deleting compression fallback had these results:

| File | Logical bytes | Allocation after compression | Checksum |
| --- | ---: | ---: | --- |
| `7110a95923_t1320.db` | 4,427,956,224 | 1,575,641,088 | Matches original manifest |
| `53f5b4ce8c_t343.db` | 4,424,351,744 | 1,720,385,536 | Matches original manifest |
| `7110a95923_t1310.db` | 4,377,927,680 | 1,560,600,576 | Matches original manifest |
| `7110a95923_t1300.db` | 4,327,653,376 | 1,545,379,840 | Matches original manifest |

Windows reports 11,155,881,984 fewer allocated bytes for those four files. A
second API, `FileStandardInfo`, independently confirmed their resulting allocation
sizes. However, C: free space went from about **4.39 GB before the initial trial
to about 2.40 GB after the stopped batch**. The first single-file trial temporarily
increased free space by 2.85 GB; the subsequent three files did not yield a net
volume recovery. **Do not report 11.16 GB, 180 GB, or 282.47 GB as recovered space.**

Compression was stopped using its own stop flag after the current file completed
and passed its checksum check. The worker exited; no compression remains running.
The other 140 approved database candidates and all manifests remain unchanged.
Protected main-run/recovery-file metadata and the full-suite failure-log hash are
preserved. No database was deleted or rewritten at the SQLite level.

The discrepancy between file allocation and volume free space remains unresolved.
Read-only VSS inspection required administrator permissions and was unavailable;
the cause is not established. A short process I/O sample after compression stopped
did not identify a continuing multi-gigabyte writer. Do not resume compression,
attempt decompression with insufficient space, or launch large tests until this
accounting issue and the deletion policy block are resolved. The approved cleanup
does not need another user confirmation.

Measurement reference: Microsoft's
[GetCompressedFileSizeW documentation](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getcompressedfilesizew).
This file-level measurement is kept separate from observed volume free space.

## Local evidence

All detailed inventories remain in the ignored directory
`tmp/storage-audit-20260906/`:

- `inventory.json` and `files.csv.gz`: 96,702 accessible files, errors and skipped
  paths, category totals and timestamps.
- `approved-test-databases.csv`: previously approved test-only batch.
- `retention-proposal.json`, `checkpoint-candidates.csv`,
  `checkpoint-retained.csv`: broader exploratory retention calculation.
- `proposed-282gb-checkpoints.csv`: exact approved additional scope; SHA-256
  `53d55b9c5d945897248b8b7fdb8073f0091a3e27079459152f31d2fe7a363ce4`.
- `retained-verification.json`: fresh checksums, SQLite integrity and metadata
  reference checks for the two selected runs.
- `audit.py`, `analyze.py`, `validate_retained.py`: reproducible read-only audit
  scripts; none contains a deletion operation.
- `compression-trial-before.json`, `compression-trial-result.json`,
  `compression-files.json`, `compression-receipt.json`: actual fallback results.
- `protected-before-compression.json`: protected primary run and recovery-file
  metadata for the fallback.
- `compress-approved-checkpoints.ps1`: lossless compression helper, now stopped
  with `STOP-COMPRESSION`. It has no deletion operation and must remain paused
  while volume accounting is unresolved.
