# Interactive Observatory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the Observatory into a responsive, accessible exploration surface with an isometric economy map, shared click-to-inspect drawer, and truthful region-first cross-filtering.

**Architecture:** Keep `/api/v2/map` unchanged and add one exact optional `region_id` filter to `/api/agents`. A pure map model aggregates routes; a separate interaction model owns event matching, firm membership, and inspector normalization; `ObservatoryInteractionProvider` owns selected-region and inspection state while existing panels opt into region filtering or click inspection only when their payloads support it.

**Tech Stack:** React 19.2, JavaScript modules, SVG, Tailwind CSS 4.3, Vite 8.1, Node's built-in test runner, React server rendering.

## Global Constraints

- Add no new production dependency.
- Treat the view as an abstract economic topology, not a geographic map.
- Keep `/api/v2/map`, persistence, and simulation state unchanged; the only API extension is optional integer `region_id` on `GET /api/agents`.
- Preserve the current disabled and no-data empty-state copy.
- Aggregate at most 100 API flow rows into one route per source, destination, and kind.
- Trade is mint and solid-dashed; migration is gold and dotted-dashed so color is not the only distinction.
- Tooltips are supplementary; durable selected-region information lives in ordinary HTML.
- `prefers-reduced-motion: reduce` disables decorative route motion and nonessential transitions.
- Region focus filters only active mapped firms, exactly matching agents, and events with explicit top-level region keys.
- Banks, institutions, macro metrics, news, conversations, law, politics, startup records, Oracle data, calibration, costs, acceptance evidence, and participant state must never be inferred into a region.
- Existing agent modal, Oracle, participant, replay, shock, calibration, conversation-search, and event-raw interactions remain intact.
- The shared inspector is modeless, restores trigger focus, and keeps a last-observed fallback when polling drops an item from the current result window.
- Time-range, entity-relationship, and URL-persisted filters remain out of scope.
- Preserve unrelated working-tree changes and stage only feature-specific files or hunks.

## File structure

- Create `dashboard/src/components/livingEconomyMapModel.js`: payload validation, flow aggregation, and region-summary derivation only.
- Create `dashboard/src/components/LivingEconomyMap.jsx`: React state, layer controls, SVG scene, region platforms, routes, tooltip, and inspector.
- Create `dashboard/src/observatoryInteraction.js`: pure region toggle, event match, firm membership, inspection resolution, and presentation helpers.
- Create `dashboard/src/components/ObservatoryInteraction.jsx`: context provider, focus bar, modeless inspector drawer, focus restoration, and live announcements.
- Modify `dashboard/src/components/V2Observatory.jsx:1-34`: remove the old flat-map implementation and re-export `EconomicMap` from the focused module; leave the institutional panels intact.
- Modify `dashboard/src/components/ui.jsx`: make `Empty` honor existing `text` props while giving explicit children precedence.
- Modify `dashboard/src/components/Observatory.jsx`: install the interaction provider, focus bar, and drawer around the existing panel grid.
- Modify `dashboard/src/components/WorldPanels.jsx`: region-filter firms and add bank, firm, and institution inspection triggers.
- Modify `dashboard/src/components/InformationPanels.jsx`: region-filter events and add news/event inspection triggers.
- Modify `dashboard/src/components/MacroOverview.jsx`, `dashboard/src/components/OracleAndCost.jsx`, `dashboard/src/components/AcceptancePanel.jsx`, and `dashboard/src/components/V2Observatory.jsx`: add inspection triggers to static records.
- Modify `dashboard/src/components/AgentsPanel.jsx`: serialize and react to the exact selected region while preserving search, tier, paging, and the existing agent modal.
- Modify `dashboard/src/hooks/useObservatory.js`: stop polling the unbounded legacy agent array after the bounded directory owns its own requests.
- Modify `server/app.py`: add the optional exact `region_id` agent-directory predicate.
- Modify `dashboard/src/index.css:154-156`: add scene focus, route-flow animation, depth, hover, and reduced-motion styles before the existing reduced-motion rule.
- Create `dashboard/tests/living-economy-map.test.js`: pure projection tests plus server-rendered component and accessibility assertions.
- Create `dashboard/tests/observatory-interaction.test.js`: pure interaction, inspection, cross-filter, and server-rendered shell assertions.
- Create `tests/test_observatory_region_filter.py`: API filtering combined with search, tier, counts, and cursor pagination.
- Regenerate `server/static/index.html` and its hashed assets with `npm run build`; these are build artifacts, not hand-edited sources.

---

### Task 1: Normalize and aggregate live map data

**Files:**
- Create: `dashboard/src/components/livingEconomyMapModel.js`
- Create: `dashboard/tests/living-economy-map.test.js`

**Interfaces:**
- Consumes: the existing `/api/v2/map` object with optional `enabled`, `regions`, `firms`, `core_agents`, and `flows` arrays.
- Produces: `aggregateFlows(flows, regionIds)` and `normalizeMapData(map)`.
- `aggregateFlows` returns records shaped as `{ id, kind, source_region_id, target_region_id, magnitude, count, statuses }`.
- `normalizeMapData` returns `{ enabled, regions, routes, firms, coreAgents }`; every region includes `firmItems`, `coreAgentItems`, and `flowTotals.trade|migration.inbound|outbound`.

- [ ] **Step 1: Write failing projection tests**

Create `dashboard/tests/living-economy-map.test.js` with:

```js
import assert from "node:assert/strict";
import test from "node:test";

import { aggregateFlows, normalizeMapData } from "../src/components/livingEconomyMapModel.js";

const regionIds = new Set([1, 2, 3]);

test("aggregateFlows groups routes and preserves status counts", () => {
  const routes = aggregateFlows([
    { id: 1, source_region_id: 1, target_region_id: 2, kind: "trade", magnitude: 4, status: "completed" },
    { id: 2, source_region_id: 1, target_region_id: 2, kind: "trade", magnitude: 6, status: "in_transit" },
    { id: 3, source_region_id: 3, target_region_id: 1, kind: "migration", magnitude: 1, status: "completed" },
    { id: 4, source_region_id: 9, target_region_id: 1, kind: "trade", magnitude: 99, status: "completed" },
    { id: 5, source_region_id: 1, target_region_id: 2, kind: "unknown", magnitude: 99, status: "completed" },
  ], regionIds);

  assert.deepEqual(routes, [
    {
      id: "migration:3:1",
      kind: "migration",
      source_region_id: 3,
      target_region_id: 1,
      magnitude: 1,
      count: 1,
      statuses: { completed: 1 },
    },
    {
      id: "trade:1:2",
      kind: "trade",
      source_region_id: 1,
      target_region_id: 2,
      magnitude: 10,
      count: 2,
      statuses: { completed: 1, in_transit: 1 },
    },
  ]);
});

test("normalizeMapData clamps coordinates and derives regional totals", () => {
  const scene = normalizeMapData({
    enabled: true,
    regions: [
      {
        id: 1, name: "Northstar Federation", region_key: "northstar",
        currency_code: "NSD", x: -4, y: 0.35, population: 650,
        population_target: 600, specialization: ["technology", "finance"], firms: 99,
      },
      {
        id: 2, name: "Ironvale Union", region_key: "ironvale",
        currency_code: "IVC", x: 4, y: "bad", population: 146,
        population_target: 220, specialization_json: "[\"energy\"]",
      },
    ],
    firms: [
      { id: 10, name: "Foundry", region_id: 1, sector: "manufacturing" },
      { id: 11, name: "Grid", region_id: 2, sector: "energy" },
      { id: 12, name: "Missing", region_id: 9, sector: "services" },
    ],
    core_agents: [
      { id: 20, name: "Governor Vale", region_id: 1, role: "central_banker" },
      { id: 21, name: "Unplaced", region_id: null, role: "editor" },
    ],
    flows: [
      { id: 30, source_region_id: 1, target_region_id: 2, kind: "trade", magnitude: 7, status: "completed" },
      { id: 31, source_region_id: 2, target_region_id: 1, kind: "migration", magnitude: 1, status: "completed" },
    ],
  });

  assert.equal(scene.enabled, true);
  assert.equal(scene.regions[0].x, 0.08);
  assert.equal(scene.regions[1].x, 0.92);
  assert.equal(scene.regions[1].y, 0.5);
  assert.deepEqual(scene.regions[1].specialization, ["energy"]);
  assert.equal(scene.firms.length, 2);
  assert.equal(scene.coreAgents.length, 1);
  assert.equal(scene.regions[0].firmItems.length, 1);
  assert.equal(scene.regions[0].coreAgentItems.length, 1);
  assert.deepEqual(scene.regions[0].flowTotals, {
    trade: { inbound: 0, outbound: 7 },
    migration: { inbound: 1, outbound: 0 },
  });
});

test("normalizeMapData treats malformed optional collections as empty", () => {
  const scene = normalizeMapData({ enabled: false, regions: null, firms: {}, core_agents: "bad", flows: 4 });
  assert.deepEqual(scene, { enabled: false, regions: [], routes: [], firms: [], coreAgents: [] });
});
```

- [ ] **Step 2: Run the projection tests to verify they fail**

Run:

```bash
cd dashboard && node --test tests/living-economy-map.test.js
```

Expected: FAIL with `ERR_MODULE_NOT_FOUND` for `livingEconomyMapModel.js`.

- [ ] **Step 3: Implement the pure map-data model**

Create `dashboard/src/components/livingEconomyMapModel.js` with:

```js
const asArray = value => Array.isArray(value) ? value : [];
const finite = (value, fallback = 0) => Number.isFinite(Number(value)) ? Number(value) : fallback;
const clamp = (value, minimum, maximum) => Math.min(maximum, Math.max(minimum, value));
const numericId = value => Number.isFinite(Number(value)) ? Number(value) : null;

function specializations(region) {
  if (Array.isArray(region.specialization)) return region.specialization.map(String);
  try {
    const parsed = JSON.parse(region.specialization_json || "[]");
    return Array.isArray(parsed) ? parsed.map(String) : [];
  } catch {
    return [];
  }
}

export function aggregateFlows(flows, regionIds) {
  const allowed = regionIds instanceof Set ? regionIds : new Set();
  const grouped = new Map();

  for (const flow of asArray(flows)) {
    const kind = flow?.kind === "trade" || flow?.kind === "migration" ? flow.kind : null;
    const sourceId = numericId(flow?.source_region_id);
    const targetId = numericId(flow?.target_region_id);
    if (!kind || !allowed.has(sourceId) || !allowed.has(targetId) || sourceId === targetId) continue;

    const id = `${kind}:${sourceId}:${targetId}`;
    const status = String(flow?.status || "unknown");
    const magnitude = Math.max(0, finite(flow?.magnitude, 1));
    const route = grouped.get(id) || {
      id,
      kind,
      source_region_id: sourceId,
      target_region_id: targetId,
      magnitude: 0,
      count: 0,
      statuses: {},
    };
    route.magnitude += magnitude;
    route.count += 1;
    route.statuses[status] = (route.statuses[status] || 0) + 1;
    grouped.set(id, route);
  }

  return [...grouped.values()].sort((left, right) => left.id.localeCompare(right.id));
}

export function normalizeMapData(map) {
  const payload = map && typeof map === "object" ? map : {};
  const baseRegions = asArray(payload.regions).map(region => {
    const id = numericId(region?.id);
    if (id === null) return null;
    return {
      ...region,
      id,
      name: String(region?.name || region?.region_key || `Region ${id}`),
      x: clamp(finite(region?.x, 0.5), 0.08, 0.92),
      y: clamp(finite(region?.y, 0.5), 0.08, 0.92),
      population: Math.max(0, finite(region?.population, 0)),
      population_target: Math.max(0, finite(region?.population_target, 0)),
      specialization: specializations(region || {}),
    };
  }).filter(Boolean);
  const regionIds = new Set(baseRegions.map(region => region.id));
  const firms = asArray(payload.firms)
    .map(firm => ({ ...firm, region_id: numericId(firm?.region_id) }))
    .filter(firm => regionIds.has(firm.region_id));
  const coreAgents = asArray(payload.core_agents)
    .map(agent => ({ ...agent, region_id: numericId(agent?.region_id) }))
    .filter(agent => regionIds.has(agent.region_id))
    .slice(0, 100);
  const routes = aggregateFlows(payload.flows, regionIds);

  const regions = baseRegions.map(region => ({
    ...region,
    firmItems: firms.filter(firm => firm.region_id === region.id),
    coreAgentItems: coreAgents.filter(agent => agent.region_id === region.id),
    flowTotals: {
      trade: { inbound: 0, outbound: 0 },
      migration: { inbound: 0, outbound: 0 },
    },
  }));
  const byId = new Map(regions.map(region => [region.id, region]));
  for (const route of routes) {
    byId.get(route.source_region_id).flowTotals[route.kind].outbound += route.magnitude;
    byId.get(route.target_region_id).flowTotals[route.kind].inbound += route.magnitude;
  }

  return { enabled: payload.enabled !== false, regions, routes, firms, coreAgents };
}
```

- [ ] **Step 4: Run the projection tests to verify they pass**

Run:

```bash
cd dashboard && node --test tests/living-economy-map.test.js
```

Expected: 3 tests pass, 0 fail.

- [ ] **Step 5: Commit the isolated data-model task**

Run:

```bash
git add -- dashboard/src/components/livingEconomyMapModel.js dashboard/tests/living-economy-map.test.js
git diff --cached --check
git -c user.name='Oneworld' -c user.email='168804661+alinojoumi8@users.noreply.github.com' commit -m "feat(observatory): model living economy map data"
```

Expected: a commit containing only the new model and focused tests. Git identity remains command-local; repository and global Git configuration are not changed.

---

### Task 2: Render and integrate the interactive isometric scene

**Files:**
- Create: `dashboard/src/components/LivingEconomyMap.jsx`
- Modify: `dashboard/src/components/V2Observatory.jsx:1-34`
- Modify: `dashboard/src/components/ui.jsx:29-31`
- Modify: `dashboard/tests/living-economy-map.test.js`

