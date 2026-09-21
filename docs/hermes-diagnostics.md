# Controlled Hermes/Jev diagnostics

This interface is for granular validation after the host execution-policy issue
has been resolved. It is not an alternate launcher or a way around that denial.
No diagnostic live launch was performed during implementation. The original
`hermes_citizens.py` cohort command and its production retry policy are preserved.

## Explicit operations

### Attach an existing prepared server

The normal `run.py` launcher supports an exclusive resume-existing mode. It never
uses the preparation harness, `open_run` genesis/migrations, or provider preflight.
All artifact paths and budget identifiers below are mandatory. The operator
workspace path is also explicit because the HTTP server normally creates that
separate UI database. This mode must attach its existing copy instead.
The supplied workspace must match `operator_workspace.path` in the stored config,
or the normal `operator-workspace.db` default beside the existing world database.
Use absolute recorded control-plane paths when serving across worktrees; relative
configured paths retain their normal process-working-directory interpretation.

```powershell
python -B run.py --serve --host 127.0.0.1 --port PORT --ticks REMAINING_ALLOWANCE `
  --existing-run-db C:/original/data/runs/RUN_ID.db --expected-run-id RUN_ID `
  --provider-budget-db C:/original/evidence/provider-budget.db `
  --expected-budget-contract-sha256 VERIFIED_CONTRACT_SHA256 `
  --provider-budget-binding ORIGINAL_BINDING --provider-budget-scope ORIGINAL_SCOPE `
  --passport-db C:/original/control-plane/passports.db `
  --operator-workspace-db C:/original/data/runs/operator-workspace.db
```

Use the contract digest and binding/scope from the preserved allowance evidence;
do not invent a new contract or replenish usage. Paths must be distinct existing
unaliased regular files. The passport path must match the stored world config,
and every passport-linked connection must match the registry's citizenship link.
No identity, signing key, profile or registry is created. The budget's contract
digest, gateway config binding, integrity, disposition and reservation totals
are checked; sealed, breached or unresolved allowances are refused. All native
provider requests remain governed by the original shared `ProviderBudget` object.

Only paused/created worlds at complete tick boundaries with an explicit supported
semantics version and the current database schema can attach. Missing artifacts,
corrupt databases, missing schema objects, terminal/running/partial worlds and
conflicting CLI modes fail closed. Older schemas require separate reviewed
migration; this command never upgrades them. It does not read a replacement run
config or silently fall back to fresh startup. Provider credentials must already
be available through the normal environment/`.env` mechanism; no authentication
probe is performed by this mode.

Startup holds SQLite writer exclusion while rechecking the saved run and creating
runtime objects with query-only source connections. It restores saved status and
PRNG state, retaining durable provider/budget attention-pause evidence at the
current boundary. Process-only pause details that were never persisted cannot be
reconstructed; running/partial snapshots are refused rather than repaired.
`--ticks` sets the bounded server allowance; it does not execute any tick or
authorize a later live operation. Supplying `--acceptance-run`, preflight,
activation, replay or other startup modes is an error.

Opening/closing SQLite runtime handles may change physical WAL/SHM/checkpoint
files. Startup must leave canonical rows, events, admissions, submissions, budget
reservations and usage unchanged. Tests compare every table before/after the app
lifespan and prohibit genesis, transport, child-process and clock calls. They use
disposable databases only. This mode is a supported attachment interface, not
permission to bypass a host execution restriction. Run read-only CHECK and review
its evidence before separately authorizing ADVANCE-ONE or DECIDE-ONE.

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


## Incorporation catalog contract

`ae_actions_list` returns the persisted turn's participant action catalog. For
non-civic worlds with active entrepreneurship, `found_company` now has
`enabled: false`, `available: false` and a missing-opportunity reason unless the
current context supplies an incorporation action. A supplied action is exposed
as an exact template: name, sector, lawyer, capital and business idea cannot be
retargeted. New catalogs use this contract; existing turn envelopes and rejected
receipts are historical evidence and are not rewritten by an upgrade.

The existing context builder remains the source of deterministic opportunities.
No opportunity generation, authorization grant, economic rule or identity rule
is added by this fix. Its current next-tick opportunity is checked by the same
read-only `ActionExecutor.founding_prerequisite_error` used at execution. The
executor retains the same ordered checks, rejection reasons, permit consumption
and ledger effects. The helper never reserves a permit or changes state.

