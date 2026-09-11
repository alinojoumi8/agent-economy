# Population migration and historical replay admission

Status: the bounded migration matrix passes through the real migration runner,
and a reproduced older-run replay comparison error is fixed. The original
source inventory and named mixed/profile matrices remain complete. Full current
local/platform gates, native acceptance and W5 completion remain open. Schema 26
and Semantics 21 are admitted only within disposable tests; public schema 25,
maximum Semantics 20 and unregistered migration 26 remain unchanged.

## Reproduced problem and correction

A real one-day Semantics-20 source in schema 25 replayed into schema 26 with
matching economic effects. The verifier nevertheless marked the seven new empty
population tables and the additive migration receipt as differences. Existing
versioned compatibility handling stopped at Semantics 20/schema 25.

`world/replay_verify.py` now declares the seven population tables as the
Semantics-21/schema-26 extension. It uses the existing comparison rule: before
Semantics 21, only these explicitly named empty tables and the new migration
receipt are omitted. Populated population tables, unknown tables and older
migration receipts remain visible. At Semantics 21, population tables and the
schema-26 receipt are required in the comparison. This changes no settlement,
person identity, ledger, migration SQL, hash contract or public version limit.

The original failed source/replay pair is retained. Rechecking those same closed
files with the corrected verifier yields exact comparison without changing
either file. The initial receipt is one failed/eight passed, and remains evidence
of the defect. It is not replaced by a new run or counted as a passing gate.

## Migration matrix

All 14 focused cases pass:

- Three late failures (SQL, structural verification and history-receipt insertion)
  roll back every new schema object and migration row, preserving all original
  stored rows and the schema-25 marker. Constructor handles close on failure.
- A successful additive upgrade preserves the existing schema objects, identities,
  accounts and all other historical rows. Only the schema marker and new receipt
  change; all new population tables start empty. Two reopens are idempotent, and
  the stored Semantics-20 configuration remains unchanged.
- Changed migration checksums, unknown history and a missing population guard
  reject reopening without repair.
- The real Semantics-20 replay remains exact after schema-26 installation, does
  not create residence or census history, and validates both source and replay
  v7 exports against their databases.
- A fresh Semantics-21 world gets schema 26 through ordinary Store initialization,
  registers each person once, restarts after NIGHT_CLOSE, replays exactly and
  validates both v8 exports. Repeated initialization does not add rows.
- Five negative comparisons retain unexpected population data, unknown empty
  tables, changed earlier receipts, missing required draft tables and altered
  draft receipts as differences. Hash validation also rejects populated draft
  history under the old v7 contract.

The test fixture patches registration and version ceilings locally. It does not
install the draft into a user's database. Closed original source files retain
their SHA-256 hashes and modification times, with no SQLite sidecars. The final
read-only audit records the original failed pair and both current World pairs,
their matching canonical hashes, schema/semantics markers and SQLite integrity.
These one-day prescribed worlds verify upgrade/replay mechanics, not demographic
emergence or the long native study.

## Validation and CI

| Selection | Passed | Pytest duration | Retained artifact bytes |
| --- | ---: | ---: | ---: |
| Focused migration and comparison boundaries | 14 | 132.96 seconds | 117,699,321 |
| Seven schema, residence, compatibility and legacy replay suites | 129 | 25.26 seconds | 237,961,424 |
| Complete seven-suite population export CI selection | 114 | 510.97 seconds | 438,388,757 |

The 14 focused cases are included in the full 114-case export selection. The
129-case compatibility selection overlaps its eight golden/source-replay cases,
so these two selections contain 235 distinct tests. Documentation and public
admission checks have a separate final receipt; the public-admission case also
appears in the compatibility selection. The initial probe is not added again.

The population-export CI job now includes the migration suite, retaining its
20-minute timeout and Ubuntu/Windows by Python 3.11/3.12 matrix. The complete
selection passed locally on Windows/Python 3.11. Full project shards and other
platforms are not claimed as executed. The existing Starlette/httpx deprecation
warning remains. All receipts verify unchanged source hashes/mtimes and empty
staging. The export selection ends with 332.1 GB free,
above the 40 GiB reserve. No cleanup, paid providers or native campaign ran.

Six additional project checks passed on unchanged sources: Python compilation,
pinned research datasets, `python -m pip check`, all 264 dashboard Node tests,
TypeScript checking and third-party notices. Their exact commands and full output
are retained under `tmp/estate-finality-population-migration-prerequisites-*`. These use the installed locked
environment; no dependency reinstall, vulnerability audit, dashboard build or
browser/hosted integration was performed in this follow-up.

## Next execution specification

1. Run the remaining current project gates. Follow the documented deterministic
   eight-way pytest partition with fresh short temporary directories and the
   40 GiB floor; do not replace the CI shards with an unbounded serial local run.
   Compilation, datasets, installed Python dependencies, dashboard tests/types
   and notices already passed here. Finish dependency-install/audit and dashboard
   production-build checks, rerunning completed checks only if later changes
   justify it. Resolve actual failures and retain terminal receipts. A local
   Windows pass does not establish the configured
   operating-system/Python matrix or hosted/browser integration.
2. Keep public population registration closed until the full admission/release
   requirements pass. The original 150-source inventory, named core mixed/profile
   matrices and bounded migration matrix are now complete; repeat them only when
   later changes or failures justify it.
3. Preserve the original native campaign and partial verification. The source
   stopped at day 11,356 under its original time limit; the recovered verifier
   has 7,810 completed days. At most 2,435.437 seconds remain in the original
   replay allowance, and observed throughput does not establish completion in
   that time. No budget reset or further native attempt is authorized by these
   checks. A later horizon attempt requires its own prospective protocol and
   allowance while retaining all original evidence.
4. Close W5 and earlier acceptance against their full contracts, then continue
   W6 education, W7 production/housing/spatial mechanics, W8 banking/credit and
   W9 validation/scale. Goods and equity price discovery retain equal priority,
   budgets and acceptance criteria.

Receipts: `tmp/estate-finality-population-migration-*`; the migration handoff retains the baseline, original
probe fixture, final source, changed-file patch and closed-world audit. See the
[mixed/profile matrix](2026-09-10-population-mixed-admission.md),
[population contract](2026-09-09-open-population-boundary.md),
[W5 acceptance audit](2026-09-09-w5-acceptance-audit.md) and
[full roadmap](2026-09-06-research-city-roadmap.md).
