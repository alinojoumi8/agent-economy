import { expect,test } from '@playwright/test';
import { installCityFixture } from './fixtures/city';
test.use({launchOptions:{args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']}});
async function openCity(page:import('@playwright/test').Page){
  await installCityFixture(page);await page.goto('/runs/city-fixture/world?cityView=3d');
  await expect(page.getByTestId('city-canvas')).toHaveAttribute('data-ready','true');
}
test('300 agents / 100 places share selection, camera, evidence and history',async({page})=>{
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));await openCity(page);
  const explorer=page.getByLabel('Keyboard explorer');
  await expect(explorer.locator('option')).toHaveCount(403);
  await explorer.selectOption('agent:125');
  await expect(page.getByRole('heading',{name:'Citizen 125',exact:true})).toBeVisible();
  await expect(page.getByRole('link',{name:'Open citizen dossier'})).toHaveAttribute('href',/people\/125\?city=/);
  await page.getByRole('button',{name:'Focus Citizen 125',exact:true}).click();
  for(const name of ['Zoom in','Zoom out','Rotate left','Rotate right','Pan north','Pan south','Pan east','Pan west'])await page.getByRole('button',{name,exact:true}).click();
  await explorer.selectOption('firm:1');
  await expect(page.getByRole('link',{name:'Open business dossier'})).toHaveAttribute('href',/organizations\/firm\/1\?city=/);
  await explorer.selectOption('institution:bank:1');
  await expect(page.getByLabel('Selected city evidence')).toContainText('Failed');
  await page.goto('/runs/city-fixture/world?view=3d&tick=1&institution=bank:1');
  await expect(page.getByLabel('Selected city evidence')).toContainText('Open');
  await explorer.selectOption('place:2');
  await expect(page.getByRole('heading',{name:'Place 2',exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:'Advance one tick'})).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('mount/unmount releases canvas and supports repeated 2D fallback',async({page})=>{
  await openCity(page);
  for(let n=0;n<5;n++){
    await page.getByRole('button',{name:'Atlas',exact:true}).click();await expect(page.locator('canvas')).toHaveCount(0);
    await page.getByRole('button',{name:'3D · experimental',exact:true}).click();await expect(page.getByTestId('city-canvas')).toHaveAttribute('data-ready','true');await expect(page.locator('canvas')).toHaveCount(1);
  }
});

test('3D camera bookmarks restore the rendered view across modes, evidence, history and reload',async({page},testInfo)=>{
  const navigations:string[]=[];page.on('framenavigated',frame=>{if(frame===page.mainFrame())navigations.push(frame.url());});
  try {
  await openCity(page);
  await page.getByLabel('Keyboard explorer').selectOption('agent:125');
  await page.getByRole('button',{name:'Focus Citizen 125',exact:true}).click();
  const focused=new URL(page.url()).searchParams.get('camera3d');
  expect(focused).toBeTruthy();
  await page.getByRole('button',{name:'Pan east',exact:true}).click();
  const moved=new URL(page.url()).searchParams.get('camera3d');
  expect(moved).not.toBe(focused);
  const canvas=page.getByTestId('city-canvas');
  await expect(canvas).toHaveAttribute('data-camera3d',moved!);
  await page.goBack();await expect(page).toHaveURL(url=>url.searchParams.get('camera3d')===focused);await expect(canvas).toHaveAttribute('data-camera3d',focused!);
  await page.goForward();await expect(page).toHaveURL(url=>url.searchParams.get('camera3d')===moved);await expect(canvas).toHaveAttribute('data-camera3d',moved!);
  await page.getByRole('button',{name:'Atlas',exact:true}).click();
  await page.getByRole('button',{name:'3D · experimental',exact:true}).click();
  await expect(canvas).toHaveAttribute('data-camera3d',moved!);
  await page.getByRole('link',{name:'Open citizen dossier'}).click();
  await expect(page.getByRole('dialog',{name:'People in City'})).toBeVisible();
  await page.getByRole('button',{name:'Back to City · Esc'}).click();
  await expect(canvas).toHaveAttribute('data-camera3d',moved!);
  await page.reload();await expect(canvas).toHaveAttribute('data-ready','true');
  await expect(canvas).toHaveAttribute('data-camera3d',moved!);
  await expect(page.getByLabel('Keyboard explorer')).toHaveValue('agent:125');
  } finally {await testInfo.attach('camera-navigation',{body:JSON.stringify(navigations,null,2),contentType:'application/json'});}
});

test('streets and housing keep rendering resources bounded when layers change',async({page})=>{
  await openCity(page);
  await page.getByText('Projection and rendering evidence',{exact:true}).click();
  const evidence=page.locator('.city3d-notes code');
  await expect(evidence).toContainText('geometries');
  const geometries=async()=>Number((await evidence.innerText()).match(/(\d+) geometries/)![1]);
  await expect.poll(geometries).toBeGreaterThan(0);
  const baseline=await geometries();
  for(let i=0;i<4;i++){
    await page.getByLabel('Keyboard explorer').selectOption('place:2');
    await page.getByLabel('Keyboard explorer').selectOption('agent:2');
  }
  await expect.poll(geometries).toBeLessThanOrEqual(baseline+1);
  await expect(page.getByLabel('Keyboard explorer').locator('option')).toHaveCount(403);
  expect(Number((await evidence.innerText()).match(/(\d+) draw calls/)![1])).toBeLessThan(100);
});
test('asset failure shows usable fallback and mobile remains navigable',async({page})=>{
  await installCityFixture(page);await page.route('**/city/office-low.glb',route=>route.fulfill({status:503,body:'offline'}));
  await page.setViewportSize({width:390,height:844});await page.emulateMedia({reducedMotion:'reduce'});
  await page.goto('/runs/city-fixture/world?cityView=3d');
  await expect(page.getByRole('alert').filter({hasText:'Could not load office'})).toBeVisible();
  await expect(page.getByRole('button',{name:'Use 2D atlas',exact:true})).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBeTruthy();
  await page.getByRole('button',{name:'Use 2D atlas',exact:true}).click();await expect(page.locator('canvas')).toHaveCount(0);
});
test('WebGL failure is explicit and backend failure does not invent a live city',async({page})=>{
  await installCityFixture(page);await page.addInitScript(()=>{const original=HTMLCanvasElement.prototype.getContext;HTMLCanvasElement.prototype.getContext=function(type,...args){if(type==='webgl2')return null;return original.call(this,type,...args as [any]);} as typeof original;});
  await page.goto('/runs/city-fixture/world?cityView=3d');await expect(page.getByText('3D graphics are unavailable on this device.',{exact:false})).toBeVisible();
  await page.getByRole('button',{name:'Use 2D atlas',exact:true}).click();await expect(page.locator('canvas')).toHaveCount(0);
});
test('construction preview queues a server-priced proposal and preserves request identity on retry',async({page})=>{
  await installCityFixture(page);
  const commands:Record<string,any>[]=[];let attempts=0;
  await page.route('**/api/participant',route=>route.fulfill({json:{enabled:true,active:true,running:false,completed_tick:2,next_tick:3,
    controlled_agent:{id:1,name:'Citizen 1'},action_catalog:[{type:'construct_building',variant:'default',label:'Construct workplace',enabled:true,fields:[
      {name:'firm_id',kind:'select',options:[{value:1,label:'Workshop One'}]},
      {name:'parcel_id',kind:'select',options:[{value:1,label:'Central parcel'}]},
      {name:'template_key',kind:'hidden',default:'workplace'},{name:'request_key',kind:'text'},
    ]}]}}));
  await page.route('**/api/v2/urban-development*',route=>route.fulfill({json:{run_id:'city-fixture',fork_id:null,tick:2,semantics_version:13,projection_version:1,policy_version:1,view_key:'public',snapshot_version:'urban-t2',event_cursor:9,projection:'urban.development',data:{enabled:true,
    catalog:[{template_key:'workplace',name:'Firm workplace',cost_cents:50000,capacity:12,duration_ticks:3,zone_key:'commercial'}],
    parcels:[{id:1,parcel_key:'Central parcel',region_id:1,x:.55,y:.55,zone_key:'commercial',blocked:0,owner_firm_id:null}],projects:[]}}}));
  await page.route('**/api/participant/action',route=>{commands.push(route.request().postDataJSON());attempts++;return route.fulfill({status:attempts===1?503:200,json:attempts===1?{detail:'Temporary queue failure'}:{ok:true}});});
  await page.goto('/runs/city-fixture/world?cityView=3d');await expect(page.getByTestId('city-canvas')).toHaveAttribute('data-ready','true');
  await page.getByText('Construction & citizen actions',{exact:true}).click();
  await page.getByLabel('Parcel preview').selectOption('1');
  await expect(page.getByText('Selected parcel is a proposal preview;',{exact:false})).toBeVisible();
  await page.getByRole('button',{name:'Propose construction',exact:true}).click();
  await expect(page.getByRole('alert').filter({hasText:'Temporary queue failure'})).toBeVisible();
  await page.getByRole('button',{name:'Propose construction',exact:true}).click();
  await expect(page.getByText('Proposal queued.',{exact:false})).toBeVisible();
  expect(commands).toHaveLength(2);expect(commands[0]).toEqual(commands[1]);
  expect(commands[0].action).toMatchObject({type:'construct_building',firm_id:1,parcel_id:1,template_key:'workplace'});
  expect(commands[0].action.request_key).toMatch(/^[a-f0-9-]{36}$/);
  expect(commands[0].action).not.toHaveProperty('cost_cents');
  await expect(page.getByText('No construction projects at this tick.')).toBeVisible();
  await expect(page.getByLabel('Keyboard explorer').locator('option')).toHaveCount(403);
});
test('construction before and after states preserve City context through linked evidence',async({page})=>{
  await installCityFixture(page);
  await page.route('**/api/v2/urban-development*',route=>{
    const tick=new URL(route.request().url()).searchParams.get('tick')==='1'?1:2;
    return route.fulfill({json:{run_id:'city-fixture',fork_id:null,tick,semantics_version:13,projection_version:1,policy_version:1,view_key:'public',snapshot_version:`urban-t${tick}`,event_cursor:9,projection:'urban.development',data:{enabled:true,catalog:[],parcels:[],projects:[{
      id:1,firm_id:1,status:tick===1?'building':'completed',completion_tick:2,created_event_id:8,outcome_event_id:tick===2?9:null,
    }]}}});
  });
  await page.route('**/api/v2/city/activity*',route=>{
    const tick=new URL(route.request().url()).searchParams.get('tick')==='1'?1:2;
    const outcome=tick===1?'pending':'completed';
    return route.fulfill({json:{run_id:'city-fixture',fork_id:null,tick,semantics_version:12,projection_version:2,policy_version:1,view_key:'public',snapshot_version:`s12-t${tick}-e9-fixture`,event_cursor:9,projection:'city.activity',data:{tick,source:'committed',total:1,day_total:1,changed_agents:0,offset:0,limit:40,next_offset:null,through_id:9,actors:[],actor_activity:[],counts:{[outcome]:1},categories:{construction:1},items:[{
      id:tick===1?8:9,tick,kind:tick===1?'construction_started':'construction_completed',title:'Workshop One construction',detail:'',category:'construction',outcome,actor_ids:[],actors:[],firm_id:1,firm_name:'Workshop One',
    }]}}});
  });
  const camera='95,100,110,0,0,0,2.6';
  await page.goto(`/runs/city-fixture/world?tick=1&agent=125&view=3d&camera3d=${encodeURIComponent(camera)}`);
  await expect(page.getByTestId('city-canvas')).toHaveAttribute('data-ready','true');
  await page.getByRole('button',{name:'Locate Workshop One',exact:true}).click();
  await expect(page.getByLabel('Keyboard explorer')).toHaveValue('firm:1');
  await page.getByText('Construction & citizen actions',{exact:true}).click();
  const construction=page.getByRole('region',{name:'City construction',exact:true});
  await expect(construction).toContainText('1 under construction · 0 completed');
  await expect(construction.getByRole('button',{name:'Cancel · full refund'})).toBeDisabled();
  await construction.getByRole('link',{name:'Event #8',exact:true}).click();
  await expect(page.getByRole('dialog',{name:'Evidence in City'})).toBeVisible();
  await page.getByRole('button',{name:'Back to City · Esc'}).click();
  await expect(page.getByLabel('Keyboard explorer')).toHaveValue('firm:1');
  await expect(page.getByRole('button',{name:'3D · experimental',exact:true})).toHaveAttribute('aria-pressed','true');
  await expect(page.getByTestId('city-canvas')).toHaveAttribute('data-camera3d',camera);
  await expect(page.getByRole('textbox',{name:'Inspect tick'})).toHaveValue('1');
  await page.getByRole('textbox',{name:'Inspect tick'}).fill('2');
  await page.getByRole('button',{name:'Go to tick'}).click();
  const constructionDetails=page.locator('details.city-secondary').filter({has:page.getByText('Construction & citizen actions',{exact:true})});
  if(await constructionDetails.getAttribute('open')===null)await page.getByText('Construction & citizen actions',{exact:true}).click();
  await expect(construction).toContainText('0 under construction · 1 completed');
  await expect(construction.getByRole('link',{name:'Event #9',exact:true})).toHaveAttribute('href',/city=/);
  await expect(construction.getByRole('button',{name:'Demolish · no refund'})).toBeDisabled();
});

test('graphics context loss remains failed while projections refresh',async({page})=>{
  await openCity(page);
  await page.evaluate(()=>{const gl=document.querySelector('canvas')!.getContext('webgl2')!;gl.getExtension('WEBGL_lose_context')!.loseContext();});
  await expect(page.getByText('3D graphics context was lost.',{exact:false})).toBeVisible();
  await page.getByText('Layers and agent filters',{exact:true}).click();
  await page.getByLabel('Find an agent').fill('Citizen 1');await page.getByLabel('Find an agent').fill('');
  await expect(page.getByText('3D graphics context was lost.',{exact:false})).toBeVisible();
  await page.getByRole('button',{name:'Use 2D atlas',exact:true}).click();await expect(page.locator('canvas')).toHaveCount(0);
});
test('backend disconnect disables actions and reconnect restores the committed view',async({page})=>{
  await openCity(page);
  await page.route('**/api/v2/world-map*',route=>route.fulfill({status:503,json:{detail:'City temporarily offline'}}));
  await expect(page.getByRole('alert').filter({hasText:'City temporarily offline'})).toBeVisible({timeout:25000});
  await page.route('**/api/run/status',route=>route.fulfill({status:503,json:{detail:'Status offline'}}));
  await expect(page.getByRole('button',{name:'Advance one tick',exact:true})).toBeDisabled();
  await expect(page.getByRole('button',{name:'Use 2D atlas',exact:true})).toBeVisible();
  await page.unroute('**/api/v2/world-map*');
  await page.unroute('**/api/run/status');
  await expect(page.getByRole('alert').filter({hasText:'City temporarily offline'})).toHaveCount(0,{timeout:15000});
  await expect(page.getByLabel('Keyboard explorer').locator('option')).toHaveCount(403);
});
test('invalid refreshed projection clears entities instead of retaining a false live city',async({page})=>{
  await openCity(page);
  await page.route('**/api/v2/world-map*',route=>route.fulfill({json:{run_id:'city-fixture',fork_id:null,tick:2,semantics_version:12,projection_version:999,policy_version:1,view_key:'public',snapshot_version:'bad',event_cursor:9,projection:'world.map',data:{}}}));
  await expect(page.getByText('Unsupported or malformed city projection.',{exact:false})).toBeVisible({timeout:15000});
  await expect(page.getByLabel('Keyboard explorer').locator('optgroup option')).toHaveCount(0);
});
test('participant clock requires an explicit action and disables continuous Run',async({page})=>{
  await installCityFixture(page);let queued=false;
  await page.route('**/api/participant',route=>route.fulfill({json:{enabled:true,active:true,running:false,completed_tick:2,next_tick:3,controlled_agent:{id:1,name:'Citizen 1'},queued_action:queued?{id:1,target_tick:3,action:{type:'do_nothing'}}:null,action_catalog:[{type:'do_nothing',variant:'default',label:'Do nothing',enabled:true,fields:[]}]}}));
  await page.route('**/api/participant/action',route=>{queued=true;return route.fulfill({json:{ok:true}});});
  await page.goto('/runs/city-fixture/world?cityView=3d');await expect(page.getByTestId('city-canvas')).toHaveAttribute('data-ready','true');
  await expect(page.getByRole('button',{name:'Advance one tick',exact:true})).toBeDisabled();
  await expect(page.getByRole('button',{name:'Run',exact:true})).toBeDisabled();
  await page.getByText('Construction & citizen actions',{exact:true}).click();
  await page.getByRole('button',{name:'Queue action for next day',exact:true}).click();
  await expect(page.getByRole('button',{name:'Advance one tick',exact:true})).toBeEnabled();
  await expect(page.getByRole('button',{name:'Run',exact:true})).toBeDisabled();
});

test('local Stop finishes a running city and a rejected stop stays retryable',async({page})=>{
  await installCityFixture(page);
  let status='paused',stops=0;
  await page.route('**/api/run/status',route=>route.fulfill({json:{run_id:'city-fixture',status,tick:2,running:status==='running'}}));
  await page.route('**/api/run/start',route=>{status='running';return route.fulfill({json:{status}});});
  await page.route('**/api/run/stop',route=>{
    stops++;
    if(stops===1)return route.fulfill({status:503,json:{detail:'Stop temporarily unavailable'}});
    status='finished';return route.fulfill({json:{status,tick:2,report_path:'reports/test.html'}});
  });
  await page.goto('/runs/city-fixture/world?cityView=3d');
  const clock=page.getByRole('group',{name:'Simulation clock'});
  await clock.getByRole('button',{name:'Run',exact:true}).click();
  await expect(clock).toContainText('running');
  await clock.getByRole('button',{name:'Stop + report',exact:true}).click();
  await expect(clock.getByRole('alert')).toContainText('Stop temporarily unavailable');
  await clock.getByRole('button',{name:'Stop + report',exact:true}).click();
  await expect(clock).toContainText('finished');
  await expect(clock.getByRole('button',{name:'Run',exact:true})).toBeDisabled();
  await expect(clock.getByRole('button',{name:'Stop + report',exact:true})).toBeDisabled();
  expect(stops).toBe(2);
});

test('primary drag pans horizontally and vertically without orbiting; secondary drag rotates',async({page})=>{
  await openCity(page);
  await page.evaluate(async()=>{
    const path='/src/city/CityScene.ts';
    const {CityScene}=await import(/* @vite-ignore */ path);
    const host=document.createElement('div');host.id='camera-gesture-test';
    host.style.cssText='position:fixed;inset:0;width:600px;height:400px;z-index:99999';document.body.append(host);
    (window as any).gestureScene=new CityScene(host,()=>{},()=>{},()=>{},()=>{});
  });
  const pose=()=>page.evaluate(()=>{const s=(window as any).gestureScene;return {target:s.controls.target.toArray(),offset:s.camera.position.clone().sub(s.controls.target).toArray()};});
  const drag=async(dx:number,dy:number,button:'left'|'right')=>{await page.mouse.move(300,200);await page.mouse.down({button});await page.mouse.move(300+dx,200+dy,{steps:8});await page.mouse.up({button});};
  try{
    const start=await pose();await drag(90,0,'left');const horizontal=await pose();
    expect(Math.hypot(...horizontal.target.map((v:number,i:number)=>v-start.target[i]))).toBeGreaterThan(1);
    horizontal.offset.forEach((v:number,i:number)=>expect(v).toBeCloseTo(start.offset[i],5));
    await drag(0,70,'left');const vertical=await pose();
    expect(Math.hypot(...vertical.target.map((v:number,i:number)=>v-horizontal.target[i]))).toBeGreaterThan(1);
    vertical.offset.forEach((v:number,i:number)=>expect(v).toBeCloseTo(start.offset[i],5));
    await drag(90,0,'right');const rotated=await pose();
    expect(Math.hypot(...rotated.offset.map((v:number,i:number)=>v-vertical.offset[i]))).toBeGreaterThan(1);
  }finally{await page.evaluate(()=>{(window as any).gestureScene.dispose();document.querySelector('#camera-gesture-test')?.remove();});}
});
