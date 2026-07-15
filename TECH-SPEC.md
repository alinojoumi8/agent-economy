# Agent Economy — Technical Specification

**Version:** 1.1 · **Date:** 2026-07-15 · **Companion to:** PRD.md

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
| Language | **Python 3.11 and 3.12** | Both supported versions run the complete Linux/Windows CI matrix. |
| Simulation kernel | Plain Python, single process, `asyncio` | 100 agents ≪ needing distribution. Async matters only for parallel LLM calls, not compute. |
| API | **FastAPI** + WebSocket | Standard, minimal boilerplate, async-native. |
| World store | **SQLite (WAL mode)**, one file per run | Zero-ops, transactional, portable, and replay-exact. R19 proves the deterministic 1,000-agent profile on SQLite; R22 deliberately retains this boundary. |
| Hosted control plane | **PostgreSQL 17** with forced row-level security | Optional R22 identity, tenant membership, sessions, run catalog, writer leases, audit, and snapshot metadata. It never stores or mutates deterministic world state. |
| Hosted artifacts | Local filesystem or **S3-compatible object storage** | Immutable, checksum-verified SQLite snapshots; S3/MinIO is the deployment profile and filesystem storage remains useful for development. |
| LLM | **Provider-agnostic gateway.** Adapters: OpenAI-compatible (Kimi/Moonshot and MiniMax), Anthropic, and a restricted CLI adapter (Oracle/dev only). The maintained production profile routes citizens/founders to `MiniMax-M3` and strong seats plus Oracle to Kimi Code's `kimi-for-coding`; conversation and memory purposes inherit the actor's role route. Routing is `role → {provider, model}` in YAML, not code. | Swapping providers per role is configuration, which also enables model-vs-model economy experiments. |
| Dashboard | **React + Vite + Tailwind**, Recharts for charts | Standard; easy for AI-assisted iteration. Served statically by FastAPI — one process to run. |
| Config | Single `run.yaml` per run (population, models, budget, cadences, shock schedule, seed) | Reproducibility = config + seed + code version. |

Local v1 remains one `python run.py --config run.yaml` process with no Docker,
PostgreSQL, or object-store requirement. R22 is a separately enabled FastAPI
deployment with a hardened container/Compose reference stack; it does not
change the local entry point or simulation semantics.

## 3. Time: ticks and phases

1 tick = 1 simulated day. Each tick executes phases **in fixed order** (determinism requires ordered execution):

| # | Phase | What happens | LLM? |
|---|---|---|---|
| 1 | `NIGHT_CLOSE` (previous day) | Interest accrual, loan payments due, payroll on paydays, **lifecycle draws** (illness onset/recovery, deaths + estate settlement, birthdays/aging, retirement transitions, deterministic arrival spawning), shocks, and a pre-decision reconciliation check | No |
| 2 | `MORNING` | Before decisions, each new semantics-7 arrival receives exactly one governed persona enrichment call; then scheduled agents perceive → decide. News from yesterday is delivered per media diet | Yes (persona + decisions) |
| 3 | `EXECUTION` | Validator + engine apply all queued actions in deterministic order (sorted by agent id + action seq) | No |
| 4 | `MARKET` | Exchange session: order book matches queued orders; goods purchases settle; labor offers/acceptances bind | No |
| 5 | `NEWSROOM` | Reporters (strong model) scan the day's event log, write stories; editors pick and frame per outlet slant | Yes |
| 6 | `EVENING` | Conversation pairing: K pairs sampled by social-graph weight + event salience; 2–4 exchange turns each | Yes |
| 7 | `MEMORY` | Each active agent's day is compressed to a summary; importance scoring; belief updates extracted | Yes (cheap) |
| 8 | `FINALIZE` | Idempotent completed-day metrics snapshot, Oracle resolution, and reconciliation after every settled action | No |

`engine_semantics_version: 2` selects the completed-day contract. Version `3` retains it and adds research-valid information/metric semantics: final-goods GDP, separate labor income, 30-day inflation, true 365-day YoY CPI, and explicit belief provenance. Semantics 4 adds legal/political institutions; semantics 5 adds regions, currencies, FX, shipments, and migration; semantics 6 adds bilateral hiring, agent-priced IPOs, and actor-provenanced lender-of-last-resort decisions. Maintained semantics 7 adds net bank loss recognition, retirement liquidity/cadence, deterministic arrivals with governed persona enrichment, and autonomous qualified R20 actions. Database schema remains v11. Stored semantics 1–6 retain their historical behavior, and only an explicit fork may upgrade. The separate persisted `population.baseline_citizens_core: true` marker activates fully scheduled non-regional baseline citizens, health founders, and later arrivals under semantics 7. It is ignored by older semantics and regional R19 worlds; markerless stored semantics-7 runs retain their historical peripheral assignment for exact replay.

**Agent cadences (cost + realism):** every agent acts *only when scheduled* — shopping ~daily, portfolio review weekly, career decisions monthly, plus **event-triggered wakeups** (your bank is in the news, you got fired, someone told you something with high salience). Institutional agents act every tick. In non-regional semantics-7 maintained profiles, `population.baseline_citizens_core` keeps baseline households on this scheduler; R19 regional profiles instead use their explicit core/periphery policy. This is the single biggest cost lever (see §12).

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
events         id, tick, phase, kind, payload_json     -- append-only spine; includes
                                                       -- belief_updated/normalized/rejected
