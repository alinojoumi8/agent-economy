# Population registration candidate — pending admission

Current recovery status: [environment recovery](2026-09-11-environment-recovery.md)
supersedes the live status and available-evidence claims below. Cleanup removed
Ubuntu, test packages, candidate source copies and older proof records. The
native trial and Windows v4 continuation are terminal failures; surviving
records and the closed native world are preserved in the project's recovery
directory. Rebuilt source and fresh validation are required before admission.

An isolated candidate is prepared for the final population registration change.
The working project still uses schema 25 and supports Semantics 1–20. Do not
apply this candidate until the remaining W5 native and release requirements pass.
Goods and equity price discovery keep equal priority in the parent program.

## Change prepared for review

The [pending revision-2 patch](patches/2026-09-11-population-registration-v2.patch) registers
the existing migration 26, raises the storage ceiling to 26 and supports explicit
Semantics 21. The migration SQL, its checksum and all economic policies are
unchanged. Existing profiles and stored run configurations keep their declared
semantics. Replay continues to open its source without rewriting it.

Tests now exercise ordinary registration. Successful new-version worlds no
longer patch the supported version ceiling or install the migration SQL manually.
Domain fixtures verify the installed structures. A shared test helper creates
genuine schema-25 sources under a temporary legacy registry, closes them, then
restores ordinary registration. The upgrade under test opens a separate copy.

The test changes retain atomic failure and rollback, corruption rejection without
repair, future-version rejection, idempotent reopen, unchanged old rules and
accounts, exact recorded replay, and independent research export validation.
They also retain rejection of residence services against unupgraded old storage.

The candidate changes 15 files: three production files, eleven existing test files
and one new test helper. It is based on the captured dirty working tree, not just
the Git HEAD. A patch application check passed without changing the working tree.

## Current check status

The first Windows/Python 3.11 candidate attempt collected 694 cases from 44 test
files and stopped with **167 passed and one failed** after 973.46 pytest seconds.
Its complete supervised allowance consumed 985.328 seconds and retained
972,523,774 artifact bytes. The original failed attempt and
[revision-1 patch](patches/2026-09-11-population-registration-v1.patch) remain saved.

The failed test expected a database's entire research hash to survive a real
schema upgrade unchanged. Independent diagnosis shows that only `run_meta` and
`schema_migrations` changed: the schema marker becomes 26 and its receipt is
added. All other table hashes and earlier receipts remained identical; the
existing logical replay comparator also reports exact compatibility. Changing
the research hash implementation to conceal this metadata would be wrong.

Revision 2 corrects that test to verify both metadata changes explicitly while
requiring every other table to remain exact. It preserves the original source,
upgrades a copy, checks unchanged stored semantics and empty population tables,
and checks idempotent reopening and logical replay compatibility. Production
code, shared fixtures and every other test function are unchanged from revision
1; a comparison of syntax trees verifies the scope of the correction.

The new check first runs all 11 older-contract variants of the corrected test,
then the 516 previously unexecuted cases in two disjoint groups. The 167 complete
earlier passes are retained separately with their phase/source evidence. Any
combined coverage claim must reconcile those results with the 527 new cases;
it is not a fresh 694-test passing invocation. The corrected **11-case regression
passed in 110.29 pytest seconds** (111.61 seconds including its supervisor),
within its 120-second allowance. All setup, call and teardown phases passed;
there were no skipped selected cases. The first remaining group then reached
its 1,200-second limit with 200 completed passes, no reported test failure and
58 unproved cases. The other 258-case group had not started. The whole revision-2
supervisor consumed 1,321.25 seconds; its failed/limited receipt remains unchanged.

The intermediate audited complete count was 378 (167 earlier unaffected cases,
11 corrected variants and 200 newly completed cases). A separate continuation
ran only the remaining 316 cases in four disjoint groups of 79, on the unchanged
revision-2 source. Its 1,253.75-second cap uses the unused supervised allowance,
with five seconds held back; revision 2 plus this continuation must stay within
2,580 seconds. The four jobs have a shared 4 GiB process-tree memory ceiling and
separate temporary directories. No original failed attempt becomes passing.

**All 694 selected cases now have complete passing evidence.** Each continuation
group passed all 79 cases, including setup, call and teardown. The continuation
took 462.438 seconds; revision 2 plus continuation consumed 1,783.688 supervised
seconds of their original 2,580-second combined allowance. Peak combined memory
was 940,232,704 bytes and new continuation artifacts totalled 1,431,121,141 bytes.
An independent closure reconciles the disjoint 378 retained and 316 new cases
against the collected selection, verifies the unchanged source and earlier
receipts, and confirms that the known owned processes have exited. This is
combined Windows/Python 3.11 coverage, not a fresh single passing invocation.

