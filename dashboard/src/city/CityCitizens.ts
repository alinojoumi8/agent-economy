import { BoxGeometry, Color, DynamicDrawUsage, Group, InstancedMesh, Matrix4, MeshLambertMaterial, OrthographicCamera, SphereGeometry, Vector3 } from 'three';
import type { CityInstance } from './cityProjection';
import { citizenPose, createCityDay } from './cityMotion.js';

type Day=ReturnType<typeof createCityDay>;
type Pose=ReturnType<typeof citizenPose>;
const HEIGHT=2.8;
const COATS=['#2457a6','#b3492b','#397660','#b07c24','#734d88','#31788d'];
const SKIN=['#ce946e','#8d593f','#e6b797','#b77850'];

/** Original, jointed citizens. One instanced batch per body part, no scene rebuild per frame. */
export class CityCitizens {
  readonly group=new Group();
  private items:CityInstance[]=[];
  private poses=new Map<string,Pose>();
  private parts=new Map<string,InstancedMesh>();
  private box=new BoxGeometry(1,1,1);
  private head=new SphereGeometry(1,8,6);
  private material=new MeshLambertMaterial({color:'#ffffff'});
  private scale=1;
  private root=new Matrix4();
  private joint=new Matrix4();
  private local=new Matrix4();
  private size=new Vector3();

  setItems(items:CityInstance[]){
    this.clear();this.items=items.filter(item=>item.entityType==='agent');
    if(!this.items.length)return;
    for(const name of ['torso','head','hair','arms','legs','shoes']){
      const pairs=['arms','legs','shoes'].includes(name);
      const mesh=new InstancedMesh(name==='head'?this.head:this.box,this.material,this.items.length*(pairs?2:1));
      mesh.instanceMatrix.setUsage(DynamicDrawUsage);mesh.frustumCulled=false;
      mesh.userData.keys=this.items.flatMap(item=>pairs?[item.key,item.key]:[item.key]);
      this.items.forEach((item,index)=>{
        const color=new Color(name==='torso'||name==='arms'?COATS[item.entityId%COATS.length]
          :name==='head'?SKIN[item.entityId%SKIN.length]:name==='legs'?'#28394b':name==='hair'?'#3d3028':'#192329');
        mesh.setColorAt(index*(pairs?2:1),color);if(pairs)mesh.setColorAt(index*2+1,color);
      });
      this.parts.set(name,mesh);this.group.add(mesh);
    }
  }
  update(day:Day,elapsed:number,reduced:boolean,camera:OrthographicCamera,height:number){
    // Keep a readable silhouette when the complete district is fitted on phones.
    // At very wide scales citizens remain illustrative symbols, never real sizes.
    const vertical=new Vector3(0,HEIGHT,0).transformDirection(camera.matrixWorldInverse);
    const pixels=Math.abs(vertical.y)*HEIGHT*height*camera.zoom/110;
    this.scale=Math.max(1,Math.min(2.4,28/Math.max(1,pixels)));
    for(const [index,item] of this.items.entries()){
      const pose=citizenPose(day,item,elapsed,reduced);this.poses.set(item.key,pose);
      this.root.makeRotationY(pose.heading);this.root.scale(this.size.setScalar(this.scale));
      this.root.setPosition(...pose.position as [number,number,number]);
      const bob=Math.abs(pose.stride)*.055;
      this.part('torso',index,0,1.64+bob,0,.72,.86,.43);
      this.part('head',index,0,2.38+bob,0,.34,.39,.34);
      this.part('hair',index,0,2.68+bob,-.035,.58,.19,.53);
      for(const [side,sign] of [-1,1].entries()){
        this.part('arms',index*2+side,sign*.49,1.99+bob,0,.22,.85,.25,sign*pose.stride,-.37);
        this.part('legs',index*2+side,sign*.21,1.23+bob,0,.27,1.02,.29,-sign*pose.stride,-.5);
        this.part('shoes',index*2+side,sign*.21,1.23+bob,0,.32,.2,.53,-sign*pose.stride,-1.02,.11);
      }
    }
    for(const mesh of this.parts.values()){
      mesh.instanceMatrix.needsUpdate=true;
      // Raycasts must use the current limb positions, not a cached earlier pose.
      mesh.boundingSphere=null;
    }
  }
  private part(name:string,index:number,x:number,y:number,z:number,sx:number,sy:number,sz:number,angle=0,drop=0,forward=0){
    this.joint.makeRotationX(angle);this.joint.setPosition(x,y,z);
    this.local.makeScale(sx,sy,sz);this.local.setPosition(0,drop,forward);
    this.local.premultiply(this.joint).premultiply(this.root);
    this.parts.get(name)!.setMatrixAt(index,this.local);
  }
  position(key:string){return this.poses.get(key)?.position;}
  labelHeight(){return HEIGHT*this.scale+2;}
  /** Read back the submitted matrices; evidence can check real geometry and gait. */
  evidence(camera:OrthographicCamera,width:number,height:number){
    const matrix=new Matrix4(),point=new Vector3();
    return this.items.map((item,index)=>{
      const pose=this.poses.get(item.key);
      const mesh=this.parts.get('head')!;mesh.getMatrixAt(index,matrix);
      point.setFromMatrixPosition(matrix).project(camera);
      const head={x:(point.x+1)*width/2,y:(1-point.y)*height/2};
      const legs=this.parts.get('legs')!;legs.getMatrixAt(index*2,matrix);
      const legMatrix=matrix.toArray();
      point.set(...(pose?.position||item.position) as [number,number,number]).project(camera);
      return {id:item.entityId,...pose,screen:{x:(point.x+1)*width/2,y:(1-point.y)*height/2},head,
        heightPx:Math.abs(head.y-(1-point.y)*height/2)*HEIGHT/2.38,legMatrix};
    });
  }
  clear(){for(const mesh of this.parts.values())mesh.dispose();this.parts.clear();this.group.clear();this.poses.clear();this.items=[];}
  dispose(){this.clear();this.box.dispose();this.head.dispose();this.material.dispose();}
}
