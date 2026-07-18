# World OS: Communications and Causal Observatory Implementation Plan

**Date:** 2026-07-18<br>
**Status:** Approved at Gate -1; implementation in progress<br>
**Branch reviewed:** `main` at `c9f0b23`<br>
**Product contract:** [World OS PRD](../world-os/PRD.md)<br>
**Technical contract:** [World OS Technical Specification](../world-os/TECH-SPEC.md)<br>
**Framework decision:** [Framework Research](../world-os/FRAMEWORK-RESEARCH.md)

## Outcome

Ship the first World OS semantic lake as one reproducible causal proof:

```text
private message
    |
    v
authorized delivery --> agent memory/belief --> scheduled decision
    |                                           |
    |                                           v
    +---------------- causal trace <---- domain action
                                                |
                                                v
                                         event + ledger
                                                |
                                                v
                                  live/replay Observatory
```

The release is complete when the approved
[30-tick treatment/control protocol](../world-os/30-TICK-RESEARCH-PROTOCOL.md) demonstrates
this chain, survives pause/resume/fork/replay under `hash-contract-v1`, exposes no private
field to an unauthorized consumer, rebuilds identical authorized projections, recovers a
dropped WebSocket cursor, and passes the browser investigator workflow.

## Step 0: Scope challenge

The full vision includes education, households, housing, services, careers, richer law,
political institutions, and population-scale simulation. Building those simultaneously
would make failures impossible to attribute and migrations difficult to replay. Scope is
therefore reduced to the smallest lake that proves the architecture needed by every later
institution: typed commands, private communication, immutable access grants, knowledge
boundaries, causal provenance, versioned projections, and an investigation-first UI.

The scope reduction is architectural sequencing, not a reduction in the product vision.
Semantics 9 and later are explicitly reserved for the later lakes in the PRD.

## What already exists

| Existing capability | Evidence in the repository | Plan treatment |
|---|---|---|
| Deterministic authoritative tick loop | `world/loop.py` runs named phases and owns world mutation | Reuse; extract a static `PhaseSpec` table without changing historical semantic order |
| Stable action compatibility boundary | `engine/actions.py::ActionExecutor.execute_action` accepts mapping-shaped actions and has many callers | Preserve the facade and result shape; validate through a typed registry behind it |
| Event spine and append-only ledger | Existing domain handlers write events and balanced financial entries | Reuse as authoritative economic truth; communication bodies remain outside the public event payload |
| Database initialization and ad-hoc migrations | `engine/schema.py::initialize_schema` applies existing schema evolution | Replace future ad-hoc evolution with a numbered registry while retaining every historical step |
| Replay, checkpoint, and provider resume | `llm/gateway.py` and world run state already persist replay/resume information | Extend; the new phase and communication tables must participate in the same deterministic receipt |
| Firms, banks, VC, IPOs, bankruptcy, law, politics, news, personas, memory, beliefs, and lifecycle | Existing world/domain packages and tests | Reuse. This plan does not rebuild those domains; messages must motivate their ordinary actions |
| FastAPI REST and WebSocket support | Existing server/controller surface and installed FastAPI/WebSocket dependencies | Add thin versioned adapters over shared projection builders |
| React Observatory and charts | `dashboard/src`, React 19, Recharts, and `useObservatory.js` endpoint aggregation | Migrate incrementally to route workspaces and typed query state; retain useful current panels |
| Experiment harness and hosted catalog | Existing experiment/report flows and hosted audit/run catalog | Reuse run identity and audit patterns; keep operator annotations outside world truth |

The plan deliberately extends these contracts instead of introducing a second simulation
engine, event bus, graph database, or frontend source of truth.

## NOT in scope

| Deferred work | Rationale |
|---|---|
| Education, teachers, credentials, and skill formation | Reserved for semantics 9 after communication causality is proven |
| Households, families, inheritance, housing, and mortgages | Reserved for semantics 10 because ownership and lifecycle rules require a separate migration lake |
| Rich services and career ladders | Depends on education and household demand; later semantic version |
| Full criminal procedure, appellate courts, and jurisdictional law | First lake only needs existing legal actions to appear in causal traces |
| Real geography or GIS data | Real-world data licensing and coordinates are separate concerns |
| New full-depth World, People, Organizations, Markets, Politics & Law, and Experiments workspaces plus deck.gl layers | Routes preserve/rehouse current panels; new cross-domain visualization depth follows the causal gate |
| Distributed world-state mutation | One process remains the authoritative writer; only stateless inference may scale later |
| Ray in the default runtime | Added only after profiling proves local structured concurrency misses the accepted budget |
| Kafka, Redis, Neo4j, or another operational database | SQLite plus bounded relational causal links meets the first-lake consistency and deployment needs |
| Multiplayer public hosting and billing | Hosted research-group metadata is designed, but commercial tenancy is not a first-lake gate |
| Open-ended user scripting or runtime phase plugins | Static phase order is a reproducibility boundary |
| Autonomous outbound real email or brokerage integration | Communications and markets are simulated, never connected to real accounts |

## Accepted architecture decisions

All review choices were explicitly accepted by the user using the recommended complete
option. They are constraints, not implementation suggestions.

1. Keep the current Python kernel and place discriminated Pydantic command models behind
   `ActionExecutor.execute_action()` while preserving mapping inputs and result outputs.
2. Use one immutable semantics version per authoritative lake; existing runs never upgrade
   in place and may only continue under their recorded semantics or be explicitly forked.
3. Store asynchronous private communications separately from public events; only safe
   metadata may appear on the event spine.
4. Grant access immutably at delivery time. Joining an organization reveals no old mail;
   leaving does not revoke already delivered mail; discovery and forwarding create explicit
   provenance-bearing grants.
5. Represent causality in bounded SQLite relations with authority, confidence, and
   provenance; use the normative `engine`, `actor_claim`, and `model_inference` authority
   vocabulary plus the relation-direction matrix in the technical specification.
6. Build every REST, WebSocket, live, and replay read from the same versioned projection
   functions.
7. Keep the kernel single-writer. Use local `asyncio.TaskGroup` for independent inference;
   introduce Ray only behind a dispatcher after profiling.
8. Use SQLite as replay truth and content-addressed Parquet/DuckDB bundles for offline
   research only.
9. Use React Router, TanStack Query, generated OpenAPI types, deck.gl, Sigma/Graphology,
   Recharts, and equivalent semantic tables in an incremental TypeScript migration.
10. Keep local/hosted operator notes in a separate audited store and address world objects
    only through stable references.

## Architecture review

### System boundary

```text
                              READ-ONLY / DERIVED
                  +---------------------------------------+
                  |                                       v
+-----------------+------------------+       +---------------------------+
| Authoritative simulation process   |       | Observatory / research UI |
|                                    |       |                           |
| scheduler -> deliberation          |       | REST bootstrap/backfill   |
|              |                     |       | WS ordered deltas          |
|              v                     |       | route/query state          |
| ActionExecutor compatibility API   |       | maps/graphs/charts/tables  |
|              |                     |       +-------------+-------------+
|              v                     |                     |
| typed registry -> domain handlers  |                     v
|              |                     |       +---------------------------+
|              +--> world.db         |       | operator-workspace.db     |
|                   events/ledger    |       | notes/hypotheses/views    |
|                   communications   |       | never mutates world.db    |
|                   causal links     |       +---------------------------+
|                   checkpoints      |
+-----------------+------------------+
                  |
                  | stateless request/result only
                  v
        +-----------------------------+
        | inference dispatcher        |
        | local TaskGroup by default  |
        | optional remote workers     |
        +-----------------------------+
```

