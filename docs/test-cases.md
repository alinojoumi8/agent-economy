# Agent Economy PRD-Traceable Test Catalog

Stable catalog of automated evidence for PRD requirements R1–R32 and extension contracts
(Gateway, Commons, cognition, citizenship, Live City). Each entry has a fixed ID.

## Execution tiers

| Tier | Meaning |
|------|---------|
| `fast-offline` | Focused unit/integration tests suitable for every PR |
| `full-offline` | Full offline Python or dashboard suite without external services |
| `hosted-integration` | PostgreSQL / S3 / Docker isolation (opt-in CI) |
| `live-provider` | Real model providers (opt-in) |
| `release-evidence` | Long-duration, load, or campaign corpus evidence (opt-in) |

## Status values

| Status | Meaning |
|--------|---------|
| `existing-coverage` | Already automated before this catalog |
| `newly-automated` | Added by the PRD-traceable test suite plan |
| `opt-in-gate` | Coverage exists but runs only behind an explicit opt-in gate |
| `contractual-gap` | Requirement or surface is not product-complete; recorded, not implemented here |

## Catalog entries

### AE-R01-001

- **requirement**: R1
- **risk**: high
- **preconditions**: Initialized economy with ledger accounts
- **given**: A sequence of validated economic actions
- **when**: The engine executes each tick
- **then**: Assets minus liabilities reconcile exactly
- **oracle**: Zero ledger discrepancy; failed reconciliation halts
- **test**: tests/test_ledger.py
- **tier**: full-offline
- **status**: existing-coverage

### AE-R02-001

- **requirement**: R2
- **risk**: high
- **preconditions**: Persona library and agent runtime configured
- **given**: Agents with memory and decision context
- **when**: A tick runs the decide/execute loop
- **then**: Prompt context, actions, and belief updates are inspectable
- **oracle**: Decision rows and belief events are recorded
- **test**: tests/test_prd_completion.py
- **tier**: full-offline
- **status**: existing-coverage

### AE-R03-001

- **requirement**: R3
- **risk**: high
- **preconditions**: Banks, firms, labor, and goods markets initialized
- **given**: Founding, credit, hiring, and bankruptcy paths
- **when**: Institutional actions execute
- **then**: Company lifecycle is observable on the ledger
- **oracle**: Loan, employment, and bankruptcy events balance
- **test**: tests/test_credit_and_firms.py
- **tier**: full-offline
- **status**: existing-coverage

### AE-R04-001

- **requirement**: R4
- **risk**: medium
- **preconditions**: Exchange enabled with listed firms
- **given**: Limit and market orders from agents
- **when**: Matching runs
- **then**: Prices emerge only from orders
- **oracle**: Deterministic price-time priority matching
- **test**: tests/test_exchange.py
- **tier**: full-offline
- **status**: existing-coverage

### AE-R05-001

- **requirement**: R5
- **risk**: high
- **preconditions**: News outlets and conversation graph present
- **given**: A false bank rumor injection
- **when**: Conversations and belief updates run for 10 ticks
- **then**: Rumor spreads with measurable trust and deposit effects
- **oracle**: Rumor pilot acceptance criteria
- **test**: tests/test_information_completion.py
- **tier**: full-offline
- **status**: existing-coverage

### AE-R06-001

- **requirement**: R6
- **risk**: medium
- **preconditions**: Oracle subsystem configured
- **given**: A probability question about world state
- **when**: The Oracle answers and later resolves
- **then**: Structured prediction and Brier scoring occur without write access
- **oracle**: Prediction rows and resolution criteria
- **test**: tests/test_oracle_campaign.py
- **tier**: live-provider
- **status**: opt-in-gate

### AE-R07-001

- **requirement**: R7
- **risk**: high
- **preconditions**: Run controller with cost governor
- **given**: Budget caps and provider failures
- **when**: Start/pause/resume and degradation fire
- **then**: Spend stays within cap and resume is phase-aware
- **oracle**: Governor and pause state visible
- **test**: tests/test_governor_and_world.py
- **tier**: full-offline
- **status**: existing-coverage

