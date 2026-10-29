import { normalizeLiveCity, legPlan, dayClock, recordedPointAt } from '../lib/liveCity.js';
import { createRoadLayout, roadPath, pointOnRoadPath, roadWaitingNodes } from './cityNavigation.js';

/** Only complete, authorized daily records may move an identified citizen. */
export function createCityDay(city) {
  const ids=new Set(city.instances.filter(i=>i.entityType==='agent').map(i=>i.entityId));
  const data=city.envelope.data;
  const presence=(data.presence||[]).filter(row=>row&&ids.has(row.agent_id)
    &&Number.isSafeInteger(row.place_id)&&row.place_id>0
    &&Number.isFinite(row.x)&&row.x>=0&&row.x<=1
    &&Number.isFinite(row.y)&&row.y>=0&&row.y<=1);
  const complete=normalizeLiveCity({...data,presence}).agents.filter(agent=>!agent.missingSlots.length);
  const navigation=createRoadLayout(city.instances);
  // Waiting nodes belong to the full authorized roster, not the visible filter.
  // They are outside-place presentation positions, never recorded coordinates.
  const occupants=new Map();
  for(const agent of complete)for(const anchor of agent.anchors){
    const idsAtPlace=occupants.get(anchor.placeId)||new Set();
    idsAtPlace.add(agent.id);occupants.set(anchor.placeId,idsAtPlace);
  }
  const completeIds=new Set(complete.map(agent=>agent.id));
  for(const item of city.instances)if(item.entityType==='agent'&&!completeIds.has(item.entityId)&&navigation.ports.has(item.placeId)){
    const idsAtPlace=occupants.get(item.placeId)||new Set();
    idsAtPlace.add(item.entityId);occupants.set(item.placeId,idsAtPlace);
  }
  const waiting=new Map();
  for(const [place,idsAtPlace] of occupants){
    const choices=roadWaitingNodes(navigation,navigation.ports.get(place));
    [...idsAtPlace].sort((a,b)=>a-b).forEach((id,index)=>{
      if(choices.length)waiting.set(`${id}:${place}`,choices[index%choices.length]);
    });
  }
  const agents=complete.map(agent=>{
    let nodes=agent.anchors.map(anchor=>waiting.get(`${agent.id}:${anchor.placeId}`));
    // Adjacent places can share a waiting area. Distinct destinations must
    // still have distinct endpoints for this citizen.
    if(nodes.some((node,i)=>nodes.some((other,j)=>node===other&&agent.anchors[i].placeId!==agent.anchors[j].placeId)))
      nodes=agent.anchors.map(anchor=>navigation.ports.get(anchor.placeId));
    const paths=nodes.map((node,index)=>roadPath(navigation,node,nodes[(index+1)%nodes.length]));
    const routeBlocked=paths.some(path=>!path);
    // Hold the entire itinerary if a leg is unavailable: skipping it would
    // teleport the person at the next slot boundary.
    return {...agent,paths,routeBlocked,moves:agent.moves&&!routeBlocked,hold:navigation.nodes.get(nodes.find(node=>navigation.nodes.has(node)))};
  });
  const byId=new Map(agents.map(agent=>[agent.id,agent]));
  return {agents,byId,waiting,navigation,plan:legPlan(agents.filter(agent=>!agent.routeBlocked)),movers:agents.filter(agent=>agent.moves).length};
}

export function citizenPose(day,item,elapsed,reduced=false) {
  const agent=day.byId.get(item.entityId);
  const port=day.navigation.nodes.get(day.waiting.get(`${item.entityId}:${item.placeId}`))
    ||day.navigation.nodes.get(day.navigation.ports.get(item.placeId));
  const still={position:[...(agent?.hold||port||item.position)],heading:0,stride:0,distance:0,fromPlace:null,toPlace:null,placeId:item.placeId??null};
  if(!agent||agent.routeBlocked)return still;
  const clock=dayClock(elapsed,day.plan),point=recordedPointAt(agent,clock);
  if(!point)return still;
  const path=agent.paths[clock.beatIndex];
  if(!path)return still;
  const t=reduced?(point.t<.5?0:1):point.t;
  const distance=path.length*t;
  return {...pointOnRoadPath(path,distance),
    stride:!reduced&&!point.stationary&&t>0&&t<1?Math.sin(distance/1.8*Math.PI*2)*.62:0,
    distance,fromPlace:point.from.placeId,toPlace:point.to.placeId,
    placeId:t===0?point.from.placeId:t===1?point.to.placeId:null};
}
