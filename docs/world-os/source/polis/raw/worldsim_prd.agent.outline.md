# POLIS — A Living Macroeconomy of Autonomous Agents: Product Requirements & Technical Specification

## 1. Executive Summary & Vision (~1200 words) [ROUND 2 — after all chapters]
### 1.1 Vision
#### 1.1.1 A persistent digital society where LLM-driven agents are born, work, found companies, trade, vote, sue, consume news, and die — emergence over scripting
#### 1.1.2 Core design creed: physics-first, cognition-second; the event log is the product; institutions are reducers, not agents (Insights 1, 3, 4)
### 1.2 What the Research Proved
#### 1.2.1 Every mechanic has a validated precedent (EconAgent, AgentSociety, OASIS, Generative Agents, ElectionSim) — integration is the risk, not novelty
#### 1.2.2 Tiered cognition makes it affordable: ~$73/sim-day at 10k agents vs ~$16k naive (Dim05, Dim08)
### 1.3 The Build
#### 1.3.1 Custom event-sourced kernel + borrowed cognitive patterns; MVP in 3 phases; god-view UI with Story Desk, Causal Inspector, Semantic-Zoom Map (Insight 8)

## 2. Product Requirements (PRD) (~2500 words, 4 tables) [ROUND 1]
### 2.1 Product Definition & User Personas
#### 2.1.1 Three user personas: Builder/Founder (ships scenarios), Observer (watches the world), Researcher (runs experiments) — with goals and jobs-to-be-done
#### 2.1.2 Product principles: emergence over scripting; narrative never invents state; every number hyperlinks to its causal events
### 2.2 Functional Requirements Catalog (FR-A…FR-W)
#### 2.2.1 Agent core & persona (FR-A1–A3): two-layer persona (structured ledger + narrative backstory), memory, needs engine (table: FR id, requirement, priority, phase)
#### 2.2.2 Communication (FR-C1–C3): conversations, async email with inbox/outbox, relationship graph
#### 2.2.3 Lifecycle (FR-L1–L2): birth, education, career, retirement, death, inheritance
#### 2.2.4 Economy (FR-E1–E3): typed goods/services, ledger-backed money, measurable macro aggregates
#### 2.2.5 Companies & capital (FR-B1–B4, FR-M1–M3): founding, financials, bankruptcy, litigation, stock market, VC rounds
#### 2.2.6 Politics, professions & news (FR-P1–P3, FR-N1–N2): elections→policy loop, career tracks, news generation & consumption
#### 2.2.7 World engine (FR-W1–W3): tick loop, typed event bus, time controls
### 2.3 Non-Functional Requirements
#### 2.3.1 Solo-builder feasibility, headless sim service + Next.js front end, one-command local spin-up, model-abstraction layer, golden-run replay tests (table: NFR, target, verification method)
### 2.4 Success Metrics
#### 2.4.1 Cost per sim-day, agent count, macro stylized-fact scores, persona-consistency scores, time-to-demo (table of metrics with MVP targets)
### 2.5 Scope: MVP vs Phases vs Out-of-Scope
#### 2.5.1 Phase 1 (50–200 agents: economy+companies+news+simple market), Phase 2 (lifecycle, elections, litigation), Phase 3 (VC depth, 10k scale) — explicit out-of-scope list

## 3. Agent & World Domain Model (~2500 words, 3 tables) [ROUND 1]
### 3.1 Agent Anatomy
#### 3.1.1 Two-layer persona: structured state (demographics, Big Five, skills, balance sheet) + narrative backstory — census-grounded generation at scale (Dim06)
#### 3.1.2 Four-tier memory: episodic stream (recency×importance×relevance), Ebbinghaus decay, temporal knowledge graph, procedural skill library; nightly consolidation
#### 3.1.3 Needs & emotion engine: Maslow needs-vector → Theory-of-Planned-Behavior planning (AgentSociety-validated), OCC appraisal, 3-degrees mood contagion
### 3.2 Agent Classes
#### 3.2.1 Hero (full LLM, 1–2%) / Named (cheap LLM, ~15%) / Background (rules+archetypes, ~85%) with promotion/demotion events (Insight 6)
### 3.3 Lifecycle State Machine
#### 3.3.1 Birth→education→career→retirement→death FSM; estate/inheritance handling; skill growth via teachers/education (table: states, transitions, triggers)
### 3.4 Relationships & Social Fabric
#### 3.4.1 Relationship graph (trust, kinship, employment, ownership); homophily-driven formation; Dunbar-bounded maintenance
### 3.5 The Agent Cognition Loop
#### 3.5.1 Perceive (visibility-filtered) → retrieve memory → deliberate (tiered model) → act (schema-constrained tool call) → reflect (cadence: intra-day/nightly/weekly)

