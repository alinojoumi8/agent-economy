export function activityFrame(frame:any,items:any[]=[]) {
  const cards=items.map(event=>({...event,title:event.kind.replaceAll('_',' '),detail:'',category:'work',outcome:'completed',actor_ids:[1],actors:[{id:1,name:'Supplier Officer'}]}));
  return {...frame,projection:'city.activity',data:{tick:frame.tick,through_id:frame.event_cursor||0,source:'committed',window:'selected_day',total:cards.length,day_total:cards.length,offset:0,limit:40,next_offset:null,items:cards,counts:{completed:cards.length},categories:{work:cards.length},actors:cards.length?[{id:1,name:'Supplier Officer'}]:[],changed_agents:cards.length?1:0,actor_activity:cards.length?[{agent_id:1,event:cards[0]}]:[],marker_events:cards}};
}
