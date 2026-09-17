# Population construction and historical decision roles — W5 follow-up

Construction now checks an actor's current residence before fresh commands in
draft Semantics 21. An outside contributor cannot spend a retained wallet, and
an outside clerk cannot approve a permit through a stale staff assignment.
The combined nine-day World scenario also exposed and corrected a historical
role-validation defect affecting Semantics 20 and 21.

This continues [the mixed lifecycle matrix](2026-09-09-population-lifecycle-and-regional-settlement.md)
and [the population admission contract](2026-09-09-open-population-boundary.md).
Schema remains 25, maximum supported Semantics remains 20 and migration 26 is
unregistered. Full population admission, native acceptance and W5–W9 remain open.

## Reproduced service defects

The ordinary action executor already checks local participation. Four isolated
cases exposed missing checks in the construction service itself:

1. After an actual World departure, an owner could directly contribute another
   100 cents from their retained wallet to an approved project.
2. After a clerk's departure, deliberately restoring an obsolete staff binding
   let that clerk directly approve a pending construction permit.
3. A new actor without recorded residence history could fund construction.
4. That actor could receive construction action suggestions without the missing
   history being reported.

`ConstructionEconomy._start` now applies the current-actor/history check before
fresh draft commands. All seven call sites cover proposal, permit application
and decision, funding, cancellation and both layers of timed work. Existing
cached outcomes retain their historical idempotency behavior; they do not
perform another transfer. `decision_context` applies the same residence boundary
before constructing new action suggestions. Missing supported history raises
before effects. Legitimate refusals may retain their normal rejection receipt.

Legacy command admission is unchanged. The repair does not confiscate accounts,
escrow or property, and does not use death settlement for departure.

## Combined construction and staff scenario

[The workflow tests](../../tests/test_population_construction_workflow.py) declare
two projects, one fully funded with 1,200 USD cents and one with a pending
permit. One existing, qualified citizen is declared unemployed in genesis so
the clerk vacancy has an eligible candidate. This is disclosed initial state,
not a modeled resignation or a newly created person. Construction action choice
is scripted; unrelated automatic project initiation is disabled in this fixture.

| Day | Verified result |
| --- | --- |
| 0 | The owner funds a six-unit home; a separate resident's construction permit remains submitted. |
| 2 | Owner and clerk depart through their recorded movement schedules. Existing resident 24 becomes the permit clerk and approves the same pending case through a recorded decision. |
| 2–4 | The owner keeps title and all 1,200 cents of escrow. Work stays at zero and local project control is vacant. |
| 3 | Source and replay both restart after NIGHT_CLOSE, with the two original people still outside. |
| 5–7 | The owner returns using the same identity/wallet and contributes two work units on each day. Three accepted decisions pay 300 cents in wages and 300 in procurement through the ledger. |
| 7 | The home completes; the remaining 600 cents returns to the original contributor, escrow reaches zero and the owner uses the completed home. |
| 8–9 | The original clerk returns without recovering the old office. The resident successor retains the appointment. |

The owner retains 37 IVC separately. Neither departed person receives model
calls during absence; population identity count remains 47. Daily checks cover
title/stewardship, civic authority, household invariants, scenario progress,
finite time and the ledger. Both closed databases replay exactly, and the
source-validated v8 export passes with zero provider cost and unchanged source
bytes/mtime. Each final database contains 13,299,712 bytes.

These are controlled integration cases. They do not establish native generation,
housing-market prices or economic realism of the existing procurement abstraction.
Goods and equity research remain equally required by the original plan.

## Historical decision-role repair

The first complete source/replay pair had identical rows and identical aggregate
hashes, but two tables failed model-reference validation. The verifier used
person 24's current `permit_clerk` role to check their earlier day-1 `citizen`
decision. The real appointment occurred on day 2. A separate actual Semantics-20
staff-succession case reproduced the same mistake.

