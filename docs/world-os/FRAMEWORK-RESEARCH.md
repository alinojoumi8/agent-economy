# World OS framework research and build-versus-buy decision

**Research date:** 2026-07-18<br>
**Status:** Approved architecture input for Semantics 8<br>
**Scope:** Agent Economy to World OS expansion

## Decision

Extend the existing deterministic Agent Economy kernel. Do not replace it with a
general-purpose agent framework.

The project already owns the difficult and differentiating parts: conserved money,
contracts, firms, banks, markets, lifecycle, phase-aware checkpoints, stored-model
replay, information boundaries, experiments, and a hosted single-writer control
plane. A framework migration would retain generic scheduling and prompting while
forcing the project to rebuild those guarantees inside somebody else's lifecycle.

The stack therefore follows one rule:

> Build the world semantics. Buy or adopt the contracts, testing, analytics,
> transport, and visualization machinery around them.

## Simulation framework evaluation

| Candidate | What it is good at | Fit for this project | Decision |
|---|---|---|---|
| Existing Agent Economy kernel | Deterministic phases, double-entry settlement, domain contracts, exact replay, checkpoint forks | It already implements the load-bearing world semantics and has regression evidence | **Use as the authoritative kernel** |
| [Mesa](https://mesa.readthedocs.io/stable/) | Python ABM primitives, `AgentSet`, data collection, batch runs, and Solara visualization | Its analysis patterns are useful, but replacing the kernel would duplicate existing scheduling, persistence, metrics, and UI. Solara would also split the maintained React surface. | Borrow batch-analysis ideas; do not adopt as the runtime |
| [AgentSociety 2](https://agentsociety.readthedocs.io/en/latest/) | LLM-native social agents, modular environments, research workflows, Ray-based scaling, and replay-oriented tooling | Useful reference for experiment workflows and stateless scale-out. Its official material emphasizes social and urban simulation rather than a conserved financial ledger. Replacing the kernel would still require rebuilding Agent Economy's accounting and compatibility rules. This fit assessment is an inference from the documented architecture. | Borrow experiment and worker-dispatch patterns; do not use as the base |
| [Concordia](https://github.com/google-deepmind/concordia) | Componentized generative agents and a Game Master that resolves natural-language actions | The entity/component decomposition is valuable for persona cognition. Game-Master outcome resolution is too open-ended for money, ownership, legal status, and replay-sensitive settlement. | Borrow component ideas; keep deterministic domain resolution |
| [SimPy](https://simpy.readthedocs.io/en/stable/index.html) | Process-oriented discrete-event simulation using Python generators | Good for queues and resource contention. The existing world uses a semantics-versioned daily phase machine with resumable boundaries; a generator-process migration would add a second time model. | Reject for the world clock |
| [PettingZoo](https://pettingzoo.farama.org/) | Standard sequential and parallel APIs for multi-agent reinforcement-learning environments | Useful if the product later exposes a benchmark environment for trained policies. It does not supply persistent institutions, private knowledge, accounting, or human-readable causal provenance. | Optional future adapter, not a foundation |
| [Ray actors/tasks](https://docs.ray.io/en/latest/ray-core/actors.html) | Multi-process and multi-node execution with explicit retry and actor lifecycle controls | Ray's retry modes can execute work more than once and actor state requires application-level checkpointing. That is unsafe for world mutation but suitable for idempotent inference requests whose results are ordered and committed by the local kernel. | Add only behind the stateless inference-dispatch seam after profiling |

### What this comparison changes

AgentSociety 2 is now an active option and should no longer be described simply as an
abandoned economy framework. It remains the wrong kernel for this repository, but its
current Ray tasks, research-workflow, and replay patterns deserve periodic comparison.
The rejection is about domain fit and migration cost, not project quality.

## Adopted implementation stack

| Concern | Choice | Reason |
|---|---|---|
| Typed agent commands | [Pydantic discriminated unions](https://pydantic.dev/docs/validation/latest/concepts/unions/) | The `type` field selects one predictable validator, produces useful errors, and maps cleanly to the existing dictionary wire format. |
| API and live transport | Existing [FastAPI REST plus WebSockets](https://fastapi.tiangolo.com/advanced/websockets/) | Reuses the hosted/local API and authentication boundaries. REST bootstraps and backfills; WebSockets carry bounded deltas and invalidations. |
| Authoritative world state | Existing SQLite in WAL mode | One writer preserves ordering. WAL lets dashboard readers continue while the kernel commits, as documented by [SQLite](https://www3.sqlite.org/wal.html). |
| Hosted workspace state | Existing PostgreSQL control plane | Tenant-scoped investigations and audit records fit the current control plane. PostgreSQL RLS defaults to denial when enabled without an applicable policy, subject to owner and bypass-role caveats described in the [official RLS documentation](https://www.postgresql.org/docs/17/ddl-rowsecurity.html). |
| Research exports | Parquet plus embedded DuckDB | DuckDB reads and writes Parquet and performs filter/projection pushdown, making cross-run analysis fast without changing replay truth. See the [DuckDB Parquet guide](https://duckdb.org/docs/lts/data/parquet/overview). |
| Model-based backend tests | [Hypothesis `RuleBasedStateMachine`](https://hypothesis.readthedocs.io/en/latest/stateful.html) | Stateful generation can explore send/deliver/read/reply, membership, death, pause, resume, and replay sequences against a small reference model. |
| Browser workflows | [Playwright](https://playwright.dev/docs/trace-viewer-intro) | Covers reconnects, cursor gaps, role visibility, keyboard paths, responsive layouts, and captures traces on first retry. |
| Shareable navigation | [React Router URL values](https://reactrouter.com/start/declarative/url-values) | Run, fork, tick, event, entity, filters, and workspace become reloadable and shareable URLs. |
| Server-state cache | [TanStack Query](https://tanstack.com/query/latest/docs/framework/react/guides/query-invalidation) | Owns REST caching, deduplication, stale state, and targeted invalidation instead of expanding the current hand-written fetch fan-out. |
| API type generation | [openapi-typescript](https://openapi-ts.dev/introduction) | Generates runtime-free TypeScript types from the committed FastAPI schema and supports discriminators. CI can reject schema drift. |
| Synthetic world view after the first causal gate | [deck.gl `OrthographicView`](https://deck.gl/docs/api-reference/core/orthographic-view) | Renders a top-down non-geospatial world with layered agents, organizations, movement, capital, trade, and information flow without a tile provider. |
| Relationship graphs | [Sigma.js](https://www.sigmajs.org/docs/advanced/data/) plus [Graphology](https://graphology.github.io/standard-library/) | Sigma supplies WebGL rendering; Graphology supplies layouts, traversal, paths, components, and graph metrics. |
| Metric charts | Existing Recharts | Already shipped and sufficient for synchronized time-series views. Its chart API includes an accessibility layer, but each visualization still needs an equivalent semantic table. |
| Provenance vocabulary | Small project-owned relation set informed by [W3C PROV-O](https://www.w3.org/TR/prov-o/) | W3C PROV validates the distinction between entities, activities, agents, derivation, quotation, and influence. The product needs a smaller SQLite-native vocabulary, not an RDF store. |

## Components to build in this repository

These are domain contracts, not commodity infrastructure:

1. A semantics-versioned typed command registry behind `ActionExecutor.execute_action()`.
2. Private asynchronous communication with materialized access grants and exact-once delivery.
3. Agent-visible knowledge projections distinct from operator ground truth.
4. Authoritative and inferred causal/provenance links with explicit relation types.
5. Deterministic phase specifications and phase-boundary fault injection.
6. Rebuildable read projections with tick, projection version, and event cursor.
7. A causal investigation workflow that joins messages, memories, beliefs, decisions,
   events, contracts, and ledger transactions without confusing correlation with cause.
8. Education, household/housing, and services/career domain modules in later semantic lakes.

## Components not to build

- A second agent orchestration framework.
- A message broker between in-process world phases.
- A graph database for causal links at the planned scale.
- A distributed authoritative kernel.
- A custom browser router, server-state cache, graph renderer, map renderer, chart
  library, property-testing engine, or browser-testing engine.
- A second source of API types maintained by hand.
- Embedded Hermes, OpenClaw/Moltbot, OpenMolt, or arbitrary owner code inside the hosted
  process. These remain remote clients of the shared MCP/REST gateway.

## The harness

The harness is more important than any individual model provider.

```text
Scenario fixture + seed + semantics version
                  |
                  v
        Scripted/model Gateway
                  |
                  v
      Typed command boundary -------- invalid-command corpus
                  |
                  v
      Deterministic phase runner ----- phase fault injector
                  |
          +-------+--------+
          |                |
          v                v
  World SQLite truth   Projection builders
          |                |
          +-------+--------+
                  v
       Reference-model assertions
                  |
       +----------+-----------+
       |          |           |
       v          v           v
  Replay diff  API contract  Playwright flow
```

The release layers are:

0. **Frozen protocol:** predeclared treatment, controls, refutation thresholds, privacy
   matrix, causal edges, and canonical evidence hashes.
1. **Pure domain tests:** ledgers, access checks, causal edge rules, command validation.
2. **Reference-model state machines:** long generated operation sequences and minimized failures.
3. **Scripted world scenarios:** no network, exact table-by-table replay, deterministic forks.
4. **Projection contract tests:** live, replay, and rebuilt projections have the same envelope and content.
5. **Browser workflows:** scripted projection server first, then one small real simulation.
6. **Live-provider smoke:** persona quality and natural communication only; never the deterministic release oracle.
7. **Scale receipt:** 100 cognitive agents at the manifest's p95/p99 interactive tick budget
   and 1,000 hybrid agents offline within the stated resource budgets.

## Scale-out trigger

Local [`asyncio.TaskGroup`](https://docs.python.org/3/library/asyncio-task.html#task-groups)
remains the default. Add a Ray implementation only when a recorded
profile shows inference dispatch, not provider latency, is the bottleneck and one of
these thresholds is crossed:

- more than 250 simultaneous ready inference requests,
- sustained local serialization overhead above 10% of tick wall time, or
- a multi-host provider-routing requirement.

Even then, workers receive immutable prompts and return typed candidate responses.
They never receive a writable store handle. The kernel commits results by stable
request key and deterministic order. At-least-once retries therefore cannot duplicate
world effects.

## Licensing and supply-chain rule

This document approves package evaluation, not source copying. Before adding a
dependency, lock the exact version, record its license, update third-party notices,
scan advisories, and verify Windows/Linux CI.
[AgentSociety's repository](https://github.com/tsinghua-fib-lab/agentsociety) includes a
commercial subdirectory exception, so any future code reuse requires a fresh path-level
license review. Architectural ideas may be independently implemented with attribution.

## Final recommendation

Build World OS as the next semantics layers of Agent Economy. Use established tools
at every replaceable boundary, but keep one local ordered kernel, one authoritative
world database per run, and one explicit path from observation to decision to settlement.

For outside-agent interoperability, use remote Streamable HTTP MCP as the primary
framework-neutral interface and generated OpenAPI REST clients as the fallback. Treat
Hermes and OpenClaw as configuration presets, OpenMolt as a social-product/API reference,
and A2A as a later coordination layer. None replaces the typed world-action boundary.
