import { expect,test,type Page } from '@playwright/test';
import { installCityFixture } from './fixtures/city';

test.use({launchOptions:{args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']}});
const probe=(page:Page)=>page.evaluate(()=>(window as any).__city3dProbe?.());
async function open(page:Page,width=1440,agents=24,places=12){
  await page.setViewportSize({width,height:1000});
  await installCityFixture(page,{agents,places,recordedDay:true});
  await page.goto('/runs/city-fixture/world?view=3d&population=all');
  await expect(page.getByTestId('city-canvas')).toHaveAttribute('data-ready','true');
  await expect.poll(async()=>!!(await probe(page))?.citizens.length).toBeTruthy();
}

test('walking, gait, pause, restart and speed are presentation-only',async({page},info)=>{
  const writes:string[]=[];page.on('request',r=>{if(r.url().includes('/api/')&&!['GET','HEAD'].includes(r.method()))writes.push(r.url());});
  await open(page);
  const initial=await probe(page);
  await page.getByRole('button',{name:'Play recorded day',exact:true}).focus();
  await page.keyboard.press('Enter');
  await expect.poll(async()=>(await probe(page)).elapsed).toBeGreaterThan(1500);
  await page.getByRole('button',{name:'Pause recorded day',exact:true}).click();
  await expect.poll(async()=>(await probe(page)).playing).toBe(false);
  const moved=await probe(page),person=moved.citizens.find((c:any)=>c.id===1),start=initial.citizens.find((c:any)=>c.id===1);
  expect(person.position).not.toEqual(start.position);expect(person.legMatrix).not.toEqual(start.legMatrix);
  expect(moved.citizens.find((c:any)=>c.id===2).position).toEqual(initial.citizens.find((c:any)=>c.id===2).position);
  await page.waitForTimeout(250);
  expect((await probe(page)).elapsed).toBe(moved.elapsed);
  await page.getByLabel('Playback speed', {exact:true}).selectOption('4');
  expect((await probe(page)).elapsed).toBe(moved.elapsed);
  await page.getByRole('button',{name:'Play recorded day',exact:true}).click();
  await expect.poll(async()=>(await probe(page)).elapsed).toBeGreaterThan(moved.elapsed+2000);
  await page.getByRole('button',{name:'Restart day',exact:true}).click();
  await expect.poll(async()=>(await probe(page)).elapsed).toBe(0);
  expect((await probe(page)).citizens.find((c:any)=>c.id===1).position).toEqual(start.position);
  expect((await probe(page)).tick).toBe(2);expect(writes).toEqual([]);
  await info.attach('walking-render-evidence',{body:JSON.stringify({initial,moved}),contentType:'application/json'});
});

for(const width of [390,768,1440])test(`recognizable citizens and playback controls at ${width}px`,async({page},info)=>{
  await open(page,width);
  const evidence=await probe(page);
  expect(Math.min(...evidence.citizens.map((c:any)=>c.heightPx))).toBeGreaterThan(24);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  const controls=page.getByRole('group',{name:'3D recorded day playback'});
  for(const button of await controls.getByRole('button').all())expect((await button.boundingBox())!.height).toBeGreaterThanOrEqual(44);
  await page.getByTestId('city-canvas').screenshot({path:info.outputPath(`citizens-${width}.png`)});
});

test('reduced motion and hidden tabs stop continuous movement',async({page})=>{
  await page.emulateMedia({reducedMotion:'reduce'});await open(page);
  await expect(page.getByText(/Reduced motion: outside-place positions/)).toBeVisible();
  const initial=await probe(page);
  await page.getByRole('button',{name:'Play recorded day',exact:true}).click();
  await expect.poll(async()=>(await probe(page)).elapsed).toBeGreaterThan(1000);
  expect((await probe(page)).citizens.map((c:any)=>c.stride)).toEqual(initial.citizens.map(()=>0));
  expect((await probe(page)).citizens[0].position).toEqual(initial.citizens[0].position);
  await page.evaluate(()=>{Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'));});
  await expect(page.getByRole('button',{name:'Play recorded day',exact:true})).toBeVisible();
  expect((await probe(page)).playing).toBe(false);
  await page.evaluate(()=>{delete (document as any).hidden;});
  await page.reload();
  await expect.poll(async()=>(await probe(page))?.elapsed).toBe(0);
});

test('new tick and fork reset playback without carrying private records',async({page})=>{
  await open(page);
  await page.getByRole('button',{name:'Play recorded day',exact:true}).click();
  await expect.poll(async()=>(await probe(page)).elapsed).toBeGreaterThan(600);
  await page.evaluate(()=>{history.pushState(null,'','?view=3d&population=all&tick=1&fork=branch-b');dispatchEvent(new PopStateEvent('popstate'));});
  await expect.poll(async()=>(await probe(page))?.tick).toBe(1);
  const frame=await probe(page);expect(frame.playing).toBe(false);expect(frame.elapsed).toBe(0);
  expect(frame.identity).toContain('branch-b');
  await page.route('**/api/v2/world-map*',route=>route.fulfill({status:403,json:{detail:'Locations withheld'}}));
  await page.reload();
  await expect(page.getByRole('button',{name:'Use 2D atlas',exact:true})).toBeVisible();
  expect((await probe(page))?.citizens||[]).toEqual([]);
});

test('without daily presence the visible citizens stand still and playback is unavailable',async({page})=>{
  await installCityFixture(page,{agents:24,places:12});
  await page.goto('/runs/city-fixture/world?view=3d&population=all');
  await expect(page.getByTestId('city-canvas')).toHaveAttribute('data-ready','true');
  await expect(page.getByRole('button',{name:'Play recorded day',exact:true})).toBeDisabled();
  const frame=await probe(page);expect(frame.citizens).toHaveLength(24);
  expect(frame.citizens.every((c:any)=>c.stride===0)).toBeTruthy();
  expect(frame.citizens.find((c:any)=>c.id===1).position).not.toEqual(frame.citizens.find((c:any)=>c.id===13).position);
});

test('a moving citizen remains selectable and camera follow tracks the rendered position',async({page})=>{
  await open(page,1440,2,2);
  await page.getByLabel('Keyboard explorer').selectOption('agent:1');
  await page.getByRole('button',{name:'Focus Citizen 1',exact:true}).click();
  await page.getByRole('button',{name:'Play recorded day',exact:true}).click();
  await expect.poll(async()=>(await probe(page)).elapsed).toBeGreaterThan(1500);
  await page.getByRole('button',{name:'Pause recorded day',exact:true}).click();
  const citizen=(await probe(page)).citizens.find((c:any)=>c.id===1);
  const box=await page.getByTestId('city-canvas').boundingBox();
  await page.mouse.click(box!.x+citizen.head.x,box!.y+citizen.head.y);
  await expect(page.getByRole('heading',{name:'Citizen 1',exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:'Follow person',exact:true})).toBeEnabled();
  await page.getByRole('button',{name:'Follow person',exact:true}).click();
  await page.getByRole('button',{name:'Play recorded day',exact:true}).click();
  const start=await probe(page);
  await expect.poll(async()=>(await probe(page)).elapsed).toBeGreaterThan(start.elapsed+1500);
  const current=(await probe(page)).citizens.find((c:any)=>c.id===1);
  expect(Math.abs(current.screen.x-box!.width/2)).toBeLessThan(2);
  await expect(page.getByRole('link',{name:'Open citizen dossier'})).toHaveAttribute('href',/people\/1/);
});

test('300 moving citizens retain bounded geometry and report measured frame times',async({page},info)=>{
  await open(page,1440,300,100);
  await page.getByRole('button',{name:'Play recorded day',exact:true}).click();
  await expect.poll(async()=>(await probe(page)).frameTimes.length,{timeout:15000}).toBeGreaterThan(30);
  await page.getByRole('button',{name:'Pause recorded day',exact:true}).click();
  const evidence=await probe(page);expect(evidence.citizens).toHaveLength(300);
  expect(evidence.citizens.filter((c:any)=>c.distance>0).length).toBe(225);
  await info.attach('300-citizen-frame-times',{body:JSON.stringify(evidence),contentType:'application/json'});
});

test('rendered citizens turn along roads and clear every building throughout a day',async({page},info)=>{
  await open(page);
  await expect(page.getByText(/Citizens follow illustrative roads between recorded places/)).toBeVisible();
  await page.getByLabel('Playback speed',{exact:true}).selectOption('4');
  await page.getByRole('button',{name:'Play recorded day',exact:true}).click();
  const samples=await page.evaluate(async()=>{
    const frames=[];
    for(let i=0;i<64;i++){
      frames.push((window as any).__city3dProbe());
      await new Promise(resolve=>setTimeout(resolve,200));
    }
    return frames;
  });
  await page.getByRole('button',{name:'Pause recorded day',exact:true}).click();
  const first=samples[0];
  for(const frame of samples)for(const citizen of frame.citizens){
    const [x,,z]=citizen.position;
    expect(first.roads.some((r:any)=>Math.abs(x-r.x)<=r.width/2+1e-6&&Math.abs(z-r.z)<=r.depth/2+1e-6)).toBe(true);
    for(const b of first.footprints)expect(Math.hypot(Math.max(Math.abs(x-b.x)-b.half,0),Math.max(Math.abs(z-b.z)-b.half,0))).toBeGreaterThanOrEqual(2.6-1e-6);
  }
  expect(samples.at(-1).elapsed-samples[0].elapsed).toBeGreaterThan(45000);
  expect(new Set(samples.map(frame=>frame.citizens.find((c:any)=>c.id===1).heading)).size).toBeGreaterThan(1);
  await info.attach('road-day-samples',{body:JSON.stringify(samples),contentType:'application/json'});
});
