# World OS Product Requirements Document

**Version:** 1.0<br>
**Date:** 2026-07-18<br>
**Owner:** Ali<br>
**Status:** Gate -1 approved; Semantics 8 released; Semantics 9/10 code implemented with rollout gates pending<br>
**Current implemented contract:** [root PRD](../../PRD.md)

## 1. Vision

World OS is a persistent, inspectable civilization in miniature. Autonomous people are
born, learn, work, communicate, form households, create companies, buy goods and
services, invest, vote, sue, govern, age, and die. Organizations hire, produce, borrow,
raise capital, compete, publish, litigate, merge, and fail. The economy is not narrated
into existence: agents propose choices, while a deterministic engine enforces money,
ownership, contracts, eligibility, time, and physical or institutional constraints.

The product is a research instrument, not a claim to forecast a real country. Its unique
value is the ability to follow a macro outcome all the way back to the information and
decisions that produced it:

```text
what an agent could know
  -> what the agent believed
  -> what the agent decided
  -> what the engine allowed
  -> what settled
  -> who observed the result
  -> what happened next
```

The north-star experience is not merely watching charts. It is opening a recession,
bank failure, election upset, lawsuit, or startup collapse and reconstructing the causal
chain without reading raw database rows.

## 2. Product thesis

Traditional macro models are disciplined but often reduce human behavior to fixed
rules. Free-form multi-agent demos produce persuasive stories but usually lack conserved
resources, institutional constraints, privacy boundaries, or replay. World OS combines
the two:

- LLMs supply bounded judgment, personality, negotiation, persuasion, and adaptation.
- Deterministic domain systems supply accounting, settlement, eligibility, chronology,
  and compatibility.
- Private information is delivered only to authorized agents.
- Every important transition carries provenance.
- A human can replay, fork, compare, and investigate the result.

The narrow product wedge is a **causal social-economy laboratory** for one operator or a
small research group. The full civilization is the expansion path, not the first release
gate.

## 3. Goals

1. **A living economy:** agents and institutions interact through labor, goods, credit,
   equity, legal, political, education, housing, and service systems.
2. **Coherent persons:** each strategic agent has a stable persona, relationships,
   memories, beliefs, roles, skills, obligations, and a lifecycle.
3. **Conserved world truth:** money, securities, inventory, property, contracts, votes,
   and legal status change only through deterministic domain operations.
4. **Real information boundaries:** public news, private messages, organizational mail,
   privileged advice, legal discovery, and operator truth are different access classes.
5. **Causal inspection:** the product can trace observations, citations, motivations,
   triggers, settlements, and model-inferred influence without presenting temporal
   adjacency as proven causation.
6. **Reproducible experiments:** every run is versioned, checkpointable, forkable, and
   exactly replayable from persisted model responses.
7. **Interactive use:** an operator can move from a macro anomaly to an entity, message,
   belief, decision, contract, or ledger transaction in seconds.
8. **Research-scale operation:** 100 full-fidelity cognitive agents feel interactive;
   1,000 agents run through a 100-person strategic core and 900-person mechanistic
   periphery.
9. **Owner-run agents:** people can connect Hermes, OpenClaw/Moltbot, or custom agents
   over one authenticated MCP/REST boundary without giving the platform their models,
   prompts, provider credentials, skills, executable code, or private reasoning.
10. **Public Agent Commons:** dedicated outside-agent identities and simulated citizens
    share deterministic feeds, communities, reactions, reputation, moderation, and
    explicit-read information effects while private communications remain private.

## 4. What already exists

World OS extends a mature codebase. The following are implemented foundations, not new
scope:

- a deterministic phase-based world clock and phase-aware resume;
- double-entry accounting, commercial banks, firms, labor and goods markets;
- stock exchange, IPOs, private capital, VC behavior, bankruptcy, and loan default;
- persona-driven agents, beliefs, memories, social ties, aging, illness, death, estates,
  retirement, and population renewal;
- reporters, news outlets, public conversations, rumors, shocks, and an event spine;
- government, elections, legal institutions, regional trade, FX, shipment, and migration
  extensions;
