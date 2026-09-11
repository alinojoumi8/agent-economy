# Full campaign verification — interrupted trial

The first full-source trial was interrupted without a terminal result: label
`estate-finality-native-closed-verification-r1`, artifacts
`C:/Users/matri/.codex/tmp/ae-7970721c`, specification SHA256
`f4988bbf7bef6f34ccfd0496f044735d498e52d8c5a41dc9d982f728edd9f582`.
Its source ends at day 11,356 after the native campaign reached its unchanged
four-hour limit. Batch 19–24 actually exited 0 and all final audits passed.
The source hash is
`984f6ab4d6ae6ba53422b0210560fa065643c8bf9932b4ce93fa83c9f7ca1dba`.
The recorded parent and child processes are absent. No full-source comparison
or export result is available. The preserved stage metadata at
`tmp/estate-finality-native-closed-verification-r1-meta.json` still says
`running`; it is stale. See the [interruption evidence](#verifier-interruption-observed-2026-09-09)
below and the [copy-only recovery result](2026-09-10-population-decision-guidance.md#native-replay-recovery-and-storage).
The separate integrity-checked copy contains 7,810 completed days, with day 7,811
awaiting FINALIZE. The original replay allowance has at most 2,435.437 seconds
remaining. No replay was advanced or budget reset during this recovery inspection.

Admission observed more than 104 GiB free disk and 20 GiB available RAM. The
limits below remain unchanged. The project's four tested integration patches
were applied only after native closure; neither frozen verification environment
was edited. The root combined tests passed and remain separate from this
full-source trial.

The preserved one-year source has now passed the complete bounded workflow:
recorded-response re-execution, exact comparison, research export and an
independent source-backed readback. The final multi-decade source is a
separate trial. A verified prefix does not satisfy the original 14,600-day
native horizon when that campaign stops at a resource limit.

This implements the execution boundary in the
[campaign replay/export specification](2026-09-09-campaign-replay-and-export.md)
and uses the [bounded export and dependency work](2026-09-09-bounded-research-exports.md).
The full [W5 acceptance contract](2026-09-09-w5-acceptance-audit.md) remains open.

## Root integration evidence

After native closure, the four reviewed patches were applied to the project:
historical kind reconstruction, bounded replay comparison, bounded export and
the export dependency pin. Git converted line endings during application;
every normalized file matched the tested source. The validated raw bytes were
then restored and all 15 file hashes verified, preserving every unrelated
source file and its modification time. Later documentation edits update status
only. Evidence: `tmp/estate-finality-root-integration-r1-meta.json`; pre/post
source snapshots and backups: `C:/Users/matri/.codex/tmp/ae-081edba1`.

The root Python 3.11.15 environment installed the same hash-locked pandas,
NumPy and pytz dependencies tested in isolation; compatibility checking passed.
The combined root gate passed **213 tests in 317.28 seconds**, covering bounded
replay/export, role history, household positions/finance API, source-preserving
and legacy replay, research exports, documentation and PRD regressions. One
existing Starlette/httpx deprecation warning remains. Source hashes/mtimes for
all 1,107 working files stayed unchanged throughout the gate; staging was empty.

The owned test supervisor exited 0, within 1,200 seconds, 4 GiB process-tree RSS,
4 GiB test artifacts and a 40 GiB free-space floor. Measured peak process-tree
RSS was 227,561,472 bytes and peak artifacts 633,142,268 bytes. Final fixtures
occupy 610,746,068 bytes in `C:/Users/matri/.codex/tmp/ae-f4168a5d`. Commands,
test output and source identity are recorded in
`tmp/estate-finality-root-integration-gate-r1-{meta,source,supervisor}.json`
and the matching logs.

All 209 maintained Python source files in the documented compilation scope
compiled successfully. The broad directory command also exited 0 but warned
about inaccessible archived paths under `reports/out`; that historical-output
walk is not counted as clean maintained-source coverage. Dataset verification
passed for the four pinned datasets; two optional sources remain unpinned.
Complete CI, other platforms and the full-source trial remain open gates.

## Preserved runtimes

| Purpose | Location | Evidence |
|---|---|---|
| Original native runtime, separate frozen copy | `C:/Users/matri/.codex/tmp/ae-1f0e7772` | All 1,099 files captured before native closure retain their original hashes/mtimes; original hash-locked Python 3.11.15 environment; `tmp/estate-finality-frozen-native-runtime-meta.json` |
| Bounded comparison/export environment | `C:/Users/matri/.codex/tmp/ae-13979342` | Tested comparator, exporter, independent validator and pinned pandas environment; freeze its source snapshot for each trial |
| Corrected historical-role audit reader | `C:/Users/matri/.codex/tmp/ae-daca0e1c` | Separate unchanged 1,100-file reader manifest pinned by the native supervisor |

The runtime copy includes the original uncommitted work, not just HEAD. Its
runtime file hashes equal those used for the previously verified native year.
The new comparison/export libraries execute in separate processes from the
original engine. This separation allows later project edits after the native
writer exits while preserving the exact runtime needed for recorded replay.
Never edit either frozen runtime or the analysis snapshot during verification.

## Executed one-year evidence

Original source: `C:/Users/matri/.codex/tmp/ae-c3a23cce/source.db`, 197,783,552 bytes,
SHA256 `7a2c80dc9a202337f55a18a022895fa53de559a67d9454211ffb8838a25ff53a`.
It retains an empty WAL and 32,768-byte SHM. Those original files were hashed
before and after and left unchanged. Only this known, closed fixture with its
verified empty WAL uses that compatibility procedure. The final native source
must be standalone without any sidecars.

The pipeline makes an owned private replay-source copy. For the older year
fixture, it also makes a standalone verification copy, since the original
sidecars must be preserved. For the final standalone campaign, comparison and
export can use the original through `open_read_only_connection(require_closed=True)`.
The re-execution reads only its private source copy. It disables checkpoints,
uses private output paths, forbids fresh scripted policy callbacks, and checks
the gateway's dispatch and source-consumption counters.

| Stage | Original-runtime trial seconds | Frozen-runtime trial seconds |
|---|---:|---:|
| Recorded re-execution of 365 daily ticks | 100.875 | 100.234 |
| Exact comparison | 92.859 | 93.016 |
| Export including its own independent readback | 93.375 | 91.984 |
| Separate independent readback process | 22.375 | 22.437 |

Both trials exited 0. The first completed in 317.906 seconds; the second in
315.953 seconds. Each stayed within the declared 600-second total, 2 GiB child
process-tree RSS and 2 GiB combined working-disk ceilings, preserving a 40 GiB
free-space floor. Final artifacts were 596,432,302 and 596,434,055 bytes.
The largest sampled combined working footprint was about 776 MB. These timings
are operational observations with concurrent native activity, not controlled
performance comparisons.

Both replays consumed all 8,580 source calls exactly once, with no missing,
unexpected or duplicate source IDs, no compatibility fallback and zero fresh
dispatches. All routes remained scripted and recorded provider spend was $0.
Ledger, household and daily census checks passed. Re-execution peaked at about
405 MB of child working set in the first trial; full-size replay memory is
still subject to the declared supervisor ceiling.

The exact comparator passed all 189 tables and reproduced the earlier legacy
proof, except for the intentionally distinct replay run ID. Its source/replay
hash is `f3cc3e3e6ea6433a91e45ce4e9d9234a736c8405f8dc714ecc5b3e2fc5b73cd9`.
The first comparison used 182,030,336 bytes of scratch and about 52.6 MB peak
child working set. The largest canonical record was 33,327 bytes.

Exports covered 193 tables and 148,024 rows. Both complete manifests and every
verified Parquet checksum matched, with bundle hash
`4579bc484693dcfe5b496cdf1a5171b6742c91a8b420f1ce3392e2f1cd2180d8`.
Exported files occupied about 2.26 MB: default exports redact model request and
response bodies. Canonical source hashes and exact replay still cover those
contents. Raw call-table size must not be treated as exported row size.

Receipts: `tmp/estate-finality-year-pipeline-r{1,2}-meta.json`,
`tmp/estate-finality-year-pipeline-cross-runtime-parity.json`, and the two bases
`C:/Users/matri/.codex/tmp/ae-fb241dd9` and
`C:/Users/matri/.codex/tmp/ae-ff8618b9`.

## Supervisor hardening

`tmp/estate-finality-verification-pipeline-v3.py` retains identical Python ASTs
for the v2 replay, consumption, comparison, export and readback child functions.
Its parent uses `tmp/estate_finality_process_guard.py` to stop only owned
processes when limits or monitoring fail, including observed descendants that
outlive their parent. Five real subprocess checks passed: success, nonzero exit,
timeout, injected monitoring exception and a surviving descendant. A separate
sentinel process survived every guarded case.

The sampler tolerates owned spill files disappearing during directory
enumeration. Other monitoring errors fail the trial and clean up the owned
job. This addresses a failure path where the previous monitor could exit and
leave a child running. Proof: `tmp/estate-finality-process-guard-validation.json`.
The complete year workflow was exercised with v2; v3's unchanged child work and
the replacement process guard were checked separately. Do not describe that
as a third complete one-year pipeline run.

The consumption receipt reads IDs and purposes without duplicating all stored
request/response bodies. It is named `recorded-consumption-identities-v1` and
does not impersonate `Gateway.replay_execution_stats()`. The subsequent exact
comparison supplies the complete logical-content proof. The original gateway
still retains consumed-call strings during re-execution; its memory is measured
and capped by the supervising process.

## First full-source trial

Admission requires the actual native supervisor exit, its successful final
audits, an unchanged source hash, no active writer/lock or sidecars, matching
original runtime files, at least 104 GiB free disk and more than 20 GiB available
RAM. The source boundary is the final recorded tick, including a clean resource
stop. No native budget, seed, demographic clock or horizon is changed.

| Verification stage | Cooperative allowance | Supervisor hard stop |
|---|---:|---:|
| Recorded re-execution | 14,400 s | 14,410 s |
| Exact comparison | 3,600 s | 3,610 s |
| Export and internal readback | 3,600 s | 3,610 s |
| Separate source-backed readback | 1,200 s | 1,210 s |

The combined verification ceiling is 23,000 seconds. These are prospective
first-trial budgets, informed by the 148,024-row year measurement; they are
separate from the unchanged four-hour native campaign budget. The unused v1
prototype's 900-second full-export guess was revised before any full-source
attempt. Time feasibility is not yet proven.

The child process-tree RSS ceiling is 16 GiB. Original disk allocations remain
16 GiB each for private source copies, replay plus comparison scratch, and
export plus spill, with 48 GiB combined working artifacts and the 40 GiB free
reserve. Comparison scratch is capped at 8 GiB. Export uses a declared 512 MiB
DuckDB buffer and at most 8 GiB spill. Defaults still limit canonical records
to 64 MiB and export records/batches to 8 MiB, with 512 export rows per batch.
The supervisor samples process trees and disk use; it also checks each exited
child's own peak working set. These are observed/process controls, not an OS
disk reservation against unrelated writers.

From the project root, after the admission evidence is verified:

```powershell
& C:/Users/matri/.codex/tmp/ae-1f0e7772/.venv/Scripts/python.exe -X utf8 -u tmp/estate-finality-verification-pipeline-v3.py campaign estate-finality-native-closed-verification-r1
```

The trial saves its specification and source manifests before copying or
executing. It retains every stage result, command, log, source stamp, resource
measurement and actual exit status. A failed/refused stage stops the pipeline;
no automatic restart, partial exactness claim, omitted fields or silent budget
increase is permitted. Root integration and full CI remain separate gates.

## Verifier interruption observed 2026-09-09

At 13:38:21 UTC, a Windows process query found no original parent/child PID
(49532/51208) and no Python command matching this trial or its work directory.
The saved process handle 77187 also returned `Unknown process id`. The original
metadata still says `running`; that is stale, not evidence of an active run.
The last replay log entry is tick **7,800 of 11,356**, at **11,964.563 seconds**
with **3,700,467,672 replay bytes**. This is the last logged checkpoint, not a
claim about an unlogged final database boundary. No terminal exit, exact
comparison, export or independent readback result is available. The cause of
interruption is unknown; no time-limit or disk-limit cause is inferred.

The read-only audit `tmp/estate-finality-population-participation-source-audit.json`
verified the original source SHA-256
`984f6ab4d6ae6ba53422b0210560fa065643c8bf9932b4ce93fa83c9f7ca1dba`,
size and mtime, with no WAL/SHM/journal sidecars. Both frozen source manifests
(1,099 runtime files and 1,104 analysis files) and the prospective specification
hash also match. Neither the source database nor the partial replay was opened
for mutation. The process observation is saved separately; the original
supervisor metadata and partial logs are preserved as recorded.

The trial is **interrupted with no terminal result**. It was not restarted and
its budget was not increased. Completion of the full-prefix workflow remains
open. Investigate the lost process and define any recovery attempt separately,
with fresh resource admission and retained predecessor evidence. Continued root
implementation and focused tests still use fresh directories and the 40 GiB
free-space floor. The observed approximately 132 GiB of free space permits that
work; it does not establish the remaining full-trial time or memory feasibility.
