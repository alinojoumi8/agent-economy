import test from 'node:test';
import assert from 'node:assert/strict';
import { projectCity, activityForCity } from '../src/city/cityProjectionCore.js';
import { deriveCityModel } from '../src/lib/civicCity.js';
import { cityActivityMarkers, validateActivity } from '../src/app/cityProjection.js';
import { parseObserverViewState, patchObserverViewState } from '../src/app/observerViewStateCore.js';
import { cityEvidenceParams, cityWorkspaceHref } from '../src/app/cityNavigation.js';

const frame={run_id:'city',fork_id:null,tick:3,semantics_version:13,projection_version:2,policy_version:1,view_key:'ordinary',snapshot_version:'day3',event_cursor:125};
test('all renderers share complete native actor markers beyond the visible page and former caps',()=>{
  const agents=Array.from({length:125},(_,n)=>({id:n+1,name:`Agent ${n+1}`}));
  const events=agents.map(a=>({id:a.id,tick:3,kind:'goods_sale',actor_ids:[a.id],outcome:a.id===125?'pending':'completed'}));
  const map={...frame,projection:'world.map',data:{agents}};
  const activity={...frame,projection:'city.activity',data:{tick:3,source:'committed',total:125,items:events.slice(0,40),marker_events:events}};
  assert.equal(validateActivity(activity,map),activity);
  const markers=cityActivityMarkers(activity);
  const atlas=deriveCityModel({agents,map:map.data,events:markers,tick:'3',historical:true});
  const three=activityForCity(projectCity(map),activity);
  assert.equal(atlas.agents.filter(a=>a.isActive).length,125);
  assert.equal(three.length,125);
  assert.equal(atlas.agents.find(a=>a.id===125).activityState,'pending');
  assert.equal(three.find(e=>e.id===125).state,'pending');
  assert.deepEqual(activityForCity(projectCity(map),{...activity,tick:4}),[]);
  assert.throws(()=>validateActivity({...activity,view_key:'private'},map),/context/);
});
test('switching presentation preserves selection, filters, day and evidence return context',()=>{
  let params=new URLSearchParams('tick=3&agent=7&activity=markets&actor=7&population=all&q=Ada&camera=40,60,4');
  for(const view of ['3d','list','atlas']) {
    params=patchObserverViewState(params,{view});
    const state=parseObserverViewState(params);
    assert.equal(state.agent,7);assert.equal(state.tick,'3');assert.equal(state.activity,'markets');assert.equal(state.actor,7);
    const evidence=cityEvidenceParams(state);
    const returned=new URL(cityWorkspaceHref('city',{...state,city:evidence.get('city')}),'http://local');
    assert.equal(returned.searchParams.get('activity'),'markets');
    assert.equal(returned.searchParams.get('actor'),'7');
    assert.equal(parseObserverViewState(returned.searchParams).view,view);
  }
});
test('old 3D links can leave 3D and retain a typed selection',()=>{
  const legacy=new URLSearchParams('cityView=3d&cityType=bank&cityEntity=3&tick=2');
  assert.equal(parseObserverViewState(legacy).institution,'bank:3');
  assert.equal(parseObserverViewState(patchObserverViewState(legacy,{view:'atlas'})).view,'atlas');
});
