# Agent Economy — Technical Specification

**Version:** 1.0 · **Date:** 2026-07-09 · **Companion to:** PRD.md

This document is written to be handed to an AI coding agent (or a developer) and implemented directly. Plain-language rationale is included because architectural "why" prevents bad shortcuts later.

---

## 1. Architecture overview

```
┌─────────────────────────────────────────────────────────────┐
│                        DASHBOARD (browser)                   │
│   metrics · ticker · news feed · conversations · inspector   │
│   Oracle chat · shock console · cost meter · run controls    │
└──────────────▲──────────────────────────────▲───────────────┘
               │ WebSocket (live events)      │ REST (queries, controls)
┌──────────────┴──────────────────────────────┴───────────────┐
│                      API SERVER (FastAPI)                    │
├──────────────────────────────────────────────────────────────┤
│                     SIMULATION KERNEL                        │
│  ┌────────────┐  ┌─────────────┐  ┌───────────────────────┐ │
│  │ World clock │→│ Agent       │→│ Action validator +     │ │
│  │ (tick/phase)│  │ scheduler   │  │ executor              │ │
│  └────────────┘  └─────────────┘  └───────────┬───────────┘ │
│  ┌─────────────────────────────────────────────▼───────────┐ │
│  │ ECONOMIC ENGINE (deterministic, no LLM)                 │ │
│  │ double-entry ledger · order book · loan contracts ·     │ │
│  │ payroll · bankruptcy waterfall · metrics                │ │
│  └─────────────────────────────────────────────────────────┘ │
├──────────────────────────────────────────────────────────────┤
│  LLM GATEWAY: model routing · budget governor · caching ·   │
│  concurrency limits · structured-output parsing · retries   │
├──────────────────────────────────────────────────────────────┤
│  STORE (SQLite): world state · events · memories · ledger · │
│  conversations · news · predictions · checkpoints           │
└──────────────────────────────────────────────────────────────┘
```

**The one rule that keeps the system sane:** LLMs *propose*, the engine *disposes*. No LLM output ever writes directly to state. Every agent decision is a JSON action validated against hard rules (does the money exist? does the share exist? is the market open?) before the engine applies it. Invalid actions are rejected back to the event log — which is itself interesting data (agents attempting to overspend is realistic behavior).

## 2. Stack

| Layer | Choice | Why |
|---|---|---|
| Language | **Python 3.12** | Best ecosystem for LLM tooling; matches Ali's AI-tool experience; an AI coding agent produces reliable Python. |
| Simulation kernel | Plain Python, single process, `asyncio` | 100 agents ≪ needing distribution. Async matters only for parallel LLM calls, not compute. |
| API | **FastAPI** + WebSocket | Standard, minimal boilerplate, async-native. |
| Store | **SQLite (WAL mode)**, one file per run | Zero-ops, transactional, a whole run is one portable file you can archive or share. Revisit Postgres only at 1,000+ agents (P2). |
| LLM | **Provider-agnostic gateway.** Adapters: OpenAI-compatible (covers Kimi/Moonshot and MiniMax — both expose OpenAI-style APIs), Anthropic, and a restricted CLI adapter (Oracle/dev only). Defaults: citizens/conversations/memory → `minimax-m3`; strong seats + Oracle → `kimi-k2.7`. Routing is `role → {provider, model}` in `run.yaml`, not code. | Per PRD decision: Ali holds Kimi + MiniMax API keys; swapping providers per role is config, and enables model-vs-model economy experiments. |
| Dashboard | **React + Vite + Tailwind**, Recharts for charts | Standard; easy for AI-assisted iteration. Served statically by FastAPI — one process to run. |
| Config | Single `run.yaml` per run (population, models, budget, cadences, shock schedule, seed) | Reproducibility = config + seed + code version. |

No Docker/Kubernetes/queues in v1. One `python run.py --config run.yaml` process. Keep it boring.

## 3. Time: ticks and phases

