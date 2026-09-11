# Current merger control and startup phase recovery

Status: implemented and locally validated in the draft Semantics-21 boundary.
The original participation inventory has **79 reviewed scopes and 71 remaining**.
Public schema 25 and maximum supported Semantics 20 remain unchanged; migration
26 is unregistered. W5 admission, complete CI, native acceptance and W6–W9 remain
open. Goods and equity price discovery retain equal priority.

## Company opportunities

A company with a deceased founder was excluded from merger suggestions even when
an heir had inherited its shares and could operate it. Nominal cash in a different
currency could also prevent a local acquirer from receiving any opportunity.
Conversely, a company without an available local controller could be suggested.

`ContextBuilder._autonomous_merger_action` now selects draft-version operating
firms in the same sector and currency whose current operator passes the shared
control check. This validates life, adulthood and local residence, and rejects
corrupt history before producing a suggestion. An unavailable cash leader or
cheapest target no longer hides another eligible opportunity. Founder identity
remains historical. Existing minimum age, pending-deal exclusions, cash-share
limit and premium calculation remain, as do the original Semantics 1–20 queries.
Context construction changes no balances, prices or ownership.

This menu still uses the declared cash-plus-premium proposal rule. It is a
controlled mechanism, not evidence of an empirically calibrated merger valuation
or a completed equity price-discovery model.

## Restart contract

The eight-day city workflow exposed a separate engine defect. After day-4 MORNING
was committed and the process restarted, the queued successor approval survived
but its supplied startup menu did not. The exact-copy validator rejected that
valid approval; the day-5 regulator consequently had no deal to review.

With draft semantics and entrepreneurship active, `World.step` now saves the
current day's menus alongside MORNING decisions. A pure codec detaches the cache
and records version 1, the day, ordered actor/action lists and a canonical SHA-256
checksum. EXECUTION validates the complete frame inside its existing savepoint
before replacing the cache or executing a decision.

Missing frames, unsupported versions, wrong days, checksum failures, duplicate
actors and invalid action types are rejected before economic execution. A queued
merger price changed by one cent still fails the existing exact-copy check.
The checksum detects corruption; it is not a signature. Checkpoint and study
manifests provide artifact binding, and normal authority and economic checks
still run. No live context is regenerated to authorize a stored decision.

Older draft partial checkpoints that reach active startup EXECUTION without this
frame are refused. Preserve those artifacts and use a separately recorded
compatible replay or an earlier coherent restart point; do not fabricate a menu.
Historical Semantics 1–20 and inactive entrepreneurship retain their existing
phase path. No public version or migration is admitted by this change.

## Evidence

Eighteen focused cases pass in **96.81 seconds**, retaining **112,145,549 bytes**.
The original guidance/history failures, restart failure and their exact source
variants are retained. A later failed inspection used nonexistent ledger column
names; correcting that test query was necessary, not another engine correction.

Component cases exercise an actual estate transfer, successor approval, regulator
review, conserved cash settlement, unavailable-company selection, missing history
and the preserved legacy helper result. The inheritance tie and company capital
are explicitly declared fixture inputs; the estate itself settles through the
engine. Actual historical-world behavior has separate compatibility coverage.

The full eight-day city scenario declares two additional genesis companies,
capital transfers from existing wallets, a 999/1 target share split, daily cadence
for four people and a departure/return schedule. It inserts no later market
inventory or prices. Scripted agents choose the actual supplied menus:

| Day | Recorded outcome |
| --- | --- |
| 2 | Target founder 24 departs; resident shareholder 23 operates the company. |
| 3 | Acquirer 25 proposes the same-currency merger despite a richer foreign-currency company. |
| 4 | Successor 23 approves after a restart following MORNING. |
| 5 | The competition regulator reviews the proposed deal. |
| 6 | The acquirer closes it for 55,000 NSD cents; execution is followed by another restart. |
| 8 | The outside shareholder returns with the same identity and wallet pointers. |

All four actions are accepted. Actual ledger credits are **54,945 NSD cents** to
the outside majority owner's existing wallet and **55 NSD cents** to the resident
operator's wallet; they balance the acquirer debit. There are still 47 people,
the original founder remains recorded, and there are no model calls for that
owner on outside days 2–7. Source and replay use the same declared genesis and
restart boundaries; replay consumes recorded responses with zero provider cost.

The closed databases compare exactly and each independently validates a
hash-contract-v8 export against its own records. Closed-source hashes and
modification times remain unchanged, with no SQLite sidecars. A separate
read-only audit confirms the four accepted actions, owner credits and return.

## Validation and scope

| Local selection | Passed | Pytest duration | Retained artifact bytes |
| --- | ---: | ---: | ---: |
| Focused merger/restart suite | 18 | 96.81 seconds | 112,145,549 |
| Exact startup/recovery CI selection | 60 | 409.93 seconds | 701,169,725 |
| Four-suite compatibility selection | 115 | 104.23 seconds | 493,334,514 |

The exact six-suite CI target list is saved in `.github/workflows/ci.yml`, job
`research-population-startup-resume`. Its separate job avoids adding time to the
existing population/Commons selection, which previously took about 18 minutes
locally. Ubuntu/Windows × Python 3.11/3.12 are configured; only local Windows
Python 3.11 was executed here. The compatibility command is:

```text
python -m pytest -q tests/test_native_entrepreneurship.py tests/test_v2_startups.py tests/test_semantics20_succession.py tests/test_prd_completion.py
```

Every batch records terminal success, unchanged source hashes/mtimes, an empty
index and the 40 GiB reserve intact. The CI selection ended with
**343,347,884,032 bytes free**. The broader selections overlapped for part of their
duration; measured times are not throughput guarantees. The existing
Starlette/httpx TestClient deprecation warning remains.

The final documentation/admission command is:

```text
python -m pytest -q tests/test_documentation.py tests/test_population_residence_history.py::test_unfinished_population_boundary_is_not_advertised
```

The new original inventory disposition is the merger-opportunity helper.
The phase loop and codec have supporting reviews. Startup settlement was already
reviewed; its existing corporate ownership treatment is not expanded here.
Household custody/residence reconciliation, institutional work, recovery
employment paths and the other remaining inventory scopes still need review.

Preserve the native source, both frozen runtimes, interrupted verifier and
separate recovered copy. No native trial or cleanup is included. The original
horizon and cumulative verification allowances remain; extra disk space does not
reset them. This short scenario does not establish native emergence, real-world
fit or complete W5 acceptance.

Next: finish the 71 remaining source reviews and mixed admission scenarios,
complete earlier acceptance and W5, then proceed with W6 education, W7 production
and housing, W8 finance and W9 validation under the accepted roadmap.
