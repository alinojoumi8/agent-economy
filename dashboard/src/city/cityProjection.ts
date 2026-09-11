import { projectCity as project, activityForCity as activity } from './cityProjectionCore.js';
import type { ProjectionEnvelope } from '../generated/worldOs';
export type CityInstance = {
  key:string; renderKey:string; entityType:'agent'|'firm'|'place'|'bank'; entityId:number;
  name:string; assetKey:string; position:[number,number,number]; provenance:'observed'|'derived';
  regionId:number|null; kind:string; placeId:number|null; evidenceIds:string[]; status:string; capacity:number|null;
};
export type CityProjection = {
  identity:string; envelope:ProjectionEnvelope<unknown>; city_layout_version:number;
  instances:CityInstance[]; regions:Array<{id:number;name:string;position:[number,number,number]}>;
  clusters:Array<{id:string;name:string;count:number}>; warnings:string[];
};
export type CityActivity = {id:number;tick:number;kind:string;state:'settled'|'rejected';targets:string[]};
export const projectCity = project as (envelope:unknown)=>CityProjection;
export const activityForCity = activity as (city:CityProjection,snapshot:unknown)=>CityActivity[];