The selection includes all population suites, migration foundations,
compatibility guards, older golden and source replay, metric compatibility and
documentation checks.

The earlier complete platform, hosted, dashboard and browser gates apply to their
recorded source snapshots. They are not a complete release verdict for this new
registration candidate. No registration or active simulation setting changed in
the working project.

Revision 1 retains its original 60-second collection, 1,800-second execution and
1,860-second combined limits. The separate corrected check declares 60 seconds
for collection, 120 seconds for the 11-case regression and 1,200 seconds for each
remaining group, with a 2,580-second combined cap. Each attempt has a 4 GiB
process-tree memory limit, 8 GiB artifact limit and 40 GiB free-disk reserve. The
failed attempt's time is not reset or hidden. Neither check runs a paid-provider
campaign or automatically retries. Supervisors control only their owned trees.

## Remaining execution order

1. The 694-case candidate selection is closed and independently reconciled.
   Retain its complete results, the original failed/limited attempts and the
   immutable source manifests. Full release/platform checks remain open.
2. Let the separately running 14,600-day native trial finish under its existing
   limits. Confirm the owned native writer and parent have exited before using
   the already prepared full replay/export/readback verifier. Preserve all
   earlier failed, interrupted and limited cases and their original budgets.
3. Reconcile the native life-course and complete verification evidence against
   W5. Native adulthood does not guarantee employment; report absent employment
   coverage without adding jobs or changing a declared run for a favorable result.
4. Check the patch and affected-file hashes against the current working tree.
   Inspect intervening code changes instead of overwriting them. Apply the saved
   patch only after admission permits registration. Keep profile semantics
   explicit and preserve old run configurations.
5. Complete the release checks justified by registration on the resulting source
   and required environments. They may run against the frozen candidate before
   main-tree admission, with source equivalence checked again at application.
   The bounded Windows candidate selection does not
   substitute for the full configured platform matrix. Reuse older evidence only
   where its source, selection and environment still apply.
6. Update operator and acceptance documentation from the verified result. Close
   W5 only when its complete contract is met, then implement
   [W6 education](2026-09-10-education-integration.md), followed by W7 production,
   housing and space, W8 banking and W9 validation/scale.

## Retained evidence

Revision-2 root: `C:\Users\matri\.codex\tmp\ae-cb1c7615`.
Preserved revision-1 root: `C:\Users\matri\.codex\tmp\ae-c4a341cc`.
Independent metadata diagnosis: `C:\Users\matri\.codex\tmp\ae-6a8e43d8\diagnosis.json`.

- `original-source.json` records the 1,193-file working-source baseline, hashes,
  modification times and sizes. The copy contains 23,716,218 source bytes.
- `candidate-source-v2.json` pins the corrected candidate, including its test helper.
- `candidate-registration-v2.patch` matches the pending patch saved with this
  plan. The migration checksum remains
  `f602de3b366ecf3d29d828128123f59431be4ce7b9024b0531e25648df8818d6`.
- `check-plan-v2.json` declares selections and resource limits before execution.
- `check-receipt-v2.json` records current or terminal supervised status.
- `carried-passes-v2.json` binds the 167 earlier complete passes to their original
  source and phase records. Those sources stay unchanged.
- Each stage retains its exact selection, collection, setup/call/teardown phases,
  actual process identity and complete log. The first attempt's corresponding
  `*-v1` records and independent `phase-audit-v1.json` remain in its original root.
- `phase-audit-v2.json` reconciles the disjoint selections, retained old passes,
  actual phase outcomes, source hashes and process identities. It distinguishes
  a live wait from terminal acceptance and requires all 694 cases before reporting
  combined selection completion. It cannot close native or full-release admission.

Operational pointers: `tmp/population-release-candidate-active.json` and
`tmp/native-hiring-active.json`. These identify current owned processes and exact
continuation commands; their stale status fields alone do not establish liveness.

Related records: [native diagnosis and pilot](2026-09-10-native-employment-diagnosis.md),
[completed project/hosted gates](2026-09-10-population-hosted-admission.md),
[migration admission](2026-09-10-population-migration-admission.md) and the
[execution log](2026-09-06-research-city-execution.md).

## Full test inventory and storage preparation

