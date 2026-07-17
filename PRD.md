# Agent Economy — Product Requirements Document

**Version:** 1.1 · **Date:** 2026-07-16 · **Owner:** Ali · **Status:** Maintained implementation contract

---

## 1. Vision

A living, miniature US-style economy populated entirely by AI agents. Roughly 100 persona-driven agents — teachers, lawyers, economists, bankers, journalists, founders, investors — live, work, talk, borrow, invest, publish news, and vote inside a simulated world. Every economic decision is made by an LLM reasoning in character; every dollar is tracked by a deterministic engine so the economy stays internally consistent.

The purpose is not a game. It is an **observable laboratory**: run the world, inject shocks (a rate hike, a fake-news story, an oil spike), ask live questions ("what's the probability of a bank run this month?"), and watch whether the emergent outcome matches the prediction. The core scientific question: **how much of an economy is driven by talk, belief, and narrative rather than fundamentals?**

## 2. Key design decisions (locked)

These were decided during scoping and constrain everything below.

| Decision | Choice | Rationale |
|---|---|---|
| Who generates numbers | **LLMs decide, engine executes.** Agents output structured actions (borrow, hire, bid, publish); a deterministic engine validates and applies them via double-entry ledger and order matching. | Pure LLM-generated prices/balances don't reconcile. Conservation of money is what makes crashes and runs *real* within the sim. |
| LLM backend | **Provider-agnostic hybrid.** The gateway maps each role to any {provider, model} in config. The maintained production profile routes citizens/founders to **MiniMax-M3** and high-leverage institutional seats plus the Oracle to Kimi Code's stable **`kimi-for-coding`** alias; conversation and memory calls inherit the actor's route. Anthropic API remains an optional alternative tier. **Claude/Codex/Grok CLI subscriptions are never used for the agent swarm** — rate limits and provider terms rule them out for bulk inference; the restricted CLI adapter is permitted for Oracle/development purposes only. | Citizen decisions dominate call volume, so per-role routing preserves cost control and enables model-vs-model economy experiments without hard-coding a provider. |
| Foundation | **Own kernel; selectively adapt published ideas.** Rejected as base: AgentSociety 2 (pivoted to AI-social-scientist tooling; its economy modules live in the legacy, unmaintained 1.x), Doxa (single-maintainer v0.1 prototype, GPL-3.0, no double-entry banking layer), LLM-Economist (narrow tax-policy scope). Inspired by: LLM-Economist's persona-conditioning approach (clean synthetic-heuristic implementation with pinned attribution; no upstream code vendored) and Doxa's shock/trend/conditional event-trigger taxonomy (design idea only; no GPL code copied). | The frameworks provide the easy 20% (agent scaffolding); none contain the hard parts (conserved ledger, bank mechanics, order book + firm lifecycle, Oracle, cost governor, exact replay). |
| User's role | **Observer-only acceptance baseline.** Ali controls the world (start/pause/speed/shocks) and interrogates it (Oracle). The implemented R18 participant extension is isolated and its runs are excluded from observer-only acceptance. | Preserves an uncontaminated v1 research baseline while permitting separately classified participant experiments. |
| Interface | **Live web dashboard + end-of-run reports.** | Watch it unfold in real time, then get a written narrative + data appendix per run. |
| Run length | **Open-ended.** A run continues until stopped, with checkpointing so it can pause/resume across days. | Long-horizon emergent effects (inequality drift, boom-bust cycles) need time. |
| Budget | **Fully metered; cap is profile-specific.** Safety-capped profiles degrade before their configured ceiling. The production/acceptance profile is uncapped, waits through provider rate limits, and records actual spend. | The $200 figure is a measured efficiency target, not a production stop condition. This keeps capped development safe without terminating long production experiments. |
| Agent information | **Public information by default.** Citizens and founders see their own finances plus public bank identity/status, news, conversations, and memories; they do not receive private reserve ratios. Credit officers see their own bank; the central banker, Oracle, dashboard, and reports retain full ground truth. | Narrative experiments are invalid if citizens can disprove a rumor from private balance-sheet data unavailable to real depositors. |
| Macro measurement | **Final-goods output and labor income are separate.** Daily/30-day GDP proxies use final-goods sales; wages are a separate labor-income series. True year-over-year CPI requires 365 completed days. | Prevents double counting, payday spikes, and short-run changes being mislabeled as year-over-year inflation. |
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