### AE-R08-001

- **requirement**: R8
- **risk**: medium
- **preconditions**: Dashboard built and server running
- **given**: Live tick updates
- **when**: Observatory panels render
- **then**: Macro, agents, and event surfaces remain usable
- **oracle**: Dashboard unit and e2e smoke
- **test**: dashboard/tests/e2e/world-os-routes.spec.ts
- **tier**: full-offline
- **status**: newly-automated

### AE-R09-001

- **requirement**: R9
- **risk**: medium
- **preconditions**: Shock library configured
- **given**: Shock, trend, and conditional triggers
- **when**: Shocks fire
- **then**: Logged events produce observable downstream effects
- **oracle**: Shock events present in event spine
- **test**: tests/test_prd_completion.py
- **tier**: full-offline
- **status**: existing-coverage

### AE-R10-001

- **requirement**: R10
- **risk**: low
- **preconditions**: Completed or stopped run
- **given**: Report generation request
- **when**: End-of-run report is produced
- **then**: HTML and Markdown companions include metrics and seed
- **oracle**: Report artifact paths exist
- **test**: tests/test_report_narrative.py
- **tier**: full-offline
- **status**: existing-coverage

### AE-R11-001

- **requirement**: R11
- **risk**: high
- **preconditions**: Lifecycle tables and population policy enabled
- **given**: Illness, death, retirement, and arrivals
- **when**: Lifecycle phases run
- **then**: Estate settlement and arrivals remain ledger-safe
- **oracle**: Deterministic lifecycle schedule for a fixed seed
- **test**: tests/test_lifecycle.py
- **tier**: full-offline
- **status**: existing-coverage

### AE-R12-001

- **requirement**: R12
- **risk**: medium
- **preconditions**: Government and election systems present
- **given**: Tax collection and election cycles
- **when**: Votes and fiscal policy shift
- **then**: Fiscal and political outcomes are recorded
- **oracle**: Election and tax events
- **test**: tests/test_v2_information_politics.py
- **tier**: full-offline
- **status**: existing-coverage

### AE-R13-001

- **requirement**: R13
- **risk**: medium
- **preconditions**: Startup funding track enabled
- **given**: Pitch through term sheet and close
- **when**: VC round settles
- **then**: Cap table and cash balances update
- **oracle**: Funding round events
- **test**: tests/test_v2_startups.py
- **tier**: full-offline
- **status**: existing-coverage

### AE-R14-001

- **requirement**: R14
- **risk**: medium
- **preconditions**: Experiment harness configs available
- **given**: Multi-seed experiment definition
- **when**: Harness runs and compares outcomes
- **then**: Comparison report distributions are produced
- **oracle**: Experiment report artifacts
- **test**: tests/test_p1_harness_and_tools.py
- **tier**: full-offline
- **status**: existing-coverage

### AE-R15-001

- **requirement**: R15
- **risk**: medium
- **preconditions**: Explicit Oracle calibration manifest
- **given**: Finalized eligible live Oracle runs
- **when**: Calibration evaluator runs
- **then**: Reliability and Brier receipts are deterministic
- **oracle**: Manifest-bound JSON/Markdown receipts
- **test**: tests/test_oracle_campaign.py
- **tier**: release-evidence
- **status**: opt-in-gate

### AE-R16-001

- **requirement**: R16
- **risk**: high
- **preconditions**: Recorded run database available
- **given**: Replay mode without live LLM access
- **when**: Replay advances through ticks
- **then**: Canonical hashes match the source run
- **oracle**: Exact replay proof
- **test**: tests/test_recorded_replay_golden.py
- **tier**: fast-offline
- **status**: existing-coverage

### AE-R17-001

- **requirement**: R17
- **risk**: medium
- **preconditions**: Health economy institutions present
- **given**: Medical firms, insurance, or epidemic shock
- **when**: Health-related spending and recovery run
- **then**: Effects appear on agent ledgers and events
- **oracle**: Health-related ledger and event rows
- **test**: tests/test_lifecycle.py
- **tier**: full-offline
- **status**: existing-coverage

