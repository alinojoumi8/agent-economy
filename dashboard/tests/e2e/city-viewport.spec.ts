import { expect,test } from '@playwright/test';
import { installCityFixture } from './fixtures/city';
test.use({launchOptions:{args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']}});
async function openCity(page:import('@playwright/test').Page){
  await installCityFixture(page);await page.goto('/runs/city-fixture/overview?cityView=3d');
  await expect(page.getByTestId('city-canvas')).toHaveAttribute('data-ready','true');
}
test('300 agents / 100 places render; keyboard selection, camera, evidence and history work',async({page})=>{
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));await openCity(page);
  await expect(page.locator('#city-entity-select option')).toHaveCount(402);
  await page.locator('#city-entity-select').selectOption({label:'● Citizen 1 · agent 1'});
  await expect(page.getByRole('heading',{name:'Citizen 1',exact:true})).toBeVisible();
  await expect(page.getByRole('link',{name:'Open agent evidence'})).toHaveAttribute('href','/runs/city-fixture/people/1');
  await page.getByRole('button',{name:'Focus camera',exact:true}).click();
  for(const name of ['Zoom in','Zoom out','Rotate left','Rotate right','Pan north','Pan south','Pan east','Pan west'])await page.getByRole('button',{name,exact:true}).click();
  await page.getByLabel('Search city').fill('Workshop One');
  await expect(page.locator('#city-entity-select option')).toHaveCount(1);
  await page.locator('#city-entity-select').selectOption({index:0});
  await expect(page.getByRole('link',{name:'Open business evidence'})).toHaveAttribute('href','/runs/city-fixture/organizations/firm/1');
  await page.getByLabel('Search city').fill('Civic Bank');
  await page.locator('#city-entity-select').selectOption({index:0});
  await expect(page.getByRole('link',{name:'Open bank evidence'})).toHaveAttribute('href','/runs/city-fixture/organizations/bank/1');
  await expect(page.locator('.city3d-inspector dd').filter({hasText:/^failed$/})).toBeVisible();
  await page.goto('/runs/city-fixture/overview?cityView=3d&tick=1&cityType=bank&cityEntity=1');
  await expect(page.locator('.city3d-inspector dd').filter({hasText:/^open$/})).toBeVisible();
  await expect(page.getByRole('link',{name:'Open bank evidence'})).toHaveAttribute('href','/runs/city-fixture/organizations/bank/1?tick=1');
  await page.goto('/runs/city-fixture/overview?cityView=3d&tick=1&cityType=place&cityEntity=2');
  await expect(page.getByTestId('city-canvas')).toHaveAttribute('data-ready','true');
  await expect(page.getByRole('link',{name:'Open place evidence'})).toHaveAttribute('href','/runs/city-fixture/world?tick=1&place=2');
  await expect(page.getByText('Name, category and region metadata may reflect current records; this is not a complete historical reconstruction.')).toBeVisible();
  await expect(page.getByRole('button',{name:'Advance one tick'})).toHaveCount(0);
  expect(errors).toEqual([]);
});
test('mount/unmount releases canvas and supports repeated 2D fallback',async({page})=>{
  await openCity(page);
  for(let n=0;n<5;n++){
    await page.getByRole('button',{name:'2D atlas',exact:true}).click();await expect(page.locator('canvas')).toHaveCount(0);
    await page.getByRole('button',{name:'3D city',exact:true}).click();await expect(page.getByTestId('city-canvas')).toHaveAttribute('data-ready','true');await expect(page.locator('canvas')).toHaveCount(1);
  }
});
test('asset failure shows usable fallback and mobile remains navigable',async({page})=>{
  await installCityFixture(page);await page.route('**/city/office-low.glb',route=>route.fulfill({status:503,body:'offline'}));
  await page.setViewportSize({width:390,height:844});await page.emulateMedia({reducedMotion:'reduce'});
  await page.goto('/runs/city-fixture/overview?cityView=3d');
  await expect(page.getByRole('alert').filter({hasText:'Could not load office'})).toBeVisible();
  await expect(page.getByRole('button',{name:'Use 2D atlas',exact:true})).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBeTruthy();
  await page.getByRole('button',{name:'Use 2D atlas',exact:true}).click();await expect(page.locator('canvas')).toHaveCount(0);
});
test('WebGL failure is explicit and backend failure does not invent a live city',async({page})=>{
  await installCityFixture(page);await page.addInitScript(()=>{const original=HTMLCanvasElement.prototype.getContext;HTMLCanvasElement.prototype.getContext=function(type,...args){if(type==='webgl2')return null;return original.call(this,type,...args as [any]);} as typeof original;});
  await page.goto('/runs/city-fixture/overview?cityView=3d');await expect(page.getByText('3D graphics are unavailable on this device.',{exact:false})).toBeVisible();
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
  await page.goto('/runs/city-fixture/overview?cityView=3d');await expect(page.getByTestId('city-canvas')).toHaveAttribute('data-ready','true');
  await page.getByLabel('Parcel preview').selectOption('1');
  await expect(page.getByText('Outline is a proposal preview.',{exact:false})).toBeVisible();
  await page.getByRole('button',{name:'Propose construction',exact:true}).click();
  await expect(page.getByRole('alert').filter({hasText:'Temporary queue failure'})).toBeVisible();
  await page.getByRole('button',{name:'Propose construction',exact:true}).click();
  await expect(page.getByText('Proposal queued.',{exact:false})).toBeVisible();
  expect(commands).toHaveLength(2);expect(commands[0]).toEqual(commands[1]);
  expect(commands[0].action).toMatchObject({type:'construct_building',firm_id:1,parcel_id:1,template_key:'workplace'});
  expect(commands[0].action.request_key).toMatch(/^[a-f0-9-]{36}$/);
  expect(commands[0].action).not.toHaveProperty('cost_cents');
  await expect(page.getByText('No construction projects at this tick.')).toBeVisible();
  await expect(page.locator('#city-entity-select option')).toHaveCount(402);
});
test('graphics context loss remains failed while projections refresh',async({page})=>{
  await openCity(page);
  await page.evaluate(()=>{const gl=document.querySelector('canvas')!.getContext('webgl2')!;gl.getExtension('WEBGL_lose_context')!.loseContext();});
  await expect(page.getByText('3D graphics context was lost.',{exact:false})).toBeVisible();
  await page.getByLabel('Search city').fill('Citizen 1');await page.getByLabel('Search city').fill('');
  await expect(page.getByText('3D graphics context was lost.',{exact:false})).toBeVisible();
  await page.getByRole('button',{name:'Use 2D atlas',exact:true}).click();await expect(page.locator('canvas')).toHaveCount(0);
});
test('backend disconnect disables actions and reconnect restores the committed view',async({page})=>{
  await openCity(page);
  await page.route('**/api/v2/world-map*',route=>route.fulfill({status:503,json:{detail:'City temporarily offline'}}));
  await expect(page.locator('.city3d-state strong')).toHaveText('Stale',{timeout:25000});
  await expect(page.getByRole('button',{name:'Advance one tick',exact:true})).toBeDisabled();
  await expect(page.getByRole('button',{name:'Use 2D atlas',exact:true})).toBeVisible();
  await page.unroute('**/api/v2/world-map*');
  await expect(page.locator('.city3d-state strong')).toHaveText('paused',{timeout:15000});
  await expect(page.locator('#city-entity-select option')).toHaveCount(402);
});
test('invalid refreshed projection clears entities instead of retaining a false live city',async({page})=>{
  await openCity(page);
  await page.route('**/api/v2/world-map*',route=>route.fulfill({json:{run_id:'city-fixture',fork_id:null,tick:2,semantics_version:12,projection_version:999,policy_version:1,view_key:'public',snapshot_version:'bad',event_cursor:9,projection:'world.map',data:{}}}));
  await expect(page.getByText('Unsupported or malformed city projection.',{exact:false})).toBeVisible({timeout:15000});
  await expect(page.locator('#city-entity-select option')).toHaveCount(0);
});
test('participant clock requires an explicit action and disables continuous Run',async({page})=>{
  await installCityFixture(page);let queued=false;
  await page.route('**/api/participant',route=>route.fulfill({json:{enabled:true,active:true,running:false,completed_tick:2,next_tick:3,controlled_agent:{id:1,name:'Citizen 1'},queued_action:queued?{id:1,target_tick:3,action:{type:'do_nothing'}}:null,action_catalog:[{type:'do_nothing',variant:'default',label:'Do nothing',enabled:true,fields:[]}]}}));
  await page.route('**/api/participant/action',route=>{queued=true;return route.fulfill({json:{ok:true}});});
  await page.goto('/runs/city-fixture/overview?cityView=3d');await expect(page.getByTestId('city-canvas')).toHaveAttribute('data-ready','true');
  await expect(page.getByRole('button',{name:'Advance one tick',exact:true})).toBeDisabled();
  await expect(page.getByRole('button',{name:'Run',exact:true})).toBeDisabled();
  await page.getByRole('button',{name:'Queue action for next day',exact:true}).click();
  await expect(page.getByRole('button',{name:'Advance one tick',exact:true})).toBeEnabled();
  await expect(page.getByRole('button',{name:'Run',exact:true})).toBeDisabled();
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
