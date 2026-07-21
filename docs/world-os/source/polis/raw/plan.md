# Plan — World Sim: Macroeconomy Agent Society Simulator (PRD + Specs)

## Goal
Deliver a detailed PRD + Technical Specification for a large-scale agent-based macroeconomy world simulator
(LLM-driven agents: born/die, found companies, trade, invest, litigate, vote, email, consume news),
including: deep research on frameworks (existing vs build-from-scratch harness), and a solid interactive UI concept.

## Stage 1 — Deep Research (skill: deep-research-swarm, Route B: focused multi-dimensional)
Parallel research agents (each returns a validated research brief with sources):
1. **Agent-Based Modeling frameworks**: Mesa, Agents.jl, Repast, MASON, NetLogo — suitability for macro-scale, Python/TS ecosystems.
2. **LLM agent societies / sandboxes**: Generative Agents (Stanford Smallville), Concordia (DeepMind), OASIS, AgentSociety, MetaGPT, CAMEL — architectures, memory, scheduling, scalability lessons.
3. **Economic & financial simulators**: Salesforce AI Economist, EconAgent, MACRO/Bank/JPMorgan ABMs (EURACE, Mark-0, CRISIS), stock market sims, Sugarscape; macro ABM literature (SFC stock-flow consistent models).
4. **Simulation harness engineering**: event-driven vs tick-based schedulers, ECS architecture, LLM call batching/caching, cost control, persistence (Postgres/event sourcing), determinism/replays, scaling to 10k+ agents.
5. **Interactive UI for living-world sims**: Generative Agents replay UI, OASIS social feeds, god-view maps (deck.gl/MapLibre), dashboards (Recharts/ECharts), 3D world (Three.js/R3F), time controls, agent inspector patterns.

Orchestrator cross-validates and merges into a single research brief.

## Stage 2 — Writing (skill: report-writing)
Read SKILL.md + style. Feed Stage 1 brief. Produce `.agent.final.md` containing:
- Executive summary & vision
- Product Requirements: personas, user stories, functional/non-functional requirements, MVP vs full roadmap
- System architecture: world engine, agent cognition loop, economy/market engine, institutions (gov/courts/press/banks/VC), comms layer (email/news), lifecycle (birth/death), politics/elections, law/litigation
- Data model, event sourcing, persistence
- Framework decision: adopt vs build custom harness (with tradeoff matrix) — recommendation
- Scalability, cost engineering (LLM budgets, caching, tiered cognition), determinism & replay
- Interactive UI spec: god view, agent 360, company/market dashboards, news feed, elections, courtroom, time machine
- Tech stack, milestones, risks

## Stage 3 — Artifact (skill: docx)
Convert final markdown → formatted .docx in /mnt/agents/output/. Deliver .md + .docx.
