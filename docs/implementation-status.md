# Agent Economy — Implementation Status & PRD Gap Assessment

> **Assessment date:** 2026-07-10
>
> **Frozen code baseline:** `main` at `363a91a`
>
> **Product baseline:** [PRD v1.0](../PRD.md) (Draft for review, 2026-07-09)
>
> **Technical baseline:** [Technical Specification v1.0](../TECH-SPEC.md) (2026-07-09)
>
> **Canonical status:** This Markdown document is the source of truth. The [HTML companion](implementation-status.html) is a synchronized visual rendering of the same assessment.

## Executive verdict

**Agent Economy is a feature-rich functional prototype, but it is not yet PRD-v1 complete.** Most P0 and P1 product surfaces exist and the committed test suite exercises the core ledger, markets, credit, lifecycle, government, VC, health, experiment, calibration, and replay components. The remaining distance is concentrated in acceptance proof and specification fidelity: the default world is scripted rather than powered by the locked MiniMax/Kimi model mix, the dashboard is static HTML rather than the specified React stack, and several quantitative acceptance gates have not been run or asserted exactly.

The scores below measure different things and should not be combined into a single delivery percentage.

| Score | Result | Calculation | Meaning |
|---|---:|---:|---|
| **Feature coverage** | **87%** | 14.75 / 17 = 86.8% | How much of the P0/P1 capability surface has substantive implementation. |
| **Acceptance proof** | **63%** | 10.75 / 17 = 63.2% | How much of the exact PRD acceptance contract is demonstrated by committed tests or repeatable evidence. |
| **Technical-spec fidelity** | **64%** | 9.00 / 14 = 64.3% | How closely the implementation follows the locked architecture, stack, runtime, and test strategy. |

### Scoring method

Each row is scored independently as **Complete = 1.00**, **Substantial = 0.75**, **Partial = 0.50**, or **Absent = 0.00**. Feature and acceptance scores use the 17 P0/P1 requirements as their denominator. The technical score uses 14 technical commitments. P2 items are deliberately excluded because the PRD marks them as future work.

Evidence labels used in this report:

- **Tested** — covered by a committed automated test.
- **Implemented** — substantive code exists, but the full acceptance contract is not proven.
- **Manually observed** — confirmed in the local dashboard on the frozen build.
- **Unproven** — required quantitative or end-to-end evidence is absent.

## What has been built

