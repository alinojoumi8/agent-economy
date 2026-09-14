# Resident shopper guidance and household demand

Status: implemented and focused validation passes in the draft Semantics-21
boundary. The original source inventory has **78 reviewed scopes and 72 remaining**.
Public schema 25 and maximum Semantics 20 remain unchanged; migration 26 is
unregistered. W5 admission, full CI, native acceptance and W6–W9 remain open.

## Corrected behavior

An uncached citizen context used every living, noncritical citizen to divide
available inventory. That included children and people who had departed. In a
declared stock fixture with two units per eligible adult shopper, this produced
a one-unit suggestion. Missing residence evidence also went unchecked.

`ContextBuilder._citizen_context` now counts living adult resident citizens for
this draft-version fallback. It validates their residence at the requested tick.
The normal morning path continues to use the actual scheduled cohort. Cached and
uncached counts need not be equal under arbitrary wake cadences; these tests
explicitly give all existing citizens a daily cadence. Original Semantics 1–20
fallback queries remain intact. No prices, balances or ownership records are
changed by context construction.

Children continue to consume through household provisioning. Departure does not
erase personal debt, cash or shares. The scheduler already excludes outside
people and minors before local decisions; no additional normal-run per-person
history validation was added to cohort preparation.

## Evidence and fixture boundaries

Thirteen focused cases pass in 190.39 seconds, retaining 134,256,179 bytes.
Source hashes and modification times remain fixed throughout the test run; the
index is empty and the 40 GiB free-space reserve is preserved.

Six component cases combine outside people, children or both with regional and
global action surfaces. They explicitly declare stock for two units per eligible
shopper, read fresh contexts without database writes, execute the suggested
purchase and verify actual inventory reduction, cash debit and reconciliation.
Two corrupt-history cases reject the read without effects. Two component checks
retain the old fallback result; actual historical-world compatibility is a
separate validation boundary. A later child's corrupt history rolls back the
entire existing household-provisioning call, including earlier effects.

Two seven-day city World workflows use real production and settlement. Their
only fixture cadence override is declared at genesis for both source and replay;
neither workflow inserts inventory or overrides prices. A child is born on day 1,
another adult departs on day 2 and returns on day 5. Both source and replay restart
after day-2 MORNING and day-5 NIGHT_CLOSE.

| Household | Recorded seven-day food demand | Actual purchases | Actual spending |
| --- | ---: | ---: | ---: |
| Parent 24, region 1 with no food producer | 7 units | 0 units | 0 NSD cents |
| Parent 27, region 2 with food production | 7 units | 7 units | 4,660 IVC cents |

The initial workflow incorrectly expected positive purchases in region 1. Its
failed receipt is retained. Inspection showed adequate guardian cash but no
same-region food producer. The final tests cover both real shortage and available
supply; this is a corrected test assumption, not an additional engine defect.

Each final workflow has 48 people, unchanged original wallet pointers, no model
calls for the child and none for the departing adult on outside days 2–4. Daily
needs and shopper observations match replay exactly. The closed source and replay
databases compare exactly, export hash-contract-v8, and validate independently
against their own records. Source hashes and mtimes remain unchanged and closed
sources have no sidecars. All provider calls are scripted with zero recorded cost.

## Source review

Seven additional original candidates have current dispositions:
`prepare_decision_cohort`, `_citizen_context`, `scheduled_agents`,
`Households.register_person`, `Households.birth`, `Households.provision_children`
and `Metrics._unemployment`. Graph caller discovery was checked against current
AST source because indexed snippets were stale.

Registration creates origin evidence for a newly created identity; it must not
require that evidence to exist already. Birth retains its atomic permanent child
identity and zero endowment. Household purchases retain same-region, same-currency
suppliers and ledger settlement. The legacy unemployment helper is bypassed by
the current draft snapshot's validated resident metrics, so its historical
denominator was preserved.

Custody/residence reconciliation and the remaining institutional, merger and
recovery employment paths still require their own review. These seven dispositions
do not close the broader mixed scenario or population admission requirements.

## Local validation

| Selection | Passed | Pytest duration | Retained artifact bytes |
| --- | ---: | ---: | ---: |
| New focused suite | 13 | 190.39 seconds | 134,256,179 |
| Exact 17-suite population/Commons CI selection | 214 | 1,076.09 seconds | 1,257,819,179 |
| Six-suite compatibility selection | 170 | 265.77 seconds | 797,790,029 |

Every batch has a terminal zero exit, unchanged source hashes and modification
times, an empty index and the 40 GiB reserve intact. The CI selection finished
with 345,149,276,160 bytes free. The broader selections ran concurrently for part
of their duration; these are observed timings, not throughput guarantees. Each
reports the existing Starlette/httpx TestClient deprecation warning.

The exact CI target list is recorded in `.github/workflows/ci.yml`, job
`research-population-commons`. The compatibility command is:

```text
python -m pytest -q tests/test_semantics15_households.py tests/test_population_outside_life.py tests/test_population_metrics.py tests/test_scheduler_scaling.py tests/test_population_runtime.py tests/test_prd_completion.py
```

The final documentation/admission command is:

```text
python -m pytest -q tests/test_documentation.py tests/test_population_residence_history.py::test_unfinished_population_boundary_is_not_advertised
```

The configured Ubuntu/Windows × Python 3.11/3.12 matrix requires its own CI run;
local Windows Python 3.11 results do not substitute for that matrix.

Preserve the original native source, frozen runtimes, interrupted verifier and
the separate recovered copy. No native trial or cleanup is part of this slice.
The original replay allowance and the outstanding native horizon remain intact.
Longer supply and price-response experiments remain part of W7/W9; the observed
shortage stays visible in the research evidence.

Next work: review the remaining 72 original candidates and mixed scenarios,
complete W5 admission and prior acceptance, then continue W6–W9 in order with
goods and equity price discovery equally prioritized.
