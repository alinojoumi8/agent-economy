import { lazy, Suspense, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useParams } from 'react-router';
import { useObserverViewState, projectionScopeParams } from '../app/observerViewState';
import { projectionApi, workspaceApi } from '../app/api';
import { BanksPanel, FirmsPanel, InstitutionsPanel } from '../components/WorldPanels';
import { OraclePanel, CalibrationPanel, CostPanel } from '../components/OracleAndCost';
import { AcceptancePanel } from '../components/AcceptancePanel';
import { ReplayModal } from '../components/ReplayModal';

const MacroOverview=lazy(()=>import('../components/MacroOverview'));
const ENDPOINTS={
  economy:{banks:'/api/banks',firms:'/api/firms',institutions:'/api/institutions',metrics:'/api/metrics'},
  tools:{cost:'/api/cost',oracle:'/api/oracle/predictions',acceptance:'/api/acceptance/status',calibration:'/api/oracle/calibration?scope=run',calibrationAll:'/api/oracle/calibration?scope=all'},
};
export function CityOperationsWorkspace({kind='tools'}) {
  const {runId}=useParams();
  const [state]=useObserverViewState();
  const [replay,setReplay]=useState(false);
  const [actionError,setActionError]=useState('');
  const historical=state.tick!=='live';
  const query=useQuery({
    queryKey:['city-operations',runId,state.fork,state.tick,kind],enabled:!historical,retry:false,
    refetchInterval:kind==='economy'?5000:15000,
    queryFn:async ({signal})=>{
      const frame=await projectionApi(`/api/v2/snapshot?${projectionScopeParams(state)}&domains=summary`,signal);
      if(frame.run_id!==runId)throw new Error('The current server belongs to a different run.');
      const status=await workspaceApi('/api/run/status',{signal});
      if(status.run_id!==runId)throw new Error('Run changed while reading operator data.');
      const entries=await Promise.all(Object.entries(ENDPOINTS[kind]).map(async ([key,path])=>[key,await workspaceApi(path,{signal})]));
      return {status,...Object.fromEntries(entries)};
    },
  });
  async function act(path,body={}) {
    if(historical||query.isError||!query.data)throw new Error('Current run data is unavailable.');
    const status=await workspaceApi('/api/run/status');
    if(status.run_id!==runId)throw new Error('The current run changed.');
    const result=await workspaceApi(path,{method:'POST',body:JSON.stringify(body)});
    await query.refetch();return result;
  }
  if(historical)return <p className="city-capability-note">These operator summaries describe the current run only and are hidden while inspecting day {state.tick}. Use Businesses & banks and Markets for the public evidence available at that day, or return to Live.</p>;
  if(query.isPending)return <p role="status">Reading {kind==='economy'?'economic':'operator'} records…</p>;
  if(query.isError)return <p role="alert">{query.error.message} <button onClick={()=>query.refetch()}>Retry</button></p>;
  const data=query.data;
  return <section className="city-operator-panels">
    <p className="city-capability-note">Current operator snapshot · day {data.status.tick}{data.status.active_tick>data.status.tick?` · day ${data.status.active_tick} is in progress`:''}. Live balance sheets and operations are separate from the committed-day activity feed.</p>
    {kind==='economy'?<>
      <Suspense fallback={<p role="status">Loading recorded metrics…</p>}><MacroOverview metrics={data.metrics}/></Suspense>
      <div className="city-financial-grid"><BanksPanel banks={data.banks}/><FirmsPanel firms={data.firms}/><InstitutionsPanel institutions={data.institutions}/></div>
    </>:<>
      <div className="city-context-actions"><button className="button" onClick={()=>setReplay(true)}>Replay viewer</button><button className="button" onClick={()=>{setActionError('');act('/api/report').catch(error=>setActionError(error.message));}}>Generate report</button></div>
      {actionError&&<p role="alert">{actionError}</p>}
      <OraclePanel oracle={data.oracle} act={act}/>
      <CostPanel cost={data.cost} readiness={data.status.provider_readiness}/>
      <CalibrationPanel calibration={{run:data.calibration,all:data.calibrationAll,errors:[]}}/>
      <AcceptancePanel acceptance={data.acceptance}/>
      {replay&&<ReplayModal onClose={()=>setReplay(false)}/>}
    </>}
  </section>;
}
