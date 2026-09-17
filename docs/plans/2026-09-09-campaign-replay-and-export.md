# Bounded campaign replay and export — implementation specification

Status: the comparator, bounded exporter and dependency fix are integrated
after isolated validation and the native writer's actual terminal exit.
The [complete one-year verification pipeline](2026-09-09-full-campaign-verification.md)
passed with both the original and separately preserved runtime. Verification
of the closed day-11,356 source was interrupted without a terminal result;
its saved `running` metadata is stale. See the
[recorded interruption](2026-09-09-full-campaign-verification.md#verifier-interruption-observed-2026-09-09).
The [copy-only recovery](2026-09-10-population-decision-guidance.md#native-replay-recovery-and-storage)
passed SQLite integrity and recovered 7,810 completed days plus the pending
FINALIZE of day 7,811. This did not advance replay or reset its original budgets.
The combined root gate at that stage passed 213
tests; complete CI remains open. The original native campaign stopped at its
four-hour limit. This supports the
[native life-course protocol](2026-09-08-life-course-validation.md) and
[W5 acceptance audit](2026-09-09-w5-acceptance-audit.md). It does not change the
campaign's seed, daily clock, 14,600-day horizon, runtime fingerprint or limits.

## Current evidence

At the preceding day-7,667 pause, the same native source's closed artifacts
occupied 3,654,987,141 bytes before the final audit attachments. `llm_calls`
alone occupied 3,153,281,024 SQLite bytes. The host had about 139 GiB free after
closure; these are observations, not a promise about future availability.
The original 104 GiB admission threshold reserves four 16 GiB allocations
(source, replay, private source copy and export), plus a 40 GiB free-space floor.

The existing recorded 365-day replay passed exactly across 189 compared tables
(`tmp/estate-finality-life-course-recorded-year-v2-proof.json`). That evidence
does not establish the memory requirements of a full campaign.

The original pinned implementation has three relevant paths:

| Location | Inspected behavior | Required work |
|---|---|---|
| `world/replay_verify.py::_logical_llm_call_references` and `_logical_event_references` | Materialize canonical call and event maps, including recorded request/response contents and backward provenance. | Bound retained reference data without changing logical identity or reference validation. |
| `world/replay_verify.py::_table_digest` and `verify_replay_connections` | Fetch all rows, build all serialized records, sort logical-row tables in memory, and retain both source and replay reference maps together. | Stream hashing, bound sorting and reference storage, and avoid keeping both large sides resident unnecessarily. |
| `research/export_bundle.py::_export_table` | Collect all transformed rows in a list, then insert them into an in-memory DuckDB table. | Bound transformation/insertion batches and DuckDB memory/spill space. |

`research/hashing.py::table_digest` already streams its SQLite cursor into the
digest. Do not replace it on the mistaken assumption that it fetches all rows.
No full-size out-of-memory failure has been observed. The findings above are
code-level scaling concerns requiring measurement and implementation.

## Execution boundary and resources

1. Finish or retain a declared terminal/pause receipt for the native campaign.
   The original four-hour native allowance remains unchanged. A resource stop
   is not completion of the declared horizon.
2. Verify the source byte hash, metadata, no active writer/lock and absence of
   SQLite sidecars. Audits use `open_read_only_connection(require_closed=True)`.
   `run.open_run` and the current replay comparator use ordinary read-only
   connections, which can create sidecars. Run replay against a private copy
   and preserve the original source bytes and metadata.
3. Use a fresh short `C:/Users/matri/.codex/tmp/ae-<8hex>` verification base.
   Record the fixed source, runtime, interpreter, verifier/export implementation,
   commands and resource limits before execution. For any isolated verification
   checkout, capture the current working files, not just HEAD: the campaign uses
   unpublished working-tree changes. Do not change its pinned runtime in place.
4. Measure available RAM and disk before admission. Declare process-memory,
   temporary-disk and elapsed-time ceilings for each verification stage. Initial
   target: at most 16 GiB verifier memory, with smaller fixture probes first.
   Replay database plus its comparison scratch data must fit the existing replay
   allocation; export working files must fit its export allocation. Spill and
   temporary sort files count toward limits. Preserve the 40 GiB free-space floor.
   If an allocation is insufficient, retain an incomplete receipt and design the
   next bounded step explicitly; do not silently exceed the original budgets.
5. Record peak process memory, peak temporary bytes, duration, free space and
   terminal exit status. Wait for the actual child exit before editing pinned
   sources or recording completion. Provider callbacks must be forbidden during
   replay, with recorded inputs restored and zero new provider spend verified.

Older pilot fixtures currently retain an empty WAL and a 32,768-byte SHM. An
immutable read correctly rejected those originals. A separate 4.39 MB household
inspection copy was made only after verifying its empty WAL and recorded database
hash; original database/sidecar hashes and mtimes remained unchanged. This is a
specific preserved-fixture procedure, not permission to omit a live WAL.

## Exact comparison contract

Preserve all current excluded tables, ignored operational fields/purposes,
semantics-specific empty extensions, deterministic column handling and table
ordering. Do not drop recorded request/response contents, call latency, reference
owners or causal provenance to make the comparison cheaper.

- Replace full-table `fetchall()` and record lists with cursor iteration and
  incremental hashing. Hash the same JSON bytes and trailing newline for every
  row, with the same Unicode, numeric, null and non-finite-value rules.
- For logical-row tables, use bounded sorted chunks and an external merge, or
  disk-backed BLOB sorting with demonstrated byte-order parity. Keep duplicate
  rows, row counts and exact lexicographic byte order. SQL text collation is not
  a substitute for the current byte sort.
- Bound logical-reference storage and caches. A disk-backed implementation must
  preserve the existing nested logical values, backward-event resolution and
  invalid-reference results. Account for unusually large individual records and
  nested expansions; a bounded table batch alone is not a memory bound.
- Process source/replay sides sequentially where possible. Preserve the existing
  proof keys, table hashes, total hashes, differing-table list and tick mismatch
  behavior. Exact replay here means equality under the declared comparator, not
  byte-identical SQLite files. Original source-byte preservation is a separate check.

Acceptance starts with unchanged proofs on small genuine recorded fixtures.
Retain the negative cases in `tests/test_prd_completion.py`: reordered surrogate
IDs, nested references, malformed/dangling IDs, wrong actor/tick/role/purpose,
and legal/communication ownership. Both sides sharing the same invalid pointer
must still fail. Include backward-event references and the existing Semantics
1/2 and recorded golden replay gates. Demonstrate bounded peak memory as row
counts grow; a passing small equality test alone is insufficient.

## Export and independent validation

Transform and insert bounded batches, with explicit row/byte limits, into a
DuckDB execution environment with a declared memory limit and spill directory.
Preserve schema, source row order where contractual, redaction/pseudonym counts,
classified table coverage, canonical source hashes and deterministic output.
Prefer byte parity with the current small fixtures. If a necessary encoding
change alters Parquet bytes, version and explain it; do not claim identity with
the old content-addressed manifest.

`validate_bundle` currently verifies manifests and file hashes/sizes/presence.
Add an independent read of each exported Parquet table, verifying schema, row
counts and the expected transformed contents against the recorded source.
Exercise empty tables, nulls, Unicode, large payloads, sensitive-field handling,
corrupted/omitted files and interrupted staging. Publish the manifest only after
all required outputs are complete. A partial export remains explicitly partial.

## Completion evidence

Save fixture parity and rejection results, measured resource receipts, the full
recorded replay proof, independent export validation and original source/sidecar
preservation. Keep these separate from native demographic observations, policy
quality and empirical calibration. School capacity, external departure, deeper
production/finance and larger-world validation remain in the original W5–W9 order.

## Implementation and fixture validation in isolation

The comparator is implemented in
`C:/Users/matri/.codex/tmp/ae-13979342`, captured from all 1,097 current
tracked/nonignored root files before development. It includes unpublished
working changes, not merely HEAD. The root engine and its campaign fingerprint
remain unchanged.

The change adds `world/replay_storage.py`, changes the comparator in
`world/replay_verify.py`, and adds `tests/test_bounded_replay.py`. It streams
ordinary table hashes, sorts logical records using a SQLite BLOB primary key
with a duplicate-preserving ordinal, resolves calls lazily through a bounded
serialized cache, and stores backward event references in owned scratch space.
Source and replay are processed sequentially. Existing proof keys, canonical
bytes, ignored fields, invalid-reference outcomes and total hashes are preserved.

The optional `limits`, `scratch_dir` and `stats` arguments leave resource
measurements outside the proof dictionary. Default limits are 64 MiB per raw
SQLite row/canonical record/reference expansion, 8 MiB serialized cache with
1,024 entries, 2 MiB SQLite scratch cache, 8 GiB scratch and 600 seconds. A
repeated reference is charged before decoding another object tree. The library's
free-space floor defaults to zero; campaign callers must explicitly supply the
40 GiB floor and their stage's budget. `ReplayResourceLimitError` produces no
partial exactness verdict. Scratch cleanup is limited to the newly created,
ownership-checked directory, and caller SQLite record limits are restored.

These are bounded data structures and explicit refusal paths, not a universal
hard process-memory guarantee. Source row shape, Python object overhead and
nested JSON still matter; a supervising process remains required for the
declared full-size RSS/time limits. The subsequent
[bounded export implementation](2026-09-09-bounded-research-exports.md) adds
separate batching, source readback and resource-refusal evidence in isolation.

Executed local checks:

- Initial resource tests: 13 passed; the added pre-decode expansion regression
  then passed in the combined gate.
- Combined gate: **63 passed, 70 deselected, one existing FastAPI/Starlette
  deprecation warning, 95.65 seconds** (96.58 s including the wrapper).
  It covers 14 new bounded tests, replay source lifecycle including Semantics
  1/2, saved-world origins, provenance rejection and the recorded golden replay.
- Exact command, after the wrapper's fresh-directory/reserve admission:
  `python -m pytest -v --tb=short --maxfail=3 tests/test_bounded_replay.py tests/test_replay_source_lifecycle.py tests/test_checkpoint_origins.py tests/test_prd_completion.py tests/test_recorded_replay_golden.py -k "bounded_replay or replay or checkpoint_origins" --basetemp C:/Users/matri/.codex/tmp/ae-789886be`.
  The 1,099 source files retained their hashes/mtimes, staging stayed empty and
  test artifacts occupied 634,564,148 bytes.
- Two sequential old/new probe runs compared complete output dictionaries.
  Both matched in all eight cases: a genuine recorded golden pair (130 tables,
  exact), three deliberately differing/corrupted final fixtures (same negative
  proofs), a native three-day state inventory (189 tables, valid references),
  and three synthetic scaling inventories. A matching negative proof is not an
  exact replay. The three-day inventory is not a 40-year replay.

The second resource probe also captured each Windows child's own peak working
set, because periodic parent polling in the first run missed some brief peaks.
The corrected measurements are:

| Added synthetic rows in each growing table | Original child peak MiB | Bounded child peak MiB | Bounded scratch MiB | Original / bounded proof seconds |
|---|---:|---:|---:|---:|
| 1,000 | 32.074 | 26.086 | 4.953 | 0.234 / 1.031 |
| 8,000 | 101.492 | 26.285 | 39.527 | 1.219 / 8.641 |
| 32,000 | 341.336 | 26.363 | 158.047 | 5.453 / 33.672 |

These probes use a 512 KiB reference cache, 128 entries, 8 MiB records,
512 MiB scratch, a 1,536 MiB supervised process-tree RSS ceiling, 180 seconds per
child, a 3 GiB total artifact ceiling and the 40 GiB free-space reserve. All 16
children exited 0. The probe completed in 65.656 seconds, with 207,430,669 bytes
of artifacts before source-code attachments. All fixture database/sidecar bytes
and mtimes were preserved; private copies were used for the originals that
retained an empty WAL and SHM.

The bounded implementation traded speed for memory in this workload: the largest
probe was about six times slower. It does not yet prove that the full native
source can be compared within its original wall-time/scratch allocation.
Performance work or explicit resource refusal may be necessary; do not silently
increase budgets or drop proof fields.

Receipts and reproducible handoff:

- Isolated `tmp/estate-finality-bounded-replay-integrated-r2-{meta,source}.json`
  and its log record the 63-test gate.
- Root `tmp/estate-finality-bounded-replay-parity-scale-r2-meta.json` and
  `C:/Users/matri/.codex/tmp/ae-f0561225` retain specs, exact outputs, private
  fixtures and process measurements.
- `tmp/estate-finality-bounded-replay-validation-archive.json` identifies the
  archived tested implementation, baseline verifier, test source hashes and
  probe script. A later one-line trailing-whitespace correction was checked to
  have an identical Python AST; compilation and diff hygiene passed.
- `tmp/estate-finality-bounded-replay.patch` contains only the three comparator
  files relative to the preserved root baseline. `git apply --check` passed;
  it was **not applied**. `tmp/estate-finality-bounded-replay-integration.json`
  records the baseline/new file hashes and patch hash.

The native source has separately passed corrected historical-role, cohort and
family audits at [day 9,636](2026-09-08-life-course-validation.md#current-closed-boundary--day-9636).
Bounded continuation uses a frozen audit-reader worktree and the original
simulation runtime. The original native budget has 3,583.36 seconds left;
reaching that budget must produce an audited resource stop, not a completion
claim. Root integration, full campaign recorded replay/export, independent
validation of the full campaign export and complete CI remain open.
