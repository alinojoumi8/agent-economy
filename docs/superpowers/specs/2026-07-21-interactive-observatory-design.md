# Interactive Observatory: Region Focus and Shared Inspection

## Goal

Make the Observatory feel explorable rather than read-only. The first delivery combines the approved interactive isometric Living Economy Map with a shared inspection system for static panels and a reliable region-first cross-filter.

This specification extends `2026-07-19-living-economy-map-design.md`. It does not replace the map's visual, aggregation, accessibility, or performance requirements. It supersedes one ownership detail: `ObservatoryInteractionProvider`, rather than `EconomicMap`, owns selected-region state; the map receives the selected region and emits selection actions.

## Delivery strategy

The approved staged direction is:

1. Add click-to-inspect behavior across static Observatory panels.
2. Make region selection the first shared cross-filter.
3. Defer time-range and entity-relationship cross-filtering until a later delivery.

This keeps the initial interaction model coherent and uses relationships that already exist in persisted data. It avoids pretending that panels have regional provenance when their payloads do not contain it.

## Considered approaches

### Shared Observatory interaction layer — selected

One provider owns region focus and inspection state. Panels emit typed selections and receive only the focus data they can use truthfully. This produces consistent behavior, keeps cross-panel coordination explicit, and lets polling continue independently.

### URL-driven interaction state

Region and inspection state could live in query parameters. That would make views shareable and reload-stable, but it would introduce routing and history semantics before the interaction model has matured. URL state is deferred.

### Independent panel interactions

Each panel could own its own modal, filter, and selection. This is mechanically simple but creates inconsistent keyboard behavior, duplicated formatting, and no cross-panel focus. It is not selected.

## Architecture

`Observatory.jsx` wraps its panel grid in an `ObservatoryInteractionProvider`. The provider exposes two independent state machines:

- `regionFocus`: either `null` or `{ regionId, regionKey, regionName }`.
- `inspection`: either `null` or a typed reference with a fallback snapshot.

The public interaction surface is intentionally small:

- `selectRegion(region)` toggles the active region.
- `clearRegion()` removes the cross-filter.
- `inspect(reference, fallbackSnapshot)` opens the shared drawer.
- `closeInspection()` closes the drawer and restores focus.

The provider does not fetch simulation data and does not mutate the run. Existing polling in `useObservatory.js` remains the source of dashboard payloads. `Observatory` passes current payload collections to the inspector resolver so an open item can refresh when the same record remains available.

## Shared components

### Region focus bar

The focus bar appears below the run header only while a region is selected. It contains the region name, a concise explanation that related panels are filtered, and a clear button. It is sticky on desktop and remains in normal document flow on narrow screens.

The bar reports which panels are affected: firms, agents, and region-tagged events. It never claims that banks, metrics, news, law, politics, or acceptance results are region-filtered.

### Inspector drawer

The inspector is a modeless right-side drawer on wide screens and a bottom sheet on narrow screens. Live polling and run controls remain visible behind it.

The drawer accepts typed references for:

- bank;
- firm;
- public institution;
- news article;
- macro metric;
- legal matter or obligation;
- bill;
- startup lifecycle record or summary;
- acceptance check or shock trace;
- provider-cost record;
- event.

Each type maps to a normalized presentation with a title, subtitle, labeled fields, optional narrative text, and optional provenance/raw data. The drawer stores the snapshot that was clicked and also attempts to resolve the same item from the latest payload. If the item falls outside a recent-results window, it shows the fallback snapshot with a `Last observed` label instead of closing unexpectedly.

The existing agent modal, Oracle form, participant controls, replay modal, shock modal, calibration scope selector, conversation search, and event raw toggle remain specialized interactions and are not replaced.

## Region-first cross-filter

### Living Economy Map

Selecting a region platform sets `regionFocus`; selecting it again, using the map background, pressing Escape in the map, or using the focus bar clears it. The map keeps its compact in-card region inspector from the map design. Connected trade and migration routes remain prominent while unrelated routes recede.

### Firms

`/api/v2/map` already returns active firm IDs with region IDs. When a region is focused, `FirmsPanel` intersects its normal `/api/firms` snapshot with those IDs. The filtered state therefore shows active firms known to belong to the region. Bankrupt or acquired firms absent from the map payload are not guessed into a region.

The panel header reports `N firms in Region Name`, and an empty result explains that no active mapped firms are present. Clearing the region restores the complete table. Clicking a ticker chip or table row opens the firm inspector.

### Agents

`GET /api/agents` gains one optional integer query parameter, `region_id`. The server applies the exact `a.region_id=?` predicate alongside the existing search, population-tier, cursor, and total-count logic.

`agentDirectoryPath` accepts `regionId` and serializes it as `region_id`. A region change resets the agent cursor to the first page while preserving the user's text search and tier selection. A failed filtered request keeps the last valid directory page visible and shows an inline error; it does not replace the directory with an empty result.

The existing agent modal and participant-mode behavior remain unchanged.

### Events

An event is region-related only when its top-level payload contains the selected numeric region ID under one of these explicit keys:

- `region_id`;
- `origin_region_id`;
- `destination_region_id`;
- `source_region_id`;
- `target_region_id`;
- `issuer_region_id`.