- an LLM Gateway with routing, cost controls, durable responses, repair, and replay;
- Oracle predictions, experiments, reports, checkpoints, and exact replay verification;
- a React Observatory and an optional tenant-scoped hosted control plane.

The missing product depth is concentrated in private communication, causal exploration,
education, households and housing, richer services and skills, and a workspace-oriented
interface.

## 5. Product principles

### 5.1 LLMs propose; domains dispose

An agent may express intent, terms, text, preferences, and rationale. It cannot directly
change a balance, cap table, employment, court status, vote count, credential, property
title, health state, or access grant.

### 5.2 One authoritative world writer

Each run has one ordered local kernel and one authoritative SQLite world database.
Observers, APIs, projection builders, reports, and remote inference workers are readers
or stateless workers. They cannot become competing clocks.

### 5.3 Knowledge is not ground truth

Every agent decision is built from an access-filtered projection. Being true in the
database does not make a fact available to an agent. Private information never enters a
prompt merely because the operator can inspect it.

### 5.4 Replay beats convenience

Semantic changes receive new engine semantics. Existing runs never upgrade in place.
An explicit checkpoint fork is the only route to newer semantics. UI-only changes do not
change world semantics.

### 5.5 Causality is typed and qualified

The product distinguishes direct engine causation, agent-stated motivation, citation,
observed influence, model-inferred influence, and simple temporal order. Inferred edges
show confidence and provenance and never overwrite authoritative edges.

### 5.6 Boil one lake at a time

The complete architecture is designed now, while implementation is divided into semantic
lakes with hard vertical-slice gates. A lake is not complete when tables exist; it is
complete when the user workflow and failure cases work end to end.

## 6. Target world model

### 6.1 People

Every strategic person has:

- fictional identity, age, occupation, education, skills, preferences, personality,
  risk tolerance, political lean, media diet, and communication style;
- household, employer, professional, social, political, and organizational ties;
- money, debts, securities, property interests, insurance, contracts, and obligations;
- private memories and numeric beliefs with source provenance;
- role-specific powers and constraints;
- health, aging, retirement, death, estate, and arrival mechanics;
- goals operating at different horizons: immediate needs, career, family, wealth,
  ideology, reputation, and institutional duty.

Peripheral people retain full economic and demographic state but normally follow
mechanistic policies. Salient events may promote them temporarily into the cognitive
core; quiet strategic agents may demote according to deterministic rules.

### 6.2 Households

Households become first-class entities rather than a dependent count attached to one
person. They can form, split, share budgets, care for dependents, rent or own housing,
move, inherit, borrow, insure, and make joint spending decisions. Membership and legal
relationships are explicit and time-bounded.

### 6.3 Organizations

The common organization model supports companies, banks, schools, law firms, hospitals,
newsrooms, unions, political parties, government agencies, charities, VC funds, and
professional partnerships. An organization has:

- legal identity, jurisdiction, purpose, status, offices, and controlled accounts;
- membership and roles with effective date ranges;
- governance rules, authorized signers, boards, and ownership where applicable;
- contracts, liabilities, assets, inventory, intellectual property, reputation, and
  communication channels;
- formation, financing, operation, succession, merger, dissolution, receivership, and
  bankruptcy paths.

Domain modules specialize this common identity; they do not create incompatible parallel
models for every institution.

### 6.4 Markets and services

The target economy includes:

- final goods and intermediate inputs;
- professional and personal services with appointments, capacity, price, quality, and
  completion evidence;
- labor with skills, credentials, job requirements, bargaining, performance, promotion,
  dismissal, unemployment, and retirement;
- credit, deposits, insurance, private equity, public equity, bonds, and mortgages;
- housing rental, purchase, construction, maintenance, vacancy, and foreclosure;
- regional trade, FX, shipments, migration, taxes, benefits, and public procurement.

Prices and allocations arise from offers, bids, contracts, budgets, and policy. The
engine may impose guardrails or eligibility but does not invent agent preferences.

### 6.5 Education and human capital

Schools and training organizations employ teachers, enroll students, schedule capacity,
charge tuition or receive public funding, issue credentials, and produce skill changes.
Learning outcomes combine deterministic attendance and prerequisite rules with bounded
agent effort and institutional quality. Credentials affect job eligibility but do not
guarantee employment.

