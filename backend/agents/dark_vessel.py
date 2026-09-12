from backend.agents.orchestrator import Workflow
from backend.models.behaviour_model import behaviour_features,parse_time
from backend.models.risk_model import fuse_risk
from backend.services.geospatial import jurisdiction
from backend.services.evidence_graph import evidence_graph
from backend.services.storage import now

def normalized_event(event,index):
    kind=str(event.get('type',event.get('eventType',event.get('event_type','event')))).lower()
    if 'gap' in kind:kind='gap'
    elif 'loiter' in kind:kind='loitering'
    elif 'fishing' in kind:kind='fishing'
    elif 'encounter' in kind:kind='encounter'
    elif 'port' in kind:kind='port_visit'
    label={'gap':'Historical AIS gap','loitering':'Historical loitering','fishing':'Apparent fishing event','encounter':'Historical encounter','port_visit':'Historical port visit'}.get(kind,kind.replace('_',' ').title())
    return {'id':'event-'+str(event.get('id',index)),'label':label,'type':kind,
        'source':event.get('source','Global Fishing Watch'),'timestamp':event.get('start',event.get('timestamp',event.get('startTime'))),
        'detail':event.get('description',f'{label} recorded in the provider event dataset. This is a behaviour classification, not a legal finding.'),
        'confidence':70 if kind!='sar_candidate' else 35,'raw':event}

def investigate(vessel,track,marine):
    workflow=Workflow('investigation','BEHAVIOUR_ANOMALY / ANALYST_REVIEW')
    identity=workflow.run('identity','Retrieved cached identity and available historical event records.',lambda:{'name':vessel.get('name'),'mmsi':vessel.get('mmsi'),'source':vessel.get('source'),'events':len(vessel.get('events',[])),'provenance':vessel.get('provenance')})
    timestamp=parse_time(vessel.get('timestamp')); now_dt=parse_time(now())
    age=(now_dt-timestamp).total_seconds()/60 if timestamp else None
    workflow.record('surveillance','Checked timestamp and observation provenance.',{'last_timestamp':vessel.get('timestamp'),'age_minutes':round(age,1) if age is not None else None,'historical_staleness_is_ais_gap':False,'observations':len(track)})
    features=workflow.run('behaviour','Calculated available track features; unobserved history is left unknown.',behaviour_features,track)
    evidence=workflow.run('dark_vessel','Assembled evidence directly from recorded provider events.',lambda:[normalized_event(e,i) for i,e in enumerate(vessel.get('events',[]))])
    if len(track)>=3:
        evidence.append({'id':'observed-track','label':'Recorded AIS behaviour','type':'behaviour','source':'AISStream PositionReport','timestamp':track[-1].get('timestamp'),'detail':'; '.join(features['reasons']) or 'No configured trajectory anomaly threshold exceeded.','confidence':75,'raw':features})
    if vessel.get('latitude') is not None and vessel.get('longitude') is not None:
        boundary=workflow.run('jurisdiction','Checked downloaded jurisdiction geometry; no legal conclusion inferred.',jurisdiction,vessel['latitude'],vessel['longitude'])
    else:
        boundary=workflow.record('jurisdiction','Vessel has no verified position for polygon lookup.',{'matches':[],'coverage':'POSITION UNAVAILABLE','legal_determination':False})
    workflow.record('environment','Checked available marine context separately from event-time weather.',{'samples':len(marine),'historical_weather_matched':False,'note':'Present forecasts are not evidence of weather during a historical event.'})
    skeptic=[
        'AIS silence can reflect reception coverage, antenna failure, transmission limits or equipment faults; it is not proof of deliberate concealment.',
        'Apparent fishing, loitering and encounters can be lawful. No fishing authorization or complete legal determination is available.',
        'Satellite detections are not added unless an actual sourced observation exists; no satellite identity link is inferred.',
        'Historical sample age is not treated as a live tracking gap.',
        'Evidence from a single provider is not independent corroboration.',
    ]
    if not evidence:skeptic.append('No recorded behavioural event or adequate trajectory is available. This case cannot support an elevated finding.')
    if len(track)<3:skeptic.append('Insufficient sequential AIS positions for trajectory anomaly analysis.')
    if not boundary['matches']:skeptic.append('No verified jurisdiction match was available at this position.')
    workflow.record('skeptic','Tested innocent explanations and downgraded unsupported inferences.',{'findings':skeptic,'independent_satellite_corroboration':False})
    risk=workflow.run('risk','Fused structured screening signals and evidence confidence separately.',fuse_risk,evidence,features)
    return workflow.finish({'vessel':vessel,**risk,'evidence':evidence,'graph':evidence_graph(vessel,evidence),
        'behaviour':features,'jurisdiction':boundary,'skeptic':skeptic,
        'recommendation':'Human analyst review recommended; verify coverage, vessel authorization and independent evidence before action.' if risk['risk_score']>=35 else 'Continue observation. Available evidence does not support an elevated finding.',
        'assumptions':['Decision-support prototype. Maritime activity classifications require human verification.','Risk score is a screening index, not a probability of illegal activity. No enforcement action is automated.']})
