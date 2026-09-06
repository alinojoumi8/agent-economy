# Agent Economy: research and city review

Date: 2026-09-06. Reviewed checkout: `534323ea458cd410e246b2358e36c42680e9928f`
on `codex/review-remediation-2026-09-01`; tracked worktree was clean at entry.
This is a dated assessment, not a new release receipt.

Read next: [execution roadmap](2026-09-06-research-city-roadmap.md) and
[implementation specifications](2026-09-06-research-city-specs.md).

## Verdict

Keep this engine and develop it into an economic research laboratory with an
explorable city. The strongest asset is the combination of deterministic
settlement, recorded agent decisions, institutions, and replay. That is a
valuable foundation for investigating mechanisms and comparing agent policies.

The main limitation is the distance between a working miniature economy and a
validated model of economic behavior. Adding more agents or more model calls
does not, by itself, close that distance. Family formation, education, housing,
production inputs, and bank money creation need explicit economic contracts.
Price discovery needs dedicated measurements and benchmark experiments.

The user confirmed equal priority for prices inside the economy and financial
asset prices. Both should be in the first research milestone. The longer-term
vision is a visible loop: household needs create demand; firms produce, hire,
invest, and finance themselves; markets discover prices; those prices change
household and business decisions; demographic change alters the economy.

## What is already present

| Capability | Implementation inspected | Assessment against the new vision |
|---|---|---|
| Deterministic authority | [World.step](../../world/loop.py), [ledger](../../engine/ledger.py), action execution | Strong foundation. Phases, savepoints, recorded decisions, and reconciliation are explicit. |
| Death, aging, retirement, arrivals | [Lifecycle](../../engine/lifecycle.py), `World._spawn_due_arrivals` | Present. Replacement arrivals are adults aged 20–55 with externally funded starting cash. |
| Births and family | `Lifecycle._maybe_birth`, `_find_heir` | Birth increments `dependents`; it does not create a child identity. The heir is the strongest living social tie. A generational household model is still needed. |
| Education | [CognitionEconomy.study_skill](../../engine/cognition.py) | Semantics 11 has paid study and skill XP. Schools, enrollment, teachers as educational producers, credentials, and child-to-worker transitions are a separate expansion. An occupation named Teacher is not proof of a school institution. |
| Firms and labor | [Firms](../../engine/firms.py), [labor](../../engine/labor.py), [startup lifecycle](../../engine/startups.py) | Incorporation, jobs, bilateral wage offers, production, payroll, financing, IPOs, failures, and mergers already exist. Extend them. |
| Goods prices | `Firms.set_price`, `buy_goods`; [founder policy](../../agents/policies.py) | Firms post prices and buyers purchase available units. Scripted pricing uses markup and inventory rules; household spending uses cash-share rules. This is an implemented mechanism, not evidence of realistic demand elasticities. |
| Financial price discovery | [Exchange.match_firm](../../engine/exchange.py), `Firms.close_ipo` | Price/time order matching, cash/share settlement, IPO bidding, and circuit breakers exist. First trades require an expressed price. Retain this machinery. |
| Portfolio behavior | `citizen_decision` in [policies](../../agents/policies.py) | Modern scripted policies bootstrap from book value/goods price, then vary limits around the previous price using sentiment, risk, and noise. These rules can explain observed price patterns and must be tested as assumptions. |
| Banking | [Bank.disburse_loan](../../engine/credit.py), repayment/default/liquidity support | Loans debit reserves and credit the borrower. Useful simplified funding model; insufficient by itself for claims about modern deposit creation or full institutional balance sheets. |
| Geography and construction | [regions](../../engine/regions.py), [city](../../engine/city.py), [construction contract](../semantics13-construction-economy.md) | Regions, currencies, migration, places, appointments, permits, escrow, work units, and completion already exist. Construction is not missing. Competitive rents, land scarcity, and transport costs need further design. |
| Research | [counterfactuals](../../research/counterfactual.py), [experiments](../../experiments/harness.py), [exports](../../research/export_bundle.py), [R21](../../research/r21.py) | Paired runs, bootstrap summaries, pinned initialization data, exports, and replay foundations exist. Research eligibility and artifact preservation need tightening. |
| City UI | [LiveCity](../../dashboard/src/components/LiveCity.tsx), [CivicCity](../../dashboard/src/components/CivicCity.jsx), [WorldWorkspace](../../dashboard/src/workspaces/WorldWorkspace.tsx) | Recorded-day animation plus an analytical Atlas/2.5D view with layers, selection, keyboard exploration, and evidence links. Integrate their behavior before adding another renderer. |
| Research UI | [MarketsWorkspace](../../dashboard/src/workspaces/MarketsWorkspace.tsx), [ExperimentsWorkspace](../../dashboard/src/workspaces/ExperimentsWorkspace.tsx) | Good evidence tables. Missing the integrated design/run/compare workflow and price-mechanism investigation experience proposed here. |

The maintained maximum is semantics 14/schema 20 according to the
[status ledger](../implementation-status.md); the base profile still selects
semantics 7. A feature existing in an opt-in profile does not mean it is active
in every world. Historical compatibility is a strength to preserve.

