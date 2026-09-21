# Jev domain delegation (v4)

Jev can choose among bounded, actor-authorized alternatives for economic and
civic decisions. This opt-in implementation expands the earlier shopping/job
policy. It includes stock orders, business formation, founder operations and
recorded voting. The engine still validates and executes every action.

Existing run configurations, v1/v2/v3 policy contracts and recorded worlds keep
their behavior. No saved world is upgraded by loading this code. The completed
v2 live experiment is not evidence that v4 improves investment returns, voting,
institutional policy or long-term welfare. These domains are experimental until
prospective comparisons support their adoption.

## Ownership and coverage

`agents/decision_domains.py` classifies all 110 registered engine commands into
20 families, plus eight Commons operations and six optional services. A registry
entry is an ownership declaration, not a promise that every possible action has
an automatic opportunity generator. The compiler consumes current observations
and the engine's existing eligible actions; it cannot create missing authority,
counterparty assent, legal evidence or future information.

| Domain | Implemented selection | Boundary |
|---|---|---|
| Consumption | Goods, affordable quantities, wait; compatible shopping/job bundles | Stock and funds rechecked at execution |
| Career | Apply, accept, reject and bounded wage counters | Current offers, applications, health, employment and retirement gates |
| Founder operations | Hold/lower/raise price, make/accept/counter/reject offers, post a vacancy, dismiss an employee; price plus one hiring action | Own firm currency/cash and payroll reserve; employee/applicant facts |
| Personal finance | Insurance, cancellation, retirement shortfall withdrawal, bank changes; existing prepared loans/transfers | Exact terms and actor funds; no invented loan approval |
| Investment | Buy/sell limit orders, order cancellation, IPO bids and prepared FX orders | Existing commitments deducted; quantities bounded; fills never assumed |
| Entrepreneurship | Alternative eligible sectors and capital amounts, permit application or founding, required appointment | Cached engine-authorized alternatives, permits, capital and fees |
| Funding | Bounded pitch sizes/equity terms, offered term sheets, due diligence, accept/decline/fund/close; existing IPO actions | Current startup workflow and actual investor/founder authority |
| Mergers and IP | Existing prepared disclosure, registration, license, merger proposal/approval/closing actions | Authorized terms; consent, clearance and settlement remain deterministic |
| Bank policy | Loan denial/bounded rates and terms; policy-rate hold or bounded step; solvent liquidity approval/denial | Bank reserves, credit rules, evidence and ledger effects remain in engine |
| Contracts and legal | Existing prepared contract/counteroffer, reject/accept, obligation, filing, notice, settlement and counsel choices | No new prose, legal finding, represented party or monetary authority |
| Binding judgments | Retained on the existing route | `issue_legal_decision` is deliberately excluded from Jev selection |
| Regulation | Existing eligible permit/construction/merger reviews | Current assignment, case, version and authority checked by engine |
| Politics | Recorded fiscal/federal/legislative ballots; prepared sponsor/amend/committee/executive/override/lobby actions | Actual eligible voters; executive veto and lobbying opposition alternatives |
| Communications | Choose an already-prepared authorized message, reply, forward, claim, publication or correction | Direct models still draft prose; protocol-specific duties retain their route |
| Learning and compute | Study, eligible plan purchase/cancellation, prepared sponsorship | Study occupies the economic turn; simulation funds are separate from API dollars |
| Regional | Prepared trade and migration/population-movement alternatives | Destination, logistics, consent and currency mechanics stay in engine |
| Estates | Bounded property/unlisted bids, eligible acceptance and withdrawal | Authorized account, lot/custody version, blockers and expiry; bid is not a valuation |
| Construction | Existing eligible project, permit, funding, work, cancellation, demolition and building actions | Ownership, escrow, duration and occupancy checks |
| Household and time | Prepared partnership/move/response/separation and complete time plans | Each adult's assent; care, wages and time accounting stay deterministic |
| Frontier | Existing exploration, settlement, build, move and charter options | Costs, duration, prerequisites and active-task occupancy |

No fabricated zero-price stock quote is used. When no trade exists, a bounded
limit proposal may use explicitly labeled visible fundamentals. Estate bids
are budget fractions, explicitly not appraisals. These proposal rules are
experimental policy assumptions that must be compared with the same-menu
baseline and the existing direct-model route.

