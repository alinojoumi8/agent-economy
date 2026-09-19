import {expect,test} from '@playwright/test';

const realRunId=process.env.AE_REAL_RUN_ID||'';
test.describe('provider-free real backend City smoke',()=>{
  test.skip(!realRunId,'Set AE_REAL_RUN_ID to a disposable deterministic run with a recorded day.');
  test('City home, activity and contextual panels read the same real run without advancing it',async({page,request})=>{
    const errors:string[]=[];page.on('pageerror',error=>errors.push(error.message));
    const before=await(await request.get('/api/run/status')).json();
    expect(before.run_id).toBe(realRunId);
    await page.goto('/');
    await expect(page).toHaveURL(new RegExp(`/runs/${realRunId}/world`));
    await expect(page.locator('.world-os-context h1')).toHaveText('City');
    await expect(page.getByLabel('Day activity totals')).toContainText('events');
    const activity=await(await request.get('/api/v2/city/activity')).json();
    await expect(page.getByLabel('Day activity totals')).toContainText(`${activity.data.total.toLocaleString()} events`);
    if(process.env.AE_CAPTURE_CITY) await page.screenshot({path:'../docs/research/assets/city-unified-atlas.png'});
    for(const label of ['Economy','People','Businesses & banks','Markets','Law & civic life','Conversations & news','Evidence']){
      await page.getByRole('link',{name:label,exact:true}).click();
      const panel=page.getByRole('dialog',{name:label+' in City'});
      await expect(panel).toBeVisible();
      // The causal graph exposes its current zoom as a live status readout.
      // Wait for actual workspace and nested loaders, not every status region.
      await expect(panel.locator('.world-os-loading')).toHaveCount(0,{timeout:15000});
      await expect(panel.getByRole('alert')).toHaveCount(0);
      await page.getByRole('button',{name:'Back to City · Esc'}).click();
      await expect(page.getByLabel('Keyboard explorer')).toBeEnabled();
    }
    await page.getByRole('button',{name:'Inspect this day'}).click();
    await expect(page.getByRole('group',{name:'Simulation clock'})).toHaveCount(0);
    await page.getByRole('link',{name:'Economy',exact:true}).click();
    await expect(page.getByRole('dialog')).toContainText('hidden while inspecting');
    await page.keyboard.press('Escape');
    await page.setViewportSize({width:390,height:844});
    await page.getByRole('button',{name:'List',exact:true}).click();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
    if(process.env.AE_CAPTURE_CITY) await page.screenshot({path:'../docs/research/assets/city-unified-mobile.png'});
    expect((await(await request.get('/api/run/status')).json()).tick).toBe(before.tick);
    expect(errors).toEqual([]);
  });
  test('experimental 3D uses the shared inspector and survives reload',async({page})=>{
    await page.goto(`/runs/${realRunId}/world?view=3d&population=all`);
    await expect(page.getByTestId('city-canvas')).toHaveAttribute('data-ready','true');
    const explorer=page.getByLabel('Keyboard explorer');
    const first=await explorer.locator('optgroup[label="Agents"] option').first().getAttribute('value');
    expect(first).toBeTruthy();await explorer.selectOption(first!);
    await expect(page.getByRole('link',{name:'Open citizen dossier'})).toHaveAttribute('href',new RegExp(`/runs/${realRunId}/people/`));
    await page.getByRole('button',{name:'Zoom in',exact:true}).click();
    await page.reload();await expect(page.getByTestId('city-canvas')).toHaveAttribute('data-ready','true');
    await expect(explorer).toHaveValue(first!);
    await expect(page.locator('.city3d-inspector')).toHaveCount(0);
    if(process.env.AE_CAPTURE_CITY) await page.screenshot({path:'../docs/research/assets/city-unified-3d.png'});
  });
});
