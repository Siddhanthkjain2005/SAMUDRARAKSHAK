export type Mission = 'control' | 'route' | 'sentinel' | 'debris' | 'investigations' | 'agents' | 'data' | 'impact' | 'status';
export interface Port {id:string;name:string;latitude:number;longitude:number;country?:string}
export interface Vessel {id:string;name:string;mmsi?:string;latitude:number;longitude:number;speed?:number;course?:number;timestamp?:string;source?:string;provenance?:string;events?:any[];track?:any[]}
export interface Provider {id:string;name:string;status:string;records:number;provenance:string;detail?:string;last_refresh?:string}
export interface Trace {agent:string;agent_name?:string;timestamp:string;status:string;message:string;output?:any}
export interface Bootstrap {providers:Provider[];stats:Record<string,number>;ports:Port[];vessels:Vessel[];debris:any[];hotspots:any[];marine:any[];agents:any[];scenarios:{routes:{origin_id:string;destination_id:string;name:string}[];investigations:string[]}}
export const emptyBootstrap:Bootstrap={providers:[],stats:{},ports:[],vessels:[],debris:[],hotspots:[],marine:[],agents:[],scenarios:{routes:[],investigations:[]}};
export async function api<T=any>(path:string,body?:unknown):Promise<T>{const r=await fetch(`/api/${path}`,{method:body===undefined?'GET':'POST',headers:body===undefined?{}:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});if(!r.ok){let reason='The service is temporarily unavailable.';try{const d=await r.json();reason=typeof d.detail==='string'?d.detail:reason;}catch{}throw new Error(reason)}return r.json()}
export const num=(v:unknown,d=0)=>typeof v==='number'&&Number.isFinite(v)?v.toLocaleString('en-IN',{maximumFractionDigits:d}):'—';
