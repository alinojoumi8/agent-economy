# Local and hosted API reference

The dashboard uses the same REST and WebSocket interfaces available to local
tools. Local mode has no account authentication; keep the server on localhost.
Local operator actions additionally require the operator session's CSRF token. FastAPI exposes
interactive OpenAPI documentation at `/docs` while the app is running.

## Local research operator

`/api/v2/operator/research` provides the local study library, reviewed drafts,
durable jobs and private exports. Every request requires the current `run_id`,
`tick=live`, the current `fork_id` when applicable and `X-CSRF-Token` from the
operator session. Hosted-safe instances reject these routes. Responses use
`Cache-Control: private, no-store`.

`GET /capabilities` lists the fixed scripted pilot and valid owner-configured
policy designs. `POST /drafts/validate` accepts either G2/F2 parameters or a
strict `preset: "POLICY"` request with reviewed design identity, explicit source
worlds, model draws and original limits. No validation step contacts a provider.
`GET /drafts/{id}` returns the reviewed protocol without gateway configuration,
credential references or private paths.

`POST /drafts/{id}/launch` binds the draft hash and idempotency key. Policy
drafts additionally require literal `approve_live_inference: true`. The
supervisor repeats all source/design checks and charges preflight to the
original allowance. `POST /jobs/{id}/resume` accepts only the original progress
hash, compatibility-check hash and idempotency key, never replacement caps.
Both writes return 202 and preserve existing jobs on an identical retry.