1 tick = 1 simulated day. Each tick executes phases **in fixed order** (determinism requires ordered execution):

| # | Phase | What happens | LLM? |
|---|---|---|---|
| 1 | `NIGHT_CLOSE` (previous day) | Interest accrual, loan payments due, payroll on paydays, **lifecycle draws** (illness onset/recovery, deaths + estate settlement, birthdays/aging, retirement transitions, arrival spawning), metrics snapshot, ledger reconciliation check | No |
| 2 | `MORNING` | Agents scheduled to act today: perceive → decide. News from yesterday delivered per media diet | Yes (decisions) |
| 3 | `EXECUTION` | Validator + engine apply all queued actions in deterministic order (sorted by agent id + action seq) | No |
| 4 | `MARKET` | Exchange session: order book matches queued orders; goods purchases settle; labor offers/acceptances bind | No |
| 5 | `NEWSROOM` | Reporters (strong model) scan the day's event log, write stories; editors pick and frame per outlet slant | Yes |
| 6 | `EVENING` | Conversation pairing: K pairs sampled by social-graph weight + event salience; 2–4 exchange turns each | Yes |
| 7 | `MEMORY` | Each active agent's day is compressed to a summary; importance scoring; belief updates extracted | Yes (cheap) |

**Agent cadences (cost + realism):** every agent acts *only when scheduled* — shopping ~daily, portfolio review weekly, career decisions monthly, plus **event-triggered wakeups** (your bank is in the news, you got fired, someone told you something with high salience). Institutional agents act every tick. This is the single biggest cost lever (see §12).

## 4. Data model (SQLite)

Core tables (columns abridged to the meaningful ones):

```
agents         id, name, kind(citizen|staff|firm_ai), occupation, employer_id,
               age, health(healthy|sick|critical), dependents INT,
               personality_json, political_lean, media_diet_json, risk_tolerance,
               cadence_json, model_tier, alive, died_tick, arrived_tick
firms          id, name, sector, founder_agent_id, status(private|listed|bankrupt),
               product_json (what it sells, unit cost structure)
accounts       id, owner_type(agent|firm|bank|gov|central_bank), owner_id,
               bank_id, kind(checking|savings|reserve), balance_cents
ledger_entries id, tick, txn_id, account_id, delta_cents, counter_account_id, memo
               -- Ledger.post rejects unbalanced batches before insertion;
               -- reconciliation recomputes every account after each tick
loans          id, bank_id, borrower_id, principal, rate_bps, term_ticks,
               schedule_json, collateral_json, status(active|paid|default)
shares         firm_id, holder_id, qty            -- cap table
orders         id, tick, agent_id, firm_id, side, qty, limit_price_cents, status
trades         id, tick, buy_order_id, sell_order_id, qty, price_cents
jobs           id, firm_id, title, wage_cents, status; applications(job_id, agent_id, state)
memories       id, agent_id, tick, kind(observation|summary|belief), text,
               importance REAL, last_accessed_tick
beliefs        agent_id, key(e.g. 'trust:bank:2', 'inflation_expectation'),
               value REAL, updated_tick          -- numeric so metrics can aggregate
news_articles  id, tick, outlet_id, headline, body, slant_tags, source_event_ids
conversations  id, tick, participant_ids; messages(conv_id, agent_id, text, seq)
events         id, tick, phase, kind, payload_json     -- append-only spine of the sim
metrics        tick, name, value                       -- gdp_proxy, cpi, unemployment,
                                                       -- index, m2, gini, sentiment
predictions    id, asked_tick, question, p REAL, reasoning, resolution_rule_json,
               deadline_tick, resolved_tick, outcome BOOL, brier REAL, evidence_json
llm_calls      id, tick, agent_id, model, purpose, request_json, response_json,
               in_tokens, out_tokens, cost_usd
               -- full request/response stored: powers the inspector (PRD R2),
               -- exact replay (§13), and prompt debugging
checkpoints    tick, path, created_at
run_meta       tick(last complete), active_tick, next_phase, phase_state_json,
               prng_state, lifecycle_prng_state, legacy_partial
shocks         id, kind, trigger_type(shock|trend|conditional), trigger_json,
               duration_ticks, params_json, fired BOOL
               -- shock: fires at tick N · trend: gradual effect over duration ·
               -- conditional: fires when a metric predicate becomes true
```