**Interfaces:**
- Consumes: `normalizeMapData(map)` from Task 1, the existing `Panel` and `Empty` components, and `number()`/`shortKind()` formatting utilities.
- Produces: `EconomicMap({ map })`, re-exported from `V2Observatory.jsx` with the same import contract used by `Observatory.jsx` and existing tests.
- Selection is represented by a numeric `selectedRegionId`; layers are `{ trade: boolean, migration: boolean, actors: boolean }`.

- [ ] **Step 1: Add failing server-rendered scene assertions**

Append to `dashboard/tests/living-economy-map.test.js`:

```js
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";

const renderedMap = {
  enabled: true,
  regions: [
    {
      id: 1, name: "Northstar Federation", region_key: "northstar", currency_code: "NSD",
      x: 0.25, y: 0.35, population: 650, population_target: 600,
      specialization: ["technology", "finance"],
    },
    {
      id: 2, name: "Ironvale Union", region_key: "ironvale", currency_code: "IVC",
      x: 0.72, y: 0.28, population: 146, population_target: 220,
      specialization: ["manufacturing", "energy"],
    },
  ],
  firms: [{ id: 10, name: "Foundry", sector: "manufacturing", status: "listed", region_id: 1 }],
  core_agents: [{ id: 20, name: "Governor Vale", role: "central_banker", region_id: 1 }],
  flows: [
    { id: 30, source_region_id: 1, target_region_id: 2, kind: "trade", magnitude: 7, status: "completed" },
    { id: 31, source_region_id: 1, target_region_id: 2, kind: "trade", magnitude: 3, status: "in_transit" },
    { id: 32, source_region_id: 2, target_region_id: 1, kind: "migration", magnitude: 1, status: "completed" },
  ],
};

test("EconomicMap renders an accessible isometric scene and controls", async () => {
  const vite = await createServer({ appType: "custom", logLevel: "silent", server: { middlewareMode: true } });
  try {
    const { EconomicMap } = await vite.ssrLoadModule("/src/components/V2Observatory.jsx");
    const markup = renderToStaticMarkup(React.createElement(EconomicMap, { map: renderedMap }));

    assert.match(markup, /Regional economy command table/);
    assert.match(markup, /Perspective economic topology/);
    assert.match(markup, /aria-label="Toggle trade routes"[^>]*aria-pressed="true"/);
    assert.match(markup, /aria-label="Toggle migration routes"[^>]*aria-pressed="true"/);
    assert.match(markup, /aria-label="Toggle actor markers"[^>]*aria-pressed="true"/);
    assert.match(markup, /data-region-id="1"/);
    assert.match(markup, /data-route-id="trade:1:2"/);
    assert.match(markup, /tabindex="0"/);
    assert.match(markup, /Select a region/);
    assert.match(markup, /2 aggregated routes/);
  } finally {
    await vite.close();
  }
});

test("EconomicMap preserves the disabled regional-economy guidance", async () => {
  const vite = await createServer({ appType: "custom", logLevel: "silent", server: { middlewareMode: true } });
  try {
    const { EconomicMap } = await vite.ssrLoadModule("/src/components/V2Observatory.jsx");
    const markup = renderToStaticMarkup(React.createElement(EconomicMap, {
      map: { enabled: false, regions: [] },
    }));
    assert.match(markup, /Regional economy disabled for this run profile/);
  } finally {
    await vite.close();
  }
});
```

- [ ] **Step 2: Run the component tests to verify the old flat map fails them**

Run:

```bash
cd dashboard && node --test tests/living-economy-map.test.js
```

Expected: the three projection tests pass and the new scene test fails because `Regional economy command table` is absent.

- [ ] **Step 3: Create the focused React/SVG map component**

Create `dashboard/src/components/LivingEconomyMap.jsx`. Use the following state and rendering contract exactly:

```jsx
import { useEffect, useId, useMemo, useState } from "react";

import { number, shortKind } from "../api";
import { Empty, Panel } from "./ui";
import { normalizeMapData } from "./livingEconomyMapModel";

const REGION_COLORS = ["#79e6bd", "#f7d783", "#ff9788"];
const ROUTE_COLORS = { trade: "#79e6bd", migration: "#f7d783" };

const project = region => ({
  x: 115 + region.x * 770,
  y: 105 + region.y * 345,
});

function routePath(route, byId) {
  const source = project(byId.get(route.source_region_id));
  const target = project(byId.get(route.target_region_id));
  const dx = target.x - source.x;
  const dy = target.y - source.y;
  const length = Math.hypot(dx, dy) || 1;
  const bend = route.kind === "trade" ? -1 : 1;
  const offsetX = (-dy / length) * 38 * bend;
  const offsetY = (dx / length) * 38 * bend - Math.min(105, 44 + length * 0.08);
  const controlX = (source.x + target.x) / 2 + offsetX;
  const controlY = (source.y + target.y) / 2 + offsetY;
  return `M ${source.x} ${source.y} Q ${controlX} ${controlY} ${target.x} ${target.y}`;
}

function activationKey(event, action) {
  if (event.key !== "Enter" && event.key !== " ") return;
  event.preventDefault();
  action();
}

function LayerToggle({ active, label, onClick }) {
  return <button type="button" aria-label={`Toggle ${label.toLowerCase()}`} aria-pressed={active}
    onClick={onClick} className={`economy-map-toggle ${active ? "is-active" : ""}`}>
    <span aria-hidden="true" className="economy-map-toggle-dot" />{label}
  </button>;
}

function FlowRoute({ route, byId, selectedRegionId, markerId, onActive, onInactive }) {
  const source = byId.get(route.source_region_id);
  const target = byId.get(route.target_region_id);
  const connected = selectedRegionId === null
    || route.source_region_id === selectedRegionId
    || route.target_region_id === selectedRegionId;
  const statusText = Object.entries(route.statuses)
    .map(([status, count]) => `${count} ${shortKind(status)}`)
    .join(", ");
  const label = `${shortKind(route.kind)} from ${source.name} to ${target.name}; ${number(route.magnitude, 0)} magnitude across ${route.count} records; ${statusText}`;
  const activate = () => onActive({ title: `${source.name} → ${target.name}`, body: label });
  const visibleWidth = Math.min(8, 1.6 + Math.sqrt(route.magnitude) * 0.7);

  return <g role="button" tabIndex="0" data-route-id={route.id} aria-label={label}
    className={`economy-map-route ${connected ? "" : "is-muted"}`}
    onMouseEnter={activate} onMouseLeave={onInactive} onFocus={activate} onBlur={onInactive}
    onClick={event => { event.stopPropagation(); activate(); }}
    onKeyDown={event => activationKey(event, activate)}>
    <path d={routePath(route, byId)} fill="none" stroke="transparent" strokeWidth="18" />
    <path d={routePath(route, byId)} fill="none" stroke={ROUTE_COLORS[route.kind]}
      strokeWidth={visibleWidth} strokeLinecap="round" markerEnd={`url(#${markerId})`}
      className={`economy-map-route-line is-${route.kind}`} />
  </g>;
}

function RegionPlatform({ region, index, selected, actorsVisible, onSelect, onActive, onInactive }) {
  const point = project(region);
  const color = REGION_COLORS[index % REGION_COLORS.length];
  const radius = Math.min(82, 46 + Math.sqrt(region.population) * 1.25);
  const depth = 15 + Math.min(25, region.firmItems.length * 3);
  const label = `${region.name}; ${number(region.population, 0)} agents; ${region.currency_code}; ${region.firmItems.length} active firms; ${region.coreAgentItems.length} strategic agents`;
  const choose = () => onSelect(region.id);
  const activate = () => onActive({ title: region.name, body: label });

  return <g transform={`translate(${point.x} ${point.y})`} role="button" tabIndex="0"
    data-region-id={region.id} aria-label={label} aria-pressed={selected}
    className={`economy-map-region ${selected ? "is-selected" : ""}`}
    onClick={event => { event.stopPropagation(); choose(); }}
    onKeyDown={event => activationKey(event, choose)}
    onMouseEnter={activate} onMouseLeave={onInactive} onFocus={activate} onBlur={onInactive}>
    <ellipse cy={depth + 13} rx={radius + 14} ry={(radius + 14) * 0.42} fill="#020706" opacity=".62" />
    {[depth, depth * 0.72, depth * 0.44].map((offset, layer) => <ellipse key={layer}
      cy={offset} rx={radius} ry={radius * 0.42} fill={color} opacity={0.08 + layer * 0.035} />)}
    <ellipse rx={radius} ry={radius * 0.42} fill={color} fillOpacity=".15" stroke={color} strokeWidth={selected ? 3 : 1.8} />
    <ellipse className="economy-map-focus-ring" rx={radius + 8} ry={radius * 0.42 + 8}
      fill="none" stroke="#ffffff" strokeWidth="2" strokeOpacity="0" />
    <ellipse rx={Math.max(18, radius * Math.min(1, region.population / Math.max(1, region.population_target)))}
      ry={Math.max(8, radius * 0.42 * Math.min(1, region.population / Math.max(1, region.population_target)))}
      fill={color} fillOpacity=".11" />
    {actorsVisible && region.firmItems.slice(0, 8).map((firm, firmIndex) => {
      const x = (firmIndex - (Math.min(8, region.firmItems.length) - 1) / 2) * 11;
      const height = 14 + (firmIndex % 3) * 6;
      return <g key={firm.id} transform={`translate(${x} -12)`}>
        <line y1="0" y2={-height} stroke={color} strokeWidth="4" strokeLinecap="round" />
        <circle cy={-height} r="3" fill="#e7f1ed"><title>{firm.name} · {firm.sector}</title></circle>
      </g>;
    })}
    {actorsVisible && region.coreAgentItems.slice(0, 18).map((agent, agentIndex) => {
      const angle = (Math.PI * 2 * agentIndex) / Math.max(1, Math.min(18, region.coreAgentItems.length));
      return <circle key={agent.id} cx={Math.cos(angle) * radius * 0.73}
        cy={Math.sin(angle) * radius * 0.28} r="2.7" fill="#ffffff" fillOpacity=".78">
        <title>{agent.name} · {agent.role || agent.occupation}</title>
      </circle>;
    })}
    <text textAnchor="middle" y={depth + 36} fill="#e7f1ed" fontSize="16" fontWeight="750">{region.name}</text>
    <text textAnchor="middle" y={depth + 54} fill="#9fb8af" fontSize="11">
      {number(region.population, 0)} agents · {region.currency_code}
    </text>
  </g>;
}

export function EconomyScene({ scene, layers, selectedRegionId, onSelectRegion, onClearSelection, onActive, onInactive }) {
  const prefix = useId().replaceAll(":", "");
  const byId = new Map(scene.regions.map(region => [region.id, region]));
  return <svg viewBox="0 0 1000 560" role="img" aria-labelledby={`${prefix}-title ${prefix}-description`}
    className="economy-map-svg" onClick={onClearSelection}>
    <title id={`${prefix}-title`}>Regional economy command table</title>
    <desc id={`${prefix}-description`}>Perspective economic topology with selectable regions and aggregated trade and migration routes.</desc>
    <defs>
      <linearGradient id={`${prefix}-floor`} x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stopColor="#10201c" /><stop offset="1" stopColor="#050a09" />
      </linearGradient>
      <pattern id={`${prefix}-grid`} width="42" height="26" patternUnits="userSpaceOnUse" patternTransform="skewX(-18)">
        <path d="M 42 0 L 0 0 0 26" fill="none" stroke="#79e6bd" strokeOpacity=".1" strokeWidth="1" />
      </pattern>
      {Object.entries(ROUTE_COLORS).map(([kind, color]) => <marker key={kind} id={`${prefix}-${kind}-arrow`}
        markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">
        <path d="M0,0 L0,6 L7,3 z" fill={color} />
      </marker>)}
      <radialGradient id={`${prefix}-vignette`}>
        <stop offset="45%" stopColor="#07110f" stopOpacity="0" />
        <stop offset="100%" stopColor="#020706" stopOpacity=".72" />
      </radialGradient>
    </defs>
    <rect width="1000" height="560" rx="22" fill="#040b09" />
    <polygon points="68,82 932,82 984,516 16,516" fill={`url(#${prefix}-floor)`} stroke="#79e6bd" strokeOpacity=".18" />
    <polygon points="68,82 932,82 984,516 16,516" fill={`url(#${prefix}-grid)`} />
    {scene.routes.filter(route => layers[route.kind]).map(route => <FlowRoute key={route.id}
      route={route} byId={byId} selectedRegionId={selectedRegionId}
      markerId={`${prefix}-${route.kind}-arrow`} onActive={onActive} onInactive={onInactive} />)}
    {scene.regions.map((region, index) => <RegionPlatform key={region.id} region={region} index={index}
      selected={selectedRegionId === region.id} actorsVisible={layers.actors}
      onSelect={onSelectRegion} onActive={onActive} onInactive={onInactive} />)}
    <rect width="1000" height="560" rx="22" fill={`url(#${prefix}-vignette)`} pointerEvents="none" />
  </svg>;
}

function Metric({ label, value, tone = "text-slate-200" }) {
  return <div className="rounded-lg border border-mint-300/10 bg-ink-950/45 p-2">
    <dt className="text-[9px] uppercase tracking-widest text-slate-600">{label}</dt>
    <dd className={`tabular mt-1 text-sm font-semibold ${tone}`}>{value}</dd>
  </div>;
}