`GET /studies/{id}?result_sha256=...` independently verifies evidence before
comparison. V3 policy frames retain distinct model draws and use separate
pending and final contracts. Private exports require the displayed result and
verification hashes. See the [complete endpoint table](research/price-lab.md#local-operator-api)
and [operator policy specification](plans/2026-09-07-policy-operator-workflow.md#owner-configuration-and-request-contract)
for fields, directory configuration, admission bounds and recovery semantics.

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

Hosted administrative writes append tenant-local chained audit rows after
control-plane migration 003. The HTTP API does not present the hash chain as
simulation truth or external non-repudiation; authorized operators verify one
tenant's ordered rows and retain chain heads separately. See the
[operator runbook](operator-runbook.md#hosted-audit-chain).

The remaining unprefixed routes in this document describe local mode. Local
mode has no authentication; do not put it behind a public proxy.

## Run control

| Method | Path | Input/result |
|---|---|---|
| `POST` | `/api/run/start` | Optional `max_ticks` query; starts or resumes |
| `POST` | `/api/run/pause` | Requests an interruptible clean pause |
| `POST` | `/api/run/step` | Executes one tick and returns its summary |
| `POST` | `/api/run/stop` | Finishes, checkpoints, and generates a report |
| `POST` | `/api/run/speed` | JSON `{"delay_s": 0.5}`; `delay_s` must be finite and between 0 and 3600 seconds, otherwise HTTP 422 |
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
| `GET` | `/api/agents` | Identity, status, and execution list; add `limit` (1–200), `after_id`, `q`, or `population_tier=core|periphery` for a bounded cursor page |
| `GET` | `/api/agents/{id}` | Persona, accounts, loans, bounded beliefs and history, memories, holdings, decision audit, current compute plan/route, skills, XP, and progression/subscription history |
| `GET` | `/api/banks` | Operator ground-truth balance sheets and trust |
| `GET` | `/api/firms` | Sector, status, inventory, price, workers, cash, and stock price |
| `GET` | `/api/institutions` | Government, VC, healthcare, and outlets |
| `GET` | `/api/news?limit=30` | Latest articles |
| `GET` | `/api/conversations?limit=20&q=bank&agent_id=12&tick_from=1&tick_to=30&before_id=90` | Conversations, topics, participants, and messages; bounded literal text/topic/speaker search with optional agent, tick-range, and cursor filters |
| `GET` | `/api/events?limit=80&min_importance=0` | Recent append-only event spine |
| `GET` | `/api/trades?limit=50` | Latest executed exchange trades |
| `GET` | `/api/cost` | Governor plus model/purpose/agent cost breakdown |
| `GET` | `/api/llm/runtime` | Global/provider capacity plus ephemeral public-safe per-agent `queued|thinking` activity (`activity_revision`, agent id, active-call count, tick, elapsed time); also peaks, p50/p95 queue/response/day latency, cooldowns, failures, rate limits, and fallbacks. No prompts, response bodies, reasoning, cache keys, or raw errors are returned. |
| `GET` | `/api/v2/datasets` | Verified manifests/targets plus the latest R21 source and calibrated-versus-synthetic distance summary |

Default macro metrics include `gdp_proxy` (daily final-goods sales),
`gdp_proxy_30d`, `labor_income`, `cpi`, `inflation_30d`, true `cpi_yoy` after
tick 365, unemployment, index, policy rate, money supply, Gini, and sentiment.

### Historical-safe observer projections

These read-only endpoints return the canonical envelope and accept `tick` plus
`fork_id`. List endpoints use bounded `after`/`limit` pagination.

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/v2/workspaces/living-agents` | `agent_id`, `project_kind`, and `status` filters; committed, runtime-live-only, and derived evidence remain labelled |
| `GET` | `/api/v2/agents/{agent_id}/journey` | Historical profile, current-at-tick state, milestones, public outputs, and safe evidence references |
| `GET` | `/api/v2/construction-projects` | Semantics-13 projects; filter by `project_kind=private_home|workplace|public_facility` and exact lifecycle `status` |
| `GET` | `/api/v2/construction-projects/{project_id}` | One exact public project or privacy-safe aggregate, plus contribution-type totals where authorized |
| `GET` | `/api/v2/world-map?layers=construction_projects` | Construction layer separate from usable `places`; supports stable project selection in Live City |
| `GET` | `/api/v2/world-map?layers=households,institutions&tick=N` | Historical core household membership/child needs and public bank status, bound to the map envelope; no private accounts or exact household residences. See the [lens contract](plans/2026-09-07-city-society-lenses.md). |
| `GET` | `/api/v2/city/conversations?tick=3&fork_id=...&limit=60` | `city.conversations` envelope for the exact recorded day; ordinary small-talk transcripts, never private communication or provider stores |

City conversations return `data.items`, `tick`, `source=recorded_small_talk`,
`has_more` and `content_truncated`. The default is the newest 60 conversations
(maximum 200), each with up to 64 messages, 4,000 characters per message and
512 topic characters. Per-item/message truncation flags preserve this boundary.
Future conversations, messages and participants are withheld; malformed
participant records are excluded. A wrong fork or unavailable tick returns 409.
The endpoint performs no scientific writes. The city checks its envelope against
the already displayed map before releasing any words. See the
[city observer contract](research/city-observer.md).

Peripheral private-home construction is aggregated by region, status, and
stage. Owner, contributor, permit, exact-site, place, and reversible evidence
links are omitted from those aggregates.

Living Agents and observer events use one semantic activity-card projection.
Cards expose a bounded verb, object, outcome, lifecycle/stage, salience, and
safe `kind`/`id`/`tick` references. Unknown kinds use a labelled generic
fallback and never copy raw event payloads. Runtime `queued`/`thinking`
presence may be included only for a current view; a historical `tick` request
drops current runtime telemetry.

## City observation bookmarks

Local city navigation bookmarks use a separate operator workspace:

| Method | Path | Input/notes |
|---|---|---|
| `GET` | `/api/v2/operator/city-observations?context=<JSON>` | Exact map run/fork/visibility/version context; returns context, optimistic version and up to 20 navigation strings |
| `PUT` | `/api/v2/operator/city-observations` | Context, `expected_version`, entries and operator-session CSRF header; atomic save, 409 on stale context/version; no world writes |

Both routes return 404 in hosted-safe mode. See the
[city workspace contract](plans/2026-09-07-city-workspace-navigation.md) for the
field allowlist, context schema, local identity and error handling.

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

Kinds: `policy_rate`, `policy_rule_change`, `oil`, `rumor`, `slant`, `scandal`,
`epidemic`. Triggers: `shock`, `trend`, `conditional`. Empty trigger schedules
the next tick. Unknown kinds return HTTP 400; halted runs return HTTP 409.
Trigger and parameter fields are type-checked when the shock is scheduled
(integer ticks and ids, finite numbers, known `op`, `bank_selector`, and
`audience` values): a malformed field returns HTTP 400 with the reason instead
of failing later inside every NIGHT_CLOSE and wedging the run.

## Reports and replay viewer

| Method | Path | Notes |
|---|---|---|
| `POST` | `/api/report` | Generates/reuses a report at a completed tick boundary and returns its filesystem path plus served `/reports/...` URL in local mode; returns `409` while Run or a partial tick is active |
| `GET` | `/api/replay/runs` | Lists stored runs |
| `GET` | `/api/replay/{run_id}/summary` | Stored run summary |
| `GET` | `/api/replay/{run_id}/metrics` | Stored metrics; optional `names` |
| `GET` | `/api/replay/{run_id}/tick/{tick}` | Events/state view for one tick |

Generated reports are served from the configured `report_dir` under `/reports/`.
The replay viewer is read-only;
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

Hosted connection creation requires a run whose gateway is enabled on engine
semantics 9 or later. The default compatible choice is
`world-os-external` (semantics 10). A preserved semantics-7 run returns HTTP
409 with `detail.code = semantics_not_enabled`; a newer profile with the gateway
disabled returns HTTP 409 with `detail.code = gateway_disabled`. These are
configuration conflicts, not service outages, and no catalog connection or
credential is created.

See the [gateway contract](world-os/EXTERNAL-AGENT-GATEWAY.md) and
[client quickstart](../clients/README.md) for the turn and receipt protocol.
`GET /api/v2/agent/turn` and `ae_world_observe` require the `world.read` scope;
the `commons` tier, which is defined without it, reads Commons content only. A
turn always targets the next tick on which the connection is due: the next wake
tick under its `wake_interval_ticks`, never a tick whose decision mailbox has
already closed because it is in progress.
World observations and Commons content are untrusted data; these endpoints never
return private messages, prompts, chain-of-thought, provider payloads, or owner
identity.
The hosted REST proxy accepts only the routes and methods listed above (including
a UUID-shaped action receipt id). Encoded parent segments, alternate internal
paths, and unlisted methods return `404 not_found` before proxying.

When a run explicitly selects Semantics 14, every due first-class external
actor also receives immutable attendance evidence in the run database.
Attendance distinguishes an authored submission, including submitted
`do_nothing`, from a missed turn that applied `safe_do_nothing_v1`. It does
not add a public mutation endpoint and does not replace the turn, submission,
receipt, event, or ledger contracts. See the
[Semantics 14 guide](semantics14-external-turn-attendance.md).

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
