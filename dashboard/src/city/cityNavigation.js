// Presentation-only streets. Building assets fit a 3-unit square; district
// copies extend to 1.35 + .64 * 1.5. Clearance covers the largest citizen gait
// at CityCitizens' maximum 2.4 display scale, not just its centre point.
export const NAV_CLEARANCE = 2.6;
const ROAD_WIDTH = 3, MAX_GRID = 256;

/** One deterministic layout supplies both painted roads and walkable edges. */
export function createRoadLayout(instances) {
  const buildings = new Map();
  for (const item of instances) {
    if (item.entityType === 'agent' || !Number.isFinite(item.position?.[0]) || !Number.isFinite(item.position?.[2])) continue;
    const key = item.renderKey || `${item.entityType}:${item.entityId}`;
    const half = item.kind === 'residential_district' ? 2.31 : 1.5;
    if (!buildings.has(key) || buildings.get(key).half < half) buildings.set(key, {key, x:item.position[0], z:item.position[2], half});
  }
  const footprints = [...buildings.values()].sort((a,b)=>a.key.localeCompare(b.key));
  const sites = instances.filter(p=>p.entityType==='place' && p.provenance==='observed'
    && Number.isFinite(p.position?.[0]) && Number.isFinite(p.position?.[2]))
    .map(p=>({id:p.entityId,region:p.regionId,x:p.position[0],z:p.position[2]})).sort((a,b)=>a.id-b.id);
  const nodes = new Map(), edges = new Map(), ports = new Map(), roads = [];
  const addEdge = (a,b) => { edges.get(a).add(b); edges.get(b).add(a); };
  let regionIndex = 0;
  for (const region of new Set(sites.map(p=>p.region))) {
    const local = sites.filter(p=>p.region===region), prefix = `${regionIndex++}:`;
    const minX = Math.floor(Math.min(...local.map(p=>p.x))-12), minZ = Math.floor(Math.min(...local.map(p=>p.z))-12);
    const width = Math.ceil(Math.max(...local.map(p=>p.x))+12)-minX+1;
    const depth = Math.ceil(Math.max(...local.map(p=>p.z))+12)-minZ+1;
    // Dispersed display coordinates cannot allocate an unbounded grid.
    if (width>MAX_GRID || depth>MAX_GRID) continue;
    const count = width*depth, blocked = new Uint8Array(count);
    const point = i => [minX+i%width,0,minZ+Math.floor(i/width)];
    const neighbours = i => {
      const result=[];
      if(i%width>0)result.push(i-1);if(i%width<width-1)result.push(i+1);
      if(i>=width)result.push(i-width);if(i<count-width)result.push(i+width);
      return result;
    };
    for(const b of footprints){
      const pad=b.half+NAV_CLEARANCE;
      for(let z=Math.max(0,Math.ceil(b.z-pad-minZ));z<=Math.min(depth-1,Math.floor(b.z+pad-minZ));z++)
        for(let x=Math.max(0,Math.ceil(b.x-pad-minX));x<=Math.min(width-1,Math.floor(b.x+pad-minX));x++)blocked[z*width+x]=1;
    }
    // Label free-space components once. Never bridge a sealed courtyard or
    // another region just to make an itinerary appear complete.
    const components=new Int32Array(count),queue=new Int32Array(count);let component=0;
    for(let seed=0;seed<count;seed++)if(!blocked[seed]&&!components[seed]){
      let head=0,tail=1;queue[0]=seed;components[seed]=++component;
      while(head<tail)for(const n of neighbours(queue[head++]))if(!blocked[n]&&!components[n]){components[n]=component;queue[tail++]=n;}
    }
    const used=new Set(), entries=[];
    for(const site of local){
      let best=-1,distance=Infinity;
      for(let i=0;i<count;i++)if(!blocked[i]&&!used.has(i)){
        const [x,,z]=point(i),d=(x-site.x)**2+(z-site.z-5)**2;
        if(d<distance){best=i;distance=d;}
      }
      if(best<0)continue;
      used.add(best);ports.set(site.id,prefix+best);entries.push(best);
    }
    const painted=new Set();
    const paint = path => {
      for(const i of path){painted.add(i);const key=prefix+i;if(!nodes.has(key)){nodes.set(key,point(i));edges.set(key,new Set());}}
      for(let i=1;i<path.length;i++)addEdge(prefix+path[i-1],prefix+path[i]);
    };
    for(const port of entries){
      paint([port]);
      for(const direction of [-1,1]){
        let previous=port;
        for(let step=1;step<=2;step++){
          const next=port+direction*step;
          if(Math.floor(next/width)!==Math.floor(port/width)||next<0||next>=count||blocked[next])break;
          paint([previous,next]);previous=next;
        }
      }
    }
    const gridPath = (start,end) => {
      const previous=new Int32Array(count).fill(-1);let head=0,tail=1;
      queue[0]=start;previous[start]=start;
      while(head<tail&&previous[end]<0){
        const current=queue[head++];
        for(const n of neighbours(current))if(!blocked[n]&&previous[n]<0){previous[n]=current;queue[tail++]=n;}
      }
      if(previous[end]<0)return [];
      const path=[end];while(path.at(-1)!==start)path.push(previous[path.at(-1)]);
      return path.reverse();
    };
    for(const group of new Set(entries.map(i=>components[i]))){
      const pending=entries.filter(i=>components[i]===group),linked=[pending.shift()];
      while(pending.length){
        let best=null;
        for(const a of linked)for(const b of pending){
          const d=Math.abs(a%width-b%width)+Math.abs(Math.floor(a/width)-Math.floor(b/width));
          if(!best||d<best.d)best={a,b,d};
        }
        paint(gridPath(best.a,best.b));linked.push(best.b);pending.splice(pending.indexOf(best.b),1);
      }
    }
    // Compact collinear edges into instanced rectangles. Navigation uses only
    // these painted cells, with no free-space search during animation.
    for(const i of painted)for(const n of neighbours(i))if(painted.has(n))addEdge(prefix+i,prefix+n);
    for(const step of [1,width])for(const i of [...painted].sort((a,b)=>a-b)){
      const has = (a,b) => edges.get(prefix+a)?.has(prefix+b);
      if(!has(i,i+step)||has(i,i-step))continue;
      let end=i;while(has(end,end+step))end+=step;
      const a=point(i),b=point(end);
      roads.push({x:(a[0]+b[0])/2,z:(a[2]+b[2])/2,width:Math.abs(a[0]-b[0])+ROAD_WIDTH,depth:Math.abs(a[2]-b[2])+ROAD_WIDTH});
    }
    for(const i of painted)if(!edges.get(prefix+i).size){const [x,,z]=point(i);roads.push({x,z,width:ROAD_WIDTH,depth:ROAD_WIDTH});}
  }
  const trees=[];
  for(const site of sites)for(const offset of [-3,3]){
    const x=site.x+offset,z=site.z+8;
    if(footprints.every(b=>Math.hypot(x-b.x,z-b.z)>b.half+2.5)
      &&roads.every(r=>Math.abs(x-r.x)>r.width/2+1||Math.abs(z-r.z)>r.depth/2+1))trees.push({x,z,height:1.5+(site.id%4)*.18});
  }
  return {nodes,edges,ports,footprints,cache:new Map(),scenery:{roads,lots:sites.map(p=>({id:p.id,x:p.x,z:p.z})),trees}};
}