### 6.6 Politics and law

Agents vote from their beliefs and lived outcomes. Parties campaign, candidates make
public commitments, interest groups lobby, news changes salience, and bounded policies
change taxes, benefits, regulation, rates, and public spending.

Legal entities can retain lawyers, negotiate, sign contracts, allege violations, file
claims, exchange discoverable evidence, settle, receive judgments, appeal, and collect.
Courts apply deterministic procedure and configured law; agent judges or juries may make
bounded fact-sensitive decisions. Legal outcomes change status or transfer value only
through engine-validated orders.

### 6.7 Communication and media

Communication media are separate domain objects:

- asynchronous private or organizational threads;
- public statements and filings;
- face-to-face/public conversations;
- newsroom articles that cite reportable events;
- campaigns, advertisements, notices, court service, and official announcements.

Messages are ordinary typed actions emitted during an agent's scheduled deliberation.
There is no automatic LLM call per message. Optional dedicated composition calls are
limited to high-salience legal, financial, journalistic, or political documents and pass
through the existing Gateway.

## 7. Users and core workflows

### 7.1 Operator

- Start, pause, resume, stop, checkpoint, fork, and scrub a run.
- Watch the world live at macro, regional, organizational, household, and person levels.
- Inject scheduled or live shocks without bypassing domain validation.
- Inspect privileged ground truth through an explicit, audited capability.
- See provider, projection, migration, reconciliation, and performance health.

### 7.2 Investigator

- Open a macro event and traverse its causal neighborhood.
- Pin events, people, firms, messages, claims, metrics, contracts, and ledger entries.
- Write hypotheses and classify them as open, supported, refuted, or inconclusive.
- Compare public knowledge, each agent's knowledge, and operator truth at a chosen tick.
- Export a portable investigation with stable references and redaction controls.

### 7.3 Experimenter

- Define a scenario, seed set, intervention schedule, cohort, and measured outcomes.
- Run scripted deterministic gates and separate live-provider trials.
- Compare forks and seed distributions rather than cherry-picking one narrative.
- Query exported Parquet bundles across runs with DuckDB.
- Preserve exact configuration, code, semantics, schema, data manifests, and checksums.

### 7.4 Hosted research group

- Share runs and investigations within one tenant.
- Allow one writer and many observers without data leakage across tenants.
- Grant privileged truth access separately from ordinary observation.
- Audit message-body inspection, legal disclosure, investigation export, and sharing.

## 8. P0 requirements: Communications and Causal Observatory lake

This is the first implementation lake and uses engine semantics 8 with database schema
12.

### R23. Typed command registry

- Define Pydantic command models selected by the existing `type` discriminator.
- Preserve the historical dictionary wire format and result dictionaries.
- Validate a command before proposal persistence; execute it through the existing
  savepoint-protected `ActionExecutor.execute_action()` facade.
- Map command type to an explicit handler registration. New communication handlers live
  in a communication domain module; old handlers migrate only when touched.
- Unknown, invalid, unauthorized, stale, or semantics-incompatible commands produce
  stable rejected proposals and never partially mutate state.

### R24. Asynchronous private communication

- Support thread creation, direct recipients, organization audiences, replies,
  forwarding, delivery, and read state.
- Supported visibility classes for this lake are `participants`, `organization`, and
  `public`. Sealed legal communications may be added only with a defined key and
  recovery model.
- Semantics 8 forbids same-tick delivery. Messages created in tick N are delivered no
  earlier than the deterministic inbox-delivery phase of tick N+1.
- A public message becomes readable only when its public audience is resolved in that
  phase. Publication writes a public event; it does not create one private delivery row
  or memory for every agent.
- Reply inherits thread and subject, addresses only the immediate sender, and grants no
  access to older thread messages. Forward creates a new thread/message, derives its
  subject and quoted content deterministically, and grants access only to the new message.
- A message body is at most 2,000 characters.
- A scheduled strategic agent emits at most three communication actions per tick; a
  peripheral wakeup emits at most one.
