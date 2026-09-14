# Agent Economy: proposed research city specifications

Date: 2026-09-06. Status: **Implementation in progress; see the execution log for delivered contracts**.
Companions: [review](2026-09-06-research-city-review.md) and
[delivery roadmap](2026-09-06-research-city-roadmap.md).

All new type, table, route, metric, and file names below are proposed contracts.
They do not exist merely because they appear here. Reuse an equivalent existing
contract when source inspection establishes one. Preserve the current
[architecture](../architecture.md), [development](../development.md), and
[status authority](../implementation-status.md).

## S1. Research contract and experiment integrity

Work packages: W0–W1. Existing seams: `research/scenarios.py`,
`research/counterfactual.py`, `experiments/harness.py`, `research/hashing.py`,
`research/export_bundle.py`, `world/replay_verify.py`, `reports/oracle_campaign.py`,
and `run.py`.

### Model description

Produce a maintained `docs/research/model-description.md` using ODD's purpose,
entities/scales, scheduling, design concepts, initialization, input data, and
submodels. Link to the actual source for each mechanism. For every mechanism
record whether it is an accounting constraint, externally specified process,
scripted/adaptive policy, recorded LLM decision, or visual derivation.

Each supported question declares its relevant mechanisms, ignored mechanisms,
units, horizon, agent information, and evaluation patterns. Avoid one global
claim that the entire model is realistic. Preserve the older model descriptions
and cite their versions from immutable study manifests.

### Study manifest

Implement a strict `StudySpec` validator, preferably beside the existing
scenario-pack loader. Reject unknown fields and incompatible capabilities.
Required fields:

| Field group | Required contents |
|---|---|
| Identity | Study key, protocol version, canonical manifest digest, creation provenance |
| Question | Hypothesis, estimand, treatment unit, primary outcomes, exploratory outcomes |
| Model | Commit/tree identity, engine semantics, schema contract, resolved configuration digest, feature/regime list, model-description version |
| Inputs | Dataset vintage/transform/hash, calibration targets, separate holdout manifest, scenario/initial-state digest |
| Arms | Named baseline, treatment differences, intervention timing, information/exposure policy; all other differences explicit |
| Randomness | Fixed seed list, seed roles, mechanism-stream version, pairing policy, any model replicate IDs |
| Behavior | Policy family/version, prompt digest, exact provider/model/endpoint reference, sampling settings, wake/communication cadence, core/periphery assignment |
| Time | Tick duration, warm-up window, intervention window, measurement window, horizon, declared stop rules |
| Analysis | Units/currency, metric versions, aggregation, pairing, missing-data policy, uncertainty method, minimum usable pairs, multiple-outcome policy |
| Operations | Provider-free or explicitly live execution, bounded calls/tokens/spend/time/disk, concurrency cap, pause/failure policy |

Provider secrets remain environment/credential references. A manifest must not
contain their values. Code or prompt changes produce a new manifest identity.
Historical and synthetic ex-post analyses are labeled as such; do not call
them preregistered because a manifest was written afterward.

### Attempt storage and state

Use a unique attempt ID within an immutable study namespace, for example:

```text
data/experiments/<study-key>/<manifest-digest>/<cell-id>/<attempt-id>/
  source.db
  replay.db
  attempt.json
  source-receipt.json
  replay-receipt.json
reports/out/studies/<study-key>/<manifest-digest>/
  analysis-<receipt-digest>.json
  findings-<receipt-digest>.md
```

The example is a proposed layout. Never unlink a source because a path already
exists. Use exclusive creation and a single-writer claim. A mutable working
attempt becomes an immutable artifact when finalized; operational progress is
kept separately from the frozen protocol.

Keep execution and eligibility separate:

- Execution: `planned → initialized → running → paused | completed | failed`.
- Eligibility: `pending → eligible | ineligible`, with explicit reason codes.
- A paused compatible attempt may resume. A failed or finalized attempt gets a
  new attempt ID for another execution. Neither branch overwrites its predecessor.
- A completed run requires a committed final boundary and the runner's declared
  stop condition; a temporary server Paused badge is not a completion receipt.

Resume checks manifest, code contract, provider policy, database integrity,
phase state, and attempt ownership. Incompatibility refuses resume and preserves
the original. Publication uses temporary files plus atomic finalize. Crashes
between source, replay, and report leave the attempt pending/ineligible, never
implicitly complete.

