import { useInfiniteQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { useParams, useSearchParams } from 'react-router';
import { projectionApi } from '../app/api';
import { useObserverViewState, projectionScopeParams } from '../app/observerViewState';
import { NewsCommunicationsWorkspace } from './NewsCommunicationsWorkspace';

function RecordedInformation({kind}:{kind:'news'|'conversations'}) {
  const {runId}=useParams();
  const [state]=useObserverViewState();
  const client=useQueryClient();
  const queryKey=['world-os',runId,state.fork,'city-information',kind,state.tick];
  const query=useInfiniteQuery({
    queryKey,initialPageParam:null as {before:number;tick:number}|null,retry:false,staleTime:Infinity,
    queryFn:async ({pageParam,signal})=>{
      const params=projectionScopeParams({...state,tick:pageParam?String(pageParam.tick):state.tick});
      params.set('limit','30');if(pageParam)params.set('before_id',String(pageParam.before));
      const frame=await projectionApi<any>(`/api/v2/city/${kind}?${params}`,signal);
      if(frame.run_id!==runId || (state.fork!==null&&frame.fork_id!==state.fork)
        || (state.tick!=='live'&&String(frame.tick)!==state.tick))throw new Error('Information belongs to a different City context.');
      return frame;
    },
    getNextPageParam:last=>last.data.next_before_id?{before:last.data.next_before_id,tick:last.tick}:undefined,
  });
  const rows=query.data?.pages.flatMap(page=>page.data.items)||[];
  return <section className="city-recorded-information" aria-label={kind==='news'?'City newsroom':'Recorded public conversations'}>
    <header><h3>{kind==='news'?'Newsroom':'Public conversations'}</h3><span>Day {query.data?.pages[0]?.tick??'…'}</span>{state.tick==='live'&&<button disabled={query.isFetching} onClick={()=>client.resetQueries({queryKey,exact:true})}>Refresh day</button>}</header>
    {query.isPending&&<p role="status">Reading stored {kind}…</p>}
    {query.isError&&<p role="alert">{query.error.message}</p>}
    {!query.isPending&&!query.isError&&!rows.length&&<p>No {kind==='news'?'news stories':'public conversations'} recorded on this day.</p>}
    {rows.map((row:any)=><article key={row.id}>{kind==='news'?<>
      <small>{row.outlet_name||'Newsroom'} · day {row.tick}{row.numeric_claims_redacted?' · unsupported numeric claims removed':''}</small><h4>{row.headline}</h4><p>{row.body}</p>
    </>:<><h4>{row.topic||`Conversation #${row.id}`}</h4>{row.messages.map((message:any,index:number)=><p key={index}><strong>{message.name}: </strong>{message.text}{message.text_truncated?'… [stored text truncated]':''}</p>)}{row.messages_truncated&&<p>Showing the first 64 messages.</p>}</>}</article>)}
    {query.hasNextPage&&<button disabled={query.isFetchingNextPage} onClick={()=>query.fetchNextPage()}>Load more {kind}</button>}
  </section>;
}
export function CityInformationPanel() {
  const {threadId}=useParams();
  const [params]=useSearchParams();
  const requested=Boolean(threadId)||['agent','truth'].includes(params.get('view')||'');
  const [threadsOpen,setThreadsOpen]=useState(requested);
  useEffect(()=>{if(requested)setThreadsOpen(true);},[requested]);
  return <><div className="city-information-grid"><RecordedInformation kind="conversations"/><RecordedInformation kind="news"/></div><details className="city-secondary" open={threadsOpen} onToggle={event=>setThreadsOpen(event.currentTarget.open)}><summary>Authorized communication threads</summary><NewsCommunicationsWorkspace/></details></>;
}