export function RegionInspector({ region, scene }) {
  if (!region) return <aside className="economy-map-inspector" aria-live="polite">
    <div className="eyebrow">Region inspector</div>
    <h3 className="mt-2 text-base font-semibold text-slate-200">Select a region</h3>
    <p className="mt-2 text-xs leading-relaxed text-slate-500">Choose a platform to isolate connected routes and inspect its measured economy.</p>
    <dl className="mt-4 grid grid-cols-2 gap-2">
      <Metric label="Regions" value={scene.regions.length} />
      <Metric label="Routes" value={scene.routes.length} />
      <Metric label="Firms" value={scene.firms.length} />
      <Metric label="Actors" value={scene.coreAgents.length} />
    </dl>
  </aside>;

  return <aside className="economy-map-inspector" aria-live="polite">
    <div className="eyebrow">Selected region</div>
    <h3 className="mt-2 text-base font-semibold text-slate-100">{region.name}</h3>
    <p className="mt-1 text-[11px] text-mint-300">{region.currency_code} · {region.region_key}</p>
    <div className="mt-3 flex flex-wrap gap-1">
      {region.specialization.map(item => <span key={item} className="rounded-full border border-mint-300/15 px-2 py-1 text-[10px] text-slate-400">{shortKind(item)}</span>)}
    </div>
    <dl className="mt-4 grid grid-cols-2 gap-2">
      <Metric label="Population" value={number(region.population, 0)} />
      <Metric label="Target" value={number(region.population_target, 0)} />
      <Metric label="Firms" value={region.firmItems.length} tone="text-mint-300" />
      <Metric label="Core actors" value={region.coreAgentItems.length} />
      <Metric label="Trade in" value={number(region.flowTotals.trade.inbound, 0)} tone="text-mint-300" />
      <Metric label="Trade out" value={number(region.flowTotals.trade.outbound, 0)} tone="text-mint-300" />
      <Metric label="Migration in" value={number(region.flowTotals.migration.inbound, 0)} tone="text-gold-300" />
      <Metric label="Migration out" value={number(region.flowTotals.migration.outbound, 0)} tone="text-gold-300" />
    </dl>
    <p className="mt-3 text-[10px] leading-relaxed text-slate-600">Press Escape or select the platform again to clear focus.</p>
  </aside>;
}

export function EconomicMap({ map }) {
  const scene = useMemo(() => normalizeMapData(map), [map]);
  const [selectedRegionId, setSelectedRegionId] = useState(null);
  const [activeItem, setActiveItem] = useState(null);
  const [layers, setLayers] = useState({ trade: true, migration: true, actors: true });
  const selectedRegion = scene.regions.find(region => region.id === selectedRegionId) || null;

  useEffect(() => {
    if (selectedRegionId !== null && !scene.regions.some(region => region.id === selectedRegionId)) {
      setSelectedRegionId(null);
    }
  }, [scene.regions, selectedRegionId]);

  const toggleLayer = layer => setLayers(current => ({ ...current, [layer]: !current[layer] }));
  const toggleRegion = regionId => setSelectedRegionId(current => current === regionId ? null : regionId);
  const clearSelection = () => setSelectedRegionId(null);

  return <Panel className="col-span-full xl:col-span-8" title="Living economy map" eyebrow="TRADE · CAPITAL · MIGRATION">
    {!scene.regions.length ? <Empty text={map?.enabled === false
      ? "Regional economy disabled for this run profile. Use the institutional Observatory rehearsal to activate it."
      : "No regional economy data has been recorded yet."} /> :
      <div className="p-3" onKeyDown={event => { if (event.key === "Escape") clearSelection(); }}>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div>
            <div className="text-xs font-semibold text-slate-300">Perspective economic topology</div>
            <div className="mt-0.5 text-[10px] text-slate-600">{scene.routes.length} aggregated routes · measured run data</div>
          </div>
          <div className="flex flex-wrap gap-1.5" aria-label="Map layers">
            <LayerToggle active={layers.trade} label="Trade routes" onClick={() => toggleLayer("trade")} />
            <LayerToggle active={layers.migration} label="Migration routes" onClick={() => toggleLayer("migration")} />
            <LayerToggle active={layers.actors} label="Actor markers" onClick={() => toggleLayer("actors")} />
          </div>
        </div>
        <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_250px]">
          <div className="economy-map-stage">
            <EconomyScene scene={scene} layers={layers} selectedRegionId={selectedRegionId}
              onSelectRegion={toggleRegion} onClearSelection={clearSelection}
              onActive={setActiveItem} onInactive={() => setActiveItem(null)} />
            {activeItem && <div className="economy-map-tooltip" role="status">
              <strong>{activeItem.title}</strong><span>{activeItem.body}</span>
            </div>}
          </div>
          <RegionInspector region={selectedRegion} scene={scene} />
        </div>
        <div className="mt-3 flex flex-wrap gap-4 text-[11px] text-slate-500">
          <span><b className="text-mint-300">━</b> trade</span>
          <span><b className="text-gold-300">┈</b> migration</span>
          <span><b className="text-white">●</b> core strategic agent</span>
          <span>{scene.firms.length} active firms plotted</span>
        </div>
      </div>}
  </Panel>;
}
```

- [ ] **Step 4: Preserve the existing public export while removing the flat implementation**

In `dashboard/src/components/V2Observatory.jsx`, replace lines 1-34 with:

```jsx
import { number, shortKind } from "../api";
import { Empty, Panel } from "./ui";

export { EconomicMap } from "./LivingEconomyMap";
```

Do not modify `InstitutionalPulse`, `LegalPoliticalPanels`, or the existing changes below line 34.

In `dashboard/src/components/ui.jsx`, replace `Empty` with this backward-compatible implementation so both its existing `text` call sites and child content render truthful copy:

```jsx
export function Empty({ children, text = "Nothing recorded yet." }) {
  return <div className="p-5 text-sm leading-relaxed text-slate-500">{children ?? text}</div>;
}
```

- [ ] **Step 5: Run the focused tests**

Run:

```bash
cd dashboard && node --test tests/living-economy-map.test.js
```

Expected: 5 tests pass, 0 fail.

- [ ] **Step 6: Run the complete dashboard test suite**

Run:

```bash
cd dashboard && npm test
```

Expected: all dashboard tests pass, including the pre-existing empty-state and institutional-panel assertions in `tests/ui.test.js`.

- [ ] **Step 7: Commit the scene and integration**

Stage the two new feature files normally. Because `V2Observatory.jsx` already contains unrelated working-tree edits, stage only the import/export replacement hunk and verify the cached diff before committing:

```bash
git add -- dashboard/src/components/LivingEconomyMap.jsx dashboard/src/components/ui.jsx dashboard/tests/living-economy-map.test.js
git add -p -- dashboard/src/components/V2Observatory.jsx
git diff --cached --check
git diff --cached -- dashboard/src/components/V2Observatory.jsx
git -c user.name='Oneworld' -c user.email='168804661+alinojoumi8@users.noreply.github.com' commit -m "feat(observatory): add interactive isometric economy map"
```

Expected: the cached `V2Observatory.jsx` diff contains only removal of the old map and addition of the re-export; the commit contains no institutional-panel changes.

---

### Task 3: Add depth, focus, flow motion, and reduced-motion styling

**Files:**
- Modify: `dashboard/src/index.css:154-156`
- Modify: `dashboard/tests/living-economy-map.test.js`

**Interfaces:**
- Consumes: class names emitted by `LivingEconomyMap.jsx`: `economy-map-stage`, `economy-map-svg`, `economy-map-toggle`, `economy-map-route`, `economy-map-route-line`, `economy-map-region`, `economy-map-focus-ring`, `economy-map-tooltip`, and `economy-map-inspector`.
- Produces: visible 3D depth, interactive focus states, animated direction cues, and a motion-free equivalent under the existing reduced-motion media query.

- [ ] **Step 1: Add a failing stylesheet contract test**

Append to `dashboard/tests/living-economy-map.test.js`:

```js
import { readFile } from "node:fs/promises";

