# Local and hosted API reference

The dashboard uses the same REST and WebSocket interfaces available to local
tools. There is no authentication; keep the server on localhost. FastAPI exposes
interactive OpenAPI documentation at `/docs` while the app is running.

## Hosted R22 boundary

The optional hosted application is a separate authenticated entry point. It
sets secure `__Host-ae_session` and CSRF cookies; every mutation must include
the CSRF cookie value in the header named by `GET /api/v2/mode` (currently
`X-AE-CSRF`). Observers are read-only; admins manage membership, runs, and
controls. Cross-tenant resources return 404.

| Method | Path | Role / result |
|---|---|---|
| `GET` | `/api/v2/mode` | Public hosted capabilities and profile names; never secrets |
| `POST` | `/auth/register` | Redeem a one-time tenant invitation |
| `POST` | `/auth/login` | Tenant UUID, email, and password; sets session + CSRF cookies |
| `POST` | `/auth/logout` | Authenticated mutation; revokes the session |
| `GET` | `/api/v2/tenants/{tenant}/session` | Current user and role |
| `POST` | `/api/v2/tenants/{tenant}/invitations` | Admin; returns the credential once |
| `POST` | `/api/v2/tenants/{tenant}/invitations/revoke` | Admin |
| `GET` | `/api/v2/tenants/{tenant}/members` | Admin |
| `PATCH` | `/api/v2/tenants/{tenant}/members/{user}` | Admin; role/status update with self-lockout guard |
| `GET` | `/api/v2/tenants/{tenant}/runs` | Observer/admin tenant run catalog |
| `POST` | `/api/v2/tenants/{tenant}/runs` | Admin; creates one SQLite-backed run from an allowlisted profile |
| `GET` | `/api/v2/tenants/{tenant}/runs/{run}` | Catalog and available runtime status |
| `PATCH` | `/api/v2/tenants/{tenant}/runs/{run}` | Admin ownership transfer; lifecycle changes use control |
| `POST` | `/api/v2/tenants/{tenant}/runs/{run}/control` | Admin; `start`, `pause`, `stop`, `step`, or `speed` |
| `GET` | `/api/v2/tenants/{tenant}/runs/{run}/world/{path}` | Bounded, sanitized read-only world API proxy |
| `WS` | `/api/v2/tenants/{tenant}/runs/{run}/ws` | Authenticated tenant/run event stream |

Hosted world proxy routes are allowlisted. Mutations, reports/static file
mounts, replay discovery, arbitrary paths, provider configuration, prompt
payloads, and credentials are not proxied. Service endpoints are
`/health/live`, `/health/ready`, and `/metrics`.

The remaining unprefixed routes in this document describe local mode. Local
mode has no authentication; do not put it behind a public proxy.

## Run control

| Method | Path | Input/result |
|---|---|---|
| `POST` | `/api/run/start` | Optional `max_ticks` query; starts or resumes |
| `POST` | `/api/run/pause` | Requests an interruptible clean pause |
| `POST` | `/api/run/step` | Executes one tick and returns its summary |
| `POST` | `/api/run/stop` | Finishes, checkpoints, and generates a report |
| `POST` | `/api/run/speed` | JSON `{"delay_s": 0.5}` |
| `GET` | `/api/run/status` | Run, phase, governor, readiness, cooldown, and report state |
| `GET` | `/api/acceptance/status` | Gate results, progress, spend projection, exact Oracle checkpoint schedule, and shock evidence; a run/tick-matched final receipt supplies attachment-backed completed gates |

Halted worlds reject mutating controls. Starting an already-running world returns
its current state rather than creating another task.

## Participant sandbox

These routes return HTTP 403 unless `participant_mode.enabled` is true. Control
changes require a paused, completed-day boundary and an `expected_tick` matching
the current completed tick.

| Method | Path | Input/result |
|---|---|---|
| `GET` | `/api/participant` | Current lease, next tick, queued command, role-scoped action catalogue, and last execution result |
| `GET` | `/api/participant/history?agent_id=4&limit=50&before_id=120` | Newest-first durable action history with an optional exclusive cursor; returns at most 100 records and `next_before_id` |
| `POST` | `/api/participant/control` | JSON `{"agent_id": 4, "expected_tick": 0}`; controls one living citizen |
| `POST` | `/api/participant/action` | JSON with `expected_tick`, an action from the returned catalogue, and optional `reasoning` |
| `POST` | `/api/participant/release` | JSON `{"expected_tick": 3}`; releases control and cancels the next queued command |

While a citizen is controlled, continuous `/api/run/start` is disabled and
`/api/run/step` requires one queued action for the next day. Commands use the
normal deterministic validator and ledger. Participant influence is persisted
and makes the run ineligible for observer-only acceptance evidence.
The citizen inspector loads this history on demand and can page backward without
adding it to the observatory's frequent polling payload.

