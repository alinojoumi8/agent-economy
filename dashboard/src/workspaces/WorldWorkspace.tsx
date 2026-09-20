import { lazy, Suspense, useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useNavigate, useSearchParams } from 'react-router';
import { projectionApi, workspaceApi } from '../app/api';
import { cityActivityMarkers, cityRuntimeMatches, loadCityConversations, loadCityProjection } from '../app/cityProjection.js';
import { cityEvidenceParams, cityWorkspaceHref } from '../app/cityNavigation.js';
import { parseObserverViewState } from '../app/observerViewState';
import { CivicCity } from '../components/CivicCity';
import { useModalFocus } from '../components/useModalFocus';
import { CityActivityPanel, useCityActivity } from '../city/CityActivityPanel';
import { UrbanDevelopment, type CityProposal } from '../city/UrbanDevelopment';
import { CityControls } from '../city/CityControls';
import { FrontierPanel, type FrontierState } from './FrontierPanel';
import { useWorkspaceProjection } from './workspaceShared';
import '../city/city-workspace.css';

const CityViewport = lazy(() => import('../city/CityViewport'));
const TERMINAL = new Set(['completed','failed','finished','halted','stopped']);
const PANELS = [
  ['economy','Economy'],
  ['people','People'],['organizations','Businesses & banks'],['markets','Markets'],
  ['politics-law','Law & civic life'],['news-communications','Conversations & news'],
  ['investigations','Evidence'],
];

function CityDetailPanel({title,children,onClose}:{title:string;children:ReactNode;onClose:()=>void}) {
  const ref=useModalFocus({onEscape:onClose});
  return <div className="city-panel-backdrop" onMouseDown={e=>{if(e.currentTarget===e.target)onClose();}}>
    <section className="city-detail-panel" role="dialog" aria-modal="true" aria-label={title+' in City'} ref={ref} tabIndex={-1}>
      <header className="city-panel-heading"><div><p className="world-os-kicker">City details</p><h2>{title}</h2></div><button onClick={onClose}>Back to City · Esc</button></header>
      {children}
    </section>
  </div>;
}