- **The v1 acceptance baseline has no human player.** The later R18 participant extension is implemented, but participant-influenced runs are separately classified and cannot satisfy observer-only acceptance.
- **The v1 acceptance baseline has no calibration to real US data.** The optional R21 initialization mode now samples pinned U.S. income/wealth/firm-size supports, but the sim remains US-*style* rather than a forecast and does not match real GDP/CPI paths.
- **The v1 acceptance baseline is one region and one currency.** The optional R20 multi-region/trade/FX extension is implemented under later semantics and is not required for v1 acceptance.
- **No real money, real trading, or real news ingestion.** Fully sandboxed; nothing connects to real markets.
- **No fine-tuning or custom model training.** Off-the-shelf APIs + prompting only.
- **The v1 acceptance profile targets approximately 100 agents.** The optional R19 core/periphery extension now supports a deterministic 1,000-agent run, but it does not redefine the v1 baseline.

## 6. The world — core concepts

### 6.1 Time
The world advances in **ticks (1 tick = 1 simulated day)** with phases inside each tick: morning (read yesterday's news per media diet, perceive, plan), workday (labor, production, transactions), market session (exchange open), evening (conversations; newsrooms write tomorrow morning's stories), night (memory consolidation, interest accrual, metrics snapshot). Wall-clock speed is adjustable; the sim pauses cleanly between ticks.

### 6.2 Agents (~100 at launch)
Every agent has:
- **Persona**: name, age, occupation, employer, income, wealth, personality traits, risk tolerance, political lean, media diet (which news outlets they read), social ties.
- **Memory**: recent events verbatim; older events compressed into daily/weekly summaries; retrieval uses the weighted additive score `0.5·recency_decay + 0.3·importance + 0.2·relevance`.
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
- As an operator, I want to click any agent and inspect its persona, balance sheet, memories, and recent decisions with their short public rationale and local provenance so that I can audit *why* something happened without exposing private model reasoning.
- As an operator, I want to see running API spend and any configured cap so that I'm never surprised by cost.
- As a hosted administrator, I want invite-only membership and tenant-scoped roles so that separate research groups cannot inspect or control each other's runs.
- As a hosted observer, I want to watch a shared run while a single authorized writer controls it so that collaboration never creates two competing simulation clocks.

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
- The simulator owns an `agents.personas.library` boundary around an attributed clean synthetic-heuristic sampler. It remains the default and supplies fictional identity/traits in R21; the explicit `real_us` mode overlays only pinned SCF/SUSB initialization fields. New adult arrivals retain engine-owned age, wealth, accounts, region, and lifecycle state; before their first morning decision, exactly one governed `role=persona, purpose=persona` completion may enrich only bounded persona traits. Provider/budget pauses resume normally, malformed successful output falls back deterministically, and replay fails closed when the recorded persona response is missing.
- Decision loop per agent per tick: perceive (world events + personal state + retrieved memories) → decide (LLM returns a structured action list) → engine executes.
- Memory: verbatim recent buffer, compressed summaries beyond that, retrieval scored by `0.5·recency_decay + 0.3·importance + 0.2·relevance` (a weighted sum, not a product).
- Reserved beliefs have defined numeric ranges and every accepted, normalized, or rejected update is appended to the event spine with provenance.
- Acceptance: an agent inspector shows, for any decision, the exact prompt context, returned action JSON, and belief-update history.

**R3. Core institutions: banks + firms + labor + goods**
- ≥ 2 commercial banks taking deposits and underwriting loans (LLM credit decisions, engine-enforced repayment schedules, default and collateral seizure mechanics).
- Under maintained semantics 7, default seizes eligible collateral first and recognizes only unrecovered principal as a balanced `loan_loss_chargeoff` from the bank's currency-matched equity account to `SYS_LOSS`. The default event exposes recovered and net charged-off amounts. Stored semantics 1–6 keep their original behavior.
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
- Rumor experiments may resolve the largest bank at fire time and target current depositors; resolved bank and audience IDs are persisted without directly changing beliefs or balances.
- Acceptance (rumor pilot): after injecting a false rumor about a bank, within 10 ticks (a) the rumor appears in ≥ 5 distinct conversations, (b) trust-in-that-bank belief falls by at least 20% relative to each agent's actual pre-rumor value for ≥ 25% of exposed agents, and (c) that bank's deposit outflow exceeds 2× its pre-rumor baseline.