| Product layer | Current implementation | Primary evidence | Confidence |
|---|---|---|---|
| Economic kernel | Conserved double-entry ledger, action validation, deterministic tick loop, reconciliation, metrics, and checkpoints. | [Ledger](../engine/ledger.py), [action executor](../engine/actions.py), [world loop](../world/loop.py), [ledger tests](../tests/test_ledger.py) | Tested |
| Agents and decisions | Persona/runtime scheduling, context construction, short/daily/weekly memory storage, scripted policies, provider adapters, routing, structured action parsing, call logging, and budget governor. | [Agent runtime](../agents/runtime.py), [memory](../agents/memory.py), [LLM gateway](../llm/gateway.py), [adapters](../llm/adapters.py) | Implemented; real default model mix unproven |
| Banking and credit | Two-bank mechanics, deposits/reserves, lending, amortization, missed-payment default, cross-bank settlement, bank failure, and bankruptcy waterfall. | [Credit engine](../engine/credit.py), [credit tests](../tests/test_credit_and_firms.py) | Tested |
| Firms and labor | Firm creation, legal validation, payroll, hiring, firing, production, goods sales, borrowing, default, bankruptcy, and ownership state. | [Firms](../engine/firms.py), [labor](../engine/labor.py), [actions](../engine/actions.py) | Implemented; complete lifecycle pilot unproven |
| Securities market | Order book, price-time priority, partial fills, holdings checks, IPO/trading state, prices derived from trades, and circuit breakers. | [Exchange](../engine/exchange.py), [exchange tests](../tests/test_exchange.py), [circuit-breaker test](../tests/test_spec_polish.py) | Tested |
| Information economy | Reporter/editor newsroom, published articles, conversations, rumor propagation, belief/trust movement, and associated event storage. | [Newsroom and conversations](../world/newsroom.py), [rumor integration test](../tests/test_governor_and_world.py), [newsroom test](../tests/test_spec_polish.py) | Tested at reduced scale; exact pilot thresholds unproven |
| Oracle | Question classification, probability generation, predictions, deterministic resolution rules, Brier scoring, scorecard, and calibration decomposition. | [Oracle](../oracle/analyst.py), [calibration](../oracle/calibration.py), [Oracle tests](../tests/test_governor_and_world.py) | Implemented; real latency and calibration targets unproven |
| Shocks | Scheduled and manual shock console covering rumor, bank panic, rate change, productivity, market halt, and epidemic behavior. | [Shock engine](../world/shocks.py), [P1 tests](../tests/test_p1_features.py), [dashboard](../server/static/index.html) | Implemented; five-shock acceptance suite incomplete |
| Lifecycle and health | Seeded sickness, death, estates, heirs/escheat, arrivals, wage loss, medical billing, hospitals, insurers, premiums, lapses, and epidemic multipliers. | [Lifecycle](../engine/lifecycle.py), [lifecycle tests](../tests/test_lifecycle.py), [health tests](../tests/test_p1_features.py) | Tested at unit/integration scale; two-year pilot unproven |
| Government | Income-tax withholding, unemployment benefits, elections, bounded policy changes, and integration with the world loop. | [Government](../engine/government.py), [government tests](../tests/test_p1_features.py) | Tested |
| Venture capital | Pitches, investment decisions, cap tables, follow-ons, declines, and write-offs. | [VC engine](../engine/vc.py), [VC tests](../tests/test_p1_features.py) | Tested |
| Experimentation | Treatment/control multi-seed harness, per-arm databases, effect distributions, and Markdown/HTML experiment reports. | [Experiment harness](../experiments/harness.py), [experiment test](../tests/test_p1_harness_and_tools.py) | Tested at small N; five-seed target unproven |
| Replay and forks | Read-only replay catalogue/tick views, stored-response lookup, checkpoints, resume, deterministic fixture replay, and what-if forks that preserve the parent. | [Replay reader](../server/replay.py), [gateway replay lookup](../llm/gateway.py), [replay/fork tests](../tests/test_p1_harness_and_tools.py) | Implemented; full real-LLM replay equality unproven |
| Reports | End-of-run HTML and Markdown generation with narrative, event timeline, SVG charts, Oracle scorecard/calibration, cost summary, configuration, and seed. | [Report generator](../reports/generate.py), [CLI entry point](../run.py) | Implemented; dashboard Stop automation unproven/not wired |
| Observatory | FastAPI REST endpoints, WebSocket updates, run controls, metrics, agents, banks, firms, news, conversations, shocks, Oracle, reports, calibration, and replay UI. | [Server](../server/app.py), [static dashboard](../server/static/index.html) | Manually observed; latency/accessibility gates unproven |

## PRD requirement assessment

