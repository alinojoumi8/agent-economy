# World OS Legacy Route Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the World, Organizations, Markets, Politics & Law, and Experiments placeholder routes with route-native, time-aware workspaces built from authoritative projections and existing Observatory capabilities.

**Architecture:** Add envelope-producing, as-of-tick workspace projection builders on the server, then create one focused TypeScript workspace and one pure JavaScript model per route. Share observer state, freshness, lineage, loading/error primitives, and validated cross-route links. Rehouse current panels and evidence tools without claiming later full-depth redesigns.

**Tech Stack:** FastAPI, SQLite projections, React 19, TypeScript/JavaScript modules, TanStack Query, React Router 8, Node test runner, Playwright Chromium.

## Global Constraints

- Every projection accepts `tick` and `fork_id`, returns the canonical projection envelope, and filters out future rows/state.
- Never reconstruct historical state from a mutable final-state column when ordered events or version rows are required.
- Current provider capacity is labelled current telemetry and is never rendered as historical.
- Observer routes are read-only and must not expose private communications, beliefs, provider diagnostics, or unknown event kinds.
- Preserve loading, empty, error, stale, disabled, historical, narrow-layout, keyboard, screen-reader, and reduced-motion behavior.
- Use validated entity IDs from projection data in links; never linkify raw model text.
- Each route is an independent commit/review boundary.
- This plan rehouses existing functionality; deeper future product redesigns remain outside scope.

---

## File structure

- Create: `server/projections/workspaces.py` — time-bounded builders for World, Organizations, Markets, Politics & Law, and Experiments.
- Modify: `server/projections/__init__.py` — export workspace builders.
- Modify: `server/v2_api.py` — envelope routes under `/api/v2/workspaces/*`.
- Modify: `server/v2_api.py` world-map builder to remove historical final-state leakage.
- Create: `tests/test_world_os_workspace_projections.py` — future-row/privacy/lineage/disabled-state tests.
- Create: `dashboard/src/workspaces/workspaceShared.tsx` — shared query-state/error/freshness/section primitives.
- Create: `dashboard/src/workspaces/worldWorkspaceModel.js`
- Create: `dashboard/src/workspaces/organizationsWorkspaceModel.js`
- Create: `dashboard/src/workspaces/marketsWorkspaceModel.js`
- Create: `dashboard/src/workspaces/politicsLawWorkspaceModel.js`
- Create: `dashboard/src/workspaces/experimentsWorkspaceModel.js`
- Create: `dashboard/src/workspaces/WorldWorkspace.tsx`
- Create: `dashboard/src/workspaces/OrganizationsWorkspace.tsx`
- Create: `dashboard/src/workspaces/MarketsWorkspace.tsx`
- Create: `dashboard/src/workspaces/PoliticsLawWorkspace.tsx`
- Create: `dashboard/src/workspaces/ExperimentsWorkspace.tsx`
- Modify: `dashboard/src/app/WorldOSApp.tsx` — replace `LegacyWorkspace` routes and remove it after all five land.
- Modify: `dashboard/src/app/WorkspaceShell.tsx` — only if route labels/selection need contract-preserving adjustment.
- Modify: `dashboard/src/index.css` — workspace grids/tables/focus/narrow layout/reduced motion.
- Create: `dashboard/tests/world-os-routes.test.js` — pure models and source contracts.
- Create: `dashboard/tests/e2e/world-os-routes.spec.ts` — real Chromium route flows.
- Modify: `dashboard/tests/e2e/world-os-privacy.spec.ts`
- Modify: `dashboard/tests/e2e/world-os-states.spec.ts`
- Modify: `docs/test-cases.md`

### Task 1: Add canonical as-of workspace projections

**Files:**
- Create: `server/projections/workspaces.py`
- Modify: `server/projections/__init__.py`
- Modify: `server/v2_api.py`
- Create: `tests/test_world_os_workspace_projections.py`

