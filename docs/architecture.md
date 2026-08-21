# Architecture

## System shape

```mermaid
flowchart LR
    UI[React observatory] <-->|REST and WebSocket| API[FastAPI server]
    API --> PROJ[Read-only projections]
    API --> WORLD[Deterministic world loop]
    WORLD --> ENGINE[Economy engine]
    WORLD --> AGENTS[Agent runtime]
    WORLD --> INFO[News and conversations]
    AGENTS --> GATEWAY[LLM gateway]
    AGENTS --> POLICY[Deterministic local policies]
    INFO --> GATEWAY
    GATEWAY --> PROVIDERS[Scripted or live providers]
    WORLD --> ORACLE[Read-only Oracle]
    ORACLE --> GATEWAY
    ENGINE --> DB[(SQLite run database)]
    AGENTS --> DB
    INFO --> DB
    ORACLE --> DB
    PROJ --> DB
```

`run.py` is the application entry point. It resolves inherited configuration,
performs provider readiness checks, opens or creates a run database, and starts
either a headless world or the local observatory.

Hosted R22 is an optional outer control plane:

```mermaid
flowchart LR
    B[Hosted dashboard] -->|session + CSRF| H[Hosted FastAPI]
    H --> P[(PostgreSQL catalog + forced RLS)]
    H --> S[Lease-based run supervisor]
    S --> R1[(Tenant A / run 1 SQLite v11)]
    S --> R2[(Tenant B / run 2 SQLite v11)]
    S --> O[(Immutable local or S3 snapshots)]
    H --> M[Prometheus metrics]
```

PostgreSQL owns identity, tenancy, sessions, run metadata, leases, audit, and
snapshot pointers. It does not own economic state. Each supervised run still
uses the same single-writer deterministic world and SQLite schema as local mode.

## Ownership boundary

LLMs can only propose structured actions and belief updates. Deterministic code
validates identities, ownership, balances, market phase, institutional roles,
and action bounds before applying state. The gateway cannot directly mutate a
balance, loan, firm, job, order, or policy rate.

The tier boundary changes decision selection, not state authority. Scheduled
core agents use their configured Gateway or scripted route. Scheduled peripheral
agents select a state-derived local policy directly and create no `llm_calls`
row. Both produce ordinary action envelopes that pass through the same
`ActionExecutor`, domain services, ledger, event spine, and replay contract.

Every monetary effect uses integer-cent double-entry transactions whose legs
sum to zero. The world reconciles at tick boundaries; an invariant failure
halts and checkpoints instead of continuing with corrupted state.

## Evidence and authority layers

Four layers deliberately answer different questions:

| Layer | Authority | Examples |
|---|---|---|
| Canonical simulation state | Deterministic engine and ledger | accounts, contracts, actions, events, metrics |
| Additive decision evidence | Versioned immutable run tables | Semantics 14 external-turn attendance |
| Read-time projection | No mutation; caller-vetted public facts only | Living Agents and observer activity cards |
| Ephemeral operations | Current process health only | provider queue/thinking presence and latency |

`server/projections/activity.py` is the single semantic adapter used by Living
Agents and observer events. It maps safe references into bounded activity
cards, never copies event payloads, and marks unknown facts with an honest
generic fallback. Current runtime presence may appear only in a current view;
historical views drop it. Projection adds no event and changes no replay hash.

Semantics 14 writes one immutable attendance row for every due first-class
external actor. A submitted `do_nothing` remains authored attendance; an
absent runtime produces missed attendance while the engine applies
`safe_do_nothing_v1`. Attendance does not replace submission, execution,
event, or ledger evidence. See
[the Semantics 14 guide](semantics14-external-turn-attendance.md).

`builder_workspace/` exposes only a deterministic immutable
`proposal.create` sink. It validates an allowlisted patch and fixed check
evidence, stores a tenant-scoped proposal bundle, and returns a receipt. It has
no apply, Git, deployment, network, secret, engine, ledger, replay, or
`ActionExecutor` authority. No Civic Builder runtime or mandate facade is
implemented.

Hosted administrative audit rows use a tenant-local SHA-256 chain after hosted
migration 003. This detects supplied-row modification, middle deletion,
reordering, and cross-tenant mixing. Pre-migration rows remain explicitly
legacy. Tail deletion requires a separately retained chain head, and the chain
is not externally anchored or non-repudiation. It is separate from the
simulation event log.

## Tick lifecycle

One tick is one simulated day, executed in fixed phases:

1. **Night close**: interest, repayments, payroll, production, lifecycle,
   government/health/VC sweeps, and shocks.