test("economy map styles include motion and accessible reduced-motion behavior", async () => {
  const css = await readFile(new URL("../src/index.css", import.meta.url), "utf8");
  assert.match(css, /@keyframes economy-map-route-flow/);
  assert.match(css, /\.economy-map-region:focus-visible \.economy-map-focus-ring/);
  assert.match(css, /\.economy-map-route-line\.is-migration/);
  assert.match(css, /prefers-reduced-motion: reduce[\s\S]*\.economy-map-route-line/);
});
```

- [ ] **Step 2: Run the focused tests to verify the stylesheet contract fails**

Run:

```bash
cd dashboard && node --test tests/living-economy-map.test.js
```

Expected: 5 tests pass and the stylesheet contract fails because `economy-map-route-flow` is absent.

- [ ] **Step 3: Add the map stylesheet**

Insert this block in `dashboard/src/index.css` immediately before the existing `@media (prefers-reduced-motion: reduce)` rule:

```css
.economy-map-stage {
  position: relative;
  min-width: 0;
  overflow: hidden;
  border: 1px solid rgba(121, 230, 189, .12);
  border-radius: .9rem;
  background: #040b09;
  box-shadow: inset 0 1px rgba(255, 255, 255, .025), inset 0 -50px 90px rgba(0, 0, 0, .28);
}
.economy-map-svg { display: block; height: auto; width: 100%; }
.economy-map-toggle {
  display: inline-flex;
  min-height: 1.9rem;
  align-items: center;
  gap: .38rem;
  border: 1px solid rgba(121, 230, 189, .13);
  border-radius: 999px;
  background: rgba(5, 10, 9, .65);
  color: #78938a;
  padding: .3rem .58rem;
  font-size: .64rem;
  font-weight: 700;
  letter-spacing: .04em;
  transition: border-color 160ms ease, background 160ms ease, color 160ms ease, transform 160ms ease;
}
.economy-map-toggle:hover { transform: translateY(-1px); border-color: rgba(121, 230, 189, .4); }
.economy-map-toggle.is-active { border-color: rgba(121, 230, 189, .42); background: rgba(121, 230, 189, .1); color: #d8e8e2; }
.economy-map-toggle-dot { height: .38rem; width: .38rem; border-radius: 999px; background: currentColor; box-shadow: 0 0 10px currentColor; }
.economy-map-route { cursor: pointer; opacity: .88; transition: opacity 180ms ease; }
.economy-map-route.is-muted { opacity: .1; }
.economy-map-route-line { animation: economy-map-route-flow 2.8s linear infinite; filter: drop-shadow(0 0 5px currentColor); transition: stroke-width 160ms ease, opacity 160ms ease; }
.economy-map-route-line.is-trade { stroke-dasharray: 12 8; }
.economy-map-route-line.is-migration { stroke-dasharray: 3 10; animation-direction: reverse; }
.economy-map-route:hover .economy-map-route-line,
.economy-map-route:focus-visible .economy-map-route-line { stroke-width: 8; opacity: 1; }
.economy-map-region { cursor: pointer; opacity: .88; transition: opacity 180ms ease, filter 180ms ease; }
.economy-map-region:hover,
.economy-map-region.is-selected { opacity: 1; filter: brightness(1.18) drop-shadow(0 10px 18px rgba(0, 0, 0, .4)); }
.economy-map-region:focus-visible { outline: none; }
.economy-map-region:focus-visible .economy-map-focus-ring { stroke-opacity: .9; }
.economy-map-tooltip {
  pointer-events: none;
  position: absolute;
  left: .75rem;
  top: .75rem;
  max-width: min(26rem, calc(100% - 1.5rem));
  border: 1px solid rgba(121, 230, 189, .2);
  border-radius: .7rem;
  background: rgba(5, 10, 9, .88);
  padding: .55rem .7rem;
  box-shadow: 0 12px 40px rgba(0, 0, 0, .38);
  backdrop-filter: blur(10px);
}
.economy-map-tooltip strong { display: block; color: #d8e8e2; font-size: .7rem; }
.economy-map-tooltip span { display: block; margin-top: .2rem; color: #78938a; font-size: .62rem; line-height: 1.45; }
.economy-map-inspector {
  min-height: 12rem;
  border: 1px solid rgba(121, 230, 189, .1);
  border-radius: .9rem;
  background: linear-gradient(160deg, rgba(12, 28, 24, .82), rgba(5, 10, 9, .68));
  padding: .9rem;
}
@keyframes economy-map-route-flow { to { stroke-dashoffset: -40; } }

@media (max-width: 640px) {
  .economy-map-tooltip { position: static; max-width: none; border-width: 1px 0 0; border-radius: 0; box-shadow: none; }
}
```

Extend the existing reduced-motion block so it reads:

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { scroll-behavior: auto !important; transition: none !important; animation: none !important; }
  .economy-map-route-line { animation: none !important; }
}
```

- [ ] **Step 4: Run focused and full dashboard tests**

Run:

```bash
cd dashboard && node --test tests/living-economy-map.test.js && npm test
```

Expected: all focused and dashboard tests pass with 0 failures.

- [ ] **Step 5: Build the production dashboard**

Run:

```bash
cd dashboard && npm run build
```

Expected: Vite exits 0, writes `server/static/index.html`, one CSS asset, and JavaScript assets without unresolved imports or bundle errors.

- [ ] **Step 6: Commit the stylesheet and regenerated bundle without swallowing unrelated artifacts**

Run:

```bash
git add -- dashboard/src/index.css dashboard/tests/living-economy-map.test.js server/static/index.html server/static/assets
git diff --cached --check
git diff --cached --stat
git -c user.name='Oneworld' -c user.email='168804661+alinojoumi8@users.noreply.github.com' commit -m "style(observatory): polish economy map depth and motion"
```

Expected: the commit includes only the stylesheet contract, map styles, and Vite's regenerated static bundle. Review the cached asset deletions and additions as one coherent hash replacement before committing.

---

### Task 4: Define the shared observatory interaction model

**Files:**
- Create: `dashboard/src/observatoryInteraction.js`
- Create: `dashboard/tests/observatory-interaction.test.js`

**Interfaces:**
- Consumes: current Observatory payloads plus map regions shaped as `{ id, region_key, name }`.
- Produces: `normalizeRegion`, `nextRegionFocus`, `firmIdsForRegion`, `eventMatchesRegion`, `makeInspection`, `resolveInspection`, and `inspectionPresentation`.
- An inspection reference is `{ kind, id, collection, title, fallbackSnapshot }`; `collection` is required only for startup records and provider-cost rows.
- `eventMatchesRegion` examines only the event's top-level `payload` object and only the six approved region keys.

- [ ] **Step 1: Write the failing pure-model tests**

Create `dashboard/tests/observatory-interaction.test.js` with:

```js
import assert from "node:assert/strict";
import test from "node:test";

import {
  eventMatchesRegion,
  firmIdsForRegion,
  inspectionPresentation,
  makeInspection,
  nextRegionFocus,
  normalizeRegion,
  resolveInspection,
} from "../src/observatoryInteraction.js";

test("region focus normalizes valid regions and toggles by numeric id", () => {
  const northstar = { id: "1", region_key: "northstar", name: "Northstar Federation" };
  assert.deepEqual(normalizeRegion(northstar), {
    regionId: 1, regionKey: "northstar", regionName: "Northstar Federation",
  });
  assert.equal(normalizeRegion({ id: "bad" }), null);
  const selected = nextRegionFocus(null, northstar);
  assert.equal(selected.regionId, 1);
  assert.equal(nextRegionFocus(selected, northstar), null);
});

test("firm membership uses only active firm ids explicitly mapped to the region", () => {
  assert.deepEqual([...firmIdsForRegion({ firms: [
    { id: 8, region_id: 1 }, { id: "9", region_id: "1" },
    { id: 10, region_id: 2 }, { id: "bad", region_id: 1 },
  ] }, 1)], [8, 9]);
  assert.deepEqual([...firmIdsForRegion({ firms: null }, 1)], []);
});

test("event matching accepts only explicit top-level region keys", () => {
  assert.equal(eventMatchesRegion({ payload: { origin_region_id: "2" } }, 2), true);
  assert.equal(eventMatchesRegion({ payload: { destination_region_id: 2 } }, 2), true);
  assert.equal(eventMatchesRegion({ payload: { agent_id: 2 } }, 2), false);
  assert.equal(eventMatchesRegion({ payload: { nested: { region_id: 2 } } }, 2), false);
  assert.equal(eventMatchesRegion({ payload: null }, 2), false);
});

test("inspection resolves the newest record and retains a last-observed fallback", () => {
  const reference = makeInspection(
    { kind: "firm", id: 7, title: "Anchor Works" },
    { id: 7, name: "Anchor Works", cash_cents: 10 },
  );
  const current = resolveInspection(reference, {
    firms: [{ id: 7, name: "Anchor Works", cash_cents: 25 }],
  });
  assert.equal(current.record.cash_cents, 25);
  assert.equal(current.lastObserved, false);

  const missing = resolveInspection(reference, { firms: [] });
  assert.equal(missing.record.cash_cents, 10);
  assert.equal(missing.lastObserved, true);
});

test("inspection presentation is safe for unsupported and malformed snapshots", () => {
  const known = inspectionPresentation(makeInspection(
    { kind: "news", id: 3 },
    { id: 3, headline: "A verified headline", body: "Full story", tick: 92 },
  ), { news: [] });
  assert.equal(known.title, "A verified headline");
  assert.equal(known.narrative, "Full story");
  assert.equal(known.lastObserved, true);
  assert.ok(known.fields.some(field => field.label === "Day" && field.value === "92"));

  const unknown = inspectionPresentation(makeInspection(
    { kind: "mystery", id: null }, { circular: null },
  ), {});
  assert.equal(unknown.title, "Unsupported inspection item");
  assert.deepEqual(unknown.fields, []);
});
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run:

```bash
cd dashboard && node --test tests/observatory-interaction.test.js
```

Expected: FAIL with `ERR_MODULE_NOT_FOUND` for `src/observatoryInteraction.js`.

- [ ] **Step 3: Implement the pure interaction model**

Create `dashboard/src/observatoryInteraction.js` with:

```js
const arrays = value => Array.isArray(value) ? value : [];
const numericId = value => Number.isFinite(Number(value)) ? Number(value) : null;
const sameId = (left, right) => numericId(left) !== null && numericId(left) === numericId(right);

export const REGION_EVENT_KEYS = Object.freeze([
  "region_id", "origin_region_id", "destination_region_id",
  "source_region_id", "target_region_id", "issuer_region_id",
]);

export function normalizeRegion(region) {
  const regionId = numericId(region?.id ?? region?.regionId);
  if (regionId === null) return null;
  return {
    regionId,
    regionKey: String(region?.region_key ?? region?.regionKey ?? ""),
    regionName: String(region?.name ?? region?.regionName ?? `Region ${regionId}`),
  };
}

export function nextRegionFocus(current, region) {
  const normalized = normalizeRegion(region);
  if (!normalized) return current || null;
  return current?.regionId === normalized.regionId ? null : normalized;
}

export function firmIdsForRegion(map, regionId) {
  const selected = numericId(regionId);
  const ids = arrays(map?.firms)
    .filter(firm => selected !== null && sameId(firm?.region_id, selected))
    .map(firm => numericId(firm?.id))
    .filter(id => id !== null)
    .sort((left, right) => left - right);
  return new Set(ids);
}

export function eventMatchesRegion(event, regionId) {
  const selected = numericId(regionId);
  const payload = event?.payload;
  if (selected === null || !payload || typeof payload !== "object" || Array.isArray(payload)) return false;
  return REGION_EVENT_KEYS.some(key => sameId(payload[key], selected));
}

export function makeInspection(reference, fallbackSnapshot) {
  return {
    kind: String(reference?.kind || "unsupported"),
    id: reference?.id ?? null,
    collection: reference?.collection ? String(reference.collection) : null,
    title: reference?.title ? String(reference.title) : null,
    fallbackSnapshot: fallbackSnapshot && typeof fallbackSnapshot === "object"
      ? fallbackSnapshot : {},
  };
}

function recordsFor(reference, data) {
  const v2 = data?.v2 || {};
  const direct = {
    bank: data?.banks,
    firm: data?.firms,
    news: data?.news,
    event: data?.events,
    legal_matter: v2?.legal?.items,
    legal_obligation: v2?.legal?.obligations,
    bill: v2?.politics?.bills,
    acceptance_check: data?.acceptance?.checks,
  };
  if (reference.kind === "provider_cost") {
    return arrays(data?.cost?.[reference.collection]).map((record, index) => ({
      ...record,
      id: reference.collection === "by_model" ? record.model
        : reference.collection === "by_purpose" ? record.purpose
        : record.agent_id ?? `shared-${index}`,
    }));
  }
  if (reference.kind === "startup_record") return arrays(v2?.startups?.[reference.collection]);
  if (reference.kind === "institution") {
    const record = data?.institutions?.[reference.id];
    return record && typeof record === "object" ? [{ ...record, id: reference.id }] : [];
  }
  if (reference.kind === "macro_metric") {
    const series = arrays(data?.metrics?.[reference.id]);
    return series.length ? [{ id: reference.id, series, latest: series.at(-1)?.value }] : [];
  }
  if (reference.kind === "shock_trace") {
    const evidence = arrays(data?.acceptance?.checks)
      .find(check => check.id === "shock_traces")?.evidence;
    const trace = evidence?.[reference.id];
    return trace && typeof trace === "object" ? [{ ...trace, id: reference.id }] : [];
  }
  if (reference.kind === "startup_summary") return [];
  return arrays(direct[reference.kind]);
}

export function resolveInspection(reference, data) {
  if (!reference) return null;
  if (reference.id === null) {
    return { record: reference.fallbackSnapshot || {}, lastObserved: false };
  }
  const current = recordsFor(reference, data).find(record => sameId(record?.id, reference.id)
    || String(record?.id) === String(reference.id));
  return {
    record: current ? { ...(reference.fallbackSnapshot || {}), ...current }
      : reference.fallbackSnapshot || {},
    lastObserved: !current,
  };
}

const LABELS = {
  tick: "Day", status: "Status", kind: "Kind", phase: "Phase", importance: "Importance",
  outlet: "Outlet", outlet_name: "Outlet", tone: "Tone", truthful: "Truthful", sector: "Sector",
  slant_tags: "Slant tags", source_event_ids: "Source events", ruleset: "Ruleset",
  employees: "Employees", deposits_cents: "Deposits", reserves_cents: "Reserves",
  reserve_ratio: "Reserve ratio", loans: "Loans", loans_cents: "Loans", avg_trust: "Average trust",
  cash_cents: "Cash", price_cents: "Goods price", last_stock_price: "Stock price",
  inventory: "Inventory", inventory_qty: "Inventory", production: "Production", output: "Production",
  payroll_cents: "Payroll", revenue_cents: "Revenue",
  calls: "Calls", in_tokens: "Input tokens", out_tokens: "Output tokens", cost_usd: "Spend",
  latest: "Current value", delta: "Latest change", series: "Recent points", count: "Count",
};
const FIELD_KEYS = Object.keys(LABELS);

function scalar(value) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (Array.isArray(value)) return value.map(item => typeof item === "object"
    ? JSON.stringify(item) : String(item)).join(", ");
  if (typeof value === "object") return null;
  return String(value);
}

export function inspectionPresentation(reference, data) {
  const supported = new Set([
    "bank", "firm", "institution", "news", "macro_metric", "legal_matter",
    "legal_obligation", "bill", "startup_record", "startup_summary",
    "acceptance_check", "shock_trace", "provider_cost", "event",
  ]);
  const resolved = resolveInspection(reference, data) || { record: {}, lastObserved: false };
  const record = resolved.record && typeof resolved.record === "object" ? resolved.record : {};
  if (!supported.has(reference?.kind)) {
    return { title: "Unsupported inspection item", subtitle: "", narrative: "", fields: [], raw: record, lastObserved: resolved.lastObserved };
  }
  const title = String(reference?.title || record.headline || record.title || record.name
    || record.label || `${reference.kind.replaceAll("_", " ")} ${reference.id ?? "summary"}`);
  const subtitle = String(record.subtitle || record.model || record.purpose || record.agent_name || "");
  const narrative = String(record.body || record.reasoning || record.description || record.help || "");
  const fields = FIELD_KEYS
    .filter(key => Object.hasOwn(record, key))
    .map(key => ({ label: LABELS[key], value: scalar(record[key]) }))
    .filter(field => field.value !== null);
  return { title, subtitle, narrative, fields, raw: record, lastObserved: resolved.lastObserved };
}
```

- [ ] **Step 4: Run the pure interaction tests**

Run:

```bash
cd dashboard && node --test tests/observatory-interaction.test.js
```

Expected: 5 tests pass, 0 fail.

- [ ] **Step 5: Commit the interaction model**

Run:

```bash
git add -- dashboard/src/observatoryInteraction.js dashboard/tests/observatory-interaction.test.js
git diff --cached --check
git -c user.name='Oneworld' -c user.email='168804661+alinojoumi8@users.noreply.github.com' commit -m "feat(observatory): add shared interaction model"
```

Expected: one commit containing only the pure model and its focused tests.

---

### Task 5: Install shared region focus and inspector UI

**Files:**
- Create: `dashboard/src/components/ObservatoryInteraction.jsx`
- Modify: `dashboard/src/components/Observatory.jsx`
- Modify: `dashboard/src/components/LivingEconomyMap.jsx`
- Modify: `dashboard/tests/observatory-interaction.test.js`
- Modify: `dashboard/tests/living-economy-map.test.js`

**Interfaces:**
- Consumes: Task 4's `nextRegionFocus`, `normalizeRegion`, and `inspectionPresentation`.
- Produces: `ObservatoryInteractionProvider`, `useObservatoryInteraction`, `inspectionTriggerProps`, `RegionFocusBar`, and `InspectorDrawer`.
- Context value: `{ regionFocus, inspection, selectRegion, clearRegion, inspect, closeInspection, announcement }`.
- `inspect(reference, fallbackSnapshot)` captures `document.activeElement` for focus restoration; it performs no fetch or mutation.

- [ ] **Step 1: Add failing server-rendered shell tests**

Append to `dashboard/tests/observatory-interaction.test.js`:

```js
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";

test("focus bar names exactly the three region-filtered panels", async () => {
  const vite = await createServer({ appType: "custom", logLevel: "silent", server: { middlewareMode: true } });
  try {
    const { RegionFocusBar } = await vite.ssrLoadModule("/src/components/ObservatoryInteraction.jsx");
    const markup = renderToStaticMarkup(React.createElement(RegionFocusBar, {
      regionFocus: { regionId: 1, regionKey: "northstar", regionName: "Northstar Federation" },
      onClear: () => {},
    }));
    assert.match(markup, /Northstar Federation/);
    assert.match(markup, /Firms, agents, and region-tagged events/);
    assert.match(markup, /aria-label="Clear Northstar Federation region filter"/);
    assert.doesNotMatch(markup, /banks are filtered/i);
  } finally { await vite.close(); }
});

test("drawer is modeless, labelled, and exposes last-observed state", async () => {
  const vite = await createServer({ appType: "custom", logLevel: "silent", server: { middlewareMode: true } });
  try {
    const { InspectorDrawer } = await vite.ssrLoadModule("/src/components/ObservatoryInteraction.jsx");
    const snapshot = { id: 4, name: "Northstar Reserve", status: "open", deposits_cents: 500 };
    snapshot.self = snapshot;
    const inspection = makeInspection({ kind: "bank", id: 4 }, snapshot);
    const markup = renderToStaticMarkup(React.createElement(InspectorDrawer, {
      inspection, data: { banks: [] }, onClose: () => {}, headingRef: { current: null },
    }));
    assert.match(markup, /aria-label="Observatory inspector"/);
    assert.doesNotMatch(markup, /aria-modal="true"/);
    assert.match(markup, /Northstar Reserve/);
    assert.match(markup, /Last observed/);
    assert.match(markup, /Close inspector/);
    assert.match(markup, /Unable to serialize this snapshot/);
  } finally { await vite.close(); }
});
```

- [ ] **Step 2: Run the shell tests to verify they fail**

Run:

```bash
cd dashboard && node --test tests/observatory-interaction.test.js
```

Expected: the pure tests pass and both component tests fail with `ERR_MODULE_NOT_FOUND` for `ObservatoryInteraction.jsx`.

- [ ] **Step 3: Create the provider, focus bar, and modeless drawer**

Create `dashboard/src/components/ObservatoryInteraction.jsx` with:

```jsx
import { createContext, useContext, useEffect, useMemo, useRef, useState } from "react";
import { inspectionPresentation, makeInspection, nextRegionFocus, normalizeRegion } from "../observatoryInteraction";

const NOOP = () => {};
const FALLBACK = {
  regionFocus: null, inspection: null, announcement: "",
  selectRegion: NOOP, clearRegion: NOOP, inspect: NOOP, closeInspection: NOOP,
};
const ObservatoryInteractionContext = createContext(FALLBACK);

export function useObservatoryInteraction() {
  return useContext(ObservatoryInteractionContext);
}

export function inspectionTriggerProps(inspect, reference, snapshot, ariaLabel) {
  return {
    role: "button",
    tabIndex: 0,
    "aria-label": ariaLabel,
    onClick: () => inspect(reference, snapshot),
    onKeyDown: event => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      inspect(reference, snapshot);
    },
  };
}

export function RegionFocusBar({ regionFocus, onClear }) {
  if (!regionFocus) return null;
  return <aside className="observatory-focus-bar" aria-label="Active region filter"
    onKeyDown={event => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      onClear();
    }}>
    <div>
      <div className="eyebrow">Regional focus</div>
      <strong>{regionFocus.regionName}</strong>
      <p>Firms, agents, and region-tagged events are filtered. Other panels remain global.</p>
    </div>
    <button type="button" className="button" onClick={onClear}
      aria-label={`Clear ${regionFocus.regionName} region filter`}>Clear region</button>
  </aside>;
}