## Priority findings

### R1 — Counterfactual reruns can destroy prior evidence

**High priority; source-confirmed.** `research.counterfactual._run_arm`, around
lines 109–122, constructs `<scenario>-s<seed>-<arm>.db` and calls `path.unlink()`
if it already exists. `run_counterfactual` also uses fixed report filenames.
The CLI reaches this path through `--counterfactual`, confirmed with the code
graph's inbound call trace. Repeating a study can replace its original data.

Give every campaign an immutable manifest identity and every attempt its own
directory. Refuse collisions; resume only an exact compatible unfinished
attempt. Preserve failures and diagnostics. Do not execute the existing
counterfactual command against valuable campaign directories while addressing
this finding. No destructive rerun was performed in this review.

### R2 — General paired summaries lack an eligibility boundary

**High priority; source and diagnostic confirmed.** `_run_arm` returns the
achieved tick and reconciliation status. `run_counterfactual` checks external
influence and a genesis event hash, but does not require every arm to reach the
declared horizon, reconcile, and complete exact replay before summarizing.
`paired_summary` does not inspect those validity fields.

A direct call using a reconciled control at tick 30 with value 100 and an
unreconciled treatment at tick 3 with value 130 returned an effect of 30 and a
bootstrap interval of `[30, 30]`. This demonstrates the helper's permissive
boundary; it is not a simulated economic finding. Empty differences also become
a zero mean and `[0, 0]`, which confuses missing evidence with no effect.

Add explicit attempt eligibility, paired coverage, and missing-data states.
The current field named `replay_hash` is an event digest, not proof that a fresh
replay was executed. Use the existing replay verifier for an actual receipt.
The stricter Oracle/release campaign machinery should inform this work; this
finding is about the general counterfactual path, not every campaign tool.

### R3 — Live City ignores the historical tick in its URL

**High priority; reproduced in the browser.** With disposable run `57be5cdf01`
paused at tick 3, `/runs/57be5cdf01/live-city?tick=1` still displayed
`RECORDED DAY · TICK 3`. The analytical `/world?tick=1` displayed historical
tick 1. This is reachable through ordinary historical workspace navigation.

`LiveCity` requests `/api/run/status` and `/api/v2/map` with its own `useSource`
keys, without including the shared tick/fork cursor. Its return link also
needs to preserve observer context. Move its reads and selections onto the
shared projection contract and test run/fork/tick isolation before expanding
the interface. Never show live data as the requested past.

### R4 — CPI documentation and implementation disagree

**High priority for interpretation; source-confirmed.** The
[research guide](../research-guide.md) describes inventory-weighted CPI.
`Metrics._cpi`, around lines 165–189 in [metrics](../../world/metrics.py),
actually averages posted prices of genesis non-health/non-insurance firms
under semantics 2+, then normalizes against a stored base. It is neither
inventory-weighted nor an index based on executed household expenditure.
It also does not convert the component posted prices to a common currency.

Correct the description first, preserving historical values. Add separately
versioned transaction-based indices with basket, currency, coverage, and stale
price rules. Do not silently redefine stored `cpi` or feed a new definition into
policy agents without a semantics change.

### R5 — Generational life is represented through proxies

**Product gap, not a broken implementation of the old contract.** A dependent
count cannot become a student, worker, parent, or heir with its own history.
Social ties are not household membership or kinship. Adult replacement arrivals
are migration with an endowment, not endogenous population reproduction.

Add persistent people, households, guardianship, partnerships, educational
progress, and explicit inheritance. Keep the current stable-population mode as
a benchmark. Compare open-migration and endogenous-demography worlds rather
than mixing their inflows without reporting them.

### R6 — Production and banking constrain the questions you can ask

**Modeling limits.** `Firms._produce_one` multiplies worker count by fixed output
and pays input costs to `SYS_COMMODITY`; it does not require a chain of
competing upstream suppliers. Construction also has a materials-system
counterparty. This limits endogenous bottleneck and input-price studies.

`Bank.disburse_loan` funds loans from reserves. Balanced cash transfers do not
alone establish a stock-flow-consistent model of bank assets, deposit
liabilities, equity, and interbank settlement. Introduce explicit alternative
regimes, with reconciliation for physical stocks and institutional claims as
well as money. Report system-account inflows and outflows by cause.

### R7 — Economic competence and human realism need separate evidence

**Research priority.** Present policies deliberately produce activity. A
reconciled trade or an interesting boom is not enough to show realistic price
discovery. Compare scripted, bounded rational/adaptive, and LLM policies with
the same authority, information, resources, and opportunities. Vary prompts,
model versions, cadence, and core/periphery assignment in declared experiments.

Test simple choices with known answers before complex worlds. Track rejected
actions, fulfilled needs, forecast calibration, liquidity, gains from trade,
and sensitivity. Use several independent runs; thousands of agents sharing one
world are not thousands of independent treatment replications.

### R8 — The UI's components are more mature than its combined workflow

**Design assessment from source and browser inspection.** The recorded-day
view makes the population visible; the analytical view contains the useful
inspectors and 2.5D controls. The user has to cross surfaces to connect an
individual's life, a building, an economic change, and a study.

