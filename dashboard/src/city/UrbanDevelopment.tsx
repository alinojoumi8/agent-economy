import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router';
import { projectionApi, workspaceApi } from '../app/api';

type Parcel={id:number;parcel_key:string;region_id:number;x:number;y:number;zone_key:string;blocked:number;owner_firm_id:number|null};
type Project={id:number;firm_id:number;parcel_id:number;status:string;requested_tick:number;completion_tick:number;cost_cents:number;currency_code:string;capacity:number;place_id:number|null;created_event_id:number|null;outcome_event_id:number|null};
type Urban={enabled:boolean;catalog:Array<{template_key:string;name:string;cost_cents:number;capacity:number;duration_ticks:number;zone_key:string}>;parcels:Parcel[];projects:Project[]};
type Descriptor={type:string;enabled:boolean;disabled_reason?:string;fields:Array<{name:string;kind:string;options?:Array<{value:number|string;label:string}>}>};
type Participant={enabled:boolean;active:boolean;running:boolean;completed_tick:number;controlled_agent?:{id:number;name:string};action_catalog:Descriptor[]};
export type CityProposal={x:number;y:number;label:string}|null;
export function UrbanDevelopment({runId,tick,fork,stale,onPreview}:{runId:string;tick:string;fork:string|null;stale:boolean;onPreview:(proposal:CityProposal)=>void}){
  const client=useQueryClient(),[parcelId,setParcelId]=useState(''),[firmId,setFirmId]=useState('');
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('');
  const request=useRef({signature:'',key:''});
  const params=new URLSearchParams({tick});if(fork)params.set('fork_id',fork);
  const query=useQuery({queryKey:['world-os',runId,fork,'urban-development',tick],queryFn:({signal})=>projectionApi<Urban>(`/api/v2/urban-development?${params}`,signal),refetchInterval:tick==='live'?3000:false,retry:false});
  const participant=useQuery({queryKey:['city-participant',runId],queryFn:({signal})=>workspaceApi<Participant>('/api/participant',{signal}),enabled:tick==='live',refetchInterval:tick==='live'?3000:false});
  const data=query.data?.data;
  const descriptor=participant.data?.action_catalog?.find(d=>d.type==='construct_building');
  const firms=descriptor?.fields.find(f=>f.name==='firm_id')?.options||[];
  const permittedParcels=new Set((descriptor?.fields.find(f=>f.name==='parcel_id')?.options||[]).map(o=>Number(o.value)));
  const chosenFirm=firmId||String(firms[0]?.value||'');
  const parcel=data?.parcels?.find(p=>String(p.id)===parcelId)||null;
  const template=data?.catalog?.[0];
  const historical=tick!=='live';
  const disabled=historical||stale||busy||participant.isError||query.isError||!participant.data?.active||participant.data.running;
  useEffect(()=>{
    onPreview(parcel&&!historical?{x:parcel.x,y:parcel.y,label:`Proposed workplace on ${parcel.parcel_key}`} : null);
    return()=>onPreview(null);
  },[parcel?.id,parcel?.x,parcel?.y,historical,onPreview]);
  async function queue(type:string,payload:Record<string,unknown>){
    const state=participant.data;if(!state||disabled)return;
    const signature=JSON.stringify([state.controlled_agent?.id,state.completed_tick,type,payload]);
    if(request.current.signature!==signature)request.current={signature,key:crypto.randomUUID()};
    setBusy(true);setError('');setNotice('');
    try{
      await workspaceApi('/api/participant/action',{method:'POST',body:JSON.stringify({expected_tick:state.completed_tick,action:{type,...payload,request_key:request.current.key},reasoning:'City construction proposal'})});
      setNotice('Proposal queued. Advance one tick to let the engine validate and settle it.');
      await client.invalidateQueries({queryKey:['city-participant',runId]});
    }catch(e){setError(e instanceof Error?e.message:'Proposal rejected');}finally{setBusy(false);}
  }
  function allowed(type:string,id:number){const d=participant.data?.action_catalog?.find(d=>d.type===type);return d?.enabled!==false&&d?.fields.some(f=>f.name==='project_id'&&f.options?.some(o=>Number(o.value)===id));}
  const scope=new URLSearchParams();if(historical)scope.set('tick',tick);if(fork)scope.set('fork',fork);
  if(!data?.enabled)return null;
  return <section className="city3d-build" aria-label="City construction">
    <header><div><p className="city3d-kicker">BUILD THE CITY</p><h3>From a permit to a workplace</h3></div><span>{data.projects.filter(p=>p.status==='building').length} under construction · {data.projects.filter(p=>p.status==='completed').length} completed</span></header>
    {query.isError&&<p role="alert">Construction state is stale. Reconnecting; actions are disabled.</p>}
    <p className="city3d-note">A living founder with a permitted company can claim a vacant commercial parcel. The firm funds construction in escrow. Cancel before completion for a full refund; demolition returns no money.</p>
    {!historical&&<div className="city3d-build-form">
      <label>Funding company<select value={chosenFirm} onChange={e=>setFirmId(e.target.value)} disabled={disabled||!firms.length}><option value="">Choose a permitted company</option>{firms.map(f=><option key={f.value} value={f.value}>{f.label}</option>)}</select></label>
      <label>Parcel preview<select value={parcelId} onChange={e=>setParcelId(e.target.value)}><option value="">Select a parcel</option>{data.parcels.map(p=><option key={p.id} value={p.id}>{p.parcel_key} · {p.blocked?'blocked':p.owner_firm_id?'occupied':p.zone_key}</option>)}</select></label>
      <div className="city3d-quote"><strong>{template?.name}</strong><span>{template?.cost_cents.toLocaleString()} local currency cents · {template?.duration_ticks} ticks · capacity {template?.capacity}</span></div>
      <button disabled={disabled||!parcel||!chosenFirm||!permittedParcels.has(parcel.id)||descriptor?.enabled===false||!template}
        onClick={()=>queue('construct_building',{firm_id:Number(chosenFirm),parcel_id:parcel!.id,template_key:template!.template_key})}>Propose construction</button>
      {parcel&&<p className="city3d-note">Outline is a proposal preview. It confers no ownership or building; the server checks the company’s region, zoning, permit and funds.</p>}
      {!firms.length&&<p className="city3d-note">Control an eligible citizen, apply for a business permit, attend the appointment, and found a company using the civic actions below. Construction becomes available to its founder.</p>}
    </div>}
    {error&&<p role="alert">{error}</p>}{notice&&<p role="status">{notice}</p>}
    <div className="city3d-projects"><table><caption>Authoritative construction projects · tick {query.data?.tick}</caption><thead><tr><th>Project / firm</th><th>State</th><th>Due tick</th><th>Evidence</th><th>Action</th></tr></thead>
      <tbody>{data.projects.map(project=>{const event=project.outcome_event_id||project.created_event_id;const qs=new URLSearchParams(scope);if(event)qs.set('event',String(event));return <tr key={project.id}><td>#{project.id} / firm {project.firm_id}</td><td>{project.status}</td><td>{project.completion_tick}</td><td>{event?<Link to={`/runs/${encodeURIComponent(runId)}/investigations?${qs}`}>Event #{event}</Link>:'No event reference'}</td><td>
        {project.status==='building'&&<button disabled={disabled||!allowed('cancel_construction',project.id)} onClick={()=>queue('cancel_construction',{project_id:project.id})}>Cancel · full refund</button>}
        {project.status==='completed'&&<button disabled={disabled||!allowed('demolish_building',project.id)} onClick={()=>queue('demolish_building',{project_id:project.id})}>Demolish · no refund</button>}
      </td></tr>;})}</tbody></table>{!data.projects.length&&<p>No construction projects at this tick.</p>}</div>
  </section>;
}
