# Agent Economy: research city execution roadmap

Date: 2026-09-06. Status: **Implementation active; automated city/price-study workflow verified; deeper-economy and validation packages remain**.
Basis: [review and verified limitations](2026-09-06-research-city-review.md).
Contracts: [implementation specifications](2026-09-06-research-city-specs.md).

## Product direction

Build an economic laboratory that can be explored like a city. A researcher
should be able to follow a household, inspect a business or bank, examine how
prices formed, change a declared assumption in a separate experiment, and
compare the resulting worlds with reproducible evidence.

The user explicitly prioritizes **both** everyday economic prices and financial
asset prices. Give them equal status in the research interface, experiment
catalog, benchmark budget, and release criteria. Housing, education, and family
formation extend their economic causes; they are not prerequisites for the
first useful paired goods/equity study.

The current PRD's implemented scope and its release gates remain valid. This
roadmap expands the research ambition; it does not relabel the old PRD as
unfinished or claim that proposed features already exist. The user has now
authorized implementation of recommendations 1–5 in order: research integrity,
the dual price lab, the interactive city, deeper economics, then validation.
Track completed code and verification in the [execution log](2026-09-06-research-city-execution.md).
The [production workflow gate](2026-09-07-city-research-acceptance.md) now repeats
the city-to-study path with real projections, both price domains and independently
verified exports. Human usability sessions and research-scale validation remain.
The [household decision slice](2026-09-07-household-decisions.md) extends W5 with
recorded consent, partnerships, separation and joint moves.
The [daily time slice](2026-09-07-daily-time-and-earned-wages.md) connects delivered
care, work, study, construction, appointments and travel to one daily budget,
with proportional production and earned wage claims. W5 remains open for complete
estates, business succession and cohort/multi-decade validation; W6–W9 remain.
The [cash estate checkpoint](2026-09-07-estate-cash-and-credit.md) adds recorded
same-currency wallet settlement and bank-principal losses. It is one component
of the remaining estate work, not closure of W5.

## First deliverable: Price Discovery Lab v1

Deliver one complete workflow before expanding the world further:

1. Open a provider-free world and see whether its price and accounting data are
   usable. Display the selected profile's capabilities and limitations.
2. Select a grocery/manufacturing business. Inspect posted prices, executed
   purchases, quantities, inventory, wages, and operating cash flow.
3. Select a listed firm. Inspect expressed orders, executions, liquidity,
   ownership, disclosures, and its connection to real business activity.
4. Prepare an input-cost or demand experiment and a financial-information
   experiment. Predeclare controls, seeds, outcomes, and eligibility rules.
5. Run treatment/control attempts in immutable locations, inspect failures,
   and compare effects with uncertainty and matched sample counts.
6. Move between the city, person/business inspector, market charts, and evidence
   while retaining the same run, fork, tick, and selected object.
7. Export a reproducibility bundle and a plain-language findings report with
   supported conclusions, missing data, and negative results.

Success means completing this workflow for both price domains. It does not
require a statistically significant effect, realistic-looking volatility, or
an LLM outperforming a simpler policy.

## Design choices

| Decision | Proposed choice | Reason |
|---|---|---|
| Engine | Extend the current deterministic Python engine | Preserve ledger, replay, provenance, and installed institutional capabilities. |
| Agent autonomy | Bounded preferences, information, and action menus; interchangeable decision policies | Makes assumptions testable and separates economic opportunity from model competence. |
| Initial economic horizon | Daily settlement, with explicit session sequence for equities | Works with current phases. Finer market time can be added without changing biological age or interest accrual. |
| Demographic horizon | Keep days and years consistent; benchmark multi-decade offline runs | A year of trading cannot also mean a generation of aging. |
| Renderer | Reuse Atlas and deck.gl 2.5D, unify their state and inspectors with recorded-day playback | Existing rendering capability is sufficient for the first milestone. |
| City interaction | Pan, zoom, select, follow, filter, time travel, compare, and preview interventions | These interactions serve research and the requested SimCity feel. |
| Experimental intervention | Immutable child attempt from a verified boundary, with a declared treatment | Preserves the source and makes the intervention reviewable. |
| Real-data role | Pinned initialization plus separate held-out behavioral/dynamic validation | Good starting distributions do not validate later outcomes. |
| Scale | Start with 100–300 persistent residents; profile 1,000 before targeting more | The bottleneck and policy fidelity must be measured first. |
| Platform expansion | Defer additional hosted/agent-builder infrastructure unless a milestone requires it | Focus effort on economic explanations and usable studies. |