| Requirement | Priority | Capability | Feature weight | Acceptance proof | Proof weight | Evidence | Remaining gap | Evidence required to close |
|---|---|---|---:|---|---:|---|---|---|
| **R1 — Conserved double-entry ledger** | P0 | Complete | 1.00 | Substantial | 0.75 | **Tested:** [ledger invariants and tamper detection](../tests/test_ledger.py); [30-tick reconciliation](../tests/test_governor_and_world.py). | No committed active-run test proves a failed reconciliation both halts the simulation and emits the required diagnostic event. | Inject corruption during a running world and assert halt, diagnostic event, and no subsequent tick commit. |
| **R2 — LLM agent runtime, persona, memory, decisions, inspector** | P0 | Partial | 0.50 | Partial | 0.50 | **Implemented:** [runtime](../agents/runtime.py), [memory](../agents/memory.py), [gateway](../llm/gateway.py), and agent inspector UI. **Manually observed:** inspector and exact stored decision fields in the local scripted run. | The default route is scripted, real MiniMax/Kimi decisions are unproven, the observed world had about 83 agents rather than approximately 100, and weekly rollup is not a true weekly consolidation. | Run the locked provider/model mix near 100 agents and verify exact prompt, response, parsed action, memory rollup, and inspector display for each role. |
| **R3 — Banks, firms, labor, goods, and complete company lifecycle** | P0 | Substantial | 0.75 | Partial | 0.50 | **Tested:** loan payoff, three-miss default, bankruptcy waterfall, bank failure, payroll, and world integration in [credit/firm tests](../tests/test_credit_and_firms.py) and [world tests](../tests/test_governor_and_world.py). | No single acceptance run follows a founder through lawyer validation, loan, hiring, payroll, revenue, distress, and bankruptcy using the full production flow. | Add one deterministic end-to-end company-lifecycle test with ledger reconciliation at every stage. |
| **R4 — Order book, IPO, and market index** | P0 | Complete | 1.00 | Complete | 1.00 | **Tested:** price-time priority, partial fills, ownership enforcement, and no engine-set prices in [exchange tests](../tests/test_exchange.py); circuit breaker in [spec-polish tests](../tests/test_spec_polish.py). | No material PRD-v1 blocker identified in the committed implementation. | Preserve the existing tests and add regression cases only as market behavior changes. |
| **R5 — News, conversations, and rumor pilot** | P0 | Complete | 1.00 | Partial | 0.50 | **Tested:** reporter/editor order and reduced-scale rumor movement in [newsroom](../world/newsroom.py), [world tests](../tests/test_governor_and_world.py), and [spec-polish tests](../tests/test_spec_polish.py). | The test does not assert at least five conversations, a trust drop of at least 0.2 for at least 25% of exposed agents, or deposit outflow above twice baseline within ten ticks. | Implement the exact PRD rumor pilot with explicit exposure cohort, baseline window, threshold assertions, and deterministic seed. |
| **R6 — Oracle prediction, resolution, and Brier score** | P0 | Substantial | 0.75 | Partial | 0.50 | **Tested:** probability record, deterministic outcome resolution, Brier computation, and insufficient-data handling in [Oracle tests](../tests/test_governor_and_world.py). | The test uses a shortened horizon and scripted responses; real-provider response latency below 60 seconds and the exact 30-tick contract are unproven. | Run a real-provider latency benchmark and a 30-tick automatic-resolution acceptance test with persisted scorecard output. |
| **R7 — Run control, cost governor, cap, and degradation visibility** | P0 | Complete | 1.00 | Partial | 0.50 | **Tested:** governor stages, pause/resume/checkpoint, and deterministic world behavior in [world tests](../tests/test_governor_and_world.py). **Implemented:** run controls and live cost state in [server](../server/app.py). | No 365-day real-provider run proves the $200 cap is never exceeded, provider failures pause safely, and every degradation stage is visible in the dashboard. | Add fake-price threshold tests at 60/80/95/100%, provider-failure tests, and a full real-provider budget run with exported evidence. |
| **R8 — Live observatory dashboard** | P0 | Substantial | 0.75 | Partial | 0.50 | **Implemented:** REST/WebSocket observatory and panels in [server](../server/app.py) and [dashboard](../server/static/index.html). **Manually observed:** run/pause/step, agent inspector, shocks, and replay on the frozen build. | No automated update-latency proof below two seconds; the static page is a 925-line monolith with narrow-screen, long-table, and accessibility debt. The onboarding card remained at “Day 0” during a day-47 run. | Add WebSocket latency instrumentation, responsive/accessibility checks, and a regression test for current-day onboarding state. |
| **R9 — Minimum shock catalogue and downstream effects** | P0 | Complete | 1.00 | Partial | 0.50 | **Implemented:** six shock kinds in [shock engine](../world/shocks.py) and dashboard console. **Tested:** rumor, epidemic multiplier, and circuit-breaker behavior across the existing suite. | There is no parameterized acceptance suite showing a required downstream economic effect for each of the five minimum PRD shocks. | Add one deterministic scenario per required shock and assert both the shock event and its downstream metric/ledger effect. |
| **R10 — Automatic end-of-run report** | P0 | Substantial | 0.75 | Partial | 0.50 | **Implemented:** narrative, timeline, charts, Oracle scorecard, calibration, cost, configuration, and seed in [report generator](../reports/generate.py). Headless completion generates a report through [run.py](../run.py). | Dashboard Stop only requests a stop; it does not automatically generate the report. There is no content-contract test for all required sections. | Generate once the interactive world reaches stopped state and test both Markdown/HTML section presence, values, seed/config, and event logging. |
| **R11 — Two-year lifecycle acceptance** | P0 | Substantial | 0.75 | Partial | 0.50 | **Tested:** estates with debt/heir, escheat, deterministic schedules, sickness cost/wage loss, hospitals, and insurers in [lifecycle tests](../tests/test_lifecycle.py) and [P1 tests](../tests/test_p1_features.py). | No 730-tick acceptance run proves death/estate, sickness, and an arrival obtaining housing and a job within ten ticks while reconciling throughout. | Add a seeded two-year scenario with forced representative events and exact arrival-integration assertions. |
| **R12 — Government and elections** | P1 | Complete | 1.00 | Complete | 1.00 | **Tested:** withholding, unemployment benefits, bounded election shifts, integration, and determinism in [government/P1 tests](../tests/test_p1_features.py). | No material P1 capability blocker identified; longer-run policy realism remains calibration work rather than missing implementation. | Retain deterministic tests and add calibration evidence when real-provider full runs exist. |
| **R13 — Venture capital** | P1 | Complete | 1.00 | Complete | 1.00 | **Tested:** pitch, investment, cap table, decline, follow-on, and write-off behavior in [VC tests](../tests/test_p1_features.py). | No material P1 capability blocker identified. | Preserve the current acceptance coverage and add cross-run portfolio metrics later. |
| **R14 — Experiment harness** | P1 | Complete | 1.00 | Substantial | 0.75 | **Tested:** treatment/control execution, effect distribution, and HTML/Markdown artifacts in [harness tests](../tests/test_p1_harness_and_tools.py). | The committed test uses two seeds and available local evidence uses fewer than the five-seed lagging-success target. | Run and archive a deterministic five-seed treatment/control experiment with config, seed list, effect distribution, and reproducibility command. |
| **R15 — Oracle calibration dashboard** | P1 | Substantial | 0.75 | Partial | 0.50 | **Tested:** calibration decomposition identity in [harness/tool tests](../tests/test_p1_harness_and_tools.py). **Implemented:** calibration computation and dashboard/report presentation in [calibration](../oracle/calibration.py) and [report generator](../reports/generate.py). | There is no meaningful multi-run set of resolved real-provider predictions to demonstrate calibration quality. | Accumulate resolved predictions across full runs and verify bins, reliability/resolution/uncertainty, Brier baseline, and UI rendering. |
| **R16 — Replay UI** | P1 | Substantial | 0.75 | Partial | 0.50 | **Tested:** run listing/tick paging, checkpoint/resume, golden event fixture, and parent-preserving forks in [harness/tool tests](../tests/test_p1_harness_and_tools.py), [world tests](../tests/test_governor_and_world.py), and [spec-polish tests](../tests/test_spec_polish.py). | Current UI replay reads stored state; 100% exact end-to-end re-execution using stored real LLM outputs has not been checksum-proven. | Replay a completed real-provider run and compare full ordered event, ledger, metrics, and terminal-state hashes. |
| **R17 — Health economy** | P1 | Complete | 1.00 | Substantial | 0.75 | **Tested:** medical split, premiums, lapses, epidemic multiplier, world integration, and determinism in [P1 tests](../tests/test_p1_features.py). | The mechanics are well covered at small scale, but actuarial behavior and long-run institution solvency are not demonstrated in a full real-provider run. | Add a long-run health-economy scenario with hospital/insurer solvency, illness incidence, claims, premiums, and reconciliation assertions. |