export function WorldWorkspace({panel,children}:{panel?:string;children?:ReactNode}) {
  const projection=useWorkspaceProjection<{frontier?:FrontierState}>('workspace.world','/api/v2/workspaces/world');
  const {observerState,runId}=projection;
  // Detail routes have their own view/filter parameters. Keep the underlying
  // City on its bookmark so opening a panel does not dispose the 3D renderer.
  const cityState=useMemo(()=>panel?{
    ...parseObserverViewState(new URLSearchParams(observerState.city||'')),
    fork:observerState.fork,tick:observerState.tick,event:observerState.event,
  }:observerState,[panel,observerState]);
  const updateCity=useCallback<typeof projection.setObserverState>((...args)=>{
    if(!panel)projection.setObserverState(...args);
  },[panel,projection.setObserverState]);
  const navigate=useNavigate();
  const [params,setParams]=useSearchParams();
  useEffect(()=>{if(!panel&&params.has('region')){const next=new URLSearchParams(params);next.delete('region');setParams(next,{replace:true});}},[panel,params,setParams]);
  const [proposal,setProposal]=useState<CityProposal>(null);
  const tick=observerState.tick;
  const city=useQuery({
    queryKey:['world-os',runId,observerState.fork,'world-city',tick,cityState.population],
    queryFn:({signal})=>loadCityProjection({...cityState,runId},path=>projectionApi(path,signal)),
    retry:false,
    refetchInterval:query=>tick==='live'&&!TERMINAL.has(String(query.state.data?.overview.data.summary?.status||'').toLowerCase())?3000:false,
  });
  const frame=!city.error?city.data?.envelope:null;
  const summary=city.data?.overview.data.summary;
  const activity=useCityActivity(frame,!city.error?city.data?.activity:null);
  const markers=cityActivityMarkers(activity.data);
  const conversations=useQuery({
    queryKey:['world-os',runId,observerState.fork,'city-conversations',frame?.snapshot_version],
    queryFn:({signal})=>loadCityConversations(frame,path=>projectionApi(path,signal)),
    enabled:cityState.view==='recorded'&&Boolean(frame),retry:false,
  });
  const pollRuntime=tick==='live'&&cityState.view!=='recorded'&&Boolean(frame)&&!TERMINAL.has(String(summary?.status));
  const runtime=useQuery({
    queryKey:['llm-runtime',runId,observerState.fork],
    queryFn:({signal})=>workspaceApi<any>('/api/llm/runtime',{signal}),
    enabled:pollRuntime,retry:false,refetchInterval:pollRuntime?2000:false,
  });
  const currentRuntime=pollRuntime&&!runtime.error&&cityRuntimeMatches(runtime.data,frame,tick)?runtime.data:null;
  const stale=city.isError||projection.transport.status!=='live';
  const href=(path:string)=>'/runs/'+encodeURIComponent(runId)+'/'+path+'?'+cityEvidenceParams(observerState);
  // Dismiss the modal with its URL change; a deferred transition can otherwise
  // leave the inert City and focus trap mounted after history already moved.
  const closePanel=()=>navigate(cityWorkspaceHref(runId,observerState),{flushSync:true});
  const actorScope=activity.category!=='all'||activity.actor
    ? (activity.data?.data.actor_activity||[]).map((row:any)=>row.agent_id) : null;
  return <section className="world-os-world-workspace city-home">
    <div inert={panel?true:undefined} aria-hidden={panel?true:undefined}>
    <nav className="city-context-actions" aria-label="Explore City details">
      {PANELS.map(([path,label])=><Link key={path} to={href(path)}>{label}</Link>)}
    </nav>
    <div className="city-stage">
      <CivicCity
        agents={frame?city.data?.agents:[]} firms={frame?city.data?.firms:[]} events={markers}
        map={frame?city.data?.map:null} frame={frame} civic={frame?city.data?.civic:null}
        runtime={currentRuntime} runId={runId} tick={tick} phase={summary?.phase} status={summary?.status}
        loading={city.isLoading} error={city.error instanceof Error?city.error.message:''}
        connected={projection.transport.status==='live'} historical={tick!=='live'}
        variant="world-os" observerState={cityState} onObserverStateChange={updateCity} suspendSelectionRepair={Boolean(panel)}
        hideActivityDock activityActorIds={actorScope} activityDay={activity.data?.data}
        recordedAvailable={Boolean(city.data?.map.presence?.length)}
        conversations={!conversations.error&&conversations.data?.mapSnapshot===frame?.snapshot_version?conversations.data?.data:null}
        conversationsLoading={conversations.isLoading} conversationsError={conversations.error instanceof Error?conversations.error.message:''}
        lineage={frame?{semantics:frame.semantics_version,projection:frame.projection_version,policy:frame.policy_version}:null}
        render3d={({visibleAgents,selected}:any)=><Suspense fallback={<p role="status">Loading 3D city…</p>}>
          <CityViewport embedded envelope={frame} snapshot={activity.data} runId={runId} tick={tick}
            status={summary?.status||''} stale={stale} loading={city.isLoading}
            error={city.error instanceof Error?city.error.message:''} visibleAgentIds={visibleAgents.map((a:any)=>Number(a.id))}
            selectedAgentId={selected?.id??null} onSelect={updateCity} followId={cityState.follow} proposal={proposal} observerState={cityState}
            onFallback={()=>updateCity({view:'atlas'})}/>
        </Suspense>}
      />
      <CityActivityPanel activity={activity} runId={runId} tick={tick} onSelect={projection.setObserverState}/>
    </div>
    <details className="city-secondary"><summary>Regions & settlements</summary>
      {projection.loading?<p role="status">Reading regions…</p>:projection.error?<p role="alert">{projection.error.message}</p>:<FrontierPanel data={projection.data?.frontier}/>}
    </details>
    <details className="city-secondary"><summary>Construction & citizen actions</summary>
      <UrbanDevelopment runId={runId} tick={tick} fork={observerState.fork} stale={stale} onPreview={setProposal}/>
      {tick==='live'?<CityControls showClock={false} runId={runId} selectedAgentId={observerState.agent} stale={stale}/>:<p>Historical inspection is read-only. Return to Live to use citizen actions.</p>}
    </details>
    <details className="city-secondary"><summary>Provider diagnostics</summary>
      {tick!=='live'?<p>Current provider activity is unavailable in historical views.</p>:runtime.error?<p role="alert">Runtime telemetry is unavailable.</p>:currentRuntime?<>
        <p>{currentRuntime.global.in_flight} calls in flight · {currentRuntime.global.queue_depth} queued. These are live provider requests, separate from recorded agent actions.</p>
        {(currentRuntime.providers||[]).map((lane:any)=><p key={lane.provider}>{lane.provider}: {lane.in_flight}/{lane.capacity} active · {lane.queue_depth} queued · {lane.failures} failures</p>)}
      </>:<p>{TERMINAL.has(String(summary?.status))?'This run has ended. Current provider activity is unavailable.':runtime.data?"Runtime telemetry does not match this city's run and fork context.":'Live provider telemetry is unavailable for this frame.'}</p>}
    </details>
    </div>
    {panel&&<CityDetailPanel title={panel} onClose={closePanel}>{children}</CityDetailPanel>}
  </section>;
}