The committed-day implementation now includes supervised CLI and local operator
resume, a separate working-study library view and portable working evidence.
Read compatibility is independent of execution compatibility; a changed checkout
may read a frozen checkpoint but cannot resume it. Operator continuations bind
the original job/context, progress hash, validation hash and cumulative budget.
Opt-in phase recovery now verifies the exact saved phase, all three PRNG streams,
queued-state digest and every earlier admitted-input prefix. Incomplete days
have no study measurements. CLI and reviewed operator step pauses use the new
protocol; existing saved-day studies retain their original contract. The detailed contracts and commands are
in [paused-study recovery](2026-09-06-paused-study-resume.md).

### Eligibility and causal pairing

Before estimating a confirmatory effect, require the declared measurement
window, valid final boundary, ledger and added stock invariants, no disallowed
participant/external influence, compatible information/treatment policy, and
source/replay receipts bound to exact artifacts. Check common initial state with
canonical table hashes or a verified common checkpoint; an event-only genesis
digest is insufficient proof of state identity.

A field called replay hash must identify a completed replay comparison. Keep
the ordinary event digest under a different name. Replay reads the source
without migrations and writes a fresh database; all canonical tables required
by that semantics contract must compare exactly.

Common seeds do not guarantee common later exogenous shocks when a treatment
changes the number of RNG draws. For new semantics, use independently keyed
streams by mechanism and stable entity/event ID. Keep exogenous schedules
paired while allowing endogenous outcomes to diverge. Preserve historical RNG
contracts. Fresh live LLM arms can remain stochastic even at temperature zero;
record their realized decisions and evaluate across independent replications.

Implementation checkpoint: [Semantics 16](../semantics16-randomness.md) supplies
daily mechanism/origin keys, version-bound study declarations and request-cache
seed binding. Common-key isolation, G2/F2 pause/resume and replacement-arrival
replay are verified. Genesis initialization and within-policy branching retain
their documented limits; confirmatory design remains unsupported.

Attempt failure and economic failure differ. A correctly reconciled bankruptcy,
market freeze, or societal collapse is an economic outcome. A crash, missing
response, or truncated horizon is an execution/measurement outcome. Predeclare
how each contributes to the estimand. Report failure rates for all assigned
attempts; do not silently estimate on surviving successful worlds alone.

### Result contract

Every effect includes assigned/started/completed/eligible attempt counts,
matched usable pair count, exclusion reasons, measurement windows, unit,
metric version, point estimate, and interval method. Missing data is `null`
with a reason. Never return zero effect or a zero-width interval for no pairs.
With fewer pairs than the preregistered minimum, show descriptive observations
and `insufficient_replication`, not confirmatory confidence.

Use paired differences by seed/world. Bootstrap whole pairs, not daily points
or individual citizens, for between-world effects. Within-run time-series
inference requires a separately declared dependence-aware method. Standardized
effect is undefined when its denominator is zero. Label exploratory outcomes
and sensitivity searches; preserve all planned negative results.

### Acceptance cases

1. A second identical launch preserves the first source/report hashes and
   either refuses the duplicate or creates a new explicit attempt.
2. An interrupted arm at tick 3 cannot enter a tick-30 complete-window effect.
3. An unreconciled arm, wrong manifest, changed policy, or false replay receipt
   produces a named ineligibility result.
4. Missing/all-missing outcomes and unmatched seeds produce explicit coverage
   and null effects; one pair cannot produce a confirmatory confidence claim.
5. A valid bankruptcy remains an eligible economic observation under its
   declared complete-horizon rules.
6. A fork retains source hashes and complete common-state equality. A later
   promotion, message, or new birth cannot change paired exogenous hazards for
   unrelated pre-existing actors under the new stream contract.
7. Rejected and interrupted attempts remain discoverable in exports and UI.

## S2. Price discovery and measurement

Work packages: W1, W3, W8. Existing seams: `engine/exchange.py`,
`engine/firms.py`, `engine/labor.py`, `engine/credit.py`, `engine/regions.py`,
`world/metrics.py`, `server/projections/workspaces.py`, and market/report code.

### Two equally supported domains

Every study catalog, summary, and comparison offers both **real-economy prices**
and **financial-market prices**. The first release measures goods and equities;
wage, housing, credit, and FX panels activate only when their data contracts
support the requested measure. A quoted price, transaction price, appraised
value, and latent benchmark are distinct fields.

Create a versioned metric registry. Each entry contains definition, source
rows/events, currency or numeraire/FX convention, time scale, aggregation
weights, eligible population/instruments, availability, and missing/stale rules.
Retain the current `cpi` values and identify them as the legacy posted-price
index. Fix its guide text before adding a new series.

### Proposed observations and formulas

