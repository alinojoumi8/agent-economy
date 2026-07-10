# Agent Economy — Implementation Status & PRD Gap Assessment

> **Assessment date:** 2026-07-10
>
> **Code baseline:** `fix/provider-live-readiness` at `b2b25c0`
>
> **Product baseline:** [PRD v1.0](../PRD.md)
>
> **Technical baseline:** [Technical Specification v1.0](../TECH-SPEC.md)
>
> **Canonical status:** This Markdown document is the source of truth. The [HTML companion](implementation-status.html) contains the same verdict, scores, requirement states, and evidence.

## Executive verdict

**The repository is feature-complete for the PRD-v1 P0/P1 scope and its current MiniMax/Kimi subscription routes have now been authenticated in a fresh 100-agent run.** The deterministic economy, strict action contract, provider routing and failure handling, exact stored-response replay, two-year lifecycle proof, measured five-seed experiment, randomized property tests, report automation, weekly memory, and specified React dashboard are implemented and tested. Remaining production acceptance work is narrower: measure Oracle-specific latency, prove the 365-day cost envelope, accumulate calibration data, and repeat the documented causal signatures in a live-provider experiment.

The three scores measure different qualities and should not be combined.

| Score | Result | Calculation | Meaning |
|---|---:|---:|---|
| **Feature coverage** | **100%** | 17.00 / 17 = 100.0% | All P0/P1 capability surfaces have substantive implementation. |
| **Acceptance proof** | **96%** | 16.25 / 17 = 95.6% | All deterministic gates and routed-role provider proof are complete; three long-run or lagging-evidence gates remain substantial. |
| **Technical-spec fidelity** | **100%** | 14.00 / 14 = 100.0% | The locked architecture, provider mix, validation rules, test strategy, and frontend stack are implemented and exercised. |

### Scoring method

Each requirement is scored independently as **Complete = 1.00**, **Substantial = 0.75**, **Partial = 0.50**, or **Absent = 0.00**. Feature and acceptance scores use the 17 P0/P1 requirements. Technical fidelity uses 14 technical commitments. P2 work is intentionally excluded.

Evidence labels:

- **Tested** — covered by a committed automated test.
- **Implemented** — substantive production code exists.
- **Manually observed** — exercised in a local browser or CLI smoke run.
- **Unproven** — requires real credentials, paid inference, or accumulated lagging data.

## Implemented system inventory

