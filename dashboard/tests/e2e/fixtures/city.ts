import type { Page } from '@playwright/test';
export async function installCityFixture(page:Page,{agents=300,places=100}:{agents?:number;places?:number}={}){
  await page.addInitScript(()=>{
    class Socket extends EventTarget{
      readyState=1;static OPEN=1;
      constructor(){super();queueMicrotask(()=>{this.dispatchEvent(new Event('open'));this.dispatchEvent(new MessageEvent('message',{data:JSON.stringify({type:'hello',run_id:'city-fixture',fork_id:null,tick:2,semantics_version:12,projection_version:2,policy_version:1,view_key:'public',event_cursor:9,status:'paused'})}));});}
      send(){} close(){this.readyState=3;}
    }
    Object.defineProperty(window,'WebSocket',{value:Socket});
  });
  await page.route('**/api/**',async route=>{
    const url=new URL(route.request().url()),path=url.pathname;
    const tick=url.searchParams.get('tick')==='1'?1:2;
    const base={run_id:'city-fixture',fork_id:url.searchParams.get('fork_id'),tick,semantics_version:12,projection_version:2,policy_version:1,view_key:'public',snapshot_version:`s12-t${tick}-e9-fixture`,event_cursor:9};
    if(path==='/api/v2/mode')return route.fulfill({json:{mode:'local',hosted:false,navigation:{run_id:'city-fixture'}}});
    if(path==='/api/participant')return route.fulfill({json:{enabled:false,active:false}});
    if(path==='/api/v2/workspaces/people')return route.fulfill({json:{...base,projection:'workspace.people',data:{agents:[],projects:[],summary:{living_agents:0,active_employments:0,active_projects:0,completed_projects:0,runtime_active:0,projects_total:0},source_legend:{}}}});
    if(path==='/api/run/status')return route.fulfill({json:{run_id:'city-fixture',status:'paused',tick,running:false}});
    if(path==='/api/llm/runtime')return route.fulfill({json:{live_only:false,activity_revision:0,active_agents:[],global:{in_flight:0,capacity:2,queue_depth:0,peak_in_flight:0},simulated_days:{samples:0,p50_wall_ms:null,p95_wall_ms:null},providers:[]}});
    if(path==='/api/v2/world-map')return route.fulfill({json:{...base,projection:'world.map',data:{
      regions:[{id:1,name:'Test district',x:.5,y:.5}],
      agents:Array.from({length:agents},(_,n)=>({id:n+1,name:`Citizen ${n+1}`,region_id:1,place_id:(n%places)+1})),
      places:Array.from({length:places},(_,n)=>({id:n+1,name:`Place ${n+1}`,kind:['residential_district','firm_workplace','licensing_office','public_commons'][n%4],region_id:1,x:.3+(n%10)*.04,y:.3+Math.floor(n/10)*.04,capacity:12})),
      banks:[{id:1,name:'Civic Bank',region_id:1,status:tick===1?'open':'failed'}],
      institutions:{tick,source:'public_bank_status',visibility:'public_status_only',available:true,items:[{id:'bank:1',bank_id:1,kind:'bank',name:'Civic Bank',status:tick===1?'open':'failed',currency_code:'USD'}]},
      organizations:[{id:1,name:'Workshop One',sector:'manufacturing',place_id:2,region_id:1}],
    }}});
    if(path==='/api/v2/civic/summary')return route.fulfill({json:{...base,projection:'civic.summary',data:{enabled:true,tick,queue:{depth:0,oldest_age_ticks:0},offices:[]}}});
    if(path==='/api/v2/city/activity'){
      const all=Array.from({length:125},(_,n)=>({id:n+1,tick,phase:'EXECUTE',kind:n%3?'wage_paid':'construction_queued',title:n%3?'Wage paid':'Construction queued',detail:`Recorded action ${n+1}`,category:n%3?'work':'construction',outcome:n%3?'completed':'pending',actor_ids:[n+1],actors:[{id:n+1,name:`Citizen ${n+1}`}],activity:n%3?'working':'construction',evidence_ref:`event:${n+1}`}));
      const actor=url.searchParams.get('actor_id'),category=url.searchParams.get('category');
      const filtered=all.filter(e=>(!actor||e.actor_ids.includes(Number(actor)))&&(!category||category==='all'||e.category===category));
      const offset=Number(url.searchParams.get('offset')||0),limit=Number(url.searchParams.get('limit')||40);
      return route.fulfill({json:{...base,projection:'city.activity',data:{tick,through_id:125,source:'committed',window:'selected_day',total:filtered.length,day_total:all.length,offset,limit,next_offset:offset+limit<filtered.length?offset+limit:null,items:filtered.slice(offset,offset+limit),counts:{completed:filtered.filter(e=>e.outcome==='completed').length,pending:filtered.filter(e=>e.outcome==='pending').length},categories:{work:83,construction:42},actors:all.map(e=>({...e.actors[0],count:1})),changed_agents:filtered.length,actor_activity:filtered.map(event=>({agent_id:event.actor_ids[0],event})),marker_events:filtered}}});
    }
    if(path==='/api/v2/urban-development')return route.fulfill({json:{...base,projection:'urban.development',data:{enabled:false}}});
    if(path==='/api/v2/snapshot')return route.fulfill({json:{...base,projection:'world.snapshot',data:{summary:{status:'paused',phase:'FINALIZE',active_tick:null,agents_alive:agents,active_firms:1,ledger_balance:0},alerts:[],communications:{total:0,published:0,private_total:0},events:{items:[{id:9,tick,phase:'FINALIZE',kind:'wage_paid',importance:1,payload:{agent_id:1,firm_id:1}}]}}}});
    return route.fulfill({status:404,json:{detail:'Fixture endpoint unavailable'}});
  });
}