Numeric values under unrelated keys are never interpreted as regions. With a region focused, `EventsPanel` defaults to related events and provides a `Show all` toggle. If none of the current recent events match, the panel explains that the event window has no region-tagged records and offers the same toggle.

Clicking an event opens the shared inspector. The existing `Human`/`Raw` toggle continues to control inline payload rendering.

### Panels intentionally not region-filtered

Banks, public institutions, macro metrics, news, conversations, legal matters, bills, startup records, Oracle data, calibration, provider costs, acceptance evidence, and participant state remain unfiltered unless their current payloads gain an explicit reliable regional relationship in a future design.

The static records named in the next section still gain click-to-inspect. Existing specialized interactions remain unchanged.

## Inspectable panel behavior

- `BanksPanel`: bank rows open deposits, reserves, reserve ratio, loans, trust, and status.
- `FirmsPanel`: ticker chips and rows open production, employment, price, stock, cash, sector, and status.
- `InstitutionsPanel`: government, venture-capital, and health sections open their full current payloads as labeled fields.
- `MacroOverview`: each metric card opens its definition, current value, delta, and recent series points. Existing mini charts remain unchanged.
- `NewsPanel`: article cards open the full body, outlet, day, tone, truthfulness, slant tags, and source event IDs.
- `InstitutionalPulse` and `LegalPoliticalPanels`: matters, obligations, bills, and available startup records open structured details; summary-only counts identify themselves as summaries rather than fabricated records.
- `AcceptancePanel`: checks and shock traces open their exact evidence objects with readable labels and an optional raw-data section.
- `CostPanel`: model, purpose, and agent cost rows open their exact call, token, and spend fields.
- `EventsPanel`: event rows open kind, day, phase, importance, and payload.

Inspectable rows and cards use visible hover and focus treatment but remain semantically appropriate buttons or button-containing rows. Table-row activation supports Enter and Space.

## Data flow and polling

1. `useObservatory` refreshes all existing payloads on its current schedule.
2. The interaction provider retains `regionFocus` and the inspection reference across refreshes.
3. The map payload supplies region identity and active firm membership.
4. Region focus is passed only to Firms, Agents, and Events.
5. The inspector resolver searches the latest relevant payload by type and ID.
6. If a focused region disappears from the map payload, the provider clears the region and announces the change through an `aria-live` status.
7. If an inspected item is no longer present, the drawer keeps its fallback snapshot and labels it `Last observed`.

No inspection or filtering action writes to the API, simulation database, or event spine.

## Error and empty states

- Existing whole-Observatory refresh warnings remain unchanged.
- Region-filtered agent fetch errors are local to `AgentsPanel` and preserve the last successful directory data.
- A filtered panel distinguishes `no related records in the current window` from `system disabled` and from `data not loaded`.
- Malformed inspector snapshots render only validated labeled fields and a safe JSON fallback; they do not throw the Observatory render tree.
- Unknown inspection kinds show `Unsupported inspection item` and remain closable.
- Missing map regions clear focus rather than retaining a misleading filter.

## Accessibility and motion

- All inspectable items are keyboard reachable and activate with Enter or Space.
- The focus bar and drawer have explicit accessible names.
- Opening the drawer moves focus to its heading or close control. Closing restores focus to the exact trigger when it still exists.
- Escape closes the drawer first; a second Escape in the map or focus bar clears region focus.
- The modeless drawer does not trap focus or mark background content inert.
- Filter status and automatic focus clearing use polite live-region announcements.
- Color is supplementary to labels, pressed states, route patterns, and count text.
- The existing reduced-motion requirement for the map also covers drawer and focus-bar transitions.

## Responsive behavior

- Desktop: the focus bar is sticky beneath the run header; the drawer occupies the right edge without covering run controls.
- Tablet: the drawer uses a narrower overlay with a visible close control.
- Mobile: the focus bar scrolls normally and the inspector becomes a bottom sheet capped below the viewport header.
- Tables retain horizontal scrolling, and inspection does not require hover.

## Testing and verification

Automated tests cover:

- interaction reducer transitions and toggle semantics;
- exact region-key event matching without false numeric matches;
- firm-ID intersection from the map payload;
- `region_id` API filtering combined with search, tier, counts, and cursor pagination;
- `agentDirectoryPath` query encoding and cursor reset on region change;
- inspector normalization and missing-item fallback behavior;
- server-rendered accessible labels, buttons, pressed states, focus bar, and drawer structure;
- existing specialized interactions and empty-state tests;
- the full Python and dashboard suites plus a production dashboard build.

Browser acceptance uses the isolated worktree Vite preview at `http://127.0.0.1:5173/`, with a local TCP forward from Vite's configured API target on port `8000` to the live run API on port `8001`. It verifies:

- desktop and mobile layouts;
- region selection and clearing;
- firm, agent, and event filtering;
- `Show all` event behavior;
- inspection from every newly interactive panel type;
- focus movement and restoration;
- Escape ordering;
- polling stability;
- reduced-motion behavior.

## Out of scope

- Time-range cross-filtering.
- Agent, firm, or bank relationship graphs outside the approved map.
- URL-persisted or shareable interaction state.
- New detail endpoints for inspected records.
- Region inference from names, sectors, narrative text, or arbitrary numeric payload values.
- Any simulation mutation from the inspector or region focus.