Before choice, the catalog can evaluate current actor availability, whether a
current opportunity exists, its exact payload, lawyer eligibility, existing
business control, present funds and already-used formation capacity. Opportunity
construction also applies configured age, health, retirement, risk, employment,
arrival/review cadence, reserve/capital and market conditions. Zero capital is
legal at execution; the configured opportunity generator may require more.
Legacy profiles without active entrepreneurship retain their editable form.
Civic worlds retain the existing permit/appointment opportunity flow.

Listing is not an execution reservation. Earlier actions in the governed tick
can consume capacity/funds, change lawyer availability or company control, or
consume a civic authorization. Execution rechecks those conditions and records
a terminal rejection if necessary. No speculative future state is used to
promise success.

### Preserved live evidence

Run `9b08e45cca`, tick 2, Omar actor 29, receipt
`add5ca73-45a1-4c0e-9f3a-e825660c430b` correctly rejected incorporation because
`found_company is available only from a supplied entrepreneurship opportunity`.
The old catalog always appended the non-civic editable form, using the optional
opportunity only for default values. Without an opportunity it still offered
blank business fields, a valid lawyer and zero capital. Form normalization was
not the engine's authorization check. The new unavailable descriptor prevents
that known-invalid choice; exact templates also prevent invented terms when an
opportunity exists. The old rejection is retained without modification.

The path is `server.external_api` MCP `ae_actions_list` ->
`ExternalAgentService.turn` -> `ParticipantService.action_catalog` ->
`ContextBuilder.build`. Submission normalizes against the turn catalog; governed
execution calls `ActionExecutor._do_found_company`. Persisted turn catalogs are
intentional snapshots, so dynamic execution guards remain necessary.

### Other catalog findings

The generic `pitch_vc` mismatch identified during incorporation testing is now
addressed by the funding contract below. Other consumers of
`_startup_authorization_error` (term-sheet proposal/acceptance, diligence,
funding close, IP registration and merger proposal/approval/close) enter this
participant catalog through exact context-derived startup variants; no further
generic-form plus exact-startup-authorization mismatch was found among those
consumers. This is a bounded inspection, not a guarantee about every action.

## VC pitch availability contract

The MCP path is `ae_actions_list` -> `ExternalAgentService.turn` ->
`ParticipantService.action_catalog`. The former generic founder form supplied
an owned firm ID, editable ask (default 50,000 cents) and editable summary
(default "growth capital"). Under active entrepreneurship, those arbitrary
terms could not satisfy `_startup_authorization_error`, even though the form
was marked enabled. Existing exact `startup-*` variants coexisted with it.

With active entrepreneurship, the generic form is removed. The current
`startup_work.eligible_actions` pitch variants remain, checked by the shared
read-only `ActionExecutor.pitch_prerequisite_error`. If none exists, a founder
gets an explicit disabled/unavailable descriptor explaining that a current
supplied action is required. Authorized company, ask and summary are hidden
exact fields; clients cannot change them. The UI variant identifies the form,
not an economic authorization field. Legacy inactive-entrepreneurship forms
remain unchanged. No authorization is created by the new availability helper;
the existing context generation and actor/tick authorization caches are retained.

### Actual prerequisites

Precomputable at listing time:

- A current actor/tick supplied startup action under active entrepreneurship,
  matched by canonical payload (only existing provenance fields are excluded).
- The actor controls the specified firm under normal business-control rules.
- The firm is private, the ask is positive, and no pending pitch exists.
- The current context must still offer that pitch, rather than an old cache
  entry. Its preseed generation requires enabled autonomous preseed, the
  configured founding/activation delay, a business idea, no prior pitch, and
  no higher-priority lifecycle action. JEV v4 also supplies exact 75% and 125%
  ask alternatives; these remain available, not collapsed to the base amount.

`pitch_vc` itself does not set investor identity, equity, valuation or fund
capital. Those belong to later investment/term-sheet actions. The ask is an exact
supplied integer, not a client-chosen range. A successfully created pitch starts
pending; it does not transfer money or guarantee funding. Pending pitch expiry
is 14 ticks; that is distinct from the actor/tick opportunity authorization.

Execution still rechecks authority and control and calls the same
`VentureCapital.can_pitch` predicate through the normal pitch creation path.
An earlier action can create a pending pitch or change control/private status.
A consumed preseed opportunity is not offered again, even if a historical
pending pitch later expires, because the generator requires no prior pitch.
The catalog never reserves funding or promises execution success.

