# Household residence, custody and delivered care

Status: implemented and locally validated in the draft Semantics-21 boundary.
The original participation inventory now has **90 reviewed scopes and 60
remaining**. Public schema 25, maximum supported Semantics 20 and the unregistered
migration-26 boundary remain unchanged. Full population admission, CI, native
acceptance and the later workstreams remain open.

## Corrected behavior

Four focused reproductions exposed effects that could proceed without valid
residence admission: an outside adult could use the direct internal household
split service, and a child with corrupt residence evidence could be included in
a family separation, named care plan or newly assigned guardianship.

- Direct internal separation now checks the adult's local residence at its tick
  before changing a household or returning from the singleton path.
- Family-decision snapshots validate every affected member, including minors.
  Missing evidence raises before agreement, assent or membership effects.
- Local care targets validate the child and exclude outside children. Existing
  named-target validation therefore rejects both missing evidence and an outside
  child introduced through invalid mixed membership.
- Custody repair validates living members of households with living minors
  before changing assignments. It accepts a family together outside, but rejects
  a household that mixes resident and outside members.

Custody and region-mismatch repair now have aggregate draft savepoints. A later
invalid person or a failure during authority/project refresh rolls back earlier
repair effects. The extracted private repair bodies keep their original SQL and
ordering for Semantics 1–20. Custody itself transfers no money, shares or property.

An outside family still has identities, household membership, guardianship and
financial rights. It receives no local time, care delivery or child-food rows.
The normal model/participant/civic entry paths govern local decision admission;
own-household identity and past spending remain readable. Returning people must
use the existing explicit population-movement and care-assent protocol.

## Controlled evidence

Seventeen focused cases pass in **84.94 seconds**, retaining **69,703,431 bytes**.
The original failures and exact test/source variants are preserved.

The component cases cover the four reproduced failures, a real local separation
that keeps primary wards, an accepted time plan with actual delivered care,
replacement-adult validation, aggregate rollback after a later region repair
failure, and rollback after a late custody/control failure. A whole outside family
keeps custody without local consumption or time delivery. Three invalid mixed
membership cases reject local custody/family/care operations without effects.
Four legacy component checks retain original behavior; actual old-world replay
is validated separately.

The city workflow uses an explicitly declared genesis household: parent 27 and
companion 30 already live in region 2. It schedules a day-1 birth, prospective
movement and adult assent, one controlled mortality draw, and a later return.
It does not claim these inputs emerged autonomously. The engine performs the
birth, estate settlement, custody reassignment, movements, daily care, production
and food purchases. The two named adults use recorded scripted decisions; other
agents retain their normal scripted policies.

| Day | Recorded result |
| --- | --- |
| 1 | Child 48 is born; parent 27 delivers 120 care minutes and buys one food unit for 874 IVC cents. |
| 2 | The companion assents to the group departure; care and the 874-cent food purchase repeat. |
| 3 | Both adults and the child depart together. Custody remains with parent 27. |
| 4 | The parent dies outside; companion 30 becomes the child's guardian. |
| 5–6 | The surviving guardian proposes the return with explicit child-care terms; there is no local care or food demand while outside. |
| 7 | Guardian and child return. The child receives 120 care minutes, and one unmet food unit is recorded after other buyers exhaust local stock. |

The initial workflow expected a day-7 food purchase and failed. The retained
database shows a funded guardian, actual food production and adult sales, and
zero stock at household provisioning. The final test preserves that shortage:
there are **360 delivered care minutes**, **two food units purchased for 1,748
IVC cents**, and **one unmet food unit** across the three local days. This corrected
test expectation is distinct from the four engine defects. Scarcity stays visible
for later production/price-response research.

The final world has 48 permanent people, 47 living residents, three recorded
departures and two returns. The original adult wallet pointers are unchanged.
The child receives no model calls, and the named adults receive none during
outside days 3–6. Child and surviving-guardian local time rows are absent then;
there are no outside child-care or food-need rows.

Source and replay both restart after day-3 NIGHT_CLOSE, day-4 NIGHT_CLOSE and
day-7 MORNING. The closed worlds compare exactly, and each independently
validates a hash-contract-v8 export against its own records. Source bytes and
modification times remain unchanged, with no closed-source SQLite sidecars.
All calls are scripted with zero recorded provider cost.

## Source review and validation

Eleven additional original candidates have current dispositions: household
split, residence/custody repair and context; family adult admission, snapshot
and reconciliation; daily-time adult admission, care targets, day preparation
and context. Supporting review covers the repair helpers, death closure,
explicit group movement, invariants, time-plan submission and current-agreement
checks. Graph discovery was checked against current AST after stale snippets.

Partnership continuity and own-household financial history are preserved outside.
Normal day preparation already validates and filters the local cohort before
creating time rows. Those paths required a reviewed disposition rather than a
blanket replacement of every living-person query. The other 60 original scopes
and the full mixed admission matrix remain open.

| Local selection | Passed | Pytest duration | Retained artifact bytes |
| --- | ---: | ---: | ---: |
| New household/care suite | 17 | 84.94 seconds | 69,703,431 |
| Exact expanded lifecycle CI selection | 183 | 915.21 seconds | 1,092,013,573 |
| Six-suite compatibility selection | 104 | 377.24 seconds | 377,016,052 |

The exact 11-suite CI selection is recorded in `.github/workflows/ci.yml`, job
`research-population-lifecycle`. The compatibility command is:

```text
python -m pytest -q tests/test_semantics15_households.py tests/test_semantics17_household_decisions.py tests/test_semantics18_daily_time.py tests/test_semantics20_succession.py tests/test_population_decision_context.py tests/test_replay_source_lifecycle.py
```

The final documentation/admission command is:

```text
python -m pytest -q tests/test_documentation.py tests/test_population_residence_history.py::test_unfinished_population_boundary_is_not_advertised
```

Each batch has a terminal result, unchanged tested source hashes/mtimes, no staged
changes and the 40 GiB reserve intact. The CI selection ended with
**339,583,651,840 bytes free**. The two broader selections partly overlapped; their
timings are observations, not throughput guarantees. The existing Starlette/httpx
TestClient deprecation warning remains. Only local Windows Python 3.11 ran here;
the configured Ubuntu/Windows × Python 3.11/3.12 matrix still needs execution.

## Remaining execution

Complete the other 60 source reviews and full population admission scenarios,
earlier acceptance, full CI and native horizon/verification before closing W5
or admitting schema 26/Semantics 21. Preserve the original native source, frozen
runtimes, interrupted verifier and separate recovered copy with their cumulative
budgets unchanged. This slice performs no new native trial or cleanup.

Continue the accepted roadmap through W6 education, W7 production/housing, W8
financial depth and W9 empirical/scale validation. Goods and equity research
retain equal priority. The controlled care and shortage observations are
mechanical evidence, not native generational emergence or real-world fit.