| Product layer | Current implementation | Evidence | Confidence |
|---|---|---|---|
| Economy kernel | Conserved double-entry ledger, deterministic tick phases, action validation, reconciliation, diagnostics, metrics, checkpoints, resume, and forks. | [Ledger](../engine/ledger.py), [world loop](../world/loop.py), [ledger tests](../tests/test_ledger.py) | Tested |
| Agents and memory | Persona generation, role routing, cadence, context, short/daily/weekly memory synthesis, beliefs, decisions, and full inspector data. | [Runtime](../agents/runtime.py), [memory](../agents/memory.py), [completion tests](../tests/test_prd_completion.py) | Tested |
| Provider runtime | MiniMax/Kimi production profile, key/model preflight, concurrency, retry, structured parsing/repair, complete repair-call accounting, provider-reported cache accounting, conservative cap reservation, durable budget-stage events, safe provider pause, and secret-safe diagnostics. | [Production profile](../runs/production.yaml), [gateway](../llm/gateway.py), [readiness](../llm/readiness.py), [live validation](live-provider-validation.md) | Tested and authenticated live |
| Banks, credit, firms, labor | Deposits/reserves, cross-bank settlement, loans/default, liquidity support, firm formation, lawyer validation, hiring, payroll, production, revenue, and bankruptcy. | [Credit](../engine/credit.py), [firms](../engine/firms.py), [company lifecycle acceptance](../tests/test_prd_completion.py) | Tested |
| Securities market | IPOs, holdings enforcement, price-time priority, partial fills, trade-derived prices, index, and circuit breakers. | [Exchange](../engine/exchange.py), [exchange tests](../tests/test_exchange.py) | Tested |
| Information economy | Reporter/editor newsroom, slanted outlets, conversations, memories, rumor exposure, trust movement, and bank-run transmission. | [Newsroom](../world/newsroom.py), [exact rumor pilot](../tests/test_governor_and_world.py) | Tested |
| Oracle | Read-only questions, probabilities, drivers, resolution rules, automatic 30-tick resolution, Brier score, calibration decomposition, and scorecards. | [Oracle](../oracle/analyst.py), [calibration](../oracle/calibration.py) | Tested; live p90 latency unproven |
| Shocks | Policy-rate, oil, rumor, slant, scandal, and epidemic scheduling with downstream effects. | [Shock engine](../world/shocks.py), [shock acceptance](../tests/test_prd_completion.py) | Tested |
| Lifecycle and health | Aging, sickness, death, estates, heirs/escheat, replacement arrivals, housing, job search, hospitals, insurers, premiums, claims, and epidemic multipliers. | [Lifecycle](../engine/lifecycle.py), [two-year acceptance](../tests/test_prd_completion.py) | Tested |
| Government and VC | Taxes, benefits, elections, bounded policy shifts, pitches, funding, cap tables, follow-ons, declines, and write-offs. | [Government](../engine/government.py), [VC](../engine/vc.py), [P1 tests](../tests/test_p1_features.py) | Tested |
| Experiments | Treatment/control arms, five seeds, isolated run databases, distributions, effect summaries, reconciliation, Markdown/HTML reports, and a committed measured rumor study. | [Harness](../experiments/harness.py), [measured experiment](experiments/rumor-vs-control.md), [five-seed acceptance](../tests/test_p1_harness_and_tools.py) | Tested and executed |
| Replay | Read-only UI replay plus fresh-database engine re-execution from stored responses, no live fallback, copied cost accounting, and canonical per-table SHA-256 proof. | [Replay verifier](../world/replay_verify.py), [replay tests](../tests/test_prd_completion.py), [live validation](live-provider-validation.md) | Tested and live-run replay observed |
| Reports | Standalone Markdown/HTML reports with narrative, metrics, events, Oracle/calibration, cost, config, and seed; automatic generation after interactive or headless stop. | [Generator](../reports/generate.py), [report acceptance](../tests/test_prd_completion.py) | Tested and browser-observed |
| Observatory | Modular React/Vite/Tailwind/Recharts client, FastAPI REST/WebSocket backend, responsive tables, live ticker, controls, metrics, institutions, information flow, Oracle, per-model/per-purpose/per-agent costs, shocks, replay, and agent audits. | [Dashboard source](../dashboard/src), [server](../server/app.py), [bundle acceptance](../tests/test_prd_completion.py) | Tested and manually observed |

## PRD requirement matrix

