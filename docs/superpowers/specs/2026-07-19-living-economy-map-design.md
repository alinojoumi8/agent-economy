# Living Economy Map: Interactive Isometric Redesign

## Goal

Replace the Observatory's flat regional SVG with a richer, pseudo-3D economic atlas that makes regional scale, firms, strategic agents, trade, and migration easier to read and explore. The map must remain fast, responsive, accessible, and faithful to measured `/api/v2/map` data.

The view is an abstract economic topology, not a geographic map. Existing normalized region coordinates continue to determine placement.

## Considered approaches

### 1. Isometric SVG atlas — selected

Build the scene from SVG layers, gradients, filters, curved paths, and semantic controls. This produces convincing depth while retaining crisp text, direct keyboard interaction, deterministic rendering, and a small bundle. It also fits the current React and SVG implementation without adding a rendering dependency.

### 2. CSS 3D board

Place DOM cards on a perspective-tilted plane. Region panels would be easy to style, but routing curved flows between independently transformed elements would be brittle, and labels would distort or require a second overlay coordinate system.

### 3. WebGL scene

Use a true 3D camera and meshes. This would allow orbiting and more dramatic depth, but three regions do not justify the extra runtime, bundle size, accessibility work, rendering complexity, or test burden.

## Selected experience

The map becomes a dark, isometric command-table scene. A perspective floor grid and soft vignette establish depth. Each region sits on a raised, layered platform with a shadow, luminous top surface, population ring, and small vertical economy markers. Platform footprint reflects population; marker count and height communicate firm activity without implying false precision.

Trade and migration use separate curved, elevated routes. Trade remains mint and migration remains gold. Duplicate API rows are aggregated by source, destination, and kind before rendering so a busy run produces readable route strength instead of dozens of overlapping lines. Route width and an accompanying count encode aggregate activity. Motion uses restrained flowing dashes or particles and stops when the user requests reduced motion.

The visual language stays inside the existing Observatory palette: ink backgrounds, mint trade activity, gold migration, coral accents, and slate labels. The map remains visually compatible with the surrounding institutional panels.

## Interaction design

The scene has three layer controls: Trade, Migration, and Actors. Trade and migration start enabled; Actors controls strategic-agent and firm markers. Controls are real buttons with pressed state, visible focus, and text labels.

Hovering or keyboard-focusing a region raises its contrast and shows a compact tooltip. Clicking a region locks the selection and opens a detail panel containing:

- population and population target;
- currency and specializations;
- active firm and strategic-agent counts;
- inbound and outbound trade totals;
- inbound and outbound migration totals.

When a region is selected, connected routes remain prominent and unrelated routes recede. Clicking the selected region again, clicking the scene background, or pressing Escape clears the selection. Region platforms are keyboard-reachable and respond to Enter and Space.

Hovering or focusing a route shows its kind, direction, aggregate count or magnitude, and known statuses. Route hit targets are wider and transparent so thin visible strokes remain easy to interact with.

On narrow layouts, the detail panel stacks below the scene. On wide layouts, it occupies a compact rail within the map card. Text never rotates with the isometric floor.

## Component architecture

The map moves into a focused `LivingEconomyMap.jsx` module while preserving the existing `EconomicMap` export used by `V2Observatory.jsx` and its tests.

The module has four clear responsibilities:

- `normalizeMapData` validates coordinates, groups firms and agents by region, and derives per-region totals.
- `aggregateFlows` groups recent flow rows by source, destination, and kind and preserves status counts.
- `EconomyScene` renders the SVG floor, routes, region platforms, actors, and SVG definitions.
- `RegionInspector` renders selection details and summary metrics as ordinary HTML.

`EconomicMap` owns only view state: selected region, hovered/focused item, and enabled layers. The API response remains the source of truth; the component does not invent simulated values or mutate run state.

## Data flow

`Observatory` continues to pass `data.v2.map` into `EconomicMap`. No endpoint or persistence changes are required.

1. The component normalizes the map payload and drops flows whose endpoints are absent.
2. Recent flow rows are aggregated into stable route records.
3. Region summaries are derived from regions, firms, strategic agents, and aggregated routes.
4. Layer and selection state determine presentation only; they never change the underlying data.
5. Polling updates replace the payload while the selected region remains selected if it still exists. Selection clears if that region disappears.

## Resilience and accessibility

The current disabled and no-data empty states remain unchanged. Missing arrays are treated as empty. Invalid coordinates are clamped to the scene bounds, and unknown flow endpoints are ignored rather than rendered at an arbitrary origin.

The SVG keeps an explicit accessible name and description. Interactive regions and routes expose meaningful labels, keyboard behavior, focus indication, and pressed states where applicable. Tooltips are supplementary; the selected detail panel contains the durable readable information. Color is never the only route distinction: trade and migration also use different dash patterns and labels.

Animation is decorative. `prefers-reduced-motion: reduce` disables route motion and nonessential transitions. The scene remains understandable without hover, animation, or fine pointer input.

## Performance constraints

The redesign adds no new production dependency. Up to 100 API flow rows are reduced to at most one route per source/destination/kind combination before rendering. Actor dots remain bounded by the API's existing core-agent limit. SVG filters are shared through one definitions block rather than duplicated per region.

## Testing and verification

Automated coverage will verify:

- flow aggregation, magnitude totals, and status counts;
- missing endpoints and malformed optional arrays;
- server-rendered accessibility labels, layer controls, and the disabled empty state;
- region summary counts for firms, strategic agents, and inbound/outbound flows;
- a production dashboard build and the existing dashboard test suite.

Browser verification will confirm the live day-92+ payload renders correctly at desktop and mobile widths, layer controls work, mouse and keyboard selection work, the inspector updates, Escape clears selection, and reduced-motion mode removes route animation. A final screenshot review will check label collisions and scene readability against the surrounding Observatory panels.

## Out of scope

- A rotatable globe, free-orbit camera, or true terrain model.
- Backend schema or `/api/v2/map` response changes.
- Geographic borders or claims of real-world location accuracy.
- Editing regions, firms, agents, or flows from the map.
- Replacing the Observatory's overall visual system.