The requested SimCity direction revises the interpretation of the current
[DESIGN.md](../../DESIGN.md) prohibition on turning the world into an isometric
game. The implementation should update that wording to permit an original,
interactive 2.5D research city while preserving evidence labels and removing
no accounting or authority protections. The design amendment is now reflected
in DESIGN.md following implementation authorization. Do not
copy SimCity source, assets, branding, or proprietary simulation formulas.

## Delivery order and work packages

Effort sizes are rough engineering estimates for one experienced implementer
after contracts are settled, excluding paid campaigns and external validation.
They are not calendar commitments. Re-estimate after the first two packages.
Every package includes implementation, appropriate tests, documentation, and
review; none is complete merely because a screen renders.

| ID | Package and concrete deliverable | Depends on | Size | Exit criterion |
|---|---|---|---|---|
| W0 | Research preservation and eligibility: collision-safe attempts, terminal/horizon/reconciliation gates, explicit missing effects, real replay receipts | None | 3–6 days | Repeating a campaign preserves every prior byte; invalid or incomplete arms cannot become valid effects. Covers review R1–R2. |
| W1 | Metric and model contracts: mechanism inventory, ODD description, units, quote/trade distinction, corrected CPI description, proposed price metrics | None; W0 for campaign receipts | 3–5 days | Every headline series has formula, currency, population, source, window, missingness, version, and a reproducible fixture. Covers R4/R6. |
| W2 | City context repair: shared run/fork/tick, historical queries, capability empty states, explicit playback clock | None | 2–4 days | Historical Live City matches analytical City; no live status is requested for historical playback. Covers R3/R9. |
| W3 | Dual price benchmark suite: goods allocation/price response and equity auction/liquidity/price response, with policy baselines | W0, W1 | 5–9 days | Both domains have known-answer mechanical cases and paired policy studies; report coverage and uncertainty, even for null findings. |
| W4 | Integrated city and Price Discovery Lab: shared inspectors, linked charts, intervention draft, paired comparison, export | W0–W3 | 7–12 days | A researcher completes the seven-step v1 workflow for both price domains through the UI. |
| W5 | Households and demographic identities: child/person records, membership, partnerships, care, inheritance, migration modes | W0, W1 | 8–14 days | Birth → dependent → adult transitions and estate settlement preserve identity, assets, and cohort accounting in an offline fixture. |
| W6 | Education and labor capacity: schools, enrollment, attendance, skill accumulation, credentials, time allocation | W5; W1 metric contracts | 6–10 days | Capacity/funding/time-constrained education affects measured skills and eligible job matching without guaranteed employment. |
| W7 | Production and spatial housing: recipes/suppliers, capital, housing occupancy/rents, materials-backed construction and transport | W1, W3, W5; W6 for school locations | 10–18 days, split into at least 3 PRs | Shortages, rents, and completed places have counterparties and physical-stock reconciliation; no invented travel-time benefit. |
| W8 | Financial depth: cash-flow/disclosure/ownership links, bank balance-sheet regime, credit risk, optional intraday market scheduler | W1, W3; W7 for richer firm cash flows | 10–18 days, split by contract | Deposits, loans, reserves, capital, defaults, shares, and corporate actions reconcile; study artifacts distinguish funding regimes. |
| W9 | Integrated validation and scale: held-out moments, prompt/model sensitivity, demographic horizon, 1,000-agent measurements | W3–W8 | 5–10 days plus campaign time | Publish a reproducible evidence package with model limitations, cost/fidelity curves, and independent holdout results. |

W1 and W2 can be implemented independently of each other after a shared branch
inventory. W7 and W8 are equally ranked economic tracks: split them into small
slices and alternate delivery so finance does not become a last-minute add-on.
This ordering describes dependencies, not an instruction to start parallel
agents or background jobs now.

### Checkpoint A: trustworthy foundations

