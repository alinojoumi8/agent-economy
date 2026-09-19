import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useRef, useState } from 'react';
import { workspaceApi } from '../app/api';
import { inferenceMode } from '../lib/inferenceMode.js';

type RunStatus={run_id:string;status:string;tick:number;running:boolean;remaining_ticks?:number|null;provider_readiness?:any};
export function CityRunControls({runId,stale,participantActive=false,hasQueuedAction=false}:{runId:string;stale:boolean;participantActive?:boolean;hasQueuedAction?:boolean}){
  const client=useQueryClient(),[busy,setBusy]=useState(''),[error,setError]=useState('');
  const pending=useRef(new Set<string>());
  const query=useQuery({queryKey:['city-run-status',runId],queryFn:({signal})=>workspaceApi<RunStatus>('/api/run/status',{signal}),refetchInterval:1000});
  const status=query.data;
  const participant=useQuery({queryKey:['city-participant',runId],queryFn:({signal})=>workspaceApi<{active:boolean;queued_action?:unknown}>('/api/participant',{signal}),refetchInterval:3000,retry:false});
  participantActive=participantActive||Boolean(participant.data?.active);
  hasQueuedAction=hasQueuedAction||Boolean(participant.data?.queued_action);
  const unavailable=!status||status.run_id!==runId||stale||query.isError||participant.isPending||participant.isError;
  const mode=inferenceMode(status?.provider_readiness);
  const running=Boolean(status?.running||status?.status==='running'||busy==='step'||busy==='start');
  const terminal=status&&!['created','paused','running','active'].includes(status.status);
  async function control(action:'start'|'pause'|'step'|'stop'){
    if(unavailable||pending.current.has(action))return;
    pending.current.add(action);
    setBusy(action);setError('');
    try{await workspaceApi(`/api/run/${action}`,{method:'POST',body:'{}'});await Promise.all([
      client.invalidateQueries({queryKey:['world-os']}),client.invalidateQueries({queryKey:['city-run-status',runId]}),client.invalidateQueries({queryKey:['city-participant',runId]}),
    ]);}catch(e){setError(e instanceof Error?e.message:'Run command rejected');}finally{pending.current.delete(action);setBusy([...pending.current].at(-1)||'');}
  }
  return <div className="city3d-run-controls" role="group" aria-label="Simulation clock">
    <strong>Day {status?.tick??'—'} · {status?.status??'loading'}</strong>
    <span title={mode.title}>Native agents: {mode.label}</span>
    <button disabled={unavailable||terminal||running||!!busy||status?.remaining_ticks===0||(participantActive&&!hasQueuedAction)} onClick={()=>control('step')}>Advance one tick</button>
    <button disabled={unavailable||terminal||running||!!busy||status?.remaining_ticks===0||participantActive} onClick={()=>control('start')}>Run</button>
    <button disabled={unavailable||!running||busy==='pause'||busy==='stop'} onClick={()=>control('pause')}>Pause</button>
    <button disabled={unavailable||terminal||busy==='stop'} onClick={()=>control('stop')} title="Finish this run and generate its report">{busy==='stop'?'Stopping…':'Stop + report'}</button>
    {status&&status.run_id!==runId&&<span role="alert">This address names a different run. Controls are disabled.</span>}
    {query.isError&&<span role="alert">Run status unavailable.</span>}
    {participantActive&&<span>{hasQueuedAction?'Citizen action queued. Advance one tick to resolve it.':'Queue a citizen action (including Do nothing) before advancing.'} Release the citizen to use continuous Run.</span>}
    {error&&<p role="alert">{error}</p>}
  </div>;
}
