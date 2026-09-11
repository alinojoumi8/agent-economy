# W5 cohort and native life-course validation — in progress

The household/estate implementation needs both controlled combined-loss cases
and a genuine multi-decade world. A short forced-death case does not establish
generational behavior. This work follows the
[W5 acceptance contract](2026-09-06-research-city-specs.md#s5-people-households-and-generations)
and [current succession checkpoint](2026-09-07-estate-assets-and-succession.md).

## Current terminal boundary — day 11,356

Batch 19–24 actually exited 0 after all three final audits passed. The native
writer stopped at its original cumulative time limit: `resource_stop`,
`total_wall_time`, 14,401.601 seconds. It reached 11,356 of the planned 14,600
daily ticks. This is a time-censored run, not a completed 40-year campaign;
the original plan and runtime budgets are unchanged.

The closed source contains 18 living people, 10 active households, seven births,
14 deaths/estates, 14 retirements and five native-born adults. Person 31 reached
adulthood at day 10,271. There are 13,039 goods executions, 169 equity executions
and 215,071 scripted calls with $0 provider spend. All 31 annual reports
reproduce; the cohort audit checks 11,357 census boundaries and 768 birthdays,
with no minor model calls, transition endowments or ledger/currency mismatches.
These counts do not establish productive second-generation behavior.

The standalone source is 5,002,399,744 bytes, SHA256
`984f6ab4d6ae6ba53422b0210560fa065643c8bf9932b4ce93fa83c9f7ca1dba`.
Final audits preserved its bytes and left no sidecars or active lock. The
native writer preserved all 1,099 pinned working files through closure.
Receipts are `tmp/estate-finality-life-course-batch-19-24-meta.json` and the
three segment-24 audit files recorded there.

The [full-prefix verification trial](2026-09-09-full-campaign-verification.md)
has started against that closed source. Its original replay runtime and
bounded comparison/export environment are separately frozen, allowing the
project's tested repairs to be integrated after native closure. Full-prefix
verification, the original 40-year horizon and complete CI remain distinct
open gates. The integrated history/replay/export changes passed 213 combined
tests; see the verification specification for the exact local scope.

## Prior closed boundary — day 9,636

Batch 14–18 exited 0 and paused at its five-segment boundary. The original
native source records 19 living people, 10 households, seven births, 13 deaths
and estates, 12 retirements, and four native-born people reaching adulthood.
The fourth is person 30 at day 9,588. No minors lack household assignment.
Goods have 11,547 executions and equities 148; 188,109 scripted calls cost $0.
These observations do not establish productive second-generation behavior.

All 26 stored annual household reports reproduce from the closed source with
the frozen corrected role reader. The independent cohort and family auditors
passed their ledger, age, membership, assent and rejection checks. The source
SHA256 is `fc6a1c01620ccb9cb9d72904345cddfa90688de4c378c426210437b180a243b3`.
Its 1,098 root source files retained hashes and mtimes, staging stayed empty,
and the writer left no SQLite sidecars. Closed artifacts occupied
4,401,533,580 bytes before final audit attachments.

The native runtime has consumed 10,816.64 of its original 14,400 seconds.
Another bounded batch may use the remaining allowance, preserving the same
seed, 14,600-day target, 600-second segments, 16 GiB artifact ceiling and
40 GiB disk reserve. A runtime or storage stop remains an incomplete horizon.
Versioned audit wrappers now admit clean resource stops and the completed
horizon without changing the source metadata. Four closure cases and 12
rejection cases passed; all three wrappers reproduced the prior day-9,636
economic proofs. The original audit helpers and receipts remain preserved.

Receipts: `tmp/estate-finality-life-course-batch-14-18-meta.json`, the three
`tmp/estate-finality-life-course-native-40y-segment18-*-v3.json` / `cohorts-v2.json`
audits, and `tmp/estate-finality-terminal-auditors-validation.json`.
Full horizon, recorded replay, export/readback and complete CI remain open.

## Native profile and initial measurement

`runs/life-course-rehearsal.yaml` extends the existing household decision
rehearsal, opts into Semantics 20, and restores the declared 0.05 annual birth
hazard. It keeps drift population, native policies, banks, firms and mutual
household assent. One tick is one day and a demographic year is 365 days.
Initial ages come from the ordinary recorded genesis cohort. This small profile
is an uncalibrated mechanics rehearsal, not an estimate of real population or
economic behavior. School enrollment/credentials remain W6 work.

The first native pilot completed 30 daily steps in **5.86 seconds**, beginning
with 25 agents and finishing with 18 households. It recorded 649 scripted calls
with zero provider cost. All 1,092 source files retained hashes and mtimes;
staging stayed empty. It observed no births or deaths in that short horizon.
The position reader took 3.1–7.5 ms at sampled ticks. Final artifacts were
18,280,197 bytes; the live database/WAL/log peak was 22,878,221 bytes. The last
ten days were profiled, so their timings include profiler overhead.

Receipt: `tmp/estate-finality-life-course-pilot-first-meta.json`; source:
`C:/Users/matri/.codex/tmp/ae-ecfbff4d/source.db`. Source, configuration,
operational log and call-profile evidence are preserved. This pilot is runtime
and storage evidence only; it does not satisfy multi-decade acceptance.

## One-year measurement and exact recorded replay

The native 365-day run completed in **104.20 seconds**, with 198,111,128 bytes of
closed artifacts. It recorded 8,580 scripted calls and zero provider cost. The
world retained 25 agents and 18 households, with no births or deaths during that
year. Goods recorded 898 sale events; equities recorded 78 executions, involving
390 shares. Two companies were bankrupt and one remained listed. These are
observations of the declared small profile, not calibration evidence.

The call table occupied about 171 MB. Repeated origin lookup was a measurable
cost: it scanned an agent's growing event history and sorted it. The physical
`ix_events_person_origin_key` partial index accelerates that exact query without
caching across transactions or changing migration checksums/canonical rows. The
isolated lookup probe was about nine times faster. The repeated native year took
**83.95 seconds**, with 198,115,224 bytes of closed artifacts. These wall times
include measurement overhead and profiling on the final ten days; they are not
a general performance guarantee. The final household read took about 20 ms.

The integrated regression passed **64 tests / 70.25 s**: keyed origin lookup,
rollback and reused IDs, existing-schema initialization, historical Semantics
1/2 replay, source lifecycle, golden replay and household positions. All 1,093
source files retained hashes/mtimes and staging stayed empty. Receipt prefix:
`tmp/estate-finality-origin-index-integrated`; base:
`C:/Users/matri/.codex/tmp/ae-9c4ab06b`.

The fresh native pair is not an exact recorded-response replay. Its decision
rows and economic tables match, but fresh call durations differ. The strict
replay comparator includes those durations in call references, so its pairwise
verdict is false for `llm_calls`, `agent_decisions` and `action_proposals`.
Separately, the frozen v7 hash comparison differs only in `run_meta`, whose
configuration records each run's different checkpoint directory. The first
verification harness stopped on that metadata difference; its failed receipt
is preserved. No comparator or hash rule was relaxed.

An actual recorded-response replay of the pre-index source then completed all
365 days under the indexed implementation and passed the existing strict
comparison **exactly**, with no differing tables. Fresh scripted callbacks were
forbidden. Both original database byte hashes remained unchanged; all 1,093
source files retained hashes/mtimes and staging stayed empty. The full receipt
took 169.25 seconds, including preliminary hashes and final comparison; replay
artifacts occupied 198,146,405 bytes. Prefix:
`tmp/estate-finality-life-course-recorded-year-v2`; base:
`C:/Users/matri/.codex/tmp/ae-47d99eda`. Original source:
`C:/Users/matri/.codex/tmp/ae-c3a23cce/source.db`; indexed fresh replication:
`C:/Users/matri/.codex/tmp/ae-fad8b195/source.db`.

## Declared native campaign

The next campaign fixes **seed 1 and 14,600 ordinary daily ticks (40 years)**
before genesis. It uses the unchanged life-course profile, its ordinary genesis
ages and native scripted policies. No forced deaths, age acceleration or extra
births are introduced. It is an uncalibrated mechanics study; absence of an
expected demographic event must be reported rather than manufactured.

The execution harness is `tmp/estate-finality-life-course-campaign.py`. A copy
is preserved with the campaign plan and evidence. Its limits are:

- 16 GiB for the growing source, logs, annual household reports and receipts;
  no periodic database checkpoint copies.
- A 40 GiB free-space floor. Initial admission requires 104 GiB free, reserving
  four 16 GiB allocations for source, replay, private source copy and export in
  addition to the floor. Actual future verification must recheck free space.
- Ten-minute segments and a cumulative four-hour native execution allowance.
  Checks occur at day boundaries, so one completed step can overshoot a limit.
- Scripted routes only and zero provider cost. The positive configured governor
  denominator is not permission to spend. New call rows are audited incrementally.

Each segment appends daily census, demographic, estate, goods/equity execution,
storage and runtime observations. Annual household reports keep currencies and
valuation types separate. Complete databases and all failed/paused receipts are
retained. A clean segment pause closes the database and records its byte hash.
Resume verifies that hash, the fixed plan, Python runtime, simulation sources
and harness before using the normal `open_run` resume/PRNG restoration path.
Concurrent attempts and failed/interrupted sources are rejected; this harness
does not claim crash recovery. Documentation and observer UI may change between
closed segments; runtime/config/data remain pinned. No source/docs/build edits
are allowed during an active segment.

The three-day harness smoke paused after day 1, resumed through day 3 and then
passed a separate exact recorded replay, leaving source bytes unchanged. Both
segments preserved all 1,093 source files and empty staging. Source base:
`C:/Users/matri/.codex/tmp/ae-7f2122cf`; replay base:
`C:/Users/matri/.codex/tmp/ae-98f76f68`; receipts:
`tmp/estate-finality-life-course-segment-smoke-meta.json` and
`tmp/estate-finality-life-course-segment-smoke-replay.json`. The smoke validates
the clean segment boundary, not forty-year behavior or crash recovery.

### First campaign segment: closed pause at day 1,648

The declared campaign started from fresh genesis and completed **1,648 native
days (about 4.5 years)** in 600.58 seconds before its planned segment pause.
Population reconciles as 25 opening people + 3 births - 1 death = 27 living
people, in 18 households. Two retirement events and one estate were recorded;
there were no unassigned minors at the boundary. The first death occurred on
day 513. Children were born on days 993, 1,188 and 1,486. Their ages at the pause
were 1, 1 and 0; each birth recorded zero endowment, and each child's current
wallet was still zero. None has reached adulthood yet.

Goods recorded 2,974 executions through day 1,648. Equities recorded 85
executions for 425 shares; their last execution was day 1,172. The later lack
of equity trading is part of the evidence, not a new observed price. All
37,865 calls were scripted and recorded zero cost. Closed segment artifacts
occupied 873,330,844 bytes, before the small follow-up audit receipt. The pause
left 161,351,729,152 bytes free. All 1,093 source files retained hashes/mtimes;
staging was empty, and the process exited successfully.

The closed-source audit reconciled all 1,649 daily census rows and reproduced
all four saved annual household reports. Historical reads took 26-44 ms in
that check. Its first comparison incorrectly compared integer Python map keys
with JSON string keys; comparing both reports in their persisted JSON format
passed. No financial value or history rule was changed. The source database
retained its byte hash throughout these reads. The audit does not replace
the full campaign's outstanding recorded replay and export.

Campaign base: `C:/Users/matri/.codex/tmp/ae-a1447feb`; source:
`world/native-life-course-seed-1.db` within that base. Plan, harness copy,
daily observations, annual reports and per-segment source/receipt records
are preserved there. Latest status:
`tmp/estate-finality-life-course-native-40y-meta.json`; closed audit:
`tmp/estate-finality-life-course-native-40y-segment1-audit.json`.

Resume the same declared campaign, checking its clean pause rather than
starting another source:

```powershell
& .venv\Scripts\python.exe -X utf8 -u tmp\estate-finality-life-course-campaign.py resume estate-finality-life-course-native-40y
```

The 14,600-day target is still open. Keep the simulation sources and harness
pinned between segments; retain the same cumulative time and storage limits.

### Second segment: closed pause at day 2,555

The same source resumed to **day 2,555 (seven years)**, then closed at its
ten-minute segment boundary. This segment took 600.97 seconds; cumulative
native time is 1,201.55 seconds. Its 58,405 calls were all scripted with zero
recorded cost. Population reconciles as 25 + 4 births - 2 deaths = 27 living
people, in 17 households. Three retirement events and two estates have been
recorded. The fourth child was born on day 1,682. Children are now 4, 3, 2 and
2 years old; none has reached school age or adulthood. Both deceased people
were 84 at their deaths, on days 513 and 2,441.

Goods have 4,010 executions through the current day. Equity executions remain
85, last observed on day 1,172; the absence of later trading is retained.
Closed artifacts occupied 1,355,257,496 bytes before the small audit receipt,
with 158,873,755,648 bytes free. All 1,093 source files retained hashes/mtimes
and staging stayed empty. The closed audit reconciled all 2,556 census rows
and reproduced all seven annual household reports, taking 21-62 ms per read.
Source bytes remained unchanged. Receipt:
`tmp/estate-finality-life-course-native-40y-segment2-audit.json`.

The initial resume attempt found an empty WAL left by the earlier read-only
audit and stopped before opening the world. SQLite closed that empty journal
with a `(0, 0, 0)` checkpoint result, preserving the exact database byte hash;
receipt: `segment-001/empty-wal-close.json` inside the campaign base. There was
no data-bearing journal to apply or discard. Closed audits now use the existing
`open_read_only_connection(require_closed=True)` through
`Store.from_read_only_connection`; the second audit left no WAL/SHM/journal
sidecars. Use this closed-source reader for future segment audits.

### Third segment: first native school-age transition

The same campaign reached a clean pause at **day 3,377 (about 9.25 years)**.
This segment took 600.74 seconds; cumulative native time is 1,802.29 seconds.
Five births and four deaths leave 26 living people in 16 households, with four
retirement events and four estates. No minor lacks a recorded guardian. The
fifth child was born on day 3,018. The two new deaths occurred on days 3,222
(age 64) and 3,238 (age 73). Children remain alive at ages 6, 5, 5, 4 and 0.

The first newborn, agent 26, reached the recorded sixth birthday on day 3,183
and is now `school_age`. This verifies the native age/stage transition, not
school enrollment, attendance or credentials; those remain W6. No newborn
has reached adulthood yet.

All 75,918 calls were scripted and cost zero. Goods have 4,833 executions
through day 3,377. Equities still have 85 executions/425 shares, last traded
on day 1,172. Closed artifacts occupied 1,762,236,351 bytes before the audit
receipt, leaving 156,842,774,528 bytes free. The call table occupies
1,536,090,112 bytes. The fixed 16 GiB artifact cap, 40 GiB free reserve,
zero paid-provider allowance and no periodic checkpoint-copy policy remain.

All 1,094 source files retained hashes/mtimes during the segment; staging
stayed empty. The closed audit reconciled all 3,378 census rows and reproduced
all nine annual household reports in 26-95 ms each. Source bytes stayed
unchanged, with no WAL/SHM/journal sidecars. Source SHA-256:
`a4e9bf6d8f6e31fbb5f6ce8c44bdda3a2d5b6cd1132c0a3bd0f70af379f7e14d`.
Receipt: `tmp/estate-finality-life-course-native-40y-segment3-audit.json`.

### Fourth segment: closed pause at day 4,092

The unchanged source reached **day 4,092 (about 11.2 years)** and paused after
600.91 seconds, for 2,403.20 cumulative native seconds. Six births and four deaths
leave 27 living people in 16 households, with five retirements and four estates.
The sixth child was born on day 3,701. Children are ages 8, 7, 7, 6, 2 and 1;
four have crossed the native school-age boundary, and none is an adult.

All 89,809 calls were scripted and cost zero. Goods recorded 5,515 executions
through day 4,092. Equities remain at 85 executions/425 shares, last traded on
day 1,172. Closed artifacts occupied 2,086,568,741 bytes before the audit receipt,
leaving 155,596,472,320 bytes free. The call table occupies 1,814,548,480 bytes.
The original source, plan, runtime and storage limits were retained. All 1,095
source files kept hashes/mtimes and staging stayed empty throughout the segment.

The closed audit reconciled all 4,093 census rows and reproduced all eleven
annual household reports in 25-100 ms each. It verified all four recorded sixth
birthdays. Source bytes stayed unchanged and no sidecars were created. SHA-256:
`f5c40f75c38fc992477fe4f74c8c6c9e88d4ac6326cd8f7b2db5cceee12cc401`.
Receipt: `tmp/estate-finality-life-course-native-40y-segment4-audit.json`.

## Fifth segment and storage admission check

The same fixed campaign closed successfully at **day 4,701 / about 12.9 years**.
This segment took **600.93 seconds**, bringing cumulative native time to
**3,004.14 seconds**. Six births and four deaths still leave 27 living people
in 16 households, with five retirements, four estates and no unassigned minors.
The native-born children are ages 10, 9, 8, 8, 4 and 2. Native-born adulthood
remains unobserved; the earliest possible eighteenth birthday is day 7,563.

All **101,638 calls were scripted with zero provider cost**. Goods recorded
6,080 executions through day 4,701. Equities retain 85 executions / 425 shares,
last traded on day 1,172; that inactive interval remains part of the evidence.
The closed audit reconciled all **4,702 census rows**, reproduced all twelve
annual household reports in **27–104 ms each**, and verified the four recorded
sixth birthdays. These ages do not establish enrollment or credentials.

The process exited with code zero. All 1,096 source files retained their hashes
and mtimes, staging stayed empty, and the plan and harness remained unchanged.
The closed database hash is
`f3bef89a29de05fc9d283fe6f53184723a399ce12c78930e5216fc62db9807d5`.
The audit preserved those source bytes and created no SQLite sidecars. Receipt:
`tmp/estate-finality-life-course-native-40y-segment5-audit.json`.

Closed artifacts occupied **2,363,369,294 bytes**. The subsequent storage check
found **154,189,045,760 bytes free / about 143.6 GiB**, above the original
104 GiB initial admission requirement. Even 130 decimal GB is about 121.1 GiB
and meets that requirement. The original 16 GiB campaign allowance and 40 GiB
free-space floor remain in force; no further cleanup was needed for this stage.
The last 500 daily observations imply about **6.87 decimal GB** of campaign
artifacts at the target if that growth rate persists. This is an estimate,
not a measurement of the final source, replay, private copy or export.

Mean step time rose from **0.291 seconds** on days 1–1,000 to **0.964 seconds**
on days 4,001–4,701; the latest 500 steps averaged **0.986 seconds**. To finish
the remaining 9,899 ticks within the declared four-hour native budget, all
remaining work must average at most **1.151 seconds per tick**. Continued
slowdown could therefore exhaust the time budget before the target despite
ample storage. No responsible component has been established by these timing
observations. Keep the original limits fixed and preserve a resource-stop
outcome if one occurs. Growth receipt:
`tmp/estate-finality-life-course-native-40y-segment5-growth.json`.

## Sixth segment and independent cohort-history audit

The unchanged campaign closed at **day 5,226 / about 14.3 years**, after
**600.42 seconds** in this segment and **3,604.56 cumulative native seconds**.
Six births and four deaths leave 27 living people in 16 households. There are
now seven retirement events and four estates. The six native-born children are
ages **11, 11, 10, 9, 6 and 4**; the fifth sixth birthday occurred on day 5,208.
No native-born adulthood has occurred, and school-age status does not establish
enrollment or credentials.

All **112,106 calls were scripted and cost zero**. Goods reached 6,606 executions
through day 5,226; equities remain at 85 executions / 425 shares, last traded on
day 1,172. The process exited with code zero, all 1,096 source files retained
hashes/mtimes, and staging stayed empty. Closed artifacts occupied
**2,610,816,868 bytes**, with **153,348,292,608 bytes free** at closure. The
closed database hash is
`aa98de38c89e9833903b2f1f01ebe80a5597259846dc97573691490c013e60bb`.
All fourteen annual reports reproduced in 26–114 ms each, and all 5,227 census
rows reconcile. Receipt:
`tmp/estate-finality-life-course-native-40y-segment6-audit.json`.

The new local audit helper `tmp/estate-finality-life-course-audit-cohorts.py`
checks the complete recorded history, not only the latest population counts.
It verified all **31 permanent people and 393 birthdays**, continuous and
non-overlapping membership intervals, age-appropriate membership roles,
guardianship age/life/co-residence, parent identity and ancestry, household
formation/dissolution, partnership co-residence and every daily care-gap and
legacy-dependent count. The history contains 38 membership intervals, six
guardianship intervals, seven partnerships with two ended, and 25 households
with nine dissolved. No minor had a model call. Birth/adulthood transitions had
no positive population-inflow ledger entry. Every account matched its journal,
all transactions balanced, and account/transaction currencies matched.

That audit passed in **5.16 seconds**, preserving source bytes and creating no
SQLite sidecars. Six deliberately corrupted in-memory inputs were rejected:
wrong birthday age, missing initial membership day, negative guardianship
interval, birth endowment, child model call and population funding on a
transition. Receipt:
`tmp/estate-finality-life-course-native-40y-segment6-cohorts.json`.
Its exact initial verifier is archived as
`C:/Users/matri/.codex/tmp/ae-a1447feb/segment-006/cohort-audit-initial.py`.

The verifier was then extended to report all adulthood transitions and check
model calls for every recorded minor, including declared genesis cohorts.
It passed both existing 22-day age-boundary recorded-replay outputs, recognizing
agent 20's day-20 adulthood, and rejected an invented 100-cent adulthood
endowment in each. It also rechecked the native source and rejected a premature
adulthood event. The older fixtures' primary databases have zero-byte WAL and
32 KiB SHM sidecars; the strict reader refused those primary files. The checks
used their standalone replay outputs and verified that every original database
and sidecar retained its bytes and mtime. Receipt:
`tmp/estate-finality-cohort-auditor-age-boundaries-v2.json`. This supersedes an
earlier receipt's description of SHM size; its verification results were unchanged.

These are verifier checks against completed controlled fixtures. They do not
establish native-born adulthood, the full 40-year horizon, partnership assent
content, full estate-disposition coverage or the campaign's final replay/export.
Those remain required, along with the original fixed resource limits.

## Combined owner, guardian and successor losses

`tests/test_semantics20_combined_cohorts.py` adds one four-day world-loop stress.
Two existing founders form a household through mutual assent. Two children are
born through scheduled-birth mechanics on day 1. One parent and an independent
original owner die together on day 2; the surviving parent, also the independent
owner's heir, dies on day 3. On day 4 an independently funded, accepted supplier
contract pays 1,800 cents to the first estate. These are declared losses and
births; both children remain infants, so this is not natural generational aging.

The receipt pays the first estate's 1,000-cent loan claim, then splits its
800-cent residual equally. One child receives 400 cents. The other 400 passes
through the deceased parent's estate and reduces its 500-cent recovery claim
to 100; the second child receives no cash and acquires no personal loan.
The bank's written-off loan asset remains distinct from its unpaid estate
recovery claim. Of the first issuer's 11 shares, five reach the first child
and six remain with the indebted successor's estate. The independent issuer's
13 shares also remain there. Both original issuers and all ownership quantities
stay distinct; no asset is copied into several heirs' additive totals.

The test checks simultaneous death/census events, original deceased identities,
zero birth endowments, guardian succession and the later explicit care gap,
unique instrument keys, exact one-half conditional fractions through both
estates, creditor order, and immutable historical reports. Daily restarts
preserve authoritative state. Export validation and exact recorded replay pass,
without fresh scripted callbacks or changes to source database bytes.

The first fixture run used the wrong account-column name and was corrected.
The second initially asserted an unpaid claim against the bank's already
written-off loan asset; the assertion now checks the actual estate recovery
claim. No production behavior was changed to obtain a pass. Final verification
passed **1 test / 69.76 s**, with all 1,094 source files retaining hashes/mtimes
and empty staging. Prefix: `tmp/estate-finality-combined-cohort-third`; base:
`C:/Users/matri/.codex/tmp/ae-4faca43a`; artifacts: 9,511,868 bytes. The existing
Starlette/httpx deprecation warning remained.

The case now runs both with USD obligations alone and with an additional
70-cent EUR loan to the first deceased owner. The dollar receipt follows the
same dollar waterfall. The euro estate recovery claim stays unpaid at 70,
the EUR bank equity charge remains -70, and no euro receipt or currency
conversion is invented. This exercises currency-specific creditor boundaries
through the combined world loop, daily restarts, historical reports, export
and exact replay. It does not test a subsequent foreign-currency receipt.

Both variants passed **2 tests / 125.00 s** (125.94 s including the wrapper).
All 1,094 source files retained hashes/mtimes and staging stayed empty.
Prefix: `tmp/estate-finality-combined-currency-first`; base:
`C:/Users/matri/.codex/tmp/ae-0acffac3`; artifacts: 19,089,152 bytes.
No production code changed. The existing Starlette/httpx warning remained.
This controlled four-day stress still does not establish natural aging.

### Combined property and creditor coverage

The third variant adds two original personal projects to the same USD/EUR
world-loop stress. Both are declared at genesis through actual proposal,
permit, funding and work actions. The first owner's unfinished project has
600 cents from that owner and 600 from the independent payer. The other owner
funds a 1,200-cent home and completes its declared two work units. These are
small mechanics fixtures, not evidence of independently emergent construction.

On day 2 both original owners die. The unfinished project's interest stays in
the indebted first estate; the completed home reaches the surviving guardian.
When that guardian dies on day 3, the completed home enters that person's
estate and remains subject to its creditors. The day-4 dollar receipt clears
the first estate's dollar claim and releases the unfinished title: one half
reaches the first infant, while the other half enters the indebted successor's
estate. That estate retains its full interest in the completed home. The
70-cent EUR claim is still separate under the currency-specific custody policy.

The test preserves both original project/initiator identities, all three
funding records and their original accounts/transactions, and the unfinished
project's unspent refund pool. Rights sum exactly to one for each project.
The dead guardian loses authority; infants are not permitted to manage work.
Household reports retain distinct unpriced instruments, with no cost-based
market valuation or duplicated title. Historical reports, estate and time/ledger
invariants, export and exact recorded replay pass with the other assertions.

All three variants passed **3 tests / 187.48 s** (188.41 s including the wrapper).
All 1,095 source files retained hashes/mtimes and staging stayed empty. Prefix:
`tmp/estate-finality-combined-property-first`; base:
`C:/Users/matri/.codex/tmp/ae-88a7e671`; artifacts: 29,182,961 bytes. Production
code was unchanged, and the existing Starlette/httpx warning remained.

## Declared genesis age, custody and migration boundaries

`tests/test_semantics20_age_boundaries.py` runs two 22-day world-loop cases.
They declare a 17-year-old ward and a 64-year-old person at genesis, using the
ordinary recorded age basis. Their birthdays occur on days 20 and 22. These
are synthetic starting cohorts; no newborn is aged through years in a few
ticks. A second region and its permit clerk exist before person origins and
the initial census are recorded. Existing citizens follow the declared stress
policy, so this case does not claim native policy behavior.

The ward's guardian/company owner dies on day 19 or 20. The household's work
move is proposed two days before that death and accepted by the other adult
one day before it, through actual scripted action execution. The changed
household cancels the agreed move before settlement; no member migrates under
the old assent. The ward receives all 11 issuer shares through the disclosed
strongest-social-tie fallback. No fabricated parent/child relation is used.
The original founder identity and total issued shares stay unchanged.

When the death occurs on day 19, the other household adult temporarily operates
the minor's company. On day 20, the ward becomes an adult through normal daily
aging, the guardianship ends, and operating authority passes to the shareholder.
The same-day death/adulthood case reaches the same committed ownership and
authority boundaries. The former guardian receives no shares and loses control.
The new adult can set the company's goods quote on day 21; this is an authority
check, not an observed market execution. Adulthood grants no cash endowment or
personal loan. The other declared person retires at 65 on day 22.

Both cases verify authoritative state across daily restarts, all prior household
reports, share conservation, estate/household/ledger invariants, export validation
and exact recorded replay. Replay consumes the original responses, and source
database bytes remain unchanged. The first setup attempt created the regional
clerk after the genesis census; historical-origin validation rejected it. The
fixture now creates that clerk before registration/census. No production
behavior was changed to obtain a pass.

Final verification passed **2 tests / 573.99 s** (575.00 s including the wrapper).
All 1,095 source files retained hashes/mtimes and staging stayed empty. Prefix:
`tmp/estate-finality-age-boundaries-second`; base:
`C:/Users/matri/.codex/tmp/ae-1a5cbc4d`; artifacts: 62,713,509 bytes. The existing
Starlette/httpx deprecation warning remained. These controlled cases complement
the native campaign. At that earlier checkpoint, native adulthood and the
declared horizon had not yet been reached; the later evidence follows below.

## Twenty-one-year pause and first native adulthood

The fixed campaign continued through six more ten-minute segments under the
unchanged seed, sources, 16 GiB artifact cap, 40 GiB reserve and cumulative
four-hour native allowance. The supervisor exited **0** at a clean review pause
on day **7,667**, after observing the first native-born adult. This is about
21 simulated years; the declared 14,600-day horizon remains unfinished.

Each segment closed and passed the historical-report/census audit and the
independent cohort audit before the next one started. No pinned source,
documentation, build or staging changes occurred during those segments.

| Segment | Day | Births | Deaths | Native adulthood transitions | Annual reports | Goods executions | Equity executions |
|---|---|---|---|---|---|---|---|
| 7 | 5699 | 7 | 5 | 0 | 15 | 7116 | 85 |
| 8 | 6136 | 7 | 6 | 0 | 16 | 7575 | 89 |
| 9 | 6546 | 7 | 6 | 0 | 17 | 7984 | 93 |
| 10 | 6933 | 7 | 6 | 0 | 18 | 8372 | 97 |
| 11 | 7304 | 7 | 7 | 0 | 20 | 8742 | 100 |
| 12 | 7667 | 7 | 8 | 1 | 21 | 9098 | 104 |

The final audit covers 32 recorded people, 553 birthdays, 7,668 daily census
rows, 40 membership intervals, seven guardianship intervals, seven partnerships
(two ended), and 25 households (eleven dissolved). At the pause, 24 people live
in fourteen households, with one unassigned minor. All 21 annual financial
reports reproduce from the closed source. Ledger/account and currency checks
pass; no recorded minor model calls or birth/adulthood population endowments
were found. The seven deliberately corrupted cohort inputs are still rejected.

Person 26 was born on day 993 and became eighteen on day 7,563, with all eighteen
birthdays recorded. Membership changed from child to adult and guardianship
ended through the normal nightly transition. The adulthood event gives zero
endowment. Native decisions begin on day 7,564: 75 accepted `do_nothing` actions
and fifteen memory calls were recorded by day 7,667, all scripted and costing
zero. This person remains a job seeker with no employer or adult time
allocations in the observed interval. The transition works; an economically
active second generation is not established by it. Investigate the recorded
opportunities, policy and future education capabilities before changing behavior.
Do not manufacture a job, income or starting portfolio for an acceptance result.

### Household consent and native care gaps

An additional read-only auditor verifies all seven actual partnership proposals,
their fourteen adult acceptances, the recorded household-member snapshots, and
proposal/assent/formation event linkage and timing. There are no ambiguous
within-tick membership boundaries in these seven records. Eight corrupted input
cases are rejected, including consistently removing both an acceptance and its
event, and consistently recording a decline in both places. A six-partnership
three-day fixture also passes. This checks recorded consent; it does not
reconstruct changing historical social-tie weights or replace full replay.

Guardian 2 died of recorded illness on day 5,871. Children 27 and 28 remained
in household 2 without another adult. Child 27 has 1,797 uncovered care days
through day 7,667 (215,640 required minutes, zero delivered). Child 28 has 1,602
such days through day 7,472 (192,240 required minutes, zero delivered), followed
by a recorded illness death at age sixteen on day 7,473. Identity, membership
end, and estate 8 remain recorded; the child was not deleted.

These observations must not be presented as evidence that missing care caused
the death. `Lifecycle._health_transition` uses the declared age/health hazards
and does not consume recorded care or nutrition inputs. A causal relationship
would require an explicit later model contract and validation. Likewise,
inherited cash does not establish delivered care: child 27 still has 17,500 USD
cents in a personally owned wallet. Household, personal and estate assets stay
distinct in the selected-day reports.

The profile remains an uncalibrated mechanics rehearsal with native scripted
policies. Seven children have crossed their sixth birthdays, but school-age
eligibility is not enrollment, attendance or a credential. Those remain W6.
Goods last traded on day 7,667; the 104 equity executions involved 520 shares,
with the latest at day 7,641. Equity trading resumed during segment 8 after the
earlier inactive interval. Counts and inactivity are observations, not proof of
efficient price discovery or real-world validity.

### Evidence and next verification

- Supervisor: `tmp/estate-finality-life-course-batch-7-12-meta.json`, terminal
  `review_pause`, exit 0, no active child, stop reason `native_adulthood_observed`.
- Per-segment receipts: `tmp/estate-finality-life-course-native-40y-segmentN-audit.json`
  and `-cohorts.json`, for N = 7 through 12.
- Native consent/care/adult-action receipt:
  `tmp/estate-finality-life-course-native-40y-segment12-family-outcomes.json`;
  helper `tmp/estate-finality-life-course-audit-family-outcomes.py`.
- Small fixture: `tmp/estate-finality-household-assent-pilot-copy.json` and
  `C:/Users/matri/.codex/tmp/ae-c8505202/assent-audit-pilot-v2.json`. Original
  database/WAL/SHM were preserved. The first inspection query incorrectly assumed
  an `id` column on the composite-key assent table; it was corrected on the
  private copy before validation. No production code changed.
- Closed source SHA-256:
  `5d24c121fa05d3ee0367e9a7c3424c738fdd7a6e33464fa3e75164f4b8a01331`.
  Audits preserve its bytes/mtime and create no sidecars.

Native execution has consumed 7,209.10 seconds of the original 14,400-second
allowance. Closed campaign artifacts occupied 3,654,987,141 bytes before audit
attachments. Disk remains above admission and reserve thresholds, while growing
step time may limit the horizon. The
[bounded replay/export specification](2026-09-09-campaign-replay-and-export.md)
records the inspected memory bottlenecks and exactness gates. Its implementation
and full-campaign verification remain pending; no memory failure is being claimed.

## Required remaining evidence

1. Finish the [W5 acceptance audit](2026-09-09-w5-acceptance-audit.md). The combined USD/EUR
   owner/guardian/successor cases and current-semantics age/death/migration
   boundaries above now pass. Preserve those explicit limits alongside the
   earlier focused estate cases; they do not establish arbitrary generations
   or subsequent foreign-currency recovery by themselves. The additional
   combined property variant now covers two original projects and the later
   successor's creditors. External-world departure accounting remains a
   separate uncovered population boundary in the original S5 contract.
2. Finish the declared 14,600-day native campaign with its original parameters,
   seed and limits. The day-7,667 pause supplies native birth-to-adulthood,
   retirement/death and household-history evidence; it does not complete the
   fixed horizon or every estate-disposition check. Preserve the histories,
   adverse outcomes and absence of arrival endowments at birth/adulthood.
3. Report observed goods and equity executions equally, including missing or
   inactive markets. Separate signed cash, face claims, observed marks and
   unpriced rights; do not invent cohort net wealth.
4. Record runtime, table/database growth, zero provider spend, checkpoint policy,
   source fingerprint, source integrity and exact replay/export evidence.
   Calibrated claims, larger populations and W6–W9 remain separate gates.

These acceptance items remain open. Do not mark W5 or the full goal complete
from the profiling pilots, the controlled stress cases, or these campaign segments.

## Documentation verification for the day-7,667 pause

After the supervisor and both native audits exited, the documentation gate ran:
`python -m pytest -v --tb=short --maxfail=3 tests/test_documentation.py`, through
the bounded wrapper with fresh base `C:/Users/matri/.codex/tmp/ae-b197531a`.
It passed **22 tests / 0.38 s** (1.31 s including the wrapper). All 1,097 source
files retained hashes/mtimes during that run, and staging remained empty.
Receipt prefix: `tmp/estate-finality-native-segment12-docs`. These are focused
documentation checks, not full CI or completion of the remaining W5 gates.

## Day 8,009: audit failure preserved, second native adulthood verified

Segment 13 completed normally after 600.654 seconds, at day 8,009. Cumulative
native wall time is 7,809.754 of the original 14,400 seconds. Native artifacts
occupied 3,795,990,700 bytes at closure; the original 16 GiB cap and 40 GiB
reserve were not reached. All 1,097 source files retained hashes/mtimes during
the segment, with the original runtime fingerprint and plan-file hash.

The batch supervisor then exited 1 at `closed_audit_13` and started no further
segment. Re-reading the year-one household report failed equality. A diagnostic
compared all 21 annual reports: each now omits person 11's historical citizen
cash after their promotion to permit clerk on day 7,827. Only five
`cash_distribution/USD` fields differ in each report. The independent consent
auditor also fails because it tests old proposals using today's person kind.
See the [specific diagnosis and repair gate](2026-09-09-historical-role-reconstruction.md).
The original snapshots and source were preserved; neither failing audit has
been relabelled passing.

The separate cohort audit passed on the closed source:

- Person 27 reached adulthood on day 7,758, following birth on day 1,188 and
  eighteen ordinary daily-clock birthdays. Person 26 remains the other native
  adult; no endowment was issued at either transition.
- 32 people, 576 birthdays, 8,010 census rows, 41 membership intervals and seven
  guardianship intervals reconcile. There are 23 living people and 13 active
  households at day 8,009, with no currently unassigned minors.
- Nine deaths/estates and nine retirements are recorded. The new death was
  person 25, the original permit clerk, on day 7,827.
- Ledger/currency checks passed, with no minor model calls, no population
  endowments and seven rejected negative audit inputs.
- The campaign's closing counters record 9,479 goods executions and 107 equity
  executions, 161,804 scripted calls and zero provider cost. These are activity
  counts, not empirical price-discovery validation.

The closed source hash is
`95743d4dd300633f7366d10512d4fd10a7aff7242373fb9434f1f75378f123af`.
The diagnostic and cohort readers retained its bytes/mtime and no sidecars.
The batch log, failed family-audit log, detailed report differences and passing
`-segment13-cohorts.json` are retained under root `tmp/`.

Independently, [bounded comparator development](2026-09-09-campaign-replay-and-export.md#implementation-and-fixture-validation-in-isolation)
passed 63 focused tests and full-output parity across eight cases in an isolated
worktree. Synthetic child peak memory stayed about 26 MiB through 32,000 added
rows per table; scratch storage and runtime grew. This code has not been
integrated into the native runtime, and export is unchanged.

Next: repair selected-boundary kind reconstruction and consent auditing, then
revalidate the preserved source before any new native segment. The fixed horizon,
full recorded replay/export, remaining W5 acceptance and W6–W9 remain open.

The documentation gate for these updates passed **22 tests / 0.36 s** (1.22 s
with its wrapper), using fresh base `C:/Users/matri/.codex/tmp/ae-d3233ab8`.
All 1,098 source files retained hashes/mtimes during the check and staging was
empty. Receipt prefix: `tmp/estate-finality-native-segment13-docs`. Compilation,
comparator patch application checks and focused tests do not replace full CI.

## Historical-role audit recovery and bounded continuation

The [historical-role repair](2026-09-09-historical-role-reconstruction.md#implemented-repair-and-validation)
is implemented in a separate worktree and passed its final 40-test gate
(103.20 s), including cash/household instruments, current-day equality,
Semantics 1/2 and golden replay. Corrected audit version `kind-v2` reproduces
all 21 saved reports and validates all seven native partnerships, fourteen
assents and sixteen negative cases on the unchanged day-8,009 source.

An independent same-day fixture confirms that a proposal before the nightly
promotion still has a citizen proposer, while a later event observes staff.
The current-day report and stored USD cash metrics also remain identical.
The original failed supervisor, auditors and difference receipts are retained;
the correction changes the historical reader, not the stored simulation.

The explicit continuation supervisor `tmp/estate-finality-life-course-batch-14-18.py`
admits only those verified receipts, freezes the reader worktree and pins all
audit helpers. It can resume at most five segments with the original native
engine and original resource limits. Its process and metadata establish actual
progress once launched. Both isolated integration patches, full campaign
replay/export, remaining W5 gates and W6–W9 remain open.
