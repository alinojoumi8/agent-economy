# Full-stack review remediation — 2026-09-01

A line-by-line review of the server, hosted control plane, world loop, LLM
gateway, external agent gateway, and the dashboard. The automated gates were
green before the review started; every item below was found by reading code
against the invariants in `CONTRIBUTING.md`, confirmed against the source, fixed
in the same change set, and covered by `tests/test_review_regressions.py` or the
dashboard unit and Playwright suites unless noted.

## Fixed: server and projections

- Rejected migrations were projected as arrivals (`server/projections/workspaces.py`,
  `server/projections/living_agents.py`); only `completed` rows now move a citizen.
- Snapshot alerts were the run's oldest 100 events; they are now the newest 20
  salient events. Summary counts of living agents and active firms are now
  as-of the requested tick, so historical snapshot versions are stable.
- Legal settlement offers and acceptances were visible before their tick.
- A single agent's journey included region-wide permit aggregates.
- Observer search scanned every event in Python; the scan is bounded in SQL with
  escaped wildcards and communication authorization runs only for candidate
  threads. Results are unchanged.
- Backfill handed out commits from the in-progress tick; the event kind filter
  list is capped at 50.
- Hosted-safe documents now strip `database`, directory, and file keys and
  redact absolute artifact paths in string values; stored `run_exception`,
  `report_failed`, and `checkpoint_failed` errors are path-scrubbed.
- Static exports no longer include the private event spine, PRNG state, or the
  partial-tick decision buffer.
- Replay reader treats sidecar databases as "not found" instead of failing.
- The loop watchdog reports a stall while it is still ongoing and samples the
  loop thread rather than assuming the main thread.

## Fixed: run control and world loop

- `POST /api/shocks` validates trigger and parameter types when scheduling.
- `POST /api/run/speed` rejects non-finite or unbounded delays, and Pause/Stop
  wake the world out of its inter-tick sleep.
- A Stop queued behind a Start is re-asserted under the control lock; a repeated
  Stop no longer copies the database again; a Stop racing a reconciliation halt
  no longer relabels the halted run as finished.
- WebSocket broadcasts serialize once and fan out concurrently with a per-client
  timeout, so one stalled client cannot block the others.
- A failed transactional phase restores the persisted phase-start PRNG state so
  resume and replay draw the same numbers; provider and budget pauses checkpoint
  off the serving loop and are not duplicated by the run loop's teardown.
- `--ticks 0` runs nothing instead of running unbounded; negative values are
  rejected. Static export and fork-parent lookup open stored runs read-only.
- `uses_paid_providers` now sees tier, premium, and cohort routes.

## Fixed: external agent gateway and LLM gateway

- Turns target the connection's next wake tick and skip a tick whose mailbox is
  already closed; persisted envelopes answer long-polls without rebuilding the
  catalog; MORNING re-entry reuses attendance and logs one fallback event.
- `observe` and the turn mailbox require `world.read`; bank balance-sheet
  metrics follow `information.citizen_bank_visibility`.
- Gateway errors outside explicit handlers answer with their own status, MCP
  argument type errors are `-32602`, malformed OAuth bodies are `400`, and
  rate-limit windows are pruned.
- Provider gate slots granted to a cancelled waiter are returned; a stored
  invalid completion pauses a tiered run on resume; replay tries every planned
  target's cache key; malformed model envelopes are rejected instead of crashing
  the phase; configuration errors pause the run instead of being swallowed per
  citizen; the legacy retry loop no longer re-sends 4xx contract rejections or
  malformed-body parse errors.

## Fixed: hosted control plane

- Run-local SQLite service calls run on the serving loop, never in a worker
  thread beside the tick.
- A terminal snapshot retires the handle so the next request reopens the run
  lazily instead of wedging behind a lost lease; reopening a stopped run does
  not relabel the catalog row; transient heartbeat errors retry until the TTL
  is genuinely at risk; one unrecoverable run no longer fails startup.
