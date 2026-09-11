# Native employment diagnosis and next validation

The stopped population run has two distinct limits: its baseline hiring policy
never posted a vacancy, and the declared four-hour runtime ended before the
40-year horizon. Extending runtime alone does not address the hiring policy.

## What the preserved run shows

A bounded, read-only inspection at day 11,356 verified seven birth-origin people,
five surviving native-born adults aged 20–28, zero historical employment records
for those people, zero job records, and zero `post_job`, `apply_job`, `hire`,
`make_job_offer` or `accept_job_offer` proposals across the campaign. One native
adult made 33 accepted goods-purchase proposals; absence of employment must not
be reported as absence of all economic decision-making.

The latest surviving-company decision is recorded call 215053, day 11,355,
actor 18, firm 2. Its context has one employee, target headcount three, payroll
250,000 cents and company cash 13,123,302 cents. Workforce recovery is absent.
The baseline policy posts jobs only when employees reach zero. Existing workers
therefore prevent replacement recruitment even when cash covers another wage.

The frozen policy reproduced the complete recorded response exactly: a purchase
of eight goods. Changing only the context's existing workforce-recovery flag
produced a job-posting proposal for firm 2 at a wage of 250,000 cents. This was a
pure policy evaluation: the proposal was not executed, no world advanced, and
no hiring, income, full-world counterfactual or successful generation is claimed.

The complete current policy file matches the original frozen policy byte for
byte. The scenario setting which enables this behavior is
`firms.recruit_to_target: true`. A separately saved configuration loads through
the frozen configuration reader and enables retail recruitment on day one;
the control with the setting false disables it. This is an existing option,
not a new engine behavior or a change to historical semantics.

## Timing evidence

| Observed days | Mean seconds per day |
|---|---:|
| 1–1,000 | 0.291 |
| 4,001–5,000 | 1.004 |
| 7,001–8,000 | 1.651 |
| 10,001–11,000 | 2.056 |
| 11,001–11,356 | 2.016 |

Using only the last observed mean, the missing 3,244 days would add about 6,541
seconds, giving about 5.82 hours overall. This is an estimate, not a guarantee;
the hiring treatment can change workload. Stored timings cover whole steps and
do not identify a particular slow function or query. No speculative performance
patch was made on the basis of these measurements.

## Separate prospective trial

Preserve the original campaign as its recorded negative baseline. Do not resume
it beyond its four-hour allowance, edit its configuration, or reuse the partial
verifier's remaining allowance as a fresh budget. Its stopped horizon and
incomplete replay/export remain recorded outcomes.

The proposed next trial is a separate mechanics validation from genesis, with
seed 1, Semantics 20, the original population/bank/firm settings, ordinary daily
aging and the full 14,600-day horizon. Its one economic configuration change is
`firms.recruit_to_target: true`. Record that intervention before execution. Do
not force births, deaths, employment, prices or another outcome. A failure to
observe productive native adulthood remains a reported gap.

Proposed limits for this separate trial are eight hours of native execution,
then eight hours for recorded replay, two for exact comparison, two for export
and one for independent readback: 21 hours maximum across those stages. Keep
ten-minute native segments, cumulative accounting, no automatic retries, a
16 GiB process-tree memory ceiling and zero paid-provider spending. These are
prospective limits, not extensions or resets of the original campaign/verifier.

Retain four 16 GiB disk allocations for source, private copy, replay/comparison
and export, plus a 40 GiB reserve. Admission requires 104 GiB free and at least
20 GiB available RAM. The initial 93.44 GiB capacity check was insufficient;
the later check found 129.94 GiB free and resolved that constraint. The controller
independently checked disk and RAM on admission. No files were deleted here.

The separate controller passed a three-day rehearsal with two clean restarts,
58 scripted calls, zero provider cost, balanced ledger and household checks,
four census observations, SQLite integrity and unchanged frozen source. Actual
re-entry and altered-budget probes rejected before modifying the completed
case. The entire check took 19.516 seconds and retained about 4.5 MB. Its native
portion took 14.140 seconds. The prepared v1 contract was never executed; v2
added durable child process identities before either v2 trial began.

The full v2 campaign started at 2026-09-11 00:39:00 UTC (September 10 locally),
under its separate eight-hour allowance. Its source directory is
`C:/Users/matri/.codex/tmp/ae-e11aa039`, with a live `receipt.json` and daily
`observations.jsonl`. The source controller, configuration and contract are
copied into that directory. Parent PID 22924 has creation time
`1789087139.2311227`; the controller records each child identity independently.
The process must be checked by PID and creation time before any later action.
Current status is running, not accepted. Reports and disabled-checkpoint paths
are allocated inside this new case. The original campaign and verifier retain
their terminal/interrupted outcomes and original limits.

