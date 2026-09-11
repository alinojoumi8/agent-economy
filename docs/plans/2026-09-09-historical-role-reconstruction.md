# Historical role reconstruction — campaign audit failure

Latest reader follow-up: [construction and historical decision roles](2026-09-09-population-construction-and-role-replay.md)
uses the same validated promotion receipt to check a model call's historical
personal role. It repairs a separate false replay-reference rejection for
citizen decisions recorded before appointment as a clerk. The stored source and
earlier annual-report evidence remain unchanged. Full native verification is
still pending and must pin the reader used by a new prospective attempt.

Status: repaired, validated in isolation and integrated after the original
native writer's terminal exit. Corrected audits reproduce all 31 annual
reports through day 11,356. The three integrated files match the tested reader
bytes; the combined root gate passed 213 tests, including role-history,
household positions and legacy replay. The preserved native runtime remains
separate for recorded replay. Earlier evidence below documents the initial
21-report repair on the day-8,009 source.
This was a W5 historical-reporting defect, not a storage failure or evidence
that an earlier household consent was invalid.

## Evidence

The native campaign completed segment 13 at day 8,009 with its original
runtime, seed, daily clock and resource limits. The supervisor then stopped
with exit 1 at `closed_audit_13`; it did not start segment 14. The campaign
metadata remains `paused`, distinct from the failed supervisor.

The saved source hash is
`95743d4dd300633f7366d10512d4fd10a7aff7242373fb9434f1f75378f123af`.
The diagnostic read preserved its bytes and modification time and created no
SQLite sidecars. It compared all 21 previously saved annual household reports.
Every report differed in exactly five fields, all under
`cash_distribution/USD`: person 11's observation, population count, signed
cash, nonnegative cash, and Gini. The rest of each report matched.

At day 365, the saved report includes person 11 with 7,924,568 USD cents and
14 living citizen-kind people; the current historical reader instead reports
13 people and omits that cash. Its Gini changes from 0.35165150480318863 to
0.3643655472847072. These are saved-versus-recomputed observations, not a
correction to the ledger.

The causal code path is specific:

1. Person 25, the original permit clerk, died on day 7,827.
2. `engine/city.py::City._promote_successor` selected person 11 (Ugo Okafor)
   from living, eligible citizen-kind adults and changed their current kind
   to `staff`. Event 165606 records `agency_staff_succeeded` on day 7,827,
   in `NIGHT_CLOSE`; event 165603 ends the previous staff assignment.
3. `engine/position_history.py::people_at` joins the current `agents.kind`
   while applying historical origin/death boundaries. The later promotion
   therefore changes the citizen cohort returned for an earlier day.
4. `cash_distribution_at` correctly applies its declared citizen-only cohort
   rule to that incorrect historical kind. Broadening the metric to all people
   would change its definition and would not repair the time boundary.
5. The temporary family-outcome auditor independently makes the same temporal
   mistake: `read_data` reads current kind, then `validate_assents` uses it
   to test citizenship at an old proposal. It now fails with
   `snapshot adult citizen`. The earlier day-7,667 consent receipt remains a
   historical passing result; revalidation against the later source is pending.

There is no generic agent-kind/role history table in the inspected source.
Existing `agency_staff` effective dates and succession events provide recorded
evidence for this transition. The maintained promotion predicate establishes
that the predecessor kind was citizen; do not infer arbitrary unrecorded role
changes from today's role.

Evidence files, retained without overwriting earlier receipts:

- `tmp/estate-finality-life-course-batch-13-18-meta.json` and its log:
  segment/supervisor exit states and the failing historical report assertion.
- `tmp/estate-finality-life-course-native-40y-segment13-report-diagnosis.json`:
  all 105 differences across the 21 reports, source preservation and new death.
- `tmp/estate-finality-life-course-native-40y-segment13-cohorts.json`:
  independent passing census, birthday, membership, guardianship and ledger
  checks; 32 people, 576 birthdays and 8,010 census days.
