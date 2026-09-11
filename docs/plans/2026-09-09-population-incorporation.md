# Available people at company formation

Draft Semantics 21 now requires a locally available adult lawyer when a person
incorporates a company. The manual catalog excludes unavailable professionals,
and native entrepreneurship checks the founder's residence and chooses from
available lawyers before applying its existing regional preference. A later
missing residence record raises before an incomplete candidate list is exposed.

Five reproduced failures motivated the change: incorporation accepted an
outside lawyer, the manual menu retained that lawyer, the native opportunity
preferred that lawyer over an existing local professional, and direct permit
applications charged fees for outside applicants or applicants with missing
residence history. The permit service now checks adult local availability before
the fee or case is created. Earlier Semantics 1–20 retain their prior rules.

This is availability validation. It does not add a professional licensing model,
lawyer capacity or fee market, or an education system; those remain part of the
later workstreams. Company capital still comes from the founder's existing
account through the ledger, and share issuance does not imply an executed price.

## Verified scenarios

[Thirteen tests](../../tests/test_population_incorporation.py) cover those
failures, missing later candidate history, an outside founder, no available
professional, retained historical service eligibility, return and duplicate
permit-fee prevention. The declared seven-day World uses 44 existing people
and disables city permitting to isolate incorporation through manual control.

| Day | Recorded behavior |
| --- | --- |
| 0 | Person 23 is manually controlled. Existing lawyer 9 and the founder retain their original account identities. |
| 2 | Lawyer 9 departs. The catalog disables incorporation and rejects the queued attempt without changing database contents. |
| 3 | Source and replay restart after MORNING while the lawyer remains outside. |
| 5 | The lawyer returns with the same identity. Incorporation becomes available and is queued for day 6. |
| 6 | Exactly one company is formed; source and replay restart after EXECUTION. Two ledger legs transfer 500 cents from the founder to the new company. The founder receives 1,000 issued shares with no executed price. |
| 7 | The new company and ownership persist, all original person/account identities remain, and the ledgers reconcile. |

Recorded replay is exact. Both closed databases pass source-validated
hash-contract-v8 export, and the source hash, modification time and absence of
sidecars are preserved. Each database is 12,009,472 bytes. The capitalization
uses NSD cents; issuance records have no executed price and zero trade amount.
The outside lawyer receives zero calls on days 2–4;
every provider is scripted and total provider cost is $0. This is a declared
availability/recovery scenario, not a native demographic or price-calibration
acceptance result.

A separate current-city service case returns the applicant on day 5, pays one
permit fee and rejects a duplicate application without any additional effect.
That case validates the direct service boundary; it is not described as the
seven-day source/replay journey above.

## Validation record

Receipts use `tmp/estate-finality-population-incorporation-*`. `reproduction`
preserves the original three failures; `permit-reproduction` preserves the two
direct-service failures. The original source variants and diagnostic databases
remain in their fresh directories. `correction` passes the first three checks.
The ten-case `workflow` passed in 81.25 seconds. The final thirteen-case
`workflow-final` passed in 84.52 seconds, retaining 102,434,624 artifact bytes
and leaving 103,437,434,880 bytes free. Sources kept their hashes and modification
times during each run; staging stayed empty. An existing Starlette/httpx
deprecation warning remains.

The suite is added to the existing cross-platform population/Commons CI job.
Its exact 14-suite selection passed 182 tests locally in 555.35 seconds
(`ci`, wrapper 556.50 seconds), retaining 958,589,945 artifact bytes and leaving
101,769,162,752 bytes free. The six-suite native/manual/civic compatibility
selection passed 95 tests in 121.50 seconds (`compatibility`, wrapper 122.55
seconds), retaining 376,074,240 artifact bytes and leaving 102,754,742,272 bytes
free. Both runners exited 0 with source hashes and modification times unchanged
and staging empty. These were Windows/Python 3.11.15 runs; the configured
Ubuntu/Windows and Python 3.11/3.12 CI matrix has not been executed here.

Nine more original participation scopes have been reviewed. The consolidated
inventory now has 59 reviewed scopes matching current source and 91 remaining
out of 150. Supporting caller reads do not count as completed domain reviews.

## Remaining work

Continue the original participation inventory and full mixed scenario matrix.
The catalog and these service boundaries have explicit scope reviews; their
unchanged domain callees still require the remaining individual reviews. Keep
financial ownership and receipt eligibility separate from local actor authority.

Public schema 25 and maximum Semantics 20 remain unchanged; draft migration 26
is unregistered. Complete admission, full CI, native horizon/full-prefix
verification and the remaining earlier acceptance requirements before closing
W5. W6–W9 retain their original scope and order, with goods and equity discovery
equally prioritized. Bounded tests retain the 40 GiB reserve. The original
native simulation and both frozen readers/runtimes remain separate artifacts.