Completion still requires full-horizon cohort/census/estate audits, actual
native-generation observations, balanced money, equal goods/equity records,
exact recorded replay, complete comparison, export and independent readback.
The isolated policy evaluation above closes none of those broader requirements.
W5 and the later workstreams remain open under the existing execution order.

## Verification controller evidence

The three-day source also passed recorded replay, exact comparison across 189
tables, export of 193 tables/2,752 rows and independent source-backed readback.
The v2 verification rehearsal took 99.140 seconds and retained about 9.2 MB.
It consumed all 58 recorded calls once, without fresh model dispatch, and left
the source and both frozen runtimes unchanged. This is controller evidence for
the small source; the 14,600-day source still needs its own complete execution.

The final verifier revision also ensures a failed final resource/source check
returns a failing process exit code. Its separate v3 rehearsal passed all four
stages in 105.375 seconds with the same bundle hash as v2. The verified v3
controller subsequently received the reader/audit integration below; v1's
failure and the successful v2/v3 results remain retained.

### Current reader and life-course integration

The older analysis snapshot predates the validated repair for personal roles
before a staff appointment, and for workforce-recovery model references. The
three-day rehearsal alone does not exercise a later staff succession. The
full trial now uses a separate frozen copy of the current tested readers:
`C:/Users/matri/.codex/tmp/ae-784123d0`. All 1,192 copied files match the captured
source snapshot; production/test files match the 1,190-file gate snapshot,
with five documentation paths changed afterward. The dependency lock matches
the existing analysis environment. Both older runtimes remain preserved.

The v4 verification rehearsal passed recorded replay, 189-table comparison,
193-table/2,752-row export, independent readback and life-course checks in
102.953 seconds, retaining the same bundle hash as v2/v3. Its additional audit
runs inside the existing readback time/memory allowance. It checks birthdays,
household and guardian intervals, consent, census, currency/ledger balances,
estate identity, saved household reports, care observations and both markets.
It reports employment contracts, delivered work, earned claims and received
cash separately. A three-day pass does not establish native adulthood.

A separate executed regression reads the preserved native source: call 10,
person 11, day 1 records `citizen`; appointment event 165606 is on day 7,827.
The old analysis reader returns `permit_clerk`; the frozen current reader
correctly returns `citizen`. It also confirms the original seven native people
have no employment records. This read preserved size/mtime and created no
sidecars; it did not recompute that original database's full hash.

The actual 34-day hiring fixture validates 14,880 delivered work minutes,
258,333 NSD cents accrued and 212,500 cents received after tax for genesis
person 24. Source bytes/mtime remained unchanged. Two deliberately corrupt
inputs fail: an invalid employment reference and a wage-tax record inconsistent
with ledger cash. Corruption occurs only in an in-memory fixture; original
files and immutable-row triggers remain unchanged. The final regression takes
4.172 seconds. Three earlier fixture-selection/corruption-setup failures remain
retained, separately from this passing result. None proves a native generation
in the running hiring trial.

The first verification rehearsal failed during export because a staging folder
was atomically renamed while the supervisor enumerated disk usage. Replay and
comparison had passed, but that attempt is retained as failed. Its owned process
identities were independently verified absent. A focused regression reproduces
the original failure and verifies that the correction tolerates a vanished
temporary folder while still propagating permission errors. The original stage
library and original verification trial were left unchanged.

The full-scale campaign completed its first clean native segment at day 1,541,
with ledger/household reconciliation and a closed hashed database, then resumed
in a fresh child process. Full native acceptance remains open. Operational
handoff is `tmp/native-hiring-active.json`; it records the active process
identity, immutable contracts and the next verifier invocation. A verifier may
start only after the new campaign completes all 14,600 days and its writer exits.

### Interim market inactivity

A bounded snapshot of the controller's daily observations through day 4,561
records 6,318 goods executions, with the last increase on day 2,070, and 265
equity executions, with the last increase on day 2,082. These are 2,491 and
2,479 subsequent complete days without an execution respectively. Both markets
must remain visible in the report, including their inactive periods. This is
an interim observation from the recorded daily counters; it does not identify
the cause, validate full-source replay or establish productive native adulthood.
The live campaign was not changed. The subsequent observations below identify
company failures and their cash flows. Full closed-source verification remains
required, without forcing market activity or jobs.

