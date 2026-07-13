# Agent Economy — Implementation Status & PRD Gap Assessment

> **Assessment date:** 2026-07-12
>
> **Code baseline:** `codex/research-validity-v1`, based on merged `main` at `07ba53d`
>
> **Product baseline:** [PRD v1.0](../PRD.md)
>
> **Technical baseline:** [Technical Specification v1.0](../TECH-SPEC.md)
>
> **Canonical status:** This Markdown document is the source of truth. The [HTML companion](implementation-status.html) contains the same verdict, scores, requirement states, and evidence.

## Executive verdict

**The repository is feature-complete for the PRD-v1 P0/P1 scope, including the research-validity hardening exposed by the first 100-agent live run.** New runs keep private bank fundamentals out of citizen contexts, validate and audit belief changes, measure relative rumor effects from persisted history, separate final-goods output from wages, and expose correctly windowed inflation plus live acceptance progress. Free rehearsal `5f5eac3794` completed 365 ticks and passed every deterministic gate; its only failed receipt gate was the intentional real-provider requirement. The stopped paid run `f7c6238bf5` remains diagnostic evidence and cannot be the final receipt. Remaining work is operational proof—a capped post-fix pilot, a representative live Oracle sample, the 365-day/$200 live envelope, calibration data, and live-provider causal signatures.

The three scores measure different qualities and should not be combined.

| Score | Result | Calculation | Meaning |
|---|---:|---:|---|
| **Feature coverage** | **100%** | 17.00 / 17 = 100.0% | All P0/P1 capability surfaces have substantive implementation. |
| **Acceptance proof** | **94%** | 16.00 / 17 = 94.1% | Deterministic gates are complete; R5, R6, R7, and R15 each still need post-fix or lagging live evidence. |
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
| Agents and memory | Persona generation, role-scoped information, cadence, context, short/daily/weekly memory synthesis, bounded beliefs, provenance events, decisions, and full inspector data. | [Runtime](../agents/runtime.py), [memory](../agents/memory.py), [research-validity tests](../tests/test_research_validity.py) | Tested |
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
| **R5 — News, conversations, and rumor pilot** | P0 | Complete (1.00) | Substantial (0.75) | Rehearsal `5f5eac3794` used actual belief history, a true 20% relative threshold, largest-bank/current-depositor targeting, and exact-run evidence binding: 36/40 trust drops, 83 conversations, and $3.13M simulated outflow. The refreshed N=5 study reconciled all 10 arms. | The corrected public-information scenario has not yet been rerun with live providers. | Pass the capped 30-day live pilot before the full acceptance run. |
| **R6 — Oracle prediction, resolution, and Brier score** | P0 | Complete (1.00) | Substantial (0.75) | Prediction contract, bounded evidence, exact resolution, scoring, and one live Oracle answer at 28.48 seconds. The acceptance profile now requires at least five latency samples. | One sample cannot establish p90. | Complete the six-question production schedule and publish persisted p50/p90 evidence. |
| **R7 — Run control, cost governor, cap, and degradation visibility** | P0 | Complete (1.00) | Substantial (0.75) | Exact budget stages, durable events, safe pause/resume, uncapped policy reporting, and a separate machine-checkable $200 efficiency target. Diagnostic run `f7c6238bf5` spent $24.232937 through 76 ticks. | The 365-day real-provider target remains unproven. | Complete the paid long run and prove actual spend ≤$200. |
| **R8 — Live observatory dashboard** | P0 | Complete (1.00) | Complete (1.00) | React bundle, live ticker, belief provenance, per-agent costs, acceptance progress/projected spend, responsive keyboard audit, and local-only assets. | No v1 blocker. | Add automated visual/accessibility regression if the UI expands. |
| **R9 — Minimum shock catalogue and downstream effects** | P0 | Complete (1.00) | Complete (1.00) | Parameterized acceptance proves every required shock fires and changes the intended metric, belief, article, or market channel. | None for v1. | Preserve scenario tests. |
| **R10 — Automatic end-of-run report** | P0 | Complete (1.00) | Complete (1.00) | Paused and actively running Stop paths generate standalone reports with required sections and durable events; browser smoke confirmed a real file. | None for v1. | Preserve report content contract. |
| **R11 — Two-year lifecycle acceptance** | P0 | Complete (1.00) | Complete (1.00) | A 730-tick acceptance run proves death/estate, replacement arrival, conserved housing cost, job application within ten ticks, and reconciliation. | None for v1. | Keep the long test in CI. |
| **R12 — Government and elections** | P1 | Complete (1.00) | Complete (1.00) | Withholding, benefits, election bounds, integration, and determinism tests. | None for v1. | Future calibration only. |
| **R13 — Venture capital** | P1 | Complete (1.00) | Complete (1.00) | Pitch, investment, cap table, decline, follow-on, and write-off tests. | None for v1. | Future portfolio calibration only. |
| **R14 — Experiment harness** | P1 | Complete (1.00) | Complete (1.00) | The 2026-07-12 rerun completed five treatment seeds plus five same-seed controls in 29.7 seconds: all arms reconciled, treatment averaged 16.8 deposit moves versus zero controls, and the committed [measured write-up](experiments/rumor-vs-control.md) records distributions. | None for harness acceptance. | Archive a production-scale real-provider experiment after authorization. |
| **R15 — Oracle calibration dashboard** | P1 | Complete (1.00) | Substantial (0.75) | Calibration identity, run/all-run API, dashboard ledger, and report scorecard are implemented and tested. | A meaningful corpus of resolved real-provider predictions does not yet exist. | Accumulate cross-run predictions and publish bins, Brier, reliability, resolution, and uncertainty. |
| **R16 — Replay UI and exact replay** | P1 | Complete (1.00) | Complete (1.00) | Replay viewer plus fresh genesis re-execution; missing responses pause without provider calls; all 27 deterministic tables and LLM accounting hash identically on the [completed live run](live-provider-validation.md). | None for v1 replay acceptance. | Preserve the live-run canonical replay regression. |
| **R17 — Health economy** | P1 | Complete (1.00) | Complete (1.00) | Hospital/insurer flows, premiums, lapses, claims, illness multiplier, lifecycle integration, determinism, and long-run reconciliation coverage. | No v1 mechanics blocker. | Long-run actuarial calibration is product research, not missing implementation. |

