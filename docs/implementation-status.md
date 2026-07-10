# Agent Economy — Implementation Status & PRD Gap Assessment

> **Assessment date:** 2026-07-10
>
> **Code baseline:** `feature/prd-completion` at `8d0e79c`
>
> **Product baseline:** [PRD v1.0](../PRD.md)
>
> **Technical baseline:** [Technical Specification v1.0](../TECH-SPEC.md)
>
> **Canonical status:** This Markdown document is the source of truth. The [HTML companion](implementation-status.html) contains the same verdict, scores, requirement states, and evidence.

## Executive verdict

**The repository is now feature-complete for the PRD-v1 P0/P1 scope, with production acceptance still conditional on a paid real-provider evidence run.** The deterministic economy, provider routing and failure handling, exact stored-response replay, two-year lifecycle proof, five-seed experiments, report automation, weekly memory, and specified React dashboard are implemented and tested. What remains is operational proof: authenticate the production MiniMax/Kimi profile, measure real latency and provider caching, and demonstrate the 365-day cost envelope without exceeding the $200 cap.

The three scores measure different qualities and should not be combined.

| Score | Result | Calculation | Meaning |
|---|---:|---:|---|
| **Feature coverage** | **100%** | 17.00 / 17 = 100.0% | All P0/P1 capability surfaces have substantive implementation. |
| **Acceptance proof** | **94%** | 16.00 / 17 = 94.1% | All deterministic gates are executable; four real-provider/lagging-evidence gates remain substantial rather than complete. |
| **Technical-spec fidelity** | **95%** | 13.25 / 14 = 94.6% | The locked architecture and frontend stack are present; current provider IDs and live operating proof remain qualified. |

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
| Provider runtime | MiniMax/Kimi production profile, key/model preflight, concurrency, retry, structured parsing, provider-reported cache accounting, hard budget governor, safe provider pause, and secret-safe diagnostics. | [Production profile](../runs/production.yaml), [gateway](../llm/gateway.py), [readiness](../llm/readiness.py) | Implemented and offline-tested; live run unproven |
| Banks, credit, firms, labor | Deposits/reserves, cross-bank settlement, loans/default, liquidity support, firm formation, lawyer validation, hiring, payroll, production, revenue, and bankruptcy. | [Credit](../engine/credit.py), [firms](../engine/firms.py), [company lifecycle acceptance](../tests/test_prd_completion.py) | Tested |
| Securities market | IPOs, holdings enforcement, price-time priority, partial fills, trade-derived prices, index, and circuit breakers. | [Exchange](../engine/exchange.py), [exchange tests](../tests/test_exchange.py) | Tested |
| Information economy | Reporter/editor newsroom, slanted outlets, conversations, memories, rumor exposure, trust movement, and bank-run transmission. | [Newsroom](../world/newsroom.py), [exact rumor pilot](../tests/test_governor_and_world.py) | Tested |
| Oracle | Read-only questions, probabilities, drivers, resolution rules, automatic 30-tick resolution, Brier score, calibration decomposition, and scorecards. | [Oracle](../oracle/analyst.py), [calibration](../oracle/calibration.py) | Tested; live p90 latency unproven |
| Shocks | Policy-rate, oil, rumor, slant, scandal, and epidemic scheduling with downstream effects. | [Shock engine](../world/shocks.py), [shock acceptance](../tests/test_prd_completion.py) | Tested |
| Lifecycle and health | Aging, sickness, death, estates, heirs/escheat, replacement arrivals, housing, job search, hospitals, insurers, premiums, claims, and epidemic multipliers. | [Lifecycle](../engine/lifecycle.py), [two-year acceptance](../tests/test_prd_completion.py) | Tested |
| Government and VC | Taxes, benefits, elections, bounded policy shifts, pitches, funding, cap tables, follow-ons, declines, and write-offs. | [Government](../engine/government.py), [VC](../engine/vc.py), [P1 tests](../tests/test_p1_features.py) | Tested |
| Experiments | Treatment/control arms, five seeds, isolated run databases, distributions, effect summaries, reconciliation, and Markdown/HTML reports. | [Harness](../experiments/harness.py), [five-seed acceptance](../tests/test_p1_harness_and_tools.py) | Tested |
| Replay | Read-only UI replay plus fresh-database engine re-execution from stored responses, no live fallback, copied cost accounting, and canonical per-table SHA-256 proof. | [Replay verifier](../world/replay_verify.py), [replay tests](../tests/test_prd_completion.py) | Tested and CLI-observed |
| Reports | Standalone Markdown/HTML reports with narrative, metrics, events, Oracle/calibration, cost, config, and seed; automatic generation after interactive or headless stop. | [Generator](../reports/generate.py), [report acceptance](../tests/test_prd_completion.py) | Tested and browser-observed |
| Observatory | Modular React/Vite/Tailwind/Recharts client, FastAPI REST/WebSocket backend, responsive tables, controls, metrics, institutions, information flow, Oracle, costs, shocks, replay, and agent audits. | [Dashboard source](../dashboard/src), [server](../server/app.py), [bundle acceptance](../tests/test_prd_completion.py) | Tested and manually observed |