### Company failures and operating cash flows

Two brief read-only observations used consistent SQLite WAL snapshots while the
native writer continued. They captured completed days 5,456 and 5,688 in segments
8 and 9. Historical events and ledger/labor rows stop at completed days. The
transactions closed after 0.016 and 0.050 seconds respectively, inside five-second
query and twenty-second outer limits. Both observers exited successfully. These
are live observations, not immutable full-run audits or causal comparisons.

All three companies have recorded `insolvency` bankruptcies. The first snapshot
has no active employment contracts and zero outstanding shares at all three
companies. Cash flows through each company's bankruptcy day are:

| Company | Bankruptcy day | Goods-sales cash | Production inputs | Paid wages | Operating cash result |
|---|---:|---:|---:|---:|---:|
| Food Co 1 | 90 | $0.00 | $2,258.52 | $19,091.24 | -$21,349.76 |
| Retail Co 2 | 2,101 | $83,210.49 | $51,910.80 | $512,425.30 | -$481,125.61 |
| Manufacturing Co 3 | 150 | $0.00 | $6,030.03 | $25,779.68 | -$31,809.71 |

Amounts are simulated USD. Operating cash result is sales less production-input
cash and paid wages; it is not accrual profit and excludes finance, capital
funding and bank losses. Including every recorded cash-flow category reconciles
each company account to zero at the end of its bankruptcy day.

Retail Co 2 records $2,325,000.00 in 155 loan-disbursement entries and
$1,851,967.05 in loan-payment outflows. Its day-1,980 depositor haircut removes
another $9,198.95. Initial capital and IPO subscriptions contribute $17,291.61.
These categories account for the operating shortfall and final zero balance.
They establish reliance on net financing in this run; they do not estimate the
effect of recruitment relative to a matched control. All four of its final
31-day loan applications are denied, including the day-2,100 application
decided on day 2,101.

Recorded founder call 48,635 on day 2,100 has three employees, each on a
250,000-cent, 30-day wage contract, zero company cash, no inventory, no recent
sales and a posted goods price of 495 cents. The unchanged frozen policy exactly
reproduces its proposal to raise the price to 519 cents and request a
1,500,000-cent loan. Recruitment is enabled in this context; the separate active
supply-recovery profile is absent. Enabling `recruit_to_target` therefore does
not enable its cost-aware pricing and wage checks.

An illustrative calculation uses that recorded price, wage and 120-cent input
cost, plus the seven-unit daily worker output in the later explicitly current
product snapshot. Three workers selling every unit over 30 full workdays produce
630 units, $3,118.50 in sales and $2,362.50 after input costs, against $7,500.00
in contracted wages. The integer break-even price is at least 1,311 cents per
unit before financing costs. Full attendance, full sales and an unchanged output
rate are assumptions. This is neither observed demand at that price nor a
simulated counterfactual; a higher price can reduce sales.

The inspected policy sources identify two mechanisms to evaluate.
`_select_stocked_firm` uses the cheapest stocked seller when neither inventory-
aware shopping nor recovery is active. `founder_decision` ordinarily reprices
from input cost and inventory without including wages. The separate recovery
profile supplies a wage/output/cadence calculation, which still needs independent
demand evidence. The bankrupt firm path ends employment, removes shares and
cancels open orders. That recorded closure explains the later absence of
employers and tradable issuers; final executions precede the last bankruptcy
and retain their own dates.

### Follow-up specification before another long horizon

Keep the running campaign fixed through its declared horizon and verification.
The collapse is a result to preserve. Productive native employment and full W5
acceptance remain unproved. A remedy must distinguish a mechanics defect from
a benchmark policy or scenario assumption.

1. Reproduce this decomposition against the closed source. Join firm histories,
   hiring, delivered work, wages, borrowing, bank losses, shortages and equity
   delisting at their recorded boundaries. Show inactive periods in both market
   panels; an old execution price must not appear current.
2. Use a small, separately declared fixture before another multi-decade run.
   Exercise more than one payroll period, a rejected loan, unsold inventory and
   loss-making production. Report closure as well as survival, with ledger
   reconciliation and replay. Establish feasibility before a new long campaign.
3. Compare demand allocation and cost-aware pricing as separate policy factors.
   Reuse existing opt-in shopping and supply-recovery contracts where they fit
   the question, with explicit parameters. Product-specific needs and substitution
   rules require their own demand model; weighted shopping alone is insufficient.