Complete W0–W2. Correct the verified research/UI defects before adding new
mechanics. Retain failed campaign artifacts. Describe today's CPI accurately;
keep historical series intact. Inventory existing replay, projection,
construction, calibration, and campaign code before adding equivalent modules.

### Checkpoint B: first usable research product

Complete W3–W4. Ship Price Discovery Lab v1 with one goods experiment and one
equity experiment, the same inspector and comparison workflow, and clear
profile capabilities. Use current adults, firms, banks, and institutions.
Obtain usability evidence from task completion rather than choosing a new
visual framework based only on screenshots.

### Checkpoint C: living economic society

Complete W5–W8 as versioned opt-ins. Demonstrate a child aging into education
and employment using an appropriately aged initial cohort, then run a true
multi-decade offline campaign. Connect changing household needs, rent, labor
supply, firm output, financing, and share prices. Keep a simpler benchmark
regime for every added mechanism so its contribution can be measured.

### Checkpoint D: research evidence

Complete W9. Establish fitness for named questions, not a blanket claim to
simulate the real economy. Successful negative findings are publishable
outcomes. Operational success, repeatable behavior, and empirical fit are
separate report sections.

## Experiment program

Use one independent world/seed pair as the treatment unit. Begin with small
offline pilots to estimate variance and runtime. Freeze the final sample size
using precision/power reasoning before a confirmatory campaign; five or ten
seeds is a wiring/variance pilot, not a universal scientific threshold.

| Study | Intervention and control | Main outcomes | Prerequisites |
|---|---|---|---|
| G1: goods allocation | Known buyer reservation values and seller costs; fixed/endowed resources | Gains from trade relative to feasible benchmark, executed prices, rationing, unmet demand | W0–W3 |
| G2: price adjustment | Declared input-cost increase versus unchanged inputs, common initial state | Price pass-through, quantities, margins, stockouts, employment | W0–W3; distinguish existing system-input regime from later supplier network |
| F1: equity price formation | Known redemption-value auction, heterogeneous private valuations, fixed float | Executed-price error versus declared benchmark, efficiency, spread/depth, non-trading frequency | W0–W3 |
| F2: information and liquidity | Timed public/private signal or liquidity withdrawal versus control | Discovery delay, signed price response, volume, price impact, wealth transfer | W0–W3; no latency/HFT claims under daily matching |
| GF1: business-to-asset link | Firm input/demand shock with identical disclosure policy in both arms | Goods price/margin/employment change alongside equity response and financing | W4; strengthen after W7–W8 |
| H1: housing supply | Add funded capacity/permit treatment in a child world versus unchanged supply | Contract rents, vacancy, unmet housing need, household disposable income | W5, W7 |
| E1: education access | Funded school capacity or tuition treatment versus control | Enrollment, completion, skill change, wage distribution, cohort mobility | W5–W6; appropriate multi-year horizon |
| B1: credit supply | Explicit loan underwriting/capital/liquidity treatment | Loan terms, defaults, bank equity/reserves, firm exits, real output, asset prices | W8 |
| D1: generational inequality | Explicit inheritance or migration-regime treatment | Cohort wealth, intergenerational mobility, participation, household formation | W5–W9; 20–40 simulated years |

For goods studies, judge allocations against the declared feasible benchmark;
do not assume posted-price policies must achieve a competitive equilibrium.
For equities, a redemption-value benchmark is available in a laboratory fixture,
whereas an unknown real firm's future value is not observable ground truth.

Every study runs policy ablations: current scripted behavior, a simple adaptive
or bounded-rational baseline, and optionally recorded LLM decisions. Fix or
explicitly vary communication exposure, wake cadence, prompts, model versions,
and core/periphery assignment. Treat a live-provider failure or budget-induced
policy change as an attempt outcome, never an undocumented substitute arm.

## UI experience to implement

Keep a dominant city canvas, a compact layer rail, one selected-object inspector,
and a bottom timeline. The inspector coordinates People, Institutions, Markets,
and Evidence Lab rather than duplicating their entire pages. Offer an accessible
list/table equivalent for every map selection and layer.

