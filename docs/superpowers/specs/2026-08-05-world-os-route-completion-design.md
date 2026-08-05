# World OS Legacy Route Completion Design

## Goal

Replace the World, Organizations, Markets, Politics & Law, and Experiments placeholder routes with useful, authoritative workspaces that rehouse existing Observatory capabilities while preserving the shared World OS navigation, time, lineage, freshness, privacy, and accessibility contracts.

## Scope boundary

The first causal-lake product contract intentionally delivered full new behavior for Overview, News & Communications, and Investigations. The remaining routes were allowed to mount the persistent shell and preserve current panels. They currently show `LegacyWorkspace` copy and link back to the older Observatory. This design closes that rehousing gap; it does not claim the later full-depth synthetic-map, organization-management, Bloomberg-terminal, election-night, or experiment-laboratory redesigns described as future product work.

Each route is an independent deliverable. A route can merge when its own projections and browser evidence pass without waiting for every later redesign.

## Considered approaches

### 1. Route-native wrappers around existing authoritative projections — selected

Create focused TypeScript workspaces that query current projection endpoints with the shared observer state and render extracted reusable panels. This removes dead-end navigation quickly while retaining current engine semantics and evidence.

### 2. Embed the entire legacy Observatory inside every route

This would remove placeholders but duplicate unrelated panels, break information architecture, and make route URLs misleading.

### 3. Build all later product redesigns now

The deeper designs are large independent products and lack one frozen acceptance contract. Combining them would obscure the achievable rehousing requirement and create a multi-month unreviewable change.

## Shared workspace architecture

All five workspaces use:

- `useObserverViewState` and projection-scope helpers for run, fork, tick, and historical mode;
- TanStack Query keys containing run, fork, tick, and route-specific filters;
- `FreshnessBadge` and the shared transport context;
- projection envelopes as the only source of world values;
- route-addressable selections and filters;
- explicit loading, empty, error, stale, and unsupported-semantics states;
- current privacy allowlists and no raw private-body rendering.

Reusable panels are extracted or adapted rather than copied. Data-shaping functions remain pure and testable; workspace components own routing and query state.

## Route contracts

### World

World displays the authoritative regional/civic map, population summary, currencies, migration/trade flows, places, presence, and run phase. It consumes `/api/v2/world-map`, `/api/v2/civic/summary`, and the bounded snapshot summary. Selecting a region or place updates ordinary HTML details and a URL-safe public identifier. Historical ticks never mix with current provider telemetry.

### Organizations

Organizations displays active firms, banks, and institutions using existing firm/institution projections and components such as `FirmsPanel`, `BanksPanel`, and `InstitutionsPanel`. Search, status, region, and sector filters are addressable. Selecting an organization shows only authoritative public balances, employment, lifecycle, contracts, and disclosures available to the observer.

### Markets

Markets uses `/api/v2/markets` plus bounded macro and regional projections to show orders, executed trades, FX orders/trades, circuit-breaker events, prices, and volume. It reuses `MacroOverview` where its metric contract matches. Tables retain units and currencies explicitly; empty order books are not reported as zero economic activity.

### Politics & Law

Politics & Law uses existing legal, politics, information, and startup projections with `InstitutionalPulse` and `LegalPoliticalPanels` extracted into route-appropriate sections. Bills, lobbying, rules, contracts, obligations, legal matters, and M&A reviews remain separate types. Disabled institutions show their configured state rather than an empty-data implication.

### Experiments

Experiments rehouses existing replay, fork, acceptance, Oracle/calibration, shock, and evidence entry points. It distinguishes read-only historical replay, new fork creation, scripted rehearsal, live-provider work, and release-evidence campaigns. Paid or state-changing actions retain their existing authorization and pause requirements. The workspace never labels a diagnostic or partial run as acceptance.

## Navigation and selection

Every route preserves `runId`, fork, tick, and supported filters when linking to People, Communications, Investigations, or another workspace. Entity links use validated IDs from projection data. Selecting historical time exits live follow explicitly; returning to live is a deliberate control. Global command navigation continues to resolve the same canonical paths.

## Resilience and accessibility

Tables and visual summaries provide semantic alternatives. Keyboard users can reach filters, selections, and detail panels; focus does not reset on polling. Reduced-motion mode removes decorative transitions. Narrow layouts avoid horizontal page overflow and retain readable tables through bounded internal scrolling. Projection lineage changes trigger stale recovery rather than combining two worlds.

## Verification

Each route receives:

- pure projection/model tests for units, grouping, filters, and disabled states;
- React tests for loading, empty, error, stale, historical tick, and selection behavior;
- route/navigation tests preserving run/fork/tick query state;
- privacy tests for public allowlists and canaries;
- Playwright desktop and mobile flows in real Chromium;
- keyboard, focus, reduced-motion, and no-horizontal-overflow checks;
- a production build and full dashboard regression suite.

Experiments additionally tests authorization boundaries and diagnostic-versus-release labels. Markets tests currency/unit formatting. Politics & Law tests disabled institutions. World tests historical projection consistency. Organizations tests tenant/run isolation in hosted mode.

## Delivery ordering

Shared projection and workspace primitives land first. The route order is World, Organizations, Markets, Politics & Law, then Experiments because later routes reuse entities and evidence links established earlier. Each route is committed and reviewed independently. `LegacyWorkspace` is removed only after all canonical routes have real implementations and wildcard fallback remains tested.

## Acceptance evidence

Completion requires all five canonical routes to render authoritative data without redirecting to the legacy root, route-specific automated and Chromium receipts, preserved privacy and historical-time behavior, and removal of `LegacyWorkspace`. Rehousing existing panels closes this task; later deep redesigns require separate approved specifications and cannot be implied by these route names.

## Out of scope

- New simulation semantics or database migrations.
- A graph-database rewrite or distributed world writers.
- Full later-lake product redesigns not frozen in the current release contract.
- Editing authoritative world state from observer workspaces.