2. **Morning**: scheduled agents perceive role-scoped state and request actions.
3. **Execution**: validated actions apply in stable order.
4. **Market**: order books match and close.
5. **Newsroom**: outlets select evidence, draft, and publish.
6. **Evening**: social pairs converse and transmit observations.
7. **Memory**: observations are captured, summaries/beliefs are updated, and
   weekly consolidation runs every seventh tick.
8. **Finalize**: metrics, reconciliation, durable phase state, and checkpoints.

Phase cursors make safe resume possible. Completed calls are durable and reused
if a provider interruption occurs mid-tick.

## Major packages

| Package | Responsibility |
|---|---|
| `config/` | Dataset manifests and optional hosted-service configuration |
| `runs/` | Inherited local, production, acceptance, research, and v2 profiles |
| `engine/` | Ledger, credit, firms, labor, exchange, lifecycle, government, VC, healthcare, and action validation |
| `agents/` | Persona sampling, scheduling, role-scoped context, policies, memory, and decisions |
| `world/` | Genesis, phase loop, shocks, metrics, newsroom, conversations, and replay verification |
| `llm/` | Provider adapters, routing, readiness, retry/repair, caching, metering, and budget governor |
| `oracle/` | Read-only forecasting, resolution rules, Brier scoring, and calibration |
| `experiments/` | Multi-seed treatment/control harness |
| `research/` | Calibrated initialization, canonical hashes, and research utilities |
| `scenarios/` | Versioned paired counterfactual scenario packs |
| `reports/` | Run reports and production acceptance receipts |
| `server/` | REST/WebSocket API and committed production dashboard bundle |
| `dashboard/` | React/Vite/Tailwind/Recharts observatory source |
| `hosted/` | PostgreSQL catalog/RLS, auth, supervisor, artifact adapters, hosted API, operations, and CLI |
| `builder_workspace/` | Deterministic allowlisted proposal bundles; no patch application or deployment authority |
| `deploy/` | Compose reference stack, Caddy TLS, Prometheus, and PostgreSQL role initialization |

## Information and belief model

Semantics-v3 runs enforce epistemic boundaries:

- citizens and founders see their own accounts plus public bank name/status;
- credit officers see their own bank balance sheet;
- the central banker, Oracle, dashboard, and reports retain ground truth;
- `trust:bank:*`, `sentiment`, and `inflation_expectation` have reserved bounds;
- each belief update appends old/raw/normalized/new values and source-call
  provenance to the event spine.

This separation lets experiments distinguish information exposure from direct
mechanical intervention.

## Persistence and replay

Each run is one SQLite WAL database under `data/runs/`. It stores metadata,
agents, institutions, ledger state, markets, events, memories, beliefs,
conversations, predictions, metrics, shocks, checkpoints, and LLM calls.
Schema 20 additively stores external-turn attendance for explicitly selected
Semantics 14 runs.

Exact replay rebuilds genesis in a new database and re-executes recorded LLM
responses without a network fallback. Canonical table hashes prove equality.
Semantics 14 replay copies attendance identifiers, links, reasons, policies, and
timestamps exactly from the source.
Legacy semantics-v1/v2 configurations retain their original bank visibility,
belief-event, and macro-metric behavior so historical runs remain replayable.

## Runtime boundaries

- Local v1 is a single-process app with no authentication. Bind to localhost.
- SQLite, approximately 100 agents, one region, and one operator remain the
  intentional v1 acceptance baseline.
- R18 participant mode, R19 deterministic 1,000-agent core/periphery scale,
  R20 regions/FX/trade/migration, and opt-in R21 SCF/SUSB initialization are
  implemented extensions. R21 reuses schema-v10 provenance tables and the
  schema-v11 engine.
- R22 is an implemented optional hosted boundary: invite-only auth and roles,
  forced-RLS tenant catalog, one writer lease per run, multiple observers/runs,
  immutable snapshots, hosted dashboard, and deployment/operations assets. It
  leaves local APIs, simulation schema, and semantics unchanged.
- The reference hosted stack is PostgreSQL 17 + MinIO + application + Caddy +
  Prometheus. Exact local image/Compose, TLS, isolation, S3 restore, password
  rotation, Prometheus, and bounded load evidence passed at `53081f2`; PR #19
  head `1cf1d0a` passed its six-job matrix in run `29409250171`. Public production
  deployment remains a separate, unclaimed release action.
- The Oracle is read-only and CLI-backed models are restricted to Oracle/dev
  purposes.

The normative contracts live in [TECH-SPEC.md](../TECH-SPEC.md); current proof
status lives in [implementation-status.md](implementation-status.md).
