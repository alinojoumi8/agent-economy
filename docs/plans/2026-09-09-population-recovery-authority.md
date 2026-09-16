# Recovery operator admission and shared hiring capacity

Draft Semantics 21 now checks both the acting person and the candidate before
an existing offer acceptance reserves recovery hiring capacity. Firm recovery
also resolves operator residence before building contexts or replacing model
actions. This continues [candidate recovery](2026-09-09-population-workforce-recovery.md)
and the [population admission contract](2026-09-09-open-population-boundary.md).

Five reproduced failures are corrected: an outside candidate's existing
acceptance suppressed a local recovery candidate; a local operator accepting an
outside candidate's counteroffer did the same in two allocation paths; and two
paths silently accepted missing actor history. A shared reservation helper now
checks tick-scoped living residence for both parties. It resolves the whole
batch before publishing counts. The final coordinator uses the same helper.
Local counteroffers still consume their share of capacity. These are admission
checks; the deterministic action executor retains economic validation.

The firm recovery overlay reads the current stewardship, not just the original
founder. It preflights operator residence across the eligible firm batch before
building any context. The action replacement pass likewise resolves residence
before editing decisions. Outside actors are excluded; missing history raises.
Legacy Semantics 1–20 retain their hiring rules, with no new ledger or schema
mutation. Schema 25 and public Semantics 1–20 remain the supported boundary;
population migration 26 is still unregistered.

## Recorded successor workflow

The eight-day World cohort declares one existing worker unemployed, gives the
existing employee one genesis share, and records a wage offer and a linked
counteroffer. It does not claim native unemployment, spontaneous share transfer
or calibrated wages.

| Day | Verified behavior |
| --- | --- |
| 0 | Owner 32 retains 999 of firm 2's shares; existing employee 23 owns one share. Candidate 24 submits a 300,000-NSD-cent counteroffer linked to the firm's 250,000-cent offer. The owner has a separate 37-IVC holding. |
| 2 | The owner departs. The existing local shareholder becomes operator, with no transfer of the owner's remaining shares. |
| 3 | Both source and replay restart after NIGHT_CLOSE. The successor accepts the actual counteroffer through a recorded recovery decision. The firm reaches its declared headcount of two. |
| 2–4 | The outside owner receives no local decision or model call. |
| 5 | The owner returns with the same identity, checking account and foreign holding. The successor remains operator. |
| 8 | The hire remains active and has accrued 50,000 NSD cents in earned wage claims. Source and replay match exactly, and a source-validated v8 research export passes. |

The new employment's contractual wage is 300,000 cents per 30-day interval;
this eight-day case verifies accrual, not payday settlement. The preceding
34-day workforce case separately exercises actual payroll settlement. All 47
identities persist, ledgers reconcile daily, and recorded provider cost is $0.
Each closed eight-day database is 12,660,736 bytes. Read-only verification and
export preserve source bytes, modification time and closed-file state.

## Validation and inventory

[Thirteen cases](../../tests/test_population_recovery_authority.py) cover the
reproduced failures, valid local reservations, whole-batch failure, independent
operator guards and the complete successor workflow. Receipts use prefix
`tmp/estate-finality-recovery-authority-`. The five-case correction passed in
4.92 seconds. The complete eight-day workflow passed in 47.63 seconds under
`workflow-r3`, with 25,914,242 artifact bytes and 105,892,306,944 bytes free.

Earlier failures remain preserved. The first combined fixture incorrectly
assumed person 24 worked for firm 2; the recorded employee is person 23. The
next attempt correctly rejected an unlinked counteroffer. The corrected
fixture uses the recorded employment and supplies `parent_offer_id`.

The expanded `research-population-lifecycle` CI job now contains ten suites,
including all 13 cases and the preceding 28-case workforce suite. Its local
receipt uses `ci`; final documentation/version-boundary checks use
`docs-final`. Ubuntu/Windows and Python 3.11/3.12 are configured; local evidence
here uses Windows with Python 3.11.15. Existing Starlette/httpx deprecation
warnings remain. This job is a focused selection, not full CI acceptance.

The local `ci` selection passed all **166 tests in 630.47 seconds**, including
the final 13-case authority suite. It retained 1,022,310,142 artifact bytes and
finished with 104,594,051,072 bytes free, above the 40 GiB reserve. All 1,161
counted source files kept their hashes and modification times throughout the
run, and staging stayed empty.

The audit directory is `C:/Users/matri/.codex/tmp/ae-ca0d5f0f`. Seven reviewed
runtime scopes have current coordinates and hashes, covering three prior
inventory candidates and four additional entry points. A consolidated ledger
reconciles the original 150 candidates against explicit prior reviews and
current source hashes: 28 have matching reviewed source; 122 still require
scope review. The separate credit/VC caller review is retained without
automatically converting its narrative findings into completed candidate rows.
This ledger does not prove exhaustive call coverage or the complete scenario
matrix.

The adjacent guardian-query concern was checked and did not require a change.
The [existing unique index](../../engine/migrations/v021_households.py) permits
only one active primary guardian per child. A disposable service probe creates
child 48 through the birth service, then attempts a second current guardian.
SQLite rejects it with the original guardianship unchanged, balanced ledger
and zero model calls. The 3,969,024-byte diagnostic is a birth/constraint probe,
not a completed World simulation. It excludes the hypothesized second-current-
guardian ambiguity without closing the broader business-control inventory.

Next, review the undispositioned participation paths and mixed admission
scenarios, starting with business-control and actor-input callers. Complete
those checks before version admission. The native horizon,
full-prefix recorded verification, full CI, W5 and W6–W9 remain open, as do
earlier provider/workflow/usability acceptance requirements. Goods and equity
price research retain equal priority.