metrics        tick, name, value                       -- gdp_proxy, gdp_proxy_30d,
                                                       -- labor_income, cpi, inflation_30d,
                                                       -- cpi_yoy, unemployment, index, m2,
                                                       -- gini, sentiment
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
- Reserved beliefs are normalized to defined domains (`trust:bank:*` `[0,1]`, sentiment `[-1,1]`, inflation expectation `[-0.05,0.25]`). Every update records old/raw/new values and source provenance in `events`; non-finite updates are rejected and audited.
- `gdp_proxy` is final-goods sales only in v3. `labor_income` is separate, `gdp_proxy_30d` smooths the output view, `inflation_30d` begins at day 30, and `cpi_yoy` is absent until a real 365-day comparison exists.

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

Role-specific action sets extend this: credit officers get `approve_loan/deny_loan` (with terms); the central banker gets `set_policy_rate` (clamped to ±50bps per meeting inside Taylor-rule guardrails) plus `decide_liquidity_support(request_event_id, approve|deny, evidence_event_ids)`; hiring firms and candidates exchange `make/counter/accept/reject_job_offer`; qualified issuers and investors use `open_ipo/place_ipo_bid/close_ipo`; editors get `publish(article, framing)`; reporters get `draft_story(event_ids, angle)`. Under semantics 7, retirees also receive `withdraw_savings{amount}` and qualified founders/citizens receive only the existing shipment, FX, and migration actions whose referenced opportunity IDs are present in their bounded context.

**Validator rules (hard, non-negotiable):** sufficient funds/shares; market open; counterparty exists and alive; wage ≥ 0; one loan application per bank per week per borrower; policy rate within guardrails; every action's ledger effect balances.

## 6. Agent decision prompt (citizens)

Assembled per wakeup, ~1,200–1,800 input tokens:

```
[SYSTEM — cached prefix, identical for all citizens]
You are living inside a simulated economy. Respond only with the JSON schema…
(action schema + general world rules, ~600 tokens, benefits from prompt caching)

[PERSONA] name, age, job, wage, personality, risk tolerance, political lean…
[STATE] balances, debts, portfolio, employment, upcoming obligations; retirees also receive `savings_balance` and public `retirement_drawdown_target_cents`, derived from lifecycle config `retirement_liquidity_target_cents`
[MARKETS] valid bank ids, stocked goods, jobs, listed-firm price/book/fundamentals; semantics-7 regional actors receive bounded wallet/FX facts, up to five executable trade opportunities, and career-gated migration destinations
[ROLE] full founder economics + applicant ids, underwriting packets, or macro mandate
[BELIEFS] current numeric beliefs rendered as sentences
[MEMORIES] top-k retrieved (k=6) by the weighted additive retrieval score below
[TODAY] news headlines from your media diet · things said to you yesterday ·
        current prices of goods you usually buy · your scheduled concerns today
[TASK] Decide what you do today. Stay in character. You are not obligated to act.
```

`information.citizen_bank_visibility` controls the epistemic boundary. New profiles use `public_status`: citizens/founders see bank IDs, names, and public status but no reserve ratios; credit officers see their own bank's ratio; the central banker, Oracle, dashboard, and reports see full ground truth. Missing configuration means `full_balance_sheet` only for historical replay compatibility.

Retrieval scoring (Generative-Agents style, no embeddings in v1 — keyword/entity match is enough at this scale): `score = 0.5·recency_decay + 0.3·importance + 0.2·relevance`.

## 7. Memory pipeline

