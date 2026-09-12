import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from functools import lru_cache
from fastapi import FastAPI,HTTPException,WebSocket,WebSocketDisconnect,Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from backend import config
from backend.schemas import RouteRequest,CleanupRequest,ReplanRequest,CommandRequest,ReplayRequest
from backend.services import storage
from backend.services.data_catalog import records,catalog,vessels as historical_vessels,read_json
from backend.services.geospatial import haversine
from backend.services.route_optimizer import optimize_route,RouteUnavailable
from backend.services.websocket_manager import manager
from backend.services.replay_engine import replay_recording
from backend.agents.orchestrator import Workflow,agent_states,STATE
from backend.agents.dark_vessel import investigate
from backend.agents.debris_intelligence import cluster_debris
from backend.agents.debris_coordinator import cleanup_plan
from backend.agents.reporter import render_report
from backend.models.behaviour_model import behaviour_features,parse_time
from backend.providers.aisstream import AISStreamProvider
from backend.providers.global_fishing_watch import GlobalFishingWatchProvider
from backend.providers.marine_weather import OpenMeteoProvider
from backend.providers.llm import GroqProvider

logger=logging.getLogger(__name__)
storage.initialize()
ais=AISStreamProvider(); gfw=GlobalFishingWatchProvider(); marine_provider=OpenMeteoProvider(); llm=GroqProvider()
background_tasks=set()
last_analysis={}
last_broadcast={}

def track_task(coroutine):
    task=asyncio.create_task(coroutine);background_tasks.add(task);task.add_done_callback(background_tasks.discard);return task

async def on_ais(observation):
    mmsi=observation['mmsi'];stamp=time.monotonic()
    if stamp-last_broadcast.get(mmsi,0)>2:
        last_broadcast[mmsi]=stamp
        await manager.broadcast('ais',observation)
    if stamp-last_analysis.get(mmsi,0)<120:return
    last_analysis[mmsi]=stamp
    track=await asyncio.to_thread(storage.ais_observations,120,mmsi)
    features=behaviour_features(track)
    STATE['surveillance'].update(status='COMPLETED',last_output={'mmsi':mmsi,'recorded_observations':len(track),'timestamp':observation['timestamp']})
    if features['anomaly_score']>=55:
        result=await asyncio.to_thread(investigate,observation,track,records('marine'))
        await persist_and_publish(result)

async def verify_providers():
    await asyncio.gather(gfw.search('MANGALORE',1),llm.explain('Report readiness in one sentence.',{'platform':'SamudraRakshak AI','mode':'decision support','numerical_engines':'authoritative'}),return_exceptions=True)

@asynccontextmanager
async def lifespan(app):
    if config.LIVE_ENABLED and config.AISSTREAM_API_KEY:track_task(ais.run(on_ais))
    track_task(verify_providers())
    yield
    for task in list(background_tasks):task.cancel()
    await asyncio.gather(*background_tasks,return_exceptions=True)

app=FastAPI(title='SamudraRakshak AI',version='1.0.0',description='Unified maritime decision-support engine with auditable real-data provenance.',lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=['http://localhost:3000','http://127.0.0.1:3000','http://localhost:3001','http://127.0.0.1:3001'],allow_methods=['GET','POST'],allow_headers=['Content-Type'])

def get_vessels():
    found={str(v['id']):v for v in historical_vessels()}
    now=storage.now(); current=parse_time(now)
    for v in storage.live_vessels():
        old=found.get(v['id'],{});timestamp=parse_time(v.get('timestamp'))
        is_recent=timestamp is not None and (current-timestamp).total_seconds()<600
        v={**old,**v,'events':old.get('events',[]),'provenance':'LIVE' if is_recent and ais.state['status']=='LIVE' else 'REAL DATA · OFFLINE CACHE'}
        found[v['id']]=v
    return list(found.values())

@lru_cache(maxsize=8)
def _hotspots_cache(modified):return cluster_debris(records('debris'))

def get_hotspots():
    path=config.PROCESSED/'debris.json'
    return _hotspots_cache(path.stat().st_mtime_ns if path.exists() else 0)

