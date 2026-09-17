// Node 24+, Playwright Chromium. Run against a built/static or Vite city viewer.
// Fixture data are explicitly synthetic; this is a renderer/load test, not economics evidence.
import { chromium } from '@playwright/test';
import { installCityFixture } from '../tests/e2e/fixtures/city.ts';
import { writeFile } from 'node:fs/promises';
const url=process.env.CITY_TEST_URL||'http://127.0.0.1:4174';
const seconds=Number(process.env.CITY_TEST_SECONDS||1800);
const output=process.env.CITY_TEST_OUTPUT||'/tmp/agent-economy-city-endurance.json';
const hardware=process.env.CITY_TEST_GPU==='hardware';
const browser=await chromium.launch({headless:true,args:hardware?['--enable-gpu','--use-gl=angle','--use-angle=gl','--disable-software-rasterizer']:['--enable-webgl','--ignore-gpu-blocklist','--enable-unsafe-swiftshader']});
const page=await browser.newPage({viewport:{width:1920,height:1080}});
const errors=[];page.on('pageerror',e=>errors.push(e.message));
await installCityFixture(page);
const started=performance.now();
await page.goto(`${url}/runs/city-fixture/overview?cityView=3d`);
await page.waitForFunction(()=>document.querySelector('[data-testid="city-canvas"]')?.getAttribute('data-ready')==='true');
const startupMs=performance.now()-started;
const gpu=await page.evaluate(()=>{const gl=document.querySelector('canvas').getContext('webgl2');const ext=gl.getExtension('WEBGL_debug_renderer_info');return ext?gl.getParameter(ext.UNMASKED_RENDERER_WEBGL):gl.getParameter(gl.RENDERER);});
const cdp=await page.context().newCDPSession(page);await cdp.send('Performance.enable');
await page.evaluate(()=>{
  window.__cityBench={frames:0,start:performance.now(),active:true};
  const animate=()=>{if(!window.__cityBench.active)return;document.querySelector('[aria-label="Rotate right"]')?.click();window.__cityBench.frames++;requestAnimationFrame(animate);};requestAnimationFrame(animate);
});
const initialRenderedFrames=await page.locator('[data-testid="city-canvas"]').getAttribute('data-render-frames').then(Number);
const samples=[];
const end=Date.now()+seconds*1000;
while(Date.now()<end){
  await page.waitForTimeout(Math.min(10000,Math.max(1,end-Date.now())));
  await cdp.send('HeapProfiler.collectGarbage');
  const metrics=await cdp.send('Performance.getMetrics');
  const reading=await page.evaluate(()=>({elapsedMs:performance.now()-window.__cityBench.start,frames:window.__cityBench.frames,renderedFrames:Number(document.querySelector('[data-testid="city-canvas"]')?.getAttribute('data-render-frames')),canvases:document.querySelectorAll('canvas').length,render:document.querySelector('.city3d-notes code')?.textContent}));
  samples.push({...reading,heapBytes:metrics.metrics.find(m=>m.name==='JSHeapUsedSize')?.value});
  await writeFile(output,JSON.stringify({status:'running',seconds,startupMs,gpu,errors,samples},null,2));
}
await page.evaluate(()=>{window.__cityBench.active=false;});
const result={status:'complete',seconds,startupMs,gpu,errors,samples,meanAnimationFps:samples.at(-1).frames/(samples.at(-1).elapsedMs/1000),meanRenderedFps:(samples.at(-1).renderedFrames-initialRenderedFrames)/(samples.at(-1).elapsedMs/1000)};
await writeFile(output,JSON.stringify(result,null,2));
console.log(JSON.stringify({output,status:result.status,startupMs,gpu,errors,meanAnimationFps:result.meanAnimationFps,meanRenderedFps:result.meanRenderedFps,first:samples[0],last:samples.at(-1)}));
await browser.close();