1. **Observation capture**: engine events touching the agent + conversation lines heard → `memories(kind=observation)` verbatim.
2. **Nightly compression** (the actor's configured route, ~200 out-tokens): day's observations → 1 summary + importance score (1–10) + extracted belief updates.
3. **Weekly roll-up**: 7 daily summaries → 1 weekly summary; dailies demoted (still queryable, rarely retrieved).
4. **Belief extraction**: numeric updates are validated, normalized when reserved, written to `beliefs`, and appended as provenance-bearing events. Acceptance measures trust loss from each exposed agent's actual pre-rumor value to the minimum value in the ten-tick window; runs without history fail closed.

## 8. LLM gateway

Single chokepoint through which every call flows. Responsibilities:

- **Routing**: `role → {provider, model}` from YAML. The maintained production profile sends central banking, credit, newsroom, VC, and Oracle seats to Kimi Code's `kimi-for-coding`; citizens/founders use `MiniMax-M3`. Conversation and memory calls inherit their actor's route. Other profiles may override any mapping explicitly.
- **Adapters**: one interface (`complete(request) → response`), three implementations:
  - `openai_compat` — Kimi (Moonshot) and MiniMax endpoints; the same protocol adapter can target OpenRouter, vLLM, or Ollama when their endpoint and feature support are configured explicitly.
  - `anthropic` — optional tier if Ali adds an Anthropic API key.
  - `cli` — wraps `claude -p --output-format json` (headless). **Hard-restricted in code to `purpose in {oracle_plan, oracle, dev}`** — the gateway raises if a swarm role is configured onto it. Rationale: consumer-subscription rate limits stall a swarm mid-tick, and provider terms don't permit subscriptions as bulk-inference backends.
- **Budget governor**: cumulative `llm_calls.cost_usd` per run is always metered. Capped fresh profiles carve out Oracle and end-report reserves first; world thresholds therefore cannot be changed later by generating or regenerating the operational report. When `cap_usd` is configured, thresholds at 60/80/95% of the world allocation trigger staged degradation:
  - 60%: evening conversations 15 → 8 pairs/tick
  - 80%: citizen cadences stretched ×2 (weekly → biweekly, etc.); conversations → 4 pairs
  - 95%: institutional agents only; citizens act on event-triggered wakeups only
  - 100%: clean pause + checkpoint + dashboard alert. **A configured cap is never exceeded.**
  - `cap_usd: null`: no application spend ceiling or degradation; this is the production/acceptance profile, and actual spend remains visible.
- **Prompt caching**: each provider declares `prompt_cache_mode` as `off`, `provider_automatic`, `openai_key`, or `anthropic_ephemeral`; readiness rejects adapter/mode mismatches. The legacy `prompt_cache_key` option aliases `openai_key`. MiniMax uses its OpenAI-compatible automatic-prefix behavior and therefore receives no synthetic keyed-cache field. Anthropic ephemeral mode marks the shared system block with `cache_control`. Cache-read/create telemetry and billing are persisted; a provider cache miss is operational evidence, not a simulation failure.
- **Concurrency**: configurable `asyncio.Semaphore(llm.concurrency)` on API calls (production currently uses 3); agents within a phase run concurrently and execution remains deterministic afterward.
- **Failure policy**: HTTP failures preserve status and `Retry-After`. A 429, or an explicit provider-overload response such as MiniMax 529, sets one provider-wide visible cooldown and retries until recovery or operator stop, using `Retry-After` or 15/30/60/120/300-second fallback intervals. Other failures receive the configured bounded retry count and then pause the active phase. Malformed JSON receives one repair completion; a second invalid result becomes a logged `do_nothing`. A billable malformed first completion is persisted even if its repair call fails. End-report generation adds its own bounded wall-clock timeout and falls back without mutating simulated state.

## 9. Market mechanics (all deterministic)

- **Equity order book**: price-time priority; partial fills; orders expire end of session. Index = float-weighted average of listed firms. Circuit breaker (optional config): halt a symbol −20% intraday — interesting to toggle in crash experiments.
- **Goods**: firms post prices; household `buy_goods` actions settle instantly if stocked and affordable; firm inventory decrements; simple production function converts labor-ticks + input costs → inventory each tick. A global **commodity/energy price index** feeds every firm's input-cost structure — this is the variable the oil shock moves (PRD R9).
- **Labor**: postings visible to job-seekers at wakeup; `apply_job` → firm-authored wage offer → candidate counter/accept/reject → firm counter/accept/reject. Only the receiving side can respond to a pending offer, every superseded offer remains auditable, and an accepted wage becomes the engine-enforced payroll obligation. Stored semantics 1–5 retain the historical direct-hire path; fresh semantics-6 runs cannot bypass bilateral acceptance.
- **Shock hooks** (PRD R9 mapping): rate override → clamps `set_policy_rate`; oil shock → scales the commodity index; rumor → injects a synthetic "heard" observation into targeted agents' memories; slanted-news directive → editor receives a framing instruction for N ticks; firm scandal → injects a true negative event about the firm into `events`, which the newsroom picks up naturally. Each hook can be wrapped in any of the three trigger types (instant shock, gradual trend, metric-conditional) — evaluated by the event scheduler each tick.
- **Equity issuance**: a private firm must pass deterministic age/scale/equity qualification. Its founder chooses the share count, reserve, and minimum subscription; investors submit priced bids; the engine applies price/time book clearing, balanced subscription settlement, primary-issuance cap-table provenance, and records a stock price only from those agent-authored terms. Bootstrap listings provide initial sellers but no engine-invented price.
- **Credit**: `apply_loan` packages borrower financials automatically (engine attaches true ledger data — banks see real statements, not the borrower's claims); credit officers return approve/deny + rate + term inside bank risk-policy bounds; the engine enforces schedule, arrears, and default at three missed payments. Under semantics 7, default first seizes eligible cash collateral, then posts only unrecovered principal from the bank's currency-matched equity account to the matching `SYS_LOSS` account as a balanced `loan_loss_chargeoff`; the existing `loan_default` event includes recovered and net charged-off cents. **Bank failure mechanics**: reserves below threshold → interbank borrowing attempt → immutable liquidity-support request → immediate off-cycle central-banker wakeup → actor- and model-provenanced approve/deny action. Approval transfers exactly the recorded shortfall; denial produces the depositor haircut event. Transfer-triggered shortfalls remain pending and fail the transfer closed until the governor decides. Stored semantics 1–6 retain their prior default/solvency rules for exact replay.

### 9.1 Lifecycle mechanics (PRD R11 — all deterministic, seeded PRNG)

**Design rule: biology is engine-side, reactions are LLM-side.** The LLM never decides who gets sick, dies, or is born — those draws come from the run's seeded PRNG so lifecycle schedules replay identically. Agents *react* to lifecycle events through the normal decision loop (a health event is delivered as a morning observation).

- **Health draws** (nightly, per agent): annual age-banded probabilities converted to per-tick hazards. Defaults in `run.yaml`: illness onset ~4%/yr (20–40) rising to ~15%/yr (65+); mean sick duration 5 ticks; sick → critical escalation 5%; critical → death 10%/tick, critical → recovery 25%/tick.
- **Sickness effects** (engine): sick agents are removed from the labor phase (no wage that tick), charged a medical out-of-pocket cost (config, default ~1 day's median wage per sick tick), and receive a "you are ill" observation. Firms see the absence (production function loses the labor-tick).
- **Death**: age-banded baseline mortality (negligible <50, rising after) + critical-illness channel. On death, the engine runs **estate settlement in one atomic transaction batch**: outstanding debts settle via the creditor waterfall → remaining balances and share holdings transfer to the heir (deterministic rule: strongest social-graph tie among living agents; escheat to government sink account if none) → employment contracts terminate → sole-proprietor firms with no successor enter the bankruptcy path. A death event enters `events` with full prominence — the newsroom and the deceased's social ties react via the normal LLM loop.
- **Aging/retirement**: age +1 per 365 ticks; at retirement age (config, default 65) the agent leaves the labor market. Semantics 7 applies the retired cadence both at genesis and transition: no career wake/job seeking, more frequent news, and greater conversation-pair weight. Lifecycle config `retirement_liquidity_target_cents` supplies the target; public decision context exposes it as `retirement_drawdown_target_cents` beside `savings_balance`. Scripted retirees issue `withdraw_savings{amount}` for the checking shortfall before consumption. Validation requires a retired actor, the actor's own declared savings and checking accounts, identical currency, and sufficient savings.
- **Births as household events**: a dependent-count increment with a spending-pattern shift (config probability for age-appropriate households). No child agents.
- **Arrivals (stable-population default)**: each death schedules a replacement adult arrival 5–20 ticks later. Semantics 7 spawns due arrivals deterministically during `NIGHT_CLOSE` through the owned `agents.personas.library` wrapper, funds them visibly from population inflow, and applies the same 70/30 checking/savings split as genesis. Before `MORNING` decisions, exactly one persisted `role=persona,purpose=persona` call may enrich only occupation, personality, political lean, risk tolerance, and media diet; age, wealth, accounts, region, and lifecycle state remain engine-owned. Provider/budget failures pause and resume. A successful malformed response records a deterministic fallback; replay without the recorded response fails closed. `population_mode: stable | drift` remains configurable.
- **Conservation invariant**: estate settlement moves money, never creates or destroys it; arrivals' starting savings are minted from a visible `population_inflow` equity account so reconciliation stays exact and auditable.

### 9.2 Regional trade and migration (PRD R20)

- Semantics-7 regional prompt context contains bounded own-wallet balances and FX quotes plus at most five engine-qualified `trade_opportunities` and valid `migration_options`. Action schemas are advertised only when the corresponding IDs and facts are present.
- A trade opportunity requires an effective contract between distinct-region firms, exporter inventory, and importer funds. The invoice is denominated in the importer's currency so the existing FX/settlement path can execute. A scripted founder creates at most one bounded shipment per decision; delivery and payment remain deterministic domain operations.
- Migration is available only on career cadence to a healthy, unemployed, non-retired citizen with no disqualifying credit exposure. The numeraire-adjusted wage gain must meet the configured threshold. Authorization, destination, contract, funds, credit exposure, and currency checks fail closed and remain auditable.

### 9.3 Real-U.S. calibration mode (PRD R21)

- `calibration.mode` is `synthetic` when absent. The explicit `real_us` mode
  requires semantics 7 and two verified, pinned targets: the Federal Reserve
  2022 SCF summary-extract family support and Census 2022 SUSB national
  employer-firm size support. Missing, malformed, non-finite, wrong-version, or
  unverified inputs fail before genesis. No database-schema or REST-contract
  migration is required.
- The SCF adapter requires five unique public implicates for every `YY1` family,
  sums their published weights, averages numeric amounts, and uses a stable mode
  for work/occupation categories. Deterministic integer cumulative sampling
  overlays age, work status, annual income, dependents, liquid holdings, and an
  engine-owned total-net-worth calibration baseline on otherwise fictional
  personas. `LIQ` funds the existing 70/30 checking/savings split. `NETWORTH`,
  including negative and non-liquid wealth, is persisted on the event spine and
  exposed by the agent inspector without being silently converted into deposits.
- The SUSB adapter excludes overlapping subtotal classes and weights mutually
  exclusive national size classes by `FIRM`. Sampled representative employment
  sets each initial firm target, bounded by configured labor capacity; requested
  and realized headcounts are both recorded. Sampled annual income sets the
  initial pay-interval wage within configured limits.
- Dataset rows are ingested before fresh genesis. Replay removes the mutable
  manifest path, restores the source run's `dataset_manifests` and
  `calibration_targets`, and rebuilds only from those recorded inputs. A
  dedicated seed-derived PRNG isolates calibration draws so synthetic mode is
  unchanged. Events retain per-agent/per-firm source references plus fixed-
  quantile evidence for income, modeled liquid wealth, total net worth, and
  realized firm size against the same-seed synthetic baseline where comparable.

### 9.4 Hosted multi-user control plane (PRD R22)

- Hosted mode is opt-in and uses a separate PostgreSQL catalog for tenants,
  users, memberships, invitations, sessions, run records, writer leases,
  snapshot metadata, audit records, and authentication-attempt throttling.
  Tenant-bearing tables enable and force row-level security. The runtime login
  must be `NOSUPERUSER NOBYPASSRLS`; default-deny access applies until the
  transaction sets a validated tenant scope. Narrow `SECURITY DEFINER`
  functions are limited to opaque credential routing and restart recovery.
- Registration is invitation-only. Passwords are scrypt hashes; session and
  invitation values are opaque 256-bit secrets stored only as hashes. Hosted
  mutations require a same-site secure session cookie, tenant membership, the
  appropriate `admin | observer` role, and a matching CSRF token.
  Authentication attempts are throttled, cross-tenant resources return 404,
  and audit payloads are redacted.
- Each catalog run owns exactly one schema-v11 SQLite world database. A
  lease-based supervisor permits one writer per run while allowing concurrent
  observers and independent runs. Lease loss fails closed; restart discovers
  interrupted worlds as paused rather than advancing them. Tick, pause, and
  stop boundaries publish immutable, checksummed SQLite snapshots through the
  filesystem or S3-compatible artifact adapter.
- The hosted API prefixes run queries, controls, and WebSockets with
  `/api/v2/tenants/{tenant_id}/runs/{run_id}`. Only safe read-only world routes
  and run controls are proxied; local report mounts, replay discovery, arbitrary
  filesystem paths, provider settings, and secrets are not exposed. Local mode
  retains its existing unprefixed API and observatory.
- The reference deployment builds a non-root, read-only application image and
  composes PostgreSQL 17, MinIO, migrations, the hosted service, Caddy TLS, and
  Prometheus. Health/readiness and metrics endpoints support orchestration.
  Migration, bootstrap, atomic database-credential rotation, snapshot,
  verification, restore, and readiness operations are explicit
  `python -m hosted.cli` commands. Kubernetes and a
  public managed deployment are not implied by this reference stack.

## 10. Newsroom + conversations

- Reporters receive only an explicit allowlist of public/reportable event kinds and a bounded public projection of each payload; private beliefs, participant controls, prompts, and provider diagnostics never reach a desk. Within that boundary the digest is ordered by newsworthiness (money size, rarity, entity prominence), reporters draft 2–4 stories, and the editor selects/frames per outlet slant. Stories cite `source_event_ids`; every citation must resolve locally or the complete provider article fails closed to a deterministic grounded brief. The report can later audit how coverage diverged from ground truth (fun metric: *distortion index*).
- Conversation pairing: sample K pairs weighted by social-graph edge weight + shared-event salience, with a semantics-7 participation boost for retirees; 2–4 turns through each speaker's configured route, capped ~150 tokens/turn. Lines heard become observations (→ memory → beliefs). This is the rumor-propagation medium. The stored-run API supports bounded literal text/topic/speaker search plus agent, tick, and cursor filters.
- Fresh maintained profiles require one same-day article per outlet. Editors still select and frame only true same-tick events; if a provider returns missing or dangling citations, publication fails closed to a deterministic brief tied to a local event. A genuinely quiet day first records a `quiet_day` fact so the daily promise never requires invented activity.

## 11. The Oracle

- **Read-only analyst** (the production profile uses Kimi Code's `kimi-for-coding`; an explicitly configured restricted CLI route is also permitted for Oracle volume) exposed as dashboard chat. A provider-neutral planner can request only bounded `query_metrics(names, range)`, `read_news(range)`, `sample_conversations(filter)`, `inspect_agent(id)`, `get_ledger_summary(entity)`, and `read_order_book(firm, depth)` calls. Arbitrary SQL, writes, unknown tools, oversized plans, and excessive results are rejected.
- The executed read transcript is stored in `predictions.evidence_json`, returned by the API, and shown with the prediction for auditability.
- Planner requests carry the inclusive valid tick range. A rejected plan is logged and receives one corrected planning attempt under the same tool/query/result bounds; acceptance re-asks a scheduled question when its latest prediction contains only rejected evidence.
- Answer contract: `{p: 0.xx, drivers: [...], confidence: low|med|high, resolution_rule, deadline_tick}`. Maintained profiles validate finite probability/deadline values, bounded drivers, confidence, and an allowlisted machine-checkable rule before admitting the forecast. Supported rules are `bank_failure`, `firm_bankruptcy`, `bank_run`, `index_drop`, `unemployment_above`, `cpi_above`, `metric_above`, and `metric_below`; generic metric rules must name a persisted series. If the question cannot be given a checkable rule, the Oracle returns `insufficient_data` and says why.
- A resolver job checks open predictions each tick; on resolution, Brier score = `(p − outcome)²` written to `predictions`. An unsupported or malformed stored rule becomes `insufficient_data` and is never converted into a false outcome. This stricter contract is configuration-gated, so stored historical profiles retain their original replay semantics.
- Governed acceptance checkpoints persist `scheduled_e2e_v1` latency in their prediction-bound `acceptance_checkpoint_completed` event. The timer begins before read planning and ends only after the answer is validated and linked to the scheduled forecast. Campaign ID, version, unique key, scheduled tick, question, and logical plan/answer provider evidence are persisted with the sample; missing, dangling, malformed, or duplicate completion references fail the schedule. Replay copies this measured evidence instead of timing offline calls.
- The release calibration corpus is predeclared under `runs/oracle`: ten fixed control/rumor seed profiles run scripted background behavior with only the Kimi Oracle live. The active campaign is `oracle-calibration-v3`, using fresh seeds 7321–7330 and `kimi-for-coding-highspeed`; its token prices are conservatively metered at 3x the standard Kimi route and every run retains a $25 hard cap. Each treatment window has a one-person public rumor precursor one tick before the forecast, followed by the larger depositor-targeted rumor one tick after it; this gives the Oracle observable treatment evidence without letting the precursor itself define the scored outcome. Control arms have neither shock. The validator locks this schedule, question, horizon, rule, route, seed/arm mapping, and Kimi's official OpenAI-compatible endpoint/key contract before execution. Eligible calls require prediction-bound governed request context, nonempty sanitized JSON responses, positive token/cost/latency telemetry, and an exact completion-event call summary; a provider/model label alone is not live evidence. `--oracle-campaign-run` executes one fixed arm, finalizes its source, produces an exact offline replay, and writes a source receipt. `--oracle-calibration-report` accepts the schema-v1 `runs/oracle/manifest-v3.template.yaml` contract, which names every source/replay pair, seed, standalone database, resolved profile, and SHA-256. It never discovers databases by directory scan. Sources must be finalized with no SQLite WAL/SHM sidecars; evaluation opens disposable read-only copies, recomputes exact replay, and proves all source/profile/replay hashes remain unchanged. Forks, participant runs, incomplete schedules, route mismatches, provider failures, invalid provenance, or config/profile mismatches exclude the whole run.
- The archived v1 seed-7301 source completed tick 335 with valid provider provenance but is ineligible: offline replay diverged at the first arrival because staged genesis reset a persona RNG stream that had not been checkpointed, and checkpoint inspection retained SQLite sidecars. The preceding replay-integrity revision adds versioned persona RNG state, standalone checkpoint finalization, an explicit target-tick replay postcondition, and column-specific genesis/checkpoint RNG validation; its focused, representative aggregate, and full-suite verification passed.
- The immutable v2 seed-7311 source and generated offline replay both reached tick 335 and crossed that arrival without the v1 divergence; canonical verification returned `exact: true` with `differences: []`. Receipt generation then failed because checkpoint integrity required exactly 100 total `agents` rows even though lifecycle state correctly preserved one deceased row and created a replacement arrival, leaving 101 stored rows, 100 living agents, and one deceased agent. The correction validates a bounded living population, requires total rows to equal living plus deceased, rejects invalid lifecycle states, binds every death to a chronologically valid schedule and every due schedule to exactly one arrival, authenticates `NIGHT_CLOSE` event phase and agent-subject provenance, and enforces the fixed 5–20-tick replacement delay. V2 remains diagnostic evidence and no v1 or v2 source, response, claim, checkpoint, or replay is reused in v3.
- Before any live dispatch, each fixed campaign arm consumes an immutable pre-run claim bound to the clean Git commit/tree, committed effective config, run ID, seed, and canonical data location. The receipt chain also binds the initialized-state marker, canonical source/replay paths, every required checkpoint manifest, and the actual replay execution tracker. Release eligibility requires each non-operational source call to be consumed exactly once with zero compatibility fallback and zero live replay dispatch. Claim, replay, source, and aggregate receipts are no-clobber artifacts; local consistency is not administrator-proof, so public evidence still requires independent signing or a separately administered append-only transparency log.
- Campaign gates are immutable: exactly the ten predeclared seeds, at least 60 resolved forecasts, both binary outcome classes, nearest-rank `scheduled_e2e_v1` p90 strictly below 60,000 ms, and aggregate Brier strictly below the fixed p=0.5 baseline of 0.25. Every source must include a finalized companion database that the evaluator recomputes as `exact: true` with identical ticks/hashes and `differences: []`. This Oracle-only 335-tick corpus measures forecast latency/calibration and does not satisfy the separate 365-day whole-world acceptance gate.
- Capped profiles reserve an Oracle carve-out (default: $10 of $200) so questions never starve the world. The uncapped production profile meters Oracle spend without applying a ceiling.

## 12. Cost model (planning estimate; 365-day gate pending)

The simulator's July 2026 pricing table uses a modeled price-equivalent of
approximately $0.30/M input + $1.20/M output for MiniMax M3 (cache read
$0.06/M) and $0.95/M + $4.00/M for Kimi Code/K2.7. Subscription-plan charges
and provider cache outcomes may differ; durable metering records the configured
equivalent rather than asserting an invoice.

Per tick, default config (steady state):
| Item | Calls | Tokens (in/out) | Cost |
|---|---|---|---|
| Citizen decisions (~35 wakeups/tick with cadences, M3) | 35 | 1,500 / 300 | ≈ $0.03 |
| Institutional decisions (Kimi Code/K2.7 equivalent) | 8 | 2,000 / 400 | ≈ $0.03 |
| Newsroom (Kimi Code/K2.7 equivalent) | 4 | 2,500 / 600 | ≈ $0.02 |
| Conversations (15 pairs × 3 turns, M3) | 90 | 700 / 150 | ≈ $0.04 |
| Memory compression (M3) | ~45 | 900 / 200 | ≈ $0.02 |
| Lifecycle (engine-side; ~1 persona-gen call per arrival, a few per sim-year) | ~0 | — | ≈ $0.00 |
| **Total** | | | **≈ $0.14/tick** |

→ The arithmetic projects **$200 ≈ 1,400+ simulated days (~4 sim years)** at
steady-state defaults before governor degradation. This is an unverified planning
estimate, not acceptance evidence: the explicitly authorized 365-day campaign
must still measure actual calls, provider behavior, and equivalent spend. Cache
discount is excluded from the projection; event-heavy days may spike usage.

## 13. Determinism, checkpointing, replay

- All engine randomness from one seeded PRNG. LLM outputs are *not* deterministic — so **replay uses stored outputs**: every LLM response is persisted in `llm_calls`; replay mode re-executes the engine against recorded responses, reproducing the run exactly without API cost (also = free debugging).
- Physical SQLite LLM-call IDs are surrogate keys. Canonical verification resolves every persisted `model_call_id` through the referenced call's deterministic contents; reordered concurrent insertions therefore compare equal, while missing, dangling, actor-wrong, or logically wrong references fail verification explicitly.
- Portable fixture format v2 retains only public response text and cached-input telemetry, strips raw provider envelopes/private-reasoning fields, rewrites repository paths as `repo://`, and records its source revision as `unknown-not-recorded` rather than inventing one. Rebuild restores the fixture's recorded `dataset_manifests`, `calibration_targets`, and `scenario_packs` before execution so later edits to current manifests cannot change historical replay. The `fd0adc5dc1` artifact SHA-256 is `af57eed59e47e9057d7645a65e1bb6f2b579a6a63a377fd6301f33af3955e2d7`; its normalized reconstructed replay hash is `2efcabedba51e4bff3ccfd36393db20d13b41cd5d3e9a3772df42015db4f9170`. The historical source/final-code database hash `3586581baea968819cce9fed54b8d9427391645c869f163250c90e7e27976173` remains separate evidence, not the normalized fixture hash.
- Replay opens its source database read-only without schema initialization or migration and releases both SQLite handles idempotently. It schedules persisted Oracle questions at their original `asked_tick` and reconstructs their acceptance checkpoint rows plus completed/missed orchestration events. Exact cache-key matches are preferred; when historical prompt text predates current code, the next unused call with the same tick/agent/role/purpose identity is copied verbatim with its original request and cache key.
- `run_meta.tick` is the last fully completed tick. `active_tick`, `next_phase`, and `phase_state_json` persist in-flight work; successful LLM responses are reused by request key, deterministic phases use SQLite savepoints, and newsroom/conversation/memory writes are idempotent. A rate limit, provider pause, operator stop, or process restart therefore resumes the active phase without advancing or duplicating it.
- Checkpoint = SQLite backup + phase cursor + PRNG state + governor counters, every N completed ticks and on pause. Forking a checkpoint creates a new run id for what-if branches.
- Reconciliation check every tick: `SUM(ledger deltas) == 0` and per-account recomputation matches stored balances; failure → halt + dump (PRD R1).
- On stop, one governed reporter call writes the public narrative from a bounded aggregate/event summary. It is metered against the dedicated report carve-out inside the run cap, cached by logical same-tick input, wall-clock bounded, sanitized, and linked to its local `model_call_id`; offline, replay, budget/provider failure, timeout, or an invalid response uses the deterministic engine narrative. Report generation is serialized with Run/Step/Stop and never runs across an active partial tick. The complete standalone HTML report embeds all charts, and a Markdown reviewer companion records narrative provenance, the event timeline, metric snapshot, Oracle/calibration scorecard, cost table, config, and seed.

## 14. Testing

- **Engine unit tests (no LLM)**: ledger invariants, order-book matching against known fixtures, loan schedules, bankruptcy waterfall, estate settlement (death with debts, with/without heir, founder death) (tax math added with the P1 government layer). Property tests: random valid action sequences never break reconciliation; random lifecycle event sequences (sickness/death/arrival storms) never break reconciliation; same seed ⇒ identical lifecycle schedule.
- **Scripted-agent integration tests**: replace LLM with scripted policies (always-buy, panic-withdrawer) to test systemic mechanics cheaply — a scripted bank run must produce a bank failure through real mechanics before any LLM is involved.
- **Golden-run tests**: CI retains the scripted golden run, restores a sanitized portable fixture of live run `fd0adc5dc1` (stored semantics 5, ten ticks) and replays it with network access forbidden, and runs a deterministic semantics-7 closure scenario covering the new mechanics. Every replay must match ticks, hashes, and deterministic-table differences exactly.
- **Hosted isolation tests**: catalog/auth tests cover tenant-scoped invitations,
  sessions, roles, CSRF, throttling, leases, recovery, and path containment. Real
  PostgreSQL tests exercise forced-RLS default denial, wrong-tenant writes,
  concurrent tenant reads, restart scoping, and session revocation. Real
  S3-compatible tests exercise immutable snapshots, checksums, collision
  rejection, verification, and exact restore. The deployment gate validates
  Compose, builds the non-root image, and runs CLI smoke tests. A bounded HTTPS
  load probe uses environment-sourced test credentials to exercise own-scope
  reads and cross-tenant denials and emits sanitized JSON evidence. Its timeout
  is finite and bounded, and any recorded build reference must be a full Git
  object ID.
- **Cost test**: simulated pricing table + fake responses verify governor thresholds fire at 60/80/95/100%.
- **Supply-chain/release audit**: Python installs use a universal hash-locked
  `requirements.lock`; dashboard notices include runtime dependencies and emitted
  build helpers; pinned datasets and persona prior-art have explicit provenance;
  dependency advisories and current/full-history secrets are scanned. These
  audits are repeated against a release candidate before tagging/publication.

Historical semantics-7 closure receipt: the final integrated adversarial gate
passed 93 tests and the closure suite passed 280 in 165.73 seconds. The
post-merge compatibility/replay cleanup suite passes 303 in 178.22 seconds,
including compatibility, provenance, privacy, cache, dataset-refresh, and
portable-replay regressions. Rehearsal
`5a0d40d773` and live MiniMax pilot
`b4832032ba` each completed five ticks with every targeted effect, six
checkpoints, balanced currencies, and zero provider/rejection failures. Their
offline replays matched exactly with hashes
`fa190b0dc10a6b94038f7dbd8838a6aea14c1c5b57b691a4788527f8e8cffc34` and
`ec2b24093ad599cca1b9750686a809f28ca08755ca0e4bc3bcbfef861c399ae2`.
The live run spent `$0.01121124` under its `$1` cap. PR #15 merged to `main` as
`255555c2b24530c0bd39aed2f501277a468adc0a` after the exact-head dashboard and
full Ubuntu/Windows Python 3.11/3.12 matrix passed; post-merge CI run
`29368193807` repeated all five jobs successfully. Tagging and publication
remain separate release actions.

R21 subsequently merged through PR #18 at
`21bbf30051e3de8c9b5b7a50e48a0e342d94676a` after all five PR jobs passed.
Post-merge main run `29403186283` repeated the dashboard and Ubuntu/Windows
Python 3.11/3.12 jobs successfully.
R22 then merged through PR #19 as
`1806294d4fecbe13ddbdf615c459755c74293599`. Its real-container image/Compose,
restore/rotation, and multi-user load evidence passed locally, and all six
exact-head jobs passed at `1cf1d0a` in run `29409250171`. Post-merge run
`29411023992` executed zero repository steps because GitHub blocked the account
for billing/spending-limit reasons; it is not a failed code test. No public
production deployment is claimed. After P0/P1 and R18–R22, the specification
has no remaining functional feature gap; the pending rumor, Oracle, 365-day,
and final public-release audit/deployment work is release evidence and
operations.

The preceding release-gate revision on 2026-07-15 passed 590 Python tests
with 8 skipped, 23 dashboard tests, a fresh 603-module dashboard build, and
checksum verification for the pinned FRED/BLS/SCF/SUSB datasets. The final v3
receipt-hardening tree passes 599 Python tests with 8 skipped in 1,618.07
seconds. Free
production-workflow rehearsal `881ed41994`
completed 365 ticks with 100 living agents, zero spend, balanced ledger state,
zero operational failures, six completed and resolved Oracle checkpoints, all
five shock traces, the five-seed experiment, and three run-bound reviewed
phenomena. Its receipt passed 19 of 20 checks; only `real_providers` was false
because every route was intentionally scripted. This is mechanics evidence,
not the live 365-day release gate. Companion replay
`replay-881ed41994-3465cb3101` matched tick 365 and hash
`37d18cf45365532b39de68efffac68cacb0010ab453734110b8e057e498786ed`;
every deterministic table was exact and `differences: []`.

## 15. Prior art and borrowed components

Evaluated July 2026 as potential foundations; decision was **own kernel + selective borrowing** (PRD §2).

| Source | License | Verdict | What we take |
|---|---|---|---|
| [LLM-Economist](https://github.com/sethkarten/LLM-Economist) (Karten et al. 2025) | MIT upstream | Too narrow as a base (tax planner vs. workers only) | **Adapt the published persona-conditioning approach** through an independently written deterministic synthetic-heuristic base module; pin prior-art attribution and do not classify it as Census-calibrated or vendored upstream code |
| [Doxa](https://github.com/VincenzoManto/Doxa) (v0.1, single maintainer) | GPL-3.0 | Closest in spirit; rejected — no double-entry banking layer, demo scale, and distribution would require evaluating GPL-3.0 copyleft obligations | **Design ideas only, zero code copied**: shock/trend/conditional event-trigger taxonomy; trust-graph-weighted conversation pairing sanity check |
| [AgentSociety](https://github.com/tsinghua-fib-lab/agentsociety) (Tsinghua FIB) | Apache-2.0 | v2 pivoted to AI-social-scientist tooling; the economy/city modules are in unmaintained legacy v1 | Validation that SQLite-based full replay is the right pattern (their v2 does the same); their paper's methodology for evaluating agent believability |
| Generative Agents (Stanford) / EconAgent (Tsinghua) | papers | Reference designs | Weighted additive memory scoring over recency, importance, and relevance — already in §6; decision-cadence framing — already in §3 |

Rule for external code: copied upstream source must live under `vendor/` with its
license and immutable wrapper boundary. Independently written implementations of
published ideas live in owned modules with an attribution note and must not be
described as vendored code.

## 16. Repository layout

```
agent-economy/
  run.py                  # entrypoint: python run.py --config runs/base.yaml
  runs/base.yaml          # default world config (population, models, budget, shocks)
  engine/                 # deterministic core: ledger, markets, credit, firms
  agents/                 # personas, scheduler, prompt assembly, memory, actions
    personas/             # owned base sampler + governed enrichment boundary
  llm/                    # gateway: routing, governor, caching, parsing
    adapters/             # openai_compat (Kimi/MiniMax), anthropic, cli (restricted)
  world/                  # tick loop, phases, event bus, shocks, metrics
  oracle/                 # analyst agent, tools, resolver, scoring
  server/                 # FastAPI app, WebSocket hub, static dashboard
  hosted/                 # optional R22 catalog/auth/supervisor/artifacts/API/CLI
  deploy/                 # Compose, Caddy, Prometheus, PostgreSQL role init
  config/hosted*.yaml     # strict hosted config; credentials come from env
  dashboard/              # React app (built → server/static)
  reports/                # end-of-run report generator (md + html)
  tests/
  data/runs/<run_id>.db   # one SQLite file per run (gitignored)
```

## 17. Build order (maps to PRD §11 phases: steps 1–2 = Phase 1, 3–4 = Phase 2, 5–7 = Phase 3, 8 = Phase 4)

1. **Kernel**: ledger + engine + validator + scripted agents + reconciliation tests. *No LLM yet — prove the economy's plumbing first.*
2. Agent runtime + gateway + governor; 20 route-configured citizens, 1 bank; CLI event stream.
3. Exchange + firms lifecycle + 2nd bank; scale to 100 agents; checkpoints;
   implement and verify R11 health, death, estate settlement, and arrivals.
4. Newsroom + conversations + memory pipeline; run the rumor pilot and the R11
   lifecycle acceptance gate.
5. Dashboard (read-only first, then controls).
6. Oracle + resolver + scoring.
7. Shock library + end-of-run reports → **v1 complete (PRD P0)**.
8. P1 (R12–R17): government/elections, VC, experiment harness, Oracle
   calibration, replay UI, and the health economy.
