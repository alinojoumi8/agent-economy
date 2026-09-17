/** Illustrative streets and planting around recorded places; never simulation state. */
export function planCityStreets(instances) {
  const sites = instances.filter(p => p.entityType === 'place' && p.provenance === 'observed')
    .map(p => ({id:p.entityId, region:p.regionId, x:p.position[0], z:p.position[2]}))
    .sort((a,b) => a.id-b.id);
  const roads = [], trees = [], lots = [];
  const clear = (x,z) => sites.every(p => Math.hypot(p.x-x,p.z-z)>4);
  for (const site of sites) {
    lots.push({x:site.x,z:site.z,id:site.id});
    // Each frontage is offset from its source building, whose coordinate stays exact.
    roads.push({x:site.x,z:site.z+5,width:8,depth:3});
    for (const offset of [-3,3]) if (clear(site.x+offset,site.z+8)) {
      trees.push({x:site.x+offset,z:site.z+8,height:1.5+(site.id%4)*.18});
    }
  }
  // A stable nearest-neighbour tree joins frontages within each region only.
  for (const region of new Set(sites.map(p=>p.region))) {
    const pending=sites.filter(p=>p.region===region), linked=[];
    if(pending.length)linked.push(pending.shift());
    while(pending.length){
      let best=null;
      for(const a of linked)for(const b of pending){
        const distance=Math.abs(a.x-b.x)+Math.abs(a.z-b.z);
        if(!best||distance<best.distance)best={a,b,distance};
      }
      const {a,b}=best;
      // Choose the elbow with fewer building intersections. Omit any unsafe segment.
      const choices=[
        [{x:(a.x+b.x)/2,z:a.z+5,width:Math.abs(a.x-b.x)+3,depth:3},
          {x:b.x,z:(a.z+b.z)/2+5,width:3,depth:Math.abs(a.z-b.z)+3}],
        [{x:a.x,z:(a.z+b.z)/2+5,width:3,depth:Math.abs(a.z-b.z)+3},
          {x:(a.x+b.x)/2,z:b.z+5,width:Math.abs(a.x-b.x)+3,depth:3}],
      ];
      const intersects=r=>sites.some(p=>Math.abs(p.x-r.x)<r.width/2+2.2&&Math.abs(p.z-r.z)<r.depth/2+2.2);
      choices.sort((a,b)=>a.filter(intersects).length-b.filter(intersects).length);
      roads.push(...choices[0].filter(r=>!intersects(r)));
      linked.push(b);pending.splice(pending.indexOf(b),1);
    }
  }
  return {roads:roads.filter(r=>!sites.some(p=>Math.abs(p.x-r.x)<r.width/2+2.2&&Math.abs(p.z-r.z)<r.depth/2+2.2)),lots,trees};
}