### AE-R18-001

- **requirement**: R18
- **risk**: high
- **preconditions**: Participant control enabled
- **given**: External or human participant actions
- **when**: Actions enter the same validator and ledger path
- **then**: Queued/executed/rejected history is replay-safe
- **oracle**: Participant action provenance
- **test**: tests/test_participant_mode.py
- **tier**: full-offline
- **status**: existing-coverage

### AE-R19-001

- **requirement**: R19
- **risk**: medium
- **preconditions**: Core/periphery population tiers configured
- **given**: 1,000-agent scale profile
- **when**: Peripheral agents take deterministic local turns
- **then**: No peripheral model calls; balances conserved
- **oracle**: Performance and replay gates
- **test**: tests/test_world_os_v8_benchmarks.py
- **tier**: release-evidence
- **status**: opt-in-gate

### AE-R20-001

- **requirement**: R20
- **risk**: high
- **preconditions**: Multicurrency regions enabled
- **given**: Trade, FX, and migration opportunities
- **when**: Cross-border actions execute
- **then**: Invoice currency and migration gates hold
- **oracle**: Shipment and migration completion with exact replay
- **test**: tests/test_v2_regions.py
- **tier**: full-offline
- **status**: existing-coverage

### AE-R21-001

- **requirement**: R21
- **risk**: medium
- **preconditions**: `real_us` profile and pinned SCF/SUSB data
- **given**: Real-data calibration initialization
- **when**: Households and firms are sampled
- **then**: Provenance and replay remain deterministic
- **oracle**: Calibration targets and hashes
- **test**: tests/test_r21_calibration.py
- **tier**: full-offline
- **status**: existing-coverage

### AE-R22-001

- **requirement**: R22
- **risk**: high
- **preconditions**: Hosted PostgreSQL/S3 stack available
- **given**: Multi-tenant hosted control plane
- **when**: Auth, leases, snapshots, and isolation run
- **then**: RLS and single-writer guarantees hold
- **oracle**: Hosted isolation and snapshot restore evidence
- **test**: tests/test_hosted_postgres_integration.py
- **tier**: hosted-integration
- **status**: opt-in-gate

### AE-R23-001

- **requirement**: R23
- **risk**: high
- **preconditions**: Semantics 8+ command registry
- **given**: Typed command submissions
- **when**: Invalid or unknown commands arrive
- **then**: Validation fails closed without world mutation
- **oracle**: Command registry rejection paths
- **test**: tests/test_semantics8_foundations.py
- **tier**: full-offline
- **status**: existing-coverage

### AE-R24-001

- **requirement**: R24
- **risk**: high
- **preconditions**: Private communication domain enabled
- **given**: Asynchronous private message send
- **when**: Delivery and later reads occur
- **then**: Bodies stay outside public event payloads
- **oracle**: Authorized delivery only
- **test**: tests/test_semantics8_communications.py
- **tier**: full-offline
- **status**: existing-coverage

### AE-R25-001

- **requirement**: R25
- **risk**: high
- **preconditions**: Access grant tables present
- **given**: Immutable disclosure grants
- **when**: Grants are issued and later queried
- **then**: Grants are append-only and auditable
- **oracle**: Disclosure authority rows immutable
- **test**: tests/test_semantics8_communications.py
- **tier**: full-offline
- **status**: existing-coverage

### AE-R26-001

- **requirement**: R26
- **risk**: high
- **preconditions**: Knowledge-safe delivery policy
- **given**: Unauthorized principal requests private content
- **when**: Projection builders filter messages
- **then**: Unauthorized bodies are omitted (404 / empty)
- **oracle**: No private body leakage
- **test**: tests/test_semantics8_communication_branches.py
- **tier**: full-offline
- **status**: existing-coverage

### AE-R27-001

