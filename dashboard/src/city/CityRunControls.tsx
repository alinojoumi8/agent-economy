import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { workspaceApi } from '../app/api';

type RunStatus={status:string;tick:number;running:boolean;remaining_ticks?:number|null};
export function CityRunControls({runId,stale,participantActive=false,hasQueuedAction=false}:{runId:string;stale:boolean;participantActive?:boolean;hasQueuedAction?:boolean}){
  const client=useQueryClient(),[busy,setBusy]=useState(''),[error,setError]=useState('');
  const query=useQuery({queryKey:['city-run-status',runId],queryFn:({signal})=>workspaceApi<RunStatus>('/api/run/status',{signal}),refetchInterval:1000});
  const status=query.data;
  const running=Boolean(status?.running||status?.status==='running'||busy==='step'||busy==='start');
  const terminal=status&&!['created','paused','running','active'].includes(status.status);
  async function control(action:'start'|'pause'|'step'){
    setBusy(action);setError('');
    try{await workspaceApi(`/api/run/${action}`,{method:'POST',body:'{}'});await Promise.all([
      client.invalidateQueries({queryKey:['world-os']}),client.invalidateQueries({queryKey:['city-run-status',runId]}),client.invalidateQueries({queryKey:['city-participant',runId]}),
    ]);}catch(e){setError(e instanceof Error?e.message:'Run command rejected');}finally{setBusy('');}
  }
  return <div className="city3d-run-controls" role="group" aria-label="Simulation clock">
    <span>Simulation clock · tick {status?.tick??'—'}</span>
    <button disabled={!status||stale||query.isError||terminal||running||!!busy||status.remaining_ticks===0||(participantActive&&!hasQueuedAction)} onClick={()=>control('step')}>Advance one tick</button>
    <button disabled={!status||stale||query.isError||terminal||running||!!busy||status.remaining_ticks===0||participantActive} onClick={()=>control('start')}>Run</button>
    <button disabled={!running||busy==='pause'} onClick={()=>control('pause')}>Pause</button>
    {participantActive&&<span>{hasQueuedAction?'Citizen action queued. Advance one tick to resolve it.':'Queue a citizen action (including Do nothing) before advancing.'} Release the citizen to use continuous Run.</span>}
    {error&&<p role="alert">{error}</p>}
  </div>;
}