### Feature and proof totals

- Feature weights: `14.75 / 17 = 86.8%`, rounded to **87%**.
- Acceptance-proof weights: `10.75 / 17 = 63.2%`, rounded to **63%**.
- No P0/P1 row is wholly absent, but several rows receive partial proof because the PRD specifies quantitative end-to-end gates rather than mere code presence.

## Technical-spec fidelity

| Technical commitment | Status | Weight | Evidence and divergence |
|---|---|---:|---|
| T1 — Layered dashboard/API/kernel/provider/store architecture | Complete | 1.00 | FastAPI, WebSocket, Python kernel, gateway, and SQLite boundaries are present. |
| T2 — Python, FastAPI, SQLite WAL stack | Complete | 1.00 | The selected backend/store stack is implemented and one database represents a run. |
| T3 — Tick phases and cadence | Substantial | 0.75 | Deterministic phased ticks exist; full production cadence under real-provider load is not proven. |
| T4 — Specified persisted data model | Substantial | 0.75 | Core run, agent, institution, ledger, market, event, message, prediction, metric, and LLM-call state exists; a schema-level conformance test is absent. |
| T5 — Structured action contract and validation | Substantial | 0.75 | Action parsing/validation and no-op fallback are implemented; randomized valid-action property testing is absent. |
| T6 — Short, daily, and consolidated weekly memory pipeline | Partial | 0.50 | Memory tiers are stored, but the weekly operation demotes older daily summaries rather than synthesizing seven summaries into a new weekly summary. |
| T7 — Provider gateway, routing, concurrency, retry, budget, and logging | Substantial | 0.75 | Adapters, concurrency 8, routing, one repair retry, pricing, logging, and governor exist; provider-native cache behavior and failure acceptance are unproven. |
| T8 — Locked MiniMax M3 and Kimi K2.7 default role mix | Absent | 0.00 | [Base configuration](../runs/base.yaml) leaves provider/routes commented and uses `scripted` for every role. |
| T9 — Deterministic market mechanics | Substantial | 0.75 | Exchange, credit, firms, labor, and settlement mechanics are substantial and tested; complete company-flow acceptance is missing. |
| T10 — Seeded lifecycle mechanics | Substantial | 0.75 | Death, estates, sickness, medical flows, arrivals, and deterministic schedules exist; the exact two-year acceptance is missing. |
| T11 — React, Vite, Tailwind, and Recharts dashboard | Absent | 0.00 | The dashboard is a self-contained static HTML/CSS/JS page; there is no specified `dashboard/` application. |
| T12 — Unit, property, golden-run, and cost-test strategy | Partial | 0.50 | There are 39 deterministic unit/integration tests and a golden fixture, but no random property suite and no complete 60/80/95/100% cost-threshold suite. |
| T13 — Determinism, checkpointing, resume, replay, and forks | Substantial | 0.75 | Same-seed, checkpoints, resume, fixture replay, reader UI, and forks are tested; full real-LLM replay equality is unproven. |
| T14 — Repository layout and phased build order | Substantial | 0.75 | Most specified subsystems and phase-four features exist; the React dashboard package is omitted and real-provider scale milestones are incomplete. |