- **requirement**: R27
- **risk**: high
- **preconditions**: Causal link graph populated
- **given**: Message → memory → belief → action → event chain
- **when**: Causal neighborhood is projected
- **then**: Provenance edges are complete and ordered
- **oracle**: Causal graph nodes and edges
- **test**: tests/test_semantics8_causal_membership.py
- **tier**: full-offline
- **status**: existing-coverage

### AE-R28-001

- **requirement**: R28
- **risk**: high
- **preconditions**: Versioned projection envelopes
- **given**: Snapshot and delta projections
- **when**: Cursor advances and lineage is checked
- **then**: Contiguous deltas apply; mismatches go stale
- **oracle**: Cursor reducer and transport recovery
- **test**: dashboard/tests/world-os-cursor.test.js
- **tier**: fast-offline
- **status**: newly-automated

### AE-R29-001

- **requirement**: R29
- **risk**: medium
- **preconditions**: World OS route workspaces
- **given**: Route-based Observatory navigation
- **when**: Users move across workspaces
- **then**: Selected run and tick are preserved
- **oracle**: Navigation and e2e route checks
- **test**: dashboard/tests/e2e/world-os.spec.ts
- **tier**: full-offline
- **status**: existing-coverage

### AE-R30-001

- **requirement**: R30
- **risk**: medium
- **preconditions**: Operator workspace APIs
- **given**: Operator investigations and annotations
- **when**: Operator-only routes are used
- **then**: Operator truth is separated from ordinary observer truth
- **oracle**: Operator session and investigation APIs
- **test**: tests/test_operator_workspace.py
- **tier**: full-offline
- **status**: existing-coverage

### AE-R31-001

- **requirement**: R31
- **risk**: high
- **preconditions**: Hash contracts and schema migrations
- **given**: Checkpoint, pause/resume, and fork flows
- **when**: Compatibility guards run
- **then**: Semantics and schema contracts remain stable
- **oracle**: Compatibility and hash-contract checks
- **test**: tests/test_compatibility_guards.py
- **tier**: full-offline
- **status**: existing-coverage

### AE-R32-001

- **requirement**: R32
- **risk**: high
- **preconditions**: Research export path and hash-contract-v2
- **given**: Default research export with private fields present
- **when**: Bundle is written and validated
- **then**: Private bytes are redacted; integrity evidence remains
- **oracle**: Manifest redaction counts and no canary bytes
- **test**: tests/test_research_export.py
- **tier**: fast-offline
- **status**: newly-automated

### AE-EXT-GATEWAY-001

- **requirement**: EXT-GATEWAY
- **risk**: high
- **preconditions**: External agent gateway enabled (semantics 9+)
- **given**: Connection, turn, idempotent submit, and complete
- **when**: Duplicate completes race and late completes arrive
- **then**: Exactly one terminal transition and event; late completes no-op
- **oracle**: Single executed receipt and exact replay without client network
- **test**: tests/test_external_agent_gateway.py
- **tier**: fast-offline
- **status**: newly-automated

### AE-EXT-COMMONS-001

- **requirement**: EXT-COMMONS
- **risk**: medium
- **preconditions**: Commons profiles and feed tables
- **given**: Commons entries and reactions
- **when**: Feed and moderation paths run
- **then**: Public commons remain projection-safe
- **oracle**: Commons protocol tests
- **test**: tests/test_agent_commons.py
- **tier**: full-offline
- **status**: existing-coverage

### AE-EXT-COGNITION-001

- **requirement**: EXT-COGNITION
- **risk**: medium
- **preconditions**: Semantics 11 cognition surfaces
- **given**: Skill and compute subscription state
- **when**: Cognition transitions fire
- **then**: Skill history and subscriptions remain deterministic
- **oracle**: Cognition unit tests
- **test**: tests/test_semantics11_cognition.py
- **tier**: full-offline
- **status**: existing-coverage

### AE-EXT-CITIZENSHIP-001

