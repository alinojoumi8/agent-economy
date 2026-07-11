# API reference

The dashboard uses the same REST and WebSocket interfaces available to local
tools. The API has no authentication and is intended for localhost use only.
FastAPI also exposes its generated OpenAPI UI at `/docs` while the server runs.

## Run control

| Method | Path | Input | Result |
|---|---|---|---|
| `POST` | `/api/run/start` | Optional query `max_ticks` | Starts/resumes; returns current status/tick |
| `POST` | `/api/run/pause` | None | Requests a clean pause |
| `POST` | `/api/run/step` | None | Executes one tick and returns its summary |
| `POST` | `/api/run/stop` | None | Finishes, checkpoints, and returns report path |
| `POST` | `/api/run/speed` | `{"delay_s": 0.5}` | Sets real-time delay between ticks |
| `GET` | `/api/run/status` | None | Run ID, state, tick, governor, readiness, and report |

Starting or stepping a halted run returns HTTP 409. Starting an already-running
world returns `already_running`.

## World queries

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/metrics?names=...` | Named metric series; defaults to core macro metrics |
| `GET` | `/api/agents` | Agent identity/status list |
| `GET` | `/api/agents/{agent_id}` | Persona, accounts, loans, beliefs, memories, shares, decision audit |
| `GET` | `/api/banks` | Deposits, reserves, reserve ratio, loans, and trust |
| `GET` | `/api/firms` | Sector, status, inventory, price, staff, cash, and stock price |
| `GET` | `/api/institutions` | Government, VC, healthcare, and news outlets |
| `GET` | `/api/news?limit=30` | Latest articles |
| `GET` | `/api/conversations?limit=20` | Conversations with participants and messages |
| `GET` | `/api/events?limit=80&min_importance=0` | Recent event spine |
| `GET` | `/api/trades?limit=50` | Latest exchange trades |
| `GET` | `/api/cost` | Governor plus model, purpose, and agent cost breakdown |

## Oracle

| Method | Path | Input/notes |
|---|---|---|
| `POST` | `/api/oracle/ask` | `{"question":"probability of a bank run within 30 ticks?"}` |
| `GET` | `/api/oracle/predictions` | Predictions plus current scorecard |
| `GET` | `/api/oracle/calibration?scope=run` | Current run; use `scope=all` for pooled stored runs |

Oracle answers are read-only and include a probability, drivers, confidence,
machine-checkable resolution rule, and deadline when the question is resolvable.

## Shocks

`GET /api/shocks` returns supported kinds, trigger types, and scheduled shocks.

`POST /api/shocks` accepts:

```json
{
  "kind": "oil",
  "trigger_type": "shock",
  "trigger": {"tick": 10},
  "duration_ticks": 0,
  "params": {"multiplier": 2.0},
  "label": "oil doubles"
}
```

Supported kinds are `policy_rate`, `oil`, `rumor`, `slant`, `scandal`, and
`epidemic`. Trigger types are `shock`, `trend`, and `conditional`. When
`trigger` is omitted or empty, the server schedules the shock for the next tick.
Unknown kinds return HTTP 400; halted runs return HTTP 409.

## Reports and replay

| Method | Path | Notes |
|---|---|---|
| `POST` | `/api/report` | Generates a report for the active run |
| `GET` | `/api/replay/runs` | Lists stored runs |
| `GET` | `/api/replay/{run_id}/summary` | Run summary or HTTP 404 |
| `GET` | `/api/replay/{run_id}/metrics` | Stored metrics; optional `names` query |
| `GET` | `/api/replay/{run_id}/tick/{tick}` | Events/state view for one tick |

Generated reports are served below `/reports/`.

## WebSocket

Connect to `/ws`. On connection the server sends the current tick payload; each
completed tick broadcasts another JSON payload containing run state, governor,
latest macro values, and the tick summary. The client may send keepalive text;
controls remain REST operations.

## Examples

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/run/status
Invoke-RestMethod http://127.0.0.1:8000/api/agents
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/run/step
Invoke-RestMethod -Method Post -ContentType application/json `
  -Body '{"question":"Will any bank fail within 30 ticks?"}' `
  http://127.0.0.1:8000/api/oracle/ask
```