### State ownership

| State | Authoritative owner | Mutation path | Rebuildable? |
|---|---|---|---|
| World entities, money, events, communication, grants, causal links | Per-run SQLite `world.db` | Tick loop through validated domain commands only | No; this is replay truth |
| Checkpoint/provider receipts | Run storage | World/inference gateway | No; required for resume evidence |
| REST/WS projection snapshots | Projection builders/cache | Derived from `world.db` | Yes |
| Investigation notes, hypotheses, saved views | Operator workspace DB or hosted PostgreSQL | Explicit operator API | No, but never part of simulated reality |
| Parquet research tables and manifest | Export bundle | Deterministic export job | Yes |
| Browser URL/query/selection | Browser | Router and local ephemeral state | Yes |

### Version contract

```text
run_id
  +-- semantics_version : behavior/order contract (8 for this lake)
  +-- schema_version    : SQLite storage shape (12 for this lake)
  +-- projection_version: response schema (1 for this lake)
  +-- snapshot_version  : deterministic identity of one authorized snapshot
  +-- policy_version    : field/view policy contract
  +-- view_key          : opaque principal/grant-scope lineage
  +-- event_cursor      : global ordered commit position in one run/fork

old run + old semantics --------> replay under old behavior
old run + request for new lake --> explicit fork --> new run + semantics 8
live schema migration ----------> storage compatibility only, never behavior upgrade
```

Reject opening databases whose migration checksum differs or whose schema version is from
the future. Never silently reinterpret an existing run with a new semantics version.

## Data flow and execution paths

### Tick and communication path

```text
world/loop.py::step()
  |
  +-- load PhaseSpec for recorded semantics
  |     `-- unknown semantics? -> fail closed before mutation
  |
  +-- INBOX_DELIVERY (semantics >= 8)
  |     +-- select due, undelivered messages in stable order
  |     +-- resolve audiences at delivery tick
  |     |     +-- participant -> direct grant
  |     |     +-- organization -> membership snapshot grant
  |     |     `-- no authorized recipient -> record no-delivery outcome
  |     +-- persist immutable deliveries/grants
  |     `-- append safe metadata event + causal `triggered` links
  |
  +-- MORNING / EXECUTION
  |     +-- build policy-filtered agent knowledge projection
  |     |     `-- authorization failure -> body absent, not redacted placeholder
  |     +-- ordinary scheduled deliberation proposes typed commands
  |     +-- malformed/unknown command -> stable rejected ActionResult
  |     `-- valid command -> existing ActionExecutor transaction/savepoint
  |
  +-- MARKET / NEWSROOM / EVENING / MEMORY / FINALIZE
  |     +-- existing domain behavior
  |     +-- memory records only observed content
  |     `-- checkpoint phase cursor + table hashes
  |
  `-- phase exception
        +-- rollback current phase transaction
        +-- retain last completed phase cursor
        `-- resume executes phase once, not twice
```

The planned inline diagram above belongs beside the semantics table in `world/phases.py`
and a compact transaction version belongs in `communications/delivery.py`. Those comments
are contracts and must be updated whenever phase or grant semantics change.

### Command validation path

```text
mapping from LLM / policy / existing caller
  |
  v
ActionEnvelope.from_mapping()
  +-- missing discriminator ------> rejected result: invalid_action
  +-- unknown discriminator ------> rejected result: unknown_action
  +-- known discriminator
        |
        v
  Pydantic command model
    +-- validation error ---------> stable rejected result + safe diagnostic
    `-- valid
          |
          v
  CommandRegistry.dispatch(context, command)
    +-- authorization/invariant --> domain rejection, no partial state
    +-- unexpected exception -----> savepoint rollback + structured failure
    `-- success ------------------> existing result shape + event/ledger links
```

The compatibility facade remains the only ordinary mutation entry point. A
`LegacyHandlerAdapter` preserves mapping inputs, per-action savepoints, and existing result
dictionary shapes while commands migrate into the registry. Communication proposal rows
are body-free and retain only a stable content reference plus bounded metadata; errors use
stable safe codes. New code may not call communication persistence helpers directly from
prompts, routes, or UI handlers.

### Projection and reconnect path

```text
browser route opens
  |
  +-- GET /api/v2/snapshot?fork_id=F&domains=...&tick=T
  |     `-- shared builder -> {run_id,fork_id,tick,semantics_version,
  |                            projection_version,policy_version,view_key,
  |                            snapshot_version,event_cursor,data}
  |
  +-- WS subscribe(run/fork, cursor=C, projection/policy/view lineage)
  |     +-- lineage unsupported ----------> 409/upgrade-required UI
  |     +-- C retained and contiguous ----> ordered deltas C+1 ... N
  |     +-- C too old/gap detected --------> backfill instruction
  |     `-- run paused --------------------> heartbeat + paused status
  |
  `-- client delta reducer
        +-- next cursor/version matches ---> update query cache
        `-- gap, duplicate conflict, stale -> stop applying; REST backfill/invalidate
```

WebSocket deltas never become a second truth. They are a latency optimization over the same
builders used by REST and replay.

### Investigation path

```text
event selected in timeline
  -> request bounded causal neighborhood
      -> authority filters and depth/node caps
          -> graph + chronological table share stable refs
              -> select message metadata
                  -> policy check
                      +-- authorized: fetch body
                      `-- denied: show existence-safe summary only
                          -> operator adds hypothesis in sidecar store
                              -> export references + redaction manifest
```

No investigator action changes simulation state. Operator truth access is privileged,
explicitly labeled, and audited.

## Code quality review

### Required boundaries

- `engine/actions.py` stays a small compatibility facade. Command model lookup and dispatch
  live under `engine/commands/`; communication business rules do not accumulate in the
  existing high-complexity executor.
- `world/loop.py` delegates phase iteration to `world/phases.py`. The phase table is data,
  the runner is generic, and phase injection at runtime is forbidden.
- `communications/handlers.py` validates domain intent; `delivery.py` owns temporal grant
  creation; `policy.py` is the sole body-access decision; `projections.py` exposes only
  knowledge-safe agent views.
- `causal/links.py` validates endpoints and relation types; traversal lives separately so
  write invariants cannot be bypassed by graph query conveniences.
- `server/projections/` owns response construction. REST and WebSocket adapters may select,
  authorize, serialize, and transport but may not rebuild business state independently.
- `operator_workspace/` may reference a world row but may not import mutation helpers or
  write to `world.db`.
- Frontend data ownership is explicit: TanStack Query owns server state, React Router owns
  addressable navigation, and component state owns only ephemeral display state.

### Compatibility discipline

Before refactoring a touched existing handler, add characterization tests for mapping input,
validation failure, savepoint rollback, event output, ledger output, and `ActionResult` shape.
Migrate existing handlers to typed models only when they are touched for this lake. This
avoids a repository-wide rewrite and allows old commands to retain exact behavior.

### Domain invariants

1. A private recipient reads through an immutable delivery/disclosure grant; sender,
   published-public, and operator-truth access are explicit `AccessBasis` policy exemptions,
   with operator inspection audited outside replay truth.
2. A recipient set is resolved at delivery, never re-evaluated on read.
3. Delivery, grant, safe event metadata, and causal links commit atomically.
4. Message bodies never enter public event payloads, logs, metrics labels, news prompts, or
   unauthorized exports.
5. A causal edge references two extant stable objects in the same run.
6. Deterministic direct relations have authority `engine`; stated motivation/citation uses
   `actor_claim`; scheduled model analysis uses relation `inferred` and authority
   `model_inference` with method, confidence, call, and evidence provenance.
7. Per-tick communication quotas are enforced before persistence and are deterministic.
8. Projection builders are pure with respect to world state and observer access cannot
   influence simulation results.
9. Every balance-affecting domain action remains subject to existing ledger invariants.
10. Operator annotations cannot be consumed by agents or simulation policies.

### Planned storage

The storage DDL is specified in the technical specification. Implementation uses these
logical tables and avoids the existing generic `messages` name:

```text
world.db
  comm_threads      1 ---- * comm_messages
       |                          |
       |                          +---- * comm_audiences (resolved once)
       |                          +---- * comm_deliveries (outcome; delivered=row grant)
       |                          +---- * comm_disclosure_authorities
       |                          `---- * comm_disclosures (same-case grant)
       |
       `---- stable refs <---- causal_links ----> events/action_proposals/memories/ledger_transaction refs

  schema_migrations
       migration_number + checksum + applied_at + runner_version