- **requirement**: EXT-CITIZENSHIP
- **risk**: medium
- **preconditions**: Passport and citizenship onboarding
- **given**: Join and registration flows
- **when**: Passports are issued or denied
- **then**: Citizenship boundaries stay privacy-safe
- **oracle**: Passport citizenship tests
- **test**: tests/test_passport_citizenship.py
- **tier**: full-offline
- **status**: existing-coverage

### AE-EXT-LIVECITY-001

- **requirement**: EXT-LIVECITY
- **risk**: high
- **preconditions**: Live City component and overview workspace
- **given**: Loading, empty, error, disconnected, paused, failed, historical, and live feeds
- **when**: CivicCity renders from canonical APIs
- **then**: Labels and marks match transport truth; empty/error invent no agents
- **oracle**: Playwright and civic city unit evidence
- **test**: dashboard/tests/e2e/world-os-states.spec.ts
- **tier**: full-offline
- **status**: newly-automated

### AE-EXT-PROJECTION-RECOVERY-001

- **requirement**: EXT-PROJECTION-RECOVERY
- **risk**: high
- **preconditions**: WebSocket projection protocol with `cursor_ahead`
- **given**: Client cursor N greater than server cursor M
- **when**: Server emits `cursor_ahead` and recovery continues
- **then**: Cursor resets to M, projection is stale once, contiguous M→M+1 applies, stale clears after recovery
- **oracle**: Cursor reducer unit tests and Playwright recovery scenario
- **test**: dashboard/tests/world-os-cursor.test.js
- **tier**: fast-offline
- **status**: newly-automated

### AE-EXT-BROWSER-PRIVACY-001

- **requirement**: EXT-BROWSER-PRIVACY
- **risk**: high
- **preconditions**: Private communication canaries seeded in mock APIs
- **given**: Unauthorized thread detail and authorized operator paths
- **when**: Browser navigates, reconnects, and changes historical tick
- **then**: Canaries never appear in DOM, URL, storage, console, or transport errors
- **oracle**: Playwright privacy suite
- **test**: dashboard/tests/e2e/world-os-privacy.spec.ts
- **tier**: full-offline
- **status**: newly-automated

### AE-EXT-EXPORT-PRIVACY-001

- **requirement**: EXT-EXPORT-PRIVACY
- **risk**: high
- **preconditions**: External-action submissions with canaries in sensitive JSON fields
- **given**: Default hash-contract-v2 export
- **when**: Bundle is produced
- **then**: `action_json`, `rationale_summary`, `result_json`, and `validator_results_json` are redacted
- **oracle**: No canary bytes; manifest records redactions; hash-contract-v1 unchanged
- **test**: tests/test_research_export.py
- **tier**: fast-offline
- **status**: newly-automated

### AE-EXT-INVESTIGATION-CONFLICT-001

- **requirement**: EXT-INVESTIGATION-CONFLICT
- **risk**: low
- **preconditions**: Browser-level multi-investigator conflict UI
- **given**: Concurrent operator investigations
- **when**: Conflict resolution is requested in the browser
- **then**: Stale writes stop at HTTP 409 and offer Reload, Continue editing, or Save-as-new without automatic overwrite
- **oracle**: Two isolated Chromium contexts preserve both titles, the winning version, focus, and original evidence ownership
- **test**: dashboard/tests/e2e/world-os-investigations.spec.ts
- **tier**: full-offline
- **status**: newly-automated

### AE-EXT-EXPORT-BROWSER-UI-001

- **requirement**: EXT-EXPORT-BROWSER-UI
- **risk**: low
- **preconditions**: In-browser research export workflow
- **given**: Operator requests an export from the UI
- **when**: Export UI is used
- **then**: JSON and Markdown downloads use safe filenames and only backend-redacted bytes
- **oracle**: Chromium download events, parsed schema and manifest, evidence text, and private-canary absence across browser storage and downloaded bytes
- **test**: dashboard/tests/e2e/world-os-investigations.spec.ts
- **tier**: full-offline
- **status**: newly-automated

### AE-EXT-WORLD-WORKSPACE-001

