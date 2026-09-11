import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { workspaceApi } from '../app/api';
import { CityRunControls } from './CityRunControls';
import { ParticipantPanel } from '../components/ParticipantPanel';

type Participant={enabled:boolean;active:boolean;running:boolean;completed_tick:number;controlled_agent?:{id:number;name:string};queued_action?:{action:unknown}|null;action_catalog?:Array<{type:string;enabled?:boolean}>};
export function CityControls({runId,selectedAgentId,stale}:{runId:string;selectedAgentId:number|null;stale:boolean}){
  const client=useQueryClient(),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  const query=useQuery({queryKey:['city-participant',runId],queryFn:({signal})=>workspaceApi<Participant>('/api/participant',{signal}),refetchInterval:3000});
  async function act(path:string,body:unknown){
    setError('');setBusy(true);
    try{await workspaceApi(path,{method:'POST',body:JSON.stringify(body)});await client.invalidateQueries({queryKey:['city-participant',runId]});}
    finally{setBusy(false);}
  }
  const participant=query.data;
  if(query.isError)return <><CityRunControls runId={runId} stale={true}/><p className="city3d-control-note" role="alert">Citizen controls are unavailable. Reconnecting to the run…</p></>;
  if(!participant?.enabled)return <><CityRunControls runId={runId} stale={stale}/><p className="city3d-control-note">Observer mode. Civic decisions require a participant-enabled local run.</p></>;
  return <section className="city3d-controls" aria-label="Play as a citizen">
    <CityRunControls runId={runId} stale={stale} participantActive={participant.active} hasQueuedAction={!!participant.queued_action}/><header><div><p className="city3d-kicker">CIVIC DECISIONS</p><h3>Act through a real citizen</h3></div>
      <button disabled={busy||stale||participant.running||selectedAgentId===null||participant.controlled_agent?.id===selectedAgentId}
        onClick={()=>act('/api/participant/control',{agent_id:selectedAgentId,expected_tick:participant.completed_tick}).catch(e=>setError(e instanceof Error?e.message:'Control rejected'))}>Control selected citizen</button></header>
    {error&&<p role="alert">{error}</p>}
    <p className="city3d-note">Queue one action for the next simulation tick. The engine checks authority, funds and eligibility; a queued proposal is not an accepted outcome.</p>
    <fieldset disabled={busy||stale}><ParticipantPanel participant={{...participant,action_catalog:participant.action_catalog?.filter(d=>!['construct_building','cancel_construction','demolish_building'].includes(d.type))}} act={act}/></fieldset>
  </section>;
}
