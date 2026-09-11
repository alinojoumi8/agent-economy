# Mixed population scenarios and initialization admission

Status: the bounded core mixed-scenario matrix and four-case initialization
profile matrix pass locally in disposable draft Semantics-21 worlds. The original
150-source-scope inventory is complete. Migration/version admission, full project
and platform gates, native acceptance and W5 completion remain open. Public
schema 25, maximum supported Semantics 20 and unregistered migration 26 remain.

## Change and existing version boundary

This follow-up adds `tests/test_population_profile_admission.py` to the existing
startup/phase-recovery CI job. It changes no production mechanics.

The life-course and civic rehearsal profiles each initialize, run two days with
a close/reopen after each NIGHT_CLOSE, replay the recorded decisions with the
same restarts, and validate both closed v8 exports against their databases.
Tests explicitly select draft 21, drift population, an empty movement schedule,
no checkpoints and no artificial speed delay. Other profile settings remain.
These are prescribed initialization checks, not unchanged production profiles
or evidence of native demographic emergence. Original identities and personally
owned accounts survive; actual internal relocation may change a selected wallet.

Historical behavioral and spec-closure fixtures already reject Semantics 15 or
later in `Households.__init__`. They rewrite historical genesis, so increasing
their semantics number does not make them valid modern profiles. The new tests
verify that this existing refusal occurs before World effects: all stored rows
remain unchanged, with no people or transactions created. Separately, the actual
pre-15 fixtures still pass their eight compatibility tests, including recorded
replay. No version guard was weakened and no synthetic prehistory was invented.

The initial profile probe expected all four profiles to upgrade. Its modern
profiles passed; its two old-fixture cases failed on the deliberate existing
guard. That invalid test expectation was corrected. The first test variant and
its two-failure/two-pass receipt are retained as probe evidence, not as a
production bug reproduction. Current startup, funding and construction behavior
is exercised through the existing modern World integration workflows.

## Mixed behavior verified

| Prescribed world | Evidence |
| --- | --- |
| Two 39-day lifecycle worlds | A person departs and returns with foreign cash; guardian death on day 37 or 38 invalidates a pending household departure; the child reaches adulthood naturally on day 38, retains 11 inherited company shares, receives no adult endowment and executes a recorded price action. |
| Seven-day care world | An actual day-1 birth, family departure on day 3, guardian death outside on day 4 and return on day 7 preserve custody and accounts. Local care totals 360 minutes; two food purchases and a real return-day unmet food unit remain visible. |
| Fifteen-day finance world | The founder leaves on day 2 and returns on day 12. Retained personal debt pays installments on days 7 and 14, leaving 3,500 cents outstanding; successor-operated company funding and credit continue. Pending personal credit expires at departure. |
| Nine-day construction world | Owner and clerk departure preserve a funded project and property rights. Recorded return-day work completes the project on day 7: 600 cents spent, 600 refunded and zero escrow. Return does not reinstate the clerk's office. |

Each workflow includes real World phase restarts, exact recorded replay,
reconciliation and a validated source v8 export. The care workflow also validates
the replay export. Independent read-only inspection of all five source/replay
pairs verifies matching selected census, identity, movement and economic facts,
SQLite integrity, unchanged hashes/mtimes and absence of SQLite sidecars. This
does not imply that all ten databases received independent export validation.

The 39-day fixtures set their starting near-majority cohort before first origin
registration and then use ordinary daily aging. They are not a native generation
or a replacement for the multi-decade acceptance study.

The 77 World/scenario/movement checks additionally cover complete group rollback
after late failures, retry, missing/withdrawn/declined or stale assent, changed
custody and membership, immutable prospective declarations, preserved return
identity and multicurrency accounts, retained outside financial recipients,
repeated keys and input-batch rollback. These close the named core matrix, not
every possible combination or full population admission.

## Local validation

| Selection | Passed | Pytest duration | Retained artifact bytes |
| --- | ---: | ---: | ---: |
| Four household, lifecycle, finance and construction suites | 31 | 543.62 seconds | 392,243,356 |
| Three World, declared-movement and group rollback suites | 77 | 77.78 seconds | 313,077,760 |
| Two historical fixture compatibility suites | 8 | 15.85 seconds | 397,932,189 |
| Complete eight-suite startup and phase-recovery CI selection | 73 | 586.70 seconds | 766,051,063 |

These selections contain 189 distinct tests. The four new profile cases are
included in the 73-case CI selection, so they are not added again. Documentation
and unsupported-draft admission checks run separately and have their own receipt.
The initial two modern-profile passes also overlap the final selection.

Every runner records terminal status, unchanged source hashes/mtimes, empty
staging and the 40 GiB free-space floor. The existing Starlette/httpx deprecation
warning remains. The final CI selection ends with 333.0 GB free.
No cleanup, paid provider calls or additional native campaign ran.

The existing CI job retains its 20-minute timeout and Ubuntu/Windows by Python
3.11/3.12 matrix. All eight suites passed locally on Windows/Python 3.11; this
does not claim execution of the other platforms or the full project gate.

## Next implementation and admission specification

1. Verify the draft migration through the normal migration runner in disposable
   copies: atomic failure, additive successful upgrade, checksum/history
   integrity, idempotent reopen, preserved stored semantics and untouched replay
   sources. Keep draft registration closed until its admission requirements pass.
2. Run the current full local gate and configured platform CI, resolving actual
   failures while preserving historical outputs. The source inventory and named
   core mixed/profile matrices are complete; do not restart those inventories
   as a substitute for migration and integration admission.
3. Preserve the native source, frozen runtimes, interrupted verifier and recovered
   copy with their original cumulative allowances. The original campaign is
   terminal at day 11,356; the recovered verifier is incomplete. At most
   2,435.437 seconds remain in its original replay allowance, which observed
   throughput does not establish as sufficient. A new horizon attempt requires
   its own prospective protocol and allowance; no reset or new attempt is made here.
4. Close the full W5 and earlier acceptance requirements, then continue W6
   education, W7 production/housing/spatial mechanics, W8 banking/credit and W9
   validation/scale. Goods and equity price discovery keep equal priority,
   research budgets and acceptance criteria.

Receipts: `tmp/estate-finality-population-mixed-*`. The mixed handoff retains the initial probe variant,
baseline/final source identities, unchanged original inventory, ten-database
read-only audit and native artifact preservation checks. See the
[population contract](2026-09-09-open-population-boundary.md),
[W5 acceptance audit](2026-09-09-w5-acceptance-audit.md) and
[full roadmap](2026-09-06-research-city-roadmap.md).
