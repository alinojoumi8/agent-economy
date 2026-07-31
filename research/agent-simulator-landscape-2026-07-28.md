# Agent Simulator Landscape — Deep Research

**Research date:** 2026-07-28
**Subject:** Agent Economy / World OS
**Scope:** open-source, academic, benchmark, commercial, and conventional agent-based simulators that overlap with an LLM-driven institutional economy.

## Executive conclusion

There is no single project I found that duplicates Agent Economy's complete combination of:

1. persona-driven LLM cognition;
2. a deterministic, semantics-versioned world kernel;
3. conserved integer-cent double-entry settlement;
4. banks, firms, labor, goods, credit, equity, legal, political, media, regional, and lifecycle systems;
5. private information boundaries;
6. typed observation → belief → decision → action → settlement provenance;
7. exact offline replay from recorded model outputs;
8. forkable, paired-seed counterfactual experiments; and
9. a gateway through which external black-box agents can inhabit the same world.

The closest projects each overlap with only one slice:

- **AgentSociety / AgentSociety 2** — closest broad LLM social-simulation platform and research workflow.
- **EconAgent** — closest academic LLM macroeconomic simulation.
- **CoffeeBench** — closest recent long-horizon, multi-firm LLM economy benchmark.
- **Foundation / The AI Economist** — closest programmable policy-and-economy environment.
- **Magentic Marketplace** — closest external-agent market testbed.
- **Concordia** — closest general architecture for componentized generative agents plus an environment adjudicator.
- **OASIS** — closest massive-scale social-information simulator.
- **Smallville / AI Town** — closest legible, animated, persistent social-world product surface.
- **ABIDES** — closest high-fidelity deterministic market microstructure simulator.
- **OrgForge-IT** — closest independent example of the same “LLMs generate cognition/prose; deterministic engine owns factual truth” boundary.

The market is therefore not one homogeneous competitor set. It contains at least eight different product categories that are often incorrectly compared as if they were the same thing.

## What Agent Economy actually is

Based on the local repository, Agent Economy is best described as a **causal institutional world simulator** or **agent-world kernel**, not merely a multi-agent framework.

Its operating contract is:

```text
private/access-filtered observation
  → memory and belief update
  → LLM or scripted proposal
  → typed validation
  → deterministic institutional action
  → balanced settlement
  → event/provenance record
  → exact replay and counterfactual comparison
```

Important local evidence:

- `README.md`: living US-style economy, exactly balanced double-entry ledger, 100 cognitive/1,000 hybrid agents, legal-political economy, replay, experiments, Observatory.
- `docs/architecture.md`: one deterministic writer; LLMs cannot mutate balances or institutional state; fixed daily phases; canonical table-hash replay.
- `docs/world-os/PRD.md`: explicit information classes, causal authority types, lifecycle and institutional scope, external-agent gateway.
- `docs/research-guide.md`: paired-seed treatment/control workflow and fail-closed causal evidence.
- `docs/world-os/EXTERNAL-AGENT-GATEWAY.md`: outside agents keep their own models/prompts/credentials and submit only validated world actions.

## The eight simulator categories

### 1. LLM social-world simulators

These optimize for believable persons, memory, dialogue, social interaction, and emergent narrative.