/** Cached shortest route on the painted graph; absence is a safe stop. */
export function roadPath(layout,start,end) {
  if(!layout.nodes.has(start)||!layout.nodes.has(end))return null;
  const key=`${start}>${end}`;if(layout.cache.has(key))return layout.cache.get(key);
  const previous=new Map([[start,null]]),queue=[start];
  for(let head=0;head<queue.length&&!previous.has(end);head++)for(const n of layout.edges.get(queue[head]))
    if(!previous.has(n)){previous.set(n,queue[head]);queue.push(n);}
  if(!previous.has(end)){layout.cache.set(key,null);return null;}
  const raw=[];for(let n=end;n!==null;n=previous.get(n))raw.push(layout.nodes.get(n));raw.reverse();
  const points=raw.filter((p,i)=>!i||i===raw.length-1||
    (p[0]-raw[i-1][0])*(raw[i+1][2]-p[2])!==(p[2]-raw[i-1][2])*(raw[i+1][0]-p[0]));
  const cumulative=[0];for(let i=1;i<points.length;i++)cumulative.push(cumulative[i-1]+Math.hypot(points[i][0]-points[i-1][0],points[i][2]-points[i-1][2]));
  const path={points,cumulative,length:cumulative.at(-1)};layout.cache.set(key,path);return path;
}

export function pointOnRoadPath(path,distance) {
  const d=Math.max(0,Math.min(path.length,distance));
  for(let i=1;i<path.points.length;i++)if(d<=path.cumulative[i]){
    const a=path.points[i-1],b=path.points[i],t=(d-path.cumulative[i-1])/(path.cumulative[i]-path.cumulative[i-1]);
    return {position:[a[0]+(b[0]-a[0])*t,0,a[2]+(b[2]-a[2])*t],heading:Math.atan2(b[0]-a[0],b[2]-a[2])};
  }
  return {position:[...path.points[0]],heading:0};
}

/** Stable, separated waiting positions drawn from the same road graph. */
export function roadWaitingNodes(layout,port) {
  if(!layout.nodes.has(port))return [];
  const queue=[[port,0]],seen=new Set([port]),result=[];
  for(let head=0;head<queue.length;head++){
    const [key,distance]=queue[head];if(distance%2===0)result.push(key);
    if(distance<8)for(const n of layout.edges.get(key))if(!seen.has(n)){seen.add(n);queue.push([n,distance+1]);}
  }
  return result;
}
