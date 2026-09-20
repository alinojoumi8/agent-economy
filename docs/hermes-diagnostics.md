# Controlled Hermes/Jev diagnostics

This interface is for granular validation after the host execution-policy issue
has been resolved. It is not an alternate launcher or a way around that denial.
No diagnostic live launch was performed during implementation. The original
`hermes_citizens.py` cohort command and its production retry policy are preserved.

## Explicit operations

Run from the diagnostic checkout. Common options go before the operation.
Use the actual existing world directory and URL; the examples are placeholders.

```powershell
python -B scripts/hermes_diagnostics.py --world-root C:/path/to/world-checkout --run-id RUN_ID --url http://127.0.0.1:PORT check
python -B scripts/hermes_diagnostics.py --world-root C:/path/to/world-checkout --run-id RUN_ID --url http://127.0.0.1:PORT decide-one --profile EXACT_PROFILE
python -B scripts/hermes_diagnostics.py --world-root C:/path/to/world-checkout --run-id RUN_ID --url http://127.0.0.1:PORT advance-one --expected-tick CURRENT_TICK
```

`--profiles-root` and `--hermes-python` select existing installations; neither
installs nor creates a profile. Optional `--budget-db` names the existing shared
provider allowance for inspection. It does not create, reserve, replenish or
attach a budget. Native Jev accounting also checks the run's existing
`.jev-budget.db` when present. Missing ledgers are reported as unavailable,
never as zero spend. Hermes's own provider/OAuth usage is external to that ledger.

The server must contain this branch's new local diagnostic routes for DECIDE-ONE
or ADVANCE-ONE. CHECK still reports the local snapshot if that server is absent
or old; running state and its in-process control lock then remain unavailable.
There is no fallback to an unguarded legacy Step endpoint. Hosted apps do not
expose the new routes. Existing authentication and submission endpoints are
unchanged.

### CHECK

Reads the existing manifest, profile presence, saved identity/configuration hash,
completed/active tick, saved status, admissions, queued external actions, saved
phase decisions, recorded decisions beyond the completed tick, saved governor,
and provider allowance totals/limits. It performs one optional read-only
`GET /api/run/diagnostics` to observe the server's current running/paused state,
world/database identity and control lock. A server on the wrong run or database
is rejected. A different tick between observations is labeled inconsistent.

It probes existing operator/supervisor locks with read-only handles and reports
matching local Python controller processes. These are point-in-time observations,
not a durable guarantee that nothing can start afterward. Permission limitations
can make ownership uncertain. No authenticated agent endpoint is polled: those
endpoints can update leases. CHECK creates no files/directories, profile sessions,
SQL rows, budget reservations or child processes; its report goes to stdout.