Investment requests include the agent-visible company names, cash, inventory,
book values, recent revenue, IPO terms and its own pending orders once in their
state. Explicit field lists exclude unrelated private catalog extensions.
Actor risk tolerance keeps its full range, including an explicit zero.

The menu includes wait and escalation. It admits at most 64 complete economic
candidates; over-capacity or unrepresented material duties retain the existing
route instead of silently dropping choices. Resource requirements distinguish
actor, firm, estate account and currency. Execution-time races are recorded as
rejections, not successes. The default staggered strategic review every seven
ticks retains an existing direct/scripted decision turn; ballot days still
expose the ballot. Setting the interval to zero disables that review deliberately.

## Optional services

| Service | What Jev does | What remains elsewhere |
|---|---|---|
| `attention` | Score already-visible memory items for relevance, with stable ties | All items retained; access, memory writing and truth unchanged |
| `newsroom` | Choose one public source event or abstain | Existing editor writes and grounding validates; required daily news falls back to a deterministic factual brief after abstention |
| `oracle_tools` | Choose a validated complete read-only evidence plan | Tool authorization, bounds and execution |
| `oracle_forecast` | Estimate Noul probability for an explicit rule and deadline | Direct analyst explanation/confidence; deterministic resolution and calibration |
| `hermes_helper` | Recommend among 1–32 caller-prepared catalog-valid actions | Hermes persona, session, goals and final action submission |
| `commons` | Recommend prepared post/react/read/follow/join/create/moderate/appeal | Scope, membership, content/consent, final act and exposure recording |

The newsroom path removes its reporter drafting call when enabled but retains
the editor writing call. Oracle forecasting still runs the analyst writer and
adds a probability selection call; no cost saving is claimed. Choice/Score
confidence measures answer concentration, not the probability of economic
success. Noul is the probability of its stated resolution rule. The prediction
record explicitly labels its probability and explanation sources separately.

All ten existing Hermes personas remain independently controlled. Installing
this code does not add helper calls to their scripts or submit a recommendation
for them. Helpers are optional authenticated tools, not a second controller.

## Prospective configuration

Existing `runs/jev-live.yaml` and hybrid profiles keep their recorded policy.
For a new world, add an explicit v4 policy with selected domains and services:

```yaml
engine_semantics_version: 20
llm:
  decision_policy:
    version: bounded-economic-choice-v4
    primary: {provider: openrouter_jev, model: typesafe/jev-1.13, timeout_s: 20}
    domains: [consumption, career, founder_operations, investment, entrepreneurship, politics]
    services: []
    max_candidates: 64
    price_steps_bps: [-500, 0, 500]
    investment_bps: 2500
    max_investment_quantity: 5
    firm_reserve_payrolls: 1
    strategic_review_interval_ticks: 7
    minimum_confidence: 0.0
    on_abstain: wait
    activation_tick: 1
recorded_voting:
  version: 1
  activation_tick: 1
budget:
  helper_reserve_usd: 0.0
```

This fragment requires a complete provider/budget profile. Use the existing
`openrouter_jev` typed Decisions adapter and server-side `OPENROUTER_API_KEY`
described in [Jev setup](jev.md). It does not use OpenRouter chat completions or
route another model through OpenRouter. DeepSeek and MiniMax continue on their
direct providers. Do not put keys in YAML, prompts, URLs or frontend code.
Provider model allowlists must continue to pin the approved Jev version.

V4 requires engine semantics 16 or later. Later engine features remain gated
by their own feature flags and semantics; listing a domain does not enable
its engine. Recorded voting and Commons helpers require semantics 20. The
explicit `recorded_voting.version: 1` flag selects the new prospective election
mechanics within semantics 20; flagless historical worlds retain their formulas.
When the political model is enabled, recorded voting also requires the V4
`politics` domain so legislative bill contests have an actionable native menu.
Extra ballot wakes obey the governor's citizen-enable and cadence limits;
actors already selected by the scheduler are retained. Undispatched electors
remain nonvotes rather than fabricated votes.
The unfinished semantics-21 population work is not activated.

