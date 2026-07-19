# 1. Executive Summary & Vision

POLIS is a persistent macroeconomy world simulator: a digital society in which large language model (LLM) agents are born, work, found companies, raise venture capital, trade on an exchange, go bankrupt, sue one another, read news written by AI news agencies, vote in elections, and die — each with its own persona, memory, and ledger-backed balance sheet. This document is the product requirements and technical specification for building it. Its thesis: the science is done and the engineering is not. Every mechanic POLIS requires has at least one validated research precedent, so the differentiator is disciplined integration on an event-sourced kernel — not novel agent techniques. *Citation note: `[^N^]` indices follow the source research reports (Dim02/03/05/06/07/10).*

## 1.1 Vision

### 1.1.1 A persistent digital society

The world runs whether or not anyone is watching. Time advances in ticks; agents perceive, decide, converse, and act; institutions clear markets, try cases, publish newspapers, and count votes; and every fact produced along the way is appended to an immutable event log. The user does not play a character. The user observes a civilization — and intervenes on its conditions, never its script. Professions are real specializations with distinct action spaces: lawyers file suits, journalists work the newsroom, teachers raise population skill, politicians campaign and govern.

The governing principle is **emergence over scripting**. A POLIS scenario specifies initial conditions — population composition, seed capital, legal parameters, shock events — and never specifies plot. The product's value lies in phenomena the builder did not write: a rumor that becomes a bank run, a campaign promise that becomes a tax schedule, a supply shock that becomes an election upset. Such drama is worth watching only if the underlying state is real: a bankrupt firm's creditors actually lose money, an elected mayor's tax rule actually changes ledger postings. POLIS's founding bet is that *earned* narrative — stories backed by quadruple-entry accounting — is what separates a world simulator from a storytelling toy.

### 1.1.2 Core design creed

Four creeds govern every design decision in this document. They are stated here as rules; Chapters 3–11 restate them as enforceable mechanisms and acceptance criteria.

**Table 1-1 — POLIS design creeds and their mechanical consequences.**

| Creed | Rule | Mechanical consequence |
|---|---|---|
| Physics-first, cognition-second | A deterministic kernel owns all state; LLMs only choose actions | No arithmetic hallucination; full replay; macro regularities emerge from interaction with a rigid engine [^200^][^77^] |
| The event log is the product | One append-only stream with provenance, causality links, and visibility ACLs | Agent memory, the newsroom, replay, causal inspection, and legal discovery are all views over a single structure |
| Institutions are reducers, not agents | Markets, courts, elections, and the central bank are deterministic state machines | Fairness-critical paths stay auditable; LLMs participate in institutions but never adjudicate them |
| Scale where nobody looks | Cognition is tiered — Hero, Named, Background | Full frontier-model depth is spent only on the ~1–2% of agents anyone ever inspects |

These creeds are load-bearing, not decorative. The first inverts the naive design in which the agent *is* the LLM: persona prompting alone explains less than 10% of behavioral variance in controlled studies [^10^], so POLIS treats cognition as a stateless decision service behind kernel-owned state. The third creed defines the architectural seam of the entire system — *agents propose, institutions dispose* — placing non-determinism where it is entertaining (litigants, candidates, CEOs, columnists) and determinism where fairness is judged (clearing prices, counting votes, apportioning damages). The fourth makes the other three affordable, as Section 1.2.2 quantifies. Together they convert an LLM society from a demo into an operable product: replayable, auditable, and priced.

## 1.2 What the Research Proved

### 1.2.1 Every mechanic has a validated precedent

The research phase surveyed ten dimensions — frameworks, existing societies, macroeconomic modeling, firm demography, runtime architecture, agent cognition, politics and media, scale economics, observability interfaces, and communication fabric — across more than 330 searches, then cross-verified every load-bearing claim. The central result: no mechanic in POLIS is unproven, and no existing system integrates them.

The precedent chain, mechanic by mechanic:

