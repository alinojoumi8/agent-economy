# Living Economy Map Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Observatory's flat regional map with a responsive, accessible isometric SVG atlas whose regions and aggregated trade, migration, firm, and strategic-agent data can be explored interactively.

**Architecture:** Keep `/api/v2/map` unchanged. A pure JavaScript model module will validate and aggregate the payload, while a focused React module owns presentation state and renders an SVG scene plus an HTML inspector; `V2Observatory.jsx` will preserve its existing public `EconomicMap` export by re-exporting the new component.

**Tech Stack:** React 19.2, JavaScript modules, SVG, Tailwind CSS 4.3, Vite 8.1, Node's built-in test runner, React server rendering.

## Global Constraints

- Add no new production dependency.
- Treat the view as an abstract economic topology, not a geographic map.
- Keep `/api/v2/map`, persistence, and simulation state unchanged.
- Preserve the current disabled and no-data empty-state copy.
- Aggregate at most 100 API flow rows into one route per source, destination, and kind.
- Trade is mint and solid-dashed; migration is gold and dotted-dashed so color is not the only distinction.
- Tooltips are supplementary; durable selected-region information lives in ordinary HTML.
- `prefers-reduced-motion: reduce` disables decorative route motion and nonessential transitions.
- Preserve unrelated working-tree changes and stage only feature-specific files or hunks.

## File structure

- Create `dashboard/src/components/livingEconomyMapModel.js`: payload validation, flow aggregation, and region-summary derivation only.
- Create `dashboard/src/components/LivingEconomyMap.jsx`: React state, layer controls, SVG scene, region platforms, routes, tooltip, and inspector.
- Modify `dashboard/src/components/V2Observatory.jsx:1-34`: remove the old flat-map implementation and re-export `EconomicMap` from the focused module; leave the institutional panels intact.
- Modify `dashboard/src/index.css:154-156`: add scene focus, route-flow animation, depth, hover, and reduced-motion styles before the existing reduced-motion rule.
- Create `dashboard/tests/living-economy-map.test.js`: pure projection tests plus server-rendered component and accessibility assertions.
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
git commit -m "feat(observatory): model living economy map data"
```

Expected: a commit containing only the new model and focused tests. If Git identity is unset, use the existing latest-commit identity with per-command `git -c user.name=... -c user.email=... commit`; do not change repository or global Git configuration.

---

### Task 2: Render and integrate the interactive isometric scene

**Files:**
- Create: `dashboard/src/components/LivingEconomyMap.jsx`
- Modify: `dashboard/src/components/V2Observatory.jsx:1-34`
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
git add -- dashboard/src/components/LivingEconomyMap.jsx dashboard/tests/living-economy-map.test.js
git add -p -- dashboard/src/components/V2Observatory.jsx
git diff --cached --check
git diff --cached -- dashboard/src/components/V2Observatory.jsx
git commit -m "feat(observatory): add interactive isometric economy map"
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
git commit -m "style(observatory): polish economy map depth and motion"
```

Expected: the commit includes only the stylesheet contract, map styles, and Vite's regenerated static bundle. Review the cached asset deletions and additions as one coherent hash replacement before committing.

---

### Task 4: Verify the complete live interaction story

**Files:**
- Verify: `dashboard/src/components/LivingEconomyMap.jsx`
- Verify: `dashboard/src/components/livingEconomyMapModel.js`
- Verify: `dashboard/src/index.css`
- Verify: `server/static/index.html`

**Interfaces:**
- Consumes: the running application at `http://127.0.0.1:8001/` and its day-92-or-later `/api/v2/map` payload.
- Produces: acceptance evidence for desktop, mobile, keyboard operation, layer filtering, selection persistence, and reduced motion.

- [ ] **Step 1: Confirm the live payload exercises the scene**

Run:

```bash
curl -fsS http://127.0.0.1:8001/api/v2/map | python3 -c 'import json,sys; p=json.load(sys.stdin); print({"enabled":p.get("enabled"),"regions":len(p.get("regions",[])),"firms":len(p.get("firms",[])),"core_agents":len(p.get("core_agents",[])),"flows":len(p.get("flows",[]))})'
```

Expected for the current run: `enabled` is `True`, `regions` is at least 3, `core_agents` is at least 1, and `flows` is at least 1.

- [ ] **Step 2: Capture the desktop scene**

Run:

```bash
profile_dir=$(mktemp -d /tmp/agent-economy-map-desktop.XXXXXX)
google-chrome --headless=new --no-sandbox --disable-gpu --hide-scrollbars --window-size=1600,1100 --virtual-time-budget=8000 --user-data-dir="$profile_dir" --screenshot=/tmp/agent-economy-map-desktop.png 'http://127.0.0.1:8001/?map-review=desktop'
```

Expected: the screenshot shows three raised regional platforms, a perspective grid, separated curved route families, layer controls, and a right-side inspector without clipped region labels.

- [ ] **Step 3: Capture the mobile scene**

Run:

```bash
profile_dir=$(mktemp -d /tmp/agent-economy-map-mobile.XXXXXX)
google-chrome --headless=new --no-sandbox --disable-gpu --hide-scrollbars --window-size=430,932 --virtual-time-budget=8000 --user-data-dir="$profile_dir" --screenshot=/tmp/agent-economy-map-mobile.png 'http://127.0.0.1:8001/?map-review=mobile'
```

Expected: the SVG remains fully inside the card, layer buttons wrap without horizontal overflow, and the inspector stacks below the scene.

- [ ] **Step 4: Exercise mouse and keyboard behavior in the live browser**

Open `http://127.0.0.1:8001/?map-review=interaction` and perform this exact sequence:

1. Click `Northstar Federation`; expect the inspector heading to become `Northstar Federation` and unrelated routes to fade.
2. Click `Northstar Federation` again; expect the inspector heading to return to `Select a region`.
3. Click `Migration routes`; expect its `aria-pressed` state to become `false` and gold routes to disappear.
4. Click `Migration routes` again; expect its `aria-pressed` state to become `true` and gold routes to return.
5. Tab from the layer controls into the scene; expect visible focus on routes and regional platforms.
6. Focus `Ironvale Union` and press Enter; expect the inspector to show `Ironvale Union`.
7. Press Escape; expect the inspector to return to `Select a region`.
8. Reload while the run is polling; expect the page to remain responsive and the route count to match the aggregated payload rather than the raw 100-row flow count.

- [ ] **Step 5: Verify reduced motion and rerun all automated checks**

In browser DevTools, emulate `prefers-reduced-motion: reduce`; expect route dashes to remain static while all routes and direction markers stay visible. Then run:

```bash
cd dashboard && npm test && npm run build
```

Expected: all tests pass and the production build exits 0.

- [ ] **Step 6: Review the final feature diff**

Run:

```bash
git status --short
git diff --check
git log -4 --oneline
```

Expected: no whitespace errors; feature commits are present; unrelated pre-existing working-tree changes remain untouched and uncommitted.
