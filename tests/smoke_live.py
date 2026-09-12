"""Local end-to-end check against a running server; prints only non-secret results."""
import json
import time
import httpx

with httpx.Client(base_url='http://127.0.0.1:8000',timeout=120) as client:
    response=client.get('/api/bootstrap');response.raise_for_status();data=response.json()
    print(json.dumps({'bootstrap':data['stats'],'providers':[{k:p.get(k) for k in ('name','status','records')} for p in data['providers']]},indent=2),flush=True)
    for origin,destination in [('mangaluru','kochi'),('mumbai','mangaluru')]:
        started=time.monotonic()
        response=client.post('/api/routes/optimize',json={'origin_id':origin,'destination_id':destination,'speed_knots':12,'reference_fuel_tpd':24});response.raise_for_status();result=response.json()
        print(json.dumps({'route':origin+'-'+destination,'seconds':round(time.monotonic()-started,1),'id':result['id'],'savings':result['savings'],'graph':result['graph'],'forecast_coverage_pct':result['optimized']['forecast_coverage_pct']}),flush=True)
        report=client.get('/api/reports/'+result['id']);assert report.status_code==200 and 'Save PDF' in report.text
    response=client.post('/api/cleanup/plan',json={'hours':6,'collectors':3});response.raise_for_status();cleanup=response.json()
    print(json.dumps({'cleanup':cleanup['id'],'hotspots':len(cleanup['hotspots']),'assignments':len(cleanup['assignments']),'summary':cleanup['summary']}),flush=True)
    response=client.post('/api/cleanup/replan',json={'mission_id':cleanup['id'],'event':'battery_drop','collector_id':cleanup['assignments'][0]['collector_id'] if cleanup['assignments'] else 'collector-1'});response.raise_for_status();replan=response.json()
    print(json.dumps({'replan':replan['id'],'assignments':len(replan['assignments']),'batteries':{c['id']:c['battery'] for c in replan['collectors']}}),flush=True)
    data=client.get('/api/bootstrap').json()
    if data['vessels']:
        response=client.post('/api/investigations/'+data['vessels'][0]['id']);response.raise_for_status();result=response.json()
        print(json.dumps({'investigation':result['id'],'risk_score':result['risk_score'],'confidence_score':result['confidence_score'],'evidence_count':len(result['evidence'])}),flush=True)
    print('SMOKE CHECKS PASSED',flush=True)
