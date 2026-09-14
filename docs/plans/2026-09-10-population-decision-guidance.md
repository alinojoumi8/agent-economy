# Population decision guidance and city return controls

Status: implemented and locally validated in the draft Semantics-21 boundary.
The original source inventory has **71 reviewed scopes and 79 remaining**.
Schema 25 and public maximum Semantics 20 remain unchanged; migration 26 is
still unregistered. This advances W5 without completing its admission matrix,
full CI, native acceptance or the later W6–W9 work.

## Changes and evidence

`ContextBuilder._legal_work` selected the first living lawyer even when that
person had departed or was underage. An available resident later in the same
ordering was hidden. Draft guidance now checks the shared professional
eligibility predicate, preserves the original ordering among eligible people,
and refuses corrupt residence evidence. An unpaid earned-wage claim remains
owned and unfiled if no eligible lawyer is available.

`LegalInstitution._is_lawyer` now includes adulthood in its draft predicate.
The formal representation workflow already checked adulthood and required
consent. The earlier helper result does **not** establish that formal filing
admitted underage counsel. A successful filing creates a representation request;
it does not automatically appoint the proposed lawyer. Original Semantics 1–20
selection and qualification remain intact.

`AgentRuntime._attach_civic_decision_context` serves both participant and external
decisions. It previously built and persisted local city attention for an outside
person's return command. Draft outside/minor decisions now leave this path before
context construction. Return commands continue through their existing execution
path. Invalid residence evidence raises before local context effects.

The changes preserve the ledger, retained financial ownership, historical replay
and the boundary between city projections and committed economic events.

## Seven-day city workflows

Two actual World cases exercise the same movement sequence with different
controls: an existing participant among 47 people, and one external first arrival
bringing the city to 48 people. All other genesis and movement behavior is real
scripted simulation behavior.

| Day | Recorded behavior |
| --- | --- |
| 1 | Initialize the city; admit the external person in the external case. |
| 2 | Execute the controlled departure proposal with ordinary local attention. |
| 4 | Depart; release local participation while preserving identity and wallets. |
| 5 | Execute the outside return proposal; restart after MORNING. |
| 7 | Return to the prior region; restart after NIGHT_CLOSE. |

Each source and replay reaches day 7. Outside days 4–6 have zero model calls,
attention contexts, time allocations and effective presence for the controlled
person. Both original wallet pointers and the population count remain intact.
The day-7 census reports one return and no new arrival. Both sources are closed,
replayed with the same two phase restarts, compared exactly, exported under
hash-contract-v8 and independently validated against their respective databases.
All provider calls are scripted and recorded provider cost is zero.

The 11 focused checks pass in **156.05 seconds**, retaining **97,506,647 bytes**.
Receipt: `tmp/estate-finality-population-decision-workflow-valid-meta.json`.
Initial test-setup failures are preserved separately: the first wage fixture used
the wrong accrual join and corrupted history before preparing its wage evidence;
the first expanded assertions incorrectly expected counsel appointment without
consent and a returned rejection instead of the existing filing exception.
These are test-setup corrections, not additional production defects.

The exact 16-suite population/Commons CI selection passes **201 tests** in
**769.16 seconds**, retaining **1,123,562,868 bytes**. The six-suite legal, wage,
civic and population-runtime compatibility batch passes **123 tests** in
**419.55 seconds**, retaining **630,622,433 bytes**. Both exited 0 with source
hashes and modification times unchanged, an empty staging area, and more than
the 40 GiB reserve. These two broad batches ran concurrently; their timings are
observations, not a scale benchmark. Both report the existing Starlette/httpx
deprecation warning. Local validation is Windows/Python 3.11; the configured
operating-system/Python matrix remains a separate requirement.

The terminal receipts use the prefix `tmp/estate-finality-population-decision-`
with `ci-meta.json` and `compatibility-meta.json`. Final documentation and
unreleased-version admission checks use `docs-final-meta.json`; the completed
implementation handoff verifies their outcome and the complete final source
manifest before recording this slice as progress.

## Native replay recovery and storage

The original native campaign and interrupted verifier remain unchanged. A
prospectively specified copy-only inspection recovered the interrupted replay's
database, WAL and SHM into a separate directory, verified source file hashes,
passed SQLite `quick_check`, and closed the recovered copy after WAL checkpoint.
It did not advance simulation or replay.

The recovered copy has **7,810 completed days**. Its active day is **7,811**, with
`FINALIZE` next. Its 3,700,178,944-byte database has SHA256
`ac74140a5c71ed7e389d52d56685fd39976f32d011956f367ef54b576292565e`.
This durable state is more precise than the last progress log at day 7,800;
neither is a full-prefix verification pass.

That log records at least 11,964.563 seconds used from the original 14,400-second
replay allowance, leaving **at most 2,435.437 seconds**. Another 3,546 days must
complete to reach the unchanged source endpoint, day 11,356. Extrapolating only
the latest logged 100-day rate would require over 10,000 seconds. This estimate
does not prove future throughput; completion within the original allowance has
not been established. No resumed or replacement trial was launched, and no
campaign, replay-stage or total verification budget was reset.

About 350.6 GB free was observed during this review, before the focused checks.
130 GB free is sufficient to resume development and bounded checks with the
existing 40 GiB reserve. Larger experiments retain their prospective admission
and resource limits. No cleanup or original artifact deletion occurred here.

Private evidence lives under `C:/Users/matri/.codex/tmp/ae-52da7cbc`:
`decision-context-inventory.json`, `decision-context-artifact-audit.json`,
`native-recovery-copy-protocol.json`, `native-recovery-copy-result.json` and
`native-recovery-state.json`. These local artifacts are not committed run data.

## Remaining work

Continue the original 79 remaining source scopes and mixed population admission
matrix. The shopping-cohort fallback, institutional work, merger target selection
and recovery employment target remain open; reads performed in this slice do
not count as completed dispositions. Preserve the original native horizon and
full-prefix verification requirements, remaining provider/workflow/usability
acceptance, full current-version CI, and W6 education/labor capacity, W7 production
and housing, W8 financial depth, and W9 validation/scale. Goods and equity price
discovery retain equal priority.