Provider-free rehearsal profiles:

```powershell
python run.py --config runs/jev-domains-offline.yaml --ticks 3
python run.py --config runs/jev-society-offline.yaml --ticks 3
```

The first rehearses economic menus. The second enables the six services and
recorded voting on semantics 20. Both use scripted responses and make no paid
model calls. A service or institution still needs its ordinary trigger to run;
for example an Oracle question or an external helper request.

## Recorded ballots

Ballots open after NIGHT_CLOSE and close at FINALIZE. The engine snapshots each
contest's electorate, terms and bill version. An eligible actor can cast one
recorded choice, including explicit abstention. Exact duplicate submissions are
idempotent; changed, expired, foreign or ineligible votes reject. Nonresponse is
not an inferred vote. Fiscal ties retain policy; federal ballots determine party
counts and seat allocation; legislative passage requires a majority of the
eligible electorate and advances only after closure. Bill version changes expire
the old ballot. Native economic and ballot questions can share one typed request.

External citizens own their submissions; the current turn catalog offers one
action per wake, so an external citizen cannot submit several contests plus an
economic action through one helper recommendation. Hermes attendance continues
to be governed by the existing external-agent protocol.

## Helper APIs, scopes and accounting

- `POST /api/v2/agent/jev-advice` / MCP `ae_jev_recommend`: exact open
  `target_tick`, `observed_projection_hash`, `candidate_actions`, optional `goal`.
  Requires a bound actor with `world.read` and `world.act`.
- `GET /api/v2/agent/commons/jev-view` / MCP `ae_commons_jev_view`: authorized
  preview with `observation_hash`, without impressions or exposure.
- `POST /api/v2/agent/commons/jev-advice` / MCP `ae_commons_jev_recommend`:
  `observed_tick`, `observation_hash`, prepared `candidate_actions`, optional
  `goal`. Requires `commons.read` and `commons.write`; moderation also requires
  its scope and the community role.

All recommendations return `submitted: false`. A stale result is labeled and
cannot bypass the ordinary submit endpoint's validation. There is one immutable
request per external turn (or Commons connection/tick); exact repeats reuse the
recorded result, changed requests conflict. Disabled helpers return 409, missing
identity/scope returns 401/403, exhausted allowance returns 402 and provider
unavailability returns 503. The OpenAPI artifact includes the request schemas.

Paid helper calls require a positive `budget.helper_reserve_usd`, explicitly
carved out of the existing total cap; zero is the default. Physical attempts
still use the shared durable provider allowance. Helper spend is recorded but
does not change native cognitive cadence. Private helper audit and cost rows are
control-plane evidence; replay rebuilds the actual externally submitted action,
not a fresh advisory call. Neither configuration nor helper access increases a
previously authorized spending limit.

## Evidence, replay and evaluation

Native receipts bind the actor/tick, observation, questions, complete actions,
compiler policy, selected option, provider calls/costs and executed outcomes.
Attention receipts commit in actor order after concurrent calls finish. News
selection uses public evidence contents and occurrence order rather than local
event IDs. Native v4 menus bind explicit event pointers to the complete event's
logical identity and duplicate occurrence. Local engine IDs remain unchanged;
different evidence, amounts or actors still invalidate the typed request.
Governed Oracle contracts are persisted for replay. Typed replay requires exact
recorded requests and never falls back to a live provider.

The Experiments decision view shows domains, controller, accepted/attempted
actions, all-run totals through the selected day and optional service totals.
Only the newest 200 decision rows render. Public projections exclude private
observations, menus, helper audits and forecast evidence. Private research
artifacts continue to contain the richer material needed for auditing.

`bounded-decision-report-v2` reports concentration descriptively. It computes
probability Brier scores only when actual normalized choice probabilities and
independent labels exist; the scripted comparator is not ground truth.

Build prospective frozen menus from complete recorded request observations:

```powershell
python -m research.decision_studies counterfactual --run data/closed-source.db --config runs/jev-domains-offline.yaml --domain founder_operations --out reports/out/founder-domain.json --limit 200
```

