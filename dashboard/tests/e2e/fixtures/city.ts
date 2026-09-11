import type { Page } from '@playwright/test';
export async function installCityFixture(page:Page,{agents=300,places=100}:{agents?:number;places?:number}={}){
  await page.addInitScript(()=>{
    class Socket extends EventTarget{
      readyState=1;static OPEN=1;
      constructor(){super();queueMicrotask(()=>{this.dispatchEvent(new Event('open'));this.dispatchEvent(new MessageEvent('message',{data:JSON.stringify({type:'hello',run_id:'city-fixture',fork_id:null,tick:2,semantics_version:12,projection_version:1,policy_version:1,view_key:'public',event_cursor:9,status:'paused'})}));});}
      send(){} close(){this.readyState=3;}
    }
    Object.defineProperty(window,'WebSocket',{value:Socket});
  });
  await page.route('**/api/**',async route=>{
    const url=new URL(route.request().url()),path=url.pathname;
    const tick=url.searchParams.get('tick')==='1'?1:2;
    const base={run_id:'city-fixture',fork_id:url.searchParams.get('fork_id'),tick,semantics_version:12,projection_version:1,policy_version:1,view_key:'public',snapshot_version:`s12-t${tick}-e9-fixture`,event_cursor:9};
    if(path==='/api/v2/mode')return route.fulfill({json:{mode:'local',hosted:false,navigation:{run_id:'city-fixture'}}});
    if(path==='/api/participant')return route.fulfill({json:{enabled:false,active:false}});
    if(path==='/api/run/status')return route.fulfill({json:{status:'paused',tick,running:false}});
    if(path==='/api/llm/runtime')return route.fulfill({json:{live_only:false,activity_revision:0,active_agents:[],global:{in_flight:0,capacity:2,queue_depth:0,peak_in_flight:0},simulated_days:{samples:0,p50_wall_ms:null,p95_wall_ms:null},providers:[]}});
    if(path==='/api/v2/world-map')return route.fulfill({json:{...base,projection:'world.map',data:{
      regions:[{id:1,name:'Test district',x:.5,y:.5}],
      agents:Array.from({length:agents},(_,n)=>({id:n+1,name:`Citizen ${n+1}`,region_id:1,place_id:(n%places)+1})),
      places:Array.from({length:places},(_,n)=>({id:n+1,name:`Place ${n+1}`,kind:['residential_district','firm_workplace','licensing_office','public_commons'][n%4],region_id:1,x:.3+(n%10)*.04,y:.3+Math.floor(n/10)*.04,capacity:12})),
      banks:[{id:1,name:'Civic Bank',region_id:1,status:tick===1?'open':'failed'}],
      organizations:[{id:1,name:'Workshop One',sector:'manufacturing',place_id:2,region_id:1}],
    }}});
    if(path==='/api/v2/civic/summary')return route.fulfill({json:{...base,projection:'civic.summary',data:{enabled:true,tick,queue:{depth:0,oldest_age_ticks:0},offices:[]}}});
    if(path==='/api/v2/snapshot')return route.fulfill({json:{...base,projection:'world.snapshot',data:{summary:{status:'paused',phase:'FINALIZE',active_tick:null,agents_alive:agents,active_firms:1,ledger_balance:0},alerts:[],communications:{total:0,published:0,private_total:0},events:{items:[{id:9,tick,phase:'FINALIZE',kind:'wage_paid',importance:1,payload:{agent_id:1,firm_id:1}}]}}}});
    return route.fulfill({json:{...base,projection:'empty',data:{}}});
  });
}