**Interfaces:**
- Produces: `build_world_workspace`, `build_organizations_workspace`, `build_markets_workspace`, `build_politics_law_workspace`, and `build_experiments_workspace`.
- Consumes: `store`, ordinary `Principal`, explicit `as_of_tick`, and current world services only when they already accept an as-of tick.

- [ ] **Step 1: Write failing envelope and future-row tests**

Use a fixture with current tick 10 and rows/events at ticks 4 and 9. For each builder assert:

```python
payload = build_markets_workspace(store, as_of_tick=4)
assert all(item["tick"] <= 4 for item in payload["trades"])
assert all(item["tick"] <= 4 for item in payload["fx_trades"])
assert "future-order-canary" not in json.dumps(payload)
```

Add equivalent tests for firm creation/bankruptcy, bills/votes/rules, legal matters/obligations, forks/receipts, and private communication canaries.

- [ ] **Step 2: Add failing API envelope tests**

For each endpoint assert:

```python
response = client.get("/api/v2/workspaces/markets?tick=4")
assert response.status_code == 200
body = response.json()
assert body["projection"] == "workspace.markets"
assert body["tick"] == 4
assert body["run_id"] == run_id
assert body["data"] == build_markets_workspace(store, as_of_tick=4)
```

Assert future/out-of-lineage ticks return 409 and mismatched forks fail closed.

- [ ] **Step 3: Run focused tests and verify missing builders/routes**

Run:

```bash
.venv/bin/python -m pytest tests/test_world_os_workspace_projections.py -q
```

Expected: import/404 failures.

- [ ] **Step 4: Implement pure, deterministic builders**

Use these signatures:

```python
def build_world_workspace(world, store, *, as_of_tick: int) -> dict: ...
def build_organizations_workspace(store, *, as_of_tick: int) -> dict: ...
def build_markets_workspace(store, *, as_of_tick: int) -> dict: ...
def build_politics_law_workspace(store, *, as_of_tick: int) -> dict: ...
def build_experiments_workspace(store, *, as_of_tick: int) -> dict: ...
```

Every returned list is deterministically ordered and bounded. Parse JSON through `load_json`. Derive historical lifecycle/status from creation/version/ordered events at or before the requested tick; do not filter historical firms with their final `status` alone.

- [ ] **Step 5: Add canonical envelope routes**

Add GET routes:

```text
/api/v2/workspaces/world
/api/v2/workspaces/organizations
/api/v2/workspaces/markets
/api/v2/workspaces/politics-law
/api/v2/workspaces/experiments
```

Each accepts `tick=live` and optional `fork_id`, calls `projection_tick`, uses ordinary-observer policy, and returns `build_envelope(..., as_of_tick=as_of_tick)`.

- [ ] **Step 6: Fix world-map historical organization leakage**

Add a regression where a firm founded by tick 4 but bankrupt at tick 9 appears active at tick 4 and absent/terminal according to the tick-9 contract. Apply the same event-derived lifecycle helper used by the Organizations builder.

- [ ] **Step 7: Run focused tests and commit**

Run:

```bash
.venv/bin/python -m pytest tests/test_world_os_workspace_projections.py tests/test_semantics8_projections_api.py tests/test_semantics12_civic_city.py -q
git add server/projections/workspaces.py server/projections/__init__.py server/v2_api.py tests/test_world_os_workspace_projections.py
git diff --cached --check
git commit -m "feat(world-os): add route workspace projections"
```

### Task 2: Add shared route state and presentation primitives

**Files:**
- Create: `dashboard/src/workspaces/workspaceShared.tsx`
- Create: `dashboard/tests/world-os-routes.test.js`
- Modify: `dashboard/src/index.css`

**Interfaces:**
- Produces: `useWorkspaceProjection<T>(projection, path)`, `WorkspaceState`, `WorkspaceHeader`, `WorkspaceTable`, `WorkspaceEmpty`, and `workspaceUrl(runId,path,state,extra)`.
- Consumes: `useObserverViewState`, `projectionScopeParams`, `FreshnessBadge`, and transport context.

- [ ] **Step 1: Write failing URL and state-model tests**