- `tmp/estate-finality-life-course-native-40y-segment13-family-audit.log`:
  the separate consent auditor failure, not a passing consent receipt.

Person 27 reached native adulthood on day 7,758, following birth on day 1,188.
The cohort audit verifies both native adults (26 and 27), zero population
endowments, zero minor model calls and balanced ledger/currency checks. These
facts do not close the historical-role or full replay/export gates.

## Repair specification

1. Introduce an explicit selected-boundary kind reader for supported recorded
   transitions. Inventory every current kind mutation first. Reconstruct the
   known citizen-to-staff succession using dated, linked records and its
   versioned transition contract; retain genesis staff as staff. If a transition
   cannot be reconstructed, report that limitation rather than fabricate history.
2. Preserve the existing `citizen-wallet-cash-gini-v20` population, currency,
   netting and clipping rules. Current-day results must remain identical.
   Historical reconstruction must not rewrite saved annual reports, recorded
   metrics, agent state or the original database.
3. Handle phase boundaries explicitly: the position reader observes a committed
   end of day, while household proposals/assents can precede a same-day
   `NIGHT_CLOSE` promotion. A later phase must not invalidate earlier authority.
4. Repair the independent consent audit using dated authority evidence and
   proposal boundaries. Retain its existing acceptance/ownership/linkage
   rejection cases. Keep the old failing helper and receipts as provenance.
5. Develop and validate against an isolated copy of the current working source.
   The existing verifier worktree is reserved for verifier/export work. Preserve
   the native campaign's original engine fingerprint. If corrected readers are
   used for a resumed campaign's audits, declare and pin those audit versions
   separately; do not silently change the simulation runtime.
6. Change new persisted semantics only through the project's version gates.
   A reader-only repair must demonstrate unchanged current-day metrics and
   exact stored replay behavior, including Semantics 1/2.

## Acceptance and resumption

- A citizen's earlier cash reports stay identical after a real staff succession.
  The cohort excludes that person from the promotion day's committed close
  onward, and does not remove them from earlier days.
- Genesis staff, later arrivals, minors, death boundaries, empty cohorts and
  multiple currencies retain their declared treatment.
- Same-day proposal/promotion cases preserve the correct authority at each phase.
- The corrected reader reproduces all 21 saved annual reports exactly from the
  unchanged day-8,009 source, and the corrected consent auditor validates all
  seven partnerships while retaining its negative cases.
- Independently verify current-day equality, original-source byte/mtime
  preservation, no SQLite sidecars, and exact legacy replay.
- Only after those receipts pass, consider the next native segment under the
  original 14,600-day horizon, 14,400-second cumulative native allowance,
  600-second segments, 16 GiB artifacts and 40 GiB free-space reserve.

The failed supervisor is terminal evidence; no automatic retry is implied.
W5, external departure, W6–W9, full integration and full campaign replay/export
remain open.

## Implemented repair and validation

The dedicated worktree is `C:/Users/matri/.codex/tmp/ae-daca0e1c`, captured
from all 1,098 current tracked/nonignored root files. The three-file change
adds `engine/person_kind_history.py`, uses it in `engine/position_history.py`,
and adds `tests/test_person_kind_history.py`. The separate bounded-verifier
worktree is unchanged.

`person_kinds_at` observes a committed day close or the point immediately
before a specified same-day event. It links the dated staff succession to one
matching agency/place/region assignment, checks the transition identity and
phase, and reconstructs the former citizen kind only on the earlier side of
that transition. Missing, duplicate or inconsistent history raises an explicit
error. An assignment ending does not turn staff back into citizens. This
supports the inspected citizen-to-staff transition, not arbitrary unrecorded
role histories.

The mutation inventory found one existing-person kind write:
`City._promote_successor`. The dynamic updates in `Lifecycle._retire` and
`Regions` tier promotion change retirement/cadence or population/model tiers,
not person kind. New-person creation assigns its initial kind separately and
the reader retains the recorded origin boundary.

