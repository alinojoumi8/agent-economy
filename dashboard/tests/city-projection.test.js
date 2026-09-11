import assert from 'node:assert/strict';
import test from 'node:test';
import { projectCity, cityIdentity, activityForCity } from '../src/city/cityProjectionCore.js';
const envelope = (data = {}, extra = {}) => ({run_id:'run',fork_id:null,tick:2,semantics_version:12,projection_version:1,policy_version:1,view_key:'public',snapshot_version:'s12-t2',event_cursor:9,projection:'world.map',data,...extra});
test('malformed and unsupported envelopes fail closed', () => {
  for (const e of [null, {}, envelope({}, {tick:-1}), envelope({}, {projection_version:4}), envelope({agents:'bad'})]) assert.throws(() => projectCity(e));
});
test('empty city remains empty and derived identity includes authorization and lineage', () => {
  assert.deepEqual(projectCity(envelope()).instances, []);
  assert.notEqual(cityIdentity(envelope()),cityIdentity(envelope({}, {view_key:'operator'})));
  assert.notEqual(cityIdentity(envelope()),cityIdentity(envelope({}, {fork_id:'fork'})));
});
test('derived layout is deterministic, order independent, unique, and stable as IDs arrive', () => {
  const agents = Array.from({length:300}, (_,i)=>({id:i+1,name:`Agent ${i}`,region_id:1}));
  const a=projectCity(envelope({agents})), b=projectCity(envelope({agents:[...agents].reverse()}));
  assert.deepEqual(a.instances,b.instances);
  assert.equal(new Set(a.instances.map(i=>JSON.stringify(i.position))).size,300);
  const c=projectCity(envelope({agents:[{id:999,name:'Later'},...agents]}));
  assert.deepEqual(a.instances.map(i=>i.position),c.instances.filter(i=>i.entityId!==999).map(i=>i.position));
});
test('places share a building with their firm while source bounds and absent coordinates are explicit', () => {
  const p=projectCity(envelope({places:[{id:7,name:'Workshop',kind:'firm_workplace',x:.5,y:.5}],organizations:[{id:4,place_id:7,name:'Maker',sector:'manufacturing'}],agents:[{id:1,name:'Worker',place_id:7,x:.5,y:.5}]}));
  assert.equal(p.instances[0].entityType,'agent');
  const firm=p.instances.find(i=>i.entityType==='firm'), place=p.instances.find(i=>i.entityType==='place');
  assert.equal(firm.renderKey,place.renderKey);
  assert.equal(place.assetKey,'workshop');
  assert.equal(place.provenance,'observed');
  assert.ok(p.instances.find(i=>i.entityType==='agent').position.every(Number.isFinite));
  assert.equal(projectCity(envelope({places:[{id:1,x:500,y:0}]})).instances[0].provenance,'derived');
});
test('duplicates reject; unknown kinds neutral; future and closed places absent', () => {
  assert.throws(()=>projectCity(envelope({agents:[{id:1},{id:1}]})));
  const p=projectCity(envelope({places:[{id:1,kind:'unrecognized'},{id:2,closed_tick:2},{id:3,created_tick:3}]}));
  assert.equal(p.instances.length,1); assert.equal(p.instances[0].assetKey,'neutral');
});
test('activity uses only coherent, committed known events, deduplicates and caps bursts', () => {
  const e=envelope({agents:[{id:1}]}), city=projectCity(e);
  const events=Array.from({length:70},(_,i)=>({id:i+1,tick:2,kind:'action_rejected',payload:{agent_id:1}}));
  const snapshot={...e,projection:'world.snapshot',data:{events:{items:[...events,events[0],{id:100,tick:3,kind:'action_rejected',payload:{agent_id:1}},{id:101,tick:2,kind:'made_up',payload:{agent_id:1}}]}}};
  assert.equal(activityForCity(city,snapshot).length,32);
  assert.equal(activityForCity(city,{...snapshot,tick:1}).length,0);
  assert.equal(activityForCity(city,{...snapshot,view_key:'private'}).length,0);
});
test('unknown industry neutral, children inherit derived provenance and region anchors cannot collide',()=>{
  const city=projectCity(envelope({regions:[{id:1,x:.5,y:.5},{id:2,x:.5-1.25/160,y:.5+1.25/160}],agents:[{id:1,region_id:1,place_id:7},{id:2,region_id:2}],places:[{id:7}],organizations:[{id:4,sector:'alien',place_id:7}]}));
  assert.equal(city.instances.find(i=>i.entityType==='agent'&&i.entityId===1).provenance,'derived');
  assert.equal(city.instances.find(i=>i.entityType==='firm').assetKey,'neutral');
  assert.notDeepEqual(city.instances[0].position,city.instances[1].position);
  const e=envelope(); assert.notEqual(cityIdentity(e),cityIdentity({...e,snapshot_version:'revised'}));
});
test('real civic events preserve aggregate attendance privacy and malformed activity fails closed',()=>{
  const e=envelope({agents:[{id:1}],places:[{id:2,kind:'licensing_office'}]}),city=projectCity(e);
  assert.deepEqual(activityForCity(city,{...e,projection:'world.snapshot',data:{events:{items:{}}}}),[]);
  const acts=activityForCity(city,{...e,projection:'world.snapshot',snapshot_version:'different-projection-hash',data:{events:{items:[
    {id:10,tick:2,kind:'business_permit_approved',payload:{applicant_agent_id:1}},
    {id:11,tick:2,kind:'civic_appointment_attended',payload:{place_id:2,agent_id:1}},
  ]}}});
  assert.equal(acts.length,2);
  assert.deepEqual(acts.find(a=>a.id===11).targets,[city.instances.find(i=>i.entityType==='place').key]);
});
test('derived display slots never overlap the recorded coordinate square',()=>{
  const city=projectCity(envelope({agents:[{id:1},{id:300}],places:[{id:1,x:.5,y:.5}]}));
  for(const item of city.instances.filter(i=>i.provenance==='derived'))assert.ok(item.position[0]>80);
});
test('captured legacy and civic provider-free envelopes map all visible identities once',async()=>{
  const {readFile}=await import('node:fs/promises');
  for(const name of ['legacy','civic']){
    const fixture=JSON.parse(await readFile(new URL(`./fixtures/city-${name}.json`,import.meta.url),'utf8'));
    const data=fixture.envelope.data, city=projectCity(fixture.envelope);
    assert.equal(city.instances.length,data.agents.length+data.places.length+data.organizations.length);
    assert.equal(new Set(city.instances.map(i=>i.key)).size,city.instances.length);
    assert.ok(city.instances.every(i=>i.position.every(Number.isFinite)));
  }
});
test('banks have independent public identity and stable derived slots without inferred balances',()=>{
  const city=projectCity(envelope({banks:[{id:1,name:'Civic Bank',region_id:1,status:'failed'}],agents:[{id:1}],places:[{id:1}],organizations:[{id:1}]}));
  const bank=city.instances.find(i=>i.entityType==='bank');
  assert.equal(bank.assetKey,'bank');assert.equal(bank.status,'failed');assert.equal(bank.provenance,'derived');
  assert.equal(new Set(city.instances.map(i=>JSON.stringify(i.position))).size,4);
  assert.ok(!('balance_cents' in bank));
});
