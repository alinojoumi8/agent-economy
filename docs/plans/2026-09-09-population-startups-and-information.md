# Population participation: startup authority and information delivery

Status: implemented and locally validated for draft Semantics 21. This extends
the [open population contract](2026-09-09-open-population-boundary.md); ordinary
Semantics-21 admission, the complete participation inventory and W5 remain open.
Goods and equity price research retain equal priority.

## Reproduced behavior

Actual agreed departure left four callable startup operations available to an
outside person: accepting a term sheet, closing its funding round, issuing due
diligence and registering IP. The funding operation transferred 20 USD cents
and issued 25 shares. A balanced ledger alone did not establish valid local
participation. The normal World rumor phase also delivered new information to
person 23 after their day-2 departure.

The initial seven cases produced five failures and two passes across two
terminal receipts. Offering a new term sheet and reviewing a merger already
rejected the departing fixture actor because departure vacated their role.
Those successes were retained alongside the other failures. The source files,
databases and logs use `tmp/estate-finality-population-startup-shock-reproduction*`.

## Implemented rules

[StartupLifecycle](../../engine/startups.py) now checks the current available
person before each of its six independently role/identity-authorized commands:
term-sheet proposal and acceptance, funding closure, diligence, IP registration
and merger review. It uses the existing bound legal/business-control residence
rule. Missing residence history fails before effects. A rejection cannot create
financial, legal, IP or event rows.

The other five actor-bearing startup paths already require current firm control:
disclosure, IP licensing, merger proposal, target approval and merger closure.
They retain that rule. Share ownership, named investor identity, previously
accepted agreements, completed diligence and other recorded assets are not
deleted on departure. After return, the person can perform an otherwise valid
action on those retained records. Returning does not restore a vacated VC or
regulatory role. Semantics 1–20 retain the previous service behavior.

[Rumor delivery](../../world/shocks.py) filters both `all_citizens` and
`current_depositors` to current residents before deterministic ranking and the
recipient limit. Thus outside recipients do not consume the local delivery
budget. Every candidate's residence is checked before any memory is inserted.
An empty eligible audience records an explicit zero-recipient event. Draft-21
rumor events add `population_scope: resident_citizens`; legacy payloads and
keyed/random behavior remain unchanged. Bank deposits and other financial-owner
aggregates retain outside assets; only recipients are filtered.

## Current validation

[Ten dedicated cases](../../tests/test_population_startups_and_shocks.py) passed
in **54.44 seconds**. They exercise actual group settlement, whole-state equality
after rejection, return without role restoration, missing-history rejection and
an empty depositor audience. A later missing residence reference leaves no
earlier rumor memories or events.

The full six-day fixture declares a genesis company and accepted investment
agreement. Person 23 leaves on day 2 and returns on day 5. Both source and fresh
recorded replay close/reopen after day-4 NIGHT_CLOSE. A scripted day-6 proposal
passes through normal model-response recording and deterministic action
validation, closing the retained agreement exactly once for 20 USD cents and
25 shares. Replay is forbidden from invoking the scripted policy again.
This is a declared mechanical fixture, not endogenous company formation or
evidence that an autonomous policy will choose the investment.

The independent closed-artifact audit records:

| Day | Residents / known living outside | All-citizen rumor recipients | Depositor rumor recipients | Person 23 included |
|---|---|---|---|---|
| 3 | 46 / 1 | 21 | 10 | No |
| 5 | 47 / 0 | 22 | 11 | Yes |

Person 23 has no new rumor memory on day 3. Their day-6 investment uses one
recorded `scripted` decision call. Both ledgers reconcile and the full replay
comparator passes. Authoritative hashes agree for events, memories, shocks,
term sheets, funding rounds, diligence, shares, accounts and ledger entries.
The source's v8 Parquet bundle passes source-backed validation. Source bytes
and mtime remain unchanged, no SQLite sidecars remain, and provider cost is $0.
The source and replay each occupy 12,345,344 bytes in the dedicated fixture.

| Receipt prefix under `tmp/` | Actual result | Test directory / artifact bytes |
|---|---|---|
| `estate-finality-population-startup-shock-correction-r4` | 10 passed, 54.44 s | `C:/Users/matri/.codex/tmp/ae-3aa24976` / 49,848,992 |
| `estate-finality-population-startup-shock-ci` | 148 passed, 262.21 s | `C:/Users/matri/.codex/tmp/ae-b7e64e74` / 696,125,938 |
| `estate-finality-population-startup-shock-compatibility` | 191 passed, 155.95 s | `C:/Users/matri/.codex/tmp/ae-61094d3c` / 826,355,933 |

The dedicated cases overlap the 148-case job. The two broader batches contain
339 cases, including Commons/control replay, legacy startup/merger workflows,
authority, movements, household/fiscal participation, keyed randomness,
governor/World behavior, PRD smoke and Semantics-1/2/golden source replay.
All three passing runners exited 0 with their 1,148-file source snapshots
unchanged and staging empty. One existing Starlette/httpx deprecation warning
remains. The updated CI job specifies Ubuntu/Windows and Python 3.11/3.12;
only local Windows/Python 3.11 was executed here.

An intermediate fixture attempt had eight passes and two failures: an
incomplete synthetic shock row, and a participant action that the existing UI
catalog withholds after a VC role is vacated. The corrected shock fixture uses
the real scheduling API. The full simulation uses the recorded scripted agent
proposal described above; the participant catalog was not widened. The failed
fixtures, tested source versions and terminal receipts remain preserved.

## Inventory and remaining admission work

The current MCP life-status search reports 232 matches in 156 graph results.
Some graph symbol coordinates lag source changes. The saved audit resolves the
actual matched lines through pre-edit and current ASTs into 150 source scopes,
with file hashes and precise current coordinates. Eleven startup actor methods
and the rumor delivery path have explicit dispositions in this pass.

This is not an exhaustive inventory: an actor-bearing service can have no
`alive` check and therefore never appear in that lexical search. The candidate
list and closed-artifact audit are saved under
`C:/Users/matri/.codex/tmp/ae-cbbdc02d/participation-inventory-progress.json` and
`startup-shock-artifact-audit.json`. Undispositioned candidates remain explicit.

The subsequent [credit and older VC review](2026-09-09-population-finance-entrypoints.md)
traces those callers and verifies a combined 15-day World financing workflow
through departure, return, restart, replay and export. Continue with the
remaining runtime, authority, commitment, economic and observer entry points
and the declared mixed source/restart/replay/export matrix. Do not infer that
every helper needs the same residence filter or remove outside-owned assets.

Schema 25, maximum supported Semantics 20 and migration registration are
unchanged. Full CI, native horizon/full-prefix verification, W5 acceptance and
W6–W9 remain pending. Preserve the native source, both frozen environments and
the interrupted verifier evidence. Tests retain the 40 GiB free-space floor.
