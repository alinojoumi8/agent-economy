# Population workforce recovery and event provenance — W5 follow-up

Draft Semantics 21 now excludes outside candidates from workforce recovery and
hiring context, including pending-offer counts. The accompanying 34-day World
workflow verifies actual hiring, earned wages, departure, return, restart,
recorded replay and source-validated export. A separately exposed replay-reader
defect is also corrected: workforce recovery events now have checked model
provenance instead of being rejected as unknown event types.

This continues [the population admission contract](2026-09-09-open-population-boundary.md)
and [construction/staff integration](2026-09-09-population-construction-and-role-replay.md).
Public schema remains 25, supported Semantics remains capped at 20 and migration
26 remains unregistered. The complete population inventory and scenario matrix,
native horizon/full-prefix verification, full CI and W5–W9 remain open.

## Admission correction

Departure already rejects the person's pending job applications and offers.
Independent fault-injection cases restore an obsolete offer after a real World
departure. The recovery allocator previously selected outside person 23 ahead
of local person 24. Its coordinator also let an outside acceptance reserve the
same vacancy, suppressing the local acceptance. Normal action validation would
reject the outside action, leaving that otherwise available job unfilled.

The recovery candidate allocator and acceptance coordinator now check residence
at the decision tick before allocation or reservation. Hiring context excludes
outside applicants, incoming offers and candidate counteroffers. Pending-offer
counts include current local candidates before excluding the decision actor, so
neither absence nor a display filter changes another candidate's available slot.
Missing residence history raises before these operations create effects.

The [tests](../../tests/test_population_workforce_recovery.py) cover local and
outside competition, participant reservation, current-context filtering,
retained offer counts and a later candidate with missing history. They preserve
the input decisions and database on failed history validation. Semantics 1–20
retain their hiring behavior; this change neither transfers ownership nor pays
unearned wages.

## Recorded hiring and return

The fixture declares two existing adults unemployed at genesis and gives both
an actual 250,000-NSD-cent offer for the same recorded vacancy. It enables the
existing workforce-recovery policy on day 3. This is a declared integration
cohort, not native unemployment or a calibrated wage level.

| Day | Verified behavior |
| --- | --- |
| 0 | The same 47 identities and their accounts persist. The future mover has a separate 37-IVC holding. |
| 2 | Person 23 departs; their original application and offer become rejected. |
| 3 | Both source and replay restart after NIGHT_CLOSE. Unscheduled local person 24 accepts the remaining offer through workforce recovery and starts employment. |
| 2–4 | Person 23 receives no local time allocation, decision or model call. |
| 4 onward | Person 24 earns actual wage claims through the finite-time mechanics. |
| 5 | Person 23 returns with the same checking account and foreign holding. Model turns resume; the original rejected offer stays rejected. |
| 33 | The new hire's existing 30-day contract settles 250,000 NSD cents in earned wage claims through the ledger. |
| 34 | Both worlds complete with matching hiring, wage, movement and census observations, exact replay and a source-validated v8 export. |

Each closed database is 42,762,240 bytes. Source bytes/mtime remain unchanged,
the ledger reconciles daily and recorded provider cost is $0. These observations
do not establish a native generation, empirical labor-market realism or the
remaining demographic horizon. Goods and equity price discovery remain equally
required by the original roadmap.

## Recovery-event provenance

The first complete 34-day pair had identical deterministic event rows,
1,603 action proposals, 1,069 decisions and 1,123 model-call records. Its 6,604
events differed only in excluded wall-clock timestamps. The verifier nevertheless
rejected 27 model references: 18 `workforce_recovery_model_action_replaced`
events and nine `workforce_recovery_candidate_actions_coordinated` events.

The reader now recognizes those two root-level references. It checks the
execution phase, subject, bounded integer IDs and exactly one matching recorded
decision, including its actor, day, supported role and exact purpose. Altered
actor/day/phase, a broken decision link, an incompatible purpose and malformed
or oversized IDs are rejected. Semantics 7 predates decision rows; its path uses
the supported historical actor/role/purpose contract. A real four-day Semantics-7
source/replay exercises a non-null recovery reference without decision rows.

This changes reference validity, not data or hash definitions. The preserved
failed pair has aggregate hash
`ebce104661e475a2b18c8bdeb84b5002ad1006a3b0530347ed510ea937a33ee5`
with both baseline and repaired readers. The baseline rejects `events`; the
repair validates the pair exactly without changing either database.

## Evidence and remaining work

Receipts use prefix `tmp/estate-finality-population-workforce-`:

| Suffix | Executed result | Artifact directory |
| --- | --- | --- |
| `compatibility` | 152 legacy recovery, labor, finite-time, PRD and source-replay cases passed in 120.12 seconds, before the event-reader change. | `ae-4c4385b3` |
| `reader-compatibility` | 22 bounded, golden and immutable-source replay cases passed in 6.20 seconds. | `ae-43f50f2d` |
| `final` | All 24 focused cases passed in 152.07 seconds; includes both complete source/replay workflows and the validated v8 export. | `ae-8ece314d` |
| `reference-types` | Four additional malformed/oversized-reference cases passed in 7.49 seconds. | `ae-147d81c4` |
| `ci` | All 153 cases in the expanded lifecycle CI selection passed in 574.50 seconds, including the final 28 workforce cases. | `ae-503e1770` |

Counts overlap and belong to their saved source snapshots. The expanded
`research-population-lifecycle` CI job includes the final 28-case suite and
legacy recovery regressions alongside its prior lifecycle, construction, role,
region and commitment coverage (nine suites). Its local receipt uses `ci`;
Ubuntu/Windows and Python 3.11/3.12 are configured, but only local Windows with
Python 3.11.15 is executed here. Final documentation/version-boundary checks use
`docs-final`. Existing Starlette/httpx deprecation warnings remain.

The CI run retained 937,249,660 artifact bytes and finished with
106,120,257,536 bytes free, above the 40 GiB reserve. Its 1,159 counted source
files kept identical hashes and modification times throughout execution;
staging remained empty. The original native source and frozen runtimes remain
separate from these bounded test artifacts.

Failed sources and receipts are retained. Fixture corrections account for other
legitimate applicants, give the deliberately unregistered candidate the job's
actual NSD currency, and follow the negotiated hire's 30-day contract through
payday. Storage correctly rejected deleting a referenced decision and setting a
model-call decision's link to null; the final negative case rebinds that link to
an unrelated real call. A separate legacy probe correctly rejected enabling the
city under Semantics 7 before the maintained legacy fixture was used.

The audit directory is `C:/Users/matri/.codex/tmp/ae-72bcdc8a`. It contains exact
source coordinates/hashes for 12 reviewed scopes, nine prior inventory
candidates and three additional entry points, closed-world observations,
preserved failure hashes and the baseline/repaired source recheck. Current
production delegates to finite time and payroll settles earned claims; their
legacy employee readers retain their recorded behavior.

Continue the undispositioned inventory and mixed admission matrix, including
recovery-owner and existing-decision allocation paths, before version admission.
W6 should clarify the configured initial payroll cadence versus new negotiated
contracts. Native verification, complete CI, earlier W0–W4 provider/workflow/
usability acceptance and W6–W9 remain required by the full goal.