The replay reader now reconstructs that supported transition from the dated
`agency_staff_succeeded` receipt and one matching assignment. It reuses the
identity/phase contract from the [historical kind reader](2026-09-09-historical-role-reconstruction.md).
For Semantics 21, it orders the promotion with later recorded personal-role
releases. The predecessor role comes from the maintained promotion rule, which
requires a citizen with no personal role; arbitrary role changes are not inferred.
Missing or duplicate receipts, wrong phases and inconsistent assignments remain
invalid. The lookup is scoped to the actor, not a repeated full-cohort scan.

This is a reader repair. It changes neither stored decisions nor the canonical
hash definition. Rechecking the preserved failed pair with the baseline and
repaired role readers gives the same aggregate hash
`1721e22954a140f0b13d3e024fbcac0da9962968eef41b4f51753921dfdc834c`.
The baseline rejects `action_proposals` and `agent_decisions`; the repaired reader
validates the pair exactly, without changing either file.

A read-only spot check confirms the same defect in the preserved native source:
person 11's day-1 founder call records role `citizen`; appointment event 165606
grants the clerk role on day 7,827. The baseline reader incorrectly returns
`permit_clerk` for day 1, while the repaired reader returns `citizen`. This one
role check is not full native replay, export or horizon acceptance. The original
database, frozen runtimes and interrupted verifier remain preserved; any later
verification attempt must prospectively pin its reader and resource allowance.

## Coverage and retained evidence

| Receipt suffix | Actual result | Retained artifacts |
| --- | --- | --- |
| `reproduction` | Three service failures reproduced; maxfail stopped before the fourth. | 16,289,792 bytes in `ae-6f17a940` |
| `reproduction-r2` | Missing-history context failure reproduced. | 3,977,216 bytes in `ae-01af649f` |
| `role-reproduction` | Semantics-20 historical-role failure reproduced. | 5,730,304 bytes in `ae-2ee5429e` |
| `correction-r3` | All 11 focused cases passed in 60.10 seconds. | 93,736,717 bytes in `ae-8b3472ac` |
| `compatibility` | 94 construction, authority, project, civic and finite-time cases passed in 181.68 seconds. | 349,326,023 bytes in `ae-959dc417` |
| `reader-compatibility` | 55 kind-history, bounded replay, golden replay, immutable source and population-export cases passed in 328.55 seconds. | 170,808,201 bytes in `ae-da78091a` |
| `ci` | All 111 cases in the expanded lifecycle CI target list passed in 410.77 seconds on Windows with Python 3.11.15. | 631,540,007 bytes in `ae-4bd5483e` |

Prefixes are `tmp/estate-finality-population-construction-`. Counts overlap and
belong to their saved tested source snapshots. The compatibility batch preceded
the historical-reader change; the reader batch and final focused run cover it.
All runners kept source hashes/mtimes and empty staging. The expanded CI batch
left 109,022,945,280 bytes free, above the 40 GiB reserve. Its wrapper completed
in 411.83 seconds; the existing Starlette/httpx deprecation warning remains.

Earlier workflow fixtures and receipts are also retained. The first lacked an
eligible replacement worker; the next candidate operated a company and was
ineligible. The corrected declared candidate satisfies the real staffing
predicate. The later failed pair exposed the actual historical-role bug rather
than an economic replay divergence.

The audit directory is `C:/Users/matri/.codex/tmp/ae-1f908c11`. It contains
`construction-artifact-audit.json`, `construction-admission-inventory.json` and
`prior-source-role-recheck.json`, with the failed sources, current call-site
coordinates, file hashes and preserved native spot-check evidence.

The existing `research-population-lifecycle` CI job now includes this workflow,
kind-history tests and golden replay alongside its existing lifecycle, regional,
commitment and movement suites (seven suites total). Its current local execution
receipt uses suffix `ci`; other Ubuntu/Windows and Python-version cells are not
claimed as executed here.
The final documentation/version-boundary receipt uses suffix `docs-final`.

Six prior inventory candidates now have explicit dispositions: construction
action context, project control/succession, inheritance distribution, retained
personal residuals and household home lookup. Property ownership and local
occupancy remain separate. Continue the remaining participation inventory and
mixed scenario matrix before version admission, then the original W5 and W6–W9
requirements. Earlier W0–W4 provider/workflow/usability acceptance also remains open.