**R6. The Oracle**
- Chat interface on the dashboard; read access to all world state (metrics, ledgers, news, sampled conversations, order books) but **no write access** — it can never influence the world.
- Answers probability questions with: point estimate, key drivers, confidence, and an auto-created resolution criterion + deadline.
- Predictions logged; resolved automatically when determinable from world state; Brier score tracked over the run.
- Acceptance: "What is the probability of a bank run within 30 ticks?" returns a structured prediction in < 60s; 30 ticks later it is scored without human input.
- Release calibration evidence is evaluated only from an explicit, versioned manifest of finalized live-Oracle runs; directory pooling, replay/fork/dev runs, scripted Oracle calls, and post-hoc seed substitution are ineligible. The campaign floor is 10 unique runs and 60 resolved forecasts spanning both outcome classes, with prediction-bound end-to-end p90 < 60s and aggregate Brier score < the fixed p=0.5 baseline of 0.25. `--oracle-campaign-run` finalizes each source and creates its exact offline companion replay; the aggregate evaluator recomputes that proof rather than inferring replay fidelity or accepting an independently substituted replay. The persisted scheduled interval is conservatively clamped to at least the sum of its governed planning/answer call latencies, preventing separately rounded provider clocks from making the enclosing completion event shorter than its own calls.
- Oracle campaign V7 is excluded diagnostic evidence. Seeds 7361–7364 produced passed, eligible source receipts with exact tick-335 companion replays. Seed 7365 remains paused at tick 335 in `FINALIZE`; its continuously measured completion latency was 13,658 ms while its governed calls summed to 13,660 ms, so receipt validation correctly rejected that two-millisecond floor violation before any replay or source receipt was published. This is the continuous scheduled-latency floor defect. The source is claim-bound to the original clean Git revision and is never resumed, repaired, substituted, or post-fix receipted. Seeds 7366–7370 were never run, and no V7 artifact or seed enters a later corpus.
- Oracle campaign V8 is archived and excluded. Seeds 7371–7374 produced passed, eligible source receipts with exact tick-335 companion replays and zero differences. Seed 7375 stopped at tick 245 after Kimi returned a billing-cycle usage-limit failure; the persisted `provider_failure` makes that arm ineligible, so the immutable ten-arm V8 precommit cannot satisfy the corpus gate and is never resumed, substituted, or pooled into a later campaign.
- The current precommitted `oracle-calibration-v9` campaign, version 9, uses fresh seeds 7381–7390 with alternating odd control/even rumor arms. Only the Oracle is live, routed to `minimax/MiniMax-M3`; background behavior remains scripted. The route pins MiniMax's standard ≤512k pricing at $0.30/M input, $1.20/M output, and $0.06/M cached input with `provider_automatic` caching and a $25 safety cap per run. Commitment SHA-256 is `8a1845ebe9e916b8618a1c17170dc8a2b439c929ea1e1118670e21683c341a8e`. Shared state-aware preflight, occurrence-aware citations, governed-answer repair, and the scheduled-latency floor remain fail closed. Engine semantics 7 and database schema 11 are unchanged, and no V9 live evidence is claimed before all ten predeclared arms and their exact companion replays pass the manifest gate.

**R7. Run control + cost governor**
- Start/pause/resume/speed controls; automatic checkpoints every N ticks; phase-aware resume keeps the last fully completed tick plus the active tick/next-phase cursor.
- Real-time token/cost accounting per model, per agent, per subsystem; optional budget cap with staged degradation (reduce conversation count → stretch decision cadences → institutional-agents-only mode → clean pause with alert).
- HTTP 429 throttling and explicit provider-overload responses (including MiniMax HTTP 529) create a visible provider-wide cooldown and retry until recovery or operator stop; other continuing provider failures pause on the active phase without advancing the completed tick.
- Acceptance: a capped $200 profile never exceeds it; uncapped production records actual spend; degradation, rate-limit, and resume state are visible.