## World queries

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/metrics?names=...` | Named time series; includes output, labor income, CPI, inflation, labor, market, and distribution metrics |
| `GET` | `/api/agents` | Agent identity/status list |
| `GET` | `/api/agents/{id}` | Persona, accounts, loans, bounded beliefs, `belief_history`, memories, holdings, and decision audit |
| `GET` | `/api/banks` | Operator ground-truth balance sheets and trust |
| `GET` | `/api/firms` | Sector, status, inventory, price, workers, cash, and stock price |
| `GET` | `/api/institutions` | Government, VC, healthcare, and outlets |
| `GET` | `/api/news?limit=30` | Latest articles |
| `GET` | `/api/conversations?limit=20&q=bank&agent_id=12&tick_from=1&tick_to=30&before_id=90` | Conversations, topics, participants, and messages; bounded literal text/topic/speaker search with optional agent, tick-range, and cursor filters |
| `GET` | `/api/events?limit=80&min_importance=0` | Recent append-only event spine |
| `GET` | `/api/trades?limit=50` | Latest executed exchange trades |
| `GET` | `/api/cost` | Governor plus model/purpose/agent cost breakdown |
| `GET` | `/api/v2/datasets` | Verified manifests/targets plus the latest R21 source and calibrated-versus-synthetic distance summary |

Default macro metrics include `gdp_proxy` (daily final-goods sales),
`gdp_proxy_30d`, `labor_income`, `cpi`, `inflation_30d`, true `cpi_yoy` after
tick 365, unemployment, index, policy rate, money supply, Gini, and sentiment.

## Oracle and calibration

| Method | Path | Input/notes |
|---|---|---|
| `POST` | `/api/oracle/ask` | JSON `{"question":"What is the probability of a bank run within 30 ticks?"}` |
| `GET` | `/api/oracle/predictions` | Predictions plus current scorecard |
| `GET` | `/api/oracle/calibration?scope=run` | Current run; use `scope=all` for pooled stored runs |

Oracle answers are read-only and contain probability, drivers, confidence,
machine-checkable resolution rule, deadline, bounded evidence, and later Brier
score when resolvable.

## Shocks

`GET /api/shocks` returns supported kinds, trigger types, and scheduled shocks.

`POST /api/shocks` accepts:

```json
{
  "kind": "rumor",
  "trigger_type": "shock",
  "trigger": {"tick": 15},
  "duration_ticks": 0,
  "params": {
    "bank_selector": "largest_by_deposits",
    "audience": "current_depositors",
    "n_agents": 40
  },
  "label": "largest-bank rumor"
}
```

Kinds: `policy_rate`, `oil`, `rumor`, `slant`, `scandal`, `epidemic`. Triggers:
`shock`, `trend`, `conditional`. Empty trigger schedules the next tick. Unknown
kinds return HTTP 400; halted runs return HTTP 409.

## Reports and replay viewer

| Method | Path | Notes |
|---|---|---|
| `POST` | `/api/report` | Generates/reuses a report at a completed tick boundary; returns `409` while Run or a partial tick is active |
| `GET` | `/api/replay/runs` | Lists stored runs |
| `GET` | `/api/replay/{run_id}/summary` | Stored run summary |
| `GET` | `/api/replay/{run_id}/metrics` | Stored metrics; optional `names` |
| `GET` | `/api/replay/{run_id}/tick/{tick}` | Events/state view for one tick |

Generated reports are served under `/reports/`. The replay viewer is read-only;
`python run.py --replay RUN_ID` is the separate exact engine re-execution proof.

## External Agent Gateway

Semantics 9 and later expose one scoped boundary for owner-hosted agents. The
generated contract is available at `/api/v2/openapi.json` and checked in at
[`openapi/agent-economy-v2.json`](../openapi/agent-economy-v2.json).

| Method | Path | Notes |
|---|---|---|
| `GET`, `POST` | `/mcp` | Remote Streamable HTTP MCP; bearer OAuth or scoped PAT |
| `POST` | `/oauth/register` | Dynamic registration for public PKCE clients |
| `GET` | `/oauth/authorize` | Human consent and owned-connection selection |
| `POST` | `/oauth/token`, `/oauth/revoke` | Resource-bound token rotation and revocation |
| `GET` | `/api/v2/agent/me`, `/api/v2/agent/turn`, `/api/v2/agent/events` | Identity, long-poll turn mailbox, and cursor events |
| `POST` | `/api/v2/agent/actions` | Idempotent action submission for the exact target tick and projection hash |
| `GET` | `/api/v2/agent/actions/{submission_id}` | Persisted action receipt |
| `GET`, `POST` | `/api/v2/agent/commons` | Scope-filtered Commons read/write adapter |
| `GET`, `POST` | `/api/v2/tenants/{tenant_id}/agent-connections` | Human owner/admin connection control plane |
| `POST` | `/api/v2/tenants/{tenant_id}/agent-connections/{id}/credentials` | One-time PAT rotation or revocation |

See the [gateway contract](world-os/EXTERNAL-AGENT-GATEWAY.md) and
[client quickstart](../clients/README.md) for the turn and receipt protocol.
World observations and Commons content are untrusted data; these endpoints never
return private messages, prompts, chain-of-thought, provider payloads, or owner
identity.

## WebSocket

Connect to `/ws`. The server sends current state on connection and a payload
after each completed tick containing run state, governor state, latest macro
values, and tick summary. Clients may send keepalive text; controls use REST.

## PowerShell examples

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/run/status
Invoke-RestMethod http://127.0.0.1:8000/api/acceptance/status
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/run/step
Invoke-RestMethod -Method Post -ContentType application/json `
  -Body '{"question":"Will any bank fail within 30 ticks?"}' `
  http://127.0.0.1:8000/api/oracle/ask
```