The recorded-day view also animates between three stored placements on a
separate wall clock while the simulation is paused. It discloses interpolation,
but the prominent Paused label and continuing motion are easy to misread.
Give replay animation and world advancement separate, explicit controls.

At the inspected 901×509 browser viewport, navigation and instrumentation
substantially reduced the visible analytical canvas and required scrolling to
reach it. Preserve the working keyboard explorer and evidence links; organize
them around a larger map and compact, collapsible instruments. Visual geometry
must still disclose when it is derived.

### R9 — Profile capability needs a visible explanation

**Reproduced.** The 31-tick institutional rehearsal displayed a valid regional
world but no recorded city placements. The 300-resident construction profile
displayed 897 placements at tick 3. An indefinitely waiting city can look broken
when its profile simply lacks that capability. Offer a capability explanation,
a useful regional/table view, and an explicit new-world launch option.

## Verification performed

Code discovery used the existing Codebase Memory graph and specific source
snippets, backed by current configuration, documentation, tests, and browser
inspection. This was a broad capability/architecture review with targeted deep
reads, not an exhaustive line-by-line security audit.

| Check | Result and boundary |
|---|---|
| CI smoke contract | 144 passed in 126.78 s; one Starlette/httpx deprecation warning. Initial attempt had 26 passed/118 setup errors due to access denied on the shared Windows pytest temp directory; rerun with a fresh unique `--basetemp` passed. |
| Four dashboard model suites | 46 passed; Live City, Civic City, markets, experiments. |
| Institutional rehearsal | `9e4043ec86`, 31 ticks, 36 living agents, 109 goods-sale events, 1 equity trade; all recorded calls scripted, $0. |
| City/construction rehearsal | `57be5cdf01`, 3 ticks, 300 living agents, 29 goods-sale events, 3 equity trades; all recorded calls scripted, $0. |
| Accounting reads | Both disposable databases opened using SQLite `mode=ro`; all four currency sums were zero and account/materialized-ledger mismatches were zero. |
| Browser | Pulse run control; recorded city; historical tick mismatch; analytical historical city; Atlas/2.5D switch and keyboard explorer inspected. |
| Direct summary diagnostic | Ineligible mismatched-horizon input still produced a numeric effect, as described in R2. |
| Documentation package | 22 documentation tests passed after adding the plan links; all relative links in the three new documents resolved. |

Commands used:

```powershell
$reviewTestTemp = Join-Path $env:TEMP ('ae-review-smoke-' + [guid]::NewGuid().ToString('N'))
.\.venv\Scripts\python.exe -m pytest -q tests/test_documentation.py tests/test_external_agent_gateway.py tests/test_research_export.py tests/test_prd_completion.py tests/test_recorded_replay_golden.py --basetemp $reviewTestTemp --tb=short
node --test dashboard/tests/live-city.test.js dashboard/tests/civic-city.test.js dashboard/tests/markets-workspace.test.js dashboard/tests/experiments-workspace.test.js
.\.venv\Scripts\python.exe run.py --config runs/v2-institutional-rehearsal.yaml --ticks 31 --serve --host 127.0.0.1 --port 8123
.\.venv\Scripts\python.exe run.py --config runs/civic-city-300-construction.yaml --ticks 3 --serve --host 127.0.0.1 --port 8124
```

The two disposable worlds were advanced using Pulse's Run control. They were
not paid-provider or generational studies. The institutional profile contains
deliberate fixtures; its activity is not evidence of unprompted emergence.
No fresh exact replay receipt was produced for these two runs. Passing the
recorded-replay smoke test is separate evidence. The full repository gate,
hosted deployment, large-scale performance, and live-provider validity were
not revalidated in this review.

The two task-created review servers were stopped after inspection; their
disposable databases remain in the ignored `data/runs/` directory. No existing
run, runtime source, dependency, schema, or dashboard bundle was modified.

## Primary research informing the recommendation

These are design references, not evidence that this simulator is validated:

- [Grimm et al., ODD second update (2020)](https://www.jasss.org/23/2/7.html):
  use an explicit model description covering purpose, entities, scheduling,
  initialization, data, and submodels, including rationale and evaluation.
- [Byrd et al., ABIDES (2019)](https://arxiv.org/abs/1904.12066): exchange
  protocols, message timing, and market-impact experiments are useful reference
  points for a future intraday market mode. This review recommends extending
  the existing exchange first; it does not propose importing ABIDES wholesale.
- [Fish et al., EconEvals, revision 4 (2026)](https://arxiv.org/abs/2503.18825v4):
  assess economic competence and choice tendencies separately. This motivates
  agent-level tests before interpreting aggregate behavior as human realism.
- [Bank of England, Money creation in the modern economy (2014)](https://www.bankofengland.co.uk/quarterly-bulletin/2014/q1/money-creation-in-the-modern-economy):
  lending/deposit creation motivates a distinct banking regime if that is the
  mechanism under study. The existing reserve-funded regime remains a useful
  comparison model.

The proposed ordering and specifications are engineering judgments based on
the inspected code and the user's research goals, not prescriptions from these
papers.