4. Define labor cost per delivered unit using actual wage cadence, output and
   expected utilization. A resulting reservation price or hiring limit belongs
   to an identified actor policy. The exchange continues matching agent-authored
   quotes. Higher prices and profitable firms are measured outcomes.
5. Assess credit capacity using operating cash flow, existing debt and debt
   service separately from new borrowing. Preserve bank-loss propagation and
   household claims. This informs W8; keep the current trial's underwriting fixed.
6. Declare a future experiment's sample, horizon, factors, stopping rules and
   resource allowance before execution. Include paired controls and both goods
   and equities. Preserve earlier failed/stopped cases and their allowances.
   Close W5 against its complete contract before W6 implementation.

### Declared 180-day policy pilot

A separate one-seed pilot completed from genesis. Its immutable plan is
`C:/Users/matri/.codex/tmp/ae-089e251d/native-solvency-pilot-v1.json`; artifacts
are under `C:/Users/matri/.codex/tmp/ae-0a0c530a`. The cases are:

| Case | Declared difference from the native hiring profile |
|---|---|
| Control | None; retains recruitment to target. |
| Shopping | Enables the existing inventory-aware shopping behavior and its quantity cap. |
| Recovery bundle | Adds the existing supply-recovery profile to Shopping, effective day 1. |

Recovery declares a 250,000-cent wage floor, 125% gross-margin coverage,
two payroll periods of cash coverage, one new hire per period, a three-worker
cap, thirty observation days and a five-day demand buffer. These are model
parameters, not empirically calibrated values. Recovery also affects seller
selection and hiring, so its contrast cannot isolate the effect of pricing.

All cases retain seed 1, Semantics 20, the initial population/firm/bank settings,
ordinary aging and scripted routes. The controller checks equality of selected
genesis person, household, firm, account, employment and ownership tables before
advancing a treatment case. It records company cash flows and both markets at
30-day boundaries through day 180. Every source is followed by recorded replay,
exact comparison, export and independent source-backed readback.

The separate allowance is twenty minutes total across all three cases and all
stages, with a three-minute ceiling per stage, 2 GiB process-tree memory, 6 GiB
total artifacts, a 40 GiB free-space reserve and zero provider spending. Failed
cases are retained without automatic repetition. The long native run and both
original verification allowances remain unchanged. Operational handoff is
`tmp/native-solvency-pilot-active.json`; the completed case must not be rerun.

All fifteen stages passed in 848.719 seconds and retained 907,066,721 bytes.
The three cases have identical selected genesis tables, balanced ledgers,
189-table exact replay and 193-table exports with independent readback. Replay
consumed 4,228 control, 3,858 shopping and 3,822 recovery calls exactly once,
with zero fresh dispatch or provider cost. Export row counts are 84,047, 94,038
and 92,952 respectively. An additional closed-source audit took 1.203 seconds,
reproduced the earlier two control bankruptcies and their cash flows, verified
both markets and left all source hashes/mtimes unchanged. Every owned pilot
process identity is verified absent.

| Day-180 outcome | Control | Shopping | Recovery bundle |
|---|---:|---:|---:|
| Operating firms | 1 | 3 | 3 |
| Active jobs | 3 | 9 | 9 |
| Goods executions | 615 | 1,716 | 1,652 |
| Equity executions | 53 | 41 | 46 |
| Operating cash result | -$94,322.25 | -$133,488.26 | $37,834.43 |
| Loan disbursements less loan payments | $39,600.73 | $99,826.00 | $0.00 |

Cash totals use simulated USD across the same three firms. They exclude capital
funding from operating results and are not accrual profit. Shopping kept more
firms operating, with more wage payments and financing-dependent losses. The
recovery bundle covered paid wages and input costs at each firm without a loan
disbursement during these 180 days. This does not establish long-run stability.

The following executed-price averages are weighted by units or shares traded
within days 1–180. Keep each product/issuer separate:

| Series, USD per unit/share | Control | Shopping | Recovery bundle |
|---|---:|---:|---:|
| Food Co 1 goods | No trades | $5.18 | $36.28 |
| Retail Co 2 goods | $1.94 | $1.95 | $15.98 |
| Manufacturing Co 3 goods | No trades | $3.44 | $15.05 |
| Food Co 1 equity | $21.04 | $20.95 | $35.35 |
| Retail Co 2 equity | $10.16 | $10.17 | $17.94 |
| Manufacturing Co 3 equity | $0.16 | $2.97 | $11.23 |

