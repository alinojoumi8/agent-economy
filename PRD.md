# Agent Economy — Product Requirements Document

**Version:** 1.0 · **Date:** 2026-07-09 · **Owner:** Ali · **Status:** Draft for review

---

## 1. Vision

A living, miniature US-style economy populated entirely by AI agents. Roughly 100 persona-driven agents — teachers, lawyers, economists, bankers, journalists, founders, investors — live, work, talk, borrow, invest, publish news, and vote inside a simulated world. Every economic decision is made by an LLM reasoning in character; every dollar is tracked by a deterministic engine so the economy stays internally consistent.

The purpose is not a game. It is an **observable laboratory**: run the world, inject shocks (a rate hike, a fake-news story, an oil spike), ask live questions ("what's the probability of a bank run this month?"), and watch whether the emergent outcome matches the prediction. The core scientific question: **how much of an economy is driven by talk, belief, and narrative rather than fundamentals?**

## 2. Key design decisions (locked)

These were decided during scoping and constrain everything below.

| Decision | Choice | Rationale |
|---|---|---|
| Who generates numbers | **LLMs decide, engine executes.** Agents output structured actions (borrow, hire, bid, publish); a deterministic engine validates and applies them via double-entry ledger and order matching. | Pure LLM-generated prices/balances don't reconcile. Conservation of money is what makes crashes and runs *real* within the sim. |
| LLM backend | **Provider-agnostic hybrid.** The gateway maps each role to any {provider, model} in config. Defaults: citizens + conversations + memory on **MiniMax M3** (Ali's API key); ~8 high-leverage seats (central banker, credit officers, editors/lead reporters, VC partner, Oracle) on **Kimi K2.7** (Ali's API key); Anthropic API optional as an alternative tier. **Claude/Codex/Grok CLI subscriptions are never used for the agent swarm** — rate limits and provider terms rule them out for bulk inference; Claude CLI (headless) is permitted for the Oracle and development only. | 100 agents thinking daily is cost-dominated by citizens; M3/K2.7 pricing makes runs ~4× cheaper than an Anthropic-only setup. Per-role provider config also enables a research angle: does the economy behave differently with different models as citizens? |
| Foundation | **Own kernel; strip existing frameworks for parts.** Rejected as base: AgentSociety 2 (pivoted to AI-social-scientist tooling; its economy modules live in the legacy, unmaintained 1.x), Doxa (single-maintainer v0.1 prototype, GPL-3.0, no double-entry banking layer), LLM-Economist (narrow tax-policy scope). Borrowed: LLM-Economist's census-based persona generation (MIT — vendored as code), Doxa's shock/trend/conditional event-trigger taxonomy (design idea only — no GPL code copied). | The frameworks provide the easy 20% (agent scaffolding); none contain the hard parts (conserved ledger, bank mechanics, order book + firm lifecycle, Oracle, cost governor, exact replay). |
| User's role | **Observer only.** Ali does not play an agent in v1. He controls the world (start/pause/speed/shocks) and interrogates it (Oracle), but no in-world avatar. | Keeps the sim uncontaminated; participant mode is a P2. |
| Interface | **Live web dashboard + end-of-run reports.** | Watch it unfold in real time, then get a written narrative + data appendix per run. |
| Run length | **Open-ended.** A run continues until stopped, with checkpointing so it can pause/resume across days. | Long-horizon emergent effects (inequality drift, boom-bust cycles) need time. |
| Budget | **Fully metered; cap is profile-specific.** Safety-capped profiles degrade before their configured ceiling. The production/acceptance profile is uncapped, waits through provider rate limits, and records actual spend. | The $200 figure is a measured efficiency target, not a production stop condition. This keeps capped development safe without terminating long production experiments. |
| Signature feature | **The Oracle** — a live analyst you can query mid-run ("probability of market crash within 30 days?"). It answers with a probability + reasoning, the prediction is logged, and the system later scores it against what actually happened. | This turns every run into an experiment and makes the sim's predictive value measurable (calibration/Brier scores). |

## 3. Problem statement

Real-world economic questions — "does misinformation cause bank runs?", "how do rate changes propagate through sentiment?" — cannot be tested experimentally on real economies. Traditional agent-based models (ABMs) use hand-coded rules, so they can't capture belief, persuasion, or narrative. LLM agents can hold beliefs, be persuaded, panic, and spread rumors — but no accessible tool exists that combines LLM agents with a rigorous economic engine and a live experimentation interface. Ali needs a personal research instrument to run these experiments end-to-end.

## 4. Goals

