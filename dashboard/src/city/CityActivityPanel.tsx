import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useSearchParams } from 'react-router';
import { projectionApi } from '../app/api';
import { validateActivity } from '../app/cityProjection.js';
import { projectionScopeParams, parseObserverViewState } from '../app/observerViewState';
import { cityEvidenceParams } from '../app/cityNavigation.js';

export type ActivityCard = {
  id:number; tick:number; kind:string; title:string; detail:string; category:string; outcome:string;
  actor_ids:number[]; actors:Array<{id:number;name:string}>; firm_id:number|null; firm_name?:string|null;
};
export type ActivityDay = {
  tick:number; through_id:number; total:number; day_total:number; changed_agents:number;
  offset:number; limit:number; next_offset:number|null; items:ActivityCard[];
  counts:Record<string,number>; categories:Record<string,number>;
  actors:Array<{id:number;name:string}>; actor_activity:Array<{agent_id:number;event:ActivityCard}>;
};
export function useCityActivity(map:any, base:any) {
  const [params] = useSearchParams();
  const category = params.get('activity') || 'all';
  const actor = /^\d+$/.test(params.get('actor') || '') ? params.get('actor') : null;
  const scope = `${map?.snapshot_version}:${base?.data.through_id}:${category}:${actor}`;
  const [page,setPage] = useState({scope:'',offset:0});
  const offset = page.scope === scope ? page.offset : 0;
  const query = useQuery({
    queryKey:['city-activity',map?.run_id,map?.fork_id,map?.tick,scope,offset],
    enabled:Boolean(map && base), retry:false, staleTime:Infinity,
    initialData:category==='all' && !actor && offset===0 ? base : undefined,
    queryFn:async ({signal}) => {
      const q = projectionScopeParams({tick:String(map.tick),fork:map.fork_id});
      q.set('category',category); q.set('offset',String(offset)); q.set('limit','40');
      q.set('through_id',String(base.data.through_id));
      if(actor) q.set('actor_id',actor);
      const frame=validateActivity(await projectionApi(`/api/v2/city/activity?${q}`,signal),map);
      if(frame.data.through_id!==base.data.through_id) throw new Error('The activity page changed its evidence boundary. Refresh the city.');
      return frame;
    },
  });
  return { ...query, category, actor, offset, setOffset:(offset:number)=>setPage({scope,offset}) };
}

export function CityActivityPanel({activity,runId,tick,onSelect}: {
  activity:ReturnType<typeof useCityActivity>;runId:string;tick:string;onSelect:(patch:any)=>void;
}) {
  const [params,setParams] = useSearchParams();
  const day = activity.data?.data as ActivityDay|undefined;
  const setFilter=(key:string,value:string)=>{const next=new URLSearchParams(params);if(value && value!=='all')next.set(key,value);else next.delete(key);setParams(next);};
  const evidence=(event:ActivityCard)=>{const q=cityEvidenceParams(parseObserverViewState(params));q.set('event',String(event.id));q.set('tick',String(event.tick));return `/runs/${encodeURIComponent(runId)}/investigations?${q}`;};
  return <section className="city-activity" aria-label="City activity">
    <header><div><p className="world-os-kicker">Recorded activity</p><h3>What agents did</h3></div><span>{day ? `Day ${day.tick}` : 'Loading day…'}{tick==='live'?' · latest committed':''}</span></header>
    {tick==='live'&&day&&<button className="city-pin-day" onClick={()=>onSelect({tick:String(day.tick)})}>Inspect this day</button>}
    {day && <><div className="city-activity-totals" aria-label="Day activity totals">
      <strong>{day.total.toLocaleString()} events</strong><span>{day.changed_agents} agents</span>
      {Object.entries(day.counts).filter(([,count])=>count>0).map(([state,count])=><span key={state} className={`city-outcome city-outcome--${state}`}>{count} {state}</span>)}
    </div><p className="city-activity-note">Counts cover the selected day{activity.category!=='all'||activity.actor?' and filters':''}. Pending means proposed, queued or in progress; completed requires a recorded outcome.</p></>}
    <div className="city-activity-filters">
      <label>Activity<select aria-label="Activity" value={activity.category} onChange={e=>setFilter('activity',e.target.value)}>{['all','work','markets','learning','business','construction','travel','communications','external','civic','other'].map(c=><option key={c} value={c}>{c==='all'?'All activity':c[0].toUpperCase()+c.slice(1)}</option>)}</select></label>
      <label>Agent<select aria-label="Agent" value={activity.actor || ''} onChange={e=>setFilter('actor',e.target.value)}><option value="">All agents</option>{day?.actors.map(a=><option key={a.id} value={a.id}>{a.name}</option>)}</select></label>
      {(activity.actor || activity.category!=='all')&&<button onClick={()=>{const next=new URLSearchParams(params);next.delete('actor');next.delete('activity');setParams(next);}}>Clear filters</button>}
    </div>
    {activity.isPending && <p role="status">Reading the day’s activity…</p>}
    {activity.error && <p role="alert">Activity unavailable: {activity.error.message} <button onClick={()=>activity.refetch()}>Retry</button></p>}
    {day && !day.total && <p className="city-activity-empty">{activity.actor||activity.category!=='all'?'No recorded events match these filters on this day.':'No events have been recorded on this day.'}</p>}
    <ol className="city-activity-events">{day?.items.map(event=><li key={event.id}>
      <div><span className={`city-outcome city-outcome--${event.outcome}`}>{event.outcome}</span><small>#{event.id} · {event.kind.replaceAll('_',' ')}</small></div>
      <strong>{event.title}</strong>{event.detail&&<p>{event.detail}</p>}
      <footer>{event.actors.map(actor=><button key={actor.id} onClick={()=>onSelect({agent:actor.id,population:'all',q:'',layer:'all'})}>Locate {actor.name}</button>)}{event.firm_id&&<button onClick={()=>onSelect({firm:event.firm_id,q:'',layer:'all'})}>Locate {event.firm_name||`business #${event.firm_id}`}</button>}<Link to={evidence(event)}>Evidence ↗</Link></footer>
    </li>)}</ol>
    {day && day.total>0 && <nav className="city-activity-pages" aria-label="Activity pages"><button disabled={activity.offset===0} onClick={()=>activity.setOffset(Math.max(0,activity.offset-40))}>Previous</button><span>{activity.offset+1}–{activity.offset+day.items.length} of {day.total}</span><button disabled={day.next_offset===null} onClick={()=>day.next_offset!==null&&activity.setOffset(day.next_offset)}>Next</button></nav>}
  </section>;
}