function renderValue(value) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") {
    try { return JSON.stringify(value, null, 2); }
    catch { return "Unable to serialize this snapshot."; }
  }
  return String(value);
}

export function InspectorDrawer({ inspection, data, onClose, headingRef }) {
  if (!inspection) return null;
  const view = inspectionPresentation(inspection, data);
  return <aside className="observatory-drawer" aria-label="Observatory inspector">
    <header>
      <div>
        <div className="eyebrow">Inspector</div>
        <h2 ref={headingRef} tabIndex="-1">{view.title}</h2>
        {view.subtitle && <p>{view.subtitle}</p>}
      </div>
      <button type="button" className="button" onClick={onClose} aria-label="Close inspector">Close</button>
    </header>
    {view.lastObserved && <div className="observatory-last-observed">Last observed · this item is outside the current live window.</div>}
    {view.narrative && <p className="observatory-drawer-narrative">{view.narrative}</p>}
    {view.fields.length > 0 && <dl>{view.fields.map(field => <div key={field.label}>
      <dt>{field.label}</dt><dd>{field.value}</dd>
    </div>)}</dl>}
    <details><summary>Raw data</summary><pre>{renderValue(view.raw)}</pre></details>
  </aside>;
}

export function ObservatoryInteractionProvider({ data, children }) {
  const [regionFocus, setRegionFocus] = useState(null);
  const [inspection, setInspection] = useState(null);
  const [announcement, setAnnouncement] = useState("");
  const triggerRef = useRef(null);
  const headingRef = useRef(null);

  function clearRegion() {
    setRegionFocus(null);
    setAnnouncement("Region filter cleared.");
  }

  function selectRegion(region) {
    setRegionFocus(current => {
      const next = nextRegionFocus(current, region);
      setAnnouncement(next ? `${next.regionName} region filter applied.` : "Region filter cleared.");
      return next;
    });
  }

  function inspect(reference, fallbackSnapshot) {
    triggerRef.current = typeof document === "undefined" ? null : document.activeElement;
    setInspection(makeInspection(reference, fallbackSnapshot));
  }

  function closeInspection() {
    setInspection(null);
    const trigger = triggerRef.current;
    triggerRef.current = null;
    if (trigger?.isConnected) requestAnimationFrame(() => trigger.focus());
  }

  useEffect(() => {
    if (!inspection) return undefined;
    headingRef.current?.focus();
    const onKeyDown = event => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      closeInspection();
    };
    window.addEventListener("keydown", onKeyDown, true);
    return () => window.removeEventListener("keydown", onKeyDown, true);
  }, [inspection]);

  useEffect(() => {
    if (!regionFocus) return;
    const regions = Array.isArray(data?.v2?.map?.regions) ? data.v2.map.regions : [];
    const current = regions.find(region => Number(region.id) === regionFocus.regionId);
    if (!current) {
      setRegionFocus(null);
      setAnnouncement(`${regionFocus.regionName} is no longer available; the region filter was cleared.`);
      return;
    }
    const normalized = normalizeRegion(current);
    if (normalized && (normalized.regionKey !== regionFocus.regionKey || normalized.regionName !== regionFocus.regionName)) {
      setRegionFocus(normalized);
    }
  }, [data?.v2?.map?.regions, regionFocus]);

  const value = useMemo(() => ({
    regionFocus, inspection, announcement, selectRegion, clearRegion, inspect, closeInspection,
  }), [regionFocus, inspection, announcement]);

  return <ObservatoryInteractionContext.Provider value={value}>
    {children}
    <InspectorDrawer inspection={inspection} data={data} onClose={closeInspection} headingRef={headingRef} />
    <div className="sr-only" aria-live="polite" aria-atomic="true">{announcement}</div>
  </ObservatoryInteractionContext.Provider>;
}
```

- [ ] **Step 4: Install the provider and focus bar in `Observatory.jsx`**

Apply this exact structural patch; every line between the shown anchors remains at its current indentation:

```diff
 import { ParticipantPanel } from "./ParticipantPanel";
+import { ObservatoryInteractionProvider, RegionFocusBar, useObservatoryInteraction } from "./ObservatoryInteraction";
 import { ShockModal } from "./ShockModal";