Design notes:
- **`events` is the source of truth for "what happened";** the dashboard, newsroom, Oracle, replay, and end-of-run report all read from it. Anything not in `events` didn't happen.
- **Money is integer cents.** Floats cause reconciliation drift — never use them for balances.
- **`beliefs` is numeric on purpose**: "trust in Bank 2 = 0.31" lets us chart belief collapse during a run — the core observable of the rumor experiments.

## 5. The action schema (LLM → engine contract)

Agents respond with JSON conforming to a strict schema (use the API's structured-output/tool-call mode; reject-and-retry once on invalid output, then no-op):

```json
{
  "reasoning": "brief in-character rationale (stored, shown in inspector)",
  "actions": [
    {"type": "buy_goods",    "firm_id": 12, "qty": 3},
    {"type": "place_order",  "firm_id": 7, "side": "buy", "qty": 10, "limit_price": 1450},
    {"type": "apply_loan",   "bank_id": 2, "amount": 500000, "purpose": "expand bakery"},
    {"type": "post_job",     "title": "clerk", "wage": 320000},
    {"type": "apply_job",    "job_id": 44},
    {"type": "set_price",    "product": "bread", "price": 450},
    {"type": "hire",         "application_id": 91},
    {"type": "fire",         "employment_id": 17},
    {"type": "found_company","name": "...", "sector": "...", "lawyer_agent_id": 33},
    {"type": "transfer",     "to_account": 88, "amount": 20000, "memo": "rent"},
    {"type": "say_public",   "text": "..."},
    {"type": "do_nothing"}
  ],
  "belief_updates": [
    {"key": "trust:bank:2", "value": 0.31}
  ]
}
```

Role-specific action sets extend this: credit officers get `approve_loan/deny_loan` (with terms), the central banker gets `set_policy_rate` (clamped to ±50bps per meeting inside Taylor-rule guardrails), editors get `publish(article, framing)`, reporters get `draft_story(event_ids, angle)`.

**Validator rules (hard, non-negotiable):** sufficient funds/shares; market open; counterparty exists and alive; wage ≥ 0; one loan application per bank per week per borrower; policy rate within guardrails; every action's ledger effect balances.

## 6. Agent decision prompt (citizens)

Assembled per wakeup, ~1,200–1,800 input tokens:

```
[SYSTEM — cached prefix, identical for all citizens]
You are living inside a simulated economy. Respond only with the JSON schema…
(action schema + general world rules, ~600 tokens, benefits from prompt caching)

[PERSONA] name, age, job, wage, personality, risk tolerance, political lean…
[STATE] balances, debts, portfolio, employment, upcoming obligations
[BELIEFS] current numeric beliefs rendered as sentences
[MEMORIES] top-k retrieved (k=6) by recency × importance × relevance
[TODAY] news headlines from your media diet · things said to you yesterday ·
        current prices of goods you usually buy · your scheduled concerns today
[TASK] Decide what you do today. Stay in character. You are not obligated to act.
```

Retrieval scoring (Generative-Agents style, no embeddings in v1 — keyword/entity match is enough at this scale): `score = 0.5·recency_decay + 0.3·importance + 0.2·relevance`.

## 7. Memory pipeline

1. **Observation capture**: engine events touching the agent + conversation lines heard → `memories(kind=observation)` verbatim.
2. **Nightly compression** (Haiku, ~200 out-tokens): day's observations → 1 summary + importance score (1–10) + extracted belief updates.
3. **Weekly roll-up**: 7 daily summaries → 1 weekly summary; dailies demoted (still queryable, rarely retrieved).
4. **Belief extraction**: numeric belief updates from step 2 are written to `beliefs` — this is what makes narrative → behavior measurable.

## 8. LLM gateway

Single chokepoint through which every call flows. Responsibilities:

- **Routing**: `role → {provider, model}` from `run.yaml`. Default strong seats (≈8, matching the cost model in §12): central banker (1), credit officers (2–3), editors + lead reporters (3), VC partner (1), plus the Oracle → `kimi-k2.7`. All other institutional staff and all citizens → `minimax-m3`.
- **Adapters**: one interface (`complete(request) → response`), three implementations:
  - `openai_compat` — Kimi (Moonshot) and MiniMax endpoints; also covers OpenRouter/vLLM/Ollama for free, since they all speak the OpenAI wire format.
  - `anthropic` — optional tier if Ali adds an Anthropic API key.
  - `cli` — wraps `claude -p --output-format json` (headless). **Hard-restricted in code to `purpose in {oracle, dev}`** — the gateway raises if a swarm role is configured onto it. Rationale: consumer-subscription rate limits stall a swarm mid-tick, and provider terms don't permit subscriptions as bulk-inference backends.
- **Budget governor**: cumulative `llm_calls.cost_usd` per run is always metered. When `cap_usd` is configured, thresholds at 60/80/95% trigger staged degradation:
  - 60%: evening conversations 15 → 8 pairs/tick
  - 80%: citizen cadences stretched ×2 (weekly → biweekly, etc.); conversations → 4 pairs
  - 95%: institutional agents only; citizens act on event-triggered wakeups only
  - 100%: clean pause + checkpoint + dashboard alert. **A configured cap is never exceeded.**
  - `cap_usd: null`: no application spend ceiling or degradation; this is the production/acceptance profile, and actual spend remains visible.
- **Prompt caching**: shared system prefix (schema + world rules) marked cacheable — biggest single cost saver since it's identical across ~100 agents.
- **Concurrency**: configurable `asyncio.Semaphore(llm.concurrency)` on API calls (production currently uses 3); agents within a phase run concurrently and execution remains deterministic afterward.
- **Failure policy**: HTTP failures preserve status and `Retry-After`. A 429 sets one provider-wide visible cooldown and retries until recovery or operator stop, using `Retry-After` or 15/30/60/120/300-second fallback intervals. Other failures receive the configured bounded retry count and then pause the active phase. Malformed JSON receives one repair completion; a second invalid result becomes a logged `do_nothing`.

## 9. Market mechanics (all deterministic)

- **Equity order book**: price-time priority; partial fills; orders expire end of session. Index = float-weighted average of listed firms. Circuit breaker (optional config): halt a symbol −20% intraday — interesting to toggle in crash experiments.
- **Goods**: firms post prices; household `buy_goods` actions settle instantly if stocked and affordable; firm inventory decrements; simple production function converts labor-ticks + input costs → inventory each tick. A global **commodity/energy price index** feeds every firm's input-cost structure — this is the variable the oil shock moves (PRD R9).
- **Labor**: postings visible to job-seekers at wakeup; `apply_job` → firm-side `hire` decision (LLM for founder-run firms); employment contract writes payroll obligations into the engine.
- **Shock hooks** (PRD R9 mapping): rate override → clamps `set_policy_rate`; oil shock → scales the commodity index; rumor → injects a synthetic "heard" observation into targeted agents' memories; slanted-news directive → editor receives a framing instruction for N ticks; firm scandal → injects a true negative event about the firm into `events`, which the newsroom picks up naturally. Each hook can be wrapped in any of the three trigger types (instant shock, gradual trend, metric-conditional) — evaluated by the event scheduler each tick.
- **Credit**: `apply_loan` packages borrower financials automatically (engine attaches true ledger data — banks see real statements, not the borrower's claims); credit officer (Sonnet) returns approve/deny + rate + term inside bank risk-policy bounds; engine enforces schedule, arrears, default at 3 missed payments, collateral seizure, bank loss provisioning. **Bank failure mechanics**: reserves below threshold → interbank borrowing attempt → central bank lender-of-last-resort decision (Sonnet, in character) → failure = depositor haircut event (this is what makes bank runs matter).

### 9.1 Lifecycle mechanics (PRD R11 — all deterministic, seeded PRNG)

**Design rule: biology is engine-side, reactions are LLM-side.** The LLM never decides who gets sick, dies, or is born — those draws come from the run's seeded PRNG so lifecycle schedules replay identically. Agents *react* to lifecycle events through the normal decision loop (a health event is delivered as a morning observation).

- **Health draws** (nightly, per agent): annual age-banded probabilities converted to per-tick hazards. Defaults in `run.yaml`: illness onset ~4%/yr (20–40) rising to ~15%/yr (65+); mean sick duration 5 ticks; sick → critical escalation 5%; critical → death 10%/tick, critical → recovery 25%/tick.
- **Sickness effects** (engine): sick agents are removed from the labor phase (no wage that tick), charged a medical out-of-pocket cost (config, default ~1 day's median wage per sick tick), and receive a "you are ill" observation. Firms see the absence (production function loses the labor-tick).
- **Death**: age-banded baseline mortality (negligible <50, rising after) + critical-illness channel. On death, the engine runs **estate settlement in one atomic transaction batch**: outstanding debts settle via the creditor waterfall → remaining balances and share holdings transfer to the heir (deterministic rule: strongest social-graph tie among living agents; escheat to government sink account if none) → employment contracts terminate → sole-proprietor firms with no successor enter the bankruptcy path. A death event enters `events` with full prominence — the newsroom and the deceased's social ties react via the normal LLM loop.
- **Aging/retirement**: age +1 per 365 ticks; at retirement age (config, default 65) the agent leaves the labor market and switches to a savings draw-down consumption pattern. Persona cadences shift (no job-seeking, more social).
- **Births as household events**: a dependent-count increment with a spending-pattern shift (config probability for age-appropriate households). No child agents.
- **Arrivals (stable-population default)**: each death schedules a replacement adult arrival 5–20 ticks later — generated via the vendored persona library (one LLM call), spawned with starting savings drawn from the wealth distribution, an opening "moved to town" observation, and job-seeking cadence. `population_mode: stable | drift` in `run.yaml`.
- **Conservation invariant**: estate settlement moves money, never creates or destroys it; arrivals' starting savings are minted from a visible `population_inflow` equity account so reconciliation stays exact and auditable.

## 10. Newsroom + conversations

- Reporters receive the tick's `events` digest (pre-filtered by newsworthiness heuristic: money size, rarity, entity prominence) and draft 2–4 stories; the editor selects/frames per the outlet's configured slant (e.g. `outlet A: pro-market, sensationalist; outlet B: cautious, pro-labor`). Stories cite `source_event_ids` — the report can later audit how coverage diverged from ground truth (fun metric: *distortion index*).
- Conversation pairing: sample K pairs weighted by social-graph edge weight + shared-event salience; 2–4 turns, Haiku both sides, capped ~150 tokens/turn. Lines heard become observations (→ memory → beliefs). This is the rumor-propagation medium.

## 11. The Oracle

- **Read-only analyst** (strong model — default `kimi-k2.7`; optionally routed through the Claude CLI adapter to use Ali's subscription, since Oracle volume is a handful of calls per session) exposed as dashboard chat. A provider-neutral planner can request only bounded `query_metrics(names, range)`, `read_news(range)`, `sample_conversations(filter)`, `inspect_agent(id)`, `get_ledger_summary(entity)`, and `read_order_book(firm, depth)` calls. Arbitrary SQL, writes, unknown tools, oversized plans, and excessive results are rejected.
- The executed read transcript is stored in `predictions.evidence_json`, returned by the API, and shown with the prediction for auditability.
- Answer contract: `{p: 0.xx, drivers: [...], confidence: low|med|high, resolution_rule, deadline_tick}`. The resolution rule must be machine-checkable against world state (e.g. `bank_run := any bank loses >30% deposits within any 5-tick window before deadline`). If the question can't be given a checkable rule, the Oracle returns `insufficient_data` and says why.
- A resolver job checks open predictions each tick; on resolution, Brier score = `(p − outcome)²` written to `predictions`. Dashboard shows running calibration.
- Capped profiles reserve an Oracle carve-out (default: $10 of $200) so questions never starve the world. The uncapped production profile meters Oracle spend without applying a ceiling.

## 12. Cost model (why $200 works)

Pricing (verified July 2026): MiniMax M3 ≈ $0.30/M input + $1.20/M output (cache read $0.06/M); Kimi K2.7 ≈ $0.95/M + $4.00/M (cache read $0.19/M).

Per tick, default config (steady state):
| Item | Calls | Tokens (in/out) | Cost |
|---|---|---|---|
| Citizen decisions (~35 wakeups/tick with cadences, M3) | 35 | 1,500 / 300 | ≈ $0.03 |
| Institutional decisions (K2.7) | 8 | 2,000 / 400 | ≈ $0.03 |
| Newsroom (K2.7) | 4 | 2,500 / 600 | ≈ $0.02 |
| Conversations (15 pairs × 3 turns, M3) | 90 | 700 / 150 | ≈ $0.04 |
| Memory compression (M3) | ~45 | 900 / 200 | ≈ $0.02 |
| Lifecycle (engine-side; ~1 persona-gen call per arrival, a few per sim-year) | ~0 | — | ≈ $0.00 |
| **Total** | | | **≈ $0.14/tick** |

→ **$200 ≈ 1,400+ simulated days (~4 sim years)** at defaults, before governor degradation. The PRD target of ≥365 days has ~4× margin — headroom that can instead buy richer activity (more conversation pairs, more frequent wakeups) via config. Conservatisms retained: the prompt-caching discount is *not* applied (both providers cache the shared system prefix cheaply, so real cost is lower), and strong-model usage is capped at the ≈8 seats defined in §8. Event-heavy days (crash days) spike wakeups; margin absorbs this. An Anthropic-only variant (Haiku citizens / Sonnet seats) runs ≈ $0.50/tick — still within the PRD target, useful for model-comparison experiments.

## 13. Determinism, checkpointing, replay

- All engine randomness from one seeded PRNG. LLM outputs are *not* deterministic — so **replay uses stored outputs**: every LLM response is persisted in `llm_calls`; replay mode re-executes the engine against recorded responses, reproducing the run exactly without API cost (also = free debugging).
- `run_meta.tick` is the last fully completed tick. `active_tick`, `next_phase`, and `phase_state_json` persist in-flight work; successful LLM responses are reused by request key, deterministic phases use SQLite savepoints, and newsroom/conversation/memory writes are idempotent. A rate limit, provider pause, operator stop, or process restart therefore resumes the active phase without advancing or duplicating it.
- Checkpoint = SQLite backup + phase cursor + PRNG state + governor counters, every N completed ticks and on pause. Forking a checkpoint creates a new run id for what-if branches.
- Reconciliation check every tick: `SUM(ledger deltas) == 0` and per-account recomputation matches stored balances; failure → halt + dump (PRD R1).
- On stop, the complete standalone HTML report embeds all charts. A Markdown reviewer companion records the narrative, event timeline, metric snapshot, Oracle/calibration scorecard, cost table, config, and seed.

## 14. Testing

- **Engine unit tests (no LLM)**: ledger invariants, order-book matching against known fixtures, loan schedules, bankruptcy waterfall, estate settlement (death with debts, with/without heir, founder death) (tax math added with the P1 government layer). Property tests: random valid action sequences never break reconciliation; random lifecycle event sequences (sickness/death/arrival storms) never break reconciliation; same seed ⇒ identical lifecycle schedule.
- **Scripted-agent integration tests**: replace LLM with scripted policies (always-buy, panic-withdrawer) to test systemic mechanics cheaply — a scripted bank run must produce a bank failure through real mechanics before any LLM is involved.
- **Golden-run test**: 10-tick run with recorded LLM responses committed to repo; CI replays it and diffs the event log.
- **Cost test**: simulated pricing table + fake responses verify governor thresholds fire at 60/80/95/100%.

## 15. Prior art and borrowed components

Evaluated July 2026 as potential foundations; decision was **own kernel + selective borrowing** (PRD §2).

| Source | License | Verdict | What we take |
|---|---|---|---|
| [LLM-Economist](https://github.com/sethkarten/LLM-Economist) (Karten et al. 2025) | MIT | Too narrow as a base (tax planner vs. workers only) | **Vendor the census-based persona generation** (real occupation/age/income distributions → LLM-expanded personas) into `agents/personas/vendor/`; keep upstream attribution |
| [Doxa](https://github.com/VincenzoManto/Doxa) (v0.1, single maintainer) | GPL-3.0 | Closest in spirit; rejected — no double-entry banking layer, demo scale, GPL is viral for any future distribution | **Design ideas only, zero code copied**: shock/trend/conditional event-trigger taxonomy; trust-graph-weighted conversation pairing sanity check |
| [AgentSociety](https://github.com/tsinghua-fib-lab/agentsociety) (Tsinghua FIB) | Apache-2.0 | v2 pivoted to AI-social-scientist tooling; the economy/city modules are in unmaintained legacy v1 | Validation that SQLite-based full replay is the right pattern (their v2 does the same); their paper's methodology for evaluating agent believability |
| Generative Agents (Stanford) / EconAgent (Tsinghua) | papers | Reference designs | Memory scoring (recency × importance × relevance) — already in §6; decision-cadence framing — already in §3 |

Rule for vendored code: it lives under a `vendor/` subfolder with its upstream LICENSE file, and we never modify it in place — wrap it.

## 16. Repository layout

```
agent-economy/
  run.py                  # entrypoint: python run.py --config runs/base.yaml
  runs/base.yaml          # default world config (population, models, budget, shocks)
  engine/                 # deterministic core: ledger, markets, credit, firms
  agents/                 # personas, scheduler, prompt assembly, memory, actions
    personas/vendor/      # LLM-Economist persona generation (MIT, unmodified)
  llm/                    # gateway: routing, governor, caching, parsing
    adapters/             # openai_compat (Kimi/MiniMax), anthropic, cli (restricted)
  world/                  # tick loop, phases, event bus, shocks, metrics
  oracle/                 # analyst agent, tools, resolver, scoring
  server/                 # FastAPI app, WebSocket hub, static dashboard
  dashboard/              # React app (built → server/static)
  reports/                # end-of-run report generator (md + html)
  tests/
  data/runs/<run_id>.db   # one SQLite file per run (gitignored)
```

## 17. Build order (maps to PRD §11 phases: steps 1–2 = Phase 1, 3–4 = Phase 2, 5–7 = Phase 3, 8 = Phase 4)

1. **Kernel**: ledger + engine + validator + scripted agents + reconciliation tests. *No LLM yet — prove the economy's plumbing first.*
2. Agent runtime + gateway + governor; 20 Haiku citizens, 1 bank; CLI event stream.
3. Exchange + firms lifecycle + 2nd bank; scale to 100 agents; checkpoints.
4. Newsroom + conversations + memory pipeline; run the rumor pilot.
5. Dashboard (read-only first, then controls).
6. Oracle + resolver + scoring.
7. Shock library + end-of-run reports → **v1 complete (PRD P0)**.
8. P1: government/elections, VC, experiment harness, replay UI.
