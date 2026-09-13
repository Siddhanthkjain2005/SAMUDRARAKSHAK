from backend.agents.orchestrator import Workflow
from backend.models.behaviour_model import behaviour_features,parse_time
from backend.models.risk_model import fuse_risk,evidence_completeness
from backend.services.geospatial import jurisdiction
from backend.services.evidence_graph import evidence_graph
from backend.services.storage import now

def normalized_event(event,index,vessel=None):
    vessel=vessel or {}
    kind=str(event.get('type',event.get('eventType',event.get('event_type','event')))).lower()
    if 'gap' in kind:kind='gap'
    elif 'loiter' in kind:kind='loitering'
    elif 'fishing' in kind:kind='fishing'
    elif 'encounter' in kind:kind='encounter'
    elif 'port' in kind:kind='port_visit'
    label={'gap':'Historical AIS gap','loitering':'Historical loitering','fishing':'Apparent fishing event','encounter':'Historical encounter','port_visit':'Historical port visit'}.get(kind,kind.replace('_',' ').title())
    vessel_url=vessel.get('source_url') or ('https://gateway.api.globalfishingwatch.org/v3' if 'Global Fishing Watch' in str(vessel.get('source','')) else 'https://marinecadastre.gov/')
    id_fields={field:vessel.get(field) for field in ('mmsi','name','imo','callsign','type','heading')}
    item={'id':'event-'+str(event.get('id',index)),'label':label,'type':kind,
        'source':event.get('source') or vessel.get('source') or 'UNATTRIBUTED EVENT','timestamp':event.get('start',event.get('timestamp',event.get('startTime'))),
        'detail':event.get('description',f'{label} recorded in the provider event dataset. This is a behaviour classification, not a legal finding.'),
        'source_url':event.get('source_url') or vessel_url,'vessel_id':vessel.get('id'),'raw':event,
        'identity_fields':id_fields}
    return {**item,**evidence_completeness(item)}

