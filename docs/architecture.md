# Architecture

## System shape

Agent Economy is a local, single-process simulation and observatory:

```text
React dashboard ──REST/WebSocket──> FastAPI server
                                      │
                                      ▼
                         deterministic World loop
                       ┌──────────────┼──────────────┐
                       ▼              ▼              ▼
                 economy engine   agent runtime   information layer
                 ledger/markets   prompts/memory  news/conversations
                       └──────────────┼──────────────┘
                                      ▼
                              LLM gateway + Oracle
                                      │
                                      ▼
                              SQLite run database
```

`run.py` is the only application entry point. It resolves configuration,
performs provider readiness checks, opens or creates the run database, and
starts either a headless world or the FastAPI observatory.

## Deterministic ownership boundary

LLMs propose structured actions. The deterministic engine validates and applies
them. The gateway cannot directly mutate balances, firms, loans, orders, jobs,
or policy state.

All monetary effects pass through double-entry ledger transactions whose legs
sum to zero. The world reconciles each tick. A reconciliation failure halts and
checkpoints the run rather than continuing with corrupted state.

Seeded PRNG streams own world mechanics, lifecycle events, and persona sampling.
Exact replay rebuilds genesis and re-executes stored LLM responses in a new
database, then compares every relevant table by canonical SHA-256 digest.

## Tick lifecycle

Each tick is one simulated day and executes in fixed order:

1. **Night close** — interest, loan payments, payroll, production, lifecycle,
   shocks, metrics, and reconciliation.
2. **Morning** — scheduled agents perceive state and request structured actions.
3. **Execution** — validated actions apply in stable order.
4. **Market** — the order book matches and closes.
5. **Newsroom** — outlets draft and publish from events.
6. **Evening** — social pairs converse and transmit observations/rumors.
7. **Memory** — event observations are captured, daily memories compressed,
   beliefs updated, and weekly summaries created every seventh tick.

The world commits run status after the memory phase and checkpoints at the
configured cadence.

## Major components

| Area | Responsibility |
|---|---|
| `engine/` | Ledger, banking, credit, firms, labor, exchange, lifecycle, government, VC, healthcare, and action validation |
| `agents/` | Persona generation, scheduling, context assembly, policies, memory, and decision runtime |
| `world/` | Genesis, fixed-phase loop, shocks, metrics, newsroom, conversations, and replay verification |
| `llm/` | Provider adapters, route validation, retries, structured parsing, cache accounting, and budget governor |
| `oracle/` | Read-only forecasting, resolution rules, Brier scoring, and calibration |
| `server/` | REST/WebSocket API and committed dashboard bundle |
| `dashboard/` | React, Vite, Tailwind, and Recharts observatory source |
| `acceptance/` | Resumable PRD evidence campaigns |
| `experiments/` | Multi-seed treatment/control harness |
| `reports/` | Standalone end-of-run HTML/Markdown reports |

## Agents and memory

Production genesis creates exactly 100 agents: 87 sampled citizens, 11
institutional staff, and two healthcare founders. Staff include the central
banker, credit officers, two outlet teams, VC partner, exchange operator,
lawyer, and treasury secretary.

Agent cognition is persisted, inspectable, and replayable:

- observations store text, importance, entity tags, access time, and demotion;
- retrieval scores recency, importance, and entity relevance;
- nightly LLM calls compress observations into first-person daily summaries and
  propose numeric belief updates;
- every seventh tick synthesizes daily summaries into a weekly memory before
  demoting the source summaries;
- decision request/response records preserve the exact model context and cost;
- the dashboard agent inspector exposes identity, balances, beliefs, memories,
  and recent decision audits.

The planned next memory milestone is long-horizon tiered retrieval and
counterpart continuity; current implementation details and completion status
remain documented in [implementation status](implementation-status.md).

## Persistence and artifacts

Each run is one SQLite WAL database under `data/runs/`. It contains run metadata,
agents, institutions, ledger state, events, memories, conversations, predictions,
metrics, shocks, checkpoints, and LLM calls. Checkpoint copies live under
`data/checkpoints/`; reports live under `reports/out/`.

These generated directories are operational artifacts, not source. Back up the
run database and any checkpoint needed for recovery together with the exact
configuration/commit used to create it.

## Runtime boundaries

- The server defaults to `127.0.0.1` and has no authentication or tenant model.
  Do not expose it directly to an untrusted network.
- SQLite is the v1 store; hosted multi-user operation and 1,000-agent scale are
  deferred P2 work.
- The Oracle is read-only. It may query stored state but cannot submit actions.
- The CLI adapter is restricted to Oracle/development purposes and cannot power
  swarm roles.
- `.env` is local and ignored; secrets must never enter run configs or reports.

See [TECH-SPEC.md](../TECH-SPEC.md) for the normative design and
[API reference](api-reference.md) for external interfaces.