The helper extraction preserves existing rejection text/order and VC creation,
follow-on, event and ledger behavior. Historical turn envelopes and the
protected tick-2 run are not rewritten. Test fixtures are disposable and offline.

## Mandatory pre-tick validation checkpoints

Every server opened with `--existing-run-db` now requires a complete pre-tick
checkpoint before either `/api/run/advance-one` or `/api/run/step` can dispatch.
The normal Hermes cohort uses Step and receives the same protection. This is a
prospective server change: an already running older server is not upgraded or
restarted automatically. New-world startup and economic rules are unchanged.
Continuous Run is refused on this prepared validation surface; use bounded Step.

A local operator can also call `POST /api/run/snapshot-for-replay` with
`{"expected_run_id":"<run>","expected_tick":<tick>}`. This creates evidence only;
it neither queues an action nor advances the clock. It uses the existing local
operator access boundary and refuses hosted mode, wrong/stale identity, busy or
uncommitted state, partial ticks, terminal state and attention pauses.

Capture is synchronous inside the controller lock. It reads database/WAL bytes
into private SQLite images, checks integrity/foreign keys and provider reservation
settlement, and verifies all source file stamps across the complete capture
interval. Concurrent changes fail closed without retry. All four explicit stores
(world, shared budget, passport and operator workspace) must be present. The
world image includes every table, queued submission, turn, receipt, PRNG stream,
sequence counter and configuration. Runtime PRNG state must equal the committed
state; the operation never repairs a mismatch. Runtime status/target tick and
source Git revision/working-tree digest are recorded in the manifest.
The source digest is bound at server attachment and rechecked before capture;
on-disk source changes require a newly reviewed server attachment. This operation
requires the persisted split-stream PRNG format (semantics 7 and later); older
worlds keep their existing ordinary replay path.

For a governed advance, empty SQLite `BEGIN IMMEDIATE` transactions exclude
independent writers on all four artifacts from capture through the initial
`World.step` boundary read. Query-only guards prevent accidental writes while
those exclusions are held. Lock acquisition does not wait or retry. Exclusions
are released at step entry, before normal admission and provider-accounting
writes, and on every error path. The shared budget remains governed normally
during the tick; it is not frozen for the entire provider operation. These empty
transactions may affect WAL/SHM bookkeeping, not SQL state. Snapshot-only requests
retain the byte-read-only path and do not acquire SQLite writer locks.

Files are flushed into a private staging directory and published by an atomic
rename under `<world-db-directory>/validation-checkpoints/<unique-id>/`. The
controller exposes `last_replay_checkpoint` for the most recent successful
capture. No source checkpoint catalog row or world event is written. Checkpoint
failure prevents the world step. Independent bundles are never overwritten or
automatically pruned. Retain them with the resulting provider recordings.

These bundles contain private identity material. Keep them local; do not commit
or publish them. SQLite images use rollback-journal header bytes rather than a
WAL dependency; their physical hashes differ from the live files while complete
SQL state is identical. Hashes for each image and the manifest bind the evidence.
This provides atomic publication and fail-closed capture, not a guarantee against
storage hardware failure. Concurrent external writers can cause a refused capture.

`engine.replay_checkpoint.restore_replay_bundle(bundle, new_directory)` verifies
hashes and atomically copies only the four allowlisted databases and manifest.
It never launches a server or opens paths named by the stored configuration.
Stored absolute paths remain provenance: an offline harness must explicitly bind
its copied identity/workspace/budget stores and frozen provider recordings, use
`World(..., replay=True)`, restore persisted PRNG state, and deny network access.
Never attach a restored budget to live providers. Hermes models need not be
relaunched: the pre-tick world already contains their queued inputs and prior
validation receipts. The original Hermes sessions remain separate operational
evidence, not deterministic world-step inputs.

Periodic `checkpoint_every` snapshots are post-tick, world-only artifacts. Setting
that interval to zero disabled those snapshots in the earlier validation profile;
read-only table hashes and partial exports did not replace a restorable checkpoint.
The mandatory pre-tick bundle is independent of that historical configuration.
Tests in `tests/test_validation_checkpoint.py` prove full SQL-state preservation,
WAL inclusion, isolated restore and a recorded replay from a queued-input checkpoint.
