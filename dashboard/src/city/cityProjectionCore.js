/** Pure renderer projection. Never imports a store, fetch, random source or clock. */
export const CITY_LAYOUT_VERSION = 1;
const integer = value => Number.isSafeInteger(value) && value >= 0;
const record = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const coordinates = row => typeof row.x === 'number' && typeof row.y === 'number'
  && Number.isFinite(row.x) && Number.isFinite(row.y) && row.x >= 0 && row.x <= 1 && row.y >= 0 && row.y <= 1;

export function cityCoherence(envelope) {
  return JSON.stringify([envelope.run_id,envelope.fork_id,envelope.tick,envelope.semantics_version,
    envelope.projection_version,envelope.policy_version,envelope.view_key,envelope.event_cursor,CITY_LAYOUT_VERSION]);
}
export function cityIdentity(envelope) {
  return JSON.stringify([cityCoherence(envelope),envelope.snapshot_version]);
}
function validate(envelope) {
  if (!record(envelope) || typeof envelope.run_id !== 'string' || !envelope.run_id
    || !(envelope.fork_id === null || typeof envelope.fork_id === 'string')
    || !integer(envelope.tick) || !integer(envelope.event_cursor) || !integer(envelope.semantics_version)
    || envelope.projection_version !== 1 || envelope.policy_version !== 1
    || typeof envelope.view_key !== 'string' || !envelope.view_key
    || typeof envelope.snapshot_version !== 'string' || envelope.projection !== 'world.map'
    || !record(envelope.data)) throw new Error('Unsupported or malformed city projection. Use the 2D atlas.');
  for (const key of ['agents','organizations','banks','places','regions','presence','population_clusters']) {
    if (envelope.data[key] !== undefined && !Array.isArray(envelope.data[key])) throw new Error(`Invalid city ${key} layer.`);
  }
}
const PLACE_ASSETS = {residential_district:'residence',public_commons:'neutral',residence:'residence',home:'residence',housing:'residence',residential:'residence',
  firm_workplace:'office',workplace:'office',licensing_office:'civic_hall',bank:'bank',
  workshop:'workshop',industrial:'workshop',commercial:'office'};
const placeAsset = kind => Object.hasOwn(PLACE_ASSETS,kind)?PLACE_ASSETS[kind]:'neutral';
const firmAsset = sector => ['manufacturing','energy','agriculture','logistics'].includes(sector) ? 'workshop' : ['technology','services','finance','retail','healthcare','media'].includes(sector)?'office':'neutral';

