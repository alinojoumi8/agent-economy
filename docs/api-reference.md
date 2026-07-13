# Local API reference

The dashboard uses the same REST and WebSocket interfaces available to local
tools. There is no authentication; keep the server on localhost. FastAPI exposes
interactive OpenAPI documentation at `/docs` while the app is running.

## Run control

| Method | Path | Input/result |
|---|---|---|
| `POST` | `/api/run/start` | Optional `max_ticks` query; starts or resumes |
| `POST` | `/api/run/pause` | Requests an interruptible clean pause |
| `POST` | `/api/run/step` | Executes one tick and returns its summary |
| `POST` | `/api/run/stop` | Finishes, checkpoints, and generates a report |
| `POST` | `/api/run/speed` | JSON `{"delay_s": 0.5}` |
| `GET` | `/api/run/status` | Run, phase, governor, readiness, cooldown, and report state |
| `GET` | `/api/acceptance/status` | Gate results, progress, spend projection, Oracle samples, and shock evidence; a run/tick-matched final receipt supplies attachment-backed completed gates |

Halted worlds reject mutating controls. Starting an already-running world returns
its current state rather than creating another task.

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
| `GET` | `/api/conversations?limit=20` | Conversations, participants, and messages |
| `GET` | `/api/events?limit=80&min_importance=0` | Recent append-only event spine |
| `GET` | `/api/trades?limit=50` | Latest executed exchange trades |
| `GET` | `/api/cost` | Governor plus model/purpose/agent cost breakdown |

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
| `POST` | `/api/report` | Generates a report for the active run |
| `GET` | `/api/replay/runs` | Lists stored runs |
| `GET` | `/api/replay/{run_id}/summary` | Stored run summary |
| `GET` | `/api/replay/{run_id}/metrics` | Stored metrics; optional `names` |
| `GET` | `/api/replay/{run_id}/tick/{tick}` | Events/state view for one tick |

Generated reports are served under `/reports/`. The replay viewer is read-only;
`python run.py --replay RUN_ID` is the separate exact engine re-execution proof.

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