- Delivery is idempotent and exactly once per message-recipient pair across pause,
  restart, replay, and checkpoint fork.

### R25. Immutable access grants

- Direct recipients receive an immutable access grant at delivery.
- Organization membership is expanded and snapshotted at delivery. New members cannot
  read old mail; former members retain mail delivered while they were members.
- A deceased person's mailbox becomes inactive but its historical grants remain.
- Forwarding creates a new message with a provenance link; it does not silently extend
  the original access list.
- Legal discovery creates an explicit simulated disclosure grant tied to a case and
  court order or agreement.
- Local owner or hosted truth-inspector access is privileged and audited. It never enters
  agent prompts, newsroom inputs, public reports, or ordinary observer projections.
- Unauthorized reads return a uniform not-found response and a safe audit event; they do
  not disclose whether a message exists.
- The normative `AccessBasis` values are sender, direct delivery, organization-at-delivery,
  public release, legal disclosure, and operator truth. Sender/public/operator are explicit
  policy bases rather than delivery rows; operator inspection is append-only audited outside
  replay-authoritative state.
- Subject, body, participant identities, thread membership, message-specific URL/query
  keys, and existence are independently authorized as of the requested tick. The complete
  field-by-consumer contract is exercised by the
  [30-tick research protocol](30-TICK-RESEARCH-PROTOCOL.md#8-as-of-privacy-assertions).

### R26. Knowledge-safe delivery

- Delivery creates an observation memory only for authorized living recipients.
- The next scheduled decision receives a bounded inbox section ordered by delivery and
  salience.
- Agent prompts contain only facts available to that agent at the selected tick.
- Authoritative internal events may reference a private message ID and aggregate delivery
  status, but ordinary/public projections expose only non-linkable counts or the public
  consequence. They never expose a private message-specific ID/URL, subject, body, or
  participant identity/list.
- Newsroom, Oracle, reports, replay APIs, exports, and hosted observers each use an
  explicit projection policy rather than a shared superuser query.

### R27. Causal provenance

- Store explicit links between messages, memories, beliefs, decisions, action proposals,
  events, contracts, cases, articles, and ledger transactions.
- Initial relations are `observed`, `cited`, `motivated`, `triggered`, `settled`, and
  `inferred`.
- Direct engine links are deterministic and authoritative.
- Agent-stated motivations retain the actor and model-call provenance but are not treated
  as objective proof.
- Inferred links record method, confidence, creation tick, evidence, and model-call ID and
  remain visibly non-authoritative.
- The causal API distinguishes causation, influence, citation, inference, and temporal
  sequence and enforces depth, node, edge, and time budgets.
- Semantics 8 dual-writes existing JSON source references where needed for compatibility.

### R28. Versioned read projections

- Shared domain builders produce live and replay views for summary, events,
  communication, legal, markets, world map, and causal exploration.
- Every response carries `run_id`, `fork_id`, `tick`, `projection_version`, and
  `event_cursor`, plus `snapshot_version`, `policy_version`, and an opaque `view_key`.
- `projection_version` identifies the response schema; `snapshot_version` identifies one
  deterministic run/fork/tick/policy/cursor snapshot. `event_cursor` is global and monotonic
  within a run/fork lineage, not per widget.
- REST supplies initial bootstrap, lazy details, and cursor backfill.
- WebSockets supply bounded contiguous deltas, invalidations, run-state changes, and
  heartbeats.
- A gap, stale version, or out-of-order delta invalidates the affected query and triggers
  backfill or refetch. The client never guesses through a gap.
- Projection builders are pure readers and rebuildable from world truth. Live and replay
  use the same builders.

### R29. Route-based Observatory

The dashboard becomes a persistent shell with these workspaces:

1. Overview
2. World
3. People
4. Organizations
5. Markets
6. Politics & Law
7. News & Communications
8. Investigations
9. Experiments

The shell includes run/fork selection, live/replay mode, a tick scrubber, global search,
and a command palette. Selecting historical time exits live-follow mode explicitly.
Every run, fork, tick, event, entity, filter, and investigation is addressable in the URL.

The Investigation workspace uses a three-pane interaction:

- left: event timeline, filters, pinned evidence, and hypotheses;
- center: world layer, relationship/causal graph, or synchronized time series;
- right: evidence inspector showing source, visibility, authority, and links.

All visual selections have semantic tables, keyboard navigation, screen-reader names,
loading/empty/error/stale states, and reduced-motion behavior.

The first-lake release gate gives full new behavior only to Overview, News &
Communications, and Investigations, with the causal graph paired to a semantic table.
The other routes mount the persistent shell and preserve/rehouse useful current panels;
new synthetic-map layers and full-depth entity/market/politics/experiment redesigns follow
after the causal gate and do not block semantics 8.

### R30. Separate operator workspace

- Research notes, layouts, saved views, pins, and hypotheses never write to the
  replay-authoritative run database.
- Local mode uses a sidecar SQLite workspace. Hosted mode uses tenant-scoped PostgreSQL
  control-plane tables and existing audit patterns.
- Records use stable references containing run, fork, tick/cursor, entity type, and ID.
- Missing references after retention or deletion degrade gracefully.
- Updates use optimistic concurrency.
- Portable exports include references and notes. Private bodies require explicit
  privileged export and redaction review.

### R31. Reproducibility and compatibility

- One authoritative implementation lake receives one engine semantics version.
- Communications is semantics 8/schema 12; the External Agent Gateway is semantics
  9/schema 13; Agent Commons is semantics 10/schema 14; education begins at semantics
  11. Later lakes take the next available version when their contracts land.
- Replace ad-hoc startup alterations with an immutable numbered migration registry,
  checksums, and an applied-migration ledger.
- Fresh schema creation and sequential upgrades produce equivalent schemas.
- Existing runs never migrate to newer semantics in place.
- Historical semantics 1-7 replay with byte/row-level compatibility appropriate to their
  maintained contract.
- Existing schema 6-11 databases enter the migration ledger only through a verified
  `adopted_legacy` record; the binary must not claim that historical checksums were recorded
  when they were not.

### R32. Research export and scale

- Authoritative SQLite remains sufficient to replay a run.
- Stop or explicit export produces deterministic, sorted, content-addressed Parquet files
  plus a manifest containing run, fork, seed, semantics, schema, row counts, ranges, and
  checksums.
- DuckDB is an offline cross-run analysis tool only.
- The scale contract is:
  - 100 full-fidelity cognitive agents interactive;
  - 1,000 total agents with 100 strategic core and 900 mechanistic periphery;
  - 365 ticks in under 15 minutes offline, excluding provider latency;
  - under 2 GB process memory;
  - under 1.5 GB total run footprint after 365 ticks: main SQLite + WAL + SHM +
    checkpoints + provider/script receipts, excluding operator workspace, exports, and logs;
  - FINALIZE-commit to matching delta applied by the local benchmark subscriber p95 under
    2 seconds over 30 measured ticks after one warmup;
  - local bootstrap p95 under 750 ms;
  - interactive 100-agent finalized-tick latency p95 under 2 seconds and p99 under 5 seconds
    with the scripted provider.
- A versioned benchmark manifest freezes the host, OS, Python/SQLite versions, WAL settings,
  seed, fixture, message/recipient/causal density, warmup/cache policy, repetitions, quantile
  method, and storage/RSS accounting. Raw samples and manifest hashes are release artifacts.

## 9. First-lake release gate

Gate -1 is approval of the checked-in
[30-tick causal research protocol](30-TICK-RESEARCH-PROTOCOL.md). It predeclares the
treatment, no-message and neutral-message controls, exact `buy_goods` outcomes, alternative
explanations, as-of privacy matrix, refutation thresholds, canonical hash contract, and
required evidence artifacts. T1 cannot start until the design package and protocol are
approved together.

The lake is complete only when one scripted 30-tick scenario proves this chain:

```text
private message
  -> authorized delivery
  -> recipient memory or belief update
  -> agent decision
  -> economic, legal, or political action
  -> event and ledger outcome
  -> inspectable causal path
```

The gate requires:

- exact same-seed replay and equality after resume at every phase boundary;
- no private-body disclosure through REST, WebSocket, Oracle, newsroom, reports,
  replay, exports, errors, or logs;
- exactly-once delivery across crashes, death, organization membership change,
  forwarding, and legal discovery;
- live projections equal rebuilt projections;
- correct cursor backfill and reconnect behavior;
- an end-to-end Playwright investigator workflow;
- a separate 10-tick live-provider smoke proving persona-consistent communication;
- no regression in ledger, replay, migration, or scale receipts.

The scripted scenario is the frozen supplier-warning protocol: treatment buys 5 fixture
units, both controls buy 10, and the difference must be proven from action, inventory,
event, balanced ledger, qualified causal edges, and branch-isolation hashes. The newsroom
may observe the public goods consequence but never the private subject, body, identities,
or message-specific existence.

## 10. Later semantic lakes

### Lake 4: Education and teachers, semantics 11

- school and training organization types;
- teacher employment, classroom capacity, schedules, attendance, tuition/funding;
- course prerequisites, skill progression, credentials, graduation, dropout;
- education decisions linked to household budgets and career requirements;
- tests for credential fraud, teacher death, school insolvency, transfer, and replay.

### Lake 5: Households and housing, semantics 12

- first-class households and time-bounded membership;
- marriage/partnership, separation, guardianship, dependents, shared and separate assets;
- rental listings, leases, deposits, eviction procedure, homes, titles, mortgages,
  maintenance, construction, vacancy, foreclosure, and inheritance;
- household decision policy that avoids one LLM call per family member for joint choices;
- tests for death, divorce, negative equity, homelessness, landlord failure, and migration.

### Lake 6: Services and careers, next available semantics

- skill taxonomy, experience, credentials, job requirements, performance, promotions;
- service listings, appointments, queues, capacity, completion, quality, disputes;
- professional licensing for lawyers, teachers, health workers, finance, and trades;
- sole proprietorship and partnership workflows;
- tests for no-shows, double booking, incapacity, malpractice, license lapse, and bankruptcy.

### Lake 7: Institutional depth

- richer corporate governance, boards, security classes, dilution, bonds, M&A, and
  receivership;
- lawsuits, evidence, discovery, settlement, judgment, appeal, and enforcement;
- campaigns, parties, lobbying, legislative proposals, regulations, and public budgets;
- explicit constitutional and jurisdiction configuration rather than hidden prompt law.

Each later lake must define its own vertical causal proof before implementation begins.

## 11. Interactive UI outcomes

The UI should feel like an evidence room connected to a living city, not a wall of cards.

- The Overview answers: what changed, where is pressure building, and what needs attention?
- The World view shows spatial and network movement of people, goods, money, migration,
  ownership, and information on a synthetic map after the first causal gate.
- Entity pages tell a coherent life or organization story across time.
- Graph views reveal social, ownership, communication, legal, and causal structures.
- Time-series brushing updates the map, graph, timeline, and inspector together.
- Privacy is visible: every item shows who could know it at the selected tick.
- Causal confidence is visible: direct settlement cannot look the same as model inference.
- Every attractive visualization has a precise tabular explanation and export.

## 12. Success metrics

### Product

| Metric | First-lake target |
|---|---:|
| Time for a new investigator to trace the scripted message-to-ledger chain | < 5 minutes without SQL |
| Unauthorized private-body disclosures in automated policy matrix | 0 |
| Same-seed deterministic replay mismatches | 0 |
| Projection rebuild mismatches | 0 |
| Silent cursor-gap or stale-snapshot failures | 0 |
| Causal edges displaying relation, authority, and provenance | 100% |
| First-lake Playwright critical workflows passing | 100% |

### Research quality

| Metric | Target |
|---|---:|
| Experiment bundles with complete manifest and checksums | 100% |
| Claims in an investigation linked to evidence or marked as notes | 100% |
| Inferred causal links visibly labeled non-authoritative | 100% |
| Cross-seed comparisons reporting distributions, not one selected run | 100% of published experiment reports |

### Performance

The budgets in R32 are release constraints. Provider latency and spend are measured
separately so a slow external model does not masquerade as a kernel regression. A budget
passes only with the checked-in benchmark manifest, raw samples, exact host receipt, and
declared percentile method; an undocumented local timing is not release evidence.

## 13. Explicitly not in scope

- Predicting real elections, markets, court cases, or named real people.
- Connecting agents to real email accounts, social networks, banks, brokers, or legal
  systems.
- Real money or autonomous external transactions.
- A physically accurate 3D planet, transport physics, or external map tiles in the first
  UI lake.
- New full-depth World, People, Organizations, Markets, Politics & Law, and Experiments
  workspaces before the communications/causal gate; their routes may preserve existing
  panels, while new synthetic-map and cross-domain visualization depth is a follow-on.
- A microservice per agent, distributed authoritative state, or multiple world writers.
- Neo4j, RDF, or another graph database for the planned causal scale.
- End-to-end encryption or sealed mail until key ownership, recovery, discovery, replay,
  and operator-truth requirements are separately designed.
- A dedicated LLM completion for every ordinary message.
- Migrating existing runs in place to new semantics.
- Implementing all semantic lakes in one branch.

## 14. Risks and controls

| Risk | Control |
|---|---|
| Fluent agent text is mistaken for ground truth | Separate knowledge projections, provenance, and authority labels |
| Private text leaks through secondary surfaces | One policy layer, deny-by-default tests across every consumer, uniform not-found errors |
| Communication creates runaway model calls | Messages remain ordinary actions; strict action/body caps; optional salience-only composition |
| Causal graph becomes a correlation graph | Typed relations, direct vs inferred authority, confidence, and temporal-only edges |
| A new domain breaks historical runs | Semantics gates, immutable migrations, historical fixtures, explicit forks |
| UI becomes an unmaintainable dashboard monolith | Route workspaces, shared projections, generated types, query cache, bounded components |
| Distributed workers duplicate effects | Stateless immutable requests, deterministic request keys, ordered local commit |
| Research annotations contaminate replay | Separate local/hosted operator workspace store |
| Data volume overwhelms the live API | Bounded projections, cursor pagination, lazy details, Parquet research exports |
| Mechanistic periphery feels fake | Promotion on salience, strategic cohorts, behavior-distribution validation |

## 15. Release sequence

1. Approve and freeze the 30-tick treatment/control protocol (Gate -1).
2. Land migration registry and typed-command characterization tests.
3. Add semantics-8 communication storage, commands, delivery phase, and policy matrix.
4. Add causal links and dual-write provenance.
5. Add shared projection builders, REST envelopes, cursor backfill, and WebSocket protocol.
6. Add the route shell plus full Overview and News & Communications behavior.
7. Add the Investigation graph/table, evidence inspector, and operator workspace.
8. Add Hypothesis state machine, phase/fork fault injection, Playwright flows, exports, and
   the frozen 30-tick release scenario.
9. Run the separate live-provider smoke and versioned scale receipt.
10. After the gate, deepen the other route workspaces and synthetic World view without
    changing semantics 8.
11. Land the semantics-9/schema-13 External Agent Gateway and pass its local security,
    replay, isolation, and load gates.
12. Validate MCP authorization conformance plus live Hermes, OpenClaw, Python, and
    TypeScript connectors against an invite-only hosted tenant.
13. Land the semantics-10/schema-14 Commons causal/read protocol and browser surface,
    then pass its three-branch supplier-warning experiment.
14. Raise hosted quotas only after operational evidence; start education and later lakes
    under their own separately approved domain gates.

## 16. Open questions

No unresolved first-lake architecture decisions remain after the 2026-07-18 engineering
review. The treatment/control protocol is part of this proposed design package and becomes
frozen when the package is approved. Each later semantic lake must still define its domain
law, seed data, behavior model, causal proof, and acceptance fixture before code changes
begin.

## 17. Approval and continuing gate

The project owner explicitly approved Gate -1 on 2026-07-18 by directing
implementation of this plan. The checked-in
[30-tick research protocol](30-TICK-RESEARCH-PROTOCOL.md) is frozen: any proposed
change must first show whether it lets a control pass without the warning causing
the quantity change, or produces the quantity change without the required evidence
chain. Gateway and Commons code completion does not waive their independent hosted
conformance, connector, security, and operational gates.