| Measure | Contract |
|---|---|
| Goods posted price | Seller's effective posted price, product/category, quantity unit, currency, tick, and last-change time; not proof of a purchase |
| Goods executed price | For a comparable product and window, `sum(total_paid_cents) / sum(quantity)` from successful sales; null if quantity is zero |
| Goods price index | Fixed baseline quantity/expenditure weights with a declared comparable basket. Formula and coverage use the same eligible items in numerator/denominator; no silent survivor reweighting |
| Missing/stale goods prices | Report observed basket share, last-trade age, and failed categories. Carry-forward is an explicit versioned option with a maximum age; otherwise insufficient coverage gives null |
| Demand and rationing | Intended quantity, affordable quantity, fulfilled quantity, and rejection/stockout reason; unmet demand cannot be inferred from sales alone |
| Wages | Distinguish offered contractual rate, accepted rate, pay interval, scheduled hours, and actual wage payments. Convert comparisons to a declared common period |
| Rent | Distinguish asking rent, executed lease rent, vacancy, occupancy, and arrears; the legacy arrival housing charge is not a market rent observation |
| Credit | Requested/offered/accepted amount, APR convention, fees, term, collateral, rejection reason, and realized loss; no combining unlike maturities without labeling |
| Equity price | Last actual execution plus its age; null before the first trade. Quotes/midpoints remain separately named measures |
| Equity spread/depth | Best bid/ask and displayed available quantity at a defined session boundary. Spread is null with a missing side; no daily last-price series masquerading as intraday quotes |
| Equity returns | Execution or declared marked-price sampling with stale-trade flags, dividends/corporate-action adjustment, and currency convention |
| Discovery benchmark | In induced-value fixtures, distance from the declared equilibrium interval or redemption value; in endogenous firms, analyst/model valuation is an estimate, never known fair value |
| Market response | Signed price response, volume, spread, depth, fill/cancel rates, discovery delay, concentration, and price impact with exact sampling definitions |

For a fixed basket with quantities `q0[g]`, index at time `t` is
`100 * sum(q0[g] * p[g,t]) / sum(q0[g] * p[g,0])` for the preregistered complete
basket or explicit missing-price policy. Do not average NSD, IVC, and SCD cents
without a stated conversion. Report region/currency series before any global
aggregate; changes in FX must be distinguishable from domestic inflation.

Initially derive read-only measures from existing trades, wage/loan records,
goods-sale events, and ledger evidence. When existing events omit necessary
facts, add immutable normalized observations for future ticks; do not invent
historical demand, order cancellation time, or reservation values.

### Exchange behavior and benchmarks

Retain the current price-time matching and resource revalidation. Audit and
define same-beneficial-owner matching, cancellation/expiry, resource
reservation, partial fills, fees, outstanding shares, bankrupt/delisted firms,
and resting-order behavior across corporate actions. Add only the mechanisms
required by the first benchmark; reserve changes for new semantics.

Start with a single-asset induced-value market using explicit cash/share
endowments and predictable submitted orders. Test crossing/non-crossing books,
ties, partial fills, no first price, illiquidity, insolvency, cancellation, and
closed instruments. Compare allocation against the feasible surplus benchmark.
Then add noise/adaptive/LLM traders with declared information and objectives.
Risk/noise should not guarantee a desired price trajectory.

For real firms, connect securities to ownership, disclosures, operating cash
flows, financing, dividends, dilution, and bankruptcy recovery. Add a minimal
dividend/corporate-action contract before interpreting total returns. A rise
in share price is not GDP or new firm funding unless a primary issuance or
other explicit transaction transfers funds to the firm.

If intraday research is needed, add deterministic `session_id` and `event_seq`
with an optional simulated time within the MARKET phase. Record message/delay
rules and aggregate once into the daily world. Biology, wages, interest, taxes,
and production still advance on their declared schedules. Daily matching
cannot support claims about latency arbitrage or high-frequency microstructure.

### Acceptance cases

- Reconstruct measured prices and volumes independently from a tiny ledger and
  trade fixture; invalid orders and mere quotes cannot create executions.
- An empty book and an illiquid stock show missing price/return information.
- Changing unit labels or FX rates cannot silently alter domestic price series.
- Same-owner trades cannot inflate qualified discovery/volume evidence under
  the new market policy; resource totals and shares reconcile.
- A corporate action preserves cash/ownership totals and adjusts return
  calculations correctly; delisting stays visible in cohort results.
- Both G1/G2 and F1/F2 from the roadmap produce inspectable reports with equal
  coverage, not just one functioning market panel.

## S3. Interactive city and research workbench

