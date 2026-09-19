import { useQuery } from '@tanstack/react-query';
import { Navigate, useLocation } from 'react-router';
import { workspaceApi } from './api';

export function LocalCityHome({destination='world'}:{destination?:string}) {
  const location=useLocation();
  const query=useQuery({queryKey:['local-city-home'],queryFn:({signal})=>workspaceApi<{run_id:string}>('/api/run/status',{signal}),retry:false});
  const search=new URLSearchParams(location.search);
  if(destination==='world'&&!search.has('population'))search.set('population','all');
  if(query.data?.run_id) return <Navigate to={'/runs/'+encodeURIComponent(query.data.run_id)+'/'+destination+'?'+search+location.hash} replace/>;
  return <main className="city-boot"><h1>Agent Economy · City</h1>{query.isPending?<p role="status">Identifying the current run…</p>:<><p role="alert">The current run could not be identified. {query.error?.message}</p><button onClick={()=>query.refetch()}>Retry</button></>}</main>;
}