Add pure tests asserting:

```javascript
assert.equal(
  workspaceRouteUrl("run/id", "markets", { fork: "fork-1", tick: "7" }, { side: "buy" }),
  "/runs/run%2Fid/markets?fork=fork-1&tick=7&side=buy",
);
```

Assert live/default values omit noise, selected IDs are positive validated integers, and unknown filter keys are discarded.

- [ ] **Step 2: Run tests and verify missing helper**

Run:

```bash
(cd dashboard && node --test tests/world-os-routes.test.js)
```

- [ ] **Step 3: Implement shared primitives**

`useWorkspaceProjection` must place run/fork/tick in the query key, pass abort signals, use canonical envelope data, poll only live nonterminal runs, and expose loading/error/envelope/data without hiding stale transport state.

`WorkspaceTable` renders a semantic `<table>`, internal overflow wrapper, empty body copy, and keyboard-selectable rows without page-level horizontal overflow.

- [ ] **Step 4: Add shared accessibility styles**

Add visible focus, selected row, stale/disabled callouts, internal table scrolling, narrow stacking, and `prefers-reduced-motion` rules. Avoid `100vw` inside the shell.

- [ ] **Step 5: Run unit/type/build and commit**

Run:

```bash
(
  cd dashboard
  npm test
  npm run typecheck
  npm run build
  git add src/workspaces/workspaceShared.tsx src/index.css tests/world-os-routes.test.js
  git diff --cached --check
  git commit -m "feat(world-os): add shared workspace primitives"
)
```

### Task 3: Implement the World workspace

**Files:**
- Create: `dashboard/src/workspaces/worldWorkspaceModel.js`
- Create: `dashboard/src/workspaces/WorldWorkspace.tsx`
- Modify: `dashboard/src/app/WorldOSApp.tsx`
- Modify: `dashboard/tests/world-os-routes.test.js`
- Modify: `dashboard/src/index.css`

**Interfaces:**
- Consumes: `/api/v2/workspaces/world`, shared Task 2 primitives, `CivicCity` in observer mode.
- Produces: region/place selection, population/currency/flow summaries, and canonical `/world` route.

- [ ] **Step 1: Add failing model tests**

Test `normalizeWorldWorkspace(data)` with missing arrays, invalid coordinates, duplicate flows, unknown endpoints, disabled civic data, and historical tick. Assert no invented value and stable region/place ordering.

- [ ] **Step 2: Run tests and verify missing model**

Run:

```bash
(cd dashboard && node --test tests/world-os-routes.test.js)
```

- [ ] **Step 3: Implement the pure model**

Return:

```javascript
{
  regions,
  agents,
  organizations,
  places,
  presence,
  flows,
  summary: { population, activeOrganizations, currencies, migrationCount, tradeCount },
}
```

Drop flows with unknown endpoints, preserve explicit disabled states, and never substitute current telemetry for historical data.

- [ ] **Step 4: Implement the workspace**

Render `FreshnessBadge`, bounded summary metrics, existing `CivicCity`/map presentation, region/place controls, and ordinary HTML inspector. Selection uses `region` or `place` query keys; links to People/Organizations/Investigations preserve run/fork/tick.

- [ ] **Step 5: Replace only the World legacy route**

Import `WorldWorkspace` in `WorldOSApp.tsx` and map `path="world"` to it. Leave the other four placeholders until their tasks pass.

- [ ] **Step 6: Run and commit**

Run:

```bash
(cd dashboard && npm test && npm run typecheck && npm run build)
git add src/workspaces/worldWorkspaceModel.js src/workspaces/WorldWorkspace.tsx src/app/WorldOSApp.tsx src/index.css tests/world-os-routes.test.js
git diff --cached --check
git commit -m "feat(world-os): implement world workspace"
```

### Task 4: Implement the Organizations workspace

**Files:**
- Create: `dashboard/src/workspaces/organizationsWorkspaceModel.js`
- Create: `dashboard/src/workspaces/OrganizationsWorkspace.tsx`
- Modify: `dashboard/src/app/WorldOSApp.tsx`
- Modify: `dashboard/tests/world-os-routes.test.js`
- Modify: `dashboard/src/index.css`