def providers():
    hist=historical_vessels();marine=records('marine');debris=records('debris');ports=records('ports')
    entries=catalog();entries=entries if isinstance(entries,list) else []
    boundary_count=sum(len(read_json(name,{}).get('features',[])) for name in ('boundaries.geojson','mpa.geojson') if isinstance(read_json(name,{}),dict))
    items=[
        {'id':'google_maps','name':'Google Maps','status':'CONFIGURED' if config.GOOGLE_MAPS_API_KEY else 'MISSING KEY','records':None,'provenance':'MAP PROVIDER','detail':'Browser map availability is verified by the map component.'},
        {'id':'aisstream','name':'AISStream',**ais.state,'records':storage.ais_count(),'provenance':'LIVE' if ais.state['status']=='LIVE' else 'OFFLINE CACHE'},
        {'id':'gfw','name':'Global Fishing Watch',**gfw.state,'records':len(hist),'provenance':'HISTORICAL'},
        {'id':'marine','name':'Open-Meteo Marine','status':'MODEL FORECAST' if marine else 'UNAVAILABLE','records':len(marine),'provenance':'MODEL FORECAST','detail':'Cached numerical marine forecast, not in-situ observation.','last_refresh':max([str(m.get('timestamp','')) for m in marine] or [''])},
        {'id':'debris','name':'Marine Debris Observations','status':'OFFLINE REAL DATASET' if debris else 'UNAVAILABLE','records':len(debris),'provenance':'HISTORICAL REAL DATA','detail':'Real sampled debris observations; historical concentration is not present-day recoverable mass.'},
        {'id':'ports','name':'World Ports','status':'LOCAL CACHE' if ports else 'UNAVAILABLE','records':len(ports),'provenance':'REAL DATA','detail':'Downloaded real port coordinates and identities.'},
        {'id':'boundaries','name':'Marine Boundaries','status':'LOCAL CACHE' if boundary_count else 'UNAVAILABLE','records':boundary_count,'provenance':'REAL DATA','detail':'Downloaded polygons; boundary legal interpretation requires verification.'},
        {'id':'llm','name':'Groq Intelligence',**llm.state,'records':None,'provenance':'AI EXPLANATION'},
        {'id':'database','name':'Mission / AIS Store','status':'SQLITE READY','records':storage.ais_count(),'provenance':'LOCAL PERSISTENCE','detail':'SQLite WAL durable fallback. Optional PostGIS is provided by Docker Compose.'},
    ]
    return items

def route_scenarios(ports):
    aliases=[('mangaluru','kochi','Mangaluru → Kochi'),('mumbai','mangaluru','Mumbai → Mangaluru')]
    ids={p['id'] for p in ports}
    return [{'origin_id':a,'destination_id':b,'name':n} for a,b,n in aliases if a in ids and b in ids]

@app.get('/api/health')
def health():return {'status':'ok','service':'samudrarakshak','database':'sqlite','timestamp':storage.now()}

@app.get('/api/config')
def public_config():return {'google_maps_key':config.GOOGLE_MAPS_API_KEY}

@app.get('/api/bootstrap')
def bootstrap():
    v=get_vessels();p=records('ports');d=records('debris');h=get_hotspots();missions=storage.recent_missions()
    routes=[m for m in missions if m['type']=='route'];cleanups=[m for m in missions if m['type']=='cleanup'];investigations=[m for m in missions if m['type']=='investigation']
    return {'providers':providers(),'stats':{'live_vessels':sum(x['provenance']=='LIVE' for x in v),'vessels':len(v),'ports':len(p),
        'debris_observations':len(d),'hotspots':len(h),'investigations':len(investigations),
        'fuel_saved_t':round(sum(m['savings']['fuel_t'] for m in routes),3),'co2_avoided_t':round(sum(m['savings']['co2_t'] for m in routes),3),
        'active_collectors':len(cleanups[0]['assignments']) if cleanups else 0,'recorded_ais_observations':storage.ais_count()},
        'ports':p,'vessels':v[:1000],'debris':d[:2500],'hotspots':h,'marine':records('marine'),'agents':agent_states(),
        'scenarios':{'routes':route_scenarios(p),'investigations':[x['id'] for x in v[:3]],'historical_investigations':[x['id'] for x in historical_vessels()[:3]]},
        'recent_missions':[{'id':m['id'],'type':m['type'],'created_at':m.get('created_at'),'report_url':m.get('report_url')} for m in missions[:10]],
        'notice':'Decision-support prototype. Maritime activity classifications require human verification.'}

@app.get('/api/providers')
def provider_status():return providers()

