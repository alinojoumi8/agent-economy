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
        <circle cy={-height} r="3" fill="#e7f1ed"><title>{`${firm.name} · ${firm.sector}`}</title></circle>
      </g>;
    })}
    {actorsVisible && region.coreAgentItems.slice(0, 18).map((agent, agentIndex) => {
      const angle = (Math.PI * 2 * agentIndex) / Math.max(1, Math.min(18, region.coreAgentItems.length));
      return <circle key={agent.id} cx={Math.cos(angle) * radius * 0.73}
        cy={Math.sin(angle) * radius * 0.28} r="2.7" fill="#ffffff" fillOpacity=".78">
        <title>{`${agent.name} · ${agent.role || agent.occupation}`}</title>
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
  return <svg viewBox="0 0 1000 560" role="group" aria-labelledby={`${prefix}-title ${prefix}-description`}
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