Even SQLite `mode=ro` can update a WAL read mark in `-shm`. Therefore CHECK and the
server diagnostic reader use `engine.inspection.inspection_snapshot`: byte reads
of the database/WAL, verification of the valid WAL prefix and last commit, and
SQLite deserialization into a query-only in-memory database. It follows the
[SQLite WAL format and reader algorithm](https://www.sqlite.org/fileformat2.html#wal_file_format).
It never opens source SQLite files through SQLite, never reads/writes SHM,
checkpoints, repairs or migrates a source. Metadata plus a second byte comparison
reject concurrent changes without retry. Hot rollback journals, unreadable or
unsupported snapshots and combined input sizes over 512 MiB are unavailable;
the interface does not silently repair them. A stable observation does not
reserve the world; only ADVANCE-ONE's server-side comparison authorizes a step.

### DECIDE-ONE

Exactly one explicit profile is accepted. Its home, manifest connection, active
admitted actor, authenticated run/connection/actor identity, local URL and existing
restricted Agent Economy MCP tools must agree. An unadmitted citizen returns
`admission_required`; no registration, admission or clock endpoint is available
through the decision transport. Wrong/stale identity stops before Hermes starts.

The command takes the existing supervisor and operator locks without starting a
supervisor. It requires a stopped clock at a complete saved boundary, checks for
STOP and an already queued/executed decision, and calls the reusable
`CohortOperator.decision_attempt` once. Production `_decide_once` delegates to that
same helper and retains its previous three-attempt wrapper. Diagnostic HTTP reads
and writes have no automatic retry. The helper retains the configured model,
provider credentials, session continuity, toolset, 12-turn/180-second Hermes
limits, 240-second process timeout and existing process cleanup. It does not
change provider/budget/approval rules.

The normal authenticated turn renewal and `ae_action_submit` gateway remain in
use. Projection hashes, action schemas, wake limits, idempotency and deterministic
action validation still apply. The diagnostic never directly inserts an action
or calls the engine. It only queues a proposal; no simulation tick follows it.
Normal turn/auth/session bookkeeping and the resulting action receipt can change.

Before/after evidence is saved under the cohort's ignored `diagnostics/` folder
with a unique directory per invocation. Existing per-profile attempt prompts,
transcripts, exit/timeout receipts and session metadata are retained. A timeout,
missing receipt, process failure or lost response is `ambiguous`, even when a
later observation finds a queued action. Inspect that evidence before choosing
another action; this command does not launch a recovery attempt. An interrupted
operation with only `before.json` is likewise unresolved, not permission to retry.
Structured errors omit private provider text and tokens; transcript/prompt files
remain private local operator evidence.

### ADVANCE-ONE

Requires both an explicit run ID and a nonnegative expected completed tick. The
client records its request before sending exactly one POST. The new local route
calls `RunController.advance_one`, which rejects an occupied control lock, then
compares run identity, tick, running state and partial-tick state **inside the
existing `_control_lock`**. At that same atomic boundary it rejects terminal
states (`halted`, `finished`, `error`, `completed`, `exhausted`), any existing
attention pause reason, and an exhausted served-tick limit. These checks are
authoritative for direct API callers too; the client's earlier checks are only
for usability. Rejection does not reopen a world, clear its pause, or mutate its
database. Only a valid boundary invokes `_step_locked` once, retaining all of the
normal governed-step safety checks. Diagnostic terminal and pause rejections use
HTTP 409 (`world_terminal`, `attention_pause_requires_recovery`, or
`served_tick_limit_reached`); they require separate explicit recovery.

The established participant, acceptance, halt, served-tick, provider-budget and
world-step controls remain in charge. This is one **whole-world** tick: it may
perform native Jev/DeepSeek/MiniMax work and scheduled admissions. It is not a
single-citizen clock and does not run Hermes. It may pause before completing if
an existing safeguard stops it. Such a result is `not_completed`, never silently
resumed. A stale repeated request is rejected; an active partial tick needs
explicit recovery outside this diagnostic operation. Concurrent calls are refused
rather than queued. A lost response is `ambiguous`, with a separate after-state
observation when available, and is never automatically resent.

## Installed Hermes oneshot inspection

Inspected before implementing the single-attempt interface at Hermes commit
`a84a2223f82c3d9906fd4a9d778a188774e7a08e`.

- `hermes_cli/main.py:1687-1770`: `cmd_chat` passes `oneshot_exit` to `cli.main`.
- `cli.py:4384-4436`: single-query mode calls `cli.chat` and exits after the turn.
- `agent/conversation_loop.py:1423-1570`: a conversation can iterate through
  multiple API calls/tool rounds; the loop includes an optional budget grace call.
- `agent/conversation_loop.py:1391-1420`: each iteration has provider
  retry/recovery handling through `_run_api_retry_loop`.
- `hermes_cli/_parser.py:250-266`: max-turns bounds iterations; run-budget is
  elapsed seconds. Neither means exactly one billable provider request.

**One controller attempt is not one provider/model request.** Tool rounds,
provider/transport recovery and potentially context processing can make several
underlying requests. DECIDE-ONE does not disable or alter Hermes internal retry,
auth, approval or provider behavior. Its guarantee is one controller dispatch,
not one HTTP call or a new spending allowance. Reinspect Hermes if its version or
profile configuration changes before drawing live cost conclusions.

## Verification

Focused tests use disposable scripted worlds, in-process HTTP, fake Hermes
processes and an external-network guard. They cover strict CLI selection,
admission/identity failures, production action validation, no retry on ambiguous
outcomes, one whole-world step, stale/concurrent requests, existing governance
and full database/WAL/SHM hash preservation for CHECK. WAL inspection is checked
against real SQLite at 512/4096/65536-byte pages, committed/uncommitted frames,
reset generations, corruption, concurrent modification and size limits.

```powershell
python -B -m pytest -q tests/test_hermes_diagnostics.py tests/test_inspection_snapshot.py
python -B -m pytest -q tests/test_hermes_citizens_operator.py tests/test_hermes_supervision.py
```

Also run every `tests/test_jev_*.py` file, `tests/test_live_response_contract.py`,
`tests/test_provider_budget.py`, `tests/test_external_agent_gateway.py`,
`tests/test_recorded_replay_golden.py` and `tests/test_documentation.py`.
The diagnostic suites are included in the existing CI smoke job.

After policy resolution, review this branch, use a server containing these routes,
perform CHECK, explicitly admit a chosen pending citizen if required, then choose
one DECIDE-ONE and inspect its receipt before a separately authorized ADVANCE-ONE.
No live result, production readiness or 100-tick validation is claimed by these
offline tests. PR #96 and the preserved prepared world are not deployment targets
for this implementation task.
