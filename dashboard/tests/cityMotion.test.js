import test from 'node:test';
import assert from 'node:assert/strict';
import { createCityDay, citizenPose } from '../src/city/cityMotion.js';

const citizen = id => ({entityType:'agent',entityId:id,key:`agent:${id}`,position:[8,0,9]});
const row = (id,slot,place,x=.5) => ({agent_id:id,slot,place_id:place,x,y:.5});
const rows = id => [row(id,'morning',1),row(id,'business',2,.6),row(id,'evening',1)];
const city = presence => ({envelope:{data:{presence}},instances:[citizen(1),citizen(2),
  ...[1,2].map(id=>({entityType:'place',entityId:id,regionId:1,provenance:'observed',position:[(id-1)*16,0,0]}))]});

test('recorded day translates a citizen and changes gait without changing the source',()=>{
  const source=city([...rows(1),...['morning','business','evening'].map(slot=>row(2,slot,1))]);
  const before=JSON.stringify(source),day=createCityDay(source);
  const a=citizenPose(day,citizen(1),1000),b=citizenPose(day,citizen(1),4000);
  assert.notDeepEqual(a.position,b.position);
  assert.notEqual(a.stride,b.stride);
  assert.equal(a.fromPlace,1);assert.equal(a.toPlace,2);
  assert.ok(b.distance>a.distance);
  assert.deepEqual(citizenPose(day,citizen(2),1000).position,citizenPose(day,citizen(2),4000).position);
  assert.equal(citizenPose(day,citizen(2),4000).stride,0);
  assert.equal(JSON.stringify(source),before);
});

test('private, incomplete, malformed and out-of-roster presence never invents a journey',()=>{
  const day=createCityDay(city([...rows(null),...rows(99),row(1,'morning',1),row(1,'business',2,NaN),...rows(2).map(r=>({...r,x:3}))]));
  assert.equal(day.agents.length,0);assert.equal(day.movers,0);
  assert.deepEqual(citizenPose(day,citizen(1),4000).position,[8,0,9]);
  assert.equal(citizenPose(day,citizen(1),4000).stride,0);
});

test('reduced motion uses only anchor placements and has no gait; a new day starts at morning',()=>{
  const day=createCityDay(city(rows(1)));
  const start=citizenPose(day,citizen(1),0,true);
  assert.deepEqual(citizenPose(day,citizen(1),1000,true).position,start.position);
  const later=citizenPose(day,citizen(1),20000,true);
  assert.equal(later.stride,0);
  assert.ok([1,2].includes(later.placeId));
  assert.deepEqual(citizenPose(createCityDay(city(rows(1))),citizen(1),0).position,start.position);
});

test('an unknown or disconnected leg holds the entire itinerary without teleporting',()=>{
  for(const disconnected of [false,true]){
    const source=city(rows(1));
    if(disconnected)source.instances.at(-1).regionId=2;else source.instances.pop();
    const day=createCityDay(source),start=citizenPose(day,citizen(1),0);
    assert.equal(day.movers,0);assert.equal(day.byId.get(1).routeBlocked,true);
    for(let elapsed=0;elapsed<90000;elapsed+=500)assert.deepEqual(citizenPose(day,citizen(1),elapsed),start);
  }
});

test('citizens with no itinerary keep separate safe waiting points at their public place',()=>{
  const source=city([]);
  const citizens=source.instances.filter(item=>item.entityType==='agent');
  citizens.forEach(item=>{item.placeId=1;});
  const before=JSON.stringify(source),day=createCityDay(source);
  const first=citizenPose(day,citizens[0],0),second=citizenPose(day,citizens[1],0);
  assert.notDeepEqual(first.position,second.position);
  for(const item of citizens){
    const pose=citizenPose(day,item,0),[x,,z]=pose.position;
    assert.ok(day.navigation.scenery.roads.some(r=>Math.abs(x-r.x)<=r.width/2&&Math.abs(z-r.z)<=r.depth/2));
    assert.deepEqual(citizenPose(day,item,40000),pose);
  }
  assert.equal(day.movers,0);assert.equal(day.agents.length,0);assert.equal(JSON.stringify(source),before);
});