The corrected temporary consent auditor reconstructs the same boundary
independently from raw staff assignments and succession events. It checks the
proposer's citizenship at the proposal event and each responding person's
citizenship at the actual response event. Other affected adults retain the
existing separation-specific rules. It keeps the original eight negative
consent cases and adds eight malformed/missing/incorrectly timed role cases,
including an otherwise equivalent noninteger actor ID.

Executed evidence:

- **40 passed / 103.20 s**, one existing FastAPI/Starlette deprecation warning
  (104.09 s including the bounded wrapper), across
  `tests/test_person_kind_history.py`,
  `tests/test_semantics20_household_positions.py`,
  `tests/test_replay_source_lifecycle.py`, and
  `tests/test_recorded_replay_golden.py`.
  Fresh base: `C:/Users/matri/.codex/tmp/ae-50afdedb`; 129,040,576 artifact bytes.
  All 1,100 source hashes/mtimes stayed fixed and staging was empty.
- `tmp/estate-finality-life-course-native-40y-segment13-audit-kind-v2.json`:
  **all 21 annual reports reproduce exactly**, with source bytes unchanged and
  no sidecars. The original failed auditor/report-difference receipt is retained.
- `tmp/estate-finality-life-course-native-40y-segment13-family-outcomes-kind-v2.json`:
  **seven partnerships, fourteen assents and sixteen rejected negative cases**.
  The original failed consent audit remains retained.
- `tmp/estate-finality-kind-history-native-current-and-proposal.json`:
  the complete current-day report equals the original reader, and the recomputed
  USD cash Gini/population equal the stored day-8,009 metrics
  (0.9022059460750805 and 16). The independent auditor also accepts a genuine
  same-day pending proposal before promotion and observes citizen/citizen/staff
  immediately before the proposal, promotion and later event. The fixture's
  bytes/mtime and native source were preserved. An initial fixture lookup used
  an untruncated pytest directory name; the corrected observed path and that
  probe failure are documented in the receipt.
- Compilation and whitespace checks passed. The isolated patch passes
  `git apply --check` but was not applied to the root. No persisted semantics,
  recorded metric, annual snapshot or native runtime was changed.

The validated kind-reader hash is
`0c8c397028b06c88cf30ad9b23df539e892915618f5cbbdb2d01797edd5e74a2`.
`tmp/estate-finality-historical-kind-integration.json` records baseline/new
hashes, the unapplied `tmp/estate-finality-historical-kind.patch`, and the
archive at `C:/Users/matri/.codex/tmp/ae-a1447feb/segment-013/kind-repair-v2`.
The earlier v1 implementation/receipts are also archived separately.

## Native continuation after recovery

`tmp/estate-finality-life-course-batch-14-18.py` is the explicit continuation
supervisor. It admits only the unchanged day-8,009 segment-13 source after the
corrected audit/current-day/compatibility receipts above. It freezes all 1,100
isolated reader source files, verifies their hashes and modification times
around every child, and pins the native harness plus the corrected report and
consent auditors and existing cohort auditor.

It may run at most five native segments, auditing every closed segment. It
stops on any child failure or native terminal/resource state; it does not
automatically recover a failure. The engine continues from the original root
with its original seed, horizon and budgets. Audit processes use the separate
frozen reader worktree. Root integration and full current CI remain pending.

Once started, authoritative progress is in
`tmp/estate-finality-life-course-batch-14-18-meta.json` and its actual process
handle. A prepared supervisor is not itself proof that it ran, and a live
segment is not a completed horizon. Full campaign recorded replay/export,
external departure, remaining W5 acceptance and W6–W9 remain open.

The documentation gate passed **22 tests / 0.35 s** (1.17 s including its
wrapper), with 1,098 source files unchanged during that check, fresh base
`C:/Users/matri/.codex/tmp/ae-bc5e5b94` and empty staging. Receipt prefix:
`tmp/estate-finality-historical-kind-docs`. This is focused local evidence;
complete integration and CI remain pending.