## 4. System Architecture — The Harness (~3000 words, 2 diagrams-in-words, 3 tables) [ROUND 1]
### 4.1 Architectural Creed
#### 4.1.1 Physics-first, cognition-second: deterministic kernel owns ALL state; LLMs are a stateless decision service behind a salience router (Insight 1)
#### 4.1.2 Institutions are reducers, not agents: markets, courts, elections are deterministic FSMs; participants are LLM agents — agents propose, institutions dispose (Insight 4)
### 4.2 The Event-Sourced Kernel
#### 4.2.1 Append-only event log + snapshots + decision journal = replay, branch, counterfactual; the event log powers memory, newsroom, UI time-machine, legal discovery (Insight 3)
#### 4.2.2 Event envelope schema: id, tick, causality links, actor, type, payload, visibility ACLs, provenance (table of core event types)
### 4.3 Scheduling & Concurrency
#### 4.3.1 Hybrid: logical-time event queue with barriered tick batches; OASIS-style activation sampling; Concordia-style game-master resolution; actor-per-agent (Ray) + deterministic reducers for coordinators
### 4.4 The Cognition Scheduler
#### 4.4.1 Salience scorer (rules → nano-class → frontier-class routing), budget governor with cost/sim-day SLO, stable-prefix caching (90%), nightly Batch API (50%) (Insight 2)
### 4.5 Persistence & Data Stack
#### 4.5.1 Postgres-first: event store + TimescaleDB metrics + pgvector memory + recursive-CTE graphs; graduate to Qdrant/Neo4j past 5M memories; ClickHouse/DuckDB analytics
### 4.6 Reliability Engineering
#### 4.6.1 Schema-constrained outputs (XGrammar/strict mode), validate→retry→escalate→autopilot, Temporal-style journaled sagas for multi-tick processes (lawsuits, funding rounds)

## 5. Framework Decision — Adopt vs Build (~2000 words, 2 tables) [ROUND 1]
### 5.1 The Candidates Evaluated
#### 5.1.1 Classic ABM: Mesa (Apache-2.0, ceiling ~10³–10⁴, GIL-bound), Agents.jl (fastest, off-stack), MASON/Repast/NetLogo (rejected) (Dim01)
#### 5.1.2 LLM societies: Concordia (GM/component pattern), OASIS (1M-agent scheduling), AgentSociety (Ray+MQTT engine), AI Town (event journal) (Dim02)
#### 5.1.3 Agent runtimes: LangGraph/AutoGen/CrewAI — workflow tools, not world runtimes (Dim05)
### 5.2 Decision Matrix
#### 5.2.1 Weighted criteria: scale ceiling, determinism/replay, LLM-cost controls, domain fit (ledger/markets/courts), team stack fit, license (table with scores)
### 5.3 Verdict
#### 5.3.1 BUILD a custom thin kernel in Python (Ray + asyncio + Postgres + Redis/MQTT); BORROW Concordia components, OASIS activation sampling, AgentSociety scheduling, Generative-Agents memory — every major 2023–2026 society did exactly this (High-confidence finding #1)

