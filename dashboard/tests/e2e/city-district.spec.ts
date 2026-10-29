import { expect,test } from '@playwright/test';
import { installCityFixture } from './fixtures/city';

test.use({launchOptions:{args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']}});

for(const width of [390,768,1440])test(`district at ${width}px keeps landmarks and the shared inspector accessible`,async({page},testInfo)=>{
  await page.setViewportSize({width,height:width===390?844:width===768?1024:1000});
  await page.emulateMedia({reducedMotion:'reduce'});
  await installCityFixture(page,{agents:24,places:12});
  await page.goto('/runs/city-fixture/world?view=3d&population=all');
  const canvas=page.getByTestId('city-canvas'),lens=page.getByLabel('Selected city evidence');
  await expect(canvas).toHaveAttribute('data-ready','true');
  await expect(page.getByRole('group',{name:'District landmarks'}).getByRole('button').first()).toBeVisible();
  const field=await canvas.boundingBox(),inspector=await lens.boundingBox();
  expect(field!.y).toBeLessThan(width===390?650:700);
  if(width===1440){expect(field!.x+field!.width).toBeLessThanOrEqual(inspector!.x);expect(field!.width/width).toBeGreaterThan(.6);}
  else expect(inspector!.y).toBeGreaterThan(field!.y+field!.height);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  // Labels are real keyboard controls, remain bounded and do not collide.
  const labels=page.locator('.city3d-landmark');
  const boxes=await labels.evaluateAll(nodes=>nodes.map(node=>{const r=node.getBoundingClientRect();return{x:r.x,y:r.y,w:r.width,h:r.height};}));
  expect(boxes.length).toBeLessThanOrEqual(10);
  for(const [i,a] of boxes.entries()){
    expect(a.h).toBeGreaterThanOrEqual(44);
    expect(a.x).toBeGreaterThanOrEqual(field!.x);expect(a.x+a.w).toBeLessThanOrEqual(field!.x+field!.width);
    for(const b of boxes.slice(i+1))expect(a.x+a.w<=b.x||b.x+b.w<=a.x||a.y+a.h<=b.y||b.y+b.h<=a.y).toBeTruthy();
  }
  await page.screenshot({path:testInfo.outputPath(`district-${width}.png`)});
  await page.getByLabel('Keyboard explorer').selectOption('agent:12');
  if(width!==1440){await page.getByRole('button',{name:'Selected evidence ↓',exact:true}).click();await expect(lens).toBeFocused();}
  await expect(lens.getByRole('heading',{name:'Citizen 12',exact:true})).toBeVisible();
  await expect(lens.getByRole('link',{name:'Open citizen dossier'})).toHaveAttribute('href',/people\/12\?city=/);
  await page.getByRole('button',{name:'List',exact:true}).click();
  await expect(page.locator('.city3d-landmarks')).toHaveCount(0);
  await expect(page.getByLabel('Keyboard explorer')).toHaveValue('agent:12');
});

test('landmark keyboard selection preserves history, camera and evidence scope without writes',async({page})=>{
  const writes:string[]=[];page.on('request',request=>{if(request.url().includes('/api/')&&!['GET','HEAD'].includes(request.method()))writes.push(request.url());});
  await page.setViewportSize({width:1440,height:1000});
  await installCityFixture(page,{agents:24,places:12});
  await page.goto('/runs/city-fixture/world?view=3d&tick=1&fork=branch-a');
  await expect(page.getByTestId('city-canvas')).toHaveAttribute('data-ready','true');
  const landmark=page.locator('.city3d-landmark[data-entity-type="place"]').first();
  await expect(landmark).toBeVisible();
  const id=await landmark.getAttribute('data-entity-id');
  await landmark.focus();await page.keyboard.press('Enter');
  await expect(page.getByLabel('Keyboard explorer')).toHaveValue(`place:${id}`);
  await expect(landmark).toHaveAttribute('aria-pressed','true');
  await expect(landmark).toBeFocused();
  const url=new URL(page.url());expect(url.searchParams.get('tick')).toBe('1');expect(url.searchParams.get('fork')).toBe('branch-a');
  await page.getByLabel('Keyboard explorer').selectOption('firm:1');
  const href=await page.getByRole('link',{name:'Open business dossier'}).getAttribute('href');
  const evidence=new URL(href!,'http://fixture');expect(evidence.searchParams.get('tick')).toBe('1');expect(evidence.searchParams.get('fork')).toBe('branch-a');
  await page.getByRole('button',{name:'Focus Workshop One',exact:true}).click();
  const camera=new URL(page.url()).searchParams.get('camera3d');expect(camera).toBeTruthy();
  await page.getByRole('button',{name:'Atlas',exact:true}).click();
  await page.getByRole('button',{name:'3D · experimental',exact:true}).click();
  await expect(page.getByTestId('city-canvas')).toHaveAttribute('data-camera3d',camera!);
  await expect(page.getByLabel('Keyboard explorer')).toHaveValue('firm:1');
  await page.getByRole('button',{name:'Show all',exact:true}).click();
  const overview=new URL(page.url()).searchParams.get('camera3d');
  await page.getByRole('button',{name:'Rotate left',exact:true}).click();
  await page.getByRole('button',{name:'Show all',exact:true}).click();
  await expect(page.getByTestId('city-canvas')).toHaveAttribute('data-camera3d',overview!);
  expect(writes).toEqual([]);
});

test('empty and forbidden city projections leave no selectable landmarks',async({page})=>{
  await installCityFixture(page,{agents:0,places:0});
  let forbidden=false;
  await page.route('**/api/v2/world-map*',route=>route.fulfill(forbidden?{status:403,json:{detail:'This city is not available to this observer'}}:{json:{
    run_id:'city-fixture',fork_id:null,tick:2,semantics_version:12,projection_version:2,policy_version:1,view_key:'public',snapshot_version:'s12-t2-e9-fixture',event_cursor:9,
    projection:'world.map',data:{agents:[],places:[],organizations:[],banks:[],regions:[]},
  }}));
  await page.goto('/runs/city-fixture/world?view=3d');
  await expect(page.getByText('No city entities are available in this projection.')).toBeVisible();
  await expect(page.locator('.city3d-landmark')).toHaveCount(0);
  forbidden=true;await page.reload();
  await expect(page.getByRole('button',{name:'Use 2D atlas',exact:true})).toBeVisible();
  await expect(page.locator('.city3d-landmark')).toHaveCount(0);
  await expect(page.getByLabel('Keyboard explorer')).toBeDisabled();
});

test('a delayed city frame shows loading without selectable placeholder records',async({page})=>{
  await installCityFixture(page,{agents:24,places:12});
  let release!:()=>void;
  const held=new Promise<void>(resolve=>{release=resolve;});
  await page.route('**/api/v2/world-map*',async route=>{await held;await route.fallback();});
  await page.goto('/runs/city-fixture/world?view=3d');
  try {
    await expect(page.getByText('Reading committed city state…',{exact:true})).toBeVisible();
    await expect(page.locator('.city3d-landmark')).toHaveCount(0);
    await expect(page.getByLabel('Keyboard explorer')).toBeDisabled();
  } finally {release();}
  await expect(page.getByTestId('city-canvas')).toHaveAttribute('data-ready','true');
  await expect(page.locator('.city3d-landmark').first()).toBeVisible();
  await expect(page.getByLabel('Keyboard explorer')).toBeEnabled();
});
