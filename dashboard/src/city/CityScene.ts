import { AmbientLight, BoxGeometry, DirectionalLight, GridHelper, Group, InstancedMesh, Matrix4,
  Mesh, MeshLambertMaterial, MOUSE, TOUCH, OrthographicCamera, Raycaster, RingGeometry, Scene, Vector2, Vector3, WebGLRenderer } from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { disposeKit, loadCityAssets, type AssetKit } from './assetLoader';
import type { CityActivity, CityInstance, CityProjection } from './cityProjection';
import { buildCityScenery, disposeCityScenery } from './CityScenery';
import { normalizeCityCamera3d } from '../lib/cityCamera3d.js';
import { CityLandmarks } from './CityLandmarks';
import { CityCitizens } from './CityCitizens';
import { createCityDay } from './cityMotion.js';
import { dayClock } from '../lib/liveCity.js';
import { playbackElapsed, updatePlayback } from '../lib/recordedPlayback.js';
export type SceneStats={calls:number;triangles:number;geometries:number;textures:number;frames:number};
export type CityPlaybackState={playing:boolean;speed:number;phase:string;movers:number;available:number;blocked:number;reduced:boolean};
export class CityScene {
  private renderer:WebGLRenderer;
  private scene=new Scene();
  private camera=new OrthographicCamera(-70,70,55,-55,.1,1000);
  private controls:OrbitControls;
  private buildings=new Group();
  private ground=new Group();
  private scenery=new Group();
  private markers=new Group();
  private landmarks:CityLandmarks;
  private citizens=new CityCitizens();
  private day:ReturnType<typeof createCityDay>|null=null;
  private clock:{elapsed:number;startedAt:number|null;speed:number}={elapsed:0,startedAt:null,speed:1};
  private motionAllowed=true;
  private playbackState='';
  private motionTimer=0;
  private followed:string|null=null;
  private hovered:string|null=null;
  private lastElapsed=0;
  private lastFrameTime=0;
  private frameTimes:number[]=[];
  private drawTimes:number[]=[];
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
  private initialCamera:string|null=null;
  private gestureCamera:string|null=null;
  private running=false;
  private reduced=window.matchMedia('(prefers-reduced-motion: reduce)');
  private pointer=new Vector2();
  private ray=new Raycaster();
  private pointerStart=[0,0];
  private markerGeometry=new RingGeometry(1.8,2.1,32);
  private selectionMaterial=new MeshLambertMaterial({color:'#2457D6',emissive:'#2457D6',emissiveIntensity:.3,side:2});
  private settledMaterial=new MeshLambertMaterial({color:'#B7D64A',emissive:'#B7D64A',emissiveIntensity:.25,side:2});
  private rejectedMaterial=new MeshLambertMaterial({color:'#E44732',emissive:'#E44732',emissiveIntensity:.25,side:2});
  private pendingMaterial=new MeshLambertMaterial({color:'#df9b25',side:2});
  private recordedMaterial=new MeshLambertMaterial({color:'#657888',side:2});
  constructor(private host:HTMLElement,private onPick:(key:string)=>void,private onReady:()=>void,
    private onError:(message:string)=>void,private onStats:(stats:SceneStats)=>void,
    private onCameraChange?:(state:string)=>void,private onPlayback?:(state:CityPlaybackState)=>void){
    this.renderer=new WebGLRenderer({antialias:false,alpha:false,powerPreference:'low-power'});
    // Canvas contains geometry only; HTML labels stay at native resolution.
    // A bounded render scale keeps the 300-citizen view usable on software GPUs.
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio,1.5));
    this.renderer.setClearColor('#e8ede3');
    this.renderer.domElement.setAttribute('aria-label','Interactive 3D city. Use the entity list and camera buttons for keyboard navigation.');
    this.renderer.domElement.setAttribute('role','img');
    host.append(this.renderer.domElement);
    this.landmarks=new CityLandmarks(host,onPick);
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
    this.controls.addEventListener('start',this.cameraGestureStart);
    this.controls.addEventListener('end',this.cameraGestureEnd);
    this.controls.update();
    this.scene.add(new AmbientLight('#ffffff',1.5));
    const sun=new DirectionalLight('#fff6e7',1.65);sun.position.set(-35,80,50);this.scene.add(sun);
    this.scene.add(this.ground,this.scenery,this.buildings,this.citizens.group,this.markers);
    this.observer=new ResizeObserver(()=>this.resize());this.observer.observe(host);
    this.renderer.domElement.addEventListener('pointerdown',this.pointerDown);
    this.renderer.domElement.addEventListener('pointerup',this.pointerUp);
    this.renderer.domElement.addEventListener('pointermove',this.pointerMove);
    this.renderer.domElement.addEventListener('pointerleave',this.pointerLeave);
    this.renderer.domElement.addEventListener('webglcontextlost',this.contextLost);
    this.reduced.addEventListener('change',this.requestRender);
    document.addEventListener('visibilitychange',this.visibilityChange);
    (window as unknown as {__city3dProbe:()=>unknown}).__city3dProbe=this.probe;
    this.resize();
    loadCityAssets(this.abort.signal).then(kit=>{
      if(!this.alive){disposeKit(kit);return;}
      this.kit=kit;this.rebuild();this.onReady();
    }).catch(error=>{if(this.alive)this.onError(error instanceof Error?error.message:'City assets unavailable.');});
  }
  private contextLost=(event:Event)=>{event.preventDefault();this.playback(false);this.failed=true;this.running=false;this.landmarks.clear();cancelAnimationFrame(this.frame);this.frame=0;this.onError('3D graphics context was lost. Switch to the 2D atlas or reload the city.');};
  private visibilityChange=()=>{if(document.hidden)this.playback(false);};
  private pointerDown=(event:PointerEvent)=>{this.pointerStart=[event.clientX,event.clientY];};
  private pointerUp=(event:PointerEvent)=>{
    if(event.button!==0)return;
    if(Math.hypot(event.clientX-this.pointerStart[0],event.clientY-this.pointerStart[1])>5)return;
    const key=this.pickAt(event);if(key)this.onPick(key);
  };
  private pickAt(event:PointerEvent){
    const rect=this.renderer.domElement.getBoundingClientRect();
    this.pointer.set((event.clientX-rect.left)/rect.width*2-1,-(event.clientY-rect.top)/rect.height*2+1);
    this.ray.setFromCamera(this.pointer,this.camera);
    const hit=this.ray.intersectObjects([...this.citizens.group.children,...this.buildings.children]).find(i=>i.instanceId!==undefined);
    return hit&&hit.instanceId!==undefined?hit.object.userData.keys?.[hit.instanceId] as string|undefined:undefined;
  };
  private pointerMove=(event:PointerEvent)=>{if(event.buttons)return;const key=this.pickAt(event)||null;if(key!==this.hovered){this.hovered=key;this.requestRender();}};
  private pointerLeave=()=>{this.hovered=null;this.requestRender();};
  private resize(){
    const width=Math.max(1,this.host.clientWidth),height=Math.max(1,this.host.clientHeight);
    this.renderer.setSize(width,height);const aspect=width/height;
    this.camera.left=-55*aspect;this.camera.right=55*aspect;this.camera.top=55;this.camera.bottom=-55;
    this.camera.updateProjectionMatrix();this.requestRender();
  }
  private requestRender=()=>{if(this.alive&&!this.failed&&!this.frame)this.frame=requestAnimationFrame(this.render);};
  private cameraGestureStart=()=>{this.gestureCamera=this.cameraState();};
  private cameraGestureEnd=()=>{
    const state=this.cameraState(),before=this.gestureCamera;this.gestureCamera=null;
    if(state&&state!==before){this.followed=null;this.onCameraChange?.(state);}
  };
  cameraState(){
    return normalizeCityCamera3d([...this.camera.position.toArray(),...this.controls.target.toArray(),this.camera.zoom].join(','));
  }
  restoreCamera(value:string|null){
    const saved=normalizeCityCamera3d(value)||this.initialCamera;
    if(!saved)return;
    const [x,y,z,tx,ty,tz,zoom]=saved.split(',').map(Number);
    this.camera.position.set(x,y,z);this.controls.target.set(tx,ty,tz);this.camera.zoom=zoom;
    this.initiallyFramed=true;this.camera.updateProjectionMatrix();this.controls.update();this.requestRender();
  }
  private render=(time:number)=>{
    this.frame=0;if(!this.alive||this.failed)return;
    const drawStart=performance.now();
    this.lastElapsed=playbackElapsed(this.clock,time);
    if(this.day){
      this.citizens.update(this.day,this.lastElapsed,this.reduced.matches,this.camera,this.host.clientHeight);
      if(this.followed&&this.gestureCamera===null){
        const position=this.citizens.position(this.followed);
        if(position){const target=new Vector3(...position as [number,number,number]),delta=target.clone().sub(this.controls.target);this.camera.position.add(delta);this.controls.target.copy(target);this.controls.update();}
      }
    }
    this.markers.scale.setScalar(1); // Rings animate individually, never scale entity positions.
    for(const child of this.markers.children){
      if(child instanceof InstancedMesh)this.positionMarkers(child,time);
    }
    this.renderer.render(this.scene,this.camera);this.frameCount++;
    if(this.kit)this.landmarks.update(this.filtered,this.selected,this.camera,this.host.clientWidth,this.host.clientHeight,
      key=>this.citizens.position(key),this.citizens.labelHeight(),this.hovered);
    this.host.dataset.renderFrames=String(this.frameCount);
    this.host.dataset.camera3d=this.cameraState()||'';
    const info=this.renderer.info;
    this.onStats({calls:info.render.calls,triangles:info.render.triangles,geometries:info.memory.geometries,textures:info.memory.textures,frames:this.frameCount});
    this.publishPlayback();
    if(this.clock.startedAt!==null){
      if(this.lastFrameTime)this.frameTimes.push(time-this.lastFrameTime);
      this.drawTimes.push(performance.now()-drawStart);
      if(this.frameTimes.length>240)this.frameTimes.shift();if(this.drawTimes.length>240)this.drawTimes.shift();
      this.lastFrameTime=time;
      if(this.reduced.matches){window.clearTimeout(this.motionTimer);this.motionTimer=window.setTimeout(this.requestRender,1000);}
      else this.requestRender();
    }
    if(this.running&&!this.reduced.matches&&this.events.some(e=>(this.effects.get(e.id)||0)>time))this.requestRender();
  };
  playback(playing:boolean,speed=this.clock.speed,restart=false){
    window.clearTimeout(this.motionTimer);this.lastFrameTime=0;
    this.clock=updatePlayback(this.clock,{playing:playing&&this.motionAllowed&&!this.failed&&!document.hidden&&!!this.day?.movers,speed},performance.now());
    if(restart)this.clock.elapsed=0;
    this.publishPlayback();this.requestRender();
  }
  allowPlayback(allowed:boolean){this.motionAllowed=allowed;if(!allowed)this.playback(false);}
  follow(key:string|null){this.followed=key;if(key)this.focus(key);}
  private publishPlayback(){
    const clock=this.day?dayClock(playbackElapsed(this.clock,performance.now()),this.day.plan):null;
    const ids=new Set(this.filtered.filter(i=>i.entityType==='agent').map(i=>i.entityId));
    const agents=this.day?.agents.filter(a=>ids.has(a.id))||[];
    const state:CityPlaybackState={playing:this.clock.startedAt!==null,speed:this.clock.speed,
      phase:clock?`${clock.slot} → ${clock.nextSlot}`:'',movers:agents.filter(a=>a.moves).length,available:agents.length,
      blocked:agents.filter(a=>a.routeBlocked).length,reduced:this.reduced.matches};
    const signature=JSON.stringify(state);if(signature!==this.playbackState){this.playbackState=signature;this.onPlayback?.(state);}
  }
  private probe=()=>({tick:this.projection?.envelope.tick,identity:this.projection?.identity,
    playing:this.clock.startedAt!==null,speed:this.clock.speed,elapsed:this.lastElapsed,
    frameTimes:[...this.frameTimes],drawTimes:[...this.drawTimes],
    roads:this.day?.navigation.scenery.roads,footprints:this.day?.navigation.footprints,
    citizens:this.citizens.evidence(this.camera,this.host.clientWidth,this.host.clientHeight)});
  update(projection:CityProjection,instances:CityInstance[],selected:string|null,events:CityActivity[],running:boolean){
    if(this.failed)return;
    const scope=JSON.stringify([projection.envelope.run_id,projection.envelope.fork_id,projection.envelope.view_key]);
    if(scope!==this.effectScope){this.effects.clear();this.effectScope=scope;}
    for(const event of events)if(!this.effects.has(event.id))this.effects.set(event.id,performance.now()+1400);
    while(this.effects.size>512)this.effects.delete(this.effects.keys().next().value!);
    // Polling can deliver a new object for the same committed frame. Retain
    // geometry and articulated poses until identity or the visible set changes.
    const changed=this.projection?.identity!==projection.identity||this.filtered.length!==instances.length
      ||this.filtered.some((item,index)=>item.key!==instances[index]?.key);
    if(this.projection?.identity!==projection.identity){
      this.day=createCityDay(projection);this.clock={elapsed:0,startedAt:null,speed:this.clock.speed};
      this.hovered=null;this.frameTimes=[];this.drawTimes=[];this.lastFrameTime=0;
      window.clearTimeout(this.motionTimer);
    }
    this.projection=projection;this.filtered=instances;this.selected=selected;this.events=events;this.running=running;
    if(!instances.some(item=>item.entityType==='agent'&&this.day?.byId.get(item.entityId)?.moves))this.playback(false);
    if(changed)this.rebuild();else this.updateMarkers();
    this.requestRender();
  }
  private clearInstances(){for(const child of this.buildings.children)if(child instanceof InstancedMesh)child.dispose();this.buildings.clear();}
  private clearGround(){disposeCityScenery(this.scenery);for(const child of this.ground.children){if(child instanceof Mesh||child instanceof GridHelper){child.geometry.dispose();const m=child.material;if(Array.isArray(m))m.forEach(x=>x.dispose());else m.dispose();}}this.ground.clear();}
  private rebuild(){
    if(!this.kit||!this.projection)return;
    this.clearInstances();this.clearGround();
    this.citizens.setItems(this.filtered);
    if(this.day)this.citizens.update(this.day,playbackElapsed(this.clock,performance.now()),this.reduced.matches,this.camera,this.host.clientHeight);
    const byRender=new Map<string,CityInstance>();
    // Firm aliases select their firm's inspector while reusing the place geometry.
    for(const item of this.filtered){const prior=byRender.get(item.renderKey);if(!prior||item.entityType==='firm')byRender.set(item.renderKey,item);}
    const families=new Map<string,CityInstance[]>();
    for(const item of byRender.values()){if(item.entityType==='agent')continue;const group=families.get(item.assetKey)||[];group.push(item);families.set(item.assetKey,group);}
    const matrix=new Matrix4();
    for(const [key,items] of families){
      // A district is an aggregate place, represented by a small housing block.
      // All four illustrative homes retain the same district evidence identity.
      const copies=items.flatMap(item=>item.kind==='residential_district'
        ? [-1.35,1.35].flatMap(x=>[-1.35,1.35].map(z=>({item,x,z,scale:.64})))
        : [{item,x:0,z:0,scale:1}]);
      for(const part of this.kit.get(key)||this.kit.get('neutral')||[]){
        const mesh=new InstancedMesh(part.geometry,part.material,copies.length);
        mesh.userData.keys=copies.map(i=>i.item.key);
        copies.forEach(({item,x,z,scale},index)=>{
          matrix.makeScale(scale,scale,scale);matrix.setPosition(item.position[0]+x,item.position[1],item.position[2]+z);mesh.setMatrixAt(index,matrix);
        });
        mesh.instanceMatrix.needsUpdate=true;mesh.computeBoundingSphere();this.buildings.add(mesh);
      }
    }
    const extent=Math.max(65,...this.projection.instances.flatMap(i=>[Math.abs(i.position[0])+12,Math.abs(i.position[2])+12]));
    const ground=new Mesh(new BoxGeometry(extent*2,1,extent*2),new MeshLambertMaterial({color:'#c5d2b1'}));
    ground.position.y=-.6;this.ground.add(ground);
    // Base streets remain stable when the entity filter changes.
    const scenery=buildCityScenery(this.projection.instances,this.day?.navigation.scenery);
    // Worlds without recorded places can legitimately have no scenery.
    for(const child of [...scenery.children])this.scenery.add(child);
    this.updateMarkers();
    if(!this.initialCamera){
      const bookmark=this.initiallyFramed?this.cameraState():null;
      this.initiallyFramed=true;
      if(this.projection.regions.length&&this.filtered.some(i=>i.provenance==='observed'))this.focusRegion(this.projection.regions[0].id);else this.fitVisible();
      this.initialCamera=this.cameraState();
      if(bookmark)this.restoreCamera(bookmark);
    }
    this.requestRender();
  }
  private updateMarkers(){
    this.clearMarkers();
    const batches=new Map<MeshLambertMaterial,Array<{key:string;position:readonly number[];until:number}>>();
    for(const item of this.filtered){
      const selected=item.key===this.selected||item.renderKey===this.projection?.instances.find(i=>i.key===this.selected)?.renderKey;
      const activity=this.events.find(e=>e.targets.includes(item.key));
      if(!selected&&!activity)continue;
      const material=selected?this.selectionMaterial:activity?.state==='rejected'?this.rejectedMaterial:activity?.state==='pending'?this.pendingMaterial:activity?.state==='settled'?this.settledMaterial:this.recordedMaterial;
      const items=batches.get(material)||[];items.push({key:item.key,position:item.position,until:activity?(this.effects.get(activity.id)||0):0});batches.set(material,items);
    }
    for(const [material,items] of batches){const mesh=new InstancedMesh(this.markerGeometry,material,items.length);mesh.userData.markerItems=items;mesh.frustumCulled=false;this.positionMarkers(mesh,performance.now());this.markers.add(mesh);}
  }
  private positionMarkers(mesh:InstancedMesh,time:number){
    const matrix=new Matrix4(),scale=new Vector3();
    mesh.userData.markerItems.forEach((item:{key:string;position:number[];until:number},index:number)=>{
      const pulse=this.running&&!this.reduced.matches&&item.until>time?1+.08*Math.sin(time*.004):1;
      const position=this.citizens.position(item.key)||item.position;
      matrix.makeRotationX(-Math.PI/2);matrix.scale(scale.set(pulse,pulse,1));matrix.setPosition(position[0],.05,position[2]);mesh.setMatrixAt(index,matrix);
    });mesh.instanceMatrix.needsUpdate=true;
  }
  private clearMarkers(){
    for(const child of this.markers.children)if(child instanceof InstancedMesh)child.dispose();this.markers.clear();
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
    this.playback(false);this.day=null;this.citizens.clear();this.followed=null;this.hovered=null;
    this.running=false;this.projection=null;this.filtered=[];this.events=[];
    this.landmarks.clear();
    this.clearInstances();this.clearGround();this.clearMarkers();this.preview(null);this.requestRender();
  }
  fitVisible(derivedOnly=false){
    const items=this.filtered.filter(i=>!derivedOnly||i.provenance==='derived');if(!items.length)return;
    const xs=items.map(i=>i.position[0]),zs=items.map(i=>i.position[2]);
    const minX=Math.min(...xs),maxX=Math.max(...xs),minZ=Math.min(...zs),maxZ=Math.max(...zs);
    const target=new Vector3((minX+maxX)/2,0,(minZ+maxZ)/2);
    this.controls.target.copy(target);this.camera.position.copy(target).add(new Vector3(95,100,110));
    this.fitPoints(items);
    this.controls.update();this.requestRender();
  }
  private fitPoints(items:CityInstance[]){
    // Fit projected bounds, including building height, to the actual field.
    // A fixed zoom crops the same district on a narrow phone viewport.
    this.controls.update();
    this.camera.zoom=1;this.camera.updateProjectionMatrix();this.camera.updateMatrixWorld();
    let minX=Infinity,maxX=-Infinity,minY=Infinity,maxY=-Infinity;
    const point=new Vector3();
    for(const item of items)for(const x of [-4,4])for(const z of [-4,4])for(const y of [0,6]){
      point.set(item.position[0]+x,item.position[1]+y,item.position[2]+z).project(this.camera);
      minX=Math.min(minX,point.x);maxX=Math.max(maxX,point.x);
      minY=Math.min(minY,point.y);maxY=Math.max(maxY,point.y);
    }
    const center=new Vector3().setFromMatrixColumn(this.camera.matrixWorld,0)
      .multiplyScalar((minX+maxX)*(this.camera.right-this.camera.left)/4)
      .add(new Vector3().setFromMatrixColumn(this.camera.matrixWorld,1)
        .multiplyScalar((minY+maxY)*(this.camera.top-this.camera.bottom)/4));
    this.camera.position.add(center);this.controls.target.add(center);
    this.camera.zoom=Math.max(.35,Math.min(4,1.64/Math.max(.01,maxX-minX),1.44/Math.max(.01,maxY-minY)));
    this.camera.updateProjectionMatrix();
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
    const places=this.projection?.instances.filter(p=>p.entityType==='place'&&p.provenance==='observed'&&p.regionId===id)||[];
    const target=places.length?new Vector3(
      (Math.min(...places.map(p=>p.position[0]))+Math.max(...places.map(p=>p.position[0])))/2,0,
      (Math.min(...places.map(p=>p.position[2]))+Math.max(...places.map(p=>p.position[2])))/2+2,
    ):new Vector3(...region.position);
    const delta=target.clone().sub(this.controls.target);
    this.camera.position.add(delta);this.controls.target.copy(target);
    if(places.length)this.fitPoints(places);else {this.camera.zoom=2.6;this.camera.updateProjectionMatrix();}
    this.controls.update();this.requestRender();
  }
  focus(key:string){
    const item=this.projection?.instances.find(i=>i.key===key);if(!item)return;
    const target=new Vector3(...(this.citizens.position(key)||item.position) as [number,number,number]),delta=target.clone().sub(this.controls.target);
    this.camera.position.add(delta);this.controls.target.copy(target);this.camera.zoom=Math.max(this.camera.zoom,item.entityType==='agent'?5:2.5);
    this.camera.updateProjectionMatrix();this.controls.update();this.requestRender();
  }
  dispose(){
    window.clearTimeout(this.motionTimer);document.removeEventListener('visibilitychange',this.visibilityChange);
    const host=window as unknown as {__city3dProbe?:()=>unknown};if(host.__city3dProbe===this.probe)delete host.__city3dProbe;
    this.alive=false;this.preview(null);this.abort.abort();cancelAnimationFrame(this.frame);this.observer.disconnect();
    this.controls.removeEventListener('change',this.requestRender);
    this.controls.removeEventListener('start',this.cameraGestureStart);
    this.controls.removeEventListener('end',this.cameraGestureEnd);
    this.controls.dispose();
    this.reduced.removeEventListener('change',this.requestRender);
    this.renderer.domElement.removeEventListener('pointerdown',this.pointerDown);this.renderer.domElement.removeEventListener('pointerup',this.pointerUp);
    this.renderer.domElement.removeEventListener('pointermove',this.pointerMove);this.renderer.domElement.removeEventListener('pointerleave',this.pointerLeave);
    this.renderer.domElement.removeEventListener('webglcontextlost',this.contextLost);
    this.clearInstances();this.clearGround();this.clearMarkers();this.markerGeometry.dispose();
    this.selectionMaterial.dispose();this.settledMaterial.dispose();this.rejectedMaterial.dispose();
    this.pendingMaterial.dispose();this.recordedMaterial.dispose();
    if(this.kit)disposeKit(this.kit);
    this.landmarks.dispose();
    this.citizens.dispose();
    this.renderer.dispose();this.renderer.forceContextLoss();this.renderer.domElement.remove();
  }
}
