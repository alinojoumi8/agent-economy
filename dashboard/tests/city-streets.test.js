import assert from 'node:assert/strict';
import test from 'node:test';
import {planCityStreets} from '../src/city/cityStreets.js';
const place=(id,x,z,regionId=1)=>({entityType:'place',entityId:id,regionId,provenance:'observed',position:[x,0,z]});

test('illustrative streets are deterministic and never change source positions',()=>{
  const source=[place(2,12,0),place(1,0,0),place(3,24,16)];
  const before=structuredClone(source),plan=planCityStreets(source);
  assert.deepEqual(plan,planCityStreets([...source].reverse()));
  assert.deepEqual(source,before);
  assert.ok(plan.roads.length>source.length);
  assert.ok(plan.trees.length>0);
  for(const road of plan.roads)for(const p of source){
    assert.ok(Math.abs(p.position[0]-road.x)>=road.width/2+2.2||Math.abs(p.position[2]-road.z)>=road.depth/2+2.2);
  }
});

test('no decorative district is invented for unlocated or absent places',()=>{
  assert.deepEqual(planCityStreets([]),{roads:[],lots:[],trees:[]});
  assert.deepEqual(planCityStreets([{...place(1,200,0),provenance:'derived'},{...place(2,0,0),entityType:'agent'}]),{roads:[],lots:[],trees:[]});
});

test('separate regions never gain an implied intercity road',()=>{
  const plan=planCityStreets([place(1,0,0),place(2,100,100,2)]);
  assert.equal(plan.roads.length,2);
  assert.ok(plan.roads.every(r=>r.width===8&&r.depth===3));
});