| Action | User-visible result | Economic authority |
|---|---|---|
| Click/follow a person | Household, employer/school, income sources, current need, relationships, and evidence at this tick | Read only; expose only authorized fields |
| Click a business | Prices, sales, inventory, workers, suppliers, loans, owners, and listed security | Read only |
| Click a bank | Authorized balance-sheet view; public status otherwise | Read only; no new access from selection |
| Choose a layer | Rent, wages, unemployment, prices, inventories, credit, education, construction, or information | Read-time projection with units and coverage |
| Scrub timeline | Historical city and charts resolve together; outstanding requests cannot overwrite a later selection | Read only |
| Play recorded day | Interpolate documented positions with a separate playback speed/pause | Changes display time only |
| Run/step world | Advance the authorized live simulation through existing server controls | Canonical engine mutation |
| Preview a school or policy | Show site, payer, cost/capacity assumptions, effective tick, and expected affected mechanisms | Draft only; no unmeasured promised benefits |
| Run this experiment | Create a declared child attempt and execute through ordinary validation | Explicit operator command; source remains unchanged |
| Compare worlds | Synchronized treatment/control map, trajectories, distributions, and paired effects | Read only |

Do not present unavailable household, school, rent, or supplier data as existing
facts during the earlier milestones. Disabled layers explain their required
model capability. A skyline may be a visual encoding; commute costs may only
come from a separately implemented transport mechanism.

## Engineering and compatibility rules

- All monetary effects remain in the engine/ledger. Add physical-stock and
  balance-sheet checks alongside the existing cash invariant.
- Reuse recorded action, event, causal, export, and replay interfaces. Do not
  replace FastAPI/SQLite or add a second authoritative simulation in the UI.
- New economic behavior gets a new semantics contract. Allocate actual schema
  and semantics numbers at implementation time after inspecting the then-current
  maximum; this plan reserves no version number.
- Historical sources stay read-only. A child may explicitly opt into a new
  contract only at a verified compatible boundary with recorded lineage.
- Partition randomness by mechanism and stable actor/event identity for new
  contracts; verify pairing rather than equating a shared integer seed with
  identical later shocks.
- Research models should report exogenous subsidies, endowments, and system
  procurement. Do not force stability by silently rescuing a failing economy.
- Keep forecasts and explanatory model prose downstream of evidence. A causal
  trace supports a mechanism account; a controlled contrast supports a treatment
  effect conditional on the model.
- Preserve external citizen identity and runtime ownership. Human participant
  actions and uncontrolled external runtimes require explicit influence labels.
- Publish a new static dashboard bundle with any later UI source change,
  following the existing development contract.

## Acceptance and rollback

Every behavioral slice needs success, refusal, duplicate/retry, interruption,
resume, replay, and reconciliation cases. Add property tests for shared
resources and lifecycle collisions; use exact small examples for prices,
quantities, and accounting rather than tests that repeat production formulas.
Keep feature-specific tests small and run the maintained release gate before
integrating a completed milestone.

UI acceptance covers keyboard navigation, Back/Forward, direct links, stale and
failed responses, live/historical separation, authorization, reduced motion,
WebGL fallback, and 390/768/1440 px widths. Performance budgets and measurable
task scenarios are specified in the companion document.

Rollback means disabling the new feature for new worlds and keeping its
recorded semantics executable for existing worlds. Never downgrade or rewrite
a research database. A failing attempt remains a failing attempt; a corrected
rerun receives a new identity.

## Start-here handoff for the future executor

1. Read this roadmap, the review's R1–R4 evidence, and specs S1–S3.
2. Inspect current HEAD, dirty work, branch/worktree ownership, instructions,
   graph freshness, and maximum schema/semantics. The review is dated.
3. Start with **W0: counterfactual preservation and eligibility**. Inspect the
   stricter existing campaign and replay contracts before writing a new one.
4. Create a small regression fixture for collision preservation and the R2
   mismatched-horizon diagnostic. Specify metric missingness and attempt
   status before implementation.
5. Complete W0 with passing focused tests and documentation, then W1/W2.
6. Implement the remaining packages in dependency order, updating this plan's
   status through links to real commits and verification receipts.

Do not execute future YAML/API sketches from the specifications as though they
are implemented commands. They are design contracts for later work.