@@
-export function Observatory({ hostedSession = null }) {
+function ObservatoryContents({ hostedSession = null, observatory }) {
   const hosted = Boolean(hostedSession);
   const canControl = !hosted || hostedSession.role === "admin";
-  const { data, connected, loading, error, act, refresh } = useObservatory({ hosted });
+  const { data, connected, loading, error, act, refresh } = observatory;
+  const { regionFocus, clearRegion } = useObservatoryInteraction();
@@
     <RunHeader status={status} participant={participant} connected={connected} loading={loading} act={act}
       hosted={hosted} canControl={canControl}
       onShock={hosted ? null : () => setShockOpen(true)}
       onReplay={hosted ? null : () => setReplayOpen(true)} />
+    <RegionFocusBar regionFocus={regionFocus} onClear={clearRegion} />
@@
   </div>;
 }
+
+export function Observatory({ hostedSession = null }) {
+  const hosted = Boolean(hostedSession);
+  const observatory = useObservatory({ hosted });
+  return <ObservatoryInteractionProvider data={observatory.data}>
+    <ObservatoryContents hostedSession={hostedSession} observatory={observatory} />
+  </ObservatoryInteractionProvider>;
+}
```

The result calls `useObservatory` once in the exported wrapper and gives the provider the identical live `data` object consumed by the panel tree.

- [ ] **Step 5: Make the map consume controlled region state**

In `LivingEconomyMap.jsx`, add this import, remove `useEffect` from the React import, delete the missing-local-region `useEffect` block, and replace its selected-region declaration with:

```jsx
import { useObservatoryInteraction } from "./ObservatoryInteraction";

const { regionFocus, inspection, selectRegion, clearRegion } = useObservatoryInteraction();
const selectedRegionId = regionFocus?.regionId ?? null;
```

In `RegionPlatform`, replace its `choose` declaration with:

```jsx
const choose = () => onSelect(region);
```

Delete the local `toggleRegion` and `clearSelection` declarations. Apply this exact patch to the component-level Escape wrapper and `EconomyScene` props:

```diff
-      <div className="p-3" onKeyDown={event => { if (event.key === "Escape") clearSelection(); }}>
+      <div className="p-3" onKeyDown={event => {
+        if (event.key === "Escape" && !inspection) {
+          event.preventDefault();
+          clearRegion();
+        }
+      }}>
@@
             <EconomyScene scene={scene} layers={layers} selectedRegionId={selectedRegionId}
-              onSelectRegion={toggleRegion} onClearSelection={clearSelection}
+              onSelectRegion={selectRegion} onClearSelection={clearRegion}
               onActive={setActiveItem} onInactive={() => setActiveItem(null)} />
```

Keep `useState` for `activeItem` and layer toggles. Keep the in-card map inspector expression `scene.regions.find(region => region.id === selectedRegionId)` so it derives from provider-owned state. No test wrapper is required because `useObservatoryInteraction` has the Task 5 context fallback.

- [ ] **Step 6: Run focused and complete dashboard tests**

Run:

```bash
cd dashboard && node --test tests/observatory-interaction.test.js tests/living-economy-map.test.js && npm test
```

Expected: all interaction and map tests pass; the pre-existing dashboard suite has 0 failures.

- [ ] **Step 7: Commit the interaction shell**

Run:

```bash
git add -- dashboard/src/components/ObservatoryInteraction.jsx dashboard/src/components/Observatory.jsx dashboard/src/components/LivingEconomyMap.jsx dashboard/tests/observatory-interaction.test.js dashboard/tests/living-economy-map.test.js
git diff --cached --check
git -c user.name='Oneworld' -c user.email='168804661+alinojoumi8@users.noreply.github.com' commit -m "feat(observatory): add region focus and inspector shell"
```

Expected: the provider, focus bar, modeless drawer, and controlled map selection land together.

---

### Task 6: Add exact server-paginated agent region filtering

**Files:**
- Modify: `server/app.py:9-17,266-272`
- Create: `tests/test_observatory_region_filter.py`
- Modify: `dashboard/src/components/AgentsPanel.jsx`
- Modify: `dashboard/src/hooks/useObservatory.js`
- Modify: `dashboard/tests/observatory-interaction.test.js`

**Interfaces:**
- `GET /api/agents` retains the legacy unparameterized array contract.
- Any `limit`, `after_id`, non-empty `q`, `population_tier`, or `region_id` produces `{ items, total, population_total, limit, next_after_id }`.
- `region_id` is an optional positive integer and applies exact `a.region_id=?` filtering before matched counts and cursor paging.
- `agentDirectoryPath({ filter, tier, regionId, afterId })` emits `limit=100`, then non-empty `q`, `population_tier`, `region_id`, and `after_id` in that order.

- [ ] **Step 1: Write the failing API contract test**

Create `tests/test_observatory_region_filter.py` with:

```python
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from run import open_run
from run_config import load_config
from server.app import create_app


@pytest.fixture(scope="module")
def region_client(tmp_path_factory: pytest.TempPathFactory):
    data_dir = tmp_path_factory.mktemp("observatory-region-runs")
    store, world, _ = open_run(
        load_config("runs/r21-real-us.yaml"), None, None, data_dir=data_dir)
    try:
        with TestClient(create_app(world)) as client:
            yield store, client
    finally:
        world.close()


def test_agent_region_filter_combines_with_search_tier_counts_and_cursor(region_client):
    store, client = region_client
    region = store.query_one(
        "SELECT region_id, COUNT(*) AS n FROM agents WHERE region_id IS NOT NULL "
        "GROUP BY region_id ORDER BY n DESC LIMIT 1")
    region_id = int(region["region_id"])
    expected = int(store.scalar(
        "SELECT COUNT(*) FROM agents WHERE region_id=?", (region_id,), default=0))

    legacy = client.get("/api/agents")
    assert legacy.status_code == 200
    assert isinstance(legacy.json(), list)

    first = client.get("/api/agents", params={"limit": 2, "region_id": region_id})
    assert first.status_code == 200
    page = first.json()
    assert page["total"] == expected
    assert page["population_total"] >= expected
    assert all(item["region_id"] == region_id for item in page["items"])
    assert all(item["region_key"] for item in page["items"])

    if page["next_after_id"] is not None:
        second = client.get("/api/agents", params={
            "limit": 2, "region_id": region_id,
            "after_id": page["next_after_id"],
        }).json()
        assert not ({item["id"] for item in page["items"]}
                    & {item["id"] for item in second["items"]})

    agent = store.query_one(
        "SELECT name, population_tier FROM agents WHERE region_id=? ORDER BY id LIMIT 1",
        (region_id,))
    combined = client.get("/api/agents", params={
        "limit": 5, "region_id": region_id, "q": agent["name"],
        "population_tier": agent["population_tier"],
    }).json()
    assert combined["total"] >= 1
    assert all(item["region_id"] == region_id for item in combined["items"])
    assert all(item["population_tier"] == agent["population_tier"]
               for item in combined["items"])
    assert any(item["name"] == agent["name"] for item in combined["items"])
    assert client.get("/api/agents", params={"region_id": 0}).status_code == 422
```

- [ ] **Step 2: Run the API test to verify it fails**

Run:

```bash
../../.venv/bin/python -m pytest tests/test_observatory_region_filter.py -q
```

Expected: FAIL because the current endpoint returns the legacy array and ignores `region_id`.

- [ ] **Step 3: Implement pagination and the exact region predicate**

In `server/app.py`, change the typing import to:

```python
from typing import Literal, Optional
```

Replace the current `agents()` endpoint with:

```python
    @app.get("/api/agents")
    async def agents(
        limit: Optional[int] = Query(default=None, ge=1, le=200),
        after_id: Optional[int] = Query(default=None, ge=0),
        q: str = Query(default="", max_length=120),
        population_tier: Optional[Literal["core", "periphery"]] = None,
        region_id: Optional[int] = Query(default=None, ge=1),
    ):
        columns = (
            "a.id, a.name, a.kind, a.role, a.occupation, a.age, a.health, "
            "a.alive, a.retired, a.employer_id, a.population_tier, "
            "a.region_id, r.region_key"
        )
        base = " FROM agents a LEFT JOIN regions r ON r.id=a.region_id"
        filters: list[str] = []
        filter_params: list[object] = []
        needle = q.strip()
        if population_tier:
            filters.append("a.population_tier=?")
            filter_params.append(population_tier)
        if region_id is not None:
            filters.append("a.region_id=?")
            filter_params.append(region_id)
        if needle:
            escaped = (needle.replace("\\", "\\\\")
                       .replace("%", "\\%")
                       .replace("_", "\\_"))
            pattern = f"%{escaped}%"
            searchable = (
                "a.name", "a.occupation", "a.role", "a.kind", "a.health",
                "a.population_tier", "r.region_key",
            )
            filters.append("(" + " OR ".join(
                f"COALESCE({field}, '') LIKE ? ESCAPE '\\'"
                for field in searchable) + ")")
            filter_params.extend([pattern] * len(searchable))
        filter_sql = " WHERE " + " AND ".join(filters) if filters else ""

        paged = bool(limit is not None or after_id is not None or needle
                     or population_tier or region_id is not None)
        if not paged:
            rows = store.query("SELECT " + columns + base + " ORDER BY a.id")
            return [dict(row) for row in rows]

        page_limit = int(limit or 100)
        page_filters = list(filters)
        page_params = list(filter_params)
        if after_id is not None:
            page_filters.append("a.id>?")
            page_params.append(after_id)
        page_where = " WHERE " + " AND ".join(page_filters) if page_filters else ""
        rows = store.query(
            "SELECT " + columns + base + page_where + " ORDER BY a.id LIMIT ?",
            (*page_params, page_limit + 1),
        )
        items = [dict(row) for row in rows[:page_limit]]
        matched_total = int(store.scalar(
            "SELECT COUNT(*)" + base + filter_sql,
            filter_params,
            default=0,
        ))
        population_total = int(store.scalar(
            "SELECT COUNT(*) FROM agents", default=0))
        return {
            "items": items,
            "total": matched_total,
            "population_total": population_total,
            "limit": page_limit,
            "next_after_id": items[-1]["id"] if len(rows) > page_limit else None,
        }
```

- [ ] **Step 4: Run the API test and the existing R21 API tests**

Run:

```bash
../../.venv/bin/python -m pytest tests/test_observatory_region_filter.py tests/test_r21_api.py -q
```

Expected: both files pass; the unparameterized array contract and detail endpoint remain compatible.

- [ ] **Step 5: Add the failing agent-directory serialization assertion**

Append inside a new test in `dashboard/tests/observatory-interaction.test.js`:

```js
test("agent directory encodes region after search and tier and before cursor", async () => {
  const vite = await createServer({ appType: "custom", logLevel: "silent", server: { middlewareMode: true } });
  try {
    const { agentDirectoryPath } = await vite.ssrLoadModule("/src/components/AgentsPanel.jsx");
    assert.equal(
      agentDirectoryPath({ filter: "Ada Core", tier: "core", regionId: 2, afterId: 100 }),
      "/api/agents?limit=100&q=Ada+Core&population_tier=core&region_id=2&after_id=100",
    );
    const { readFile } = await import("node:fs/promises");
    const source = await readFile(new URL("../src/components/AgentsPanel.jsx", import.meta.url), "utf8");
    assert.match(source, /useEffect\(\(\) => \{\s*setCursors\(\[null\]\);\s*setPageIndex\(0\);\s*\}, \[regionId\]\)/);
    const observatorySource = await readFile(new URL("../src/hooks/useObservatory.js", import.meta.url), "utf8");
    assert.doesNotMatch(observatorySource, /api\("\/api\/agents"\)/);
  } finally { await vite.close(); }
});
```

- [ ] **Step 6: Run the serialization test to verify it fails**

Run:

```bash
cd dashboard && node --test tests/observatory-interaction.test.js
```

Expected: FAIL because `agentDirectoryPath` is not exported by the current client-side panel.

- [ ] **Step 7: Upgrade `AgentsPanel` to the bounded directory and add region state**

In `dashboard/src/components/AgentsPanel.jsx`, replace the first React import and add the interaction import exactly as follows, then place the constants and serializer above the component:

```jsx
import { useEffect, useState } from "react";
import { useObservatoryInteraction } from "./ObservatoryInteraction";

const AGENT_PAGE_SIZE = 100;
const EMPTY_DIRECTORY = {
  items: [], total: 0, population_total: 0, limit: AGENT_PAGE_SIZE, next_after_id: null,
};

export function agentDirectoryPath({ filter = "", tier = "", regionId = null, afterId = null } = {}) {
  const params = new URLSearchParams({ limit: String(AGENT_PAGE_SIZE) });
  if (filter.trim()) params.set("q", filter.trim());
  if (tier) params.set("population_tier", tier);
  if (regionId !== null && regionId !== undefined) params.set("region_id", String(regionId));
  if (afterId !== null && afterId !== undefined) params.set("after_id", String(afterId));
  return `/api/agents?${params.toString()}`;
}
```

Replace `AgentsPanel` from `export function AgentsPanel` through the line immediately before `export function AgentModal` with this complete component. `AgentModal` remains outside the replacement and is therefore byte-for-byte untouched.

```jsx
export function AgentsPanel({ agents = null, initialDirectory = null, participant, status, act }) {
  const { regionFocus } = useObservatoryInteraction();
  const regionId = regionFocus?.regionId ?? null;
  const [filter, setFilter] = useState("");
  const [tier, setTier] = useState("");
  const [cursors, setCursors] = useState([null]);
  const [pageIndex, setPageIndex] = useState(0);
  const [directory, setDirectory] = useState(() => initialDirectory || (
    Array.isArray(agents)
      ? { ...EMPTY_DIRECTORY, items: agents, total: agents.length, population_total: agents.length }
      : EMPTY_DIRECTORY
  ));
  const [directoryLoading, setDirectoryLoading] = useState(false);
  const [directoryError, setDirectoryError] = useState("");
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setCursors([null]);
    setPageIndex(0);
  }, [regionId]);

  useEffect(() => {
    let active = true;
    const timer = window.setTimeout(async () => {
      setDirectoryLoading(true);
      try {
        const page = await api(agentDirectoryPath({
          filter, tier, regionId, afterId: cursors[pageIndex],
        }));
        if (active) {
          setDirectory(page);
          setDirectoryError("");
        }
      } catch (reason) {
        if (active) setDirectoryError(reason instanceof Error ? reason.message : String(reason));
      } finally {
        if (active) setDirectoryLoading(false);
      }
    }, 180);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [filter, tier, regionId, pageIndex, cursors, status?.tick]);

  function resetDirectory(nextFilter = filter, nextTier = tier) {
    setFilter(nextFilter);
    setTier(nextTier);
    setCursors([null]);
    setPageIndex(0);
  }

  function nextPage() {
    if (directory.next_after_id === null || directory.next_after_id === undefined) return;
    setCursors(current => [
      ...current.slice(0, pageIndex + 1), directory.next_after_id,
    ]);
    setPageIndex(current => current + 1);
  }

  async function inspect(id) {
    setLoading(true);
    try {
      const agentDetail = await api(`/api/agents/${id}`);
      let participantHistory = null;
      if (participant?.enabled && agentDetail.agent?.kind === "citizen") {
        participantHistory = await api(`/api/participant/history?agent_id=${id}&limit=50`);
      }
      setDetail({ ...agentDetail, participantHistory });
    } finally { setLoading(false); }
  }

  async function loadOlderParticipantActions() {
    const cursor = detail?.participantHistory?.next_before_id;
    if (!detail?.agent?.id || !cursor) return;
    setLoading(true);
    try {
      const page = await api(
        `/api/participant/history?agent_id=${detail.agent.id}&limit=50&before_id=${cursor}`);
      setDetail(current => ({
        ...current,
        participantHistory: appendParticipantHistory(current?.participantHistory, page),
      }));
    } finally { setLoading(false); }
  }

  async function loadOlderAgentOutputs(kind) {
    const cursor = detail?.output_cursors?.[kind];
    if (!detail?.agent?.id || !cursor) return;
    setLoading(true);
    try {
      const page = await api(
        `/api/agents/${detail.agent.id}/outputs?kind=${kind}&limit=20&before_id=${cursor}`);
      const field = kind === "model" ? "recent_decisions" : "recent_actions";
      setDetail(current => {
        const known = new Set((current?.[field] || []).map(item => item.id));
        return {
          ...current,
          [field]: [...(current?.[field] || []), ...page.items.filter(item => !known.has(item.id))],
          output_cursors: { ...current?.output_cursors, [kind]: page.next_before_id },
        };
      });
    } finally { setLoading(false); }
  }

  async function takeControl(agentId) {
    setLoading(true);
    try {
      await act("/api/participant/control", {
        agent_id: agentId,
        expected_tick: status?.tick ?? 0,
      });
      setDetail(null);
    } finally { setLoading(false); }
  }

  const listed = directory.items || [];
  const start = listed.length ? pageIndex * AGENT_PAGE_SIZE + 1 : 0;
  const end = listed.length ? start + listed.length - 1 : 0;
  return <>
    <Panel
      title={regionFocus ? `Agents · ${directory.total} in ${regionFocus.regionName}` : `Agents · ${directory.population_total || directory.total}`}
      eyebrow="Server-paginated directory · click any row for an output audit"
      className="col-span-full"
      action={<div className="flex flex-wrap gap-2">
        <select className="field !w-auto !py-1.5" value={tier}
          onChange={event => resetDirectory(filter, event.target.value)} aria-label="Filter agents by tier">
          <option value="">All tiers</option><option value="core">Core</option><option value="periphery">Periphery</option>
        </select>
        <input className="field !w-56 max-w-[46vw] !py-1.5" value={filter}
          onChange={event => resetDirectory(event.target.value, tier)}
          placeholder="Search people, roles…" aria-label="Search agents" />
      </div>}
    >
      <div className="scrollbar max-h-[520px] overflow-auto">
        {listed.length ? <table className="data-table">
          <thead><tr><th>#</th><th>Name</th><th>Occupation</th><th>Role</th><th>Region</th><th>Tier</th><th>Age</th><th>Health</th><th>Status</th></tr></thead>
          <tbody>{listed.map(agent => <tr key={agent.id} className="cursor-pointer" tabIndex="0"
            onClick={() => inspect(agent.id)}
            onKeyDown={event => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                inspect(agent.id);
              }
            }}>
            <td className="tabular text-slate-600">{agent.id}</td>
            <td className="font-semibold"><button className="text-left text-slate-200 underline decoration-mint-300/20 underline-offset-4 hover:text-mint-300"
              onClick={event => { event.stopPropagation(); inspect(agent.id); }}>Inspect {agent.name}</button></td>
            <td>{agent.occupation || "—"}</td>
            <td>{agent.role ? <Badge>{shortKind(agent.role)}</Badge> : <span className="text-slate-600">citizen</span>}</td>
            <td>{shortKind(agent.region_key || "unassigned")}</td>
            <td><Badge tone={agent.population_tier === "core" ? "good" : "neutral"}>{agent.population_tier || "periphery"}</Badge></td>
            <td className="tabular">{agent.age}</td>
            <td><Badge tone={agent.health === "healthy" ? "good" : agent.health === "critical" ? "bad" : "warn"}>{agent.health}</Badge></td>
            <td><Badge tone={!agent.alive ? "bad" : agent.retired ? "warn" : "neutral"}>{!agent.alive ? "deceased" : agent.retired ? "retired" : "active"}</Badge></td>
          </tr>)}</tbody>
        </table> : <Empty>{directoryLoading ? "Loading agents…" : regionFocus
          ? `No agents match this search in ${regionFocus.regionName}.`
          : "No agents match this search."}</Empty>}
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-mint-300/10 px-4 py-3 text-xs text-slate-500" aria-live="polite">
        <span>{directoryError
          ? <span className="text-coral-300">Directory unavailable: {directoryError}</span>
          : directoryLoading ? "Refreshing directory…"
          : `${start}–${end} of ${directory.total} matching agents`}</span>
        <div className="flex gap-2">
          <button className="button !min-h-8" disabled={pageIndex === 0 || directoryLoading}
            onClick={() => setPageIndex(current => Math.max(0, current - 1))}>Previous</button>
          <button className="button !min-h-8" disabled={!directory.next_after_id || directoryLoading}
            onClick={nextPage}>Next</button>
        </div>
      </div>
    </Panel>
    {loading && <div className="fixed bottom-4 right-4 z-50 rounded-lg bg-mint-300 px-3 py-2 text-xs font-semibold text-ink-950">Loading agent…</div>}
    {detail && <AgentModal detail={detail} participant={participant} running={status?.running}
      historyLoading={loading} onLoadOlder={loadOlderParticipantActions}
      onLoadOlderOutputs={loadOlderAgentOutputs}
      onTakeControl={takeControl} onClose={() => setDetail(null)} />}
  </>;
}
```

In `dashboard/src/hooks/useObservatory.js`, remove the legacy full-population refresh request with this exact patch; `AgentsPanel` now owns the bounded region-aware request:

```diff
 const INITIAL = {
@@
-  agents: [],
   cost: null,
@@
-      const [status, acceptance, participant, metrics, banks, firms, institutions, news, conversations,
-        events, agents, cost, oracle, shocks, calibrationRun, calibrationAll,
+      const [status, acceptance, participant, metrics, banks, firms, institutions, news, conversations,
+        events, cost, oracle, shocks, calibrationRun, calibrationAll,
@@
         api("/api/firms"), api("/api/institutions"), api("/api/news?limit=24"),
         api("/api/conversations?limit=16"), api("/api/events?limit=80&min_importance=0.5"),
-        api("/api/agents"), api("/api/cost"), api("/api/oracle/predictions"),
+        api("/api/cost"), api("/api/oracle/predictions"),
@@
       setData({ status, acceptance, participant, metrics, banks, firms, institutions, news, conversations,
-        events, agents, cost, oracle, shocks,
+        events, cost, oracle, shocks,
```

- [ ] **Step 8: Run focused frontend and backend tests**

Run:

```bash
cd dashboard && node --test tests/observatory-interaction.test.js && npm test
cd .. && ../../.venv/bin/python -m pytest tests/test_observatory_region_filter.py tests/test_r21_api.py -q
```

Expected: all commands pass; the agent modal tests and participant behavior remain green.

- [ ] **Step 9: Commit exact agent-region filtering**

Run:

```bash
git add -- server/app.py tests/test_observatory_region_filter.py dashboard/src/components/AgentsPanel.jsx dashboard/src/hooks/useObservatory.js dashboard/tests/observatory-interaction.test.js
git diff --cached --check
git -c user.name='Oneworld' -c user.email='168804661+alinojoumi8@users.noreply.github.com' commit -m "feat(observatory): filter agent directory by region"
```

Expected: one commit containing the backward-compatible API extension, paginated UI, and both contract tests.

---

### Task 7: Filter firms and events and inspect primary panels

**Files:**
- Modify: `dashboard/src/components/WorldPanels.jsx`
- Modify: `dashboard/src/components/InformationPanels.jsx`
- Modify: `dashboard/src/components/MacroOverview.jsx`
- Modify: `dashboard/src/components/Observatory.jsx`
- Modify: `dashboard/tests/observatory-interaction.test.js`

**Interfaces:**
- Consumes: `regionFocus` and `inspect` from the provider, plus `firmIdsForRegion` and `eventMatchesRegion` from Task 4.
- Firms filter by active IDs from `data.v2.map.firms`; events filter only by approved top-level payload keys.
- Banks, institutions, metrics, news, and conversations remain global.
- Clicking or keyboard-activating a new inspectable item calls `inspect(reference, snapshot)` and never mutates the API.

- [ ] **Step 1: Add failing cross-filter and inspection assertions**

Append to `dashboard/tests/observatory-interaction.test.js`:

```js
test("world and event panels expose truthful region controls and inspection labels", async () => {
  const source = await Promise.all([
    import("node:fs/promises").then(fs => fs.readFile(new URL("../src/components/WorldPanels.jsx", import.meta.url), "utf8")),
    import("node:fs/promises").then(fs => fs.readFile(new URL("../src/components/InformationPanels.jsx", import.meta.url), "utf8")),
    import("node:fs/promises").then(fs => fs.readFile(new URL("../src/components/MacroOverview.jsx", import.meta.url), "utf8")),
  ]);
  assert.match(source[0], /firmIdsForRegion/);
  assert.match(source[0], /Inspect bank/);
  assert.match(source[0], /Inspect institution/);
  assert.match(source[1], /eventMatchesRegion/);
  assert.match(source[1], /Show all/);
  assert.match(source[1], /Inspect news article/);
  assert.match(source[2], /kind: "macro_metric"/);
});
```

- [ ] **Step 2: Run the contract assertion to verify it fails**

Run:

```bash
cd dashboard && node --test tests/observatory-interaction.test.js
```

Expected: FAIL because no panel imports the interaction model or emits the new labels.

- [ ] **Step 3: Pass the map payload to firms**

In `dashboard/src/components/Observatory.jsx`, change:

```jsx
<FirmsPanel firms={data.firms} />
```

to:

```jsx
<FirmsPanel firms={data.firms} map={data.v2?.map} />
```

- [ ] **Step 4: Add bank, firm, and institution inspection plus exact firm filtering**

In `dashboard/src/components/WorldPanels.jsx`, add these imports and get `{ regionFocus, inspect }` inside each exported panel:

```jsx
import { firmIdsForRegion } from "../observatoryInteraction";
import { inspectionTriggerProps, useObservatoryInteraction } from "./ObservatoryInteraction";
```

Inside `FirmsPanel`, apply these exact declarations:

```jsx
const mappedIds = firmIdsForRegion(map, regionFocus?.regionId);
const visibleFirms = regionFocus ? firms.filter(firm => mappedIds.has(Number(firm.id))) : firms;
const firmHeading = regionFocus
  ? `${visibleFirms.length} firms in ${regionFocus.regionName}`
  : "Production · payroll · price discovery";
```

Set the Firms `Panel` eyebrow to `{firmHeading}` and use `visibleFirms` for both the ticker and table. When it is empty under focus, render:

```jsx
<Empty>No active mapped firms are present in {regionFocus.regionName}.</Empty>
```

Spread this exact helper call on each bank row:

```jsx
{...inspectionTriggerProps(
  inspect,
  { kind: "bank", id: bank.id, title: bank.name },
  bank,
  `Inspect bank ${bank.name}`,
)}
```

Spread this exact helper call on each firm row:

```jsx
{...inspectionTriggerProps(
  inspect,
  { kind: "firm", id: firm.id, title: firm.name },
  firm,
  `Inspect firm ${firm.name}`,
)}
```

Replace each ticker `<span>` with this button:

```jsx
<button key={firm.id} type="button" className="inspectable-card !w-auto shrink-0 rounded-full !px-2.5 !py-1 text-[10px]"
  onClick={() => inspect({ kind: "firm", id: firm.id, title: firm.name }, firm)}
  aria-label={`Inspect firm ${firm.name}`}>
  <strong className="mr-1.5 text-slate-300">{firm.name}</strong>
  <span className="tabular text-mint-300">{money(firm.last_stock_price, false)}</span>
</button>
```

Replace the three institution `<article>` opening and closing tags with buttons and the following handlers; the visible JSX children between each pair of tags stay in place:

```jsx
<button type="button" className="inspectable-card !block p-4"
  aria-label="Inspect institution Government"
  onClick={() => inspect({ kind: "institution", id: "government", title: "Government" }, gov)}>
<button type="button" className="inspectable-card !block p-4"
  aria-label="Inspect institution Venture capital"
  onClick={() => inspect({ kind: "institution", id: "vc", title: "Venture capital" }, vc)}>
<button type="button" className="inspectable-card !block p-4"
  aria-label="Inspect institution Health economy"
  onClick={() => inspect({ kind: "institution", id: "health", title: "Health economy" }, health)}>
```

- [ ] **Step 5: Add news/event inspection and truthful event filtering**

In `dashboard/src/components/InformationPanels.jsx`, add these imports. This task edits only `NewsPanel` and `EventsPanel` in this file.

```jsx
import { eventMatchesRegion } from "../observatoryInteraction";
import { inspectionTriggerProps, useObservatoryInteraction } from "./ObservatoryInteraction";
```

In `NewsPanel`, call `const { inspect } = useObservatoryInteraction()` and replace each article with:

```jsx
<button key={article.id} type="button" className="inspectable-card !block border-b border-mint-300/10 py-3 text-left last:border-0"
  onClick={() => inspect({ kind: "news", id: article.id, title: article.headline }, article)}
  aria-label={`Inspect news article ${article.headline}`}>
  <div className="mb-1 flex items-center gap-2"><Badge>{article.outlet_name || "Outlet"}</Badge><span className="tabular text-[10px] text-slate-600">day {article.tick}</span></div>
  <h3 className="text-sm font-semibold leading-snug text-slate-200">{article.headline}</h3>
  <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-slate-500">{article.body}</p>
</button>
```

In `EventsPanel`, add:

```jsx
const { regionFocus, inspect } = useObservatoryInteraction();
const [showAll, setShowAll] = useState(false);
useEffect(() => setShowAll(false), [regionFocus?.regionId]);
const related = regionFocus
  ? events.filter(event => eventMatchesRegion(event, regionFocus.regionId))
  : events;
const visible = regionFocus && !showAll ? related : events;
```

Keep the Human/Raw and Shock button expressions in the panel action and insert this button between Raw and Shock while a region is focused:

```jsx
<button className="button !min-h-7 !px-2 !py-1" aria-pressed={showAll}
  onClick={() => setShowAll(value => !value)}>{showAll ? "Related only" : "Show all"}</button>
```

Render `visible` and spread this helper call on each event article:

```jsx
{...inspectionTriggerProps(
  inspect,
  { kind: "event", id: event.id, title: shortKind(event.kind) },
  event,
  `Inspect event ${shortKind(event.kind)} from day ${event.tick}`,
)}
```

If `visible` is empty while region focus is active, render:

```jsx
<Empty>No region-tagged events for {regionFocus.regionName} appear in the current event window.</Empty>
```

- [ ] **Step 6: Add macro metric inspection without changing charts**

In `MacroOverview.jsx`, add this import and call `const { inspect } = useObservatoryInteraction()` at the beginning of `MacroOverview`:

```jsx
import { inspectionTriggerProps, useObservatoryInteraction } from "./ObservatoryInteraction";
```

Immediately before returning each metric article, define:

```jsx
const snapshot = {
  id: key, title: label, help, latest, delta,
  series: series.slice(-30),
};
const trigger = inspectionTriggerProps(
  inspect,
  { kind: "macro_metric", id: key, title: label },
  snapshot,
  `Inspect macro metric ${label}`,
);
```

Spread `{...trigger}` on the metric `<article>` after its existing `key`, `className`, and `title={help}` props; its values and Recharts children are not edited.

- [ ] **Step 7: Run the focused and full dashboard tests**

Run:

```bash
cd dashboard && node --test tests/observatory-interaction.test.js && npm test
```

Expected: all tests pass; conversation search and inline event raw rendering remain unchanged.

- [ ] **Step 8: Commit region filtering and primary inspection**

Run:

```bash
git add -- dashboard/src/components/WorldPanels.jsx dashboard/src/components/InformationPanels.jsx dashboard/src/components/MacroOverview.jsx dashboard/src/components/Observatory.jsx dashboard/tests/observatory-interaction.test.js
git diff --cached --check
git -c user.name='Oneworld' -c user.email='168804661+alinojoumi8@users.noreply.github.com' commit -m "feat(observatory): cross-filter regions and inspect primary panels"
```

Expected: one coherent client-only commit with no region inference in global panels.

---

### Task 8: Inspect legal, startup, acceptance, and cost records and style the shell

**Files:**
- Modify: `dashboard/src/components/V2Observatory.jsx`
- Modify: `dashboard/src/components/AcceptancePanel.jsx`
- Modify: `dashboard/src/components/OracleAndCost.jsx`
- Modify: `dashboard/src/index.css`
- Modify: `dashboard/tests/observatory-interaction.test.js`
- Regenerate: `server/static/index.html`
- Regenerate: `server/static/assets/*`

**Interfaces:**
- Consumes: `inspect(reference, snapshot)` from Task 5 and the typed kinds supported by Task 4.
- Produces: inspection triggers for legal matters/obligations, bills, startup summaries and records, acceptance checks, shock traces, and provider-cost rows.
- Existing Oracle submission and suggestion buttons, calibration scope, acceptance progress, and map interactions remain unchanged.

- [ ] **Step 1: Add failing extended-inspection and style contracts**

Append to `dashboard/tests/observatory-interaction.test.js`:

```js
test("extended observatory panels emit supported inspection kinds and responsive shell styles", async () => {
  const { readFile } = await import("node:fs/promises");
  const [v2, acceptance, cost, css] = await Promise.all([
    readFile(new URL("../src/components/V2Observatory.jsx", import.meta.url), "utf8"),
    readFile(new URL("../src/components/AcceptancePanel.jsx", import.meta.url), "utf8"),
    readFile(new URL("../src/components/OracleAndCost.jsx", import.meta.url), "utf8"),
    readFile(new URL("../src/index.css", import.meta.url), "utf8"),
  ]);
  assert.match(v2, /kind: "legal_matter"/);
  assert.match(v2, /kind: "legal_obligation"/);
  assert.match(v2, /kind: "bill"/);
  assert.match(v2, /kind: "startup_(record|summary)"/);
  assert.match(acceptance, /kind: "acceptance_check"/);
  assert.match(acceptance, /kind: "shock_trace"/);
  assert.match(cost, /kind: "provider_cost"/);
  assert.match(css, /\.observatory-focus-bar/);
  assert.match(css, /\.observatory-drawer/);
  assert.match(css, /@media \(max-width: 640px\)[\s\S]*\.observatory-drawer/);
  assert.match(css, /prefers-reduced-motion: reduce[\s\S]*\.observatory-drawer/);
});
```

- [ ] **Step 2: Run the contract test to verify it fails**

Run:

```bash
cd dashboard && node --test tests/observatory-interaction.test.js
```

Expected: FAIL for missing supported inspection-kind strings and shell selectors.

- [ ] **Step 3: Add legal, political, and startup inspection**

In `V2Observatory.jsx`, replace its UI import with the first line below, add the interaction import, and call `const { inspect } = useObservatoryInteraction()` in both `InstitutionalPulse` and `LegalPoliticalPanels`:

```jsx
import { Badge, Empty, Panel } from "./ui";
import { inspectionTriggerProps, useObservatoryInteraction } from "./ObservatoryInteraction";
```

Spread this helper call on each legal-matter card:

```jsx
{...inspectionTriggerProps(
  inspect,
  { kind: "legal_matter", id: item.id, title: item.title || `Matter ${item.id}` },
  item,
  `Inspect legal matter ${item.title || item.id}`,
)}
```

Spread these calls on each obligation and bill wrapper respectively:

```jsx
{...inspectionTriggerProps(
  inspect,
  { kind: "legal_obligation", id: item.id, title: shortKind(item.obligation_type) },
  item,
  `Inspect legal obligation ${item.id}`,
)}
{...inspectionTriggerProps(
  inspect,
  { kind: "bill", id: bill.id, title: bill.title },
  bill,
  `Inspect bill ${bill.title}`,
)}
```

Below the four startup summary stats, render actual records from these arrays, capped at two per collection:

```jsx
{[
  ["term_sheets", startups?.term_sheets],
  ["funding_rounds", startups?.funding_rounds],
  ["ip_assets", startups?.ip_assets],
  ["mergers", startups?.mergers],
].flatMap(([collection, records]) => (records || []).slice(0, 2).map(record => (
  <button key={`${collection}-${record.id}`} type="button" className="inspectable-card"
    onClick={() => inspect({
      kind: "startup_record", id: record.id, collection,
      title: record.title || record.name || `${shortKind(collection)} ${record.id}`,
    }, record)}>
    <span>{record.title || record.name || `${shortKind(collection)} ${record.id}`}</span>
    <Badge>{shortKind(record.status || collection)}</Badge>
  </button>
)))}
```

Change its signature to `function Stat({ label, value, onInspect = null })`. When `onInspect` is present, it returns this button; otherwise it returns its current `<div>`:

```jsx
if (onInspect) return <button type="button" className="inspectable-card !block rounded-lg border border-mint-300/10 bg-ink-950/40 p-3" onClick={onInspect}>
  <div className="text-[10px] uppercase tracking-widest text-slate-600">{label}</div>
  <div className="mt-1 text-xl font-semibold tabular text-slate-200">{value}</div>
</button>;
```

For each startup stat pass:

```jsx
onInspect={() => inspect(
  { kind: "startup_summary", id: null, title: label },
  { title: label, count: value, description: "Summary from the current startup lifecycle payload." },
)}
```

The four `label`/`value` pairs are `Term sheets`/`startups?.term_sheets?.length || 0`, `Funding rounds`/`startups?.funding_rounds?.length || 0`, `IP assets`/`startups?.ip_assets?.length || 0`, and `M&A reviews`/`startups?.mergers?.length || 0`. No synthetic ID or region field is added.

- [ ] **Step 4: Add acceptance check and shock-trace inspection**

In `AcceptancePanel.jsx`, add the import below and call `const { inspect } = useObservatoryInteraction()` as the first line of `AcceptancePanel`, before the configured early return. Spread the following helper call on each check article:

```jsx
import { inspectionTriggerProps, useObservatoryInteraction } from "./ObservatoryInteraction";

{...inspectionTriggerProps(
  inspect,
  { kind: "acceptance_check", id: check.id, title: check.label },
  check,
  `Inspect acceptance check ${check.label}`,
)}
```

Spread this helper call on each shock-trace article:

```jsx
{...inspectionTriggerProps(
  inspect,
  { kind: "shock_trace", id: kind, title: `${kind.replaceAll("_", " ")} shock trace` },
  { id: kind, kind, ...trace },
  `Inspect ${kind.replaceAll("_", " ")} shock trace`,
)}
```

- [ ] **Step 5: Add provider-cost inspection without altering Oracle or calibration**

In `OracleAndCost.jsx`, add this import and call `const { inspect } = useObservatoryInteraction()` only inside `CostPanel`:

```jsx
import { inspectionTriggerProps, useObservatoryInteraction } from "./ObservatoryInteraction";
```

Spread the first and third helper calls below on the existing `by_model` and `by_agent` row `<div>` elements. The middle call defines the identical reference/snapshot contract used by the native `by_purpose` button shown next:

```jsx
{...inspectionTriggerProps(inspect,
  { kind: "provider_cost", id: row.model, collection: "by_model", title: row.model },
  { ...row, id: row.model }, `Inspect provider model cost ${row.model}`)}
{...inspectionTriggerProps(inspect,
  { kind: "provider_cost", id: row.purpose, collection: "by_purpose", title: row.purpose },
  { ...row, id: row.purpose }, `Inspect provider purpose cost ${row.purpose}`)}
{...inspectionTriggerProps(inspect,
  { kind: "provider_cost", id: row.agent_id ?? `shared-${index}`, collection: "by_agent", title: row.agent_name },
  { ...row, id: row.agent_id ?? `shared-${index}` }, `Inspect provider agent cost ${row.agent_name}`)}
```

Because `by_purpose` currently renders a bare `Badge`, replace that map expression with native buttons so it can receive the middle helper call:

```jsx
<div className="flex flex-wrap gap-1.5">{cost?.by_purpose?.map(row => <button
  key={row.purpose} type="button" className="inspectable-card !w-auto !p-0"
  onClick={() => inspect(
    { kind: "provider_cost", id: row.purpose, collection: "by_purpose", title: row.purpose },
    { ...row, id: row.purpose },
  )} aria-label={`Inspect provider purpose cost ${row.purpose}`}>
  <Badge>{row.purpose} · {row.calls}</Badge>
</button>)}</div>
```

- [ ] **Step 6: Add shared focus, drawer, and inspectable styles**

Insert before the existing reduced-motion block in `dashboard/src/index.css`:

```css
.inspectable-card {
  display: flex;
  width: 100%;
  align-items: center;
  justify-content: space-between;
  gap: .75rem;
  border: 1px solid transparent;
  border-radius: .65rem;
  padding: .55rem;
  text-align: left;
  transition: border-color 160ms ease, background 160ms ease, transform 160ms ease;
}
.inspectable-card:hover { border-color: rgba(121, 230, 189, .22); background: rgba(121, 230, 189, .04); transform: translateY(-1px); }
.inspectable-card:focus-visible,
[role="button"]:focus-visible { outline: 2px solid #79e6bd; outline-offset: 2px; }
.observatory-focus-bar {
  position: sticky;
  top: 4.4rem;
  z-index: 35;
  display: flex;
  max-width: 1760px;
  margin: .75rem auto 0;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  border: 1px solid rgba(121, 230, 189, .28);
  border-radius: .9rem;
  background: rgba(7, 18, 15, .94);
  padding: .7rem 1rem;
  box-shadow: 0 14px 45px rgba(0, 0, 0, .32);
  backdrop-filter: blur(14px);
}
.observatory-focus-bar strong { color: #d8e8e2; font-size: .9rem; }
.observatory-focus-bar p { margin-top: .15rem; color: #78938a; font-size: .7rem; }
.observatory-drawer {
  position: fixed;
  inset: 4.8rem 0 0 auto;
  z-index: 45;
  width: min(30rem, 92vw);
  overflow-y: auto;
  border-left: 1px solid rgba(121, 230, 189, .2);
  background: rgba(5, 13, 11, .97);
  padding: 1rem;
  box-shadow: -22px 0 70px rgba(0, 0, 0, .48);
  animation: observatory-drawer-in 180ms ease-out;
}
.observatory-drawer > header { display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem; }
.observatory-drawer h2 { margin-top: .2rem; color: #e7f1ed; font-size: 1.15rem; font-weight: 700; }
.observatory-drawer h2:focus { outline: none; }
.observatory-drawer header p,
.observatory-drawer-narrative { margin-top: .35rem; color: #9fb8af; font-size: .78rem; line-height: 1.55; }
.observatory-drawer dl { margin-top: 1rem; display: grid; gap: .45rem; }
.observatory-drawer dl > div { display: grid; grid-template-columns: minmax(7rem, .8fr) 1.2fr; gap: .75rem; border-top: 1px solid rgba(121, 230, 189, .1); padding-top: .45rem; font-size: .72rem; }
.observatory-drawer dt { color: #78938a; }
.observatory-drawer dd { color: #d8e8e2; overflow-wrap: anywhere; }
.observatory-drawer details { margin-top: 1rem; border-top: 1px solid rgba(121, 230, 189, .1); padding-top: .7rem; color: #79e6bd; font-size: .72rem; }
.observatory-drawer pre { margin-top: .6rem; overflow-x: auto; white-space: pre-wrap; color: #78938a; font-size: .65rem; }
.observatory-last-observed { margin-top: .8rem; border: 1px solid rgba(247, 215, 131, .2); border-radius: .55rem; background: rgba(247, 215, 131, .05); padding: .5rem; color: #f7d783; font-size: .68rem; }
@keyframes observatory-drawer-in { from { transform: translateX(1.5rem); opacity: 0; } }

@media (max-width: 640px) {
  .observatory-focus-bar { position: static; margin-inline: .75rem; align-items: flex-start; }
  .observatory-drawer {
    inset: auto 0 0;
    width: auto;
    max-height: calc(100vh - 5rem);
    border-left: 0;
    border-top: 1px solid rgba(121, 230, 189, .2);
    border-radius: 1rem 1rem 0 0;
    animation-name: observatory-sheet-in;
  }
  @keyframes observatory-sheet-in { from { transform: translateY(1.5rem); opacity: 0; } }
}
```

Inside the existing `@media (prefers-reduced-motion: reduce)` block add:

```css
.observatory-drawer, .observatory-focus-bar, .inspectable-card { animation: none !important; transition: none !important; }
```

- [ ] **Step 7: Run tests and build the production dashboard**

Run:

```bash
cd dashboard && npm test && npm run build
```

Expected: all dashboard tests pass and Vite writes a new hashed bundle without warnings or unresolved imports.

- [ ] **Step 8: Commit extended interactions, styles, and generated assets**

Run:

```bash
git add -- dashboard/src/components/V2Observatory.jsx dashboard/src/components/AcceptancePanel.jsx dashboard/src/components/OracleAndCost.jsx dashboard/src/index.css dashboard/tests/observatory-interaction.test.js server/static/index.html server/static/assets
git diff --cached --check
git diff --cached --stat
git -c user.name='Oneworld' -c user.email='168804661+alinojoumi8@users.noreply.github.com' commit -m "feat(observatory): inspect institutional and operations evidence"
```

Expected: the source changes and one coherent Vite hash replacement are committed together.

---

### Task 9: Verify the complete live interaction story

**Files:**
- Verify: `dashboard/src/components/LivingEconomyMap.jsx`
- Verify: `dashboard/src/components/livingEconomyMapModel.js`
- Verify: `dashboard/src/components/ObservatoryInteraction.jsx`
- Verify: `dashboard/src/observatoryInteraction.js`
- Verify: `dashboard/src/components/AgentsPanel.jsx`
- Verify: `dashboard/src/components/WorldPanels.jsx`
- Verify: `dashboard/src/components/InformationPanels.jsx`
- Verify: `dashboard/src/index.css`
- Verify: `server/static/index.html`

**Interfaces:**
- Consumes: the live run API at `http://127.0.0.1:8001/`, a local TCP forward on `8000`, and the isolated Vite app at `http://127.0.0.1:5173/`.
- Produces: acceptance evidence for desktop/mobile layout, region cross-filtering, shared inspection, keyboard/focus behavior, polling persistence, layer controls, and reduced motion.

- [ ] **Step 1: Run every automated check from the isolated worktree**

Run:

```bash
cd dashboard && npm test && npm run build
cd .. && ../../.venv/bin/python -m pytest -q
```

Expected: dashboard tests and Vite build exit 0; Python reports the complete suite passing with only the known skips/warning.

- [ ] **Step 2: Confirm the live payload has meaningful map and region-filter data**

Run:

```bash
curl -fsS http://127.0.0.1:8001/api/v2/map | python3 -c 'import json,sys; p=json.load(sys.stdin); print({"enabled":p.get("enabled"),"regions":len(p.get("regions",[])),"firms":len(p.get("firms",[])),"core_agents":len(p.get("core_agents",[])),"flows":len(p.get("flows",[]))})'
curl -fsS 'http://127.0.0.1:8001/api/agents?limit=2&region_id=1' | python3 -c 'import json,sys; p=json.load(sys.stdin); print({"total":p.get("total"),"page":len(p.get("items",[])),"region_ids":sorted({a.get("region_id") for a in p.get("items",[])})})'
```

Expected for the current run: map `enabled` is `True`, there are at least 3 regions and 1 flow, and every returned agent has `region_id` 1. If region 1 has no agents, take the first numeric region ID from the map response and repeat the second command with it.

- [ ] **Step 3: Forward Vite's API target to the live API**

In terminal A, run:

```bash
python3 - <<'PY'
import asyncio

async def copy(reader, writer):
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    finally:
        writer.close()

async def handle(client_reader, client_writer):
    server_reader, server_writer = await asyncio.open_connection("127.0.0.1", 8001)
    await asyncio.gather(
        copy(client_reader, server_writer),
        copy(server_reader, client_writer),
    )

async def main():
    server = await asyncio.start_server(handle, "127.0.0.1", 8000)
    async with server:
        await server.serve_forever()

asyncio.run(main())
PY
```

Expected: the process stays running without a bind error. In a third terminal, `curl -fsS http://127.0.0.1:8000/api/status` returns the live run status from port 8001.

- [ ] **Step 4: Start the isolated Vite preview**

In terminal B, run:

```bash
cd dashboard && npm run dev -- --host 127.0.0.1 --port 5173
```

Expected: Vite reports `http://127.0.0.1:5173/`; opening it loads live day-92-or-later data through the forwarder.

- [ ] **Step 5: Capture desktop and mobile evidence from the isolated preview**

Run in a third terminal:

```bash
desktop_profile=$(mktemp -d /tmp/agent-economy-observatory-desktop.XXXXXX)
google-chrome --headless=new --no-sandbox --disable-gpu --hide-scrollbars --window-size=1600,1100 --virtual-time-budget=10000 --user-data-dir="$desktop_profile" --screenshot=/tmp/agent-economy-observatory-desktop.png 'http://127.0.0.1:5173/?review=desktop'
mobile_profile=$(mktemp -d /tmp/agent-economy-observatory-mobile.XXXXXX)
google-chrome --headless=new --no-sandbox --disable-gpu --hide-scrollbars --window-size=430,932 --virtual-time-budget=10000 --user-data-dir="$mobile_profile" --screenshot=/tmp/agent-economy-observatory-mobile.png 'http://127.0.0.1:5173/?review=mobile'
```

Expected desktop: three raised region platforms, separated curved routes, wrapped layer controls, no clipped labels, and normal Observatory panels below. Expected mobile: no horizontal page overflow; the map, focus bar, tables, and bottom-sheet geometry fit a 430-pixel viewport.

- [ ] **Step 6: Exercise the exact live interaction sequence**

Open `http://127.0.0.1:5173/?review=interaction` and perform:

1. Click a region platform; the compact map inspector updates, unrelated routes recede, and the focus bar says only firms, agents, and region-tagged events are filtered.
2. Confirm Firms shows only IDs present for that region in `/api/v2/map`; its header names the region or its empty state says no active mapped firms.
3. Confirm Agents returns to page 1 while keeping a typed search and selected tier; force a bad request by stopping terminal A briefly and confirm the last valid page stays visible with `Directory unavailable`.
4. Confirm Events defaults to region-related items; click `Show all`, verify `aria-pressed=true` and global recent events return, then click `Related only`.
5. Click a bank, firm, institution, news article, macro metric, legal matter, obligation, bill, startup item or summary, acceptance check, shock trace, provider-cost row, and event; each opens the shared labelled drawer with raw data.
6. Open an agent and confirm the existing agent modal and participant/output-audit controls still work independently of the drawer.
7. Open the shared drawer from a keyboard-focused row, press Escape, and confirm focus returns to that row. Press Escape again from the map or use `Clear region`; the region focus clears.
8. Toggle `Migration routes` off and on; its `aria-pressed` state and gold dotted routes change together.
9. Leave an inspector open for two polling intervals; it stays open and refreshes the record. If a recent-window item drops out, it shows `Last observed` rather than closing.
10. Use the conversation search, event Human/Raw toggle, Oracle form, calibration scope, participant controls, shock modal, and replay modal; each specialized interaction retains its prior behavior.

- [ ] **Step 7: Verify reduced motion and responsive focus behavior**

In browser DevTools, emulate `prefers-reduced-motion: reduce`; expect route dashes, drawer, focus bar, and inspectable-card transitions to remain static while route patterns, direction markers, labels, and keyboard focus are still visible. At widths below 640 pixels, confirm the focus bar scrolls normally and the inspector is a bottom sheet below the run header.

- [ ] **Step 8: Re-run the focused acceptance checks after browser exercise**

Run:

```bash
cd dashboard && node --test tests/living-economy-map.test.js tests/observatory-interaction.test.js && npm run build
cd .. && ../../.venv/bin/python -m pytest tests/test_observatory_region_filter.py tests/test_r21_api.py -q
```

Expected: all focused tests pass and the production build exits 0.

- [ ] **Step 9: Review the final feature diff**

Run:

```bash
git status --short
git diff --check
git log -9 --oneline
```

Expected: no whitespace errors; all task commits are present; only documented verification artifacts, if any, remain untracked; the main worktree's unrelated pre-existing changes were never staged or modified from this isolated worktree.