The source must be closed with no pending journal/WAL data. The builder opens it
read-only, verifies immutability, binds actor/tick and request hashes, uses stable
actor splits and samples available constrained/pending-offer/ordinary cases.
It never joins final world tables to reconstruct a past observation. Incomplete
older contexts are counted as exclusions, so the original v2 run may not supply
usable v4 observations. These are explicitly labeled counterfactual menus with
no fabricated labels or fabricated 200-case coverage.

Before enabling domains broadly, compare the same frozen menus across scripted,
Jev and the existing direct routes, then compare complete prospective worlds for
rejection rates, costs, latency, attendance, diversity and domain outcomes.
Use correct currency/price and fulfilled-versus-proposed definitions. Ledger
reconciliation, source immutability and exact network-disabled replay are hard
gates. A paid follow-up study needs an explicitly authorized launch and allowance;
implementation authorization alone does not launch it.

## Validation

Focused suites are `tests/test_jev_domains.py`, `tests/test_jev_ballots.py`,
`tests/test_jev_services.py`, the existing Jev contract/gateway/replay/study tests
and `tests/test_live_response_contract.py`. They include mocked Jev calls with
native actions, real ballot effects, an owned Hermes submission, governed Noul
forecast, ledger reconciliation and exact replay of every deterministic table
with networking disabled and the source hash unchanged. They do not establish
live v4 model quality, profitability or forecast calibration.

Run the repeatable 100-tick acceptance in a **new** private output directory:

```powershell
python scripts/jev_domains_acceptance.py --out reports/out/jev-domains-acceptance --ticks 100
```

This fixed scripted profile enables elections every five ticks. The harness
blocks HTTP sends and outbound socket connections, reconciles both ledgers,
compares every deterministic table, verifies recorded call consumption and
checks the closed source database's SHA-256 before and after replay. It retains
the source, replay, receipt and full proof; it refuses an existing output path.
The six enabled services still require their ordinary triggers; this long
rehearsal is supplemented by the mocked provider/helper/Oracle integration test.

Local evidence on 2026-09-19:

| Check | Result |
|---|---|
| Final Jev suites, live response contract and recorded replay golden tests | 130 passed |
| Final helper/gateway, provider-budget and governor regression checks, including zero-cost-estimate denial | 97 passed |
| CI core-subset command | 447 passed |
| CI smoke command | 238 passed |
| Bounded replay, historical Oracle campaigns, politics and experiment harness (four disjoint shards) | 156 passed |
| Documentation after adding this guide to the maintained set | 22 passed |
| Dashboard unit/contract tests | 284 passed |
| Decision workspace browser tests | Desktop and mobile passed; synthetic fixtures |
| Compilation, typecheck, pinned datasets, dependency/notice audits, OpenAPI parity and production build | Passed |

The reproducible acceptance run `88c3bc5b59` completed 100 ticks with 1,731 typed
decisions, 499 recorded votes, 1,529 supporting selections, zero decision errors,
zero network attempts and $0 model spend. Both ledgers reconciled. All recorded
non-operational calls were consumed exactly once. Source and replay canonical
state hashes both equal
`c62a938a2e127607b6a4d3fdce397b7231c18ba9ceb521c2258fe6bc03fdbae0`.
The closed source SHA-256 remained
`8d823b2f627d22c943cb813d5b071a1b042222bb6dd7d884f4f92dfa0d7eb85b`.
Private databases and detailed proof remain in the ignored
`reports/out/jev-domains-verified-acceptance/` directory.

Of the typed receipts, 1,536 selected a menu choice and 195 retained the existing
route (194 strategic reviews and one undelegated institutional duty). Execution
recorded 1,828 accepted actions and 575 rejections: 573 out-of-stock purchases,
one no-longer-pending application and one unavailable job. These are recorded
outcomes, not successful trades. The quality of policy choices and competition
for supply remain measurements for the prospective live comparison.

After-change browser evidence: [desktop](images/jev-domains/desktop.png) and
[mobile](images/jev-domains/mobile.png). These show mock decision receipts and
service totals, not a live-provider world. No before screenshot was captured.

The existing Starlette TestClient deprecation and Vite chunk-size warning remain.
The entire cross-platform test matrix and a paid v4 comparison were not run;
this evidence does not justify changing the saved v2 experiment or enabling all
domains in a live world by default.