1. **A closed, consistent economy**: 100 agents transacting through banks, markets, and firms where money is conserved — the sum of all balance sheets reconciles to zero discrepancy at every tick.
2. **Emergence, not scripting**: at least three macro phenomena arise without being hard-coded, each documented with the metric signature that identifies it (e.g. CPI rising after money-supply expansion, unemployment rising after a demand shock, deposit flight after a credibility shock) — "not hard-coded" means no engine rule maps the cause to the effect directly; the path runs through agent decisions.
3. **Live interrogation**: the Oracle answers ad-hoc probability questions mid-run in under 60 seconds, and every prediction is scored against realized outcomes.
4. **Repeatable experiments**: every run is exactly replayable from its stored LLM responses (no API cost); fresh re-runs with the same seed and shock schedule are statistically comparable but not identical, since LLM outputs vary — different seeds ⇒ distribution of outcomes for the same experiment.
5. **Cost discipline**: capped profiles never exceed their configured ceiling; the uncapped production profile records actual spend and targets ≥ 365 simulated days within $200 on the default provider mix.

## 5. Non-goals (v1)

- **Not a game / no human player.** Participant mode ("I walk into the bank myself") is deferred — it contaminates observation and doubles UI scope.
- **No calibration to real US data.** The sim is US-*style* (institutions, instruments), not a forecast of the actual US economy. Matching real GDP/CPI series is a research project of its own.
- **No multi-country world, no FX.** One currency, one jurisdiction. Trade and FX are P2.
- **No real money, real trading, or real news ingestion.** Fully sandboxed; nothing connects to real markets.
- **No fine-tuning or custom model training.** Off-the-shelf APIs + prompting only.
- **Not 1,000+ agents.** Architecture should not preclude scale-up, but v1 targets ~100; population realism comes from persona diversity, not headcount.

## 6. The world — core concepts

### 6.1 Time
The world advances in **ticks (1 tick = 1 simulated day)** with phases inside each tick: morning (read yesterday's news per media diet, perceive, plan), workday (labor, production, transactions), market session (exchange open), evening (conversations; newsrooms write tomorrow morning's stories), night (memory consolidation, interest accrual, metrics snapshot). Wall-clock speed is adjustable; the sim pauses cleanly between ticks.

### 6.2 Agents (~100 at launch)
Every agent has:
- **Persona**: name, age, occupation, employer, income, wealth, personality traits, risk tolerance, political lean, media diet (which news outlets they read), social ties.
- **Memory**: recent events verbatim; older events compressed into daily/weekly summaries; retrieval by recency × importance × relevance.
- **State**: bank balances, portfolio, debts, employment status, owned businesses.
- **Beliefs**: evolving views (inflation expectations, trust in each bank, political stance) that decisions must reference.
- **Lifecycle**: age, health state (healthy/sick/critical), and dependents. Agents age, fall ill, retire, and die — all determined engine-side from seeded probability tables, never by the LLM (see R11). Agents *react* to these events through the normal decision loop.

Population mix (initial): ~70 households/workers across professions (teacher, nurse, engineer, lawyer, economist, retiree, student, gig worker…), ~10 firm founders/managers, ~20 institutional staff (bankers, exchange staff, journalists, VC partners, government officials).

### 6.3 Institutions
| Institution | Staffed by | What it does |
|---|---|---|
| Central bank | 1 governor (strong model) | Sets policy rate, lender of last resort, publishes statements |
| Commercial banks (2–3) | Credit officers, tellers | Deposits, loans (underwriting is an LLM decision), can face runs and fail |
| Stock exchange | Exchange operator | Real limit-order book; matching is deterministic; listing/IPO process |
| Firms (10–15 at start) | Founders + employees | Produce goods/services, set prices, hire/fire, seek funding, can go bankrupt |
| VC firm(s) | Partners | Evaluate pitches, buy equity, sit on boards |
| Law firm(s) | Lawyers | Incorporation, contracts (a required step to found a company) |
| News outlets (2, with different editorial slants) | Editors + reporters | Publish daily stories drawn from real sim events; feed every agent's context |
| Government (P1) | Officials | Flat tax, unemployment benefits, holds elections — entire fiscal layer arrives in P1 (R12) |

### 6.4 Markets
- **Labor**: firms post jobs with wages; agents apply; both sides negotiate (LLM).
- **Goods/services**: firms post prices; households choose what to buy given budgets (LLM choice, engine settles).
- **Credit**: loan applications underwritten by bank agents; engine enforces schedules, default mechanics, collateral.
- **Equity**: order-book exchange for listed firms; private rounds for startups (VC).

