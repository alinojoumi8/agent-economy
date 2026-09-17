# Household financial inspector — local W5 implementation

This step connects the private position reader to the city/People workflow.
Select a person in Live City, open the citizen dossier, then choose **Inspect
finances**. People also provides the same inspector directly. The selected
person's committed journey tick anchors the request, including while observing
a live run. The collapsed inspector makes no financial request. These views do
not complete the remaining W5 cohort/multi-decade work or any W6–W9 milestones.

## Request and privacy contract

`GET /api/v2/operator/household-finances/{agent_id}` requires `run_id`, accepts
`tick` and `fork_id`, and requires the existing local operator session's
`X-CSRF-Token`. Hosted mode and `operator_households.enabled: false` reject the
request. The flag defaults to true for a trusted local operator server. This
uses that server's existing local trust boundary; it does not authenticate an
external actor through a person ID or create a new hosted financial permission.

The route checks run/fork identity and the position reader checks a committed
Semantics-20 boundary with sufficient historical evidence. Invalid run/fork,
future/active ticks, incompatible semantics and incomplete histories return
errors, with no repair or mutation. Private reader exceptions are replaced by a
generic error without source identifiers. Successful and handled error responses
carry `Cache-Control: private, no-store`.

The `operator.household-finances` envelope contains `household-finances-v1` for
the selected household and estates on its conditional residual paths. The
selected person must have a core/pinned identity at that tick. Other household
members, counterparties and deceased nominees retain that identity rule: private
people and estates have anonymous names and no person ID. Authorized local
household totals still include their financial positions. The client omits a
response whose run, fork, person, tick, contract or visibility differs, and hides
cached values during a refresh or after denial. Instrument pages reset when
scope or currency changes.

Only the selected inventory is serialized. Account keys, source-evidence IDs,
private filings, unrelated households, other estate beneficiaries and the raw
per-person cash distribution are omitted. Display references for instruments
and estate boundaries are opaque within the response. The public
`build_city_households` projection is unchanged. The operator endpoint is not
installed as an external-agent capability.

## Display and measurement contract

The currency selector keeps signed wallet cash, restricted cash, receivable
face amounts, debt face amounts, dated equity execution marks and unpriced
instruments separate. It makes no currency conversion or net-wealth estimate.
Both sides of an internal household claim remain labelled. Claim replacements
reference only other instruments in this inventory. Property fractions stay
exact; share marks include unit price, execution tick and age.

Conditional rights retain their exact fraction and every intervening estate.
Each estate shows retained amounts, creditor priority and reserve limits in the
selected currency. Reserve limits are neither additional admitted debt nor a
measurement of held cash. Completed distributions remain final; future claims
reach retained assets and future receipts. No unconditional inherited cash is
shown for an unsettled residual path.

The cash Gini card is currency-specific and names its population: all living
registered citizens, including minors and citizens without a wallet in that
currency. It nets checking/savings/FX cash per person/currency and clips negative
net cash only for the inequality formula. Signed and negative cash totals stay
visible. Empty and zero-positive-cash populations have explicit zero-convention
labels. This is individual cash inequality. The macro panel now labels the
unchanged old series **Legacy account Gini** and explains that its currencies
and account types are not separated.

## Verification and remaining limits

The guarded backend run passed **50 tests in 109.80 s**, including 13 new API
cases, the 22 household-inventory cases, legal projections and the metric
registry. Its 1,090 source files retained both hashes and modification times;
staging stayed empty. Receipt prefix:
`tmp/estate-finality-household-finance-ui-first`; fresh test base:
`C:/Users/matri/.codex/tmp/ae-736746d8`. Artifacts used 129,044,480 bytes and
169,871,851,520 bytes remained free at completion. Only the existing
Starlette/httpx deprecation warning appeared.

Type checking and **261 Node tests** passed. The first full Node pass exposed 14
missing event display codes from the succession implementation; those now have
distinct registry codes and the uniqueness/completeness checks pass. Browser
checks cover desktop/mobile layout, keyboard expansion, exact fractions,
execution dates, currency changes, missing-cash meaning, request lineage and
removal of cached data after a denial or mismatched response. Screenshot review
found and corrected a contrast mismatch with the current World OS theme. The
six relevant development-browser cases passed again, including measured text
contrast of at least 4.5:1 on summary and cash-Gini readings.

The dashboard bundle builds successfully with a large-chunk advisory. The first
production-preview attempt failed to mount assets at `/static/`; its six tests
could not render the app. A temporary FastAPI static/SPA harness uses the same
asset layout as the application server for the corrected bundle smoke check.
Its first launch needed a Windows command-path correction before tests could
start. After that correction, all **six production-bundle browser tests passed
in 12.6 s**. Captures and failure/retry evidence remain under
`tmp/estate-finality-household-finance-browser-*`; the final production captures
are in `tmp/estate-finality-household-finance-browser-static-final`.
API amounts are checked against actual mechanics fixtures; browser interaction
fixtures are synthetic and are not long-horizon economic evidence.

Documentation verification passed **22 tests / 0.53 s**, with all 1,091 source
files unchanged and empty staging. Prefix:
`tmp/estate-finality-household-finance-docs`; fresh base:
`C:/Users/matri/.codex/tmp/ae-7e81f8d5`. The final static check passed syntax and
whitespace checks for 84 changed/new Python files and preserved all 19 frozen
migration/hash paths. The unrelated storage-cleanup plan remained unchanged.

The private builder still reconstructs the full world's inventory before
scoping its response. Lazy opening limits routine requests, but historical
ledger scans and estate-path growth need profiling before large-world claims.
Combined and repeated cohort stresses, multi-decade campaigns, full CI and
publication gates remain pending. Goods and equity research retain equal
priority. No paid providers, cleanup, staging, commits or publication belong to
this step.