## PRD requirement matrix

| Requirement | Priority | Implementation | Acceptance proof | Repository/test evidence | Remaining gap | Required completion evidence |
|---|---|---|---|---|---|---|
| **R1 — Conserved double-entry ledger** | P0 | Complete (1.00) | Complete (1.00) | Ledger invariant/tamper tests plus active-run corruption halt, diagnostic, reconciliation, and checkpoint acceptance. | None for v1. | Preserve invariant and active-failure tests. |
| **R2 — LLM agent runtime, persona, memory, decisions, inspector** | P0 | Complete (1.00) | Substantial (0.75) | Production routing/key validation, approximately 100-agent profile, weekly synthesis, stored prompts/responses, and browser-inspected agent audit. | No authenticated MiniMax/Kimi role sample has been archived. | Run all routed roles with real keys and retain secret-safe prompt/response/latency evidence. |
| **R3 — Banks, firms, labor, goods, complete company lifecycle** | P0 | Complete (1.00) | Complete (1.00) | Deterministic lawyer → formation → firm loan → hire → production → revenue → bankruptcy acceptance with ledger reconciliation. | None for v1 mechanics. | Preserve lifecycle regression. |
| **R4 — Order book, IPO, and market index** | P0 | Complete (1.00) | Complete (1.00) | Price-time, partial-fill, ownership, price-emergence, IPO, index, and circuit-breaker tests. | None for v1. | Preserve exchange tests. |
| **R5 — News, conversations, and rumor pilot** | P0 | Complete (1.00) | Complete (1.00) | Exact pilot asserts at least five conversations, ≥0.2 trust loss for ≥25% exposed agents, and normalized outflow above 2× baseline within ten ticks. | None for deterministic acceptance. | Repeat under the real-provider profile as production evidence. |
| **R6 — Oracle prediction, resolution, and Brier score** | P0 | Complete (1.00) | Substantial (0.75) | Prediction contract, insufficient-data handling, exact 30-tick automatic resolution, Brier scoring, and calibration tests. | Real-provider p90 response time below 60 seconds is unproven. | Run a representative live question set and publish p50/p90 latency with persisted predictions. |
| **R7 — Run control, cost governor, cap, and degradation visibility** | P0 | Complete (1.00) | Substantial (0.75) | Exact 60/80/95/100% stages, provider retry/cache billing, safe provider pause/checkpoint, Web UI visibility, and hard-cap code tests. | The 365-day real-provider run and measured cache savings are unproven. | Complete the paid long run, export cost by model/purpose/cache, and prove total spend ≤$200. |
| **R8 — Live observatory dashboard** | P0 | Complete (1.00) | Complete (1.00) | React stack/bundle test, WebSocket timestamp under two seconds, desktop/mobile browser pass, keyboard agent audit, and no browser console errors. | No v1 blocker. | Add automated visual/accessibility regression if the UI expands. |
| **R9 — Minimum shock catalogue and downstream effects** | P0 | Complete (1.00) | Complete (1.00) | Parameterized acceptance proves every required shock fires and changes the intended metric, belief, article, or market channel. | None for v1. | Preserve scenario tests. |
| **R10 — Automatic end-of-run report** | P0 | Complete (1.00) | Complete (1.00) | Paused and actively running Stop paths generate standalone reports with required sections and durable events; browser smoke confirmed a real file. | None for v1. | Preserve report content contract. |
| **R11 — Two-year lifecycle acceptance** | P0 | Complete (1.00) | Complete (1.00) | A 730-tick acceptance run proves death/estate, replacement arrival, conserved housing cost, job application within ten ticks, and reconciliation. | None for v1. | Keep the long test in CI. |
| **R12 — Government and elections** | P1 | Complete (1.00) | Complete (1.00) | Withholding, benefits, election bounds, integration, and determinism tests. | None for v1. | Future calibration only. |
| **R13 — Venture capital** | P1 | Complete (1.00) | Complete (1.00) | Pitch, investment, cap table, decline, follow-on, and write-off tests. | None for v1. | Future portfolio calibration only. |
| **R14 — Experiment harness** | P1 | Complete (1.00) | Complete (1.00) | Five treatment seeds plus five same-seed controls, isolated databases, distributions, reconciliation, and dual-format reports. | None for harness acceptance. | Archive a production-scale experiment after live-provider authorization. |
| **R15 — Oracle calibration dashboard** | P1 | Complete (1.00) | Substantial (0.75) | Calibration identity, run/all-run API, dashboard ledger, and report scorecard are implemented and tested. | A meaningful corpus of resolved real-provider predictions does not yet exist. | Accumulate cross-run predictions and publish bins, Brier, reliability, resolution, and uncertainty. |
| **R16 — Replay UI and exact replay** | P1 | Complete (1.00) | Complete (1.00) | Replay viewer plus fresh genesis re-execution; missing responses pause without provider calls; all deterministic tables and LLM accounting hash identically. | No engine/replay blocker. | Repeat the same proof on the first completed live run. |
| **R17 — Health economy** | P1 | Complete (1.00) | Complete (1.00) | Hospital/insurer flows, premiums, lapses, claims, illness multiplier, lifecycle integration, determinism, and long-run reconciliation coverage. | No v1 mechanics blocker. | Long-run actuarial calibration is product research, not missing implementation. |