A fresh collection of the frozen revision-2 source finds 3,339 tests. This is
two more than the earlier complete-gate inventory: supported stored Semantics 21
and explicit rejection of residence services on unupgraded schema-25 storage.
The other identifier changes are renamed tests or the new future-version value.
All 694 candidate cases occur in the full inventory; 2,645 are outside that
selection. Applying the production partition function covers all 3,339 exactly
once in 16 groups: eleven of 209 and five of 208. Collection passed in 14.532
supervised seconds. It is not full test execution or a platform release pass.

The inventory and exact future partition files are retained under
`C:\Users\matri\.codex\tmp\ae-d9a8668b`, including
`full-release-selection-v2.json`. A read-only size audit found 51,542,950,748
logical bytes in the 16 earlier successful Windows/Python 3.11 test directories.
New full-matrix execution needs an explicit storage plan that preserves the
native verification allowance and the free-disk reserve.

A small storage probe marked only a new empty NTFS directory for compression,
then copied six existing test files and verified identical SHA-256 hashes.
Windows supports inheritance of this setting for new files; existing source
files were not changed. See [Microsoft's compact documentation](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/compact).

After cached writes settled, three actual SQLite samples occupied 5,435,392 bytes
for 16,740,352 logical bytes. Two already-compressed Parquet samples showed no
reduction. A zero-filled refusal fixture with a `.db` suffix was excluded from
the SQLite subtotal. These six opportunistic samples are not representative
enough to promise a full-run compression ratio or a performance improvement.

Probe records are under `C:\Users\matri\.codex\tmp\ae-5fc4f910`.
`copy-result.json` retains the initial immediate allocation observation;
`settled-copy-result.json` records the later measurements and fixture distinction.
The five-case live SQLite check passed: three upgrade rollback modes, old-rule
replay, and fresh Semantics-21 restart/replay/export, all in a new compressed test
directory. Pytest took 161.52 seconds (162.906 supervised seconds) within its
300-second allowance. All five cases passed every phase; the one reported
Starlette deprecation warning is retained. Ten closed databases totalled
49,291,264 logical bytes and 13,189,120 allocated bytes after writes settled.
Their compression attributes, original source/sample hashes and modification
times, and the absence of owned processes were verified in `closure.json`.
This is evidence for these Windows fixtures, not a full-run storage estimate,
Linux-filesystem check or full-platform release verdict. It changes no active
native or verification directory, and the completed probe should not be rerun.

The outstanding-case continuation is under
`C:\Users\matri\.codex\tmp\ae-1d5650a3`; its `plan.json`, `receipt.json`, exact
selections, per-group phase/process records and independent `closure.json`
establish the 694-case combined completion. The main
operational pointer is `tmp/population-candidate-continuation-active.json`.

## Remaining Windows/Python 3.11 checks

A separate prospective release check covers the 2,645 full-inventory cases
outside the verified 694-case selection, on the same frozen candidate and
Python 3.11.15 environment. It retains the completed selection without repeating
it. The production 16-way partition map is preserved, with already-proved cases
removed from each group. The resulting groups contain 163–167 cases each and
together cover every outstanding identifier exactly once.

Evidence root: `C:\Users\matri\.codex\tmp\ae-8f77a747`.
Its immutable `plan.json` declares two concurrent jobs, 1,800 seconds per group,
14,400 seconds combined, 4 GiB total process-tree memory, 60 GiB logical artifacts
and 16 GiB allocated storage. The existing completed candidate allowances are
unchanged; these are different, previously unchecked release cases. All new
pytest directories inherit compression from a new empty NTFS directory. No
older artifact or active simulation directory is recompressed or removed.

Admission measured 128,716,406,784 free bytes and 4,519,441,336 allocated bytes
in the active native world. It reserves the unconsumed part of the native
16 GiB source allowance, all 48 GiB for the three verification allocations,
40 GiB for normal free space and a further 2 GiB margin. The ongoing guard
refreshes the native allocation and disk reserve; it stops only its owned test
jobs if their limits fail. It never restarts a failed attempt or resets a clock.

The controller records exact selections, every setup/call/teardown result,
actual pytest process identities, resource observations and unchanged source
pins. Eight service-dependent hosted cases are expected to skip in this local
environment and remain separate admission work. Unexpected skips, failures or
missing phases cannot be counted as passing coverage. A completed Windows
inventory still does not close other platforms, native acceptance or W5.

Operational pointer: `tmp/population-candidate-windows-rest-active.json`.
This first broader attempt stopped after 57.89 supervised seconds: group 0 had
35 complete passes, one hosted skip and one failure; group 1 had two complete
passes before its owned process was stopped, leaving its next test unproved.
The other 14 groups did not start. Its `phase-audit.json` verifies these outcomes,
unchanged source/previous evidence and that all known owned processes have exited.

The failure was `test_changed_results_or_database_cannot_pass_verification`:
the isolated source copy had no Git metadata, and `research.artifacts.code_identity`
correctly refused to create unverifiable benchmark evidence. No engine or
research identity rule needs changing for this setup error. Review also found
that the broader test environment needed the already-installed pinned secret
scanner; the corrected environment clears provider and hosted-service credentials
and supplies that scanner explicitly, as the earlier full gate did.

A separate continuation is prepared under
`C:\Users\matri\.codex\tmp\ae-4015c984`. Its own Git metadata refers to the
original commit `ca6c1cf6e98356994e6bba1277fc9d03b2fa223d`; all 1,194 candidate
files remain byte-for-byte and modification-time identical to revision 2. The
private index describes the original HEAD, with candidate changes left unstaged.
The original project index is unchanged. The ordinary research identity function
now returns source-tree hash
`04447e022810c33f942d3661b609ad118c3b18e89964c0dcf5d1f96c591d9aad`.
The failed source copy and all its artifacts remain untouched.

The continuation retains 731 complete passes (694 plus 37) and the one hosted
skip, selecting only the remaining 2,607 cases. It first checks the failed
benchmark and two real scanner cases under a 120-second cap, then dispatches
the other 2,604 cases in the existing 16 groups. Its supervised allowance is
14,337.11 seconds: the unused original 14,400-second allowance less five seconds
of margin. Each affected group's remaining 1,800-second allowance is also charged
for its earlier execution and the complete preflight duration. Earlier artifact
usage is deducted from the original logical and allocated storage ceilings.
The native/verifier reserve, two-job concurrency and memory ceiling stay intact.

The three-case preflight passed all setup/call/teardown phases: 23.03 pytest
seconds, 25.187 supervised seconds, no skips and one retained Starlette
deprecation warning. The failed benchmark now verifies correctly under its
ordinary research-source identity check. Both scanner tests used the existing
hash-verified Gitleaks 8.30.1 binary. These three new passes bring independently
completed candidate coverage to 734, with one separately retained hosted skip.
The remaining 2,604 cases then started. This was partial full-suite coverage;
the subsequent monitor stop and its continuation are recorded below.

Operational pointer: `tmp/population-candidate-windows-continuation-active.json`.
Running status is not passing evidence; retain the new receipt and phase
outcomes without relabeling the original attempt.

## Windows file-counter race and bounded continuation

The continuation under `ae-4015c984` stopped after 290.187 supervised seconds
when its resource observer raised `WinError 123`. The original error did not
include a stack trace. The owned test trees were closed; no test assertion
failed in this invocation. In addition to the three preflight passes, groups
0 and 1 completed 27 and 55 cases respectively, with one additional hosted skip.
Its `phase-audit.json` reconciles **816 complete passes, two hosted skips and
2,521 unproved cases** across the retained candidate attempts. Both interrupted
cases still require complete execution. The earlier receipts remain failed.

A separate 20-second diagnostic under `ae-325d546c` reproduced the observer
exception during ordinary creation, renaming and deletion of new temporary
files. A stable-path probe alone had not reproduced it. Instrumented comparison
under `ae-78cd5912` captured the cause: resolving a disappearing Windows path
could already return an extended path, including a deletion-pending path, and
the old counter added the extended prefix again. This produced an invalid name.

The corrected observer preserves literal absolute paths and an existing extended
prefix. It does not resolve a file during counting. Windows may also briefly
deny access to deletion-pending files; reads retry that specific access/sharing
condition within a fixed bound. Persistent denial and unexpected errors still
stop the observer, and only files confirmed absent are omitted. A first observer
revision exposed this access-denial case; its failed probe and helper remain
under `ae-4cbdfd62` and the local tool history.

The final 20-second regression completed 17,216 scans through 14,320 file-change
cycles. The original counter produced 5,432 errors; the corrected counter
produced none. Closed-file counts matched the old implementation, eight stable
paths of 240–360 characters retained parity, an already-extended path remained
unchanged, and injected persistent-denial and unexpected-error cases still
raised errors. These checks change only the local test observer, not the engine,
source identity rules, candidate files or active native simulation.

The next continuation is under `C:\Users\matri\.codex\tmp\ae-596cb222` and
reuses the unchanged Git-aware source at `ae-4015c984\source`. Its immutable plan
retains 816 passes and two hosted skips, selecting only the remaining 2,521 cases
in the original 16-group map. Earlier supervised execution totals 348.077 seconds.
Another 60 seconds conservatively accounts for the three observer diagnostics,
including the first unsuccessful correction. With a five-second margin,
13,986.923 seconds remain from the original 14,400-second allowance.

The two interrupted groups have 1,393.141 and 1,391.954 seconds remaining. Groups
2 and 3 retain 1,774.813 seconds after the earlier scanner preflight; other
unstarted groups retain 1,800 seconds. For the observer exception that lacked a
returned duration, the entire prior continuation duration is charged to that
group. Prior artifacts and diagnostic storage are also deducted from the
original ceilings. No clock or storage allowance is reset. Two-job concurrency,
the 4 GiB memory limit and the complete native/verifier/free-space reserve remain.
New failures retain their stack trace and elapsed time as well as test phases.

Operational pointer: `tmp/population-candidate-windows-v3-active.json`. This
continuation still cannot close other platforms, native acceptance or W5.

## Checkpoint temporary-path failure on Windows

The `ae-596cb222` continuation stopped after 297.703 supervised seconds. Its
resource observer stayed healthy. Group 0 completed 78 cases before the peer
stop; group 1 completed three cases and failed the fresh-world policy operator
pause/resume/comparison case. The independent `phase-audit.json` reconciles
**897 complete passes, two hosted skips and 2,440 unproved cases** across all
retained candidate attempts. Interrupted cases still require complete execution.
The combined supervised charge, including the earlier observer diagnostics,
is 705.780 seconds. Original receipts retain their failed statuses.

The policy workflow completed all eight study cells, but each was excluded
because its recorded replay differed. Read-only examination of every source
and replay database found one extra replay event, `checkpoint_failed`; all other
comparison tables matched exactly. The checkpoint database itself existed, but
its atomic manifest writer could not create the longer temporary filename.
The nested test root made that temporary path 269 characters long. The extra
failure event remains scientifically relevant and must not be hidden by the
comparison or treated as a successful study result.

The separate diagnostic at `C:\Users\matri\.codex\tmp\ae-e6fa1c28\result.json`
records all eight comparisons, unchanged database hashes and modification times,
and the same temporary-file operation in new empty directories. Writes succeeded
at 245 and 259 characters and failed at 260 and 269 with the same missing-file
error. This machine therefore exhibits the ordinary Windows path boundary for
this operation. [Microsoft documents the path limit and long-path opt-in
requirements](https://learn.microsoft.com/en-us/windows/win32/fileio/maximum-file-path-limitation).
No Windows policy, registry setting or engine behavior was changed.

A separate continuation at `C:\Users\matri\.codex\tmp\ae-1e4cf4ae` uses a new
compressed directory with single-character test-group children. For the failed
workflow this reduces the temporary manifest path to 254 characters. The source
remains the unchanged Git-aware candidate at `ae-4015c984\source`; the original
deep-path failure and its study databases are retained. This is a local harness
correction, not proof of general long-path support. A later portability change
should check the complete checkpoint temporary-path budget before a run starts
and give an actionable path error without relaxing replay eligibility.

The continuation first runs the one failed operator workflow under a 180-second
cap, then selects the other 2,439 unproved cases. It retains the original group
mapping, two-job concurrency, memory/storage ceilings and native/verifier/free-
space reserve. Ten seconds conservatively covers the 1.2-second path diagnostic;
its artifacts are also deducted. The combined remaining allowance is 13,679.220
seconds including the original five-second margin. Groups 0 and 1 have 1,095.469
and 1,085.345 seconds left before the new regression; its actual duration is
charged again to group 1's remaining allowance. No budget is reset.

Operational pointer: `tmp/population-candidate-windows-v4-active.json`.
Only complete setup/call/teardown results count as new passing coverage. The
short-path regression passed: 128.88 pytest seconds and 131.203 supervised
seconds, with all three phases complete and its actual pytest process closed.
`regression-closure.json` independently verifies all eight exact replays across
130 comparison tables each, no checkpoint-failure events, two paired seeds for
each of goods and equities, unchanged source/database evidence and a maximum
254-character checkpoint temporary path. The test also completed its verified
export and original provider-allowance checks using the controlled local fixture.
The retained Starlette deprecation warning did not fail this case.

This brings independently proved candidate coverage to **898 complete passes
and two hosted skips**. The other 2,439 inventory cases are now running in the
remaining original groups; the regression duration reduces group 1's remaining
allowance to 954.142 seconds. Their results remain pending until terminal
receipts and complete phase records establish the outcome. This successful
short-path invocation does not relabel the original deep-path failure or close
the full Windows/platform/native release gates.