Technical weights total `9.00 / 14 = 64.3%`, rounded to **64%**.

## Phase progress

| PRD phase | Verdict | Current state | Exit work still required |
|---|---|---|---|
| Phase 1 — Kernel and accounting | Complete | Ledger, validation, deterministic kernel, scripted mechanics, reconciliation, and core invariant tests are operational. | Add the explicit active-run reconciliation-halt acceptance case. |
| Phase 2 — Agents, banking, firms, and markets | Substantial | Runtime, memory, gateway, banks, credit, firms, labor, exchange, checkpoints, and scripted integration are operational. | Prove the locked real-provider mix near 100 agents and one full company lifecycle. |
| Phase 3 — Information, Oracle, observatory, shocks, reports | Substantial | All major surfaces exist and are usable in the local observatory. | Meet exact rumor/shock/latency/Oracle/report acceptance contracts and resolve frontend divergence. |
| Phase 4 — Government, VC, experiments, calibration, replay, health | Substantial | P1 capability surface is unusually complete for a prototype and has targeted tests. | Run five-seed and long-run real-provider evidence; prove replay equality and calibration usefulness. |

## Principal gaps and risks

### Critical — locked runtime is not the default runtime

[The default configuration](../runs/base.yaml) routes every role to the deterministic scripted adapter. Real provider adapters exist, but the locked MiniMax/Kimi model allocation, real inference costs, failure behavior, and latency have not been demonstrated. The base population is 70 citizens plus staff/founders; the manually observed run contained about 83 agents, below the approximately 100-agent launch target.

### High — acceptance evidence trails implementation