Work packages: W2, W4. Reuse `LiveCity.tsx`, `CivicCity.jsx`, existing diorama
components/helpers, `WorldWorkspace.tsx`, `PeopleWorkspace.tsx`,
`MarketsWorkspace.tsx`, `ExperimentsWorkspace.tsx`, shared observer routing,
`useWorkspaceProjection`, and authorized server projections.

### Shared observer state

One state contract carries `runId`, `forkId`, `tick: number | live`, renderer,
layer, selected entity, filters, and camera. The public URL retains existing
`fork`, `tick`, `view`, `agent`, `place`, and `project` compatibility. New
household/institution selections get validated discriminated types. Keep the
existing mutually exclusive selection rule and retain legacy deep-link aliases.

Implemented camera/follow contract: `camera=x,y,zoom` admits x/y 0–100 and
zoom 1.8–5.4; `follow=<positive person ID>` fixes one identity and implies that
person's selection. Renderer changes, tick changes, filters and reload preserve
follow. A missing, hidden, dead or unlocated target pauses it rather than selecting
a replacement. Atlas/Diorama follow only public observed positions; recorded day
follows public recorded placement geometry on its display clock. Selecting a
different object or manually panning stops follow; zoom preserves it. Continuous
follow motion creates neither observer-history entries nor economic mutations.

Projection cache keys and requests include run, fork, tick, authorization scope,
and relevant filters. Ignore late responses for another cursor. Navigation
preserves shared state; cross-run comparison uses two explicit state objects.
Never use a live local endpoint merely because a historical endpoint is missing.

First fix the reproduced Live City tick bug by moving its reads onto this
contract. If a requested legacy run cannot reconstruct a frame, show unavailable
data with its reason. Do not use the current frame under a historical URL.

### Rendering and interaction

Retain the existing renderer choices, but give them shared selection,
inspectors, layers, and timing. Draw original district/building silhouettes
whose types and size encodings match available model fields. Completed
construction becomes operational only after the canonical completion event.
Mark construction progress from exact work units, not elapsed animation time.

At desktop width, target at least 65% of the main workspace area for the map
with the inspector open; collapse optional instrumentation. A top strip carries
run identity, tick, mode, and essential controls; the bottom strip carries
history/playback. On narrow screens use one selected-object sheet and a list
view, keeping the primary controls visible without sideways scrolling.

Required interactions: pan/zoom/reset, select/follow, keyboard object explorer,
search, selected-object breadcrumbs, thematic layers with legends and units,
linked charts, event bookmarks, and return to an exact prior selection.
Reuse existing controls where they work. Tooltips are supplementary; all
critical information is available in a focusable inspector/table.

Separate three meanings of time:

| Mode | Controls | Required wording/behavior |
|---|---|---|
| Live world | Run, Pause world, Step one day | Existing authenticated/authorized server commands; disabled on missing/stale/terminal authority |
| Historical cursor | Tick scrub, jump/bookmark, return Live | Read-only frame; no current provider activity or live status fetch |
| Recorded-day playback | Play/Pause animation, playback speed | Display-only interpolation within a selected recorded tick; never advances the world |

Historical snapshots snap between arbitrary ticks. Optional playback within a
tick clearly labels the interpolated segment and recorded anchors; it does
not claim actual journeys. Reduced motion retains selectable anchors and
suppresses interpolation. Runtime queued/thinking telemetry is live-only and
never substitutes for a settled action.

### Object inspector and prices

A common inspector header shows entity, selected tick, evidence class, and
visibility boundary. Tabs show only supported fields:

- Person/household: members, age/stage, school/job, care/time commitments, budget,
  purchases, assets/debts, relations, and event history.
- Firm: products, quote versus execution, quantities/inventory, workers/wages,
  suppliers, capacity, finance, owners, disclosures, and equity chart.
- Bank: public status or authorized balance sheet, lending terms, defaults,
  funding/liquidity, and evidence.
- Place/school/project: capacity, use, occupancy, funding, staff, exact stage,
  and the relevant economic records.

A Goods/Assets switch in the price laboratory shares selected entity, time
range, and comparison. Plot price with quantity/liquidity and information
events so a single line cannot hide no trading. Explain an episode with linked
facts and explicitly labeled hypotheses; do not let a prose generator declare
causality from correlation or access a citizen's hidden information.

### Experiment workflow

Use a separate operator surface within the workbench for Draft → Validate →
Run → Compare → Export. The observer UI itself remains read-only. Drafting a
school/site/policy intervention shows the target, payer, amount, capacity,
effective tick, allowed mechanism, and estimated computational budget. No
economic benefit is promised without a model result.