### 6.5 Information layer (the point of the whole thing)
News articles, public statements, and agent-to-agent conversations are first-class objects. What an agent reads and hears enters its context and shifts its beliefs, which shifts its economic behavior. Shocks can be injected *purely informationally* (a rumor, a slanted story) to test narrative-driven outcomes.

---

## 7. User stories

All stories have one user — Ali — in two modes: **Operator** (runs the world) and **Experimenter** (interrogates it).

### Operator
- As an operator, I want to start a new run from a seed and configuration file so that runs are reproducible.
- As an operator, I want to pause, resume, and change simulation speed at any time so that I can watch interesting moments closely and skip quiet periods.
- As an operator, I want the run to checkpoint automatically so that I can stop tonight and resume tomorrow without losing state.
- As an operator, I want a live dashboard showing macro metrics, the stock ticker, the news feed, and a stream of agent conversations so that I can follow the economy like a Bloomberg terminal for the sim.
- As an operator, I want to click any agent and inspect its persona, balance sheet, memories, and recent decisions (with the LLM reasoning) so that I can audit *why* something happened.
- As an operator, I want to see running API spend and any configured cap so that I'm never surprised by cost.

### Experimenter
- As an experimenter, I want to ask the Oracle free-form questions mid-run ("probability of a bank run within 30 days?") and get a probability with reasoning so that I can form hypotheses while the world runs.
- As an experimenter, I want every Oracle prediction logged with a resolution deadline and automatically scored when the deadline passes so that I learn how well the sim's own analyst can see ahead.
- As an experimenter, I want to inject shocks from a library (rate change, oil spike, rumor, slanted news story, firm scandal) at a chosen tick so that I can run controlled experiments.
- As an experimenter, I want an end-of-run report — narrative of what happened, key events timeline, all metric charts, Oracle scorecard — so that each run produces a shareable artifact.
- As an experimenter, I want to re-run the same configuration with different seeds so that I can distinguish robust effects from one-off noise.

### Edge cases
- As an operator, I want the sim to halt gracefully (checkpoint + alert) if the ledger fails to reconcile, so that a bug never silently corrupts an experiment.
- As an operator, I want capped profiles to degrade activity (fewer conversations per tick, stretched decision cadences) rather than kill the run when spend approaches the cap.
- As an experimenter, I want the Oracle to refuse with "insufficient data" rather than fabricate a number when the question is unanswerable from world state.

---

## 8. Requirements

### P0 — Must have (the sim is not viable without these)