| Requirement | Priority | Implementation | Acceptance proof | Repository/test evidence | Remaining gap | Required completion evidence |
|---|---|---|---|---|---|---|
| **R1 — Conserved double-entry ledger** | P0 | Complete (1.00) | Complete (1.00) | Ledger invariant/tamper tests plus active-run corruption halt, diagnostic, reconciliation, and checkpoint acceptance. | None for v1. | Preserve invariant and active-failure tests. |
| **R2 — LLM agent runtime, persona, memory, decisions, inspector** | P0 | Complete (1.00) | Complete (1.00) | Production routing/key validation, 100-agent profile, weekly synthesis, stored prompts/responses, browser-inspected agent audit, and an authenticated [MiniMax/Kimi validation run](live-provider-validation.md). | None for v1 runtime acceptance. | Preserve the secret-safe live validation and routed-role regression evidence. |
| **R3 — Banks, firms, labor, goods, complete company lifecycle** | P0 | Complete (1.00) | Complete (1.00) | Deterministic lawyer → formation → firm loan → hire → production → revenue → bankruptcy acceptance with ledger reconciliation. | None for v1 mechanics. | Preserve lifecycle regression. |
| **R4 — Order book, IPO, and market index** | P0 | Complete (1.00) | Complete (1.00) | Price-time, partial-fill, ownership, IPO, index, circuit-breaker, and no-invented-price property tests; two unpriced market orders cannot establish a first price. | None for v1. | Preserve exchange and property tests. |
| **R5 — News, conversations, and rumor pilot** | P0 | Complete (1.00) | Complete (1.00) | Exact pilot asserts at least five conversations, ≥0.2 trust loss for ≥25% exposed agents, and normalized outflow above 2× baseline within ten ticks; the committed N=5 study measures 16.8 treatment deposit moves versus zero controls. | None for deterministic acceptance; real-agent emergence remains a production gate. | Repeat all three [causal signatures](emergent-phenomena.md) under the real-provider profile. |
| **R6 — Oracle prediction, resolution, and Brier score** | P0 | Complete (1.00) | Substantial (0.75) | Prediction contract, insufficient-data handling, exact 30-tick automatic resolution, Brier scoring, calibration tests, and live institutional-route p90 of 23.228 seconds. | The PRD's p90 gate has not been measured on an Oracle-specific representative question set. | Run a representative live Oracle question set and publish p50/p90 latency with persisted predictions. |
| **R7 — Run control, cost governor, cap, and degradation visibility** | P0 | Complete (1.00) | Substantial (0.75) | Exact 60/80/95/100% stages, durable transition events, retry and repair-call billing, conservative two-call reservation, safe pause/checkpoint, per-agent API/UI costs, hard-cap tests, and [live provider cache/cost evidence](live-provider-validation.md). | The 365-day real-provider cost target remains unproven. | Complete the paid long run, export cost by model/agent/purpose/cache, and prove total spend ≤$200. |
| **R8 — Live observatory dashboard** | P0 | Complete (1.00) | Complete (1.00) | React stack/bundle test, live ticker, per-agent cost view, WebSocket timestamp under two seconds, desktop/~355px browser pass, keyboard agent audit, local-only assets, and no browser console errors. | No v1 blocker. | Add automated visual/accessibility regression if the UI expands. |
| **R9 — Minimum shock catalogue and downstream effects** | P0 | Complete (1.00) | Complete (1.00) | Parameterized acceptance proves every required shock fires and changes the intended metric, belief, article, or market channel. | None for v1. | Preserve scenario tests. |
| **R10 — Automatic end-of-run report** | P0 | Complete (1.00) | Complete (1.00) | Paused and actively running Stop paths generate standalone reports with required sections and durable events; browser smoke confirmed a real file. | None for v1. | Preserve report content contract. |
| **R11 — Two-year lifecycle acceptance** | P0 | Complete (1.00) | Complete (1.00) | A 730-tick acceptance run proves death/estate, replacement arrival, conserved housing cost, job application within ten ticks, and reconciliation. | None for v1. | Keep the long test in CI. |
| **R12 — Government and elections** | P1 | Complete (1.00) | Complete (1.00) | Withholding, benefits, election bounds, integration, and determinism tests. | None for v1. | Future calibration only. |
| **R13 — Venture capital** | P1 | Complete (1.00) | Complete (1.00) | Pitch, investment, cap table, decline, follow-on, and write-off tests. | None for v1. | Future portfolio calibration only. |
| **R14 — Experiment harness** | P1 | Complete (1.00) | Complete (1.00) | Five treatment seeds plus five same-seed controls, isolated databases, distributions, reconciliation, dual-format reports, and a committed [measured write-up](experiments/rumor-vs-control.md). | None for harness acceptance. | Archive a production-scale real-provider experiment after authorization. |
| **R15 — Oracle calibration dashboard** | P1 | Complete (1.00) | Substantial (0.75) | Calibration identity, run/all-run API, dashboard ledger, and report scorecard are implemented and tested. | A meaningful corpus of resolved real-provider predictions does not yet exist. | Accumulate cross-run predictions and publish bins, Brier, reliability, resolution, and uncertainty. |
| **R16 — Replay UI and exact replay** | P1 | Complete (1.00) | Complete (1.00) | Replay viewer plus fresh genesis re-execution; missing responses pause without provider calls; all 27 deterministic tables and LLM accounting hash identically on the [completed live run](live-provider-validation.md). | None for v1 replay acceptance. | Preserve the live-run canonical replay regression. |
| **R17 — Health economy** | P1 | Complete (1.00) | Complete (1.00) | Hospital/insurer flows, premiums, lapses, claims, illness multiplier, lifecycle integration, determinism, and long-run reconciliation coverage. | No v1 mechanics blocker. | Long-run actuarial calibration is product research, not missing implementation. |

