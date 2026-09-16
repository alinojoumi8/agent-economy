# Bounded research exports — implementation and handoff

Status: implemented, tested in `C:/Users/matri/.codex/tmp/ae-13979342` and now
integrated into the working project after the native writer exited. The pinned
dependency fix is installed in the root environment; all 15 files across the
four history/replay/export/dependency patches initially matched their tested
source bytes. `tmp/estate-finality-root-integration-r1-meta.json` records the
handoff and preserved unrelated files. The combined root gate passed 213 tests
in 317.28 seconds, including export, replay, legacy compatibility and historical
household finance checks. Full-prefix verification is running in separate
frozen environments; complete CI remains open.
This extends the [campaign replay/export specification](2026-09-09-campaign-replay-and-export.md).

## Implementation

- `research/export_storage.py` defines `ExportLimits`,
  `ExportResourceLimitError`, bounded row/byte accounting, SQLite record limits,
  an owned DuckDB spill directory, and cooperative disk/deadline checks.
- `research/export_bundle.py` transforms and inserts bounded batches, holds one
  SQLite read snapshot, and restores the caller's transaction/record-limit state.
  It reads back all staged tables before publishing the manifest. Reusing an
  existing bundle counts both copies and uses the same budget; matching file
  hashes bind the existing files to the independently checked stage.
- `research/export_validation.py` reads actual Parquet schema and rows. With a
  source, it independently reconstructs types, source ordering, redactions and
  pseudonyms, compares every transformed value, and checks privacy counts and
  complete classified-table coverage. It does not call the writer's pseudonym
  function. Legacy SQLite-to-DuckDB value casts are preserved.
- `tests/test_bounded_export.py` adds 25 resource, privacy, source-preservation,
  coverage and corruption regressions. The existing content-address collision
  test now uses a real resealed conflicting manifest.

`export_bundle(..., limits=..., scratch_dir=..., stats=...)` and
`validate_bundle(..., database=..., contract_path=..., limits=...,
scratch_dir=..., stats=...)` retain their prior return types. Operational
statistics stay outside the content-addressed manifest. No engine semantics,
hash contract or research-bundle format version changed. The subsequent
dependency pin is separately validated below and remains isolated from the
original native campaign.

| Default allowance | Value |
|---|---:|
| Rows per Python insertion batch | 512 |
| Accounted bytes per batch / individual record | 8 MiB / 8 MiB |
| DuckDB buffer manager | 256 MiB |
| Owned temporary files | 8 GiB |
| Output plus temporary working files | 16 GiB |
| Cooperative elapsed time | 600 seconds |
| Library free-space floor | 0; campaign callers must supply 40 GiB |

One incoming/transformed row can coexist with the current bounded batch. The
accounted byte count is not Python object RSS. SQLite's raw record limit applies
before decoding, including during canonical source hashing. Source hashing still
uses the existing streaming `research/hashing.py` implementation.