**R8. Live dashboard**
- Panels: macro metrics time series (daily/30-day final-goods output, labor income, CPI, 30-day/YoY inflation when available, unemployment, policy rate, money supply, Gini, sentiment), stock ticker + index chart, live news feed, conversation stream, agent inspector, bank balance sheets, Oracle chat, event/shock log, cost meter, and acceptance progress.
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
- Aging + retirement: age increments each simulated year; agents exit the labor force at ~65 and live off savings/pension draw-down. Retirees can move funds only from their own declared same-currency savings account to checking through `withdraw_savings{amount}`. Lifecycle setting `retirement_liquidity_target_cents` is exposed to decisions as `retirement_drawdown_target_cents` beside `savings_balance`; retirees draw that checking shortfall before consumption, never seek jobs, read news more frequently, and receive greater conversation-pair weight.
- Births are **household events**, not new agents: dependent count increases and spending patterns shift. Population is replenished by deterministic adult **arrivals** ("moved to town") spawned during `NIGHT_CLOSE`, keeping the population ~100 (stable-population default; per approved decision 2026-07-09). Starting wealth is visibly funded from population inflow and split 70/30 between checking and savings, matching genesis.
- Acceptance: (a) over a 2-sim-year test run, at least one death settles its estate with the ledger reconciling to zero discrepancy; (b) a sick agent's wage loss and medical spending are visible in its ledger; (c) an arrival integrates — gets housing costs, seeks a job — within 10 ticks of spawning; (d) identical seed ⇒ identical lifecycle event schedule.

### P1 — Should have (fast follows)

**R12. Government fiscal layer + elections.** Flat income tax funding unemployment benefits; periodic elections where agents vote based on beliefs/economic experience; election outcomes shift fiscal policy within bounds. *(The "political views" outcome Ali wants — first-class but not needed to prove the core loop.)*
**R13. VC / private funding track.** Pitch → partner evaluation → term sheet → equity on cap table → follow-on or write-off. Founding via bank loan works in P0; VC adds the risk-capital channel.
**R14. Experiment harness.** Define experiment = {config, seed set, shock schedule, metrics of interest}; run N seeds; produce a comparison report with outcome distributions.
**R15. Oracle calibration dashboard.** Reliability curves and Brier decomposition across many predictions and runs. The release workflow uses the predeclared `runs/oracle` corpus and a read-only explicit-manifest evaluator that verifies source/profile hashes and writes deterministic JSON and Markdown receipts without scanning arbitrary databases.
**R16. Replay mode.** Re-watch any past run tick-by-tick from stored events without re-running LLMs.
**R17. Health economy.** Hospitals/doctors as firms, health insurance products, epidemics as a trend-type shock — builds on R11's health states.

### P2 — Future (design so we don't preclude them)