@app.get('/api/agents')
def agents():return agent_states()

@app.get('/api/ports')
def port_search(q:str='',limit:int=Query(40,ge=1,le=2000)):
    return [p for p in records('ports') if q.lower() in (p.get('name','')+' '+p.get('country','')).lower()][:limit]

@app.get('/api/vessels')
def vessel_list():return get_vessels()

@app.get('/api/vessels/{identifier}')
def vessel_details(identifier:str):
    vessel=next((v for v in get_vessels() if v['id']==identifier or str(v.get('mmsi'))==identifier),None)
    if vessel is None:raise HTTPException(404,'No recorded vessel with this identifier.')
    track=storage.ais_observations(200,vessel.get('mmsi',identifier)) or vessel.get('track',[])
    return {**vessel,'track':track,'behaviour':behaviour_features(track)}

@app.get('/api/map/land')
def land_geojson():return read_json('land.geojson',{'type':'FeatureCollection','features':[]})

@app.get('/api/map/boundaries')
def boundary_geojson():
    features=[]
    for name in ('boundaries.geojson','mpa.geojson'):
        data=read_json(name,{})
        if isinstance(data,dict):features.extend(data.get('features',[]))
    return {'type':'FeatureCollection','features':features}

@app.get('/api/map/mpa')
def mpa_geojson():return read_json('mpa.geojson',{'type':'FeatureCollection','features':[]})

@app.get('/api/data/catalog')
def data_catalog():return catalog()

@app.get('/api/data/{dataset}')
def data_preview(dataset:str,limit:int=Query(20,ge=1,le=500),offset:int=Query(0,ge=0)):
    allowed={'ports','vessels','debris','marine','bathymetry'}
    if dataset not in allowed:raise HTTPException(404,'Unknown preview dataset.')
    rows=records(dataset)
    return {'dataset':dataset,'count':len(rows),'offset':offset,'rows':rows[offset:offset+limit]}

async def persist_and_publish(mission):
    await asyncio.to_thread(storage.save_mission,mission)
    for entry in mission.get('trace',[]):await manager.broadcast('agent_trace',entry)
    await manager.broadcast('mission',{'id':mission['id'],'type':mission['type'],'created_at':mission.get('created_at')})
    return mission

def route_workflow(request):
    ports=records('ports');origin=next((p for p in ports if str(p['id'])==request.origin_id),None);destination=next((p for p in ports if str(p['id'])==request.destination_id),None)
    if not origin or not destination:raise HTTPException(422,'Origin or destination port is not present in the real port cache.')
    workflow=Workflow('route','NEW_SHIPPING_MISSION')
    marine=records('marine')
    workflow.record('environment','Loaded normalized surface current and wave forecast samples.',{'samples':len(marine),'provenance':'MODEL FORECAST'})
    try:
        result=workflow.run('green_route','Solved shortest-distance and minimum-fuel paths on the same land-filtered graph.',optimize_route,origin,destination,marine,request.speed_knots,request.reference_fuel_tpd,request.safety_buffer_km)
    except RouteUnavailable as exc:raise HTTPException(422,str(exc)) from exc
    workflow.record('skeptic','Verified route constraints and exposed model limitations.',{'land_intersections':0,'navigational_certification':False,'savings_derived_from_engine':True})
    return workflow.finish(result)

@app.post('/api/routes/optimize')
async def route_endpoint(request:RouteRequest):return await persist_and_publish(await asyncio.to_thread(route_workflow,request))

@app.post('/api/investigations/{identifier}')
async def investigation_endpoint(identifier:str):
    vessel=vessel_details(identifier)
    result=await asyncio.to_thread(investigate,vessel,vessel.get('track',[]),records('marine'))
    return await persist_and_publish(result)

@app.post('/api/cleanup/plan')
async def cleanup_endpoint(request:CleanupRequest):
    result=await asyncio.to_thread(cleanup_plan,records('debris'),records('marine'),request.hours,request.collectors)
    return await persist_and_publish(result)

@app.post('/api/cleanup/replan')
async def replan_endpoint(request:ReplanRequest):
    previous=storage.mission_by_id(request.mission_id)
    if not previous or previous['type']!='cleanup':raise HTTPException(404,'Cleanup mission not found.')
    result=await asyncio.to_thread(cleanup_plan,records('debris'),records('marine'),previous.get('hours',6),len(previous.get('collectors',[])) or 3,previous,request.event,request.collector_id)
    return await persist_and_publish(result)