A deliberate Run command validates authority, anti-CSRF protections where
applicable, exact parent checkpoint, expected revision, manifest digest, and
idempotency key. It creates a child attempt; it never changes the source world.
No free-form Python, SQL, shell, or model-generated code is an intervention.
Participant play uses the existing citizen action validator and labels the
world as participant-influenced.

Proposed logical API contracts, to adapt to existing local/hosted routers:

| Endpoint | Proposed contract |
|---|---|
| `GET /api/v2/research/capabilities` | Named model/metric/intervention capabilities and reasons unavailable, scoped to run and caller |
| `POST /api/v2/research/studies/validate` | Strict spec validation and resource estimate; no execution |
| `POST /api/v2/research/studies` | Persist a validated immutable study draft/manifest under operator authority |
| `POST /api/v2/research/studies/{id}/attempts` | Create/start a bounded idempotent attempt with explicit source/arm; deny stale revision or unsupported treatment |
| `GET /api/v2/research/studies/{id}` | Attempt state, evidence/eligibility, coverage, and artifacts |
| `GET /api/v2/research/comparisons/{id}` | Authorized paired outcomes with matching dimensions, missingness, and lineage |
| `GET /api/v2/market-observations` | Cursor/windowed goods and asset observations with metric definitions, units, source references, and pagination |

Reuse available run/experiment APIs instead when they meet these contracts.
HTTP 403 means denied authority, 409 means identity/revision/state conflict,
and 422 means invalid/unsupported model input. A successful validation does not
mean an attempt has run. Hosted tenant scoping must be server-enforced; URL
identifiers cannot grant cross-tenant access. Export paths/credentials/private
communication are not exposed through these public response envelopes.

### UI acceptance

1. At world tick 3, open City with tick 1: all labels, places, people, events,
   and links remain at tick 1; a request spy sees no live runtime/status request.
2. Navigate City → person → firm → market → evidence and Back: run/fork/tick and
   validated selection remain consistent. Repeat with delayed/out-of-order data.
3. Inspect a person, a business price, and an equity trade by keyboard alone;
   camera/pointer operations have equivalent controls.
4. A non-city profile explains unavailable placements and offers useful
   regional/table data instead of an endless loading state.
5. Simulation pause and playback pause visibly do different things; returning
   Live is explicit. WebGL loss falls back to Atlas/list without losing context.
6. A study preview causes no economic write. Duplicate execution clicks create
   one attempt, with conflicts surfaced and drafts retained.
7. At 390/768/1440 px, the key control and selected object's explanation are
   reachable; dialogs manage focus and chart colors have text/shape equivalents.
8. In a small usability session, at least 4 of 5 users can find a price change,
   inspect its recorded inputs, and locate a paired comparison without coaching.
   Treat this as a proposed product acceptance target, not a result obtained now.

## S4. Agent objectives, learning, and fidelity

Work packages: W3, W5–W9. Existing seams: `agents/policies.py`, scheduling,
prompt/context builders, memories, recorded LLM gateway, and cognition skills.

Give each policy the same authorized observation and feasible action schema.
Persist decision-policy family/version, observation/proposal hashes, origin,
acceptance/rejection reason, and cost. Keep numeric commitments and a concise
stated justification; do not treat hidden reasoning or model prose as ground
truth about why an action caused an outcome.

Household preferences include needs by good category, substitution, saving
buffer, risk, leisure/care time, and beliefs. Firm objectives include expected
profit, liquidity/runway, demand, capacity, hiring, and investment. Investor
preferences include horizon, risk, information, and inventory/liquidity limits.
Heterogeneity should come from explicit distributions and learning rules as
well as persona text. Record distribution sources and inspect their sensitivity.

Implement three comparable families: existing scripted policies, a simple
adaptive/bounded-rational baseline, and recorded LLM decisions. Use offline
microtasks for budget feasibility, dominance, price response, search, saving,
portfolio risk, and learning after a known regime change. Separate decision
competence from measured preferences and from similarity to human data.

Keep core/periphery scheduling, but stratify or randomize assignment for
experiments. Do not automatically give the richest/most central agents better
cognition and then attribute an inequality difference solely to economic
mechanics. Compare fixed and promotion-enabled policies explicitly. All people
keep canonical identity/assets regardless of cognition tier.

Event-triggered LLM decisions can reduce cost, but their cadence is a research
assumption. Estimate calls, tokens, latency, and cost before live execution;
record every degradation/pause. New confirmatory studies refuse an undeclared
mid-attempt provider, prompt, or policy substitution. Exact offline replay uses
recorded responses; fresh model calls are a different replication.

## S5. People, households, and generations

Implementation checkpoint: [Semantics 15](../semantics15-households.md) implements
person origins, births, basic household membership/separation/custody, age
eligibility, child food demand, demographic keyed draws and census.