| Project | Type | What it actually simulates | Scale/evidence | Overlap with Agent Economy | Main difference |
|---|---|---|---|---|---|
| [Generative Agents / Smallville](https://arxiv.org/abs/2304.03442) · [code](https://github.com/joonspk-research/generative_agents) | Research prototype | Daily plans, memory retrieval/reflection, movement, conversations in a Sims-like town | 25 agents in the paper; code can save, resume, and fork named simulations | Persona continuity, memory, daily life, visible town | Social behavior is primary; no broad conserved institutional economy or exact state-hash replay contract |
| [AI Town](https://github.com/a16z-infra/ai-town) | Deployable starter kit | AI characters living, moving, chatting, and remembering in a virtual town | Scalable Convex-backed app; not an economic research model | Real-time city UX, shared state, persistence, animation | Product/demo scaffold rather than a causal economic laboratory |
| [Concordia](https://github.com/google-deepmind/concordia) · [paper](https://arxiv.org/abs/2312.03664) | Generative-ABM library | Componentized agents acting in physical/social/digital settings; Game Master resolves the environment | General library with examples, not one canonical world | “Agents propose; environment resolves”; modular cognition | Game-Master resolution can be natural-language/open-ended; Agent Economy requires deterministic domain settlement |
| [AgentSociety](https://arxiv.org/abs/2502.08691) · [code](https://github.com/tsinghua-fib-lab/AgentSociety) | Large-scale social simulator | Urban lives, mobility, economy and social interaction; computational social experiments | Paper reports 10k+ agents and 5M interactions | Broad society, experiments, scale | Less evidence of conserved accounting, typed causal authority, and exact ledger-level replay |
| [AgentSociety 2 architecture](https://agentsociety2.readthedocs.io/en/latest/architecture.html) · [storage](https://agentsociety2.readthedocs.io/en/latest/storage.html) | LLM-native simulation/research platform; current documentation accessed 2026-07-30 | Workspace-bound agents are rebuilt and advanced in batched Ray tasks; environment routing uses a Ray actor | Workspace JSON supports resume; replay is append-only JSONL with a schema catalog and DuckDB reads; legacy SQLite models remain only for compatibility | Modern experiment harness, scalable inference, recovery, and replay-oriented analysis tooling | Ray execution and file-backed replay/storage are complementary, not contradictory. Its replay is experiment/trace oriented; this is not evidence of Agent Economy-style semantics-versioned, table-hash-identical institutional replay |
| [Project Sid](https://arxiv.org/abs/2411.00114) | Many-agent civilization experiment | Minecraft-based role specialization, rules, culture and religion using PIANO orchestration | Paper claims experiments spanning 10 to 1,000+ agents | Civilization framing, roles, norms, large groups | Game-world accomplishments and qualitative emergence rather than a formal economy with auditable accounting |
| [SOTOPIA](https://arxiv.org/abs/2310.11667) · [code](https://github.com/sotopia-lab/sotopia) | Social-intelligence benchmark/environment | Goal-driven social interactions evaluated by models/humans | Primarily bounded social episodes | Agent evaluation, goals, relationship behavior | Not a persistent macro/institutional simulation |

### 2. Massive social-media and information simulators

| Project | Type | What it simulates | Scale/evidence | Relevance | Main difference |
|---|---|---|---|---|---|
| [OASIS](https://arxiv.org/abs/2411.11581) · [code](https://github.com/camel-ai/oasis) | Scalable LLM social-media simulator | Twitter/Reddit-like networks, posts, following, comments, reposts, recommendation systems | Project reports support up to 1M agents and 23 actions | Information diffusion, activation probability, recommendation dynamics, very large populations | Narrow platform ecology; no banks, contracts, labor, conserved economy, or broad lifecycle |
| [ElectionSim](https://arxiv.org/abs/2410.20746) | Population election simulator | LLM-driven voters and election behavior | “Massive population” research setup | Political behavior and calibrated populations | Election vertical rather than persistent institutional world |
| AgentTorch | Large-population differentiable ABM framework | Population-scale social/epidemiological dynamics, often calibrated to data | Designed for large population models | Calibration, vectorized population execution, differentiable parameters | Rules/ML population modeling rather than persistent LLM persons with economic ledgers |

### 3. LLM economic and institutional simulators

These are the closest conceptual comparators.

| Project | What it simulates | LLM role | Economic depth | Replay/rigor | Comparison to Agent Economy |
|---|---|---|---|---|---|
| [EconAgent](https://aclanthology.org/2024.acl-long.829/) · [arXiv](https://arxiv.org/abs/2310.10436) | Heterogeneous agents deciding work and consumption across multiple periods in a macro environment | LLM agents with perception, memory and decision modules | Labor/consumption and macro trends; much narrower institution set | Academic experiments; no public claim of double-entry conservation or exact table-hash replay | Closest academic LLM macro model, but Agent Economy is substantially broader and more mechanically constrained |
| [CoffeeBench](https://arxiv.org/abs/2606.16613) | Six-firm coffee supply chain: 2 farmers, 2 roasters, 2 retailers over 90 days; cash, inventory, pricing, communication and transactions | One evaluated LLM controls a roaster; five fixed reference firms | Strong narrow supply-chain accounting and net-income objective | Code and trajectories released; benchmark framing supports repeatability | Excellent narrow benchmark. Agent Economy is a world; CoffeeBench is a standardized test lane that Agent Economy should emulate |
| [Foundation / The AI Economist](https://github.com/salesforce/ai-economist) · [paper](https://www.science.org/doi/10.1126/sciadv.abk2607) | Agents gather/build/trade while a planner learns tax policy | Multi-agent reinforcement learning, not LLM personas | Explicit production, trade, income, tax and redistribution in a stylized world | Controlled RL environment and experiments | Strong policy-learning benchmark, but small/stylized and not a persistent social/legal/banking system |
| [GovSim](https://arxiv.org/abs/2404.16698) | A society exploits or preserves a common-pool resource | LLM negotiation and strategic action | One resource-governance mechanism | Controlled model comparisons and ablations; paper reports best survival below 54% | Valuable governance stress test, not a general economy |
| [Homo Silicus](https://www.nber.org/papers/w31122) · [arXiv](https://arxiv.org/abs/2301.07543) | LLMs are treated as simulated experimental subjects with endowments, preferences and information | LLM responds in replicated behavioral-economics games | Experimental choices, not a running economy | Compares qualitative patterns with classic experiments | Methodological ancestor, not a simulator platform |
| [OpenLife](https://arxiv.org/abs/2606.31046) | Six persistent autonomous agents in the open internet/economic world with memory, tools, payments and budget metabolism | LLM cognition inside asynchronous memory/perception/evaluation processes | Real budgets/payment as survival pressure; not a closed conserved economy | ~12-week proof of concept; open-world outcomes cannot be exactly replayed | Closest philosophical match to cognition-as-economic-resource and persistent identity |

### 4. Business and market benchmarks for autonomous agents

These test whether an agent can manage money or transact, but they are not societies.

| Project | Environment | Agents | Strength | Limitation relative to Agent Economy |
|---|---|---|---|---|
| [Vending-Bench](https://arxiv.org/abs/2502.15840) | Run a simulated vending machine: inventory, suppliers, pricing, daily fees | One LLM manager | Long horizon (>20M tokens in reported runs), objective profit, exposes “meltdown” failure modes | Passive/stochastic environment rather than interacting institutions |
| [Vending-Bench 2](https://andonlabs.com/evals/vending-bench-2) | Expanded year-long simulated vending business | One LLM manager | Highly legible leaderboard and one economic score | Still a single-agent business benchmark |
| [Project Vend](https://www.anthropic.com/research/project-vend-1) | Claude operated a real office store for about a month | One agent plus humans/tools | Real stakes and memorable failures | Field experiment, not reproducible world simulation |
| [EcoGym](https://arxiv.org/abs/2602.09514) | Unified Vending, Freelance and Operation economies over effectively unbounded horizons | One evaluated LLM per environment | Open-source standardized interfaces, partial observability, stochasticity, 1,000+ steps | Long-horizon plan/execute benchmark, not a multi-institution society |
| [Magentic Marketplace](https://arxiv.org/abs/2510.25779) | Two-sided market of consumer Assistant agents and competing Service agents | Multiple opaque LLM agents | Measures welfare, first-proposal bias, manipulation and search effects | Marketplace vertical rather than an entire economy; highly relevant to Agent Economy’s external-agent venue |
| [TradingAgents](https://arxiv.org/abs/2412.20138) | Multi-role LLM team performs financial analysis and trading | Analyst/trader/risk-manager roles usually cooperate as one system | Useful orchestration and market-decision benchmark | The “agents” are internal roles, not independent citizens with conserved counterparties |
| [FinMem](https://arxiv.org/abs/2311.13743) | Memory-augmented LLM trading agent | One trading agent | Layered memory and market backtesting | Portfolio decision system, not an economy |
| [ABIDES](https://github.com/abides-sim/abides) | High-fidelity discrete-event financial market and order book | Many programmable trading agents | Deterministic event simulation, microstructure, latency, market experiments | Not LLM-native; narrow financial market rather than social/institutional world |

### 5. Governance, diplomacy and strategic-game simulators

Examples include GovSim, WarAgent, SOTOPIA and negotiation/collusion environments. They are useful for adversarial scenario design, but most are bounded games with a small action/state surface. Agent Economy can absorb these as scenario packs rather than replace its kernel.

### 6. Conventional agent-based modeling platforms

These are engines and toolkits, not direct competitors. They provide scheduling, data collection, batch runs, visualization or high-performance execution.

| Platform | Core strength | Scale | LLM-native? | What Agent Economy should borrow |
|---|---|---|---|---|
| [Mesa](https://mesa.readthedocs.io/) | Python ABM primitives, AgentSet, batch runs, data collection, Solara visualization | Small-to-medium general ABMs | No | Batch-analysis ergonomics, parameter sweeps, model data collectors |
| [NetLogo](https://ccl.northwestern.edu/netlogo/) | Accessible model authoring, huge teaching/model library, BehaviorSpace sweeps | Desktop/educational ABMs | No | Scenario authoring simplicity, BehaviorSpace-style experiment UX |
| [MASON](https://cs.gmu.edu/~eclab/projects/mason/) | Fast Java discrete-event multi-agent simulation | Large optimized simulations | No | Scheduler discipline and deterministic execution patterns |
| [Repast Simphony/HPC](https://repast.github.io/) | Java ABM plus high-performance variants | Desktop to HPC | No | Distributed batch execution only where state partitioning is safe |
| [FLAME GPU 2](https://flamegpu.com/) | CUDA/GPU agent simulation | Very large homogeneous/structured populations | No | Peripheral mechanistic population acceleration, not cognitive core execution |
| [GAMA](https://gama-platform.org/) | Spatial/GIS-rich modeling and visual scenario authoring | Large spatial ABMs | No | Spatial institutions, GIS layers, operator scenario tools |
| [AnyLogic](https://www.anylogic.com/) | Commercial hybrid ABM + discrete event + system dynamics | Enterprise simulation | No | Hybrid-model presentation and polished experiment interfaces |
| [Simudyne](https://simudyne.com/) | Enterprise agent simulation platform | Distributed enterprise scenarios | No | Enterprise scenario governance and deployment patterns |
| [AgentPy](https://agentpy.readthedocs.io/) | Lightweight Python ABM and experiment analysis | Small-to-medium | No | Clean parameter sampling and experiment APIs |
| [SimPy](https://simpy.readthedocs.io/) | Process-oriented discrete-event queues/resources | Efficient process simulations | No | Local queue/capacity modules, not the authoritative world clock |
| [PettingZoo](https://pettingzoo.farama.org/) | Standard APIs for multi-agent reinforcement-learning environments | Depends on environment | No | An adapter exposing Agent Economy scenarios to trained policies/benchmarks |
| [Econ-ARK/HARK](https://github.com/econ-ark/HARK) | Heterogeneous-agent structural economic models | Econometric/modeling workloads | No | Calibration discipline, distributions, lifecycle economics, model validation |
| JAS-mine / EURACE / MacroABM families | Rich conventional macro/financial ABMs | Often thousands to millions of rule-based agents | No | Stylized facts, calibration targets, bank/firm/household mechanisms |

**Build-versus-buy judgment:** none should replace Agent Economy’s kernel. The local `docs/world-os/FRAMEWORK-RESEARCH.md` conclusion is correct: adopt analysis, transport, visualization and experiment ideas around the edges; retain one authoritative deterministic world writer.

### 7. Commercial synthetic-population and “world model” products

These are commercial alternatives for market/policy questions, but their public evidence is mostly product claims. They should not be treated as technically verified equivalents.

| Company/product | Public positioning | Likely buyer/use | What is publicly unclear |
|---|---|---|---|
| [Simile](https://www.simile.com/) | “Simulation platform for human behavior” | Research, customer/policy behavior simulation | Internal mechanics, accounting, exact replay, causal identification and external validity details |
| [Aaru](https://aaru.com/) | Behavior simulation at real-world scale; predicts measurable outcomes/actions | Market research, campaigns, strategy | Proprietary calibration, error bounds, agent/world mechanics, reproducibility |
| [CulturePulse](https://www.culturepulse.ai/) | AI-driven insights for complex decisions | Social/policy/organizational analysis | Whether agents are persistent, what is calibrated, and how outcomes are validated |
| [Epistemix](https://epistemix.com/) | Person-by-person product-adoption “world model” | Adoption, epidemiology-inspired diffusion and market strategy | Not LLM-native; closed model and validation details vary by engagement |
| [Replica](https://replicahq.com/) | Built-environment and mobility data for transportation decisions | Cities, transportation and planning | More a calibrated mobility/data product than an autonomous generative society |
| [Simudyne](https://simudyne.com/) | Enterprise simulation software | Financial services and strategic scenario testing | Closed implementation and limited public evidence of LLM-native cognition |
| [AnyLogic](https://www.anylogic.com/) | General commercial simulation platform | Supply chain, logistics, operations, policy | Requires the customer to build domain logic; not a ready-made agent society |

### 8. Deterministic synthetic-data worlds

[OrgForge-IT](https://arxiv.org/abs/2603.22499) is not an economy, but it is architecturally important. It uses a deterministic simulation engine to maintain factual ground truth while LLMs generate surface prose. That is independently convergent evidence for Agent Economy’s “physics/cognition boundary.” Agent Economy applies the same idea to money, institutions, private information, and causal settlement rather than only synthetic security telemetry.

## Normalized feature comparison

Legend: **Yes** = explicit public evidence; **Partial** = some support but not the full property; **No/unclear** = absent or not established publicly.

| System | Persistent persons | LLM-native | Broad institutions | Hard economic settlement | Private information model | Exact deterministic replay | Counterfactual experiment harness | Large population |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **Agent Economy** | Yes | Yes | Yes | **Yes, double-entry** | **Yes** | **Yes, canonical hashes** | **Yes, paired seeds/forks** | Yes, 1,000 hybrid |
| AgentSociety 1 | Yes | Yes | Partial | Unclear | Partial | Unclear | Yes | **Yes, 10k+ reported** |
| AgentSociety 2 | Yes/record-based | Yes | Framework-dependent | No/unclear | Framework-dependent | Partial: trace/catalog replay | Yes | Yes, Ray tasks |
| Smallville | Yes | Yes | No | No | Partial/social memory | Partial save/resume | Partial fork | No, 25 in paper |
| Concordia | Yes | Yes | Scenario-dependent | Usually GM-adjudicated | Scenario-dependent | Unclear | Yes | Small/medium |
| OASIS | Profile persistence | Yes | Social-platform only | No | Platform/feed model | Database persistence; exact replay unclear | Yes | **Up to 1M claimed** |
| Project Sid | Yes | Yes | Norms/roles in Minecraft | Game mechanics | Social/game context | Unclear | Research runs | 10–1,000+ claimed |
| EconAgent | Yes/multi-period | Yes | Narrow macro | Structured but no double-entry proof | Partial | Unclear | Academic comparisons | Unclear |
| CoffeeBench | Firm persistence | Yes | Supply chain only | Cash/inventory bookkeeping | Partial observability/communications | Benchmark repeatability; exact replay unclear | **Yes** | No, six firms |
| AI Economist | Episode persistence | No, RL | Tax/planner + simple market | Formal game mechanics | State observations | Seeded RL environment | Yes | No, stylized small world |
| Magentic Marketplace | During runs | Yes | Marketplace only | Utility/transactions | Opaque counterparties | Experimental repeatability | **Yes** | Variable |
| OpenLife | **Yes, weeks** | Yes | Open internet/process society | Real budgets but not conserved closed-world ledger | Agent memory/process boundaries | No | Limited | No, six agents |
| ABIDES | Strategy state | No | Financial market only | **Yes, order-book mechanics** | Market observations | Strong deterministic simulation | Yes | Large market-agent sets |
| Mesa/NetLogo/etc. | Model-defined | No | Model-defined | Model-defined | Model-defined | Seed/model-defined | **Yes** | Framework-dependent |

## What is genuinely differentiated

### 1. The differentiator is the combination, not “LLM agents”

LLM personas, town maps, social dialogue, and memory are now common. None is a moat alone. Agent Economy’s defensible combination is **bounded cognition plus mechanically authoritative institutions plus a scientific audit trail**.

### 2. Conserved money is a major dividing line

Many projects have a numeric balance or profit score. That is not the same as an economy in which every monetary effect posts balanced legs and a tick halts on reconciliation failure. Agent Economy should state this distinction explicitly:

> A score can be incremented. Conserved money must come from somewhere, go somewhere, and reconcile.

CoffeeBench, Vending-Bench and AI Economist offer verifiable economic objectives, but their domains are narrow. Agent Economy’s opportunity is to become the broad test environment where money, ownership, contracts, credit and institutional authority remain coherent simultaneously.

### 3. Exact replay is unusually strong

Most projects mean one of four different things by “replay”:

1. replay a UI/event log;
2. rerun with the same seed;
3. reuse a stored trajectory/model response;
4. reconstruct the world and prove canonical state equality.

Agent Economy implements the fourth and strongest meaning. Marketing should never use the unqualified word “replay”; say **offline state reconstruction with canonical table-hash equality**.

### 4. Causal provenance is more valuable than spectacle

The critical-review literature argues that generative ABMs often rely on subjective believability and fail to establish operational validity ([review](https://arxiv.org/abs/2504.03274)). The 2026 coupling-gain paper shows that apparent consensus can be a model prior rather than genuine social coupling ([paper](https://arxiv.org/abs/2606.22203)). Agent Economy is unusually well designed to answer this criticism because it separates exposure, belief, proposal, validation and settlement and can fork a checkpoint for perturbation tests.

### 5. External black-box agents create a venue, not just a demo

Magentic Marketplace and CoffeeBench show demand for standardized economic environments. Agent Economy’s external-agent gateway can go further: a third party can retain its model, prompt, memory and credentials while the world owns identity, turn order, receipts and effects. This makes Agent Economy plausible as a neutral regression/adversarial test venue.

## What to borrow, project by project

1. **CoffeeBench:** fixed reference counterparties, a standardized role under test, trajectories, one clear economic score, and model-swapping experiments.
2. **Magentic Marketplace:** consumer/service role packs, search-policy variants, response-speed bias tests, prompt-injection and payment-redirection scenarios.
3. **AgentSociety 2:** stateless/idempotent inference dispatch, JSONL/Parquet/DuckDB research catalogs, distributed traces, experiment templates.
4. **OASIS:** salience/activation probability so only a fraction of the population calls an LLM each tick; recommendation and exposure-policy modules.
5. **Concordia:** componentized persona/cognition recipes and reusable scenario prefabs—without giving its Game Master authority over money or law.
6. **Smallville / AI Town:** visible routines, spatial navigation, client-side interpolation, story-legible event presentation.
7. **OpenLife:** budget-as-metabolism, asynchronous “sleep” consolidation, agent-authored identity distillates, measured persona separability.
8. **Mesa / NetLogo / AgentPy:** parameter sweeps, batch runners, experiment manifests, model-data collectors and easy scenario authoring.
9. **HARK / macro-ABMs:** empirical calibration targets, lifecycle distributions, stylized-fact checks and sensitivity analysis.
10. **PettingZoo:** an optional adapter that exposes bounded Agent Economy scenarios as a standard multi-agent environment.
11. **FLAME GPU / AgentTorch:** only for a future mechanistic periphery if profiling proves CPU population updates are the bottleneck; never for authoritative LLM world mutation.
12. **Vending-Bench 2:** leaderboard legibility. A complex world still needs one or two simple outcome numbers per scenario.

## Recommended competitive position

Do **not** position it as:

- another AI Town;
- an orchestration framework;
- a synthetic focus group;
- a macroeconomic forecast;
- a generic ABM toolkit; or
- “the largest” agent simulation.

Position it as:

> **A replayable institutional world for testing how autonomous agents behave when money is conserved, information is private, institutions have rules, and every consequence has a receipt.**

A sharper technical version:

> **Agent Economy is a deterministic world kernel for LLM agents: models propose; typed institutions validate; double-entry ledgers settle; canonical replay proves what happened.**

## Best near-term product lanes

### Lane A — public flagship world

Use Smallville/AI Town product legibility, but make the content uniquely Agent Economy: private communication, cognitive scarcity, bank runs, lawsuits, elections, bankruptcies and post-hoc causal receipts.

### Lane B — third-party agent testing venue

Turn CoffeeBench/Magentic Marketplace-style tasks into scenario packs:

- purchasing agent vs manipulative sellers;
- duplicate order and runaway-spend attacks;
- colluding counterparties;
- insider information and trade timing;
- credit negotiation and misrepresentation;
- refund/chargeback/dispute failures;
- delegated authority and approval-limit violations.

The client’s agent connects through the existing gateway. Scoring comes from ledger truth, contract state, policy violations and replayable receipts.

### Lane C — research instrument

Publish experiments that exploit features competitors lack:

- same city and seed, different model family;
- rumor vs no-rumor checkpoint fork;
- measured coupling gain and bias;
- salience scheduler ablation;
- public vs private communication treatment;
- rich vs poor compute subscription treatment;
- causal-edge precision audit against engine authority.

## Highest-priority competitive builds

1. **A real-provider run with transcript review.** Mechanical correctness is established far more strongly than behavioral quality.
2. **A standardized scenario/benchmark layer.** Make one external agent replaceable while reference counterparties and seed remain fixed.
3. **Parquet/DuckDB research exports and batch comparison UI.** This is table stakes against AgentSociety 2 and classic ABM workflows.
4. **Salience-driven activation.** OASIS-style sparse cognition is the main scale/cost lever.
5. **A legible city renderer.** Borrow AI Town’s presentation, not its authority model.
6. **Sensitivity and emergence diagnostics.** Directly answer the strongest methodological criticism of generative ABMs.
7. **A PettingZoo-compatible adapter.** This opens the world to policy/RL agents without changing the kernel.
8. **A concise evidence page.** Separate implemented, tested, live-provider-validated and proposed capabilities.

## Bottom line

Agent Economy is not behind because it lacks a fashionable framework. It is ahead on world integrity and behind on behavioral validation, standardized external-agent evaluation, and public legibility.

The competitive threat is not that AgentSociety, OASIS or AI Town will suddenly grow an exact institutional ledger. The threat is that narrower benchmarks such as CoffeeBench and Magentic Marketplace become the standard interfaces through which the field evaluates economic agents. Agent Economy should therefore keep its kernel, expose smaller standardized test lanes, and use the broader living city as the differentiating venue around those lanes.

## Primary source index

### Local project

- `README.md`
- `PRODUCT.md`
- `docs/architecture.md`
- `docs/research-guide.md`
- `docs/world-os/PRD.md`
- `docs/world-os/FRAMEWORK-RESEARCH.md`
- `docs/world-os/EXTERNAL-AGENT-GATEWAY.md`

### Academic and open source

- AgentSociety: https://arxiv.org/abs/2502.08691 and https://github.com/tsinghua-fib-lab/AgentSociety
- AgentSociety 2 architecture and storage (accessed 2026-07-30): https://agentsociety2.readthedocs.io/en/latest/architecture.html and https://agentsociety2.readthedocs.io/en/latest/storage.html
- Generative Agents: https://arxiv.org/abs/2304.03442
- Concordia: https://arxiv.org/abs/2312.03664 and https://github.com/google-deepmind/concordia
- OASIS: https://arxiv.org/abs/2411.11581 and https://github.com/camel-ai/oasis
- Project Sid: https://arxiv.org/abs/2411.00114
- SOTOPIA: https://arxiv.org/abs/2310.11667
- EconAgent: https://aclanthology.org/2024.acl-long.829/
- Homo Silicus: https://www.nber.org/papers/w31122
- GovSim: https://arxiv.org/abs/2404.16698
- OpenLife: https://arxiv.org/abs/2606.31046
- CoffeeBench: https://arxiv.org/abs/2606.16613
- Vending-Bench: https://arxiv.org/abs/2502.15840
- EcoGym: https://arxiv.org/abs/2602.09514
- Magentic Marketplace: https://arxiv.org/abs/2510.25779
- AI Economist: https://www.science.org/doi/10.1126/sciadv.abk2607
- ABIDES: https://github.com/abides-sim/abides
- OrgForge-IT: https://arxiv.org/abs/2603.22499
- Critical review of generative ABMs: https://arxiv.org/abs/2504.03274
- Coupling-gain/emergence diagnostic: https://arxiv.org/abs/2606.22203