## 6. Economy & Markets Engine (~3000 words, 4 tables, pseudocode) [ROUND 1]
### 6.1 The Accounting Spine
#### 6.1.1 Stock-flow-consistent (SFC) quadruple-entry ledger; every transaction is 4 postings; macro aggregates (GDP, CPI, unemployment) are pure queries (Dim03)
### 6.2 Goods, Firms & Production
#### 6.2.1 Typed goods/services, recipe-template input-output production, perishable inventories; LLM CEOs set strategy, engine computes unit economics (Dim04 — Project Vend lesson)
### 6.3 Firm Lifecycle State Machine
#### 6.3.1 8-state FSM (idea→incorporated→operating→distressed→bankrupt(Ch.7/Ch.11)→liquidated); Gibrat growth, age/size-dependent exit hazards (~20% yr-1, ~50% yr-5), Zipf tail calibration (table: states, guards, actions)
### 6.4 Capital Markets
#### 6.4.1 Limit-order-book exchange (ABIDES-style deterministic matching pseudocode), tick history, indices; agent traders via BDI beliefs from news (TwinMarket coupling)
#### 6.4.2 VC firms as organizational agents: deal sourcing, ~20%-dilution round ladder, power-law outcomes (50–65% <1×, 2–5% >10×), IPO bookbuild mechanics
### 6.5 Banking & Money
#### 6.5.1 Endogenous money: banks create deposits via lending; interest, credit scoring, bank-run risk; central bank Taylor-rule policy lever
### 6.6 Bankruptcy & Litigation Mechanics
#### 6.6.1 Dual-track triggers (liquidity default + equity deficit), trade-credit contagion cascades; litigation: breach/tort/IP/shareholder suits, two-stage settlement bargaining, engine-computed damages (Dim04)

## 7. Society: Communication, News, Politics & Law (~2500 words, 3 tables) [ROUND 1]
### 7.1 Communication Fabric
#### 7.1.1 Brokered multi-channel message envelope (email/DM/feed/newswire/legal), per-agent visibility filter (Concordia partial_state), latency & cost per channel (Dim10)
### 7.2 The Newsroom Pipeline
#### 7.2.1 7-stage event→editorial→article→distribution→belief pipeline; multiple news agencies with editorial slant; misinformation engine as scenario knob; no dedicated newsroom sim exists — design opportunity (Dim07)
### 7.3 Belief & Opinion Dynamics
#### 7.3.1 Gated belief-update pipeline into memory (provenance-tagged); hybrid bounded-confidence + LLM opinion model; feed-ranking as the sim's master policy lever (Insights 5, 7)
### 7.4 Politics & Elections
#### 7.4.1 Election-cycle FSM: parties (birth/death), candidates campaign, spatial-voting kernel + persona deliberation, winners set policy levers; validated fidelity (ElectionSim 47/51 states) with per-jurisdiction caution (Dim07, C5)
### 7.5 Law & Courts
#### 7.5.1 Court procedure FSM (filing→discovery→settlement→trial→judgment→appeal), lawyers as agent profession, ADICO machine-readable rule registry that politics mutates and the engine enforces; LLM-judge only for narrative, engine for verdicts (Dim07)

## 8. Scale, Cost & Reliability Engineering (~2000 words, 2 tables) [ROUND 1]
### 8.1 Capacity Plan
#### 8.1.1 1k agents: 1 GPU + API, <$150/day; 10k: 3–6 H100, $0.5–1.5k/day; 100k: 20–40 H100, $5–12k/day; 1M: tiered 85/14/1 + archetypes, $40–110k/day (Dim08 table)
### 8.2 The Cost Model as a Function
#### 8.2.1 cost(t, N, mix) parametric model, quarterly re-baselining against 5–10×/yr price deflation (resolves Conflict C1); cognition budget as managed SLO (Insight 2)
### 8.3 Storage & Analytics
#### 8.3.1 ~45 GB/day raw events at 10k agents (~0.5–1 TB compressed/sim-year); LLM traces 10× event volume — sample them; hot store ClickHouse, scratch DuckDB
### 8.4 Sharding & Distribution
#### 8.4.1 MMO-style partitioning by economic/social locality; tick-based windowed sync (all record-holders use it); broker spine (MQTT/Redis)

