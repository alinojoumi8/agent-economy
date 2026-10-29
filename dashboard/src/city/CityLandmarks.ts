import { OrthographicCamera, Vector3 } from 'three';
import type { CityInstance } from './cityProjection';

/** Native buttons above the scene. Names and identities come only from the projection. */
export class CityLandmarks {
  private root=document.createElement('div');
  private buttons=new Map<string,HTMLButtonElement>();
  constructor(host:HTMLElement,private onPick:(key:string)=>void){
    this.root.className='city3d-landmarks';
    this.root.setAttribute('role','group');
    this.root.setAttribute('aria-label','District landmarks');
    host.append(this.root);
  }
  update(instances:CityInstance[],selected:string|null,camera:OrthographicCamera,width:number,height:number){
    const chosen=instances.find(item=>item.key===selected);
    const candidates=[...(chosen?[chosen]:[]),...instances.filter(item=>item.entityType==='firm'||item.entityType==='bank'),
      ...instances.filter(item=>item.entityType==='place'),...instances.filter(item=>item.entityType==='agent')];
    const seen=new Set<string>(),shown=new Set<string>();
    const occupied:Array<{x:number;y:number}>=[];
    const labelWidth=Math.min(152,width-24),point=new Vector3();
    for(const item of candidates){
      if(seen.has(item.renderKey))continue;
      seen.add(item.renderKey);
      point.set(item.position[0],item.position[1]+(item.entityType==='agent'?2:5),item.position[2]).project(camera);
      const x=(point.x+1)*width/2,y=(1-point.y)*height/2;
      // Labels stay inside the field and yield to the selected identity. Dense
      // or offscreen entities remain selectable through the keyboard explorer.
      if(point.z < -1||point.z > 1||x<labelWidth/2+8||x>width-labelWidth/2-8||y<60||y>height-30)continue;
      if(occupied.some(p=>Math.abs(p.x-x)<labelWidth+8&&Math.abs(p.y-y)<56))continue;
      let button=this.buttons.get(item.key);
      if(!button){
        button=document.createElement('button');button.type='button';button.className='city3d-landmark';
        button.append(document.createElement('strong'),document.createElement('small'));
        button.addEventListener('click',()=>this.onPick(item.key));
        this.buttons.set(item.key,button);this.root.append(button);
      }
      const kind=item.entityType==='agent'?'Citizen':item.entityType==='firm'?'Business':item.entityType==='bank'?'Bank':'Place';
      button.firstElementChild!.textContent=item.name;
      button.lastElementChild!.textContent=item.provenance==='derived'?`${kind} · display slot`:kind;
      button.setAttribute('aria-label',`Select ${item.name}, ${kind.toLowerCase()}`);
      button.setAttribute('aria-pressed',String(item.key===selected));
      button.dataset.entityType=item.entityType;button.dataset.entityId=String(item.entityId);
      button.title=`${item.name} · ${item.provenance==='derived'?'Unlocated: illustrative display slot':'Recorded place; marker offset is illustrative'}`;
      button.style.left=`${x}px`;button.style.top=`${y}px`;
      occupied.push({x,y});shown.add(item.key);
      if(shown.size===10)break;
    }
    for(const [key,button] of this.buttons){
      if(!shown.has(key)){button.remove();this.buttons.delete(key);}
    }
  }
  clear(){for(const button of this.buttons.values())button.remove();this.buttons.clear();}
  dispose(){this.clear();this.root.remove();}
}