### Totals

- Feature weights: `17.00 / 17 = 100.0%`, reported as **100%**.
- Acceptance weights: `16.00 / 17 = 94.1%`, rounded to **94%**.
- The one-point proof gap consists of four 0.25 deductions: real routed-role evidence, Oracle live latency, 365-day cost/cache proof, and accumulated calibration data.

## Technical-spec fidelity

| Technical commitment | Status | Weight | Evidence or qualification |
|---|---|---:|---|
| T1 — Dashboard/API/kernel/provider/store layering | Complete | 1.00 | React client, REST/WebSocket server, deterministic kernel, gateway, and SQLite remain separate. |
| T2 — Python, FastAPI, SQLite WAL | Complete | 1.00 | Implemented as specified; FastAPI lifespan API replaces deprecated startup events. |
| T3 — Ordered tick phases and cadence | Complete | 1.00 | Ordered phases, event waking, cadence, checkpointing, and deterministic execution are tested. |
| T4 — Persisted data model | Complete | 1.00 | Run, agent, institution, ledger, market, information, prediction, metric, shock, checkpoint, and call state are persisted. |
| T5 — Structured actions and validation | Complete | 1.00 | Provider output is parsed to envelopes; the engine validates every action and defaults invalid output safely. |
| T6 — Short, daily, consolidated weekly memory | Complete | 1.00 | Weekly summaries are synthesized before their daily source summaries are demoted. |
| T7 — Routing, concurrency, retry, caching, budget, logging | Substantial | 0.75 | All mechanics and provider-reported cached tokens are implemented; live cache-hit evidence is outstanding. |
| T8 — Locked cheap/strong real-provider role mix | Substantial | 0.75 | The production profile implements the mix with current official `MiniMax-M2.7` and `kimi-k2.6`; the PRD’s older names are not current provider IDs and live authentication is unproven. |
| T9 — Deterministic market mechanics | Complete | 1.00 | Banking, firms, labor, exchange, settlement, and bankruptcy are tested end to end. |
| T10 — Seeded lifecycle mechanics | Complete | 1.00 | Biology is PRNG-owned and the exact two-year integration test passes. |
| T11 — React, Vite, Tailwind, Recharts | Complete | 1.00 | Modular source, committed local bundle, CI build, responsive browser pass, and no CDN runtime. |
| T12 — Unit, acceptance, golden, property/cost strategy | Substantial | 0.75 | 53 tests cover invariants, exact acceptance, golden output, thresholds, and long runs; a dedicated randomized property-testing framework is not present. |
| T13 — Determinism, checkpoint, resume, replay, forks | Complete | 1.00 | Same-seed, golden, checkpoints, resume, parent-safe forks, and canonical full-state replay hashes are tested. |
| T14 — Repository layout and phased build | Complete | 1.00 | All specified packages and P1 surfaces, including the dashboard package, are present. |