### Totals

- Feature weights: `17.00 / 17 = 100.0%`, reported as **100%**.
- Acceptance weights: `16.25 / 17 = 95.6%`, rounded to **96%**.
- The 0.75-point proof gap consists of three 0.25 deductions: Oracle-specific live latency, 365-day cost proof, and accumulated calibration data.

## Technical-spec fidelity

| Technical commitment | Status | Weight | Evidence or qualification |
|---|---|---:|---|
| T1 — Dashboard/API/kernel/provider/store layering | Complete | 1.00 | React client, REST/WebSocket server, deterministic kernel, gateway, and SQLite remain separate. |
| T2 — Python, FastAPI, SQLite WAL | Complete | 1.00 | Implemented as specified; FastAPI lifespan API replaces deprecated startup events. |
| T3 — Ordered tick phases and cadence | Complete | 1.00 | Ordered phases, event waking, cadence, checkpointing, and deterministic execution are tested. |
| T4 — Persisted data model | Complete | 1.00 | Run, agent, institution, ledger, market, information, prediction, metric, shock, checkpoint, and call state are persisted. |
| T5 — Structured actions and validation | Complete | 1.00 | Provider output is parsed to envelopes; living actors/counterparties, funds, ownership, market phase, formation capital, and weekly loan limits are enforced. The engine neither substitutes a counterparty nor invents a first market price. |
| T6 — Short, daily, consolidated weekly memory | Complete | 1.00 | Weekly summaries are synthesized before their daily source summaries are demoted. |
| T7 — Routing, concurrency, retry, caching, budget, logging | Complete | 1.00 | Mechanics are tested and the live run recorded provider-reported cache hits, latency, costs, repairs, and zero provider failures. |
| T8 — Locked cheap/strong real-provider role mix | Complete | 1.00 | The authenticated production profile routes default roles to `MiniMax-M3` and institutional roles to K2.7 via the stable `kimi-for-coding` alias. |
| T9 — Deterministic market mechanics | Complete | 1.00 | Banking, firms, labor, exchange, settlement, and bankruptcy are tested end to end. |
| T10 — Seeded lifecycle mechanics | Complete | 1.00 | Biology is PRNG-owned and the exact two-year integration test passes. |
| T11 — React, Vite, Tailwind, Recharts | Complete | 1.00 | Modular source, committed local bundle, CI build, responsive browser pass, and no CDN runtime. |
| T12 — Unit, acceptance, golden, property/cost strategy | Complete | 1.00 | 69 tests include seeded randomized valid-action sequences, randomized lifecycle storms, exact budget transitions, repair accounting, golden output, long runs, and requirement-level acceptance. |
| T13 — Determinism, checkpoint, resume, replay, forks | Complete | 1.00 | Same-seed, golden, checkpoints, resume, parent-safe forks, and canonical full-state replay hashes are tested. |
| T14 — Repository layout and phased build | Complete | 1.00 | All specified packages and P1 surfaces, including the dashboard package, are present. |

Technical total: `14.00 / 14 = 100.0%`, reported as **100%**.

## Phase status

| Phase | Verdict | Evidence | Exit condition |
|---|---|---|---|
| Kernel and accounting | Complete | Ledger invariants, active failure halt, diagnostics, and checkpoints. | Met. |
| Agents, banking, firms, markets | Complete | Full deterministic mechanics plus an authenticated 100-agent MiniMax/Kimi run. | Met for v1 runtime acceptance. |
| Information, Oracle, observatory, shocks, reports | Code complete; latency proof pending | Exact pilots, new frontend, two-second WebSocket proof, shock suite, report automation. | Measure live Oracle p90. |
| Government, VC, experiments, calibration, replay, health | Code complete; lagging data pending | Five-seed harness, exact replay, government/VC/health integration. | Accumulate real prediction calibration evidence. |

## Remaining gaps and risks

### High — full-year production envelope is not yet proven

