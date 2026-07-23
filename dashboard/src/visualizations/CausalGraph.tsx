import { useMemo, useState } from "react";
import type { CausalEdge, CausalNode, StableReference } from "../generated/worldOs";

function key(ref: StableReference): string { return `${ref.kind}:${ref.id}`; }

export function CausalGraph({
  nodes, edges, selected, onSelect,
}: {
  nodes: CausalNode[];
  edges: CausalEdge[];
  selected: string | null;
  onSelect: (ref: StableReference) => void;
}) {
  const [zoom, setZoom] = useState(1);
  const positioned = useMemo(() => nodes.map((node, index) => {
    const angle = (Math.PI * 2 * index) / Math.max(1, nodes.length) - Math.PI / 2;
    const radius = nodes.length < 4 ? 105 : 145;
    return { node, x: 240 + Math.cos(angle) * radius, y: 190 + Math.sin(angle) * radius };
  }), [nodes]);
  const byKey = new Map(positioned.map(item => [key(item.node), item]));
  if (nodes.length > 120 || typeof SVGSVGElement === "undefined") {
    return <div className="world-os-graph-fallback" role="status">
      Graph renderer fallback active. Use the synchronized semantic table for this bounded large state.
    </div>;
  }
  const changeZoom = (value: number) => setZoom(Math.min(1.8, Math.max(.7, value)));
  return <div className="world-os-graph-viewport">
    <div className="world-os-graph-controls" role="group" aria-label="Causal graph zoom">
      <button type="button" onClick={() => changeZoom(zoom - .2)} aria-label="Zoom out" disabled={zoom <= .7}>−</button>
      <output aria-live="polite">{Math.round(zoom * 100)}%</output>
      <button type="button" onClick={() => changeZoom(zoom + .2)} aria-label="Zoom in" disabled={zoom >= 1.8}>+</button>
      <button type="button" onClick={() => setZoom(1)} aria-label="Reset graph zoom">Reset</button>
    </div>
    <svg className="world-os-causal-graph" viewBox="0 0 480 380" role="group" aria-label="Causal graph">
      <defs><marker id="causal-arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0,0 L0,6 L7,3 z" /></marker></defs>
      <g className="world-os-graph-canvas" transform={`translate(240 190) scale(${zoom}) translate(-240 -190)`}>
        {edges.map(edge => {
          const source = byKey.get(key(edge.source));
          const target = byKey.get(key(edge.target));
          if (!source || !target) return null;
          return <g key={edge.id}>
            <line x1={source.x} y1={source.y} x2={target.x} y2={target.y} markerEnd="url(#causal-arrow)" />
            <text x={(source.x + target.x) / 2} y={(source.y + target.y) / 2}>{edge.relation}</text>
          </g>;
        })}
        {positioned.map(({ node, x, y }) => <g
          key={key(node)}
          role="button"
          tabIndex={0}
          aria-label={`${node.kind} ${node.id} at tick ${node.tick}`}
          className={selected === key(node) ? "selected" : ""}
          transform={`translate(${x} ${y})`}
          onClick={() => onSelect(node)}
          onKeyDown={event => {
            if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onSelect(node); }
          }}
        >
          <circle r="27" /><text textAnchor="middle" y="-2">{node.kind.replace("action_proposal", "proposal")}</text><text textAnchor="middle" y="12">{node.id}</text>
        </g>)}
      </g>
    </svg>
  </div>;
}