[Semantics 17](2026-09-07-household-decisions.md) adds mutual partnership assent,
separation with primary minor wards and atomic joint household migration.
[Semantics 18](2026-09-07-daily-time-and-earned-wages.md) adds delivered care,
shared daily time, proportional labor/output, non-cash earned wages and recorded
claim settlement, inheritance and write-off. Full estates, business succession,
cohort and long-horizon validation remain required; these checkpoints do not
close W5. Enrollment, attendance, credentials and education capacity remain W6.
[Semantics 19](2026-09-07-estate-cash-and-credit.md) records the positive-cash and
bank-principal waterfall per currency, including equity charge-offs. Full asset
and obligation disposition, late receipts, minor custody and succession remain.

Work package: W5. Existing seams: `engine/lifecycle.py`, `world/genesis.py`,
`World._spawn_due_arrivals`, ledger ownership, social ties, and Living Agents
projections. Preserve the existing person/agent identity space.

### Proposed canonical entities

| Entity | Essential fields and constraints |
|---|---|
| Person extension | Existing agent ID, immutable simulated birth date or genesis age basis, birth/arrival provenance, life stage, death tick; never reuse a deceased identity |
| Household | Stable ID, region, formation/dissolution ticks, policy, optional shared account; household is distinct from individual |
| Membership | Household/person, role, joined/left ticks, primary-residence flag; at most one active primary household per person |
| Kinship/guardianship | Typed relation, parties, start/end, provenance; symmetric partnership represented consistently; no self-parent or ancestry cycle |
| Household commitment | Payer/beneficiary, currency, amount/time obligation, effective interval, source contract |
| Estate | Deceased owner, asset/debt inventory, creditor settlements, heirs/shares, residual/custody destination, finalization evidence |

Person age advances from simulated time; changing an education/market schedule
cannot change aging speed. Children have persistent state with inexpensive
deterministic policies; they do not require one LLM process each.

### State transitions

Birth creates one person, guardianship, and household membership in one
transaction. It changes care needs and household demand; it does not mint an
adult's arrival endowment. Households form through a declared matching rule or
compatible accepted proposals. Partnership changes require both parties'
recorded assent where proposal-based, rather than a unilateral identity edit.

Child → student → adult eligibility is age/time-based with explicit overlapping
states; studying and working can coexist only within a finite time budget.
Adulthood does not guarantee a job, house, spouse, or wealth. Household departure,
separation, migration, retirement, and death settle their commitments and
preserve history. A guardian's death requires an explicit custody/care outcome,
not deletion of dependents.

Start with a small deterministic household formation/dissolution rule. Make
fertility hazards and migration schedules declared scenario parameters; only
later compare resource- or preference-dependent family decisions. Do not encode
assumed differences by protected demographic labels without a justified model
question, sourced parameters, and appropriate review.

Keep population modes distinct: existing stable adult replacement, explicit
open migration, and endogenous demographics. Births, deaths, arrivals,
departures, and household changes reconcile as a census identity each tick.
System endowments and migration wealth transfers are separately reported.

### Money, assets, and compatibility

Personal accounts remain personally owned. Shared spending uses an explicit
household account or recorded member contributions, with no duplicated asset
ownership. Household wealth aggregates each underlying claim once. Minors'
assets have an explicit custody policy; custody is not beneficial ownership.

Estate settlement handles all declared currencies, bank loans, securities,
housing rights, business ownership, and shared obligations with an explicit
creditor/heir waterfall. Cross-currency settlement requires a valid exchange or
separate currency settlement; it cannot net unlike currencies. Reconcile bank
loss/equity effects as well as the estate's cash transfers.

Do not invent named children or family histories for legacy `dependents`.
Legacy worlds retain the aggregate field. An opt-in child-world initialization
may generate synthetic initial households with recorded assumptions and no
claim to reconstructing the past. Derived legacy dependent counts and the new
membership model cannot both independently increase consumption.

Acceptance: atomic duplicate birth, guardian loss, household split, orphaned
commitment, adult transition, retirement, multi-currency estate, owner death
during a project, same-tick death/migration, and exact replay. Use cohort fixtures
near age thresholds, then a true multi-decade provider-free run.

## S6. Education and human capital

Work package: W6. Extend existing `study_skill`/XP contracts, firms/institutions,
employment, places, and civic time allocation. A school is an institution with
a place, finite seats, staff, funding, and a curriculum; it is not a visual
building plus automatic skill growth.

