# Population bank support and market admission — W5 follow-up

Central-bank support now validates the official's residence in draft Semantics
21. A stale role and a matching model-call record cannot authorize an outside
person to approve a rescue or deny support. Staffing checks also exclude that
person, so a request cannot wait for an official who has left the economy.

This continues [the credit/VC review](2026-09-09-population-finance-entrypoints.md)
and [the open population admission contract](2026-09-09-open-population-boundary.md).
The migration remains unregistered, schema remains 25, and maximum supported
Semantics remains 20. These changes do not close W5, native acceptance, full CI
or W6–W9.

## Reproduced defects and correction

The ordinary action executor already checks actor residence. The bank service
also promises actor-correct decisions and validated staffing, but independently
checked only `alive` and `role`. Five controlled cases reproduced the missing
residence boundary:

1. After an actual two-day World departure, restoring only the old role field
   and supplying a matching declared provenance row allowed a 100-cent rescue.
2. The same stale official could deny support and enter bank-failure settlement.
3. The staffing query counted that outside official as available.
4. Missing history for a later official was ignored before liquidity effects.
5. Missing history for the decision actor was ignored before rescue effects.

The stale role/provenance rows are deliberate fault injections, not evidence
that ordinary departure restores a role or produces new model calls. Both
failed test runs and their exact tested sources remain preserved.

`Economy` now connects the bank to the existing population service. In
`engine/credit.py`, the Semantics-21 staffing query validates every candidate's
history before accepting an available official. A later invalid history raises
instead of becoming a vacancy or being skipped after the first valid actor.
`attempt_liquidity_support` preflights staffing before interbank transfers or
request creation. `decide_liquidity_support` checks current residence before
model provenance, approval, denial or monetary effects.

Legacy staffing and actor eligibility retain their previous semantics. The
policy for a genuinely unstaffed central bank remains the existing explicit
denial/failure path. Existing deposits, loans and owner claims are not filtered
by residence. Institutional settlement still routes money through the ledger.

## Market entry-point dispositions

| Surface | Reviewed boundary |
| --- | --- |
| Personal stock orders | `ActionExecutor._do_place_order` runs after the central actor guard and retains currency, funds and share checks. Departure cancels unfilled personal orders through the commitment service. |
| Estate stock orders | `EstateSecurities.place_order` authorizes the current representative, then calls the exchange with the deceased owner's custody identity. The exchange insertion primitive must preserve this distinction. |
| IPO bids | `ActionExecutor._do_place_ipo_bid` supplies actor admission and issuer-control restrictions before the firm service checks the offering, currency and commitment. Departure ends open personal bids. |
| FX orders | The current production caller is `ActionExecutor._do_place_fx_order`, after actor admission. The regional cancellation primitive also serves institutional departure endings. |
| Bank support | Deposit-transfer and World liquidity sweeps enter the service; supported policy decisions enter through the action executor. The service now independently validates residence as described above. |
| Endowed market benchmarks | `MarketFixture` explicitly constructs its own Semantics-14 firm mechanics and endowed participants without the World scheduler. Its `_person` helper is a declared fixture boundary, not an open-population arrival implementation. |

The review resolves nine current raw call sites against actual AST scopes.
Several graph labels point to neighboring methods; the saved source inventory
records the real callers, coordinates and file hashes. The earlier startup,
credit and population inventories retain their own evidence. Other runtime,
authority, commitment, economic and observer paths still need their complete
dispositions; this table is not a complete participation audit.

## Executed acceptance

The five negative cases now reject or fail closed with the expected request
state and balanced ledger. Failed admission preserves the complete database
contents. The corrected compatibility batch also retains ordinary approval,
denial, currency-specific reserves, durable request state and recorded legacy
policy replay, plus the preceding 15-day debt/company financing workflow.

A sixth case exercises a controlled local rescue through the real Semantics-21
World runtime: declare a 100-cent request in genesis, record one local official's
approval on day 1, depart on day 2 and return on day 4. Source and replay both
restart after day-3 NIGHT_CLOSE. The departed person receives no model calls
on days 2–3; return preserves the vacated role. There is one rescue transaction
and one accepted, model-linked policy proposal. Exact replay, a source-validated
v8 export, zero provider cost, daily ledger reconciliation and unchanged closed
source bytes/mtime all pass. This is controlled integration evidence, not
autonomous monetary-policy research or native population acceptance.

| Receipt suffix | Actual result | Retained artifacts |
| --- | --- | --- |
| `reproduction` | First three cases failed in 3.94 seconds; maxfail stopped the remaining two. | 18,358,272 bytes in `ae-15481543` |
| `reproduction-r2` | Remaining two cases failed in 1.84 seconds. | 7,938,048 bytes in `ae-1fb75866` |
| `correction` | 12 cases passed in 77.33 seconds, including loan compatibility and the 15-day finance workflow. | 85,375,084 bytes in `ae-ae438140` |
| `correction-r2` | Six dedicated cases passed in 43.21 seconds, including the new five-day World source/restart/replay/export case. | 45,392,193 bytes in `ae-c4493653` |
| `ci` | 161 integration cases passed in 352.89 seconds. | 800,596,920 bytes in `ae-c9e313ab` |

Prefixes are `tmp/estate-finality-population-central-bank-`; short artifact
directories are under `C:/Users/matri/.codex/tmp`. All runners retained source
hashes/mtimes and empty staging. The latest dedicated run left
112,891,604,992 bytes free, above the 40 GiB reserve. Counts overlap and belong
to their saved tested source snapshots.

Both central-bank suites are part of `research-population-commons`, alongside
the prior social, action, service and exact replay cases. Its exact expanded
target list passed locally on Windows/Python 3.11.15. The runner exited 0 in
353.97 seconds, all 1,153 source files kept their hashes/mtimes, staging stayed
empty and 111,828,312,064 bytes remained free. The six dedicated cases and the
earlier 12-case batch overlap this 161-case gate.

The closed local-rescue source and replay each contain 9,273,344 bytes. An
independent read-only audit confirms the one approved request, one model-linked
policy decision, one rescue transaction, no outside official calls and a
vacant role after return. It also preserves the five failed source fixtures and
their actual approved, denied or pending request states. Audit and inventory
files are under `C:/Users/matri/.codex/tmp/ae-2472992d`:
`central-bank-artifact-audit.json` and `market-admission-inventory.json`.

The final documentation check targets `tests/test_documentation.py` and
`tests/test_population_residence_history.py::test_unfinished_population_boundary_is_not_advertised`;
its terminal result uses suffix `docs-final` under the same receipt prefix.
Other platform/version cells and the complete CI workflow remain unexecuted
here. The existing Starlette/httpx deprecation warning remains.

Continue the full participation inventory and mixed scenario matrix before
version admission. Preserve the original native database, both frozen source
environments and the interrupted full-prefix verifier; this work does not
restart or complete that campaign.