export function projectCity(envelope) {
  validate(envelope);
  const data=envelope.data, scope=JSON.stringify([envelope.run_id,envelope.fork_id]);
  const keyFor = (type,id) => `${scope}:${type}:${id}`;
  const regions = [...(data.regions || [])].filter(r=>record(r) && integer(r.id)).sort((a,b)=>a.id-b.id);
  const places = new Map();
  const instances=[];
  const seen=new Set();
  function add(type,row) {
    if (!record(row) || !integer(row.id) || row.id===0) throw new Error(`Invalid ${type} identity.`);
    const key=keyFor(type,row.id);
    if (seen.has(key)) throw new Error(`Duplicate ${type} identity.`);
    seen.add(key);
    if (integer(row.created_tick) && row.created_tick>envelope.tick) return;
    if (integer(row.closed_tick) && row.closed_tick<=envelope.tick) return;
    const sourcePlace = type!=='place' ? places.get(row.place_id) : null;
    const hasSource = type==='place' ? coordinates(row) : sourcePlace?.provenance==='observed';
    // Injective entity/type slots, outside the normalized source coordinate square.
    // They never re-pack as IDs arrive and consume no simulation RNG.
    const lane = type==='agent' ? 0 : type==='firm' ? 1 : type==='place' ? 2 : 3;
    const n=(row.id-1)*4+lane;
    let position;
    if (sourcePlace) position=[...sourcePlace.position];
    else if (hasSource) position=[(row.x-.5)*160,0,(row.y-.5)*160];
    else {
      // Missing locations use a global identity grid, independent of regional coordinates.
      // This avoids collisions and implies no geographic relationship to a region.
      position=[100+(n%32)*5,0,Math.floor(n/32)*5];
    }
    if (type==='agent' && sourcePlace) {
      // A marker's offset around a place is presentation, not a precise location.
      const angle=row.id*2.399963229728653;
      position[0]+=Math.cos(angle)*(2.4+(row.id%7)*.18);
      position[2]+=Math.sin(angle)*(2.4+(row.id%7)*.18);
    }
    const instance={key,renderKey:sourcePlace && type==='firm'?sourcePlace.key:key,
      entityType:type,entityId:row.id,name:String(row.name || `${type} ${row.id}`).slice(0,160),
      assetKey:type==='agent'?'agent':type==='bank'?'bank':type==='firm'?firmAsset(row.sector):placeAsset(row.kind),
      position,provenance:hasSource?'observed':'derived',regionId:row.region_id ?? null,
      kind:String(row.kind || row.sector || type),placeId:row.place_id ?? null,
      evidenceIds:[],status:String(row.status || ''),capacity:integer(row.capacity)?row.capacity:null};
    if (sourcePlace && type==='firm') sourcePlace.assetKey=instance.assetKey;
    if (type==='place') places.set(row.id,instance);
    instances.push(instance);
  }
  for (const row of [...(data.places || [])].sort((a,b)=>a.id-b.id)) add('place',row);
  for (const row of [...(data.organizations || [])].sort((a,b)=>a.id-b.id)) add('firm',row);
  for (const row of [...(data.agents || [])].sort((a,b)=>a.id-b.id)) add('agent',row);
  for (const row of [...(data.banks || [])].sort((a,b)=>a.id-b.id)) add('bank',row);
  instances.sort((a,b)=>a.entityType.localeCompare(b.entityType)||a.entityId-b.entityId);
  return {identity:cityIdentity(envelope),envelope,city_layout_version:CITY_LAYOUT_VERSION,instances,
    regions:regions.map(r=>({id:r.id,name:String(r.name || `Region ${r.id}`),position:coordinates(r)?[(r.x-.5)*160,0,(r.y-.5)*160]:[0,0,0]})),
    clusters:(data.population_clusters || []).map(r=>({id:String(r.id),name:String(r.label),count:Number(r.count)||0})),
    warnings:[...(instances.some(i=>i.provenance==='derived')?['Derived civic layout: unlocated entities occupy the eastern display grid, outside recorded coordinates.']:[]),
      'Building shapes, roads and marker offsets are illustrative; they do not measure wealth, transport or land rights.',
      'Historical presence is tick-resolved. Names, roles, population tiers and some roster metadata may reflect current records.']};
}

const EVENT_STATES = {
  action_rejected:'rejected', business_permit_denied:'rejected', business_permit_approved:'settled',
  trade:'settled', goods_sale:'settled', wage_paid:'settled', hired:'settled',
  company_founded:'settled', civic_appointment_attended:'settled', construction_started:'settled',
  construction_completed:'settled', construction_cancelled:'rejected', construction_demolished:'rejected',
};
export function activityForCity(city, snapshot) {
  if (!record(snapshot) || snapshot.projection!=='world.snapshot' || cityCoherence(snapshot)!==cityCoherence(city.envelope) || !Array.isArray(snapshot.data?.events?.items)) return [];
  const result=new Map();
  for (const event of snapshot.data?.events?.items || []) {
    if (!record(event) || !integer(event.id) || event.id===0 || event.tick!==snapshot.tick || !Object.hasOwn(EVENT_STATES,event.kind) || !record(event.payload)) continue;
    const references=event.kind==='civic_appointment_attended'?[['place',event.payload.place_id]]:
      [['agent',event.payload.agent_id ?? event.payload.actor_id ?? event.payload.applicant_agent_id ?? event.payload.founder_agent_id ?? event.payload.buyer_id ?? event.payload.buyer],
       ['agent',event.payload.seller],['firm',event.payload.firm_id],['place',event.payload.place_id]];
    const targets=city.instances.filter(i=>references.some(([type,id])=>type===i.entityType && id===i.entityId)).map(i=>i.key);
    if (!targets.length) continue;
    result.set(event.id,{id:event.id,tick:event.tick,kind:event.kind,state:EVENT_STATES[event.kind],targets});
  }
  return [...result.values()].sort((a,b)=>b.id-a.id).slice(0,32);
}
