import { BoxGeometry, CylinderGeometry, Group, InstancedMesh, Matrix4, MeshLambertMaterial, SphereGeometry } from 'three';
import type { CityInstance } from './cityProjection';
import { planCityStreets } from './cityStreets';

/** Batched presentation geometry. These roads imply no travel or land ownership. */
export function buildCityScenery(instances:CityInstance[]):Group {
  const group=new Group(), plan=planCityStreets(instances);
  type Shape={x:number;y:number;z:number;w:number;h:number;d:number};
  const boxes=(color:string,shapes:Shape[])=>{
    if(!shapes.length)return;
    const mesh=new InstancedMesh(new BoxGeometry(1,1,1),new MeshLambertMaterial({color}),shapes.length);
    const matrix=new Matrix4();
    shapes.forEach((p,i)=>{matrix.makeScale(p.w,p.h,p.d);matrix.setPosition(p.x,p.y,p.z);mesh.setMatrixAt(i,matrix);});
    mesh.instanceMatrix.needsUpdate=true;mesh.computeBoundingSphere();group.add(mesh);
  };
  boxes('#c1c4b8',plan.lots.map(p=>({x:p.x,y:-.06,z:p.z,w:6,h:.12,d:6})));
  boxes('#b8bdb8',plan.roads.map(p=>({x:p.x,y:-.07,z:p.z,w:p.width+.9,h:.10,d:p.depth+.9})));
  boxes('#697678',plan.roads.map(p=>({x:p.x,y:-.015,z:p.z,w:p.width,h:.035,d:p.depth})));
  const markings:Shape[]=[];
  for(const road of plan.roads){
    const horizontal=road.width>road.depth,length=horizontal?road.width:road.depth;
    for(let offset=-length/2+1.2;offset<length/2-.6;offset+=2.4){
      markings.push({x:road.x+(horizontal?offset:0),y:.008,z:road.z+(horizontal?0:offset),w:horizontal?1:.09,h:.008,d:horizontal?.09:1});
    }
  }
  boxes('#d8d6ba',markings);
  if(plan.trees.length){
    const matrix=new Matrix4();
    const trunks=new InstancedMesh(new CylinderGeometry(.10,.15,1,5),new MeshLambertMaterial({color:'#75614b'}),plan.trees.length);
    const crowns=new InstancedMesh(new SphereGeometry(.75,7,5),new MeshLambertMaterial({color:'#557e56',flatShading:true}),plan.trees.length);
    plan.trees.forEach((p,i)=>{
      matrix.makeScale(1,p.height,1);matrix.setPosition(p.x,p.height/2,p.z);trunks.setMatrixAt(i,matrix);
      matrix.makeScale(1,p.height*.65,1);matrix.setPosition(p.x,p.height,p.z);crowns.setMatrixAt(i,matrix);
    });
    for(const mesh of [trunks,crowns]){mesh.instanceMatrix.needsUpdate=true;mesh.computeBoundingSphere();group.add(mesh);}
  }
  group.userData.provenance='illustrative';
  return group;
}

export function disposeCityScenery(group:Group){
  group.traverse(child=>{
    if(child instanceof InstancedMesh){child.dispose();child.geometry.dispose();
      for(const material of Array.isArray(child.material)?child.material:[child.material])material.dispose();}
  });
  group.clear();
}
