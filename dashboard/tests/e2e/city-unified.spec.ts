import {expect,test} from '@playwright/test';
import {installCityFixture} from './fixtures/city';

test('City is home; full-day pagination, outcomes and actor filters share map selection',async({page})=>{
  await installCityFixture(page);await page.goto('/');
  await expect(page).toHaveURL(/\/runs\/city-fixture\/world\?/);
  await expect(page.getByRole('heading',{name:'Pulse',exact:true})).toHaveCount(0);
  await expect(page.locator('.world-os-rail')).toHaveCount(0);
  await expect(page.getByRole('group',{name:'Simulation clock'})).toHaveCount(1);
  const activity=page.getByRole('region',{name:'City activity',exact:true});
  await expect(activity.getByLabel('Day activity totals')).toContainText('125 events');
  await expect(activity.getByLabel('Day activity totals')).toContainText('42 pending');
  await expect(activity.locator('li')).toHaveCount(40);
  for(let n=0;n<3;n++)await activity.getByRole('button',{name:'Next',exact:true}).click();
  await expect(activity.getByLabel('Activity pages')).toContainText('121–125 of 125');
  await activity.getByRole('button',{name:'Locate Citizen 125',exact:true}).click();
  await expect(page.getByLabel('Keyboard explorer')).toHaveValue('agent:125');
  await page.getByRole('button',{name:'List',exact:true}).click();
  await expect(page.getByLabel('Keyboard explorer')).toHaveValue('agent:125');
  await activity.getByLabel('Agent',{exact:true}).selectOption('125');
  await expect(activity.getByLabel('Day activity totals')).toContainText('1 events');
  await expect(page.getByLabel('Keyboard explorer').locator('optgroup[label="Agents"] option')).toHaveCount(1);
  await activity.getByRole('button',{name:'Inspect this day'}).click();
  await expect(page).toHaveURL(/tick=2/);
  await expect(page.getByRole('group',{name:'Simulation clock'})).toHaveCount(0);
  await activity.getByRole('link',{name:'Evidence'}).click();
  await expect(page.getByRole('dialog',{name:'Evidence in City'})).toBeVisible();
  await page.getByRole('button',{name:'Back to City · Esc'}).click();
  await expect(page.getByLabel('Keyboard explorer')).toHaveValue('agent:125');
  await expect(page.getByRole('button',{name:'List',exact:true})).toHaveAttribute('aria-pressed','true');
  await expect(activity.getByLabel('Agent',{exact:true})).toHaveValue('125');
});

for(const clear of [false,true])test(`rapid City view and ${clear?'filter clearing':'agent filtering'} preserve both pending choices`,async({page})=>{
  await installCityFixture(page);
  await page.goto('/runs/city-fixture/world?population=all&view=atlas'+(clear?'&actor=125':''));
  const activity=page.getByRole('region',{name:'City activity',exact:true});
  await expect(activity.getByLabel('Day activity totals')).toContainText(clear?'1 events':'125 events');
  const control=await (clear?activity.getByRole('button',{name:'Clear filters',exact:true}):activity.getByLabel('Agent',{exact:true})).elementHandle();
  const list=page.getByRole('button',{name:'List',exact:true});
  // Deliver both user events before the deferred navigation can render.
  await list.evaluate((button,{control,clear})=>{
    (button as HTMLButtonElement).click();
    if(!control)throw new Error('Activity control is missing');
    if(clear)(control as HTMLButtonElement).click();
    else{
      (control as HTMLSelectElement).value='125';
      control.dispatchEvent(new Event('change',{bubbles:true}));
    }
  },{control,clear});
  await expect(page).toHaveURL(/view=list/);
  if(clear)await expect(page).not.toHaveURL(/actor=/);
  else await expect(page).toHaveURL(/actor=125/);
  await expect(list).toHaveAttribute('aria-pressed','true');
  await expect(activity.getByLabel('Agent',{exact:true})).toHaveValue(clear?'':'125');
  await expect(activity.getByLabel('Day activity totals')).toContainText(clear?'125 events':'1 events');
});

test('City panels are keyboard contained and mobile layout has no horizontal overflow',async({page})=>{
  await installCityFixture(page);await page.setViewportSize({width:390,height:844});await page.emulateMedia({reducedMotion:'reduce'});
  await page.goto('/runs/city-fixture/world?population=all&agent=75');
  await expect(page.getByLabel('Keyboard explorer')).toHaveValue('agent:75');
  await page.getByRole('link',{name:'People',exact:true}).click();
  const panel=page.getByRole('dialog',{name:'People in City'});
  await expect(panel).toBeVisible();
  for(let n=0;n<12;n++){await page.keyboard.press('Tab');expect(await panel.evaluate(el=>el.contains(document.activeElement))).toBeTruthy();}
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBeTruthy();
  await page.keyboard.press('Escape');
  await expect(panel).toHaveCount(0);
  await expect(page.getByLabel('Keyboard explorer')).toHaveValue('agent:75');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBeTruthy();
});
