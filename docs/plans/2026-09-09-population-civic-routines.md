# Civic availability through departure and return

Draft Semantics 21 now validates the named lawyer before collecting a business
permit fee and again at automatic review or clerk approval. The professional
must be alive, qualified, adult and currently resident. Missing residence history
raises before money, case, authorization or task-completion changes.

Four failures were reproduced against the preceding source: an outside lawyer,
a minor lawyer or invalid lawyer history still allowed an application fee; a
clerk could approve an existing case after its lawyer's history became invalid.
`City._lawyer_failure` now supplies the shared check. Semantics 1–20 retain
their earlier validation stage and eligibility rules.

Existing departure behavior already ends pending personal cases and unused
permits tied to the departing lawyer. It preserves a formed company and
consumed authorization. This change closes admission and review gaps; it does
not introduce licensing, professional service capacity or a lawyer-fee market.

## Executed city scenario

The eight-case [suite](../../tests/test_population_civic_routines.py) includes a
declared nine-day World with 47 existing people and actual city services.
One existing adult is declared unemployed at genesis to fill an office vacancy;
the applicant's daily decision cadence is explicit. Providers are scripted.

| Day | Verified behavior |
| --- | --- |
| 1 | The applicant pays 2,500 NSD cents and receives a permit appointment. |
| 2 | The lawyer departs; that case and its appointment end. |
| 3 | A new application naming the outside lawyer is rejected, with no additional fee or case. |
| 4 | The clerk departs. An existing local adult succeeds them. Source and replay restart after NIGHT_CLOSE. |
| 5 | The lawyer returns with the same identity and accounts. |
| 6 | A fresh application pays one new 2,500-cent fee. |
| 7 | Actual appointment attendance submits the case for review. |
| 8 | The successor approves the permit. The old clerk returns without displacing the successor. Source and replay restart after EXECUTION. |
| 9 | One company forms using the permit and a 500-cent ledger capital transfer. Its 1,000 issued shares carry no executed price. |

Both ledgers reconcile. Recorded replay is exact and both closed databases
validate against hash-contract-v8 exports. The source's hash, modification time
and absence of sidecars remain unchanged. The lawyer and clerk receive no
model calls, local time rows or effective presence while outside; local presence
resumes on return. Provider cost is $0.

All person identities and original account ownership/currency identities remain.
The four named participants retain their wallet pointers. Another person's
internal regional migration can select a different currency wallet while
preserving the original account; the test checks that distinction explicitly.
Total permit fees are 5,000 NSD cents, separate from the company's 500-cent
capitalization. This is a declared workflow, not native demographic acceptance
or a calibrated price-discovery result.

## Validation and scope

`tmp/estate-finality-population-civic-*` retains each source snapshot and terminal
receipt. `application-reproduction` has three actual failures and
`review-reproduction` has one. `correction` passes the four original cases.
The final `workflow-verified` passes eight cases in 91.03 seconds, retaining
67,466,260 artifact bytes and leaving 101,475,962,880 bytes free. The source
snapshot stayed unchanged during the run and staging stayed empty.

An initial fixture omitted the required business idea. Later fixture corrections
made the intended cadence explicit and distinguished wallet selection from
account ownership. Those failures are preserved separately and are not counted
as production defects. An existing Starlette/httpx deprecation warning remains.

The suite is added to the population/Commons CI selection. Broader integration
passed all 190 tests in the exact 15-suite selection locally in 617.99 seconds
(`ci`, wrapper 619.31 seconds), retaining 1,026,056,182 artifact bytes and
leaving 356,414,152,704 bytes free. The six-suite civic, construction,
succession and participation compatibility selection passed 84 tests in
177.74 seconds (`compatibility`, wrapper 179.16 seconds), retaining
406,626,061 artifact bytes. Both runners exited 0 with all source hashes and
modification times unchanged and staging empty. These are local Windows /
Python 3.11.15 results; the configured Ubuntu/Windows and Python 3.11/3.12
matrix remains unexecuted here. Counts overlap the focused run.

The drive's free space increased during this turn and now exceeds the earlier
104 GiB native admission threshold. A separate read-only observation records
the interrupted verifier's database and WAL/SHM hashes, absent recorded process
IDs, original specification and original stage budgets. The native source hash
still matches. Prepare a prospective recovery/verification protocol using that
evidence; more disk space does not extend the original exhausted native time
budget or turn the interrupted verification into a completed run.

Ten more original civic scopes are reviewed, bringing the current inventory to
69 reviewed and 81 remaining out of 150. Initialization, staff creation and
succession, routine leases, effective presence, applicant/staff reconciliation,
task assignment and mechanical permit review have explicit dispositions. The
previously reviewed application scope was revalidated after this change.

The remaining runtime context and recovery paths retain their separate reviews.
Complete participation admission, the mixed scenario matrix, full CI, the native
horizon/full-prefix verification and earlier acceptance before closing W5 or
registering public Semantics 21/schema 26. Public admission remains at Semantics
20/schema 25. W6–W9 retain their order and full scope, with goods and equity
price discovery equally prioritized. Bounded work retains the 40 GiB reserve.