Proposed entities: school/program, enrollment, attendance/time allocation,
curriculum/version, assessment/credential, and funding agreement. Enrollment
links person, institution, start/end, funding source, and progress. Seats and
teacher capacity constrain admission. Tuition, wages, subsidies, and refunds
flow through existing ledger mechanisms; no funds disappear into unexplained
new accounts.

Skill gains depend on attended time, curriculum, supported quality/capacity,
and bounded learner factors. Credentials and accumulated skill are separate.
Job eligibility and output can depend on explicit skill requirements and
production functions, rather than granting a wage increase merely for
enrollment. Record the opportunity cost of study and parental care.

The daily allocation of work, study, care, civic obligations, travel, and leisure
must not exceed an individual's time budget. Existing Semantics-12 appointments
already affect productive presence; reuse that authority instead of allowing
schools to assign the same hours twice.

Acceptance: oversubscribed admission, unpaid tuition, staff shortage, missed
attendance, dropout/refund, completion, mature-age retraining, time conflicts,
school closure, and skill/job effects. Education-access experiments measure
both admitted and rejected cohorts and retain pre-treatment characteristics.

## S7. Production, housing, and the spatial economy

Work package: W7; split into independently reviewable contracts.

### Supplier production and capital

Add product categories/units, recipe versions, inventory lots, supplier orders,
deliveries, and capital stocks. For a recipe, feasible production is bounded by
available labor time/skills, capacity, and each input quantity. Consumption of
inputs and creation of outputs are atomic stock movements. Working-capital
payments use recorded supplier contracts.

Begin with a small network of three to five product categories and two stages
of production. Demand comes from household needs and firm input orders.
Preserve an explicit system-supplier mode for comparison. A shortage can reduce
output; the engine must not buy unlimited hidden supplies just to maintain it.
Depreciation, spoilage, capacity investment, and bankruptcy liquidation are
named processes with rates, inventories, and accounting counterparties.

### Housing, land, and construction

Reuse Semantics-13 proposals, permits, escrow, paid work, cancellation, and
single-place completion. Add dwelling capacity/quality, housing listings,
leases, owner/tenant rights, rent obligations, vacancies, and occupancy history.
Households bid/search under budgets and location preferences. Scarce housing
can leave needs unmet; an arrival charge is not a lease or a permanent home.

If land or zoning is modeled, use canonical parcels with permitted use and
capacity, distinct from a renderer's decorative site. Construction consumes
funded work and explicit material deliveries in the new regime. The old
system-materials regime stays available and labeled. Cancellation handles
unused funds and materials; capacity appears only on completion.

Transport starts with an explicit graph or documented coarse region cost
matrix. Routes, travel times, and delivery costs affect feasible schedules and
profit only when that mechanism exists. Straight-line map interpolation has no
economic effect. Road/site previews show costs and assumptions, not guaranteed
future demand or commuting savings.

Acceptance: stock shortage, partial delivery, unit/currency mismatch, competing
input uses, capacity ceiling, rent arrears, double occupancy, housing transfer,
cancelled construction refund/material return, duplicate completion, and
historical private-home aggregation. Test a funded housing-capacity treatment
against control without adding free money or hidden utility changes.

## S8. Banking, financing, and market depth

Work package: W8. Keep the existing reserve-funded loan regime as a named
benchmark. Add a separately versioned commercial-bank balance-sheet regime
only after an accounting design and small exact examples are reviewed.

Represent reserves/settlement balances, loans, deposits, funding liabilities,
equity, accrued interest, provisions/losses, and collateral claims by owner and
currency. One source of truth must connect subledgers and statements; do not
create independently mutable bank balance sheets beside the cash ledger.

The new regime needs these transactions:

| Event | Required accounting/economic contract |
|---|---|
| Loan origination | Bank loan asset and deposit liability; borrower deposit claim and debt; explicit capital/liquidity/underwriting constraints |
| Customer payment | Transfer the deposit claim; settle across banks through reserves or an explicit settlement-credit facility |
| Principal repayment | Reduce loan/debt and the corresponding deposit claims; avoid treating principal as revenue |
| Interest/fees | Record interest income/expense and cash settlement separately with a declared accrual convention |
| Default/recovery | Apply collateral/cash recovery, recognize net losses/provisions/equity effect, terminate or restructure claims |
| Bank failure | Explicit resolution, creditor/depositor treatment, and any externally funded support; no silent negative reserve rescue |
| Central bank action | Separate reserve creation, lending, asset purchase, and interest-rate policy with named counterparties and bounds |

Balanced ledger legs remain mandatory. A zero global sum does not require
customer deposit money to stay constant: define which account categories enter
money-supply measures. Reconcile assets = liabilities + equity for each
institution and reconcile every issued claim with its holder's asset. Retain
currency-specific reconciliation and report cross-border exposures.