DuckDB memory settings apply to its buffer manager, not every allocation.
COPY and hashing can run between cooperative checks, and Parquet decoding has
its own buffers. A campaign supervisor must enforce total RSS, elapsed time,
artifact bytes and the disk reserve. See [DuckDB's documented memory boundary](https://duckdb.org/docs/current/configuration/pragmas#memory-limit).
Large legacy Parquet row groups can require a larger explicitly declared buffer
allowance; refusal is not a successful export.

## Source and publication contract

For campaign work, first wait for the writer to exit and verify the recorded
database hash, mtime, ownership and absence of SQLite sidecars. Use
`engine.store.open_read_only_connection(path, require_closed=True)` and close
the returned connection in `finally`. Never open a live campaign as immutable
merely because a sidecar is temporarily absent.

```python
from engine.store import open_read_only_connection
from research.export_bundle import ExportLimits, export_bundle

source = open_read_only_connection(str(closed_source), require_closed=True)
try:
    stats = {}
    bundle = export_bundle(
        source, output_directory,
        limits=ExportLimits(min_free_bytes=40 * 1024**3),
        stats=stats,
    )
finally:
    source.close()
```

The caller still records source byte hashes/mtimes before and after. Canonical
source hashes in a bundle are a separate contract from original SQLite bytes.
An export already includes readback before publication. A later independent
consumer can call `validate_bundle(bundle, database=source, limits=limits)`;
custom contracts must also pass their original `contract_path`.

Without a source, validation checks manifest/file hashes, schema receipt
agreement, table/file inventory agreement, actual column names, supported types,
row counts and null redactions. V1 receipts do not declare every column type or
transformed content hash, so source-free verification cannot establish all
original types, contents, source ordering or original non-null privacy counts.
A self-consistent manifest does not authenticate its publisher.

Failures before directory publication clean only the owned staging/scratch
directories. Interruption after directory publication leaves an explicitly
incomplete directory without a final manifest. Existing bundles and original
simulation records are preserved.

## Executed checks

The 43-test integration gate passed in 218.73 seconds, with 153 deselected and
one existing FastAPI/Starlette deprecation warning. It covered the 23 initial
bounded tests, existing hash/export and branch coverage, and exports for
Semantics 15, 17, 18, 19 and 20. Its exact targets and options are recorded in
`tmp/estate-finality-bounded-export-integrated-meta.json`; basetemp was
`C:/Users/matri/.codex/tmp/ae-38d9d3e6`.

After the reuse-budget repair and two additional regressions, the affected
follow-up passed **26 tests, 6 deselected, in 16.13 seconds**:

```text
python -m pytest -v --tb=short --maxfail=3 tests/test_bounded_export.py tests/test_research_branch_coverage.py -k "bounded_export or content_address_collision" --basetemp C:/Users/matri/.codex/tmp/ae-626cedb6
```

Both test wrappers recorded unchanged source hashes/mtimes, empty staging and
pytest exit 0. The follow-up shell also attempted to look up an already-ended
probe process afterward, which made that outer shell return 1; the saved pytest
receipt and terminal result are successful. These overlapping suites must not
be added together as distinct test coverage. Full CI has not been run here.

## Parity and measured limits

The final exporter matched complete old manifests, including every Parquet
checksum, for a recorded golden fixture (95 exported tables / 2,343 rows), a
native three-day fixture (193 tables / 2,752 rows), and three synthetic sizes.
Export-table counts differ from the replay comparator's table inventory.
The synthetic table has a deterministic 4,096-character payload per row,
integer identity, pseudonymous owner, redacted private field and real value.

| Synthetic rows | Old peak MiB | Bounded peak MiB | Old / bounded seconds | Declared DuckDB buffer |
|---|---:|---:|---:|---:|
| 1,000 | 68.621 | 64.113 | 5.219 / 5.313 | 256 MiB |
| 8,000 | 203.520 | 167.059 | 41.125 / 41.984 | 256 MiB |
| 32,000 | 611.238 | 467.766 | 165.047 / 166.171 | 512 MiB |

These are each Windows child's own peak working set. The supervisor also
sampled its process tree. All probes retained the **1,536 MiB process-tree RSS,
180-second child, 3 GiB total artifact and 40 GiB free-space** limits. Successful
old measurements were reused only with source and retained export-file checks.
The final 32,000-row probe completed in 170.609 seconds including supervision.
This shows reduced retained Python data, not constant total RSS or full-campaign
performance. The large synthetic case is already close to the probe deadline.

Two earlier probes failed explicitly at COPY: 64 MiB could not export the
8,000-row fixture; the default 256 MiB could not export the 32,000-row fixture.
Both returned `ExportResourceLimitError`, retained their failure evidence and
left their output roots empty. The later 512 MiB setting was a declared single
probe within the same RSS ceiling; the library default remains 256 MiB.
All five closed source database byte hashes and mtimes survived the default
probe; the widest source also survived the final probe. Source files stayed
unchanged during each test/probe. No providers were called.

## Evidence and next execution

### Pinned environment validation

The isolated implementation now adds `pandas>=2.3.3,<3` to `requirements.txt`
and regenerates the universal `requirements.lock`. All 46 existing dependency
versions are preserved. The three added packages are pandas 2.3.3, pytz
2026.3.post1 and NumPy (2.4.6 for Python 3.11; 2.5.3 for Python 3.12 and later).
The existing tzdata 2026.3 requirement becomes unconditional because pandas
requires it across platforms. Both maintained Python versions were tested on
Windows in distinct environments installed with `--require-hashes`; each
`uv pip check` passed. The project's supported interpreter range remains
Python 3.11/3.12.

The same affected suite passed on both interpreters:

| Interpreter | Results | Test seconds | Fresh test directory |
|---|---|---:|---|
| Python 3.11.15 / NumPy 2.4.6 | 67 passed, 153 deselected | 197.56 | `C:/Users/matri/.codex/tmp/ae-960f1366` |
| Python 3.12.13 / NumPy 2.5.3 | 67 passed, 153 deselected | 145.96 | `C:/Users/matri/.codex/tmp/ae-d092058a` |

These are 67 distinct tests exercised twice. Both runs retain the existing
FastAPI/Starlette deprecation warning and preserve all 1,103 source-file
hashes/mtimes, with empty staging. Targets include all 25 bounded-export tests,
research hash/export and collision regressions, Semantics 15/17/18/19/20 export
cases and documentation. Exact commands are in the isolated
`tmp/estate-finality-export-{pandas,python312}-integrated-meta.json` receipts.
`uvx --python <matching-interpreter> pip-audit -r requirements.lock` exited 0
on both interpreters and reported no known vulnerabilities at the time of the
check. Full repository CI and other operating systems remain unverified here.

The R5 probe used the maintained Python 3.12 environment. Every complete
manifest and every verified Parquet file matched the preceding Python 3.11
results across all five fixtures, including 32,000 synthetic rows. All nine
fresh children exited 0; the largest old export was reused with file checks.
The probe completed in 81.703 seconds with 109,263,663 artifact bytes. The
largest bounded case took 16.078 seconds and peaked at 511.238 MiB. These
measurements include contemporaneous native-campaign activity and are not a
controlled comparison of interpreter speed. Source databases and implementation
files retained hashes and mtimes.

Evidence: `tmp/estate-finality-export-pandas-lock-verification.json`, the two
integration test receipts/logs, dependency-audit logs, and
`tmp/estate-finality-bounded-export-parity-scale-r5-meta.json` with artifacts in
`C:/Users/matri/.codex/tmp/ae-4c319ffd`. The separate checked handoff patch is
`tmp/estate-finality-export-dependencies.patch`; its baseline/new hashes and
application result are recorded in the matching integration receipt. It is not
applied to the original campaign's checkout or Python environment.

### Measured optional-import bottleneck

A 1,000-row profile found 8,004 attempts to import missing `pandas` inside
DuckDB's Python conversion path. Filesystem module searches dominated elapsed
time. A transaction wrapper and typed multirow SQL produced the same bytes but
only small timing changes (5.09, 4.97 and 4.72 seconds respectively); neither
was adopted as a production change.

A private, hash-locked dependency experiment installed pandas 2.3.3 and NumPy
2.4.6 under `C:/Users/matri/.codex/tmp/ae-3310f512/site-packages`. It used
`uv pip install --target ... --require-hashes` and preserved the root virtual
environment's installed-package records and requirements lock. This directory
occupied 82,888,784 bytes before probe imports. The original campaign never
loads this path. No maintained dependency change has been integrated.

The R4 probe used that path only in its subprocesses. All five fixture exports
retained their prior bundle hashes. Fresh old/new exports also matched for the
golden, three-day, 1,000-row and 8,000-row cases; the 32,000-row comparison reused
the previously checked old export. Source files and all five databases retained
hashes and mtimes. Every child exited 0 under the existing resource ceilings.

| Case | Bounded seconds before / with private dependency | Peak MiB before / with dependency |
|---|---:|---:|
| Recorded golden | 24.203 / 6.625 | 55.582 / 97.039 |
| Native three-day | 41.079 / 15.750 | 58.773 / 100.016 |
| 1,000 synthetic rows | 5.313 / 0.953 | 64.113 / 106.895 |
| 8,000 synthetic rows | 41.984 / 4.250 | 167.059 / 211.523 |
| 32,000 synthetic rows | 166.171 / 16.563 | 467.766 / 510.055 |

This substantially reduces the measured time while adding about 42–44 MiB to
the synthetic-case working set. It is still fixture evidence, not a full-size
campaign export guarantee. The probe completed in 84.719 seconds and retained
109,263,595 artifact bytes. The 32,000-row case still declares a 512 MiB DuckDB
buffer; other cases declare 256 MiB. The library default remains unchanged.

Evidence: `tmp/estate-finality-export-{profile,imports,pandas-environment,pandas-probe}-meta.json`,
`tmp/estate-finality-bounded-export-parity-scale-r4-meta.json`, and
`C:/Users/matri/.codex/tmp/ae-a2d0d177`. Before adopting a maintained dependency,
validate the complete pinned environment and affected existing tests in the
isolated implementation worktree. Do not modify the running campaign's runtime.

Root `tmp/estate-finality-bounded-export-parity-scale-r{1,2,3}-meta.json`
records the three probe outcomes. The R1 archive contains the exact earlier
implementation, reconstructed with SHA256 checks after resolving mixed Windows
line endings. The final archive is
`C:/Users/matri/.codex/tmp/ae-c90234fa/implementation`; its index is root
`tmp/estate-finality-bounded-export-validation-archive.json`.

The five-file code patch is root `tmp/estate-finality-bounded-export.patch`,
SHA256 `e8fdee8d14023d2810495cbfff26d3c6a30ea92e8e50f9130e7962c37501b918`.
`git apply --check` passed; root integration is pending. Keep its code patch
separate from this new documentation until the pinned native runtime can change.

1. Preserve the running native campaign and frozen historical audit worktree.
   Continue the original seed, daily clock, horizon and resource ceilings.
2. Before full-campaign export, measure actual source tables and row sizes on a
   closed source. Declare a buffer allowance within the existing supervised
   memory budget; include spill, output, private copies and reserve accounting.
3. Validate and pin the measured dependency fix in an isolated environment.
   Preserve byte parity and resource refusal gates. Do not extrapolate the
   32,000-row timing into a promise about hundreds of thousands of calls or a
   multi-gigabyte campaign.
4. Perform the full recorded replay and export/readback under their declared
   limits. A refusal retains an incomplete receipt and requires a separately
   specified next step; never omit fields or silently raise the original budget.
5. Integrate the tested patches only after the campaign's original runtime no
   longer needs the current checkout. Merge this evidence into the latest root
   plan without replacing newer historical-role findings, then run required CI.
