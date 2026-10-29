import { normalizeLiveCity, legPlan, dayClock, recordedPointAt } from '../lib/liveCity.js';

/** Only complete, authorized daily records may move an identified citizen. */
export function createCityDay(city) {
  const ids=new Set(city.instances.filter(i=>i.entityType==='agent').map(i=>i.entityId));
  const data=city.envelope.data;
  const presence=(data.presence||[]).filter(row=>row&&ids.has(row.agent_id)
    &&Number.isSafeInteger(row.place_id)&&row.place_id>0
    &&Number.isFinite(row.x)&&row.x>=0&&row.x<=1
    &&Number.isFinite(row.y)&&row.y>=0&&row.y<=1);
  const agents=normalizeLiveCity({...data,presence}).agents.filter(agent=>!agent.missingSlots.length);
  const byId=new Map(agents.map(agent=>[agent.id,agent]));
  // A stable offset belongs to an identity at a place, not to the visible filter.
  // These are display offsets, not recorded positions or street waypoints.
  const occupants=new Map();
  for(const agent of agents)for(const anchor of agent.anchors){
    const idsAtPlace=occupants.get(anchor.placeId)||new Set();
    idsAtPlace.add(agent.id);occupants.set(anchor.placeId,idsAtPlace);
  }
  const offsets=new Map();
  for(const [place,idsAtPlace] of occupants){
    [...idsAtPlace].sort((a,b)=>a-b).forEach((id,index)=>{
      const angle=index*2.399963229728653+place*.7,radius=3.8+1.25*Math.sqrt(index);
      offsets.set(`${id}:${place}`,[Math.cos(angle)*radius,Math.sin(angle)*radius]);
    });
  }
  return {agents,byId,offsets,plan:legPlan(agents),movers:agents.filter(agent=>agent.moves).length};
}

export function citizenPose(day,item,elapsed,reduced=false) {
  const agent=day.byId.get(item.entityId);
  const still={position:[...item.position],heading:0,stride:0,distance:0,fromPlace:null,toPlace:null,placeId:item.placeId??null};
  if(!agent)return still;
  const clock=dayClock(elapsed,day.plan),point=recordedPointAt(agent,clock);
  if(!point)return still;
  const anchorPosition=anchor=>{
    const offset=day.offsets.get(`${agent.id}:${anchor.placeId}`)||[0,0];
    return [(anchor.x-.5)*160+offset[0],0,(anchor.y-.5)*160+offset[1]];
  };
  const from=anchorPosition(point.from),to=anchorPosition(point.to);
  const t=reduced?(point.t<.5?0:1):point.t;
  const dx=to[0]-from[0],dz=to[2]-from[2],length=Math.hypot(dx,dz);
  const distance=length*t;
  return {position:[from[0]+dx*t,0,from[2]+dz*t],heading:Math.atan2(dx,dz),
    stride:!reduced&&!point.stationary&&t>0&&t<1?Math.sin(distance/1.8*Math.PI*2)*.62:0,
    distance,fromPlace:point.from.placeId,toPlace:point.to.placeId,
    placeId:t===0?point.from.placeId:t===1?point.to.placeId:null};
}
