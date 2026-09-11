import { AmbientLight, BoxGeometry, DirectionalLight, GridHelper, Group, InstancedMesh, Matrix4,
  Mesh, MeshLambertMaterial, MOUSE, TOUCH, OrthographicCamera, Raycaster, RingGeometry, Scene, Vector2, Vector3, WebGLRenderer } from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { disposeKit, loadCityAssets, type AssetKit } from './assetLoader';
import type { CityActivity, CityInstance, CityProjection } from './cityProjection';
export type SceneStats={calls:number;triangles:number;geometries:number;textures:number;frames:number};
export class CityScene {
  private renderer:WebGLRenderer;
  private scene=new Scene();
  private camera=new OrthographicCamera(-70,70,55,-55,.1,1000);
  private controls:OrbitControls;
  private buildings=new Group();
  private ground=new Group();
  private markers=new Group();
  private proposal:Mesh|null=null;
  private kit:AssetKit|null=null;
  private abort=new AbortController();
  private observer:ResizeObserver;
  private projection:CityProjection|null=null;
  private selected:string|null=null;
  private filtered:CityInstance[]=[];
  private events:CityActivity[]=[];
  private alive=true;
  private failed=false;
  private effects=new Map<number,number>();
  private effectScope="";
  private frame=0;
  private frameCount=0;
  private initiallyFramed=false;
  private running=false;
  private reduced=window.matchMedia('(prefers-reduced-motion: reduce)');
  private pointer=new Vector2();
  private ray=new Raycaster();
  private pointerStart=[0,0];
  private markerGeometry=new RingGeometry(1.8,2.1,32);
  private selectionMaterial=new MeshLambertMaterial({color:'#2457D6',emissive:'#2457D6',emissiveIntensity:.3,side:2});
  private settledMaterial=new MeshLambertMaterial({color:'#B7D64A',emissive:'#B7D64A',emissiveIntensity:.25,side:2});
  private rejectedMaterial=new MeshLambertMaterial({color:'#E44732',emissive:'#E44732',emissiveIntensity:.25,side:2});
  constructor(private host:HTMLElement,private onPick:(key:string)=>void,private onReady:()=>void,
    private onError:(message:string)=>void,private onStats:(stats:SceneStats)=>void){
    this.renderer=new WebGLRenderer({antialias:false,alpha:false,powerPreference:'low-power'});
    // Canvas contains geometry only; HTML labels stay at native resolution.
    // A bounded render scale keeps the 300-citizen view usable on software GPUs.
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio,1.5)*.75);
    this.renderer.setClearColor('#dfe7e4');
    this.renderer.domElement.setAttribute('aria-label','Interactive 3D city. Use the entity list and camera buttons for keyboard navigation.');
    this.renderer.domElement.setAttribute('role','img');
    host.append(this.renderer.domElement);
    this.camera.position.set(95,100,110);
    this.controls=new OrbitControls(this.camera,this.renderer.domElement);
    this.controls.mouseButtons={LEFT:MOUSE.PAN,MIDDLE:MOUSE.DOLLY,RIGHT:MOUSE.ROTATE};
    this.controls.touches={ONE:TOUCH.PAN,TWO:TOUCH.DOLLY_PAN};
    this.controls.screenSpacePanning=true;
    this.controls.enableDamping=false;
    this.controls.maxPolarAngle=Math.PI/2.6;
    this.controls.minPolarAngle=.25;
    this.controls.minZoom=.35;this.controls.maxZoom=12;
    this.controls.addEventListener('change',this.requestRender);
    this.controls.update();
    this.scene.add(new AmbientLight('#eaf3ff',2.1));
    const sun=new DirectionalLight('#fff4df',3.3);sun.position.set(-35,80,50);this.scene.add(sun);
    this.scene.add(this.ground,this.buildings,this.markers);
    this.observer=new ResizeObserver(()=>this.resize());this.observer.observe(host);
    this.renderer.domElement.addEventListener('pointerdown',this.pointerDown);
    this.renderer.domElement.addEventListener('pointerup',this.pointerUp);
    this.renderer.domElement.addEventListener('webglcontextlost',this.contextLost);
    this.reduced.addEventListener('change',this.requestRender);
    this.resize();
    loadCityAssets(this.abort.signal).then(kit=>{
      if(!this.alive){disposeKit(kit);return;}
      this.kit=kit;this.rebuild();this.onReady();
    }).catch(error=>{if(this.alive)this.onError(error instanceof Error?error.message:'City assets unavailable.');});
  }
  private contextLost=(event:Event)=>{event.preventDefault();this.failed=true;this.running=false;cancelAnimationFrame(this.frame);this.frame=0;this.onError('3D graphics context was lost. Switch to the 2D atlas or reload the city.');};
  private pointerDown=(event:PointerEvent)=>{this.pointerStart=[event.clientX,event.clientY];};
  private pointerUp=(event:PointerEvent)=>{
    if(event.button!==0)return;
    if(Math.hypot(event.clientX-this.pointerStart[0],event.clientY-this.pointerStart[1])>5)return;
    const rect=this.renderer.domElement.getBoundingClientRect();
    this.pointer.set((event.clientX-rect.left)/rect.width*2-1,-(event.clientY-rect.top)/rect.height*2+1);
    this.ray.setFromCamera(this.pointer,this.camera);
    const hit=this.ray.intersectObjects(this.buildings.children).find(i=>i.instanceId!==undefined);
    if(hit&&hit.instanceId!==undefined){const key=hit.object.userData.keys?.[hit.instanceId];if(key)this.onPick(key);}
  };
  private resize(){
    const width=Math.max(1,this.host.clientWidth),height=Math.max(1,this.host.clientHeight);
    this.renderer.setSize(width,height);const aspect=width/height;
    this.camera.left=-55*aspect;this.camera.right=55*aspect;this.camera.top=55;this.camera.bottom=-55;
    this.camera.updateProjectionMatrix();this.requestRender();
  }
  private requestRender=()=>{if(this.alive&&!this.failed&&!this.frame)this.frame=requestAnimationFrame(this.render);};
  private render=(time:number)=>{
    this.frame=0;if(!this.alive||this.failed)return;
    this.markers.scale.setScalar(1); // Rings animate individually, never scale entity positions.
    for(const child of this.markers.children){
      const pulse=this.running&&!this.reduced.matches&&child.userData.activityUntil>time?1+.08*Math.sin(time*.004):1;
      child.scale.setScalar(pulse);
    }
    this.renderer.render(this.scene,this.camera);this.frameCount++;
    this.host.dataset.renderFrames=String(this.frameCount);
    const info=this.renderer.info;
    this.onStats({calls:info.render.calls,triangles:info.render.triangles,geometries:info.memory.geometries,textures:info.memory.textures,frames:this.frameCount});
    if(this.running&&!this.reduced.matches&&this.events.some(e=>(this.effects.get(e.id)||0)>time))this.requestRender();
  };
  update(projection:CityProjection,instances:CityInstance[],selected:string|null,events:CityActivity[],running:boolean){
    if(this.failed)return;
    const scope=JSON.stringify([projection.envelope.run_id,projection.envelope.fork_id,projection.envelope.view_key]);
    if(scope!==this.effectScope){this.effects.clear();this.effectScope=scope;}
    for(const event of events)if(!this.effects.has(event.id))this.effects.set(event.id,performance.now()+1400);
    while(this.effects.size>512)this.effects.delete(this.effects.keys().next().value!);
    const changed=this.projection!==projection||this.filtered!==instances;
    this.projection=projection;this.filtered=instances;this.selected=selected;this.events=events;this.running=running;
    if(changed)this.rebuild();else this.updateMarkers();
    this.requestRender();
  }
  private clearInstances(){for(const child of this.buildings.children)if(child instanceof InstancedMesh)child.dispose();this.buildings.clear();}
  private clearGround(){for(const child of this.ground.children){if(child instanceof Mesh||child instanceof GridHelper){child.geometry.dispose();const m=child.material;if(Array.isArray(m))m.forEach(x=>x.dispose());else m.dispose();}}this.ground.clear();}
  private rebuild(){
    if(!this.kit||!this.projection)return;
    this.clearInstances();this.clearGround();
    const byRender=new Map<string,CityInstance>();
    // Firm aliases select their firm's inspector while reusing the place geometry.
    for(const item of this.filtered){const prior=byRender.get(item.renderKey);if(!prior||item.entityType==='firm')byRender.set(item.renderKey,item);}
    const families=new Map<string,CityInstance[]>();
    for(const item of byRender.values()){const group=families.get(item.assetKey)||[];group.push(item);families.set(item.assetKey,group);}
    const matrix=new Matrix4();
    for(const [key,items] of families){
      for(const part of this.kit.get(key)||this.kit.get('neutral')||[]){
        const mesh=new InstancedMesh(part.geometry,part.material,items.length);
        mesh.userData.keys=items.map(i=>i.key);
        items.forEach((item,index)=>{matrix.makeTranslation(...item.position);mesh.setMatrixAt(index,matrix);});
        mesh.instanceMatrix.needsUpdate=true;mesh.computeBoundingSphere();this.buildings.add(mesh);
      }
    }
    const extent=Math.max(65,...this.projection.instances.flatMap(i=>[Math.abs(i.position[0])+12,Math.abs(i.position[2])+12]));
    const ground=new Mesh(new BoxGeometry(extent*2,1,extent*2),new MeshLambertMaterial({color:'#bbcbb9'}));
    ground.position.y=-.6;this.ground.add(ground);
    const grid=new GridHelper(extent*2,Math.ceil(extent/4),'#a3b6a6','#acbeae');grid.position.y=-.075;this.ground.add(grid);
    for(const region of this.projection.regions){
      const district=new Mesh(new BoxGeometry(34,.08,34),new MeshLambertMaterial({color:'#e1e7dd'}));
      district.position.set(region.position[0],-.1,region.position[2]);this.ground.add(district);
      for(const offset of [-12,-4,4,12]){
        const street=new Mesh(new BoxGeometry(.5,.025,32),new MeshLambertMaterial({color:'#a5b1ac'}));
        street.position.set(region.position[0]+offset,-.04,region.position[2]);this.ground.add(street);
      }
      const avenue=new Mesh(new BoxGeometry(32,.02,1.1),new MeshLambertMaterial({color:'#74868b'}));
      avenue.position.set(region.position[0],-.055,region.position[2]-5);this.ground.add(avenue);
    }
    this.updateMarkers();
    if(!this.initiallyFramed){
      this.initiallyFramed=true;
      if(this.projection.regions.length&&this.filtered.some(i=>i.provenance==='observed'))this.focusRegion(this.projection.regions[0].id);else this.fitVisible();
    }
    this.requestRender();
  }
  private updateMarkers(){
    this.markers.clear();
    for(const item of this.filtered){
      const selected=item.key===this.selected||item.renderKey===this.projection?.instances.find(i=>i.key===this.selected)?.renderKey;
      const activity=this.events.find(e=>e.targets.includes(item.key));
      if(!selected&&!activity)continue;
      const ring=new Mesh(this.markerGeometry,selected?this.selectionMaterial:activity?.state==='rejected'?this.rejectedMaterial:this.settledMaterial);
      ring.rotation.x=-Math.PI/2;ring.position.set(item.position[0],.05,item.position[2]);ring.userData.activityUntil=activity?(this.effects.get(activity.id)||0):0;this.markers.add(ring);
    }
  }
  cameraAction(action:'reset'|'left'|'right'|'in'|'out'|'north'|'south'|'east'|'west'){
    if(action==='reset'){this.fitVisible();return;}
    else if(action==='in'||action==='out')this.camera.zoom=Math.max(.35,Math.min(12,this.camera.zoom*(action==='in'?1.3:1/1.3)));
    else if(action==='left'||action==='right'){
      const offset=this.camera.position.clone().sub(this.controls.target).applyAxisAngle(new Vector3(0,1,0),action==='left'?Math.PI/4:-Math.PI/4);
      this.camera.position.copy(this.controls.target).add(offset);
    }else{
      const delta=new Vector3(action==='east'?5:action==='west'?-5:0,0,action==='south'?5:action==='north'?-5:0);
      this.controls.target.add(delta);this.camera.position.add(delta);
    }
    this.camera.updateProjectionMatrix();this.controls.update();this.requestRender();
  }
  clear(){
    this.running=false;this.projection=null;this.filtered=[];this.events=[];
    this.clearInstances();this.clearGround();this.markers.clear();this.preview(null);this.requestRender();
  }
  fitVisible(derivedOnly=false){
    const items=this.filtered.filter(i=>!derivedOnly||i.provenance==='derived');if(!items.length)return;
    const xs=items.map(i=>i.position[0]),zs=items.map(i=>i.position[2]);
    const minX=Math.min(...xs),maxX=Math.max(...xs),minZ=Math.min(...zs),maxZ=Math.max(...zs);
    const target=new Vector3((minX+maxX)/2,0,(minZ+maxZ)/2);
    this.controls.target.copy(target);this.camera.position.copy(target).add(new Vector3(95,100,110));
    this.camera.zoom=Math.max(.35,Math.min(4,90/(Math.hypot(maxX-minX,maxZ-minZ)+15)));
    this.camera.updateProjectionMatrix();this.controls.update();this.requestRender();
  }
  preview(proposal:{x:number;y:number;label:string}|null){
    if(this.proposal){this.scene.remove(this.proposal);this.proposal.geometry.dispose();(this.proposal.material as MeshLambertMaterial).dispose();this.proposal=null;}
    if(proposal){
      const mesh=new Mesh(new BoxGeometry(3,4,3),new MeshLambertMaterial({color:'#2457d6',wireframe:true}));
      mesh.position.set((proposal.x-.5)*160,2,(proposal.y-.5)*160);this.scene.add(mesh);this.proposal=mesh;
      const target=new Vector3(mesh.position.x,0,mesh.position.z),delta=target.clone().sub(this.controls.target);
      this.camera.position.add(delta);this.controls.target.copy(target);this.camera.zoom=3;
      this.camera.updateProjectionMatrix();this.controls.update();
    }
    this.requestRender();
  }
  focusRegion(id:number){
    const region=this.projection?.regions.find(r=>r.id===id);if(!region)return;
    const target=new Vector3(...region.position),delta=target.clone().sub(this.controls.target);
    this.camera.position.add(delta);this.controls.target.copy(target);this.camera.zoom=2.6;
    this.camera.updateProjectionMatrix();this.controls.update();this.requestRender();
  }
  focus(key:string){
    const item=this.projection?.instances.find(i=>i.key===key);if(!item)return;
    const target=new Vector3(...item.position),delta=target.clone().sub(this.controls.target);
    this.camera.position.add(delta);this.controls.target.copy(target);this.camera.zoom=Math.max(this.camera.zoom,2.5);
    this.camera.updateProjectionMatrix();this.controls.update();this.requestRender();
  }
  dispose(){
    this.alive=false;this.preview(null);this.abort.abort();cancelAnimationFrame(this.frame);this.observer.disconnect();
    this.controls.removeEventListener('change',this.requestRender);this.controls.dispose();
    this.reduced.removeEventListener('change',this.requestRender);
    this.renderer.domElement.removeEventListener('pointerdown',this.pointerDown);this.renderer.domElement.removeEventListener('pointerup',this.pointerUp);
    this.renderer.domElement.removeEventListener('webglcontextlost',this.contextLost);
    this.clearInstances();this.clearGround();this.markers.clear();this.markerGeometry.dispose();
    this.selectionMaterial.dispose();this.settledMaterial.dispose();this.rejectedMaterial.dispose();
    if(this.kit)disposeKit(this.kit);
    this.renderer.dispose();this.renderer.forceContextLoss();this.renderer.domElement.remove();
  }
}
