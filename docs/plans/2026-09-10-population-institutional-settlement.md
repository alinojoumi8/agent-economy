# Atomic compute, fiscal and information settlement

Status: implemented and locally validated in draft Semantics 21. The original
population inventory now has **106 reviewed scopes and 44 remaining**. Public
schema 25, maximum supported Semantics 20 and the unregistered migration 26
remain unchanged. Full W5 admission, CI, native acceptance and W6–W9 remain open.

## Corrected behavior

Draft primary nightly calls for cognition, government and information now own
aggregate database savepoints. Direct fiscal elections also own a savepoint.
The existing World NIGHT_CLOSE transaction still encloses its complete phase.
This closes partial-update gaps for direct service callers, while preserving
the successful settlement order and previous-version behavior.

Five focused failures were reproduced against the original implementations:

- A later official's invalid residence evidence left an earlier compute plan
  activated, with its model tier and event already changed.
- A failure after the second institutional renewal left public compute charges
  and subscription changes applied.
- A failed election receipt left that night's earlier benefit payments and
  fiscal-policy metrics applied.
- A failed direct election left the fiscal-policy metrics changed.
- Malformed stored data for a later news claim left earlier item exposures and
  belief updates applied.

Each failed draft batch now restores every table's rows to the pre-call state.
Retry activates plans, bills public sponsorship, pays benefits, changes policy
or delivers news once. The tests restore deliberately corrupted fixture data;
the production services do not repair stored source evidence automatically.

The original driver bodies are extracted into private helpers. AST comparison
confirms their successful statements are unchanged. Versions 1–20 keep the old
call behavior without these additional transaction boundaries. The fiscal
nightly boundary includes both benefits and the election, so an inner election
rollback cannot leave earlier benefits applied.

## Preserved service and ownership rules

An additional test activates a paid Flash plan, performs a real departure and
return, and verifies that the cancelled subscription stays cancelled. Departure
already resets the persisted model tier to local. Returning does not restore
paid access or refund the earlier charge: a new ordinary purchase creates a
different subscription and activates on the following day. The test initially
attempted movement before reconciling the person's age; its setup was corrected
to advance the existing age clock, without relaxing movement admission.

The source review also confirms:

- `seed_world` is called only during fresh initialization; existing worlds return
  before it. Later arrivals have a separate origin-bound seeding path. Return
  does not reseed skills or award another launch grant.
- Employer sponsorship uses active employees, renewal/skill checks, available
  premium capacity and the current local company operator. Historical ownership
  is not an operating permission.
- Premium capacity retains the documented fraction of resident non-institutional
  citizens. This slice introduces no new age- or skill-based denominator policy.
- Institutional renewal validates the resident cohort before public charges.
  Existing active/pending plans suppress duplicate renewal.
- Benefits and fiscal ballots retain their existing resident and age rules;
  an empty electorate does not change fiscal policy.
- News delivery validates local recipients, while preserving outside people's
  old exposures and beliefs. Ordinary delivery can resume after return.

Eight original candidates are dispositioned: five cognition scopes, the fiscal
recipient and election scopes, and information nightly delivery. Supporting
review covers initialization, grants, plan admission, cancellation, payment,
the extracted helpers and the departure caller. A fast graph refresh completed,
but some offsets remained stale; current AST and file hashes were authoritative.

## Validation

| Local selection | Passed | Pytest duration | Retained artifact bytes |
| --- | ---: | ---: | ---: |
| New failure, retry and active-plan return cases | 6 | 1.76 seconds | 16,388,096 |
| Seven service and compatibility suites | 158 | 91.32 seconds | 529,625,088 |
| Four world, civic, information/politics and recorded-replay suites | 27 | 123.68 seconds | 158,917,651 |

The six focused cases overlap the 158-case selection. Documentation and the
unsupported-version admission check are verified separately. All test batches
keep source hashes and modification times fixed. The existing Starlette/httpx
deprecation warning remains.

World validation repeats the nine-day professional-return and successor workflow:
47 permanent people, four applied movements, and an actual company founded by
person 23 on day 9. Closed source and replay compare exactly, with independently
validated v8 exports. Read-only artifact inspection finds the same 266 information
exposures and 92 subscription records in both worlds. Other cases cover daily
restarts, departure/return phases and historical recorded replay. These are
scripted fixtures, with zero recorded provider cost, not native emergence or
empirical validation.

The new test file is included in the existing lifecycle CI job, whose declared
matrix remains Ubuntu/Windows and Python 3.11/3.12. The entire expanded 13-suite
job and full matrix were not rerun in this slice; local checks use Windows and
Python 3.11. The replay selection ended with about 338.1 GB free, preserving the
40 GiB reserve. The original native campaign, frozen sources, interrupted
verification and recovered copy remain preserved with their original allowances.

## Next execution

Review the remaining 44 original scopes and the mixed admission matrix. Prioritize
the remaining legal/civic authority and estate administration, then initialization
and observer surfaces. Complete full CI, native and earlier acceptance before
public Semantics-21/schema-26 registration or W5 closure. Continue W6–W9 in order,
with goods and equity price discovery equally prioritized.