- Manual snapshots of a running world no longer write `paused`; quota and
  authorization refusals return 409; shutdown closes every run before raising.
- The OAuth consent redirect names the client origin in `form-action`.
- Migrations grant the web role the column update the agent-policy endpoint
  performs and no longer scan parameter-less SQL for placeholders; login
  throttling fails closed with a minimal retry window; `snapshot-all` attempts
  every run and renews its lease during publish.

## Fixed: dashboard

- Hosted world reads doubled the `/api` prefix and 404'd everywhere.
- Fresh loads no longer greet with cursor 0 and start stale; invalidations adopt
  the announced cursor; tick frames do not clear a pending recovery.
- Run controls depend only on the status request; a rejected control refreshes
  status; a stale status response cannot regress the day counter.
- Participant form input survives polling; the shock trigger select is never
  empty; the People search field shows keyboard focus; downloads revoke their
  blob URL after the click; the freshness badge is truthful while connecting.
- Bare `/commons` derives its run id instead of linking to `run`; the stored
  theme applies on every route; a failed deployment probe keeps the boot shell
  with the reason; active-route matching uses the path segment.
- Live City pulls the map once per tick change, positions territory plates
  without infinite coordinates, and offers a keyboard follow control; the
  diorama draws flows from both producers, keeps its glide alive, and declares
  update triggers; the Observatory no longer pins live lens links to a tick.
- Workspaces: threads paginate and resolve deep links, the default causal root
  is the newest committed event, errors are surfaced, selections survive
  polling, windowed counts are labelled as windows, filtered-empty copy is
  truthful, and selected items expose `aria-current`.

## Verification

| Gate | Result |
|---|---|
| CI smoke set | 144 passed |
| CI core subset | 271 passed |
| Hosted, gateway, runtime, and loop suites | 235, 276, and 58 passed |
| `tests/test_review_regressions.py` | 35 passed |
| Dashboard unit tests and type-check | 217 passed, clean |
| Playwright suite plus real-backend smoke | 67 of 67 and 1 of 1 passed |
| `uvx pip-audit -r requirements.lock` | no known vulnerabilities |

The committed bundle under `server/static/` was regenerated from the final
dashboard source; a second build reproduced the same hashed assets.

## Deferred decisions

Each of these changes a contract or a design boundary and was left for an
explicit decision rather than fixed in passing.

- Trend shocks apply `duration_ticks + 1` steps (`world/shocks.py`); fixing it
  changes historical output and needs a new `engine_semantics_version` gate.
- `hosted_transfer_run_owner` accepts `observer` and `admin` but not
  `agent_owner`; a fix is a new hosted migration 004.
- `POST /oauth/register` is unauthenticated and unbounded; bounding it is a
  policy choice about dynamic client registration.
- SECURITY DEFINER lookups under `FORCE ROW LEVEL SECURITY` require the migrator
  to be a superuser or `BYPASSRLS`; a preflight assertion would fail closed on
  deployments that differ from the reference Compose.
- Hosted supervisors that do not share `run_directory` can republish a stale
  local database after losing and regaining a lease.
- The legacy non-tiered route still converts an invalid completion into a
  `do_nothing` with `ok=False`; existing tests pin that behaviour.
- Memory retrieval orders by tick without an id tiebreaker; adding one changes
  prompts and therefore the exact-replay contract of stored runs.
- `/api/agents` runs unindexed `llm_calls` scans; new indexes change the schema
  inventory hash that research exports verify.
- Local `server/app.py` run controls have no origin or CSRF check.
- Replay does not reconstruct cancelled external arrivals; a suspended
  `pending_actor` connection cannot be resumed; the browser OAuth authorize
  route requires an owner header.
- `dashboard/src/workspaces/OverviewWorkspace.tsx` is unreachable and its test
  pins dead UI; hosted runs keep engine checkpoints per pause; preflight
  completions are not metered; Anthropic cache-write tokens are priced at the
  base rate; `HEAD /` returns 405 on the local server.
