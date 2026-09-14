# Atomic lifecycle settlement and continuing inheritance

Status: implemented and locally validated in the draft Semantics-21 boundary.
The original population inventory has **98 reviewed scopes and 52 remaining**.
Public schema 25, maximum supported Semantics 20 and the unregistered migration
26 remain unchanged. Full W5 admission, CI, native acceptance and W6–W9 remain open.

## Corrected behavior

`Lifecycle.run_nightly` now encloses the complete draft lifecycle batch in one
savepoint: new-person registration, local-service commitment checks, premiums,
aging and health, hazard/scheduled births, and custody reconciliation. A hard
failure rolls back every earlier database effect in that batch. Nested individual
birth, estate and custody savepoints continue to apply.

The normal `World.step` NIGHT_CLOSE phase already had an outer savepoint. This
change closes a gap for direct engine callers, including component research
fixtures. It does not change the successful settlement order. Versions 1–20
call the extracted original driver without the new aggregate savepoint, preserving
their recorded semantics. Draft biology uses keyed draws, so the added boundary
does not require rewinding a sequential lifecycle random generator.

Two explicit Semantics-21 reproductions fail against the original driver:

- Corrupt residence evidence for a later person leaves an earlier registration,
  birthday and real child birth applied before the exception.
- A failure during the final custody/project refresh leaves an earlier premium
  and scheduled birth applied.

Both cases now restore every table's rows to the pre-call state. The second
case then retries successfully, creating the same child identity with a
zero-funded wallet, one active guardianship and exactly one due premium. Ledger,
household and population-commitment checks pass.

The first attempt at the service test unintentionally left its lifecycle component
at Semantics 20. That fixture was corrected to select 21 explicitly; both failures
were reproduced again against the original driver before testing the correction.
The initial and definitive source/test variants and receipts are retained.

## Ownership and source review

Outside residence continues to affect local participation without erasing
financial rights. A new test performs an actual prospective departure by an heir,
then settles the resident owner's death. The heir receives **100 USD cents** in
the existing checking account and **37 EUR cents** in a matching-currency wallet.
The heir stays outside, keeps the original checking pointer and residence history,
and receives nothing again when death settlement is retried. Estate and ledger
invariants pass. This is a controlled accounting fixture, not demographic evidence.

Eight original scopes are dispositioned: the five remaining lifecycle candidates
and `EstateCases.beneficiaries_for`, `_wallet` and `open`. Supporting reads cover
registration, age, birth, scheduled birth, health, keyed randomness, commitment
checks, estate receipt batching/claims/rights/distribution and the World caller.
Graph discovery was checked against current AST where indexed offsets were stale.

Living partner/child and then parent relationships retain their existing priority;
the fallback uses the strongest living social tie with deterministic identity
ordering. Outside people can inherit. Estate receipt routing respects account
ownership and currency, including a recorded estate for a deceased recipient.
It grants no local service or operating authority. No extra resident filter was
added to these financial helpers.

## Validation

| Local selection | Passed | Pytest duration | Retained artifact bytes |
| --- | ---: | ---: | ---: |
| Nightly rollback, outside life and Semantics-20 services | 51 | 47.86 seconds | 158,126,080 |
| Household/care, lifecycle matrix, recorded replay and keyed randomness | 37 | 364.10 seconds | 324,123,014 |

The final focused tests, documentation checks and unsupported-version admission
check also pass. The final focused version replaces a redundant event-name check
with direct equality of the outside heir's residence history. The production
source was unchanged throughout both broader selections.

The replay selection repeats the seven-day birth/departure/outside guardian
death/return city case, both guardian-loss/adulthood timing cases, recorded
historical replay and keyed-draw/source-preservation tests. The city workflows
restart, compare closed source and replay records exactly, and validate their
v8 exports. The care case still records 360 delivered minutes, two actual food
purchases and one unmet food unit on return; no artificial supply was added.

All checks use Windows and Python 3.11 with scripted providers. The new three-test
file is included in the existing lifecycle CI job's Ubuntu/Windows and Python
3.11/3.12 matrix. The entire expanded 12-suite job and full matrix were not rerun
in this slice. The existing Starlette/httpx deprecation warning remains.

The 40 GiB disk reserve stayed intact. The original native campaign, frozen
runtime/analysis sources, interrupted verification files and recovered copy remain
preserved. Their original cumulative resource allowances have not been reset.

## Next execution

Continue the remaining 52 original participation scopes and mixed scenario
admission, beginning with cognition/institutional services and remaining civic
and legal authority. Complete the full CI and native/earlier acceptance before
public Semantics-21/schema-26 registration or W5 closure. Then continue W6–W9
with goods and equity price discovery equally prioritized under the saved roadmap.