The repository has strong deterministic coverage—39 committed tests passed on the frozen baseline—but many tests intentionally use smaller horizons and scripted actors. They prove mechanics, not every quantitative PRD gate. The most important missing evidence is the exact rumor pilot, one downstream-effects test per minimum shock, a two-year lifecycle run, sub-two-second dashboard updates, a 365-day real-provider budget run, real Oracle p90 latency, and full replay equality.

### High — dashboard stack diverges from the technical specification

[README.md](../README.md) records the zero-build static dashboard as a pragmatic deviation. It preserves an API boundary that can support a replacement, but the current [65 KB, 925-line page](../server/static/index.html) concentrates layout, state, rendering, and interactions in one file. This creates maintainability, responsive-layout, accessibility, and regression-testing risk.

### Medium — completion-path polish

Headless runs generate reports automatically, while interactive Stop does not. Weekly memory does not perform the specified synthesis. Prompt-cache savings are estimated in gateway accounting, but provider-level cache use is not demonstrated. Replay tooling is useful for viewing and deterministic fixtures, but has not yet proven exact real-provider re-execution.

## Prioritized roadmap to PRD-v1 completion

1. **Prove the locked real-LLM operating envelope.** Enable MiniMax M3 and Kimi K2.7 role routes, scale to approximately 100 agents, capture provider/cost/latency/failure telemetry, and complete a 365-day run without exceeding $200.
2. **Turn PRD gates into executable acceptance tests.** Add exact rumor thresholds, required-shock downstream assertions, WebSocket latency measurement, two-year lifecycle/arrival integration, Oracle 30-tick resolution and p90 latency, governor thresholds, and active-run reconciliation failure behavior.
3. **Resolve the observatory architecture decision.** Replace the static monolith with the specified React/Vite/Tailwind/Recharts client while preserving the REST/WebSocket contract, then add responsive, accessibility, and UI regression coverage.
4. **Close completion-path gaps.** Generate reports after interactive Stop, implement true weekly-summary consolidation, demonstrate provider-native prompt caching, and checksum a stored-response replay against the original real-provider run.
5. **Produce lagging-success evidence.** Run at least five treatment/control seeds, accumulate resolved Oracle predictions, quantify three emergent phenomena, verify all five shocks, and package reports/configs/seeds as repeatable evidence.

## Verification snapshot

| Check | Frozen result |
|---|---|
| Working baseline | `main` commit `363a91a` |
| Automated tests | **39 passed** with `python -m pytest tests/ -q` |
| Determinism evidence | Same-seed event log, lifecycle schedule, P1 world, golden fixture, checkpoint/resume, and parent-preserving fork tests |
| Manual observatory evidence | Run, pause, step, agent inspector, six-shock console, and replay controls operated locally; no browser/server errors observed during that pass |
| Manual UI defect | Quick-start/onboarding state still showed “Day 0 — world ready” while the simulation was at day 47 |
| CI baseline | Existing GitHub Actions workflow passed on the frozen repository baseline |

## Deferred P2 work — excluded from scores

| Future requirement | PRD disposition | Current assessment |
|---|---|---|
| **R18 — Participant mode** | P2 future | Intentionally not part of v1 completion; observer-only constraints should remain preserved. |
| **R19 — Scale to approximately 1,000 agents** | P2 future | Not assessed against current launch acceptance; architecture should avoid blocking later store/runtime changes. |
| **R20 — Regions and foreign exchange** | P2 future | Not implemented as a required current-world surface. |
| **R21 — Real-data calibration** | P2 future | Not required for the current synthetic economy; future ingestion must remain reproducible and provenance-aware. |
| **R22 — Hosted multi-user service** | P2 future | Current single-process/local observatory is appropriate for v1; authentication/tenancy are future concerns. |

## Assessment boundaries

- This is a repository-and-evidence assessment, not a claim that every economic behavior is realistic or calibrated.
- Generated local run databases and reports were used only as corroborating evidence; committed code and tests carry more weight.
- Scripted behavior receives feature credit where the mechanics are real, but it does not receive full acceptance or technical-fidelity credit when the PRD explicitly requires real LLM behavior.
- Scores are reproducible from the weights shown above and should be refreshed whenever the PRD, technical specification, default configuration, or acceptance suite changes.
