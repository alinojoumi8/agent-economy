import test from 'node:test';
import assert from 'node:assert/strict';
import { createRoadLayout, roadPath, pointOnRoadPath, NAV_CLEARANCE } from '../src/city/cityNavigation.js';
const place=(id,x,z,regionId=1,kind='workplace')=>({key:`place:${id}`,renderKey:`place:${id}`,entityId:id,entityType:'place',provenance:'observed',regionId,kind,position:[x,0,z]});

function checkPath(layout,path){
  assert.ok(path&&path.length>0);
  for(let d=0;d<=path.length;d+=.15){
    const [x,,z]=pointOnRoadPath(path,d).position;
    assert.ok(layout.scenery.roads.some(r=>Math.abs(x-r.x)<=r.width/2+1e-6&&Math.abs(z-r.z)<=r.depth/2+1e-6),'walker left painted road');
    for(const b of layout.footprints){
      const clearance=Math.hypot(Math.max(Math.abs(x-b.x)-b.half,0),Math.max(Math.abs(z-b.z)-b.half,0));
      assert.ok(clearance>=NAV_CLEARANCE-1e-6,'walker body entered building clearance');
    }
  }
}

test('roads and walkers share safe detours around intervening buildings',()=>{
  const source=[place(1,0,0),place(2,22,0),place(3,11,5,1,'residential_district')];
  const before=JSON.stringify(source),layout=createRoadLayout(source);
  const route=roadPath(layout,layout.ports.get(1),layout.ports.get(2));
  checkPath(layout,route);
  assert.ok(route.points.some(p=>p[2]!==route.points[0][2]),'a blocking building requires a turn');
  assert.deepEqual(layout.scenery,createRoadLayout([...source].reverse()).scenery);
  assert.equal(JSON.stringify(source),before);
});

test('same place stays still, unknown and cross-region destinations cannot create roads',()=>{
  const layout=createRoadLayout([place(1,0,0),place(2,20,0,2)]);
  const start=layout.ports.get(1);
  assert.equal(roadPath(layout,start,layout.ports.get(2)),null);
  assert.equal(roadPath(layout,start,undefined),null);
  const same=roadPath(layout,start,start);
  assert.equal(same.length,0);assert.deepEqual(pointOnRoadPath(same,100).position,same.points[0]);
  assert.equal(createRoadLayout([ {...place(1,0,0),provenance:'derived'} ]).ports.size,0);
});

test('dense districts, aliases and large housing blocks keep every complete segment clear',()=>{
  const places=Array.from({length:36},(_,n)=>place(n+1,(n%6)*6.4,Math.floor(n/6)*6.4,1,n%4?'workplace':'residential_district'));
  const alias={...places[0],entityType:'firm',entityId:99,key:'firm:99'};
  const layout=createRoadLayout([...places,alias]);
  assert.equal(layout.footprints.length,36);
  for(let id=1;id<36;id++)checkPath(layout,roadPath(layout,layout.ports.get(id),layout.ports.get(id+1)));
});