These averages are historical executions, not current quotes, fundamental
values or a common price index. Bankruptcy shortens some trading windows;
each source report retains execution counts, quantities and first/last dates.
One seed supplies no population-level uncertainty estimate. In particular,
the recovery package's higher prices are an actor-policy assumption to compare,
not evidence of empirically correct price levels or an isolated pricing effect.

The reusable [recovery benchmark profile](../../runs/life-course-recovery-benchmark.yaml)
contains exactly the executed recovery parameters, with descriptive comments.
It also loads through the current configuration reader with only scripted
routes. The executed pilot used the preserved engine runtime; copying this
profile does not claim another complete current-worktree campaign or change
the ongoing native trial, the default profile or historical semantics.

W5 acceptance continues to follow S5's identity, household, care, estate,
population-mode and replay requirements, including the declared native horizon.
S5 explicitly states that adulthood does not guarantee employment or wealth.
An absence of native employment is a reported coverage/outcome limitation; it
does not by itself show an accounting failure or justify forcing jobs. The
broader education-to-work demonstration and empirical fitness remain part of
the later work packages. These distinctions do not close any pending W5 gate.

## Evidence

- [Employment diagnosis](C:/Users/matri/.codex/tmp/ae-089e251d/native-employment-diagnosis.json).
- [Timing and capacity](C:/Users/matri/.codex/tmp/ae-089e251d/native-timing-and-capacity-diagnosis.json).
- [Proposed hiring configuration](C:/Users/matri/.codex/tmp/ae-089e251d/native-hiring-profile-proposed.json).
- [Executed configuration validation](C:/Users/matri/.codex/tmp/ae-089e251d/native-hiring-profile-validation.json).
- [Executed controller rehearsal and rejection checks](C:/Users/matri/.codex/tmp/ae-089e251d/native-hiring-controller-smoke-v2-audit.json).
- [Full hiring-trial contract](C:/Users/matri/.codex/tmp/ae-089e251d/native-hiring-campaign-contract-v2.json).
- [Hiring-trial progress receipt](C:/Users/matri/.codex/tmp/ae-e11aa039/receipt.json).
- [Current verifier rehearsal](C:/Users/matri/.codex/tmp/ae-089e251d/native-hiring-smoke-verification-v4.json).
- [Frozen current reader](C:/Users/matri/.codex/tmp/ae-089e251d/native-hiring-current-analysis.json).
- [Role and paid-work regression](C:/Users/matri/.codex/tmp/ae-089e251d/native-hiring-reader-work-regression-v4/receipt.json).
- [Admission and execution handoff](C:/Users/matri/.codex/tmp/ae-089e251d/native-hiring-admission-closure-v4.json).
- [Interim market observation](C:/Users/matri/.codex/tmp/ae-089e251d/native-hiring-market-observation.json).
- [Bounded bankruptcy and policy observation](C:/Users/matri/.codex/tmp/ae-089e251d/native-hiring-market-stop-observation/receipt.json).
- [Bounded company cash-flow observation](C:/Users/matri/.codex/tmp/ae-089e251d/native-hiring-firm-cashflow-observation/receipt.json).
- [Derived cash-flow and capacity calculation](C:/Users/matri/.codex/tmp/ae-089e251d/native-hiring-cashflow-diagnosis.json).
- [Declared pilot contract](C:/Users/matri/.codex/tmp/ae-089e251d/native-solvency-pilot-v1.json).
- [Verified pilot outcomes and per-firm market records](C:/Users/matri/.codex/tmp/ae-089e251d/native-solvency-pilot-outcomes-v1.json).
- [Reusable profile validation](C:/Users/matri/.codex/tmp/ae-089e251d/native-solvency-reusable-profile-v1.json).
- [Completed project gates](2026-09-10-population-hosted-admission.md).
- [Preserved native verification contract](2026-09-09-full-campaign-verification.md).

The employment audit ran in the frozen Python runtime with bytecode writing
disabled and a 30-second outer limit; it completed in 0.172 seconds. SQLite was
opened in immutable, query-only mode with a query deadline. Source size/mtime,
absence of sidecars and all inspected protected-file hashes/mtimes were unchanged.
The full 5 GB source hash was not recomputed in that diagnosis inspection.
Subsequent contract preparation did recompute it and matched the recorded
original hash. It also froze hashes, sizes and modification times for the
original plan, native/verifier metadata, verification contract and recovered
copy. Those protected records remain separate from the new trial.