**R1. Simulation engine with conserved money**
- Double-entry ledger for every account (households, firms, banks, government, central bank).
- Every action is validated before execution (no overdrafts unless a credit line exists; no selling shares you don't own).
- Acceptance: at every tick, sum of all assets minus liabilities across the system reconciles exactly; a failed reconciliation halts the run with a diagnostic dump.

**R2. Agent runtime (persona + memory + decision loop)**
- 100 agents generated from a persona template library with controlled diversity (occupation, wealth distribution, personality, political lean, media diet).
- Decision loop per agent per tick: perceive (world events + personal state + retrieved memories) → decide (LLM returns a structured action list) → engine executes.
- Memory: verbatim recent buffer, compressed summaries beyond that, retrieval scored by recency × importance × relevance.
- Acceptance: an agent inspector shows, for any decision, the exact prompt context and the returned action JSON.

**R3. Core institutions: banks + firms + labor + goods**
- ≥ 2 commercial banks taking deposits and underwriting loans (LLM credit decisions, engine-enforced repayment schedules, default and collateral seizure mechanics).
- Firms produce goods/services, set prices, hire/fire, pay wages, can go bankrupt (with creditor waterfall).
- Labor market (postings, applications, wage negotiation) and goods market (posted prices, budget-constrained household purchases).
- Acceptance: a full company lifecycle is observable — founding (via law firm), loan, hiring, revenue, and at least one bankruptcy path tested.

**R4. Stock exchange**
- Limit-order book with deterministic price-time-priority matching; market and limit orders; daily open/close.
- IPO/listing flow for firms that qualify; a market index computed from listed firms.
- Acceptance: prices emerge only from orders placed by agents; the engine never sets a price.

**R5. News outlets + conversation layer**
- 2 outlets with distinct editorial slants; reporter agents draw only on true sim events, but framing/selection is theirs; stories published daily.
- Agents consume news per their media diet; evening conversation phase pairs socially-connected agents; conversations are stored and searchable.
- Acceptance (rumor pilot): after injecting a false rumor about a bank, within 10 ticks (a) the rumor appears in ≥ 5 distinct conversations, (b) trust-in-that-bank belief drops ≥ 0.2 for ≥ 25% of exposed agents, and (c) that bank's deposit outflow exceeds 2× its pre-rumor baseline.

**R6. The Oracle**
- Chat interface on the dashboard; read access to all world state (metrics, ledgers, news, sampled conversations, order books) but **no write access** — it can never influence the world.
- Answers probability questions with: point estimate, key drivers, confidence, and an auto-created resolution criterion + deadline.
- Predictions logged; resolved automatically when determinable from world state; Brier score tracked over the run.
- Acceptance: "What is the probability of a bank run within 30 ticks?" returns a structured prediction in < 60s; 30 ticks later it is scored without human input.

**R7. Run control + cost governor**
- Start/pause/resume/speed controls; automatic checkpoints every N ticks; phase-aware resume keeps the last fully completed tick plus the active tick/next-phase cursor.
- Real-time token/cost accounting per model, per agent, per subsystem; optional budget cap with staged degradation (reduce conversation count → stretch decision cadences → institutional-agents-only mode → clean pause with alert).
- HTTP 429 throttling and explicit provider-overload responses (including MiniMax HTTP 529) create a visible provider-wide cooldown and retry until recovery or operator stop; other continuing provider failures pause on the active phase without advancing the completed tick.
- Acceptance: a capped $200 profile never exceeds it; uncapped production records actual spend; degradation, rate-limit, and resume state are visible.

**R8. Live dashboard**
- Panels: macro metrics time series (GDP proxy, CPI, unemployment, policy rate, money supply, Gini, sentiment index), stock ticker + index chart, live news feed, conversation stream, agent inspector, bank balance sheets, Oracle chat, event/shock log, cost meter.
- Acceptance: dashboard receives each tick's updates within 2 seconds of tick completion; usable while the sim runs.

**R9. Shock injection (minimum library)**
- At minimum: policy-rate override, commodity (oil) price shock, false-rumor injection targeted at a bank, slanted-news directive to one outlet, firm scandal.
- Three trigger types (taxonomy borrowed from Doxa's design): **shock** (instant at tick N), **trend** (gradual effect over a duration), **conditional** (fires when a metric crosses a threshold, e.g. "if unemployment > 8%, government stimulus").
- Scheduled in config or fired live from the dashboard.
- Acceptance: each shock type produces a logged event and observable downstream effects in at least one test run.

**R10. End-of-run report**
- Generated on stop: narrative summary (LLM-written from the event log), timeline of key events, all metric charts, Oracle prediction scorecard, cost summary, config + seed for reproduction.
- Acceptance: the complete standalone HTML artifact is saved per run with embedded charts; a reviewer-oriented Markdown companion carries the narrative, metric snapshot, Oracle/calibration summary, cost table, config, and seed.

**R11. Agent lifecycle: health, death, aging, population renewal**
- **Biology is engine-side, reactions are LLM-side**: sickness, death, and aging are drawn from the seeded PRNG using age-weighted probability tables; the LLM never decides who gets sick or dies (this preserves replayability and prevents narrative-driven deaths).
- Health states: healthy → sick → critical. Sick agents skip labor that tick (lost wages) and pay out-of-pocket medical costs; critical agents face elevated mortality until recovery.
- Death: age-weighted mortality plus critical-illness escalation. Estate settlement runs through the ledger — creditor waterfall first, remainder to the heir (strongest social tie, deterministic rule), escheat to government if none. Shares transfer to the heir; a sole-proprietor firm with no successor winds down via the existing bankruptcy path. Deaths are events: they feed news and conversations (a founder's death is a market event).
- Aging + retirement: age increments each simulated year; agents exit the labor force at ~65 and live off savings/pension draw-down.
- Births are **household events**, not new agents: dependent count increases and spending patterns shift. Population is replenished by new adult **arrivals** ("moved to town") generated from the persona library, keeping the population ~100 (stable-population default; per approved decision 2026-07-09).
- Acceptance: (a) over a 2-sim-year test run, at least one death settles its estate with the ledger reconciling to zero discrepancy; (b) a sick agent's wage loss and medical spending are visible in its ledger; (c) an arrival integrates — gets housing costs, seeks a job — within 10 ticks of spawning; (d) identical seed ⇒ identical lifecycle event schedule.

### P1 — Should have (fast follows)

**R12. Government fiscal layer + elections.** Flat income tax funding unemployment benefits; periodic elections where agents vote based on beliefs/economic experience; election outcomes shift fiscal policy within bounds. *(The "political views" outcome Ali wants — first-class but not needed to prove the core loop.)*
**R13. VC / private funding track.** Pitch → partner evaluation → term sheet → equity on cap table → follow-on or write-off. Founding via bank loan works in P0; VC adds the risk-capital channel.
**R14. Experiment harness.** Define experiment = {config, seed set, shock schedule, metrics of interest}; run N seeds; produce a comparison report with outcome distributions.
**R15. Oracle calibration dashboard.** Reliability curves and Brier decomposition across many predictions and runs.
**R16. Replay mode.** Re-watch any past run tick-by-tick from stored events without re-running LLMs.
**R17. Health economy.** Hospitals/doctors as firms, health insurance products, epidemics as a trend-type shock — builds on R11's health states.

### P2 — Future (design so we don't preclude them)

**R18. Participant mode.** Ali (or an external LLM) plays an in-world agent through the same action API agents use.
**R19. Scale to 1,000+ agents** via a two-tier population: fully-simulated core + statistically-simulated periphery.
**R20. Multi-region / trade / FX.**
**R21. Real-data calibration mode** — initialize distributions from real US micro data (income, wealth, firm size).
**R22. Public/multi-user version** — multiple observers, shared runs, hosted deployment.

---

## 9. Success metrics

### Leading (first weeks of use)
| Metric | Target | Stretch |
|---|---|---|
| Ledger reconciliation failures per run | 0 | 0 |
| Simulated days achieved within $200 (default config) | ≥ 365 | ≥ 1,000 |
| Oracle response time (p90) | < 60s | < 20s |
| Distinct emergent phenomena reproduced (documented, not scripted) | 3 | 5 |
| Shock → traceable downstream effect (pilot experiments passing) | 5/5 shock types | — |

### Lagging (after ~10 full runs)
| Metric | Target |
|---|---|
| Oracle Brier score vs. naive p=0.5 baseline, over all resolved predictions | Beats baseline |
| Replays from stored LLM responses reproduce identical event logs | 100% |
| Cross-seed experiment (N=5) produces interpretable outcome distribution | ≥ 1 written-up experiment |
| Ali still using it weekly a month after v1 (qualitative north star) | Yes |

**Measurement**: all metrics computed from the run database; no manual counting.

---

## 10. Open questions

**Blocking (answer before build starts)**
1. *(Engineering)* Conversation volume is the main cost lever: how many agent-pair conversations per evening phase at launch? Proposal: 15 pairs/tick, governor-adjustable. → **Proposed default: 15.**
2. *(Design)* Do citizens act every tick, or on personal cadences (shop daily, review portfolio weekly)? Cadenced acting cuts cost ~60% and is more realistic. → **Proposed: cadenced.**

**Non-blocking (resolve during build)**
3. *(Engineering)* SQLite vs Postgres for the run store — SQLite is simpler and likely sufficient for 100 agents; revisit at scale-up.
4. *(Design)* Should news reporters be allowed to interview agents (extra LLM calls) or only observe events? Start observe-only.
5. *(Design)* Central banker: rule-bounded (Taylor-rule guardrails + LLM discretion inside the band) or fully discretionary? Start rule-bounded to avoid absurd policy.
6. *(Experiment design)* Which pilot experiment ships as the acceptance demo — rumor-driven bank run, or rate-hike transmission? Rumor bank run is the more novel showcase.

---

## 11. Phasing

| Phase | Scope | Exit criterion |
|---|---|---|
| **Phase 1 — Kernel** (weeks 1–3) | Engine + ledger, 20 agents, 1 bank, labor + goods markets, CLI only, cost governor | 30 simulated days, money conserved, readable event log |
| **Phase 2 — Markets & media** (weeks 4–6) | Stock exchange, 2nd bank, news outlets, conversations, 100 agents, lifecycle (health/death/arrivals), checkpointing | Rumor-propagation pilot passes (R5) + lifecycle mechanics verified (R11) |
| **Phase 3 — Observatory** (weeks 7–9) | Dashboard, Oracle + prediction scoring, shock library, end-of-run reports | Full R6–R10 acceptance; first complete metered production run |
| **Phase 4 — P1 items** (weeks 10+) | Government + elections, VC track, experiment harness, replay | First multi-seed experiment written up |

Timeline assumes part-time solo build with AI-assisted coding; phases are scope-gated, not date-gated.

---

## 12. Companion document

Technical architecture, data model, action schema, prompt design, and cost math live in **TECH-SPEC.md**.