- **requirement**: EXT-WORLD-WORKSPACE
- **risk**: high
- **preconditions**: Canonical world workspace projection
- **given**: Live and historical region, place, agent, organization, presence, and flow rows
- **when**: World renders, selects a region/place, and follows a related workspace link
- **then**: Invalid coordinates and unknown/duplicate flows are rejected; run/fork/tick and public lineage are preserved
- **oracle**: Pure-model tests, projection tests, and Chromium route flow
- **test**: dashboard/tests/e2e/world-os-routes.spec.ts
- **tier**: full-offline
- **status**: newly-automated

### AE-EXT-ORGANIZATIONS-WORKSPACE-001

- **requirement**: EXT-ORGANIZATIONS-WORKSPACE
- **risk**: high
- **preconditions**: Canonical organizations workspace projection
- **given**: Public firms, banks, agencies, contracts, disclosures, and lifecycle history
- **when**: Directory filters, keyboard selection, and a validated deep link are used
- **then**: Currency units and as-of lifecycle remain explicit; owner, tenant, and private fields are absent
- **oracle**: Pure-model tests, typed build, and Chromium desktop/mobile flow
- **test**: dashboard/tests/e2e/world-os-routes.spec.ts
- **tier**: full-offline
- **status**: newly-automated

### AE-EXT-MARKETS-WORKSPACE-001

- **requirement**: EXT-MARKETS-WORKSPACE
- **risk**: high
- **preconditions**: Canonical markets workspace projection
- **given**: Orders, executions, FX records, currencies, and circuit-breaker events
- **when**: Market tabs and filters render at live and empty historical ticks
- **then**: Books and executions remain separate, units/direction are explicit, and empty evidence is not reported as measured zero activity
- **oracle**: Pure-model tests and Chromium empty/live route flows
- **test**: dashboard/tests/e2e/world-os-routes.spec.ts
- **tier**: full-offline
- **status**: newly-automated

### AE-EXT-POLITICS-LAW-WORKSPACE-001

- **requirement**: EXT-POLITICS-LAW-WORKSPACE
- **risk**: high
- **preconditions**: Canonical politics-law workspace projection
- **given**: Bills, votes, rules, lobbying, contracts, obligations, matters, mergers, and reviews
- **when**: Institutional sections render at enabled and configured-disabled ticks
- **then**: Record families stay distinct and retained rows from disabled institutions remain hidden
- **oracle**: Pure-model tests and Chromium disabled-state canary flow
- **test**: dashboard/tests/e2e/world-os-routes.spec.ts
- **tier**: full-offline
- **status**: newly-automated

### AE-EXT-EXPERIMENTS-WORKSPACE-001

- **requirement**: EXT-EXPERIMENTS-WORKSPACE
- **risk**: high
- **preconditions**: Canonical experiments workspace projection
- **given**: Checkpoints, shocks, predictions, acceptance records, campaign artifacts, datasets, and scenarios
- **when**: Evidence is classified and live/historical detail routes render
- **then**: Mechanics, partial, blocked, failed, live, and eligible evidence fail closed; observer routes start no provider spend or mutation
- **oracle**: Classification unit matrix and Chromium current-only/deep-link flows
- **test**: dashboard/tests/e2e/world-os-routes.spec.ts
- **tier**: full-offline
- **status**: newly-automated

### AE-EXT-WORLD-OS-ROUTE-COMPATIBILITY-001

- **requirement**: EXT-WORLD-OS-ROUTE-COMPATIBILITY
- **risk**: high
- **preconditions**: All five former placeholder routes implemented
- **given**: Desktop, 390px mobile, reduced-motion, historical, stale-safe, privacy-canary, and command-navigation contexts
- **when**: Chromium traverses every canonical route and validated detail link
- **then**: No page-level horizontal overflow, private/future canary, console error, page error, or non-navigation request failure occurs
- **oracle**: Combined route, state, and privacy Playwright suites
- **test**: dashboard/tests/e2e/world-os-routes.spec.ts
- **tier**: full-offline
- **status**: newly-automated

These cases close the canonical placeholder-route contract. Deeper later product redesigns remain outside this scope.
