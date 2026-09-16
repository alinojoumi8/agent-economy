import { Box3, BufferGeometry, Material, Mesh, MeshLambertMaterial, MeshStandardMaterial, Object3D, Vector3 } from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
export type AssetPart={geometry:BufferGeometry;material:Material};
export type AssetKit=Map<string,AssetPart[]>;
const required=['residence','office','workshop','bank','civic_hall','neutral','agent'];
export function disposeKit(kit:AssetKit) {
  const materials=new Set<Material>();
  for(const parts of kit.values()) for(const p of parts){p.geometry.dispose();materials.add(p.material);}
  for(const m of materials)m.dispose();
  kit.clear();
}
/** Loads only local catalog assets. Temporary and retained GPU resources have separate owners. */
export async function loadCityAssets(signal:AbortSignal):Promise<AssetKit> {
  const response=await fetch(`${import.meta.env.BASE_URL}city/catalog.json`,{signal,credentials:'same-origin'});
  if(!response.ok)throw new Error('City asset catalog could not be loaded.');
  const catalog=await response.json();
  if(catalog.schema_version!==1||catalog.coordinate_system?.export!=='Y_UP'||catalog.coordinate_system?.ground_plane!=='y=0'
    ||!Array.isArray(catalog.assets)||catalog.assets.length!==required.length)throw new Error('City asset catalog is malformed.');
  let totalBytes=0;
  const kit:AssetKit=new Map(),transientGeometry=new Set<BufferGeometry>(),transientMaterials=new Set<Material>();
  const loader=new GLTFLoader();
  try {
    for(const asset of catalog.assets){
      if(!required.includes(asset.key)||kit.has(asset.key))throw new Error('Invalid or duplicate asset key.');
      const variant=asset.variants?.low,url=variant?.url;
      if(typeof url!=='string'||url!==`/city/${asset.key}-low.glb`)throw new Error('Invalid city asset URL.');
      const result=await fetch(`${import.meta.env.BASE_URL}${url.slice(1)}`,{signal,credentials:'same-origin'});
      if(!result.ok)throw new Error(`Could not load ${asset.key} building.`);
      const bytes=await result.arrayBuffer();totalBytes+=bytes.byteLength;
      if(totalBytes>10_000_000||bytes.byteLength!==variant.bytes)throw new Error('City asset size does not match its catalog.');
      if(!crypto.subtle)throw new Error('City asset verification requires HTTPS or localhost. The 2D atlas remains available.');
      const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),b=>b.toString(16).padStart(2,'0')).join('');
      if(digest!==variant.sha256)throw new Error('City asset checksum does not match its catalog.');
      const gltf=await loader.parseAsync(bytes,'/city/'),root=gltf.scene;
      // Register every imported resource before any operation that can fail.
      root.traverse((o:Object3D)=>{if(o instanceof Mesh){transientGeometry.add(o.geometry);for(const m of Array.isArray(o.material)?o.material:[o.material])transientMaterials.add(m);}});
      root.updateMatrixWorld(true);
      const box=new Box3().setFromObject(root),size=box.getSize(new Vector3()),center=box.getCenter(new Vector3());
      const scale=asset.key==='agent'?.9/size.y:3/Math.max(size.x,size.z);
      if(!Number.isFinite(scale)||scale<=0)throw new Error('Invalid asset bounds.');
      const grouped=new Map<Material,BufferGeometry[]>();
      root.traverse((object:Object3D)=>{
        if(!(object instanceof Mesh))return;
        if(Array.isArray(object.material))throw new Error('Kit parts require one material per mesh.');
        const geometry=object.geometry.clone();transientGeometry.add(geometry);
        geometry.applyMatrix4(object.matrixWorld).translate(-center.x,-box.min.y,-center.z).scale(scale,scale,scale);
        const group=grouped.get(object.material)||[];group.push(geometry);grouped.set(object.material,group);
      });
      const parts:AssetPart[]=[];
      for(const [material,geometries] of grouped){
        const merged=mergeGeometries(geometries,false);
        if(!merged)throw new Error('City asset geometry could not be assembled.');
        transientGeometry.add(merged);
        if(!(material instanceof MeshStandardMaterial))throw new Error('Unsupported city material.');
        // Flat procedural colors need diffuse lighting, not expensive PBR shaders.
        const diffuse=new MeshLambertMaterial({color:material.color,emissive:material.emissive,
          emissiveIntensity:material.emissiveIntensity,side:material.side});
        transientMaterials.add(diffuse);parts.push({geometry:merged,material:diffuse});
      }
      kit.set(asset.key,parts);
      for(const part of parts){transientGeometry.delete(part.geometry);transientMaterials.delete(part.material);}
      for(const geometry of transientGeometry)geometry.dispose();transientGeometry.clear();
      if(signal.aborted)throw new DOMException('Aborted','AbortError');
    }
    return kit;
  }catch(error){disposeKit(kit);throw error;}
  finally{for(const geometry of transientGeometry)geometry.dispose();for(const material of transientMaterials)material.dispose();}
}