def investigate(vessel,track,marine):
    workflow=Workflow('investigation','BEHAVIOUR_ANOMALY / ANALYST_REVIEW')
    identity=workflow.run('identity','Retrieved cached identity and available historical event records.',lambda:{'name':vessel.get('name'),'mmsi':vessel.get('mmsi'),'source':vessel.get('source'),'events':len(vessel.get('events',[])),'provenance':vessel.get('provenance')})
    timestamp=parse_time(vessel.get('timestamp')); now_dt=parse_time(now())
    age=(now_dt-timestamp).total_seconds()/60 if timestamp else None
    workflow.timed_record('surveillance','Checked timestamp and observation provenance.',lambda:{'last_timestamp':vessel.get('timestamp'),'age_minutes':round(age,1) if age is not None else None,'historical_staleness_is_ais_gap':False,'observations':len(track)})
    features=workflow.run('behaviour','Calculated available track features; unobserved history is left unknown.',behaviour_features,track)
    event_types={}
    for event in vessel.get('events',[]):
        kind=str(event.get('type',event.get('eventType',event.get('event_type','event')))).lower()
        kind='gap' if 'gap' in kind else 'loitering' if 'loiter' in kind else 'fishing' if 'fishing' in kind else 'encounter' if 'encounter' in kind else 'port_visit' if 'port' in kind else kind
        event_types[kind]=event_types.get(kind,0)+1
    evidence=workflow.run('dark_vessel','Assembled evidence directly from recorded provider events.',lambda:[normalized_event(e,i,vessel) for i,e in enumerate(vessel.get('events',[]))])
    if len(track)>=3:
        sources=sorted({str(p.get('source') or vessel.get('source')) for p in track if p.get('source') or vessel.get('source')})
        vessel_url=vessel.get('source_url') or ('https://gateway.api.globalfishingwatch.org/v3' if 'Global Fishing Watch' in str(vessel.get('source','')) else 'https://marinecadastre.gov/')
        id_fields={field:vessel.get(field) for field in ('mmsi','name','imo','callsign','type','heading')}
        item={'id':'observed-track','label':'Recorded AIS behaviour','type':'behaviour','source':'; '.join(sources) or 'SOURCE UNAVAILABLE',
            'source_url':vessel.get('source_url') or vessel_url,'vessel_id':vessel.get('id'),'timestamp':track[-1].get('timestamp'),
            'detail':'; '.join(features['reasons']) or 'No configured trajectory anomaly threshold exceeded.',
            'raw':{'features':features,'observations':track},'provenance':vessel.get('provenance'),'geographic_context':vessel.get('geographic_context'),
            'identity_fields':id_fields,
            'coverage':{'samples':features.get('samples'),'duration_minutes':features.get('duration_minutes')}}
        evidence.append({**item,**evidence_completeness(item)})
    if vessel.get('latitude') is not None and vessel.get('longitude') is not None:
        boundary=workflow.run('jurisdiction','Checked downloaded jurisdiction geometry; no legal conclusion inferred.',jurisdiction,vessel['latitude'],vessel['longitude'])
    else:
        boundary=workflow.record('jurisdiction','Vessel has no verified position for polygon lookup.',{'matches':[],'coverage':'POSITION UNAVAILABLE','legal_determination':False})
    workflow.timed_record('environment','Checked available marine context separately from event-time weather.',lambda:{'samples':len(marine),'historical_weather_matched':False,'numeric_values_used_for_risk':False,'note':'Present forecasts are not evidence of weather during a historical event.'})
    skeptic=[
        'AIS silence can reflect reception coverage, antenna failure, transmission limits or equipment faults; it is not proof of deliberate concealment.',
        'Apparent fishing, loitering and encounters can be lawful. No fishing authorization or complete legal determination is available.',
        'Satellite detections are not added unless an actual sourced observation exists; no satellite identity link is inferred.',
        'Historical sample age is not treated as a live tracking gap.',
        'The end of a downloaded or truncated AIS recording is a sample boundary, not evidence that a vessel stopped transmitting.',
        'Evidence from a single provider is not independent corroboration.',
    ]
    if not evidence:skeptic.append('No recorded behavioural event or adequate trajectory is available. This case cannot support an elevated finding.')
    if len(track)<3:skeptic.append('Insufficient sequential AIS positions for trajectory anomaly analysis.')
    if not boundary['matches']:skeptic.append('No verified jurisdiction match was available at this position.')
    workflow.timed_record('skeptic','Tested innocent explanations and downgraded unsupported inferences.',lambda:{'findings':skeptic,'independent_satellite_corroboration':False})
    # Jurisdiction is evidence context. Only an actual MPA polygon can create a
    # protected_area screening signal; EEZ/territorial context never implies a violation.
    id_fields={field:vessel.get(field) for field in ('mmsi','name','imo','callsign','type','heading')}
    for index,match in enumerate(boundary.get('matches',[])):
        source=str(match.get('source') or 'boundary dataset')
        kind='protected_area' if 'mpa' in source.lower() else 'jurisdiction_context'
        item={'id':f'boundary-{index}','label':match.get('name','Verified marine boundary context'),'type':kind,
              'source':source,'timestamp':vessel.get('timestamp'),'source_url':'https://www.marineregions.org/downloads.php',
              'vessel_id':vessel.get('id'),'raw':match,'detail':'Polygon context only; this is not a legal determination.',
              'identity_fields':id_fields}
        evidence.append({**item,**evidence_completeness(item)})
    risk=workflow.run('risk','Fused structured screening signals and evidence confidence separately.',fuse_risk,evidence,features)
    input_audit={'track':{'samples':features.get('samples'),'duration_minutes':features.get('duration_minutes'),
                          'source':sorted({str(p.get('source') or vessel.get('source')) for p in track if p.get('source') or vessel.get('source')}),
                          'fields_used':['latitude','longitude','timestamp','speed/sog','course/cog']},
                 'identity':{'fields_available':[field for field in ('mmsi','name','imo','callsign','type','heading') if vessel.get(field) is not None and vessel.get(field) != ''],
                             'source':vessel.get('source'),'used_for':'identity evidence completeness and display'},
                 'historical_events':{'count':sum(event_types.values()),'types':event_types,'used_for':'weighted event signals'},
                 'jurisdiction':{'matches':len(boundary.get('matches',[])),'mpa_matches':sum('mpa' in str(m.get('source','')).lower() for m in boundary.get('matches',[])),
                                 'used_for':'context; MPA matches may add protected_area points'},
                 'marine':{'samples_available':len(marine),'used_for_risk':False,'reason':'current forecasts are not evidence of conditions during historical AIS events'},
                 'risk_signals':risk.get('contributors',[])}
    return workflow.finish({'vessel':vessel,**risk,'evidence':evidence,'graph':evidence_graph(vessel,evidence),
        'behaviour':features,'jurisdiction':boundary,'skeptic':skeptic,
        'input_audit':input_audit,
        'recommendation':'Human analyst review recommended; verify coverage, vessel authorization and independent evidence before action.' if risk['risk_score']>=35 else 'Continue observation. Available evidence does not support an elevated finding.',
        'assumptions':['Decision-support prototype. Maritime activity classifications require human verification.','Risk score is a screening index, not a probability of illegal activity. No enforcement action is automated.']})