- **Believable agents with persistent memory.** Generative Agents ran 25 agents for two game days, during which awareness of a mayoral candidacy spread unscripted from 4% to 22% of agents and party awareness from 4% to 52% [^355^].
- **LLM-driven macroeconomy.** EconAgent reproduced the Phillips curve (Pearson correlation −0.619) and Okun's law (−0.918) with correct signs, where rule-based and reinforcement-learning baselines produced unstable or wrong-signed relationships [^200^][^77^].
- **Society at scale.** AgentSociety sustained over 10,000 agents and roughly 5 million interactions [^246^]; OASIS scaled to one million agents [^28^], with herd effects intensifying as populations grow past 10,000 — scale is a scientific requirement, not vanity [^669^].
- **Elections.** ElectionSim matched 47 of 51 US state-level results for 2020 and 86.7% of swing states for 2024 [^19^][^22^].
- **News-coupled markets.** TwinMarket demonstrated that the coupling is causal: removing the social-information layer significantly degrades market realism [^1461^], and bubbles, crashes, and volatility clustering emerged only inside a deterministic exchange [^4^].
- **Affordable population.** AgentTorch covered 8.4 million agents by querying the LLM per archetype group rather than per individual [^449^].

The strategic conclusion is that **integration is the risk, not novelty**. Every major LLM-agent society of 2023–2026 — Concordia, AgentSociety, OASIS, Project Sid, EconAgent — built a bespoke kernel rather than adopting an existing framework (cross-verification Tier-1 finding; Chapter 5). The honest caveats are equally instructive: persona prompting contributes under 10% of behavioral variance [^10^], and LLM societies are fragile to prompt formatting and model swaps — so POLIS ships validation as a continuously running subsystem with pass/fail gates, not as a pre-launch phase (Chapter 9).

### 1.2.2 Tiered cognition makes it affordable

The second research result is economic. Running every decision for 10,000 agents on a frontier model costs roughly $16,000 per simulated day. Routing the same population through tiered cognition — rules for routine ticks, cheap models for ordinary decisions, frontier models reserved for salient moments, reflection batched nightly, shared prompt prefixes cached — lands near $73 per simulated day for a light API-first workload: a ~220× reduction (Chapter 8 develops both figures as planning estimates with stated assumptions). The two-orders-of-magnitude gap is produced entirely by *when* and *which* agents think — **cost is a scheduling problem, not a model problem**. External anchors bracket the plan: OASIS served one million agents on 24–27 A100 GPUs [^6^][^7^]; AgentTorch's Large Population Models ran 8.4 million agents through 90 steps for a reported $500. Because API prices deflate 5–10× per year [^27^], POLIS specifies its cost model as a parametric function re-baselined quarterly — a design decision that converts the research's one unresolved price conflict into routine operations.

## 1.3 The Build

### 1.3.1 The build in miniature

Chapter 5's verdict: build a thin custom kernel, borrow the cognitive patterns. POLIS owns an event-sourced kernel (Postgres-first) holding every fact of the world, and a Cognition Scheduler deciding which agents think, at which tier, each tick (Chapter 4). Onto that kernel it bolts the best-documented patterns in the literature: Concordia's game-master/component separation, OASIS's and AgentSociety's activation scheduling, Generative Agents' memory stream. Agents come in three classes — Hero (~1–2%, full frontier cognition), Named (~15%, cheap models), Background (~85%, rules and archetypes) — with promotion and demotion themselves emitted as world events (Chapter 3). The economy is a stock-flow-consistent quadruple-entry ledger with a limit-order-book exchange, an eight-state firm lifecycle, a venture-capital power-law ladder, and dual-track bankruptcy (Chapter 6); society runs on email, direct-message, feed, and newswire channels, a seven-stage newsroom, election and court state machines, and a machine-readable law registry (Chapter 7).

Delivery is phased to retire integration risk early: Phase 1 proves 50–200 agents with economy, companies, news, and market; Phase 2 adds lifecycle, elections, and litigation; Phase 3 deepens venture capital and scales to 10,000 agents (Chapter 2). The interface treats attention as the scarce resource: a god view in which a Story Desk curates the event firehose into followable narratives, a Causal Inspector answers any "why?" with replayable event chains, and a Semantic-Zoom Map travels from economic weather down to individual agents (Chapter 10). Every release is gated by stylized-fact tests — Phillips and Okun signs, Zipf firm-size tails, firm-exit hazards (Chapter 9) — on a Python 3.12/Ray/Postgres/vLLM stack with a Next.js/PixiJS front end (Chapter 11). What no surveyed system has built, and what the research flags as the largest differentiation opportunity, is the unity underneath: one event log powering agent memory, the newsroom, the time-machine interface, causal inspection, counterfactual branching, and in-world legal discovery at once. POLIS is that unity, productized.