**Interfaces:**
- Consumes: `/api/v2/workspaces/organizations`, `FirmsPanel`, `BanksPanel`, `InstitutionsPanel` where contracts match.
- Produces: filterable organization directory and authoritative detail view.

- [ ] **Step 1: Add failing organization model tests**

Test search, sector, region, type, status, active-only, stable ID sort, disabled institutions, historical lifecycle, and hosted run isolation. Assert balances retain currency codes and no private owner data is accepted.

- [ ] **Step 2: Implement `normalizeOrganizationsWorkspace` and `filterOrganizations`**

Normalize firms, banks, institutions, contracts, disclosures, and public employment counts. Filters are deterministic and URL-safe. Unknown types/statuses render as escaped labels rather than disappearing.

- [ ] **Step 3: Implement directory/detail UI**

Use route `/organizations/:organizationId`; validate the ID against returned data before rendering a link/detail. Detail sections show identity, region, sector, lifecycle, public balances, employment, contracts, and disclosures only when present in the authorized projection.

- [ ] **Step 4: Reuse panels without embedding the full Observatory**

Import and compose the existing public exports from `WorldPanels.jsx`; keep those legacy exports working and do not copy their component bodies into the new workspace.

- [ ] **Step 5: Replace the Organizations routes and run gates**

Run:

```bash
(cd dashboard && npm test && npm run typecheck && npm run build)
```

Expected: list and detail routes compile; World route remains green.

- [ ] **Step 6: Commit**

Commit the model, workspace, route change, focused styles, tests, and any small reusable-panel extraction as:

```bash
git commit -m "feat(world-os): implement organizations workspace"
```

### Task 5: Implement the Markets workspace

**Files:**
- Create: `dashboard/src/workspaces/marketsWorkspaceModel.js`
- Create: `dashboard/src/workspaces/MarketsWorkspace.tsx`
- Modify: `dashboard/src/app/WorldOSApp.tsx`
- Modify: `dashboard/tests/world-os-routes.test.js`
- Modify: `dashboard/src/index.css`

**Interfaces:**
- Consumes: `/api/v2/workspaces/markets` and `MacroOverview` where metric units match.
- Produces: as-of order/trade/FX/circuit-breaker workspace with unit-explicit tables.

- [ ] **Step 1: Add failing market model tests**

Assert orders and trades are separate, buy/sell/filled/open filters work, quantities/prices/currencies retain units, FX base/quote direction is stable, circuit breakers are event records, and an empty order book is labelled empty rather than zero activity.

- [ ] **Step 2: Implement pure market normalization**

Expose:

```javascript
{
  orders, trades, fxOrders, fxTrades, circuitBreakers,
  totals: { tradeCount, tradeVolume, fxTradeCount },
  currencies,
}
```

Reject nonfinite numeric display inputs and never coerce missing values to measured zero.

- [ ] **Step 3: Implement the workspace**

Render bounded metrics, tab/filters for Orders, Trades, FX, and Circuit Breakers, semantic tables, explicit unit/currency columns, empty/disabled states, and links to validated organizations/events.

- [ ] **Step 4: Replace the Markets route and run gates**