Technical total: `13.25 / 14 = 94.6%`, rounded to **95%**.

## Phase status

| Phase | Verdict | Evidence | Exit condition |
|---|---|---|---|
| Kernel and accounting | Complete | Ledger invariants, active failure halt, diagnostics, and checkpoints. | Met. |
| Agents, banking, firms, markets | Code complete; production proof pending | Full deterministic mechanics and approximately 100-agent production profile. | Authenticate and sample every routed live role. |
| Information, Oracle, observatory, shocks, reports | Code complete; latency proof pending | Exact pilots, new frontend, two-second WebSocket proof, shock suite, report automation. | Measure live Oracle p90. |
| Government, VC, experiments, calibration, replay, health | Code complete; lagging data pending | Five-seed harness, exact replay, government/VC/health integration. | Accumulate real prediction calibration evidence. |

## Remaining gaps and risks

### High — paid production envelope is not yet proven

The current environment does not contain `MINIMAX_API_KEY` or `MOONSHOT_API_KEY`. No paid inference was attempted. The production profile, readiness checks, routes, retries, pause behavior, accounting, and budget stages are ready, but a 365-day live run may consume meaningful budget and requires explicit authorization.

### Medium — provider identifiers intentionally follow current official APIs

The historical PRD names MiniMax M3 and Kimi K2.7. The implementation uses currently documented `MiniMax-M2.7` and `kimi-k2.6` endpoints. This is an evidence-backed compatibility decision, but it should be recorded as a formal specification update before v1 sign-off.

### Medium — calibration is a lagging outcome

The calibration machinery is complete, but calibration quality cannot be established without a corpus of resolved real-provider predictions. This is an operational data requirement rather than missing code.

## Prioritized completion roadmap

1. **Authorize and preflight the real-provider profile.** Supply keys locally, run offline and live preflight, and verify every routed model without exposing secrets.
2. **Prove the operating envelope.** Run the approximately 100-agent production world, capture Oracle p50/p90, provider failures/retries, actual cached tokens, and a 365-day total at or below $200.
3. **Archive production acceptance.** Exact-replay the completed live run, retain the replay hash proof, config, seed, report, and cost evidence, then run a five-seed production experiment if budget permits.
4. **Close specification governance.** Amend the PRD model identifiers to their current official equivalents and add the production evidence links to this report.

No speculative calendar estimate is assigned; completion depends primarily on credential and spend authorization.

## Verification snapshot

| Check | Result |
|---|---|
| Code baseline | `8d0e79c` on `feature/prd-completion` |
| Python suite | **53 passed** in 312.12 seconds with `python -m pytest tests/ -q` |
| Frontend | `npm ci`, zero audit vulnerabilities, production build passed, repeated build produced identical hashes |
| Compile and hygiene | Python compile-all passed; `git diff --check` passed |
| Browser | Desktop and mobile-width layouts, Step, Stop, report file, shock dialog, replay viewer, charts, keyboard agent audit, and console diagnostics verified; no console errors |
| Replay CLI | One-day source/replay: 27 deterministic tables, 150 stored calls, identical total hash `7d10be27202c151ebf35368aad1def919f20d9b79c01671fc1f00c9b96dbec1d` |
| Network assets | Production HTML references only committed `/static/assets/*`; no CDN dependency |
| CI | Workflow now builds/verifies the dashboard and runs the Python matrix; branch run is pending push |

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
- Economic realism and parameter calibration are separate from PRD feature completion.
- Scores should be refreshed when the PRD, technical specification, provider profile, or acceptance evidence changes.