### Totals

- Feature weights: `17.00 / 17 = 100.0%`, reported as **100%**.
- Acceptance weights: `16.00 / 17 = 94.1%`, rounded to **94%**.
- The 1.00-point proof gap consists of four 0.25 deductions: post-fix live rumor proof, representative Oracle latency, the 365-day cost target, and accumulated calibration data.

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
| T12 — Unit, acceptance, golden, property/cost strategy | Complete | 1.00 | 144 tests include randomized mechanics, lifecycle storms, role-scoped bank data, true relative rumor effects, belief provenance, participant history/resume/replay, macro windows, exact v3/legacy replay, budget transitions, documentation integrity, golden output, long runs, and acceptance. |
| T13 — Determinism, checkpoint, resume, replay, forks | Complete | 1.00 | Same-seed, golden, checkpoints, resume, parent-safe forks, and canonical full-state replay hashes are tested. |
| T14 — Repository layout and phased build | Complete | 1.00 | All specified packages and P1 surfaces, including the dashboard package, are present. |

Technical total: `14.00 / 14 = 100.0%`, reported as **100%**.

## Phase status

| Phase | Verdict | Evidence | Exit condition |
|---|---|---|---|
| Kernel and accounting | Complete | Ledger invariants, active failure halt, diagnostics, and checkpoints. | Met. |
| Agents, banking, firms, markets | Complete | Full deterministic mechanics plus an authenticated 100-agent MiniMax/Kimi run. | Met for v1 runtime acceptance. |
| Information, Oracle, observatory, shocks, reports | Code complete; live latency proof pending | The 365-tick rehearsal passed rumor and every shock/evidence gate with six Oracle samples; local UI/API smoke passed. | Measure live Oracle p90. |
| Government, VC, experiments, calibration, replay, health | Code complete; lagging data pending | Five-seed harness, exact replay, government/VC/health integration. | Accumulate real prediction calibration evidence. |

## Remaining gaps and risks

### High — full-year production envelope is not yet proven