operator-workspace.db                 [separate connection and file]
  investigations 1 -- * items
  investigations 1 -- * hypotheses
  saved_views
  operator_audit (append-only truth/denial/export audit)
```

All communication primary keys and causal stable references are deterministic or assigned
by the single writer in stable order. Foreign keys remain enabled. Indexes cover due
deliveries, recipient grants, thread chronology, and inbound/outbound causal traversal.
Canonical non-null SHA-256 dedupe keys enforce audience, delivery, disclosure, and causal
identity; nullable-column `UNIQUE` behavior is never an exactly-once mechanism.

### Migration review

The migration registry is immutable after release. Each migration declares its number,
checksum, `apply(connection)` function, and schema-only compatibility constraints. Startup:

```text
open database
  -> enable foreign keys / configured journaling
  -> read migration ledger
  -> checksum mismatch? ------------> abort, diagnostic, no mutation
  -> database newer than binary? ---> abort, upgrade-required
  -> pending migration
       -> BEGIN IMMEDIATE
       -> apply once
       -> validate schema/invariants
       -> record checksum
       +-- success -> COMMIT
       `-- failure -> ROLLBACK entire migration
```

Fresh schema creation and upgrade from every supported historical fixture must yield the
same normalized schema. Migration tests use copied real fixtures, never only synthetic SQL.
Schema 6-11 databases first pass boundary verifiers and receive explicit
`application_mode=adopted_legacy` ledger rows; those rows assert verified equivalence, not
that the new migration modules historically ran. Partial/ambiguous legacy states fail
before schema 12.

## UI implementation specification

### Route workspaces

```text
/runs/:runId
+-- /overview
+-- /world
+-- /people/:agentId?
+-- /organizations/:organizationId?
+-- /markets
+-- /politics-law
+-- /news-communications/:threadId?
+-- /investigations/:investigationId?
`-- /experiments/:experimentId?
```

The persistent shell carries run/fork selector, live/replay badge, tick scrubber, global
search, connection state, and command palette. Run, tick, selected object, comparison run,
and replay/live mode are URL-addressable. Selecting a historical tick exits live-follow and
requires an explicit action to resume it.

The semantics-8 gate fully implements Overview, News & Communications, and Investigations.
Other routes mount the shell and preserve/rehouse current panels; new deck.gl layers and
full-depth cross-domain redesigns follow after the causal proof.

### Investigator workspace wireframe

```text
+----------------------------------------------------------------------------------+
| Run: baseline-v8  LIVE  Tick 024/030 [<] [====o====] [>]  Search...  Cmd-K       |
+-------------------+--------------------------------------+-----------------------+
| Filters           | Causal graph                         | Inspector             |
| [x] observed      | msg:88 --observed--> memory:201      | Event ev:024:771      |
| [x] motivated     |                    --triggered-->    | --------------------  |
| [ ] inferred      | belief:44 --motivated--> proposal:912| Message delivered     |
| Authority: all    |           --triggered--> event:771   | Sender: agent:12      |
| Depth: 3          | event:771 --settled--> ledger:4401   | Recipients: 2         |
|                   |                                      | Body: [policy result] |
+-------------------+--------------------------------------+-----------------------+
| Chronological evidence table                                                     |
| tick | type | subject | relation | object | authority | confidence | provenance   |
+----------------------------------------------------------------------------------+
| Hypothesis: "Supplier warning caused inventory cut" [Save in operator workspace] |
+----------------------------------------------------------------------------------+
```

The causal graph has a synchronized semantic table with the same selection. Keyboard
navigation, focus visibility, reduced motion, color-independent relation labels, renderer
fallback, and a usable 390-pixel layout are release requirements. Post-gate map layers must
follow the same table-equivalence rule.

### Frontend branch map

```text
route loader / component
  +-- valid run and tick
  |     +-- query pending ------> skeleton with preserved shell
  |     +-- empty projection ---> contextual empty state, no fake zero
  |     +-- query error --------> retry + diagnostic ID
  |     `-- success
  |           +-- visual renderer supported -> map/graph/chart + table
  |           `-- renderer failure ---------> error boundary + complete table
  +-- unknown stable ref -------> not-found inspector; keep surrounding context
  +-- forbidden message body ---> policy explanation; no body request retry loop
  `-- stale cursor/version -----> suspend deltas, backfill, then resume
```

### Frontend dependency policy

- Pin exact major versions and commit generated OpenAPI types.
- CI regenerates types and fails on drift.
- Post-gate deck.gl work uses `OrthographicView` over synthetic coordinates; geographic
  projection is not implied.
- Sigma consumes a Graphology graph created from bounded server responses. The client never
  downloads the entire causal relation table.
- Recharts remains the metric/chart layer.
- No Redux-style mirror of server truth is introduced.

## Security and privacy review

The simulation contains fictional private communications, but information-flow correctness
is a research invariant rather than cosmetic privacy.

| Consumer | Default access | Enforcement |
|---|---|---|
| Sender agent | Own committed message fields at/after creation | Explicit `sender` access basis |
| Recipient agent | Authorized fields only at/after delivered grant tick | Agent knowledge projection before prompt construction |
| Non-recipient agent | No message-specific existence, URL, subject, body, identities, or thread entry | Same projection; uniform absence rather than redacted text |
| Public principal | Public fields only at/after resolved publication tick | Explicit `public_release` access basis |
| News agency agent | Public material and disclosed/cited content only | Newsroom-specific policy view |
| Oracle/report generator | Policy-scoped aggregate, no unrestricted body dump | Dedicated report projection |
| Local operator truth view | Privileged access, clearly labeled | Audit append commits in the separate operator store before response |
| Hosted researcher | Tenant, role, investigation, and disclosure scoped | PostgreSQL row-level security plus application audit |
| Research export | Policy-selected content and redaction manifest | Deterministic export policy |