**R18. Participant mode.** Ali (or an external LLM) plays an in-world agent through the same action API agents use. *(Implemented extension; participant-influenced runs remain disqualified from observer-only acceptance.)*
**R19. Scale to 1,000+ agents** via a two-tier population: fully-simulated core + statistically-simulated periphery. The optional regional living-world policy owns promotion/demotion. Non-regional semantics-7 maintained profiles instead persist `population.baseline_citizens_core: true` so baseline households and arrivals remain fully scheduled; markerless stored semantics-7 runs preserve their historical peripheral assignment for exact replay. *(Implemented extension with deterministic promotion/demotion and recorded performance evidence.)*
**R20. Multi-region / trade / FX.** Regional decision context exposes bounded FX quotes, own wallet balances, at most five engine-qualified cross-border trade opportunities, and career-gated migration destinations. A trade opportunity requires an effective contract, distinct regions, exporter inventory, and importer funds, and invoices in the importer's currency. Healthy unemployed non-retirees may migrate only when the numeraire-adjusted wage gain clears the configured threshold; outstanding credit exposure or invalid authorization fails closed. *(Implemented extension; five-tick scripted and MiniMax semantics-7 gates exercised shipment delivery and migration completion with exact replay.)*
**R21. Real-data calibration mode** — initialize distributions from real US statistical data (income, wealth, firm size). *(Implemented as the explicit `real_us` profile: disclosure-protected 2022 SCF family records supply income, liquid-financial-asset, and total-net-worth draws, while 2022 SUSB national employer-firm classes supply initial headcounts. `LIQ` funds the modeled bank accounts; `NETWORTH` is persisted as an engine-owned, off-ledger calibration baseline visible through agent provenance, so property/business assets and debt are not silently minted as deposits. Fictional names, traits, behavior, and relationships remain synthetic; default profiles remain replay-identical.)*
**R22. Public/multi-user version** — multiple observers, shared runs, hosted deployment. *(Implemented as an optional hosted control plane. PostgreSQL stores users, tenant membership, sessions, run catalog records, writer leases, audit records, and immutable snapshot pointers under forced row-level security. Each world remains one schema-v11 SQLite database, preserving the local deterministic engine and exact replay contract. Invite-only registration, tenant roles, CSRF protection, request throttling, redacted audit, a lease-based single-writer supervisor, local/S3 snapshot storage, an authenticated hosted dashboard, Docker Compose/Caddy/Prometheus deployment assets, migrations, backup/restore commands, and real PostgreSQL/MinIO integration tests are present. The real-container image/Compose/load gate passed locally; all six exact-head PR #19 jobs passed in run `29409250171`; and PR #19 merged as `1806294d4fecbe13ddbdf615c459755c74293599`. Post-merge run `29411023992` executed no repository steps because GitHub blocked the account for billing/spending-limit reasons. A public production deployment remains a separate release action and is not claimed.)*

After P0/P1 and R18–R22, no additional functional feature gap remains in this
PRD. The archived v1 seed-7301 Oracle source completed with valid live-provider
provenance, but its replay diverged because staged genesis did not preserve the
persona RNG stream; checkpoint inspection also left SQLite WAL/SHM sidecars.
It is diagnostic evidence only, not acceptance evidence. The draft release-gate
branch now persists and restores both semantics-7 RNG streams, finalizes every
SQLite checkpoint without WAL/SHM sidecars, enforces the replay target tick, and
validates column-specific RNG state before live dispatch. The preceding
replay-integrity revision passed 590 tests with 8 skipped. The final v3
receipt-hardening tree passes 599 tests with 8 skipped in 1,618.07 seconds.

The immutable v2 seed-7311 source and generated offline replay both reached
tick 335 and crossed the first arrival without the v1 divergence. Canonical
verification returned `exact: true` with `differences: []`. Its receipt then
failed because checkpoint integrity counted all stored agent rows rather
than validating living and deceased populations separately after a preserved
death row and replacement arrival. That v2 evidence remains diagnostic and is
never reused. The corrected contract validates the bounded living/deceased
census; chronological death, schedule, and arrival linkage; `NIGHT_CLOSE`
phase and subject provenance; one-time consumption of every due schedule; and
the fixed 5–20-tick replacement delay.

V3 seed 7321 completed its source and exact companion replay, but the original
receipt admitted only four of six forecasts because it treated authenticated
rejected planner attempts as invalid accepted plans. The original receipt
records the pre-inspection source hash; the local source artifact was later
write-opened during diagnosis and is not admissible. V3 is excluded diagnostic
evidence.

V4 seeds 7331 and 7332 completed with exact companion replays and remain
diagnostic evidence only. Seed 7333 exposed a different contract defect: the
planner catalog advertised a government ledger target, but execution mapped it
to an account-owner representation that did not contain the treasury account.
The resulting state-dependent execution failure was mislabeled as a preflight
plan rejection, so the receipt correctly excluded the forecast and therefore
the run. No v4 source, response, claim, initialized marker, checkpoint, replay,
profile, commitment, manifest entry, or seed was reused by v5. V5 seeds
7341–7347 produced passed, eligible source receipts with exact companion
replays. Seed 7348 finalized its source, but duplicate same-tick loan-default
events collapsed to ambiguous public citation identities during replay. Four
newsroom articles therefore failed closed to deterministic daily briefs at
ticks 301 and 331, cascading through nine information tables; seeds 7349–7350
were never run. V5 remains diagnostic only. The seven receipt-bound replay
databases and fourteen Oracle source/replay receipts belong only to seeds
7341–7347; seed 7348 has no eligible replay database or Oracle source/replay
receipt. Its final source databases, claims, reports, and all 320 source
checkpoint manifests and hashes are retained. Final corrected offline replay
`replay-oracle-calibration-v5-s7348-5220b912ae` reached tick 335 with
`exact: true`, identical logical hash `fee77b65…b378`, all 82 deterministic
tables exact, and `differences: []`; this post-source fix is diagnostic proof
only and creates no eligible v5 receipt. Completed storage cleanup removed 320
v5 source-checkpoint database bodies, 160 fixed-code replay checkpoint bodies,
four derived fixed-replay final databases, and the superseded partial seed-7343
replay: 485 database files and `111.945217 GiB` in total. The archive retains all
authoritative final sources; the seven eligible replay databases and fourteen
source/replay receipts for seeds 7341–7347; all source-checkpoint
manifests/hashes, claims, and reports; the 160 fixed-code replay checkpoint
manifests; and the ignored compact final exact receipt. Seed 7348 remains
excluded and has no eligible source/replay receipt or retained replay database.
No v5 source, response, claim, initialized marker, checkpoint, replay, receipt,
profile, commitment, manifest entry, run identity, or seed was reused by v6.
V6's first arm, seed 7351, stopped at tick 65 after a successful Kimi response
used `confidence: "medium"` instead of the strict `low|med|high` contract. The
rule rejection persisted, the scheduled prediction became `insufficient_data`,
and the checkpoint was missed. The arm spent $0.18351 and recorded no provider,
budget, or tool-execution failure. V6 is preserved and excluded; seeds
7352–7360 were never run and may not be substituted into that campaign.

V7 is archived as an incomplete diagnostic campaign. Seeds 7361–7364 retain
passed, eligible source receipts and exact 335-tick companion replays with zero
differences. Seed 7365 remains paused at tick 335 in `FINALIZE`; its authoritative
518,561,792-byte standalone database has SHA-256
`b48b0c5a02270f6b09eafb5c32c8480a44f42057289048faedde9474d8ca8ce5`, no
WAL/SHM sidecars, 32,114 calls, 12 Oracle calls, six resolved
forecasts/checkpoints, balanced USD, no critical events, and `$0.2754108` spend.
Its 13,658 ms persisted E2E measurement fell below the 13,660 ms governed-call
sum. The claim-bound source cannot resume or mint an eligible post-fix receipt;
seed 7365 has no replay or receipt, seeds 7366–7370 were never run, and no V7
aggregate manifest or receipt exists. No V7 artifact or seed enters V8.

The V7 archive cleanup removed exactly the 200 source checkpoint database
bodies matching anchored regex
`^oracle-calibration-v7-s736[1-5]_t\d+\.db$`, reclaiming 49,647,239,168 bytes
(`46.237595 GiB`). All 360 source/replay checkpoint manifests and hashes, five
final source databases, four final replay databases, eight source/replay
receipts for seeds 7361–7364, the five existing claim/initialized-marker pairs
for seeds 7361–7365, profiles, commitments, template, base, reports, and the
authoritative seed-7365 database remain retained.

V8 is archived as an excluded diagnostic campaign. Seeds 7371–7374 each retain
a passed, eligible source receipt and exact tick-335 companion replay with zero
differences. Seed 7375 stopped at tick 245 when Kimi returned a billing-cycle
usage-limit failure, and its persisted `provider_failure` makes the arm and
therefore the precommitted ten-arm corpus ineligible. It is never resumed,
substituted, or pooled into V9. Pending conservative cleanup is limited to the
189 source checkpoint database bodies matching anchored regex
`^oracle-calibration-v8-s737[1-5]_t\d+\.db$`: 40 each for seeds 7371–7374 and 29
for seed 7375, totaling 43,999,223,808 bytes. Retain five source databases, four
replay databases, 189 source checkpoint manifests, 160 replay checkpoint
manifests, five claims, five initialized markers, eight source/replay receipts,
reports, and campaign configurations. All 160 replay checkpoint bodies are
already absent and no V8 SQLite sidecars remain.

The current `oracle-calibration-v9` campaign-version-9 precommit starts a fresh
ten-profile corpus at seeds 7381–7390, with odd control/even rumor arms and only
the Oracle routed live to `minimax/MiniMax-M3`. It pins MiniMax's standard
≤512k prices at $0.30/M input, $1.20/M output, and $0.06/M cached input,
uses `provider_automatic` caching, and retains a $25 per-run cap. Commitment
SHA-256 is
`8a1845ebe9e916b8618a1c17170dc8a2b439c929ea1e1118670e21683c341a8e`.
Occurrence-aware citations, shared state-aware preflight, governed-answer
repair, and the fixed scheduled-latency producer remain unchanged. Engine
semantics 7 and database schema 11 are unchanged. No V9 live evidence is
claimed yet. The fresh precommit tree passed 659 Python tests with 8
environment-gated skips, 23 dashboard tests, a fresh 603-module build, pinned
dataset verification, dependency checks, and `git diff --check`.

The outstanding work is release evidence and operations: pass the fresh V9
ten-profile Oracle campaign, run the live 30-day
rumor pilot, pass the 365-day/$200 acceptance run, and repeat the final
public-release provenance audit. Release-gate PR #20 stays draft; GitHub account
billing is an external operational blocker and does not waive required CI.
Merging, tagging, publication, or public deployment requires separate
authorization.

---

## 9. Success metrics

### Leading (first weeks of use)
| Metric | Target | Stretch |
|---|---|---|
| Ledger reconciliation failures per run | 0 | 0 |
| Simulated days achieved within $200 (default config) | ≥ 365 | ≥ 1,000 |
| Oracle scheduled end-to-end response time (p90; all six governed plan + answer samples) | < 60s | < 20s |
| Distinct emergent phenomena reproduced (documented, not scripted) | 3 | 5 |
| Shock → traceable downstream effect (pilot experiments passing) | 5/5 shock types | — |

### Lagging (after ~10 full runs)
| Metric | Target |
|---|---|
| Oracle Brier score vs. naive p=0.5 baseline, over all resolved predictions | Beats baseline |
| Replays from stored LLM responses reproduce identical event logs | 100% |
| Cross-seed experiment (N=5) produces interpretable outcome distribution | ≥ 1 written-up experiment |
| Ali still using it weekly a month after v1 (qualitative north star) | Yes |

**Measurement**: run metrics are computed from persisted databases; cross-run
Oracle calibration is computed from an explicit manifest of hashed, finalized
run databases and profiles. No manual counting or directory pooling is allowed.

---

## 10. Resolved implementation decisions

1. Conversation volume is **15 pairs/tick**, governor-adjustable.
2. Citizens act on **personal cadences** plus event-triggered wakeups.
3. Every simulation run remains one **SQLite** database. The optional R22 service uses PostgreSQL only for identity, tenancy, run catalog, leases, audit, and snapshot metadata; it never becomes the deterministic world store.
4. Reporters are **observe-only**; interviews are deferred.
5. The central banker is **rule-bounded**, with LLM discretion inside configured Taylor-rule guardrails.
6. The acceptance showcase is the **rumor-driven bank-run experiment**.
7. Citizens receive **public bank status, not private reserve ratios**; full visibility remains an explicit legacy/experimental option.
8. P2 work follows a **research-quality-first** roadmap. Participant mode is an implemented extension whose runs remain outside observer-only acceptance; hosted multi-user mode is an optional implemented deployment surface and does not alter local mode or engine semantics.

---

## 11. Phasing

| Phase | Scope | Exit criterion |
|---|---|---|
| **Phase 1 — Kernel** (weeks 1–3) | Engine + ledger, 20 agents, 1 bank, labor + goods markets, CLI only, cost governor | 30 simulated days, money conserved, readable event log |
| **Phase 2 — Markets & media** (weeks 4–6) | Stock exchange, 2nd bank, news outlets, conversations, 100 agents, lifecycle (health/death/arrivals), checkpointing | Rumor-propagation pilot passes (R5) + lifecycle mechanics verified (R11) |
| **Phase 3 — Observatory** (weeks 7–9) | Dashboard, Oracle + prediction scoring, shock library, end-of-run reports | Full R6–R10 acceptance; first complete metered production run |
| **Phase 4 — P1 items** (weeks 10+) | Government + elections (R12), VC track (R13), experiment harness (R14), Oracle calibration (R15), replay (R16), health economy (R17) | First multi-seed experiment written up; calibration and health-economy gates pass |

Timeline assumes part-time solo build with AI-assisted coding; phases are scope-gated, not date-gated.

---

## 12. Companion document

Technical architecture, data model, action schema, prompt design, and cost math live in **TECH-SPEC.md**.