## 9. Validation & Evaluation Harness (~1500 words, 1 table) [ROUND 1]
### 9.1 Why Validation Is a Subsystem, Not a Phase
#### 9.1.1 76-percentage-point butterfly effects from prompt formatting; persona <10% of variance; equifinality risk — continuous re-validation on every model swap (Insight 7)
### 9.2 The Stylized-Fact Test Suite
#### 9.2.1 Macro: Phillips/Okun signs, business-cycle comovement; micro: firm-size Zipf, wealth Pareto, Cont-2001 financial facts; election turnout bounds (table: fact, target, source)
### 9.3 Robustness & Fidelity Audits
#### 9.3.1 Paraphrase audits, TRAILS-style robustness runs, behavioral-Turing spot checks vs human data, claims only at collective-pattern level (Dim02, Dim06)

## 10. Interactive UI Specification (~3000 words, 3 tables) [ROUND 1]
### 10.1 UI Creed: Attention Is the Scarce Resource
#### 10.1.1 Rendering 10k agents is solved (instancing, 1 draw call/100k sprites); watching 10k lives is not — the UI inverts consumption (Insight 8)
### 10.2 View Inventory
#### 10.2.1 God-Map (PixiJS v8 instanced sprites + DOM text overlay; semantic zoom: economic-weather glyphs → individual agents), no 3D in v1 (Dim09)
#### 10.2.2 Agent 360 (RimWorld-style tabbed dossier: persona, memory, inbox, portfolio, relationships, "Why?" history)
#### 10.2.3 Markets Terminal, Company Dashboards, Elections HQ, Courtroom, News Feed (ECharts canvas; Victoria 3 lenses + outliner; FM26 Portal inbox pattern)
### 10.3 The Three Signature Interactions
#### 10.3.1 Story Desk — LLM-curated narrative outliner over the event firehose ("Follow the Story")
#### 10.3.2 Causal Inspector — every number/claim hyperlinks into replayable event-log moments (validate before linkifying — Chirper lesson)
#### 10.3.3 Time Machine — global transport bar time-locking every view; fork-timeline what-if branching (Insight 3)
### 10.4 Front-End Architecture
#### 10.4.1 Next.js + Zustand transient lanes (render 60fps / UI 1–10Hz / IndexedDB archive); SSE for spectator, WebSocket for intervention; delta-push from the event-sourced core (table: layer, tech, rationale)

## 11. Tech Stack, Roadmap & Risks (~2000 words, 3 tables) [ROUND 2]
### 11.1 Recommended Tech Stack
#### 11.1.1 Sim core: Python 3.12, Ray, asyncio, Postgres(+Timescale/pgvector), Redis/MQTT, vLLM, XGrammar; front end: Next.js, PixiJS, ECharts, Zustand; ops: Temporal, Langfuse, ClickHouse (table: layer, choice, why)
### 11.2 Phased Roadmap
#### 11.2.1 M0–M3 milestones with exit criteria: M0 kernel+ledger (200 agents, golden-run replay), M1 economy+news UI demo, M2 institutions (elections+courts), M3 10k scale + validation gate (table)
### 11.3 Risk Register
#### 11.3.1 Cost blowout, degenerate equilibria/death spirals, LLM fragility (prompt sensitivity), validation boundedness (C5/C6), scope creep — each with likelihood/impact/mitigation (table)

# References
## worldsim_dim01.md – worldsim_dim10.md
- **Type**: Research dimension files
- **Description**: 10 deep-research briefs (ABM frameworks, LLM societies, econ sims, firm lifecycle, harness, cognition, institutions, scaling, UI, comms)
- **Path**: /mnt/agents/output/research/
## worldsim_cross_verification.md
- **Type**: Cross-verification
- **Description**: Confidence tiers + conflict zones C1–C6
- **Path**: /mnt/agents/output/research/worldsim_cross_verification.md
## worldsim_insight.md
- **Type**: Insight synthesis
- **Description**: 8 cross-dimension insights
- **Path**: /mnt/agents/output/research/worldsim_insight.md