The subscription credentials authenticated successfully and diagnostic run `f7c6238bf5` reached tick 76 with 100 agents, exact reconciliation, one resolved Oracle prediction, and $24.232937 recorded spend before the operator stopped it. That run predates the research-validity changes and failed its rumor window, so it cannot be resumed as final acceptance. A new 365-day run requires a successful capped pilot and explicit authorization.

### Medium — subscription plans are not hosted-product entitlements

The configured MiniMax Token Plan and Kimi Code membership routes are appropriate for local development and agent-style evaluation. Before exposing a hosted or multi-user product, confirm commercial terms, rate limits, concurrency, and migrate to pay-as-you-go/product APIs where required.

### Medium — calibration is a lagging outcome

The calibration machinery is complete, but calibration quality cannot be established without a corpus of resolved real-provider predictions. This is an operational data requirement rather than missing code.

### Medium — production emergence remains unconfirmed

Three causal chains are documented and mechanically tested: credibility shock → deposit flight, oil shock → founder repricing, and policy rate → credit-officer loan quote. The first live run showed why epistemic boundaries matter: citizens received exact reserve ratios and rejected a false rumor about the visibly strongest bank. New profiles remove that private signal and persist actual belief deltas, but the strongest reading of the PRD's “not scripted” success gate still requires a post-fix MiniMax/Kimi pilot.

## Prioritized completion roadmap

1. **Pass the bounded pilot.** With explicit approval, run the capped 30-day rumor profile and require its conversation, relative trust, outflow, ledger, provider, latency, and spend gates to pass.
2. **Prove the operating envelope.** Run the six-question Oracle schedule, then a separately authorized 365-day production run at or below the $200 efficiency target.
3. **Deepen research quality.** Add preregistered hypotheses, effect sizes/confidence intervals, and a causal explorer linking exposure → belief → action → economic effect.
4. **Accumulate calibration evidence.** Resolve enough live Oracle predictions to publish meaningful bins, Brier score, reliability, resolution, and uncertainty.
5. **Keep hosted expansion deferred and participant runs isolated.** The participant sandbox is implemented, but its evidence is explicitly disqualified from observer-only acceptance.

No speculative calendar estimate is assigned; completion depends primarily on credential and spend authorization.

## Verification snapshot

| Check | Result |
|---|---|
| Code baseline | `codex/participant-acceptance-v1`, based on merged `main` at `70ed92e` |
| Python suite | **144 passed in 201.27 seconds** with `python -m pytest tests/ -q` |
| Frontend/dependencies | **9 tests passed**; 595-module Vite production build passed; dependency audit and environment checks remain part of the release gate |
| Compile and hygiene | Python compile-all, documentation link/profile checks, and `git diff --check` passed |
| Local API/UI smoke | Provider-free participant run `171cddcb1b`: root and history bundle returned 200, continuous Run was blocked under control, a queued command executed at tick 1, paginated history exposed its result, release succeeded, spend remained $0, and stderr contained no error/critical/traceback finding |
| Free acceptance rehearsal | Run `5f5eac3794`: 101 agents, 365 ticks, exact ledger, six resolved Oracle samples, all five shocks/traces, 36/40 relative rumor drops, 83 qualifying conversations, valid metric windows/belief bounds, and zero failure events; only `real_providers` intentionally failed |
| Live diagnostic | Run `f7c6238bf5`: 100 agents, paused at tick 76, exact ledger, one 28.48-second Oracle sample, $24.232937 spend, zero provider/contract failures; preserved as pre-fix diagnostic evidence |
| Replay | New semantics-v3 belief events and legacy v1/v2/golden behavior pass exact replay regressions; prior live source/replay retained identical 27-table hash `405b1d5ae37e58b7ab2c8a8baf6ac44a0c17ca134427a075e170fead4a9ce6c8` |
| Network assets | Production HTML references only committed `/static/assets/*`; no CDN dependency |
| CI | Latest `main` GitHub Actions run `29205841686` passed; fresh branch CI is required after push |

## Deferred P2 work — excluded from scores

| Future requirement | PRD disposition | Assessment |
|---|---|---|
| **R18 — Participant mode** | Implemented extension | Sandbox-only one-citizen control uses a role-scoped catalogue, one command per completed-day boundary, the normal validator/ledger, paginated inspector history, restart-safe state, exact replay, and browser controls. Acceptance profiles reject participant mode and receipts fail observer integrity when influence is present. |
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
