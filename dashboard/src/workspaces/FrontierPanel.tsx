import { useState } from "react";
import "./frontier.css";

export type FrontierState = {
  tick: number;
  required_work: number;
  sites: Array<{id: number; x: number; y: number; terrain?: string; resource?: string;
    capacity?: number; discovered_tick: number | null; discovered_by: number | null}>;
  settlements: Array<{id: number; site_id: number; name: string; founder_id: number | null;
    founded_tick: number; completed_tick: number | null; charter_tick: number | null;
    work_units: number; region_id: number; residents: number[]}>;
  tasks: Array<{id: number; agent_id: number; kind: string; site_id: number;
    started_tick: number; due_tick: number; status: string}>;
};

export function FrontierPanel({ data }: { data: FrontierState | null | undefined }) {
  const [selected, setSelected] = useState(1);
  if (!data) return null;
  const site = data.sites.find(item => item.id === selected) || data.sites[0];
  const settlement = data.settlements.find(item => item.site_id === site.id);
  const tasks = data.tasks.filter(item => item.site_id === site.id && item.status === "pending");
  return <section className="frontier-panel" aria-label="Exploration and settlements">
    <header><p>RECORDED GEOGRAPHY · TICK {data.tick}</p><h2>Beyond Northstar</h2>
      <p>Explore the surrounding land. Build a settlement. Give it a name and a future.</p></header>
    <div className="frontier-layout">
      <div className="frontier-grid" role="group" aria-label="Surrounding map">
        {[...data.sites].sort((a, b) => a.y - b.y || a.x - b.x).map(item => {
          const town = data.settlements.find(s => s.site_id === item.id);
          return <button key={item.id} aria-pressed={site.id === item.id} onClick={() => setSelected(item.id)}
            className={item.discovered_tick === null ? "unexplored" : "discovered"}>
            <small>{item.x}, {item.y}</small><strong>{town?.name || `Site ${item.id}`}</strong>
            <span>{item.terrain || "Unexplored"}</span>
            {town && <small>{town.completed_tick === null ? `Building ${town.work_units}/${data.required_work}` : `${town.residents.length} residents`}</small>}
          </button>;
        })}
      </div>
      <article className="frontier-detail" aria-live="polite">
        <h3>{settlement?.name || `Site ${site.id}`}</h3>
        {site.discovered_tick === null ? <p>Terrain and resources will be revealed by a completed expedition.</p> : <>
          <p>{site.resource} · Space for {site.capacity} residents</p>
          <p>Recorded at tick {site.discovered_tick}{site.discovered_by ? ` by agent ${site.discovered_by}` : " when geography was established"}.</p>
        </>}
        {settlement && <><p>{settlement.founder_id ? `Founded by agent ${settlement.founder_id}` : "Starting community"} · tick {settlement.founded_tick}</p>
          <p>{settlement.completed_tick === null ? `Construction: ${settlement.work_units} of ${data.required_work} work units` : `Construction complete · ${settlement.residents.length} residents`}</p>
          <p>{settlement.charter_tick === null ? "Settlement within Northstar; three residents and a majority vote can establish a region." : `Region established at tick ${settlement.charter_tick}`}</p></>}
        {tasks.map(task => <p key={task.id}>Agent {task.agent_id}: {task.kind.replaceAll("_", " ")} · due tick {task.due_tick}</p>)}
        <p>Citizens choose these actions through their action catalog. Supplies cost money; travel and building take time.</p>
      </article>
    </div>
  </section>;
}