Run unit/type/build checks. Add a source test proving `LegacyWorkspace title="Markets"` is absent.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(world-os): implement markets workspace"
```

### Task 6: Implement the Politics & Law workspace

**Files:**
- Create: `dashboard/src/workspaces/politicsLawWorkspaceModel.js`
- Create: `dashboard/src/workspaces/PoliticsLawWorkspace.tsx`
- Modify: `dashboard/src/app/WorldOSApp.tsx`
- Modify: `dashboard/src/components/V2Observatory.jsx` only for reusable extraction.
- Modify: `dashboard/tests/world-os-routes.test.js`
- Modify: `dashboard/src/index.css`

**Interfaces:**
- Consumes: `/api/v2/workspaces/politics-law`, `InstitutionalPulse`, and `LegalPoliticalPanels` where contracts match.
- Produces: bills/rules/lobbying/contracts/obligations/matters/M&A sections with explicit disabled states.

- [ ] **Step 1: Add failing model tests**

Test bill/vote/rule ordering, lobbying disclosure state, contract versus obligation type separation, legal matter status, institution-disabled copy, M&A review separation, and historical exclusion of later actions.

- [ ] **Step 2: Implement pure normalization and filters**

Do not collapse bills, votes, lobbying, contracts, obligations, cases, or mergers into one generic event type. Preserve jurisdiction, rule key, tick, status, and stable ID.

- [ ] **Step 3: Implement workspace sections**

Render overview pulse plus separate semantic tables/cards. Disabled politics/legal features show configured disabled state. Links to Investigations pass event/root IDs only from projection data.

- [ ] **Step 4: Replace the Politics & Law route, run gates, and commit**

Run unit/type/build checks and commit:

```bash
git commit -m "feat(world-os): implement politics and law workspace"
```

### Task 7: Implement the Experiments workspace

**Files:**
- Create: `dashboard/src/workspaces/experimentsWorkspaceModel.js`
- Create: `dashboard/src/workspaces/ExperimentsWorkspace.tsx`
- Modify: `dashboard/src/app/WorldOSApp.tsx`
- Reuse/Modify: `dashboard/src/components/AcceptancePanel.jsx`
- Reuse/Modify: `dashboard/src/components/OracleAndCost.jsx`
- Reuse/Modify: `dashboard/src/components/ReplayModal.jsx`
- Reuse/Modify: `dashboard/src/components/ShockModal.jsx`
- Modify: `dashboard/tests/world-os-routes.test.js`
- Modify: `dashboard/src/index.css`

**Interfaces:**
- Consumes: `/api/v2/workspaces/experiments`, existing fork endpoint `/api/v2/god/fork`, current run control authorization, acceptance/Oracle projections.
- Produces: diagnostic/rehearsal/live/release-labelled evidence cards and safe links/actions.

- [ ] **Step 1: Add failing classification tests**

Assert:

```javascript
assert.equal(classifyEvidence({ passed: true, real_providers: false }), "mechanics-only");
assert.equal(classifyEvidence({ status: "running" }), "partial");
assert.equal(classifyEvidence({ passed: true, exact_replay: true, eligible: true }), "eligible");
```

Also test `blocked`, `failed`, `not_run`, external-agent contamination, participant influence, stale commit/tree, and missing artifacts.

- [ ] **Step 2: Implement model and workspace**

Separate replay/forks, scripted rehearsals, live smokes, Oracle campaigns, acceptance runs, and release receipts. Render explicit reason/evidence for every label. Never infer eligibility from a green status badge alone.

- [ ] **Step 3: Preserve action authorization**

Fork and shock actions require paused/current tick and existing CSRF/operator rules. Live-provider and paid campaign controls link to operator instructions but do not start spend from this observer route without the existing explicit approval boundary.

- [ ] **Step 4: Replace Experiments routes and remove `LegacyWorkspace`**

After all five route tests pass, remove the `LegacyWorkspace` function and all uses. Keep wildcard fallback and canonical overview redirect.

- [ ] **Step 5: Run unit/type/build and commit**

```bash
(cd dashboard && npm test && npm run typecheck && npm run build)
git commit -m "feat(world-os): implement experiments workspace"
```

### Task 8: Prove all routes in real Chromium and close the placeholder contract

**Files:**
- Create: `dashboard/tests/e2e/world-os-routes.spec.ts`
- Modify: `dashboard/tests/e2e/world-os-privacy.spec.ts`
- Modify: `dashboard/tests/e2e/world-os-states.spec.ts`
- Modify: `docs/test-cases.md`

**Interfaces:**
- Consumes: Tasks 1–7.
- Produces: route-by-route desktop/mobile/accessibility/privacy receipts.

- [ ] **Step 1: Extend the stateful API mock for all workspace endpoints**

Provide live and tick-3 envelopes, disabled institutions, empty markets, one future-row canary, one private canary, and lineage/cursor changes. Assert the browser never receives future/private data at tick 3.

- [ ] **Step 2: Test canonical navigation and deep links**

Navigate through the rail and command palette to every route, directly load organization/experiment detail URLs, preserve run/fork/tick, and verify unknown routes redirect once to absolute overview.

- [ ] **Step 3: Test loading, empty, error, stale, and historical states**

For each route, delay one response, return one controlled error, return empty data, emit stale transport, and switch to historical tick. Assert correct state copy and no current telemetry mislabelled historical.

- [ ] **Step 4: Test keyboard, reduced motion, and narrow layout**

At 390px width, assert no page-level horizontal overflow. Tab through filters/tables/details, activate rows with Enter/Space, preserve focus during polling, and emulate reduced motion.

- [ ] **Step 5: Extend privacy assertions**

Scan DOM, URL, local/session storage, IndexedDB, console, page errors, and request failures for private/future canaries after every route and cross-route link.

- [ ] **Step 6: Run focused browser tests**

Run:

```bash
(
  cd dashboard
  npm run test:e2e -- --project=chromium tests/e2e/world-os-routes.spec.ts tests/e2e/world-os-privacy.spec.ts tests/e2e/world-os-states.spec.ts
)
```

Expected: all pass with zero browser/request errors.

- [ ] **Step 7: Update the test-case ledger**

Add route-specific test cases and mark placeholder-route coverage automated only after Step 6 passes. State explicitly that deeper later product redesigns remain out of scope.

- [ ] **Step 8: Commit browser evidence**

```bash
git add dashboard/tests/e2e/world-os-routes.spec.ts dashboard/tests/e2e/world-os-privacy.spec.ts dashboard/tests/e2e/world-os-states.spec.ts docs/test-cases.md
git diff --cached --check
git commit -m "test(world-os): prove canonical workspace routes"
```

### Task 9: Run the full compatibility and merge gate

**Files:**
- Verify: all files from Tasks 1–8.

**Interfaces:**
- Consumes: complete route implementation.
- Produces: merge-ready World OS route completion, not later-lake redesign or public release.

- [ ] **Step 1: Run focused server projection tests**

```bash
.venv/bin/python -m pytest tests/test_world_os_workspace_projections.py tests/test_semantics8_foundations.py tests/test_semantics12_civic_city.py tests/test_operator_workspace.py -q
```

- [ ] **Step 2: Run all eight Python shards**

```bash
for AE_CI_SHARD_INDEX in 0 1 2 3 4 5 6 7; do
  .venv/bin/python -m pytest tests/ -q -p scripts.pytest_shard --ci-shard-index "$AE_CI_SHARD_INDEX" --ci-shard-count 8 || exit 1
done
```

Expected: all shards pass; environment-gated skips are recorded separately.

- [ ] **Step 3: Run complete dashboard and documentation gates**

```bash
(
  cd dashboard
  npm ci
  npm test
  npm run typecheck
  npm run licenses:check
  npm audit --audit-level=high
  npm run test:e2e -- --project=chromium
  npm run build
)
.venv/bin/python -m pytest tests/test_documentation.py -q
git diff --check main...HEAD
```

- [ ] **Step 4: Verify source contract removal**

Run:

```bash
rg -n 'LegacyWorkspace|Canonical route established' dashboard/src dashboard/tests
```

Expected: no matches in application source; tests may mention the strings only as negative assertions.

- [ ] **Step 5: Perform a real Chrome live-run smoke**

Against an actual run, open every route in live and historical modes, inspect at least one entity/market/legal/evidence link, and record console/page/request/HTTP errors. Compare displayed tick/run/fork and representative values with direct APIs.

- [ ] **Step 6: Request review and prepare one PR with route-level commits**

Retain each route commit boundary. Reproduce review findings, add regressions for verified defects, rerun affected gates, and report the later redesign boundary explicitly in the PR.
