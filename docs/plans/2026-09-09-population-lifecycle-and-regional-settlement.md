# Population lifecycle and regional settlement — W5 validation

Two declared 39-day World cohorts now verify guardian death before or on a
child's eighteenth birthday alongside an independent person's departure and
return. Both restart, replay exactly and produce source-validated v8 exports.
The regional review also resolves three current callers and three previously
listed participation candidates. No engine change was needed in this slice.

This continues [the population admission contract](2026-09-09-open-population-boundary.md)
and [the bank and market review](2026-09-09-population-bank-support-and-markets.md).
Schema remains 25, maximum supported Semantics remains 20, and migration 26
remains unregistered. These results advance the draft Semantics-21 matrix;
they do not close W5 or establish native generational behavior.

## Declared mixed lifecycle cases

[The new test](../../tests/test_population_lifecycle_matrix.py) declares a
17-year-old, a guardian, another household adult, a strong inheritance tie and
the guardian's mortality date before the first origin and census. Other deaths
and illness onset are suppressed in this controlled fixture. Actual daily
aging reaches eighteen on day 38; the test does not jump the clock or rewrite
a recorded birth basis. The source and replay use scripted, recorded policies
with zero provider cost.

| Event | Guardian dies on day 37 | Guardian dies on day 38 |
| --- | --- | --- |
| Independent resident leaves on day 2 and returns on day 5 | Same person and checking wallet, 37 IVC retained, no decision calls while outside | Same |
| Household departure proposed on day 35, assented on day 36, due on day 38 | Remains pending on day 37; stale household snapshot cancels at due settlement on day 38 | Aging/death changes invalidate the snapshot before due settlement on day 38 |
| Guardian dies; child inherits eleven company shares | Another household adult holds recorded guardianship and operates the firm for one day | The same-day custody and succession transitions are recorded |
| Child reaches eighteen on day 38 | Guardianship ends; adult membership and shareholder stewardship begin | Same |
| Adult's recorded day-38 decision sets the firm's asking price to 321 cents | Accepted, linked to its model-call record | Same |

The founder identity stays attached to the deceased founder. Custody and
operating authority change separately from ownership. Adulthood supplies no
new cash endowment, and the ward never departs. Every simulated day checks
household invariants, scenario progress and ledger reconciliation.

Source and replay each restart after the NIGHT_CLOSE immediately preceding
the declared death day. The replay consumes the recorded decisions and must
not call the policy producer. Both closed databases compare exactly; exports
validate against their source under hash-contract-v8. Source bytes, modification
time and the absence of SQLite sidecars are checked after validation.

The 321-cent observation is an accepted asking-price action, not an executed
goods trade. The shares are inherited ownership, not an equity execution.
These cases do not measure autonomous behavior, empirical price discovery or
productive native-born generations. Goods and equity research remain equally
required by the original plan.

## Fixture corrections and retained evidence

Four earlier attempts remain preserved with their exact test source and
receipts. Their failures were fixture issues, not newly reproduced engine
defects: genesis registers people twice, so the age declaration must run once;
movement snapshots are rechecked at the due date, not immediately when a
guardian dies; and the first case had no scheduled decision on day 39. The
accepted successor action is now requested on the recorded day-38 birthday
decision, with its successful action result and model-call link asserted.

`tmp/estate-finality-population-lifecycle-matrix-r5-meta.json` records two
passing cases in 237.70 seconds (runner: 238.72 seconds), using 187,886,106 bytes
under `C:/Users/matri/.codex/tmp/ae-25cb40ef`. All 1,154 source files retained
their hashes/mtimes and staging stayed empty. The run left 110,998,765,568 bytes
free, above the unchanged 40 GiB reserve.

The independent closed-artifact audit confirms matching declarations,
guardianships, stewardships, movement results, the accepted price action and
zero-cost/outside-call facts in both source/replay pairs. Audit files and the
retained fixture attempts are under `C:/Users/matri/.codex/tmp/ae-0225cdab`:
`lifecycle-artifact-audit.json` and `attempts/r1` through `attempts/r4`.

## Regional participation dispositions

| Surface | Current checked boundary |
| --- | --- |
| `RegionalEconomy._qualified_migration_option` | Current residence, citizenship, health, retirement, employment, debt, pending applications and qualified wage/cadence opportunity are checked at request and again at settlement. |
| `RegionalEconomy.request_migration` | Draft Semantics 21 uses that shared eligibility check before recording a request; the command also follows the central actor admission guard. |
| `RegionalEconomy.create_shipment` | Current exporter control, active firms, effective bilateral contract, the exact qualified quote, invoice currency and funds precede ledger payment and inventory commitment. Counterparty ownership is retained. |
| `RegionalEconomy.run_nightly` | Already-paid corporate shipments deliver independently of owner residence. A pending regional move revalidates eligibility. External departure also ends a person's pending regional request through PopulationCommitments. |

The actual production callers are `ActionExecutor._do_create_trade_shipment`,
`ActionExecutor._do_request_migration` and `World._phase_night_close`. The graph
returned stale neighboring scopes, so bounded AST resolution records their
current coordinates and file hashes in `regional-admission-inventory.json`.
The broader graph query also matched twelve unrelated nightly calls; those
are recorded separately and are not claimed as reviewed regional callers.

`tmp/estate-finality-population-regional-compatibility-meta.json` records
85 passing cases in 54.18 seconds (runner: 55.16 seconds), using 304,959,488 bytes
in `C:/Users/matri/.codex/tmp/ae-61a848ee`. Its targets are
`tests/test_v2_regions.py`, `tests/test_population_commitments.py` and
`tests/test_population_movements.py`. They exercise contracts, currency,
shipment settlement, personal commitment endings, retained assets, demographic
revalidation, rollback and retry. This is bounded source/test review; it is
not a new mixed World owner-departure shipment experiment.

## CI and remaining acceptance

The new `research-population-lifecycle` job runs the lifecycle matrix and those
three regional/commitment/movement suites on Ubuntu/Windows and Python 3.11/3.12,
with a short isolated artifact directory and a 20-minute ceiling. Its combined
local execution receipt is `tmp/estate-finality-population-lifecycle-regional-ci-meta.json`.
The exact combined target list passed locally on Windows/Python 3.11.15:
87 cases in 290.33 seconds (runner: 291.39 seconds), with 492,845,594 bytes
retained in `C:/Users/matri/.codex/tmp/ae-f0454054`. All 1,155 source files kept
their hashes/mtimes, staging stayed empty and 110,497,439,744 bytes remained
free. This combined count includes the dedicated lifecycle and compatibility
cases above; those counts must not be added again. The existing Starlette/httpx
deprecation warning remains.

The final documentation check uses `tests/test_documentation.py` and
`tests/test_population_residence_history.py::test_unfinished_population_boundary_is_not_advertised`,
with receipt suffix `lifecycle-regional-docs-final`. Other platform/version
cells and the full current-version CI workflow remain unexecuted here.

Continue the undispositioned participation inventory and remaining mixed
World/restart/replay/export cases, especially staff/project departures and
role vacancies with retained company and creditor rights. Admission must wait
for that complete contract. Preserve the original native source, both frozen
runtimes and interrupted full-prefix verification; their horizon, resource
limits and missing completion evidence remain unchanged. W6–W9 and the earlier
provider/workflow/usability acceptance requirements remain open.