@app.get('/api/missions/{identifier}')
def mission_endpoint(identifier:str):
    result=storage.mission_by_id(identifier)
    if result is None:raise HTTPException(404,'Mission not found.')
    return result

@app.get('/api/reports/{identifier}',response_class=HTMLResponse)
def report_endpoint(identifier:str):return render_report(mission_endpoint(identifier))

@app.post('/api/command')
async def command_endpoint(request:CommandRequest):
    message=request.message.lower();action='overview';mission=None
    ports=records('ports');mentioned=[]
    aliases={'mangalore':'mangaluru','cochin':'kochi','bombay':'mumbai'}
    for old,new in aliases.items():message=message.replace(old,new)
    for p in ports:
        names=[str(p.get('id','')).lower(),str(p.get('name','')).lower()]
        if any(len(name)>3 and name in message for name in names):mentioned.append(p)
    mentioned.sort(key=lambda p:min([message.find(n) for n in [str(p['id']).lower(),p['name'].lower()] if n in message] or [9999]))
    if any(word in message for word in ('optimize','route','shipping')):
        action='route'
        if len(mentioned)>=2:
            mission=await route_endpoint(RouteRequest(origin_id=mentioned[0]['id'],destination_id=mentioned[1]['id']))
        else:
            return {'message':'Choose an origin and destination in Green Route, or name two cached ports, for example “Optimize Mangaluru to Kochi.”','action':'route','source':'DETERMINISTIC COMMAND ROUTER'}
    elif any(word in message for word in ('debris','cleanup','collector','hotspot')):
        action='cleanup';mission=await cleanup_endpoint(CleanupRequest())
    elif any(word in message for word in ('suspicious','vessel','investigat','flagged','fishing')):
        action='investigation';available=get_vessels()
        selected=next((v for v in available if str(v['id']).lower() in message or v['name'].lower() in message),available[0] if available else None)
        if selected:mission=await investigation_endpoint(selected['id'])
        else:return {'message':'No real vessel observations or historical cases are cached yet. AISStream is recording when available; GFW access status is visible in Data Explorer. No vessel evidence has been fabricated.','action':action,'source':'DETERMINISTIC COMMAND ROUTER'}
    context={'stats':bootstrap()['stats'],'providers':[{'name':p['name'],'status':p['status']} for p in providers()]}
    fallback='The command layer can optimize routes between cached ports, inspect recorded vessel evidence, and plan simulated collector assignments against real debris observations.'
    if mission:
        context={'mission_type':mission['type'],'savings':mission.get('savings'),'risk_score':mission.get('risk_score'),'confidence_score':mission.get('confidence_score'),'summary':mission.get('summary'),'explanation':mission.get('explanation'),'recommendation':mission.get('recommendation'),'assumptions':mission.get('assumptions')}
        fallback=mission.get('explanation',mission.get('recommendation',f"Assigned {len(mission.get('assignments',[]))} simulated collectors to real historical observation clusters. No kilograms collected are claimed."))
    explanation=await llm.explain(request.message,context)
    return {'message':explanation or fallback,'action':action,'mission':mission,'source':'GROQ · VERIFIED ENGINE CONTEXT' if explanation else 'DETERMINISTIC ENGINE EXPLANATION'}

@app.post('/api/replay/start')
async def replay_endpoint(request:ReplayRequest):
    count=storage.ais_count()
    if not count:raise HTTPException(409,'No real AIS observations have been recorded. Replay cannot create artificial vessel positions.')
    track_task(replay_recording(manager,request.speed,request.limit))
    return {'status':'REPLAY STARTED','observations':min(count,request.limit),'provenance':'REAL DATA · DEMO REPLAY'}

@app.websocket('/ws')
async def websocket_endpoint(websocket:WebSocket):
    await manager.connect(websocket)
    try:
        await websocket.send_json({'type':'connected','data':{'timestamp':storage.now(),'provenance':'Events retain their original source timestamp.'}})
        while True:
            message=await websocket.receive_text()
            if message=='ping':await websocket.send_json({'type':'pong','data':{'timestamp':storage.now()}})
    except (WebSocketDisconnect,RuntimeError):manager.disconnect(websocket)