For securities, represent listing, float, ownership, issuance, dividends,
splits/dilution, delisting, and recovery as deterministic corporate actions.
Place firm operating results and disclosures in agents' point-in-time
information sets. Do not give every trader the future payout or private bank
state except in an explicitly omniscient benchmark arm.

Add more liquidity providers, costs, or intraday behavior only when the target
study needs them. Short selling, leverage, derivatives, and external-market
execution are deferred; each would require borrowing, collateral, margin,
liquidation, and additional accounting contracts. No brokerage connection is
needed for the proposed research product.

Acceptance starts with hand-calculated same-bank and cross-bank origination,
payment, repayment, default, and resolution cases; then property tests and
paired credit-supply studies. Legacy reserve-funded worlds replay unchanged.

## S9. Validation, performance, and release evidence

Work package: W9 and per-package acceptance. Maintain three separate claims:

1. **Verified mechanics:** reconciliation, constraints, interruption/resume,
   rejection paths, and exact replay.
2. **Robust simulated behavior:** reproducible distributions, policy ablations,
   mechanism sensitivity, and repeated effects within this model.
3. **Empirical fitness:** named held-out human/economic observations and their
   uncertainty under matched definitions, population, period, and institutions.

Pinned SCF/SUSB initialization is valuable but establishes only selected
starting-distribution fit. Keep calibration targets apart from validation
targets. Evaluate joint moments and trajectories: income/wealth/employment,
firm size/entry/exit, spending and price dispersion, trade/liquidity, defaults,
and cohort mobility as applicable. Match price sampling frequency before
comparing volatility. Do not optimize for a preset count of spectacular
phenomena. Publish failed fits and parameter sensitivity as well as good fits.

LLM versions, prompt variants, action order, seeds, and cognition allocation
can change outcomes. Use declared sensitivity runs and multiple policy
baselines. Avoid treating reported beliefs as measured human preferences or
using the same outcomes to tune and validate the model. External data licenses,
definitions, vintage, and transformations travel with the research bundle.

### Proposed engineering budgets

Measure on a documented reference machine with profile, commit, population,
events, horizon, concurrency, and database size. These are targets, not current
benchmarks:

- At 300 residents, warmed authorized inspector selection p95 < 250 ms and
  historical projection p95 < 500 ms on the reference local setup.
- At 1,000 residents, viewport interaction should sustain at least 30 fps on
  the documented reference GPU or switch to bounded/aggregated rendering;
  input acknowledgement p95 < 100 ms.
- Report cold bundle load/first useful frame separately from warmed queries.
  Cap projection sizes, paginate histories, and bound plotted paths/labels.
- Report wall time per tick, query counts, model time, export/replay time, and
  bytes per agent-tick at 100/300/1,000 residents. Set multi-decade runtime/disk
  budgets from these measurements before committing to larger populations.
- No long-horizon study runs without a storage estimate, checkpoint retention
  policy, and explicit provider cap. Preserve final sources, manifests, and
  receipts; checkpoint pruning must follow the repository's separate approved
  retention process.

Profile the current exchange's repeated book queries/sorts and large
projection paths before optimizing. A semantics-preserving index/query change
must preserve canonical hashes and export schema classification. Do not cache
private or current data across authorization/historical boundaries. Cache
keys identify caller scope and full observer cursor.

### Verification ownership

| Package | Required focused evidence, plus existing regression suites |
|---|---|
| W0 | Scenario loader/counterfactual/export/hash tests, collision and eligibility regression fixtures, recorded replay |
| W1/W3 | Metric reconstruction, no-trade/missing-data fixtures, goods/exchange/credit/labor tests, induced-value benchmark receipts |
| W2/W4 | Live City/Civic City/routing/workspace unit tests; real-backend historical navigation, authorization and study workflow browser tests |
| W5/W6 | Demographic/household/estate/time-budget properties; cohort transitions and education-capacity experiments; replay |
| W7/W8 | Money/claims/physical-stock reconciliation; funding, default, corporate-action and construction collision tests; legacy replay |
| W9 | Fixed manifests, matched attempt coverage, held-out comparisons, prompt/policy sensitivity, resource measurements, export verification |

Before merging a later implementation milestone, run the full local gate in
`docs/development.md`; preserve its warnings/skips in the receipt. For UI
changes regenerate and verify `server/static/`. Update the authoritative
guides/status ledger only for the exact behavior and evidence delivered.
Rollback affects eligibility/defaults for new runs; it never rewrites a stored
world or manufactures a passing receipt for a previously failed attempt.