The normative field-by-consumer/as-of matrix is the one in the
[30-tick protocol](../world-os/30-TICK-RESEARCH-PROTOCOL.md#8-as-of-privacy-assertions).
Tests cover subject, body, identities, existence, thread chronology, message URLs/query
keys, browser persistence, exceptions, logs, metrics, traces, and exports independently.
Denied lookups use safe correlation hashes rather than raw private identifiers.

Authorized operational logs may contain scoped IDs; denied lookups contain only correlation
hashes. No log contains private subjects, bodies, identities, or recipient lists.
All endpoints reuse the existing hosted session, membership, tenant, and run authorization
boundary. State-changing workspace requests require the existing CSRF contract. WebSocket
Origin and session are validated before accept; authorization is rechecked on subscribe and
when the session identity changes. Expired, revoked, disabled, and cross-tenant sessions are
tested across REST, WebSocket, and workspace routes.

Authorized bodies remain untrusted quoted world data. Prompt assembly delimits them from
system and tool instructions, and message text cannot expand the action allowlist, change
authorization, or request undisclosed facts. Scripted and live-provider tests include
prompt-injection and fake-tool bodies.

## Failure modes

| Code path | Realistic production failure | Test | Handling | User-visible behavior | Critical gap after plan? |
|---|---|---|---|---|---|
| Migration startup | Power loss or exception after partial DDL | Historical fixture + injected migration failure | One transaction; checksum ledger written last | Run refuses to open with migration diagnostic | No |
| Semantics selection | Binary does not know recorded semantics | Unit + replay fixture | Fail before tick mutation | Upgrade/compatible-binary message | No |
| Inbox selection | Duplicate execution after resume | State machine + every-phase fault injection | Unique delivery key and phase cursor | No duplicate; resume receipt available | No |
| Audience resolution | Organization changes membership on delivery tick | Ordering boundary tests | Static phase order and membership snapshot | Inspector shows grant basis and tick | No |
| Delivery transaction | Safe event writes but grant fails | Transaction integration test | Atomic rollback of delivery/event/links | Structured run failure; safe retry | No |
| Message authorization | Any private field/existence leaks before grant or to wrong view | Exhaustive field/as-of matrix + generated state machine | Central deny-by-default `AccessBasis` policy | Uniform not-found; safe audit correlation | No |
| Public/reply/forward | Creation-time publication or implicit thread-history grant | Derivation/publication boundary tests | N+1 publish; reply-to-sender; new forward thread/message | Exact publication/provenance chronology | No |
| Death/dissolution | Recipient dies between send and delivery | State machine transitions | Historical mailbox inactive; deterministic no/read rules | Timeline explains non-delivery/inactive mailbox | No |
| Forward/discovery | Forward silently grants access to original | Unit + stateful authorization tests | New message/disclosure row with provenance | Inspector shows explicit disclosure chain | No |
| Typed command parse | Provider emits missing or unknown discriminator | Characterization/property tests | Stable rejected result; no mutation | Agent action listed as rejected, not crash | No |
| Handler exception | Domain write partially commits | Savepoint regression tests | Roll back handler; preserve prior tick work as specified | Run diagnostic with action ID | No |
| Causal write | Dangling/cross-run endpoint, duplicate nullable tuple, or invalid authority/relation | Unit/property/reconciliation tests | Endpoint registry, non-null hash key, and normative matrix | Link rejected with structured failure | No |
| Causal traversal | Dense graph exhausts memory/UI | Depth/node/time cap tests | Server truncates deterministically with continuation metadata | Visible “bounded result” notice | No |
| Projection builder | Live and replay code diverge | Equality/golden tests | One shared builder package | Same snapshot or release fails | No |
| WebSocket delivery | Gap, duplicate, reconnect, or stale version | Scripted transport + Playwright | Stop reducer, REST backfill/invalidate | Reconnecting badge; no silent stale view | No |
| Browser route | Stable ref was deleted/corrupt | Router/Playwright test | Not-found boundary retains run context | Recoverable inspector state | No |
| Graph renderer | WebGL unavailable or throws | Component/E2E fallback test | Error boundary and semantic table | Full table remains usable | No |
| Operator note save | Two tabs edit same hypothesis | Store integration + Playwright | Optimistic version conflict | Compare/reload prompt, no overwrite | No |
| Parquet export | Interrupted write leaves plausible bundle | Export fault test | Stage then atomically publish manifest last | Incomplete bundle rejected | No |
| Local inference | One provider request times out | Dispatcher integration test | Structured cancellation/retry policy; no remote mutation | Run reports provider failure and resumable state | No |
| Performance overload | 1,000 agents exceed memory/time budget | Benchmark gate | Bounded bodies/links, periphery schedule, profiling receipt | Benchmark fails release; UI shows progress | No |

Every listed failure has a planned test and a defined handler. There are zero remaining
silent, unhandled, untested critical gaps in the reviewed scope.

## Test review

### Coverage diagram

The repository has strong coverage for the current kernel, but all semantics-8 branches
below are new and therefore start as planned gaps. Each gap maps to an implementation task
and must land with its code; none is deferred until after the feature.

```text
CODE PATHS                                         USER FLOWS
[GAP] migration registry                          [GAP] [->E2E] Open/fork semantics-8 run
  +-- fresh schema                                  +-- create or select run
  +-- verified legacy adoption                      +-- see compatible version status
  +-- checksum mismatch                             `-- incompatible run fails clearly
  `-- failure rollback

[GAP] static phase runner                         [GAP] [->E2E] Pause/resume/fork/replay
  +-- semantics < 8 preserves order                 +-- pause at every phase boundary
  +-- semantics 8 inbox phase                       +-- resume without duplicate effect
  +-- unknown semantics fails closed                `-- compare replay receipt
  `-- exception persists completed cursor

[GAP] typed registry                              [GAP] Agent communicates normally
  +-- legacy mapping remains compatible             +-- scheduled deliberation sees inbox
  +-- each known discriminated model                 +-- sends within deterministic quota
  +-- invalid/unknown action                         +-- message changes belief/memory
  `-- handler/savepoint exception                    `-- later domain action cites cause

[GAP] communication state machine                 [GAP] [->E2E] Private message journey
  +-- send/N+1/read/reply/forward                     +-- recipient sees fields only after grant
  +-- direct/org/public publication                  +-- non-recipient sees no existence/URL
  +-- join/leave/death/dissolution                   +-- operator truth is visibly privileged
  +-- field/as-of matrix                             `-- provenance remains inspectable
  `-- checkpoint/fork/resume/replay

[GAP] causal graph                                [GAP] [->E2E] Investigation journey
  +-- valid relation/authority combinations          +-- select event from chronology
  +-- dangling/cross-run rejection                   +-- traverse bounded causes/effects
  +-- cycles and bounds                              +-- synchronize graph and table
  `-- deterministic inferred labeling                `-- save versioned hypothesis

[GAP] projections and transport                   [GAP] [->E2E] Live Observatory
  +-- live == replay == rebuilt                      +-- bootstrap route
  +-- contiguous cursor reduction                    +-- receive live delta
  +-- gap/duplicate/stale version                     +-- drop/reconnect/backfill
  `-- authorization on snapshot/delta                `-- scrub history then resume live

[GAP] research export                            [GAP] Export evidence
  +-- hash-contract-v1 classification                +-- choose policy scope
  +-- redaction manifest                             +-- interrupted export rejected
  +-- interrupted publish                            `-- DuckDB queries documented tables
  `-- same state produces same bundle hash

[GAP] provider behavior [->EVAL]
  +-- persona-consistent reply
  +-- valid command selection
  +-- no knowledge-boundary leakage
  `-- timeout/resume metadata

COVERAGE BEFORE IMPLEMENTATION: 0 new semantics-8 paths shipped
RELEASE REQUIREMENT: 100% of diagram branches exercised at the assigned layer
LEGEND: [->E2E] browser or full-stack integration; [->EVAL] live-provider quality smoke
```

### Unit and characterization tests

| Planned test file | Required assertions |
|---|---|
| `tests/test_action_command_registry.py` | Legacy mappings produce unchanged result shapes; every discriminator resolves exactly once; invalid/unknown inputs never mutate; savepoint rollback remains compatible |
| `tests/test_phase_specs.py` | Historical tables equal current phase order; semantics 8 inserts delivery before morning; unknown version rejected; table is immutable at runtime |
| `tests/test_communication_handlers.py` | Length/quota/typed-audience validation, N+1 public publication, deterministic reply/forward derivation, non-null dedupe keys, safe event metadata, atomic resolution reconciliation |
| `tests/test_communication_policy.py` | Every field/principal/as-of/access-basis cell, org snapshot, same-case discovery, death, truth audit, and no subject/body/identity/existence/URL/persistence/error/log/trace/export leak |
| `tests/test_causal_links.py` | Endpoint registry, direction/relation/authority/provenance matrix, confidence and temporal rules, non-null dedupe, same-run rule, recorded DAG/inferred cycle behavior, deterministic order |
| `tests/test_projection_builders.py` | Live/replay/rebuild equality under full run/fork/semantics/projection/policy/view/cursor envelope, empty/maximum states, lineage rejection |
| `tests/test_operator_workspace.py` | Separate connection, stable refs, optimistic conflicts, audit trail, no world mutation import/path |
| `tests/test_research_export.py` | Stable row order/hashes, manifest-last publish, interruption rejection, redaction accounting, DuckDB readability |

### Stateful and fault-injection tests

Create `tests/stateful/test_communication_state_machine.py` using a small reference model.
Generated rules cover direct/org/public send, tick, deliver/publish, read, reply, forward,
disclose, join, leave, death, organization dissolution, pause, checkpoint, fork checkpoint,
resume, and replay. Invariants run after every transition:

- authorization equivalence between reference model and database;
- exactly-once delivery and grant uniqueness;
- valid causal endpoints and disclosure provenance;
- every subject/body/identity/existence/URL/query/persistence/error/log/trace/export access
  equals the as-of reference matrix;
- balanced ledger after any message-motivated economic action;
- same seed/config/provider receipt produces the same `hash-contract-v1` authoritative
  hashes; source checkpoint rows never change when a fork upgrades;
- observer/query activity has no effect on world results;
- rebuilt projection equals incremental projection;
- replay ends with table-for-table equality for authoritative tables.

Create `tests/test_phase_resume_faults.py` to inject an exception before and after every
phase-side-effect boundary and then resume. It must prove no lost or duplicated delivery,
event, action, memory, ledger entry, or checkpoint cursor.

### Scripted 30-tick release scenario

Implement the approved
[supplier-warning treatment/control protocol](../world-os/30-TICK-RESEARCH-PROTOCOL.md)
under `tests/scenarios/`. It freezes a tick-4 common checkpoint, no-message and neutral
controls buying 10 goods units, a private-warning treatment buying 5, exact ledger and
inventory effects, five qualified causal edges, alternative-explanation controls, complete
privacy matrix, cross-branch diff allowlist, and canonical authoritative/projection hashes.
Any clipping, unrelated row difference, missing/duplicate edge, privacy exception, or
uninterrupted/resumed/forked/replayed hash mismatch refutes the scenario.

### Browser and transport tests

Add Playwright tests under `dashboard/tests/e2e/` with a scripted projection/WebSocket
server for precise failure cases and a small real simulation for end-to-end truth:

- open canonical `/runs/:runId/...` routes and restore run/fork/tick/selection state;
- navigate event -> causal graph -> authorized message -> domain effect;
- confirm every role/field/as-of matrix cell across bootstrap, delta, URL/query key,
  persistence, errors, logs, traces, and exports;
- disconnect after cursor N, miss deltas, reconnect, backfill, and reach N+k once;
- reject duplicate/conflicting delta and unsupported projection version;
- pause, resume, fork before/after delivery, prove source immutability/cursor lineage, scrub
  history, and explicitly re-enter live-follow;
- handle empty world, one node, bounded/truncated graph, 10,000-row virtualized table, and
  renderer failure fallback;
- resolve optimistic hypothesis conflict without overwriting either version;
- operate primary investigator flow with keyboard only and at 390-pixel viewport.

Record Playwright traces on first retry and retain them as CI artifacts on final failure.

### Live-provider eval smoke

Run a separate ten-tick live-provider smoke because prompt and tool-schema behavior is
affected. Record provider/model/build identifiers and evaluate:

- communication command validity rate;
- persona-consistent, contextually relevant reply quality;
- whether message evidence changes subsequent decisions plausibly;
- absence of facts outside the agent knowledge projection;
- timeout, retry, and resume behavior.

Provider availability may produce an explicit `unavailable` or approved `waived` receipt;
it may not weaken or replace the scripted deterministic release gate. Only a completed,
passed smoke permits a provider-ready claim. A deterministic-ready release may be reported
separately, but `unavailable` or `waived` blocks the provider-readiness portion of Gate 5.

## Performance review

### Accepted budgets

| Scenario | Gate |
|---|---|
| 100 cognitive agents, scripted interactive tick | Finalized-tick p95 under 2 seconds; p99 under 5 seconds |
| 1,000 total agents (100 strategic + 900 periphery), 365 ticks | Under 15 minutes, under 2 GB peak process-tree RSS, under 1.5 GB total run footprint (SQLite + WAL + SHM + checkpoints + provider/script receipts; excludes operator workspace, exports, logs) |
| Live projection freshness | FINALIZE commit to matching delta applied by local benchmark subscriber p95 under 2 seconds over 30 ticks after one warmup |
| Local route bootstrap p95 | Under 750 ms for bounded default projection |
| Message body | At most 2,000 characters |
| Communication generation | At most 3 communication actions per cognitive agent per tick; at most 1 per periphery wake |
| Causal neighborhood | Server-enforced depth, node, edge, and time caps |

Provider latency and cost are reported separately from deterministic kernel timing.

`benchmarks/world-os-v8-standard.json` freezes exact hardware/OS/Python/SQLite/WAL
settings, dependency/fixture/seed hashes, cohort split, message/recipient/body/causal/event
density, periphery wakes, cold/warm cache rules, at least five full-run repetitions, 30
route/query samples, nearest-rank percentiles, peak process-tree RSS, and DB+WAL+SHM+
checkpoint+receipt storage accounting. Raw samples, query plans, machine receipt, and
manifest hash are retained. A result without this manifest is diagnostic, not a gate.

### Query and memory controls

- Index the due-message scan on status/delivery tick and stable ID; never scan all message
  bodies per tick.
- Resolve deliveries in batches, but preserve a documented stable ordering.
- Batch causal endpoint validation and projection reads to avoid N+1 queries.
- Fetch message bodies only after an authorization decision and only for requested IDs.
- Paginate/seek chronological tables; do not use unbounded offset scans for large runs.
- Bound graph responses on the server and render only the returned neighborhood.
- Keep query cache keys versioned by run/tick/projection; evict historical snapshots under a
  documented memory budget.
- Stream Parquet tables and publish the manifest last rather than materializing the entire
  bundle in memory.
- Run `EXPLAIN QUERY PLAN` assertions for the due-delivery and causal-neighborhood queries.

### Scale-out trigger

Profile first. An optional remote inference dispatcher may be implemented only if the
accepted 1,000-agent benchmark shows inference scheduling—not SQLite writes, projections,
or browser rendering—is the dominant bottleneck and local structured concurrency cannot
meet the gate. Remote workers receive immutable prompt/input envelopes and return proposals;
they never receive a writable database connection.

## Worktree parallelization strategy

### Dependency table

| Step | Modules touched | Depends on |
|---|---|---|
| 0. Frozen research protocol | `docs/world-os/`, design approval artifact | — |
| A. Baseline receipts and migration registry | `engine/`, `tests/fixtures/`, `tests/` | 0 |
| B. Typed command compatibility layer | `engine/commands/`, `engine/actions.py`, `tests/` | A |
| C. Static semantics phase runner | `world/`, `tests/` | A |
| D. Communication persistence and handlers | `communications/`, `engine/`, `tests/` | A, B |
| E. Authorization and agent knowledge | `communications/`, `world/`, `tests/` | C, D |
| F. Causal relations and traversal | `causal/`, `communications/`, `tests/` | A, D |
| G. Shared projections and transport | `server/`, `communications/`, `causal/`, `tests/` | E, F |
| H. Operator workspace and export | `operator_workspace/`, `research/`, `tests/` | A; stable-ref contract from F |
| I. Route shell and typed data client | `dashboard/src/app/`, `dashboard/src/generated/`, `dashboard/tests/` | G API contract |
| J. Workspaces and visualizations | `dashboard/src/workspaces/`, `dashboard/src/visualizations/`, `dashboard/tests/` | I; projection shapes from G |
| K. Stateful/replay/performance release harness | `tests/stateful/`, `tests/scenarios/`, benchmark tooling | D, E, F, G, H |
| L. Browser/eval release receipt | `dashboard/tests/e2e/`, eval tooling, docs | I, J, K |

### Parallel lanes

```text
Foundation:  A -> B -> D -> E
             A -> C -> E
Causality:   A -> D -> F
             E + F -> G
Research:    A + F -> H
Frontend:    G -> I -> J
Release:     D + E + F + G + H -> K
             I + J + K -> L
```

- Lane A: baseline/migrations -> typed commands -> communication -> authorization
  (sequential because `engine/`, `communications/`, and semantics contracts overlap).
- Lane B: static phase extraction after baseline; join Lane A before authorization/resume
  integration.
- Lane C: causal layer after communication schema; then projections/transport.
- Lane D: operator workspace/export after migration foundation and stable-reference contract.
- Lane E: frontend shell after API contract; then visual workspaces.
- Lane F: release harness after backend lanes; final browser/eval receipt after frontend.

Freeze step 0 first, then launch A's baseline work. After its migration/stable-reference
contracts merge, B/C/D
can proceed in separate worktrees. Merge communication + phases + causal + operator work,
then build projections. Frontend shell can start against a committed OpenAPI/scripted-server
contract while backend projection implementation proceeds, but generated-type drift must be
resolved before merge. Finish with the integrated harness and release receipt.

Conflict flags:

- Communication and causal lanes both touch `communications/`; agree on the stable-reference
  interface first or keep their integration commit sequential.
- Phase and authorization lanes both touch `world/`; phase extraction merges first.
- Projection and frontend lanes share the OpenAPI artifact, not implementation directories;
  treat the generated file as backend-owned until the contract is frozen.

## Implementation Tasks

Synthesized from this review's findings. Each task is build-actionable and belongs in the
first-lake branch; checkbox it only when its verification command and receipt are green.

- [x] **T0 (P1, human: ~2h / CC: ~20min)** — Research contract — Approve and freeze the 30-tick treatment/control protocol
  - Surfaced by: adversarial completeness review — implementation previously began before the causal claim, controls, refutation thresholds, privacy surface, and evidence hashes were predeclared.
  - Files: `docs/world-os/30-TICK-RESEARCH-PROTOCOL.md`, design/PRD approval status, protocol manifest.
  - Verify: reviewer can neither make treatment/control pass without the required warning chain nor produce the quantity change outside the declared diff allowlist; protocol hash is recorded before T1.

- [ ] **T1 (P1, human: ~2d / CC: ~4h)** — Compatibility — Freeze baseline contracts and fixtures
  - Surfaced by: code quality review — the high-fan-out action facade and historical phase order must be characterized before refactoring.
  - Files: `tests/test_actions.py`, `tests/test_world_loop.py`, `tests/fixtures/schemas/`, replay fixtures and table-hash helpers.
  - Verify: existing suite plus new characterization tests pass against `c9f0b23` behavior; fixture manifest records provenance and hashes.

- [ ] **T2 (P1, human: ~3d / CC: ~6h)** — Storage — Introduce immutable migration registry and schema migration ledger
  - Surfaced by: architecture/adversarial review — schema 12 needs checksums, transactional application, historical fixture equivalence, verified `adopted_legacy` bootstrap, and future-version rejection.
  - Files: `engine/migrations/`, the sole aggregate schema-12 communication/causal migration and verifier, `engine/schema.py`, `tests/test_migrations.py`, `tests/fixtures/schemas/`.
  - Verify: communication and causal schema fragments are assembled once before the immutable v12 checksum is frozen; fresh/upgraded normalized schemas match; rollback, no-op, checksum mismatch, and future-version cases pass. T5/T8 may contribute fragments and tests but do not own another v12 migration.

- [ ] **T3 (P1, human: ~2d / CC: ~4h)** — Scheduler — Extract versioned static `PhaseSpec` tables and resumable runner
  - Surfaced by: architecture review — semantics 8 needs inbox delivery before morning without changing historical runs.
  - Files: `world/phases.py`, `world/loop.py`, `tests/test_phase_specs.py`, `tests/test_phase_resume_faults.py`.
  - Verify: historical phase receipts remain identical; fault injection before/after every phase resumes exactly once.

- [ ] **T4 (P1, human: ~3d / CC: ~6h)** — Commands — Add discriminated Pydantic models and registry behind the compatibility facade
  - Surfaced by: code quality review — mapping-shaped LLM actions need typed validation without breaking existing callers/results.
  - Files: `engine/commands/`, `engine/actions.py`, `LegacyHandlerAdapter`, `tests/test_action_command_registry.py`, touched command tests.
  - Verify: all existing action tests pass; exact mapping-input, result-shape, and savepoint compatibility; registry completeness; invalid/unknown inputs; body-free communication proposal/result/error persistence; and rollback cases pass.

- [ ] **T5 (P1, human: ~4d / CC: ~8h)** — Communications — Add thread, message, audience, delivery, and disclosure persistence
  - Surfaced by: architecture/adversarial review — asynchronous communication needs normalized audience keys, conditional checks, typed same-case disclosure authority, and reconciled exactly-once outcomes without nullable uniqueness.
  - Files: schema fragment supplied to T2's sole v12 aggregator, `communications/models.py`, `communications/repository.py`, `tests/test_communication_storage.py`.
  - Verify: foreign keys/index plan, non-null dedupe keys, audience/visibility/status checks, same-case disclosure, resolution reconciliation, body limits, and atomic persistence tests pass.

- [ ] **T6 (P1, human: ~4d / CC: ~8h)** — Communications — Implement send, reply, forward, quota, and scheduled delivery handlers
  - Surfaced by: data-flow/adversarial review — communication must enter through ordinary commands; public N+1 release and reply/forward derivation must be deterministic; outcomes/grants/events/causes commit atomically.
  - Files: `communications/handlers.py`, `communications/delivery.py`, command models/registry, `tests/test_communication_handlers.py`.
  - Verify: typed direct/org/public audiences, same-tick rejection, public publication, reply-to-sender, new-thread forward, due ordering, quotas, provenance, rollback, and exact-resume tests pass.

- [ ] **T7 (P1, human: ~3d / CC: ~6h)** — Information policy — Enforce immutable grants and knowledge-safe projections
  - Surfaced by: security/adversarial review — every sender/delivery/public/disclosure/operator `AccessBasis`, field, consumer, and as-of tick needs one deny-by-default policy and non-authoritative audit path.
  - Files: `communications/policy.py`, `communications/projections.py`, prompt/context builders, `tests/test_communication_policy.py`.
  - Verify: exhaustive matrix has zero subject/body/identity/existence/URL/query/persistence/error/log/metric/trace/export leaks and operator truth cannot respond unless its sidecar audit append succeeds.

- [ ] **T8 (P1, human: ~3d / CC: ~6h)** — Causality — Add validated stable references and provenance-bearing causal links
  - Surfaced by: architecture/adversarial review — investigations require a normative endpoint/direction/relation/authority/provenance matrix, non-null dedupe, recorded DAG rules, and deterministic bounded traversal.
  - Files: schema fragment supplied to T2's sole v12 aggregator, `causal/links.py`, `causal/traversal.py`, domain integration points, `tests/test_causal_links.py`.
  - Verify: edge matrix, engine/actor/model provenance checks, temporal order, dangling/cross-run rejection, recorded DAG/inferred cycles, bounds/order, time-out labeling, dedupe, and dual-write compatibility pass.

- [ ] **T9 (P1, human: ~3d / CC: ~6h)** — Agent behavior — Integrate inbox observations into scheduled deliberation and memory
  - Surfaced by: product/adversarial gate — messages must alter beliefs/decisions through ordinary schedules without one extra LLM call per message or branch-label leakage.
  - Files: agent deliberation/context/memory modules, communication projections, scripted policies, related tests.
  - Verify: canonical policy input contains no excluded branch/protocol field; authorized bodies are delimited untrusted data; prompt-injection/fake-tool/secret-request probes cannot change system, tool, or authorization rules; relabel, body-swap, and withheld-delivery metamorphic probes make quantity follow authorized content; quotas/periphery wakes and observation -> belief -> proposal links pass.

- [ ] **T10 (P1, human: ~4d / CC: ~8h)** — Read model — Build shared, versioned live/replay projection functions and REST adapters
  - Surfaced by: architecture/adversarial review — bootstrap, history, replay, and reconstruction need one canonical run-scoped route table and full run/fork/semantics/projection/policy/view/cursor representation.
  - Files: `server/projections/`, `server/v2_api.py`, OpenAPI contract, `tests/test_projection_builders.py`, API tests.
  - Verify: canonical run-local `/api/v2` handlers and hosted `/api/v2/tenants/{tenant}/runs/{run}/world/...` prefix, live/replay/rebuild golden equality under the same view key, existing session/membership/tenant/run authorization, expired/revoked/disabled/cross-tenant denial, policy scoping, empty/boundary states, pagination, and lineage rejection pass.

- [ ] **T11 (P1, human: ~3d / CC: ~6h)** — Transport — Publish ordered WebSocket deltas with cursor recovery
  - Surfaced by: failure review — gaps, duplicates, stale versions, pauses, and reconnects must never silently corrupt the browser view.
  - Files: `server/controller.py`, projection delta helpers, WebSocket routes, scripted transport tests.
  - Verify: one global run/fork cursor, advance envelopes, full-lineage contiguous apply, duplicate/conflict rejection, retained/missed backfill, fork isolation, pause heartbeat, Origin/session validation before accept, and expired/revoked/disabled/cross-tenant reauthorization pass.

- [ ] **T12 (P1, human: ~3d / CC: ~6h)** — Operator workspace — Store investigations separately with optimistic concurrency and audit
  - Surfaced by: state-ownership review — analyst hypotheses are valuable but must not become simulated truth.
  - Files: `operator_workspace/store.py`, `operator_workspace/hosted.py`, operator API/tests, hosted RLS migrations/policies where applicable.
  - Verify: separate-file enforcement, stable refs, two-editor conflict, existing session/membership/tenant/run auth, CSRF on every state-changing request, expired/revoked/disabled/cross-tenant denial, audit, and no-world-write tests pass.

- [ ] **T13 (P1, human: ~3d / CC: ~6h)** — Research export — Produce deterministic content-addressed Parquet bundles
  - Surfaced by: product/performance/adversarial review — replay claims need an exhaustive table/column classification and typed canonical hash, while research needs queryable output without making DuckDB operational truth.
  - Files: `research/hash-contract-v1.json`, replay hash helpers, `research/export_bundle.py`, export schemas/manifest docs, `tests/test_research_export.py`.
  - Verify: new unclassified storage fails CI; identical state/view yields identical authoritative/projection/bundle hashes; wall-clock exclusions, interruption, redaction, and DuckDB-read cases pass.

- [ ] **T14 (P1, human: ~4d / CC: ~8h)** — Frontend foundation — Add route shell, query client, generated types, and cursor reducer
  - Surfaced by: UI/data-flow review — URL state and server state need explicit, non-duplicated ownership.
  - Files: `dashboard/src/app/`, `dashboard/src/generated/`, existing Observatory integration, frontend unit tests, package/CI config.
  - Verify: OpenAPI drift check, route restoration, stale/gap reducer, error/empty/loading boundaries, and existing frontend tests pass.

- [ ] **T15 (P1, human: ~5d / CC: ~10h)** — Observatory — Ship the three gate workspaces and synchronized causal graph/table
  - Surfaced by: product/UI/adversarial scope review — causal proof needs full Overview, News & Communications, and Investigations; broad new map/entity/market redesign would dilute the gate.
  - Files: `dashboard/src/workspaces/`, causal `dashboard/src/visualizations/`, shell navigation, component tests.
  - Verify: canonical routes, field-policy inspector, graph/table selection parity, renderer fallback, keyboard/reduced-motion/color checks, bounded large-state behavior, and 390px layout pass; other routes preserve current panels.

- [ ] **T16 (P1, human: ~5d / CC: ~10h)** — Verification — Add Hypothesis reference model, phase faults, and the 30-tick causal scenario
  - Surfaced by: test/adversarial review — temporal membership/death/publication/fork/resume interactions and the predeclared treatment/control effect cannot be covered reliably with examples alone.
  - Files: `tests/stateful/`, `tests/scenarios/`, replay/table-hash helpers, benchmark fixture.
  - Verify: generated sequences preserve the full six-basis field/as-of and closed causal invariants; branch-blind input/rule hash and all metamorphic probes pass; source checkpoint remains unchanged; treatment/controls meet exact quantities/diffs and five edges; uninterrupted/resumed/forked/replayed runs match `hash-contract-v1` within branch.

- [ ] **T17 (P1, human: ~4d / CC: ~8h)** — Browser verification — Add Playwright transport and investigator journeys
  - Surfaced by: test review — common flows cross route, REST, WebSocket, policy, visualization, and sidecar boundaries.
  - Files: `dashboard/tests/e2e/`, Playwright config/fixtures, scripted server, CI artifact configuration.
  - Verify: every role/field/as-of surface including URL/query/persistence/error/trace, reconnect, fork lineage/source immutability, conflict, accessibility, mobile, and real-sim flow passes; safe traces retained on failure.

- [ ] **T18 (P1, human: ~3d / CC: ~6h)** — Release evidence — Meet scale budgets and record live-provider smoke
  - Surfaced by: performance/eval/adversarial review — architecture claims require a versioned workload/machine/measurement manifest and raw receipts under scripted and real model behavior.
  - Files: `benchmarks/world-os-v8-standard.json`, benchmark/eval tooling, raw receipt schema, release manifest, operator docs, `docs/world-os/` status updates.
  - Verify: interactive p95/p99 plus 1,000-agent gates, query plans, exact total-run-footprint/RSS/FINALIZE-to-applied-delta/bootstrap budgets, manifest/raw samples, and deterministic replay receipt are recorded. The separate ten-tick provider report records `passed`, `unavailable`, or approved `waived`; only `passed` satisfies provider readiness.

## Implementation sequence and merge gates

1. **Gate -1 — Frozen claim (approved 2026-07-18):** T0 approves/hashes the
   treatment/control protocol. No implementation task starts before this gate.
2. **Gate 0 — Baseline:** T1 establishes compatibility receipts. No refactor merges before
   this gate.
3. **Gate 1 — Versioned foundation:** T2-T4 land. Historical runs replay identically and
   semantics 8 can be selected without domain behavior yet.
4. **Gate 2 — Private causal core:** T5-T9 land. Focused integration tests prove each
   delivery/publication -> knowledge -> proposal -> event/ledger link, field-policy rule,
   and metamorphic branch-blind policy contract in isolation. The complete three-branch
   scenario, cross-branch diff, and replay/hash oracle wait for T16 at Gate 5.
5. **Gate 3 — Read and research surfaces:** T10-T13 land. Projection equality, reconnect,
   operator separation, and deterministic bundle tests are green.
6. **Gate 4 — Interactive Observatory:** T14-T15 land the three full gate workspaces with
   scripted server first and small real simulation second.
7. **Gate 5 — Release receipt:** T16-T18 prove stateful, fork/replay, browser, performance,
   canonical hash, and deterministic release criteria. That permits a
   `deterministic-ready` semantics-8 receipt. Mark it `provider-ready` only when the
   separate live-provider smoke is completed and passed; `unavailable` or approved
   `waived` is explicit evidence but blocks that claim.

Each gate is independently revertible. A gate may add schema or behavior only under its
declared version and may not modify already released migration files.

## Test plan artifact summary

The QA-facing artifact for this review lists these affected routes:

- `/runs/:runId/overview` — full run health, live/replay state, freshness, and navigation.
- `/runs/:runId/news-communications/:threadId` — full authorized publication/delivery and disclosure history.
- `/runs/:runId/investigations/:investigationId` — full bounded graph/table, chronology, field policy, and hypothesis conflict.
- Other `/runs/:runId/...` routes — canonical shell, URL restoration, and preserved current-panel smoke only for this gate.

The critical QA path is message -> delivery -> observed memory/belief -> decision -> domain
event/ledger -> bounded causal trace, including unauthorized role, dropped connection,
pause/resume, replay, and keyboard-only variants.

## Retrospective learning

The current `main` history includes a recent Observatory activity-restoration fix. That is a
signal that inferred or placeholder activity can drift from measured simulation truth. This
plan is stricter in the same area: every UI datum comes from a named shared projection,
carries run/tick/version/cursor identity, and has live-versus-rebuilt equality tests. No
workspace may infer authoritative activity from presentation-layer heuristics.

## Adversarial Spec Review

Three fresh-context passes reviewed the design package across completeness, consistency,
clarity, scope, and feasibility. They produced 25 raw findings (several overlapped) at a
recorded 6/10 before their requested corrections. Those review findings were incorporated:

- the demo became a frozen, branch-blind treatment/no-message/neutral protocol with exact
  bodies, rule-contract hash, metamorphic probes, refutation thresholds, and diff allowlist;
- the access oracle now covers every field, tick, derived-message case, and all six
  `AccessBasis` values with operator audit outside replay truth;
- public/reply/forward timing, audience resolution, same-case disclosure, dedupe, and
  reconciliation are implementable SQLite contracts;
- causal endpoints, directions, authorities, provenance, temporal/cycle behavior, and five
  exact scenario edges are closed vocabularies;
- REST/UI routes, projection/snapshot/policy/view lineage, and global run/fork cursor are one
  contract;
- migration adoption, canonical hashes, merge gates, UI scope, and performance/storage/
  freshness oracles are falsifiable.

The third pass was the workflow's maximum review round. Its six final findings were patched
and verified with targeted cross-document searches and link/structure checks; no fourth
independent score was fabricated.

A subsequent full documentation sweep reconciled this plan with current `c9f0b23` runtime
boundaries. It fixed run-local versus hosted route ownership, made T2 the sole schema-12
migration/checksum owner, specified the legacy command adapter and body-free proposal
contract, reused hosted auth/CSRF/Origin controls, added prompt-injection boundaries, and
separated deterministic readiness from provider readiness when the live smoke is unavailable.

## Completion Summary

- Step 0: Scope Challenge — scope reduced to the communications and causal-observatory lake plus three full gate workspaces; full vision retained as sequenced semantics/post-gate UI.
- Architecture Review: 10 issues/choices resolved; 0 unresolved.
- Code Quality Review: 3 boundary/integrity issues resolved; 0 unresolved.
- Test Review: diagram produced, 5 coverage-gap groups resolved and mapped to T0-T18.
- Performance Review: 3 reproducibility/oracle issues resolved; 0 unresolved.
- NOT in scope: written with 12 explicit deferrals and rationale.
- What already exists: written with 9 reused capabilities.
- TODOS.md updates: 0 standalone items proposed; later lakes are product scope in the PRD, not orphan TODOs.
- Failure modes: 20 reviewed; 0 critical gaps remain in the plan.
- Outside voice: 3 fresh-context adversarial passes; 25 raw findings fixed; last independent score 6/10 before final corrections; max-round guard respected.
- Parallelization: Gate -1 first, then 6 lanes; 3 backend lanes parallel after Gate 0, frontend contract work overlaps projection implementation, integration sequential.
- Lake Score: 21/21 architecture, data, UI, test, and release recommendations chose the complete option.

## Review Log

- `gstack-review-log` recorded `clean`, 0 unresolved, 0 critical gaps, 21 findings,
  `SCOPE_REDUCED`, commit `c9f0b23`; `gstack-review-read` confirmed the same HEAD.
- QA artifact:
  `C:/Users/matri/.gstack/projects/alinojoumi8-agent-economy/matri-main-eng-review-test-plan-20260718-052128.md`.
- Task JSONL was not emitted because `jq` is unavailable. The skill explicitly forbids
  hand-written JSONL; install `jq` before `/autoplan` aggregation.
- The best-effort durable decision log could not run because this gstack installation is
  missing `lib/gstack-decision`; the clean engineering-review receipt is intact.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|---|---|---|---:|---|---|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | NOT RUN | — |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | NOT RUN | — |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAR | 21 issues resolved; 19 build tasks; 0 critical/unresolved |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | NOT RUN | — |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | NOT RUN | — |

- **VERDICT:** ENG CLEARED — adversarial corrections incorporated; ready for user approval.

NO UNRESOLVED DECISIONS
