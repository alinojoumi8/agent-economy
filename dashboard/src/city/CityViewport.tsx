import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import { CityScene, type SceneStats } from './CityScene';
import { activityForCity, projectCity, type CityInstance } from './cityProjection';
import { UrbanDevelopment, type CityProposal } from './UrbanDevelopment';
import { CityControls } from './CityControls';
import './city.css';

type Props={envelope:unknown;snapshot:unknown;runId:string;tick:string;status:string;stale:boolean;loading:boolean;error:string;onFallback:()=>void};
export default function CityViewport({envelope,snapshot,runId,tick,status,stale,loading,error,onFallback}:Props){
  const host=useRef<HTMLDivElement>(null),scene=useRef<CityScene|null>(null);
  const [params,setParams]=useSearchParams();
  const [graphicsError,setGraphicsError]=useState(''),[ready,setReady]=useState(false);
  const [layer,setLayer]=useState('all'),[region,setRegion]=useState('all'),[search,setSearch]=useState('');
  const preview=useCallback((proposal:CityProposal)=>scene.current?.preview(proposal),[]);
  const [stats,setStats]=useState<SceneStats|null>(null);
  const statsTime=useRef(0);
  const pickRef=useRef<(key:string)=>void>(()=>{});
  const parsed=useMemo(()=>{try{return {city:envelope?projectCity(envelope):null,error:''};}catch(e){return {city:null,error:e instanceof Error?e.message:'Invalid city data.'};}},[envelope]);
  const city=parsed.city;
  const selectedType=params.get('cityType')||'agent';
  const selectedId=Number(params.get('cityEntity')||params.get('agent'));
  const selected=city?.instances.find(i=>i.entityType===selectedType&&i.entityId===selectedId)||null;
  const visible=useMemo(()=>city?.instances.filter(i=>(layer==='all'||i.entityType===layer)&&(region==='all'||String(i.regionId)===region)
    &&(!search||`${i.name} ${i.entityType} ${i.entityId}`.toLowerCase().includes(search.toLowerCase())))||[],[city,layer,region,search]);
  const events=useMemo(()=>city?activityForCity(city,snapshot):[],[city,snapshot]);
  const historical=tick!=='live';
  const running=!historical&&!stale&&status==='running';
  pickRef.current=(key:string)=>{
    const item=city?.instances.find(i=>i.key===key);if(!item)return;
    const next=new URLSearchParams(params);next.set('cityType',item.entityType);next.set('cityEntity',String(item.entityId));
    if(item.entityType==='agent')next.set('agent',String(item.entityId));else next.delete('agent');
    setParams(next,{replace:true});
  };
  useEffect(()=>{
    if(!host.current)return;
    let instance:CityScene|undefined;
    try{
      instance=new CityScene(host.current,key=>pickRef.current(key),()=>setReady(true),setGraphicsError,value=>{
        if(performance.now()-statsTime.current>1000){statsTime.current=performance.now();setStats(value);}
      });
      scene.current=instance;
    }catch(e){setGraphicsError('3D graphics are unavailable on this device. The 2D atlas remains available.');}
    return()=>{instance?.dispose();scene.current=null;};
  },[]);
  useEffect(()=>{if(city)scene.current?.update(city,visible,selected?.key||null,events,running);else scene.current?.clear();},[city,visible,selected?.key,events,running]);
  const evidenceUrl=(item:CityInstance)=>{
    const scope=new URLSearchParams();if(params.get('fork'))scope.set('fork',params.get('fork')!);if(historical)scope.set('tick',tick);
    let path=item.entityType==='agent'?`people/${item.entityId}`:item.entityType==='firm'?`organizations/firm/${item.entityId}`:item.entityType==='bank'?`organizations/bank/${item.entityId}`:'world';
    if(item.entityType==='place')scope.set('place',String(item.entityId));
    return `/runs/${encodeURIComponent(runId)}/${path}?${scope}`;
  };
  const eventUrl=(id:number)=>{const q=new URLSearchParams();q.set('event',String(id));if(historical)q.set('tick',tick);if(params.get('fork'))q.set('fork',params.get('fork')!);return `/runs/${encodeURIComponent(runId)}/investigations?${q}`;};
  const failure=error||parsed.error||graphicsError;
  const camera=(action:Parameters<CityScene['cameraAction']>[0])=>scene.current?.cameraAction(action);
  return <section className="city3d" aria-label="Agent Economy 3D city">
    <header className="city3d-heading"><div><p>AGENT ECONOMY / CITY 3D</p><h2>A city with an economy.</h2></div>
      <div className="city3d-state"><strong>{historical?'Historical':stale?'Stale':status||'Connecting'}</strong><span>Tick {city?.envelope.tick??'—'} · {city?.instances.filter(i=>i.entityType==='agent').length??0} visible agents</span></div></header>
    <div className="city3d-toolbar" role="group" aria-label="City layers">
      <label>Show<select value={layer} onChange={e=>setLayer(e.target.value)}><option value="all">Everything</option><option value="place">Places</option><option value="firm">Businesses</option><option value="agent">Citizens</option><option value="bank">Banks</option></select></label>
      <label>District<select value={region} onChange={e=>{setRegion(e.target.value);if(e.target.value!=="all")scene.current?.focusRegion(Number(e.target.value));else camera("reset");}}><option value="all">All regions</option>{city?.regions.map(r=><option key={r.id} value={r.id}>{r.name}</option>)}</select></label>
      <label className="city3d-search">Find an entity<input aria-label="Search city" value={search} onChange={e=>setSearch(e.target.value)} placeholder="Name or ID" maxLength={100}/></label>
      <button onClick={()=>{setSearch('');setRegion('all');setLayer('all');camera('reset');}}>Reset view</button>
      {city?.instances.some(i=>i.provenance==='derived')&&<button onClick={()=>scene.current?.fitVisible(true)}>Find unlocated entities</button>}
    </div>
    <div className="city3d-layout">
      <div className="city3d-field">
        <div className="city3d-canvas" ref={host} data-testid="city-canvas" data-ready={ready?'true':'false'} aria-busy={!ready||loading}/>
        {(loading||!ready)&&!failure&&<div className="city3d-message" role="status">{loading?'Reading committed city state…':'Loading Blender city assets…'}</div>}
        {failure&&<div className="city3d-message" role="alert"><strong>{failure}</strong><button onClick={onFallback}>Use 2D atlas</button></div>}
        {!loading&&ready&&!failure&&!visible.length&&<div className="city3d-message" role="status">{city?.instances.length?'No entities match these filters.':'No city entities are available in this projection.'}</div>}
        <div className="city3d-camera" role="group" aria-label="Camera controls">
          <button onClick={()=>camera('in')} aria-label="Zoom in">+</button><button onClick={()=>camera('out')} aria-label="Zoom out">−</button>
          <button onClick={()=>camera('left')} aria-label="Rotate left">↶</button><button onClick={()=>camera('right')} aria-label="Rotate right">↷</button>
          <button onClick={()=>camera('north')} aria-label="Pan north">↑</button><button onClick={()=>camera('south')} aria-label="Pan south">↓</button>
          <button onClick={()=>camera('west')} aria-label="Pan west">←</button><button onClick={()=>camera('east')} aria-label="Pan east">→</button>
        </div>
        <div className="city3d-legend"><span><i className="city3d-blue"/>Selected</span><span><i className="city3d-green"/>Committed outcome</span><span><i className="city3d-red"/>Rejected / cancelled</span></div>
      </div>
      <aside className="city3d-inspector" aria-label="City entity inspector">
        <p className="city3d-kicker">SELECT & EXPLORE</p>
        {selected?<><h3>{selected.name}</h3><p>{selected.entityType} #{selected.entityId} · {selected.kind.replaceAll('_',' ')}</p>
          <dl><div><dt>Location</dt><dd>{selected.provenance==='observed'?'Recorded place coordinates':'Derived display slot'}</dd></div>
          <div><dt>Region</dt><dd>{city?.regions.find(r=>r.id===selected.regionId)?.name||'Unassigned'}</dd></div>
          {selected.status&&<div><dt>Recorded status</dt><dd>{selected.status}</dd></div>}
          {selected.capacity!==null&&<div><dt>Place capacity</dt><dd>{selected.capacity}</dd></div>}
          <div><dt>Committed tick</dt><dd>{city?.envelope.tick}</dd></div></dl>
          {historical&&<p className="city3d-note">Name, category and region metadata may reflect current records; this is not a complete historical reconstruction.</p>}
          <button onClick={()=>scene.current?.focus(selected.key)}>Focus camera</button>
          <Link className="city3d-evidence" to={evidenceUrl(selected)}>Open {selected.entityType==='agent'?'agent':selected.entityType==='firm'?'business':selected.entityType==='bank'?'bank':'place'} evidence ↗</Link>
          {!!events.filter(e=>e.targets.includes(selected.key)).length&&<div className="city3d-outcomes"><h4>Committed outcomes at this tick</h4>{events.filter(e=>e.targets.includes(selected.key)).map(e=><Link key={e.id} to={eventUrl(e.id)}>{e.kind.replaceAll('_',' ')} · #{e.id}</Link>)}</div>}
        </>:<><h3>Follow a citizen.<br/>Inspect a business.</h3><p>Select a building or choose an entity below. Every selection leads back to the simulation’s records.</p></>}
        <label className="city3d-list-label" htmlFor="city-entity-select">Entities · {visible.length}</label>
        <select id="city-entity-select" size={7} value={selected?.key||''} onChange={e=>pickRef.current(e.target.value)}>
          {visible.map(i=><option key={i.key} value={i.key}>{i.entityType==='agent'?'●':i.entityType==='firm'?'▣':'⌂'} {i.name} · {i.entityType} {i.entityId}</option>)}
        </select>
        {!!city?.clusters.length&&<p className="city3d-note">Aggregated residents: {city.clusters.map(c=>`${c.name}: ${c.count}`).join(' · ')}. Individual locations are not exposed.</p>}
      </aside>
    </div>
    <div className="city3d-notes">{city?.warnings.filter((_,index)=>historical||index<city.warnings.length-1).map(text=><p key={text}>{text}</p>)}
      <details><summary>Projection and rendering evidence</summary><code>{city?.envelope.snapshot_version||'No snapshot'} · layout {city?.city_layout_version} · {stats?`${stats.calls} draw calls / ${stats.triangles.toLocaleString()} triangles / ${stats.geometries} geometries / ${stats.textures} textures`: 'Renderer initializing'}</code></details>
    </div>
    <UrbanDevelopment runId={runId} tick={tick} fork={params.get('fork')} stale={stale} onPreview={preview}/>
    {!historical&&<CityControls runId={runId} selectedAgentId={selected?.entityType==='agent'?selected.entityId:null} stale={stale}/>}
  </section>;
}