The subscription credentials authenticated successfully and the fresh one-tick run measured real calls, caching, latency, and modeled price-equivalent cost. A 365-day live run has not been attempted; it may consume meaningful plan quota and requires explicit authorization.

### Medium — subscription plans are not hosted-product entitlements

The configured MiniMax Token Plan and Kimi Code membership routes are appropriate for local development and agent-style evaluation. Before exposing a hosted or multi-user product, confirm commercial terms, rate limits, concurrency, and migrate to pay-as-you-go/product APIs where required.

### Medium — calibration is a lagging outcome

The calibration machinery is complete, but calibration quality cannot be established without a corpus of resolved real-provider predictions. This is an operational data requirement rather than missing code.

### Medium — production emergence remains unconfirmed

Three causal chains are documented and mechanically tested: credibility shock → deposit flight, oil shock → founder repricing, and policy rate → credit-officer loan quote. The five-seed rumor experiment shows a large offline treatment-control separation. Because these results use deterministic scripted agents, the strongest reading of the PRD's “not scripted” success gate still requires confirmation with the locked MiniMax/Kimi routes.

## Prioritized completion roadmap

1. **Prove the remaining operating envelope.** Run a representative Oracle question set, then an explicitly authorized long run that demonstrates a 365-day total at or below $200.
2. **Confirm live-provider emergence.** Repeat the three documented causal signatures and the five-seed experiment with the authenticated provider profile if quota permits.
3. **Accumulate calibration evidence.** Resolve enough live Oracle predictions to publish meaningful bins, Brier score, reliability, resolution, and uncertainty.
4. **Prepare hosted expansion separately.** Confirm provider commercial terms and concurrency limits before using these subscription endpoints in a multi-user deployment.

No speculative calendar estimate is assigned; completion depends primarily on credential and spend authorization.

## Verification snapshot

| Check | Result |
|---|---|
| Code baseline | `b2b25c0` on `fix/provider-live-readiness` |
| Python suite | **69 passed** in 77.02 seconds with `python -m pytest tests/ -q` |
| Frontend | `npm ci`, zero audit vulnerabilities, production build passed, repeated build produced identical hashes |
| Compile and hygiene | Python compile-all passed; `git diff --check` passed |
| Browser | Desktop and approximately 355px content widths, live ticker, per-agent costs after Step, internal table/ticker scrolling, and console diagnostics verified; no console errors |
| Live provider run | Run `3478260d9e`: 100 agents, 170 logical calls, 45/45 conversation messages, 71/71 daily summaries, zero provider failures, zero contract failures, and modeled price-equivalent cost $0.112542 |
| Replay CLI | Live source/replay: 27 deterministic tables, no live fallback, identical total hash `405b1d5ae37e58b7ab2c8a8baf6ac44a0c17ca134427a075e170fead4a9ce6c8` |
| Network assets | Production HTML references only committed `/static/assets/*`; no CDN dependency |
| CI | GitHub Actions run `29105715999` passed: dashboard build plus Python 3.11/3.12 on Ubuntu and Windows |

## Deferred P2 work — excluded from scores

| Future requirement | PRD disposition | Assessment |
|---|---|---|
| **R18 — Participant mode** | P2 future | Intentionally deferred; observer-only integrity remains preserved. |
| **R19 — Scale to approximately 1,000 agents** | P2 future | Intentionally deferred; current launch profile targets approximately 100. |
| **R20 — Regions and foreign exchange** | P2 future | Intentionally deferred. |
| **R21 — Real-data calibration** | P2 future | Intentionally deferred; future inputs must be versioned and provenance-aware. |
| **R22 — Hosted multi-user service** | P2 future | Intentionally deferred; v1 remains a local single-process observatory. |

## Assessment boundaries

- Generated databases and reports corroborate findings but do not outrank committed code and tests.
- Scripted runs prove deterministic mechanics; they do not substitute for real-provider budget, latency, caching, or calibration evidence.
- The documented offline causal phenomena do not substitute for real-provider emergence confirmation.
- Economic realism and parameter calibration are separate from PRD feature completion.
- Scores should be refreshed when the PRD, technical specification, provider profile, or acceptance evidence changes.
