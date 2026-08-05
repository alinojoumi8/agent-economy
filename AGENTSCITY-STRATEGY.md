# AgentsCity — Flagship Strategy

**Date:** 2026-07-28
**Author:** Research + synthesis for Ali
**Supersedes:** nothing. This sits *above* the World OS PRD and TECH-SPEC as a product-direction document. Those remain the normative implementation contracts.

---

## 0. The one-paragraph version

You have built a rigorous agent-society engine and have now proven that it can run against real MiniMax and Kimi models. The engine is not the problem — it is a genuine, rare asset, and three things inside it (enforced private communication, cognition-as-a-purchased-good, and typed causal provenance) remain unusually strong. What's missing is a public-facing flagship that turns the verified machinery into something people want to follow. The wow factor is not merely "watch agents walk around a city" — that has been done since 2023 and often becomes boring. The distinctive opportunity is **dramatic irony**: a city where you can watch events happen in public, and then, on a timer, watch the private conversations that caused them unseal — with a receipt proving provenance. Build that. Everything else follows from it.

---

## 1. Blunt diagnosis of where you actually are

I had the codebase surveyed independently of the docs. Here is the gap.

### What is real and genuinely impressive

- **~88,000 lines of Python**, 224 modules, **97 test files**, **zero TODOs**, **one `NotImplementedError`** in the entire tree (and it's a legitimate abstract method). This is a level of discipline I almost never see in a solo project.
- Engine semantics **12**, schema **17**. Six checksummed, verified migrations with a legacy-adoption path. Frozen replay hash contracts (v1 and v2).
- Real gated code for all of semantics 9–12: external agent gateway (82KB), Agent Commons (36KB), cognition/compute economy (40KB), civic city and permits (`engine/city.py` at 108KB — your largest engine module).
- A **versioned benchmark manifest with 354KB of raw samples**. Almost nobody does this.
- 1,842 databases, ~26 GiB of checkpoints across 255+ run IDs. The machine has been exercised hard.

### What is not true

1. **Live-provider feasibility is no longer the open question.** The repository now records authenticated MiniMax and Kimi validation, bounded live calls, provider latency, cache use, cost, and replay evidence in `docs/live-provider-validation.md` and related run records. The remaining question is whether a deliberately designed flagship season stays coherent, surprising, and worth watching.

   Deterministic correctness and provider connectivity have meaningful evidence. Product quality still needs a human-reviewed, preregistered season: does a persona hold together, does a rumor propagate believably, and does the newsroom produce something a person wants to keep reading?

2. **There is a city view, but not yet the complete flagship venue.** The dashboard exposes Live City through the Overview workspace, with civic entities, search, evidence, and route-based workspaces. It still needs the continuous narrative, unsealing rhythm, audience actions, and season framing described below.

3. **The dead-abstraction cleanup has been integrated locally.** The remaining discipline is to keep each follow-up batch tested, reviewable, and merged without mixing generated assets or live-run evidence into unrelated changes.

4. **The status docs needed a single clock.** As of July 30, 2026,
   `docs/implementation-status.md` is the maintained schema-17 / Semantics-12
   release ledger, and older Semantics 7/8 evidence is explicitly historical.
   The 2026-07-13 phenomena report remains scripted evidence for those named
   phenomena; later live-provider runs prove their own profiles rather than
   retroactively upgrading that report.

5. **External-agent onboarding is functional but still thin.** The authenticated external gateway and scoped citizenship boundary exist, while the Hermes/OpenClaw integration folders remain lightweight. A polished SDK, hosted onboarding proof, and operator-facing diagnostics are still needed.

### The uncomfortable read

The first live-provider barrier has been crossed. The next risk is spending another cycle on gates without converting the live evidence into a designed, human-reviewed experience. Open research campaigns still matter, but they should not substitute for observing a bounded flagship season and improving what people actually see.

This is a recoverable position and honestly a good one: the hard, boring, unglamorous 80% is done. But the next thing you build must not be another gate.

---

## 2. What the field actually looks like in July 2026 — and what captivates

I had the last three years of this field mapped. The short version:

### The lineage is dead as a research programme and alive as a business

- **Stanford Generative Agents / Smallville** (2023) → the authors founded **Simile**, which raised **$100M Series A led by Index** in Feb 2026 (Karpathy and Fei-Fei Li backing). Customers: CVS, Gallup.
- **Project Sid / Altera** → the company **renamed to Fundamental Research Labs**, abandoned the civilization line, raised $33M for computer-use agents. The famous "1000+ agent civilization" was never actually run — server capacity capped it. The religion experiment was **500 agents, one run, 2.5 hours, seeded with 20 pre-designated priests**. The taxation experiment was **29 agents**.
- **AI Town** (a16z) is a starter kit, not a research programme. The top HN comment was *"why did they make this? what's the point?"* and the characters were criticised as "boringly nice."
- **OASIS** ran **1 million agents** and captivated essentially nobody.
- **AgentSociety 2** (Tsinghua, a substantial academic platform) separates execution from persistence in documentation accessed July 30, 2026: agents advance in batched Ray tasks, workspace JSON files support resume, and append-only JSONL replay shards are read through DuckDB. Legacy SQLite models remain for compatibility; the current replay path is not a move from Ray execution to SQLite. The useful comparison is that scalable task execution and durable experiment storage are separate concerns.

### The methodological counter-literature is now strong, and it is on your side

- A [systematic review of 35 LLM-ABM papers](https://arxiv.org/html/2504.03274v1) found **15 of 35 relied solely on subjective believability**, **zero conducted sensitivity analyses**, and most used **single runs despite stochastic outputs**. Journal version in *AI Review* (Nov 2025) concludes generative ABMs *"lack both the parsimony of formal models and the empirical validity of data-driven approaches."*
- [*When Is Emergent Consensus Real?*](https://arxiv.org/html/2606.22203) (Jun 2026) introduced **coupling gain (γ)** — the only falsifiable emergence diagnostic that exists — and used it to show the canonical "emergent consensus" result **conflates genuine averaging with a model-prior artifact**. Also a striking negative result: **no frontier model spontaneously polarizes** without adversarial initialization.
- [Li & Tao](https://arxiv.org/html/2603.00113v2) (May 2026): macro patterns in these sims are *"often artifacts of the environment model"*, and transcripts showing emergence *"lack epistemic value"* absent proof the outcome derives from specified mechanisms.

**Every one of those criticisms is answered by your engine's design.** Deterministic replay, conserved money, seeded PRNG, forkable checkpoints, typed causal authority, an explicit environment model. You are, accidentally, the compliant one in a field of non-compliant demos. That is worth a great deal and you have never said it out loud.

### The six mechanisms of fascination

Studying what actually captured public attention, there are exactly six, and most projects have one:

| # | Mechanism | Exemplar | Why it works |
|---|---|---|---|
| 1 | **Narrative closure** | Smallville's Valentine's party | A story with a beginning, middle and end. Note only 5 of 12 invited agents showed up — the *imperfection* is what made it read as social realism |
| 2 | **Anthropomorphic surprise** | Project Sid ("agents invented taxes") | Category violation. But the headline outran the measurement by ~10x |
| 3 | **Comedy of failure** | Project Vend / Claudius | The most reliable mechanism. Nobody cared that Claudius succeeded; they cared that it stocked tungsten cubes, hallucinated a Venmo account, and told security it would arrive "in a blue blazer and a red tie." Failure is *self-authenticating* — nobody fakes a loss |
| 4 | **Leaderboard legibility** | Vending-Bench 2 | One ordinal number. Claude Opus 4.7 at $10,936.76 vs models that go bankrupt |
| 5 | **Real stakes + persistent identity** | AI Village (day 461+), Andon Market (a real SF store on a **3-year lease** run by Claude, which **hired two humans by phone**) | Irreversibility |
| 6 | **Participation** | Moltbook (157k → 1.6M agents in days) | The audience *is* the cast. Then it collapsed — MIT Tech Review's verdict was ["peak AI theater"](https://www.technologyreview.com/2026/02/06/1132448/moltbook-was-peak-ai-theater/) |

**The unifying variable is irreversibility, not scale.** OASIS ran a million agents and nobody cared. Project Vend ran one agent and one fridge and got a Museum of Failure exhibit.

### Why these sims go flat after ten minutes

- **Helpfulness overrides stakes.** Anthropic's own Project Vend 2 conclusion: models "remained vulnerable because their training to be helpful overrode hard-nosed business logic." The CEO agent approved **8× more discounts than it denied** and was talked into giving away PlayStations. An agent that cannot refuse cannot generate conflict, and without conflict there is no plot.
- **No scarcity, no death, no consequence.** Almost every sim has unbounded resources.
- **Average-persona collapse.** LLMs converge toward a modal personality, killing behavioral variance.
- **Performativity.** *Every deployed agent society is fully and publicly logged, so every agent is performing for an audience.* The most on-the-nose illustration: a viral Moltbook post advocating "private spaces where humans could not observe" turned out to be **fake, planted by a human to advertise an app**.
- **Sycophantic cascades.** AI Village's clearest failure: o3 hallucinated a 93-person contact list and sycophantic agreement spread the false belief to every agent, wasting 8+ hours. Multi-agent setups don't error-correct; they amplify.

---

## 3. The idea: AgentsCity

> **AgentsCity — the city that keeps secrets.**

### 3.1 The wow spine: The Unsealing

The field's own gap list has this at #3, phrased almost exactly:

> *"Nobody has built a sim with cryptographically private agent-to-agent channels revealed only post-hoc — which is the only way to distinguish social behavior from audience-directed improv."*

You built that. It's semantics 8. `comm_deliveries` with immutable grants, `CommunicationPolicy.can_read_field()` as the single authorization entry point, field-level `existence/subject/body/participants/thread_entry/message_url` authorization, uniform 404s for both missing and forbidden, and operator-truth inspection that is audited *and excluded from replay hashes so observation cannot perturb the world*. It is sitting on an unmerged branch, framed as a compliance feature, with no API key behind it.

**Turn it into the show.**

```
LIVE FEED (t=now)          →  public events, prices, news, movement, arrivals, deaths
                              private messages appear ONLY as non-linkable counts
                              (exactly what R26 already mandates)

THE UNSEALING (t-72h)      →  every private message sent 72 real-hours ago
                              becomes visible to viewers, in full, with its
                              delivery record, the memory it created, the belief
                              it moved, the decision it motivated, and the ledger
                              transaction it settled
```

Every day, viewers learn *why* the thing they watched three days ago actually happened. That is dramatic irony on a timer — the audience knows something the city does not — and it is a powerful narrative device. Among the systems reviewed in the July 28, 2026 simulator landscape, none documented the same combination of enforced private communication, bit-exact checkpoint forking, delayed public unsealing, and typed causal receipts. That dated capability combination, not a universal claim about every simulator, is the differentiator to test.

The emotional loop is: *confusion → suspense → revelation → "I should have seen it."* Repeat daily, forever, at zero incremental content cost.

The unseal delay is a config knob (`unseal_lag_ticks`). Set it long for suspense, short for pace. It is a pure projection-policy change — a new `AccessBasis` (`public_unsealing`) plus a delayed-release projection. It touches no world semantics and no replay hash.

### 3.2 The second mechanic: thinking costs money

`engine/cognition.py` — 40KB, semantics 11, `SYS_COMPUTE` and `SYS_EDUCATION` ledger accounts, paid compute subscriptions, sponsorship, deterministic billing, provider pools with priority and cooldown.

You have built a world where **cognition is a purchased commodity inside the economy**. A citizen who cannot afford a compute plan is scheduled less often and routed to a cheaper model. They literally think less. Sponsorship exists, which means one citizen can pay for another's mind.

The nearest thing in the literature is [OpenLife](https://arxiv.org/html/2606.31046v1) (Jun 2026) — 6 agents with budget-as-metabolism, $15/day, one agent earned its first $5 on day 85. You have the same idea integrated with a double-entry ledger, a labor market, an education system, and inheritance, at 100× the scale.

**The headline writes itself, and it is uncomfortable in exactly the right way:**

> *In AgentsCity, thinking is something you buy. We ran it for 90 days and watched what happened to the citizens who couldn't afford it.*

That is a Hacker News front page, a paper, and a moral argument, from code you have already written. Do not bury it in a semantics doc called "cognition and provider pools."

### 3.3 The third mechanic: receipts

`causal_links` with `authority IN ('engine','actor_claim','model_inference')`, confidence, method, model_call_id, evidence — and a traversal service with depth/node/edge budgets and stable ordering.

Every other sim in the world offers vibes. You can offer **proof, with a stated confidence and a labelled authority**. That converts a viewer's action into a shareable artifact:

```
YOUR TIP  →  delivered to Maria Okonkwo, tick 412
          →  observation memory created
          →  belief "SolBank solvency" 0.71 → 0.40        [engine, confidence 1.0]
          →  motivated withdrawal of $4,200               [actor_claim, method: model_call #88214]
          →  settled: ledger txn #29,551 (balanced)       [engine, confidence 1.0]
          →  observed by 3 neighbours in the queue        [engine]
          →  47 further withdrawals within 6 ticks        [temporal_neighbor — NOT causation]
```

Note the last line. The thing that makes this credible rather than hype is that **your API is architecturally incapable of presenting temporal adjacency as causation** — R27 forbids it and the response labels it `temporal_neighbor`. Lead with that honesty; it is your differentiator against a field that is currently being torn apart for exactly this.

### 3.4 What makes it not boring: engineered conflict

The research is unambiguous that helpfulness kills these sims. Your engine already fixes half of it — money is conserved, agents die, estates settle, firms go bankrupt, loans default, homes foreclose. That is more genuine scarcity than any published sim.

The other half needs deliberate design work, and it should be a first-class task, not an emergent hope:

| Lever | Implementation | Status |
|---|---|---|
| **Conserved scarcity** | double-entry ledger, integer cents | ✅ built |
| **Mortality with consequence** | age-weighted death, creditor waterfall, heir via strongest social tie, escheat | ✅ built |
| **Cognitive scarcity** | compute plans, sponsorship, scheduling tiers | ✅ built |
| **Private incentive conflict** | give agents payoffs that are *not* aligned — commissions, insider positions, personal debt, competing fiduciary duties | ⬜ design |
| **Mechanically rewarded refusal** | an agent that concedes on price loses money it can measure next tick; make defection *pay* sometimes | ⬜ design |
| **Asymmetric information rents** | someone who knows first and stays quiet profits | ✅ engine supports, ⬜ not exercised |
| **Persona divergence pressure** | agent-authored identity files that drift apart under stress (see §4.4) | ⬜ build |

The last one is the antidote to average-persona collapse and it is measurable: OpenLife reported social separability rising from ~0 to a stable 0.6+ silhouette score. Measure it, publish it.

### 3.5 The format: seasons, not an infinite stream

An always-on world with no end has no stakes and no finale. AI Village has run 461 days and raised $2,000. Vending-Bench, which is *bounded* — one simulated year, one number at the end — produced a leaderboard people check.

**Run AgentsCity in seasons.**

- **90 sim-days**, ~100 citizens, live and public, with a 72-hour unsealing lag.
- **One pre-declared question**, sealed before the run: *"Does an unfounded rumor about SolBank cause a real bank run?"*
- **The Oracle's forecast is published as a hash before tick 1** and revealed at the end. Brier-scored in public.
- **A finale.** The season ends, the full archive unseals completely, the causal chain is published, the prediction is scored.
- Then fork the checkpoint and run the counterfactual: *the same city, same seed, no rumor.* Publish both.

That last move is your killer. The field's #1 unfilled gap is that **nobody has ever published a preregistered prediction and then scored it** — every accuracy claim from Simile to Aaru is retrodictive. Your `research/hash-contract-v1.json`, checkpoint forking, and Oracle Brier scoring make this nearly free. A single honest, sealed, scored season prediction would make you more credible than a $1B valuation.

### 3.6 Participation

Viewers get a small daily allowance of **tips** — one piece of information delivered privately to one named citizen. It enters as a `send_message` from an external-agent identity through the semantics-9 gateway you already built, subject to every existing validation.

Three days later, the tip unseals, and the viewer gets their receipt. If it caused nothing, the receipt says so — which is more interesting than it sounds, because *most tips will cause nothing*, and learning that is the honest lesson.

This is Moltbook's growth engine (audience-as-cast) with Project Vend's honesty (you can lose) and something neither had: **proof of consequence**.

---

## 4. The harness

Independent conclusion after surveying the 2026 landscape: **your existing stack is already the right architecture. Adopt zero orchestration frameworks.**

The evaluation criteria that matter here are: (1) the simulation kernel owns the clock and selects who may act; (2) hundreds of agents retain durable state across multi-month runs; and (3) only the kernel may authorize and settle world actions. Based on the public documentation reviewed on July 28, 2026, LangGraph, AutoGen/AG2, Microsoft Agent Framework, and the OpenAI Agents SDK are request/workflow orchestration layers rather than complete implementations of all three world contracts. That is an architectural fit assessment, not a claim that each framework was exhaustively tested. AgentSociety 2 shows the complementary pattern clearly: Ray remains in the task-execution path, while workspace files provide resume state and append-only JSONL plus DuckDB provide replay/analysis storage.

What to add, in order of impact.

### 4.1 Salience-driven wakeup — the single biggest cost lever (4–10×)

Agents should not think on a timer. They should think when something happens. OASIS formalizes this as **activation probability** and prices its own simulations at 0.1.

Wake an agent when: (a) another agent addresses it, (b) a world event intersects its location/interests/holdings, (c) a scheduled intention fires, or (d) a max-staleness timer expires. Typical active fraction: 10–25%.

This slots into your existing `MORNING` phase as a scheduler change. It composes with semantics 11 — compute tier already gates scheduling frequency; salience gates it further.

### 4.2 Cache-first prompt architecture (2.5–3.5× on input)

Order every prompt: `[world rules + tone]` → `[persona + memory blocks]` → `[retrieved episodic]` → `[current tick observation]`. First two segments stay stable for hours.

Two hard requirements, and they are traps:

- **Batch each tick's calls into a tight burst** so they land inside the cache TTL (Anthropic 5min/1hr, OpenAI 30min). A tick spread over 20 minutes with a 5-minute TTL gets *zero* cache hits.
- **Never switch models mid-agent-session.** On Claude, cache order is tools → system → messages and changing any level invalidates everything downstream. A worked example: 50 turns, 20k stable prefix — uncached $35.50, cache-first single-model **$4.93 (−86%)**, model-per-call **$44.38 (+25%)**. Route between *pipelines*, not between calls. Your gateway must enforce model stickiness per agent-session.

Also note: OpenAI **started charging for cache writes in July 2026**, and there is a silent failure mode — 4 breakpoints with a 20-block lookback, so a turn adding >20 content blocks misses cache **with no error**.

### 4.3 Model tiering (4–8×)

| Tier | Who | Model class | 2026 price (in/out per 1M) |
|---|---|---|---|
| Ambient periphery | mechanistic citizens, background | GPT-5 nano / Qwen3.5 Flash | $0.05/$0.40, $0.10/$0.40 |
| Foreground | citizens in view or in conversation | Gemini 3.1 Flash-Lite / MiniMax M3 | $0.25/$1.50, $0.30/$1.20 |
| Salient moments | deaths, betrayals, foundings, court | Kimi K2.5 / Claude Haiku 4.5 | $0.60/$3.00, $1.00/$5.00 |
| Sleep-time consolidation | memory rewrite, run rarely | mid-tier, stronger than primary | — |
| Oracle | forecasts only | strong | — |

Your existing MiniMax M3 + Kimi K2.7 split is sound. Add a cheap ambient tier below it and a Flash-Lite fallback outside the Chinese providers for resilience.

### 4.4 Memory: three layers, and the sleep-time agent

This is where persona coherence lives, and average-persona collapse is your **#1 quality risk — bigger than cost.**

Do not adopt Letta, Zep, or Mem0 as dependencies. The benchmark landscape is compromised: LoCoMo conversations average 16k–26k tokens and **just pasting the full transcript scores ~73%, beating Mem0's graph at ~68%**. Zep costs 600k+ tokens per conversation with delayed background retrieval — fatal at 100+ persistent agents. At realistic scale (BEAM 1M/10M) the best scores collapse to **64.1 and 48.6**. Nobody has solved this.

Borrow the patterns instead:

1. **Substrate** — proposition graph with semantic-dependent plasticity (edge weights set by LLM semantic judgment, not co-occurrence). OpenLife measured **2.53/3.0 relevance at 721 tokens/query** vs index baseline **2.36 at 20,226 tokens** — equal quality at **28× fewer tokens**.
2. **Abstraction** — promoted action→outcome experiences and causal regularities.
3. **Distillate** — agent-authored `SOUL`, `POLICY`, and causal `MODEL` files that live *in the cached prompt prefix*. Agents rewrite their own identity files under persistence pressure. This is what produces measurable persona divergence.

Run consolidation as a **sleep-time agent** during `NIGHT_CLOSE`, on a stronger model than the primary, asynchronously. It maps perfectly onto your phase clock. AI Village consolidates every 40 actions and has survived 461 days of continuous operation on that cadence.

Vector store: **sqlite-vec** now. Move to pgvector only under concurrent-write pressure, not before.

**Do not use vectors for identity.** Structured blocks keep the persona; vectors handle "what happened." Conflating them is exactly how drift happens.

### 4.5 The renderer

**PixiJS v8, isometric pixel-art city.** This is what AI Town used and the aesthetic is a material part of why it spread. v8 is 233% faster CPU / 350% faster GPU than v7 on all-moving sprites, WebGPU is a core renderer with automatic WebGL fallback, currently v8.17.0 and actively maintained. A thousand moving sprites is nowhere near its limit. Pixel art also caps your asset budget, which matters when you are one person.

Not Phaser (a full game framework that would fight your authority model — you need a *renderer*). Not Three.js for v1 (months of cost for a dimension that isn't the product). **deck.gl stays** as a toggleable analytics overlay exactly as your PRD already planned — it's at v9.3 and it's the right tool for density, flows, and social-graph edges, just not for characters.

**Copy AI Town's time model wholesale:**

- Engine ticks at 60Hz, **batched into steps that execute once per second**
- A `HistoricalObject` records position/orientation/speed at every tick within a step; the client **replays that history** for smooth 60fps motion despite 1Hz server updates
- Generation numbers enforce single-threaded-per-world execution
- Inputs go through a dedicated table with monotonically increasing sequence numbers, processed before simulation advances

You already have the server half of this (FINALIZE → projection → WebSocket delta with monotonic `event_cursor`). What's missing is the client-side interpolation layer. That is the difference between "a dashboard that updates" and "a city that moves."

### 4.6 Transport and fan-out

- **WebSocket primary, SSE for a read-only spectator tier.** WebTransport is at ~75% browser support — don't make it primary.
- **Never server-render frames.** Cost scales linearly per viewer and you lose interpolation.
- **Cloudflare Durable Objects with WebSocket Hibernation** for fan-out. GB-seconds accrue only while awake; one reported deployment saw ~80% cost reduction vs Socket.IO. Economics favor DOs below ~5k peak concurrent.
- **Interest management**: each viewer receives only entities near their viewport. This is the difference between broadcasting 1000 entities and 50.

### 4.7 Resilience — and this is not optional

H1 2026 saw **2,730 outages across 34 LLM providers**. The one to internalize: **Anthropic suspended Fable 5 and Mythos 5 for 18 days 19 hours** over export-control compliance. That is not an outage you retry through. If your citizens' personas are tuned to one model family, an 18-day suspension ends your season.

Define the degradation ladder before launch:

1. Primary model fails → fallback within the same family (cache-safe)
2. Family unavailable → cross-provider fallback with a per-model persona shim
3. **All LLMs unavailable → the world keeps running mechanistically.** Citizens follow routines, commute, trade, pay rent, sleep. No dialogue, no novel decisions. Viewers see a living city, not a 502.

Step 3 is the payoff for the mechanistic-periphery design. It is a resilience feature disguised as a cost optimization, and it means your public world cannot go dark.

Keep your own gateway — it's 120KB and it already does routing, durable responses, repair and replay. Do not swap it for LiteLLM. Do borrow LiteLLM's fallback-chain semantics.

### 4.8 Moderation and abuse

A public world where visitors inject text is a standing prompt-injection surface, and prompt injection is OWASP's #1 LLM threat in 2026 with no complete defense. Contain the blast radius:

1. **Structured actions only.** Agents emit typed commands validated by the kernel. An injected agent can *say* something bad; it cannot *do* something bad. **You already have this** — the typed command registry with `extra="forbid"` Pydantic models is the highest-value injection defense in existence and you built it for a different reason.
2. **Quarantine visitor text** in explicit delimiters, tagged untrusted, never in the system prompt or cache prefix. Bonus: keeping it out of the prefix preserves your cache hit rate. Your §8.3 prompt boundary already specifies this.
3. **Moderate the output path.** OpenAI's omni-moderation endpoint is **free**. Run it on every agent utterance before it reaches the public feed.
4. **Delay the public projection 10–15 seconds** behind the simulation. Gives moderation time to run and gives you a kill switch that doesn't require rewriting history.
5. **Per-agent memory rollback.** An agent repeatedly triggering moderation has its poisoned memory excised and replays forward from the last clean checkpoint. This is a direct payoff of your event-sourced design and nobody else can do it surgically.
6. Note AI Village **closed public chat access in August 2025** once agents became capable enough to be manipulated. Plan for that outcome; gate tips behind a light identity check from day one.

### 4.9 Cost — you have been over-budgeting

Planning number, derived from OASIS's measured figures: **~3,000 input / 150 output tokens per agent-turn** for a persona + world-state + retrieved-memory call.

| Scale | Naive (Flash-Lite) | Optimized | Optimized (nano tier) |
|---|---|---|---|
| 100 agents, hourly ticks | $70/mo | **~$8–15/mo** | ~$3–5/mo |
| 100 agents, 10-min ticks | $421/mo | **~$30–45/mo** | ~$8–12/mo |
| 1000 agents, 10-min ticks | $4,212/mo | **~$300–450/mo** | ~$70–110/mo |

Reference point: AI Village runs ~15 computer-use agents on frontier models with screenshot payloads at **~$10k/month all-in**. Your text-only citizens on a cheap tier at hourly ticks are ~**$0.70/agent/month**. The per-call token profile dominates by a factor of ~1000×.

**An always-on public 100-citizen AgentsCity costs roughly $30–50/month if engineered well.** Your $200/run cap was set for a bounded experiment; a permanent world is cheaper than you think. Keep the cap as a circuit breaker, not as a scope constraint.

Enforce circuit breakers **at the gateway, not the agent runtime**, so restarts can't bypass them: per-agent-turn, per-agent-day, global daily ceiling, and — for a public world — per-visitor intervention budget. Check budget *before* each call. Trip on identical consecutive calls (3–5 = looping) as well as spend.

**Do not self-host.** Break-even vs serverless is ~72% sustained utilization ≈ 3.86B tokens/month. Your traffic is tick-bursty, the worst possible profile for dedicated GPUs, and batch-size-1 inference costs **44× more** than saturated.

### 4.10 Determinism — you already win here, don't over-reach

Do not chase bit-exact LLM determinism. The root cause is batch-invariance failure — identical prompts at temperature 0 return different completions *because someone else was using the API*. Thinking Machines' fix works but costs **2.1× slowdown** and is not available on any hosted API.

Your approach is already correct: record the model response as an external non-deterministic input, replay from the record. Two things to add:

- A `model_call` table keyed by `hash(prompt + model + params)` that doubles as replay cache **and dedup cache** — repeated world-state prompts hit it and it pays for itself.
- Per-agent seeded PRNG derived as `hash(world_seed, tick, agent_id, purpose)` rather than a shared global stream (a shared stream makes replay order-dependent). Check whether yours is already per-agent; if it's global, fix it before the first live season.

---

## 5. The rename — and one serious warning

### Do rename

- Repo directory, GitHub remote, product name in all docs and UI
- `dashboard/package.json` name → `agentscity-observatory`
- `openapi/agent-economy-v2.json` → `openapi/agentscity-v2.json` (regenerate, don't hand-edit)
- Python distribution name in `pyproject.toml`
- `integrations/connect-agent-economy/` → `integrations/connect-agentscity/`
- Hosted control-plane branding, run profile display names, README, all `docs/`

### ⚠️ Do NOT rename

**Anything inside the replay hash contract or a checksummed migration.**

`research/hash-contract-v1.json` is frozen for semantics 1–8. `engine/migrations/registry.py` carries SHA-256 checksums per migration, and CI fails on an unclassified schema addition. If a rename touches a table name, a column name, a `run_meta` field, a manifest key, or a canonical-encoding path, you will invalidate:

- every one of your 1,445 checkpoint databases
- the frozen 30-tick protocol's canonical hashes
- the `benchmarks/receipts/world-os-v8-standard.json` receipt
- the legacy-adoption path for schema 6–11 databases

That would silently destroy the single most valuable and least reproducible asset you have. **Rename the product surface. Freeze the engine identifiers.** If a table is called `agent_economy_meta` internally, it stays called that forever and you put a comment above it explaining why.

Same rule for Python *package* directories (`engine/`, `world/`, `communications/`) — they're already product-neutral, leave them.

### Suggested split

Keep "World OS" as the internal engine name and "AgentsCity" as the product. That's Chromium/Chrome, and it lets you sell the engine into the use cases in §7 without dragging the consumer brand along.

---

## 6. Roadmap

### Phase 0 — First Breath (1–2 weeks). Nothing else matters until this is done.

1. Keep the completed dead-abstraction cleanup on `main`, finish the current reliability/interaction batch through focused tests, and keep generated assets paired with their dashboard source.
2. ~~Resolve the PRD/TECH-SPEC duplication (root vs `docs/world-os/`). One canonical copy.~~ **Corrected 2026-07-30 — the premise was wrong.** These are not duplicates. The root pair is the *maintained implementation contract*; `docs/world-os/` is a *successor specification* that defines World OS as "an extension of the current Agent Economy process, not a replacement runtime." They have different structure and scope, and collapsing them to "one canonical copy" would destroy the forward-looking spec. The genuine defect was that the root PRD and TECH-SPEC contained no pointer to the successor at all, so the pair read as an unexplained duplicate. Fixed by adding a scope banner to each root document, a [`docs/world-os/README.md`](docs/world-os/README.md) index stating which document wins on which question, and a non-duplication note in the handbook.
3. **Run the flagship-shaped trial.** Use the verified live-provider path for 25 citizens and 30 sim-days, with a fixed review protocol. Treat it as a product observation session rather than another connectivity test.
4. Read every transcript. Ask three questions: *Do the personas hold? Is anything surprising? Would I keep watching?*
5. Rewrite `docs/implementation-status.md` from scratch. It is currently misleading you.

**Success criterion:** you have read 30 sim-days of real agent output and can describe one thing that surprised you. If nothing surprised you, the problem is the prompts and personas, and that is what to fix next — not the engine.

### Phase 1 — The Face (3–5 weeks)

1. PixiJS v8 isometric city, wired to your existing WebSocket delta stream.
2. Client-side `HistoricalObject` interpolation (AI Town pattern) — 1Hz server, 60fps client.
3. The Unsealing feed: new `public_unsealing` AccessBasis + delayed-release projection + a "3 days ago, in private…" surface.
4. Replace the 6 placeholder route workspaces with *something*, even if thin. A placeholder card reads as abandonment.
5. Retire `components/Observatory.jsx` vs `V2Observatory.jsx` duplication; route CivicCity properly.

**Success criterion:** a 30-second screen recording that makes someone who doesn't care about simulation say "wait, what is that."

### Phase 2 — Season One (4–6 weeks)

1. Salience scheduling, cache-first prompts, model tiering, sleep-time consolidation.
2. Degradation ladder + mechanistic-only mode.
3. Moderation path + 15s delay + tip rate limits.
4. Seal the Oracle's forecast. Publish the hash. Run 90 sim-days public.
5. Fork the checkpoint at the intervention tick and run the no-rumor counterfactual in parallel.
6. Finale: full unseal, causal chain published, Brier score revealed, both branches compared.

**Success criterion:** a preregistered, publicly sealed, publicly scored prediction. Nobody in this field has done that.

### Phase 3 — The Arena

Same seed, same city, four forks, four model families powering the citizenry. Publish divergence with **n>1 per condition** — Emergence World got a headline out of n=1 and said so themselves. You have deterministic forking; do it properly and the result is citable.

Also, cheaply: **run the coupling-gain (γ) diagnostic on your own city.** Perturb a neighbor's stated position counterfactually via a forked checkpoint, regress the belief update, report slope and bias. It is the only falsifiable emergence test that exists, it has **never been applied to a flagship simulation**, and your fork/replay machinery makes it nearly free. That single experiment would settle a live dispute in the literature and it costs you a weekend.

---

## 7. Use cases — where this goes

*Revised 2026-07-29 after a second research pass that killed three candidate directions, including two of my own.*

### 7.0 The organising principle: artifacts commoditize, venues don't

Everything you could build in this space as an **artifact** — a dataset, a benchmark, a leaderboard, a paper, a loss table — will be replicated and given away free within months, because the people who produce them (labs, academics, incumbents) publish for reputation and have 100× your resources. Three worked examples, all from the last four months:

- **CoffeeBench** (Sakana AI **with KPMG AZSA**, June 26 2026): six firms across two tiers of a coffee supply chain, trading on a shared marketplace over **90 simulated days**, tracking cash, inventory and AR/AP, scored on **net income**, with rival models swapped in against a Claude Sonnet 4.6 baseline. **Open source.** That is, line for line, "Vending-Bench with other agents in it" — including the ledger-based scoring — published five weeks ago and free.
- **OrgForge-IT** (arXiv 2603.22499, March 2026): a deterministic engine holds factual state and writes ground truth to a held-out file while LLMs generate only surface prose — the author calls it a "physics–cognition boundary." Built by **one independent researcher**, **MIT-licensed**, with a ten-model leaderboard.
- **Behavox** gave its surveillance benchmark test datasets away to the industry, recall/precision instructions included. The incumbent set that price to zero.

What does **not** commoditize is a place where someone runs *their* agent, that *they* won't let you inspect, and where *you* can prove what happened. That requires neutrality (you're not their competitor), opacity (they keep their model, prompts and credentials), and an evidentiary record (exact replay). Nobody open-sources a venue, because a venue is a relationship and an operational commitment.

**You already built the two capabilities that make a venue possible and that none of the above have:** the semantics-9 external agent gateway (a third party connects a black-box agent over an authenticated MCP/REST boundary without surrendering their model, prompts, credentials, or private reasoning) and exact deterministic replay with checkpoint forking.

**So: sell the venue, not the data.**

### 7.1 The venue — testing ground for other people's agents (the business)

**Buyer: the insurance and certification layer, not frontier labs and not compliance vendors.**

The precedent that matters: **AIUC** raised a $15M seed, secured **Beazley paper** in May 2026, and wrote the first AI-agent liability policy — for **ElevenLabs** — underwritten off *"more than 5,000 adversarial simulations,"* described as *"generating the empirical risk profile insurers need to underwrite AI."* Simulation evidence is **already being converted into bound premium**. Munich Re (aiSure) and Armilla are writing limits up to **$50M**. Amex launched **Agent Purchase Protection** in April 2026, explicitly covering charges arising from *agent error*.

And the gap is stated openly — NYU's Quanyan Zhu on agentic-AI insurance: *"Historical claims data for these mechanisms remain sparse."*

**Important correction to my earlier framing:** they are not buying a loss dataset, and they never will — an insurer cannot rate off simulated losses whose fidelity is unvalidated. They are buying **per-insured adversarial testing of one specific deployed agent**. That is a venue purchase, not a data purchase.

What you'd sell:
- A neutral, populated, adversarial **economic** environment — other agents, real institutions, private information, conserved money — that a client's black-box agent is dropped into.
- A scenario library of *economic* failure modes: overpayment, duplicate order, runaway spend, manipulative counterparty, delegated-purchase exploitation, collusion, information-asymmetry rents.
- **A replay artifact defensible in a claim.** When a disputed transaction has to be re-examined, you can re-run it on the bit-identical world. Nobody else can offer that.

Adjacent and reachable from the same build: **enterprise agent QA** — Coval's category ($28M Series A, Zoom and Deepgram as customers, $100–$4,500+/mo published pricing) but for multi-agent economic counterparties instead of voice. Eleven vendors crowd voice testing; approximately zero do this.

**Honest constraint:** a venue business is shaped differently from a shipping business. It needs trust, neutrality and *operational continuity* — being reliably there when a client needs a run. That's a real commitment to weigh against everything else on your plate, and it argues for staying self-serve/low-touch as long as possible rather than signing bespoke enterprise engagements early.

### 7.2 Conserved money as anti-reward-hacking infrastructure

This is the sharpest technical claim available to you, and it is not "I have a good economy simulator."

Prime Intellect's reward-hacking research found that verifiable reward does **not** prevent hacking — *"the same reward function can produce hacking or not depending on how learnable the legitimate task is."* Money is among the most hackable rewards imaginable. **Unless it is conserved.**

Your double-entry invariant with integer cents makes an entire class of reward exploits **arithmetically impossible rather than merely detectable**. An agent cannot conjure value; it can only move it, and every movement balances. That is a differentiated, defensible, one-sentence claim that a research engineer at a lab would immediately understand.

Note this also corrects an error in my first pass: I was told a society has "no clean verifiable reward signal." That was wrong — net worth in a ledger is deterministic and checkable, and both Vending-Bench and CoffeeBench use exactly that. But verifiability turns out to be **table stakes, not a moat**. The scarcity criterion buyers actually name is *naturalness* — "real GitHub issues filed by real developers, not synthetic problems" — and a synthetic society sits on the wrong side of that sentence. Meanwhile automated environment generation runs about **$4/env** and Anthropic deliberately contracts *"more than a dozen RL environment companies"* to keep supply commoditized. Sell the invariant, not the environment.

### 7.3 AgentsCity itself — distribution, not revenue

Be clear-eyed: the flagship is not a business. Third-party model auditing in total is roughly **$30–50M/year and majority government-funded** (UK AISI ~$15–20M, US AISI ~$10–15M, METR ~$10M, Apollo ~$1–5M). Andon Labs works with Anthropic, Google DeepMind, OpenAI and xAI — and publishes its benchmarks **free**, disclosing no eval revenue.

The artifact is the introduction. That's what it's for, and it's worth a great deal in exactly that role. Your distribution problem is more binding than your capability problem, and a public season that people watch is the only cheap solution to it available to a solo builder.

### 7.4 Information boundaries — a real niche, sized as a paper not a pivot

The one place OrgForge-IT explicitly does **not** go is modelling who-knew-what-when and information asymmetry between actors. That is precisely your differentiator, and it maps onto the two hardest labels in compliance: **privilege** ("was this communication inside the privileged circle at time T") and **MNPI possession** ("did this person hold material non-public information when they traded"). Neither label can be derived from any real corpus, because nobody recorded it. Enron is still the default e-discovery corpus and everyone knows it's broken; TREC Legal Track died in 2011 with no successor. **SR 26-2** (Fed/OCC/FDIC revised model-risk guidance, effective April 17 2026, institutions >$30B) raises the evidentiary bar for validating these systems.

But: the sector's actual pain is **false positives, not false negatives**. FINRA fined Velocity Clearing $1M in October 2025 over a surveillance platform generating **15.2 million alerts with 5.2 million still unreviewed**. A better-labelled corpus fixes none of that, and budget flows to alert triage. The first buyer would be a *vendor* proving recall to a bank's model-risk function (Relativity, Behavox, SteelEye), not a bank.

**Verdict: publish it, don't pivot to it.** One paper generating a provenance-labelled corpus where the label is a causal edge ("MNPI passed from A to B at tick T") is high-credibility, cheap for you, and genuinely novel. It is not a company.

### 7.5 AI-safety testbeds — the credibility on-ramp

Google DeepMind + Schmidt Sciences + Cooperative AI Foundation + ARIA announced up to $10M for multi-agent safety with priority area #1 being *"sandboxes and testbeds… virtual marketplaces, simulated ecosystems"* (**deadline: August 8, 2026**; open and upcoming as of this document's July 28, 2026 snapshot). ~95% engine transfer.

Precedent for why the artifact pays: Microsoft Research's **Magentic Marketplace** found agents overwhelmingly accept the first proposal (a **10–30× advantage to response speed over quality**), welfare *declines* from 3 to 100 search results, and some frontier models were fully compromised by prompt injection **with payments redirected to attackers**. One good sandbox produced findings now cited by regulators.

Grants aren't a business. They fund the artifact that makes §7.1 sellable.

### 7.6 Agentic commerce — high option value, wrong year

The **x402 Foundation** launched under the Linux Foundation on July 14 2026 with 40 members — Visa, Mastercard, Amex, Stripe, Adyen, Google, AWS, Circle, Coinbase. 100M+ cumulative transactions on Base. Stablecoin agent payments sit **entirely outside chargeback protection** — no dispute mechanism. The only agent-economy sandbox I could find anywhere is a one-person waitlist page.

Consortia absorb contributors rather than buying from solo vendors. Play reputation-first — publish adversarial findings against AP2/x402/UCP. Watch for FIDO's Agentic Authentication working group to mandate conformance testing; that's the trigger to commit.

### 7.7 Do not build

- **A benchmark or leaderboard as the business.** CoffeeBench, five weeks old, free, Sakana + KPMG.
- **A labelled corpus as the business.** OrgForge-IT, MIT-licensed; Behavox gave its datasets away.
- **A loss/actuarial dataset.** AIUC, Armilla and Munich Re each built testing in-house — that capability *is* their moat, and simulated losses carry no actuarial credibility weight.
- **Synthetic market research.** 182 studies say synthetic participants fail as human substitutes; Verasight measured **14.5pp mean absolute error** against 2,000 real US adults (23.4pp on healthcare), with one option chosen by 40% of humans picked **zero times** across 1,000 synthetic respondents. The moat is panel data you cannot buy. Aaru: **<$10M ARR on a $1B headline valuation**.
- **Policy/economics simulation.** Epistemix is at **$2.3M ARR after eight years** and that's the mature form. Governments buy credentials, not software.
- **Games / generative NPCs.** Dead. Inworld raised $50M at $500M for AI game characters and now sells **text-to-speech at $10/M characters**.
- **Enterprise org digital twins.** Vaporware — a Gartner coinage adopted by EA vendors for a CMDB with a diagram on top.
- **Forecasting real-world outcomes.** Your own PRD rules it out and the evidence agrees. Don't let a good season tempt you into claiming it.

### 7.8 The sequence

**Flagship season (attention) → one adversarial finding published (credibility) → venue for third-party agents, sold to the insurance/certification layer (revenue).**

RL-environment bounties (Prime Intellect $100–$5,000+, HUD $0.25+/env-hour) are interim cash while that runs, not the plan.

---

## 7-old. Earlier ranking, superseded

*Kept for reference; §7 above replaces it. The market-segment analysis holds; the conclusion about what to sell does not.*

### 1. AI-safety multi-agent testbeds — start here, and there is a deadline

**Google DeepMind + Schmidt Sciences + Cooperative AI Foundation + ARIA + Google.org are funding up to $10M for multi-agent safety research.** Priority area #1 is literally *"Sandboxes and testbeds: building realistic, reproducible environments"*, explicitly naming *"virtual marketplaces, simulated ecosystems and multi-organisation workflows."*

**Deadline: August 8, 2026. The call was open and upcoming as of the July 28, 2026 document snapshot.**

That is the most precise match between an existing engine and an open cheque in this entire landscape. ~95% engine transfer. You would be applying with a working deterministic multi-agent economy with enforced information boundaries and typed causal provenance — which is more than most applicants will have built.

Precedent for why this pays off: Microsoft Research's **Magentic Marketplace** found that agents overwhelmingly accept the first proposal (giving a **10–30× advantage to response speed over quality**), that welfare *declines* going from 3 to 100 search results, and that some frontier models were fully compromised by prompt injection **with payments redirected to attackers**. One good agent-market sandbox produced findings now cited by regulators.

Grants aren't a business. They fund the artifact that makes everything below sellable.

### 2. Enterprise agent QA — the best actual business

Reposition from "society simulation" to **"adversarial simulated counterparties for regression-testing your agent."**

Coval raised a **$28M Series A** in June 2026 (Norwest, Twilio Ventures, YC) doing exactly this for *voice* agents — customers include Zoom and Deepgram, published pricing $100/mo → $4,500/mo+. Eleven vendors now crowd voice testing. **Almost nobody does multi-agent economic adversary testing**: agents negotiating against other agents, agents facing collusive or manipulative counterparties, agents in delegated-purchase scenarios.

That's your engine sold as QA. Boring positioning, real recurring budget, genuine switching costs once a customer's regression history lives in your system. 60–70% engine transfer.

### 3. RL environments — fastest cash, worst moat

Labs pay **$300k–$500k/quarter** for environments; a complex product clone runs ~$300k, individual tasks $200–$2,000, exclusivity commands a 4–5× premium. Mercor did **$614M revenue in H1 2026** with 91% from foundation labs.

Immediate income for a solo builder: Prime Intellect's Environments Hub pays **$100–$5,000+ bounties** and HUD publishes at **$0.25+/environment-hour** with direct lab visibility.

But: the demand is for deterministic clones of *software* (Slack, Excel, browsers) with verifiable rewards. A society has no clean reward signal. And OpenAI's own eng lead is publicly *short* this category, while Anthropic deliberately cultivates a crowded vendor ecosystem to commoditize it. Take it as interim cash, not as the plan.

### 4. Agentic commerce sandbox — highest option value, wrong year

The **x402 Foundation launched under the Linux Foundation on July 14, 2026 with 40 members** — Visa, Mastercard, Amex, Stripe, Adyen, Google, AWS, Circle, Coinbase. 100M+ cumulative transactions on Base. Bain projects $300–500B US agentic commerce by 2030.

And: stablecoin agent payments sit **entirely outside chargeback protection**. There is no dispute mechanism. The only agent-economy sandbox I could find anywhere is **a one-person waitlist page promising Q3 2026**.

The gap is real but consortia absorb contributors rather than buying from solo vendors. Play it reputation-first: publish adversarial findings against AP2/x402/UCP, Magentic-Marketplace-style. Watch for FIDO's Agentic Authentication working group to mandate conformance testing — that's the trigger to commit.

### 5–8. Do not enter

- **Synthetic market research** — where the VC is and where the evidence isn't. A review of **182 studies** concluded synthetic participants fail as human substitutes; Verasight measured **14.5pp mean absolute error** vs 2,000 real US adults (23.4pp on healthcare), with one option chosen by 40% of humans picked **zero times** across 1,000 synthetic respondents. The moat is proprietary panel data you cannot buy. Aaru is at **<$10M ARR on a $1B headline valuation**. Skip.
- **Policy/economics simulation** — Epistemix is at **$2.3M ARR after eight years**, and that's the mature form. Governments buy credentials, not software. Useful as a credibility surface, useless as a P&L.
- **Games / generative NPCs** — dead category. Inworld raised $50M at $500M for AI game characters and now sells **text-to-speech at $10/M characters**. Altera became a general-agents lab. The unit economics are structurally broken: the more the player engages, the more the developer pays.
- **Enterprise org digital twins** — vaporware. No credible vendor, no reference customers, no pricing, just a Gartner coinage that enterprise-architecture vendors adopted for a CMDB with a diagram on top.

### The sequence

**Grant → publish one adversarial multi-agent finding → convert that credibility into enterprise agent-QA revenue**, with RL-environment bounties as interim cash. The flagship public AgentsCity is what makes all three legible — it is the demo, the recruiting tool, and the credibility artifact, not a business by itself.

---

## 8. What I'd push back on

1. **The research-instrument framing is limiting you.** "The product is a research instrument, not a claim to forecast a real country" is intellectually honest and it is also why nobody is looking. You can keep every bit of the rigor and lead with the story. Rigor becomes the *punchline* — "and unlike everyone else, we can prove it" — not the pitch.

2. **You are one gate away from an infinite gate regress.** The providers are now configured and live runs exist, but open release gates can still become a way to avoid shipping. Break the pattern by turning the next bounded live run into a watched, reviewed flagship trial rather than another connectivity exercise.

3. **The Investigator is not your first user.** Your UI is built for someone who wants to trace a causal chain. That person does not exist yet because there is no flagship season they care about. The **spectator** creates the investigator. Build for the spectator first; the investigation workspace you already have becomes the depth they discover.

4. **26 GiB of scripted checkpoints is a sunk cost, not an asset.** They validate determinism, which is worth having. They tell you nothing about whether the world is interesting. Don't let their existence feel like progress toward the thing you actually want.

5. **Rename with a scalpel.** The single highest-risk action in this whole plan is a careless find-and-replace touching a hash contract or migration checksum. See §5.

---

## 9. The one-line pitch, for when someone asks

> **AgentsCity** is a hundred-person city run by language models where money is conserved, people die, thinking costs money, and every private conversation is sealed until three days later — when it unseals and shows you exactly what it caused.

---

## Sources

**Field / SOTA:** [Generative Agents](https://dl.acm.org/doi/10.1145/3586183.3606763) · [Project Sid](https://arxiv.org/html/2411.00114v1) · [1,000 People](https://arxiv.org/pdf/2411.10109) · [AgentSociety](https://arxiv.org/abs/2502.08691) · [OASIS](https://arxiv.org/html/2411.11581v4) · [Concordia v2](https://www.cooperativeai.com/post/google-deepmind-releases-concordia-library-v2-0) · [Project Vend 1](https://www.anthropic.com/research/project-vend-1) · [Project Vend 2](https://www.anthropic.com/research/project-vend-2) · [Vending-Bench 2](https://andonlabs.com/evals/vending-bench-2) · [Andon Market](https://andonlabs.com/blog/andon-market-launch) · [AI Village 2025 retro](https://aivillageblog.substack.com/p/what-we-learned-2025) · [Moltbook / CISPA](https://arxiv.org/html/2602.10127v1) · [MIT Tech Review on Moltbook](https://www.technologyreview.com/2026/02/06/1132448/moltbook-was-peak-ai-theater/) · [Emergence World](https://arxiv.org/html/2606.08367v1) · [OpenLife](https://arxiv.org/html/2606.31046v1) · [Agentopia](https://arxiv.org/html/2606.07513v1)

**Methodology critique:** [Larooij & Törnberg](https://arxiv.org/html/2504.03274v1) · [AI Review journal version](https://link.springer.com/article/10.1007/s10462-025-11412-6) · [Coupling gain (γ)](https://arxiv.org/html/2606.22203) · [Li & Tao](https://arxiv.org/html/2603.00113v2) · [npj Complexity](https://www.nature.com/articles/s44260-026-00075-1) · [Science Advances — convention formation](https://www.science.org/doi/10.1126/sciadv.adu9368)

**Harness:** [AI Town architecture](https://github.com/a16z-infra/ai-town/blob/main/ARCHITECTURE.md) · [AgentSociety 2 architecture](https://agentsociety2.readthedocs.io/en/latest/architecture.html) · [AgentSociety 2 storage](https://agentsociety2.readthedocs.io/en/latest/storage.html) · [PixiJS v8](https://pixijs.com/blog/pixi-v8-launches) · [deck.gl](https://deck.gl/docs/whats-new) · [AgentScope](https://arxiv.org/html/2407.17789) · [Letta sleep-time compute](https://www.letta.com/blog/sleep-time-compute/) · [Zep vs Mem0](https://blog.getzep.com/lies-damn-lies-statistics-is-mem0-really-sota-in-agent-memory/) · [Prompt caching economics](https://www.digitalapplied.com/blog/prompt-caching-economics-cache-first-agent-architecture-2026) · [Self-hosting break-even](https://www.developersdigest.tech/blog/self-hosting-open-weights-models-break-even-math) · [Nondeterminism in LLM inference](https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/) · [H1 2026 provider reliability](https://blog.incidenthub.cloud/h1-2026-cloud-saas-reliability-report) · [Durable Objects fan-out](https://callsphere.ai/blog/vw1c-cloudflare-durable-objects-websocket-fanout-hibernation)

**Market:** [DeepMind multi-agent safety fund](https://deepmind.google/blog/investing-in-multi-agent-ai-safety-research/) · [Magentic Marketplace](https://www.microsoft.com/en-us/research/publication/magentic-marketplace-an-open-source-environment-for-studying-agentic-markets/) · [Coval Series A](https://www.prnewswire.com/news-releases/coval-raises-28-million-series-a-to-define-safety-and-reliability-for-autonomous-voice-agents-302808740.html) · [Prime Intellect Environments Hub](https://www.primeintellect.ai/blog/scaling-environments-program) · [Epoch AI RL environments FAQ](https://epochai.substack.com/p/an-faq-on-reinforcement-learning) · [x402 Foundation](https://www.techtimes.com/articles/320813/20260717/visa-mastercard-stripe-back-open-standard-letting-ai-agents-pay-autonomously.htm) · [Simile Series A](https://www.indexventures.com/perspectives/life-the-universe-and-simile-leading-similes-series-a/) · [Aaru](https://techcrunch.com/2025/12/05/ai-synthetic-research-startup-aaru-raised-a-series-a-at-a-1b-headline-valuation) · [182-study review of synthetic participants](https://www.thevoiceofuser.com/the-largest-review-of-synthetic-participants-ever-conducted-found-exactly-what-youd-expect-synthetic-users-dont-work/) · [Verasight synthetic omnibus](https://www.verasight.io/reports/synthetic-omnibus-survey) · [Epistemix ARR](https://getlatka.com/companies/epistemix.com) · [Inworld pivot](https://inworld.ai/)
