import asyncio
from copy import deepcopy
from datetime import datetime,timezone,timedelta
import time
import pytest
from fastapi.testclient import TestClient
from backend import main
from backend.services import storage
from backend.services.data_catalog import records
from backend.services.replay_engine import ReplayController,ReplayUnavailable,load_recording
from backend.models.behaviour_model import parse_time
from backend.agents.dark_vessel import investigate,normalized_event
from backend.providers.aisstream import AISStreamProvider


class RecordingManager:
    def __init__(self):self.messages=[]
    async def broadcast(self,kind,data):self.messages.append({'type':kind,'data':deepcopy(data)})


@pytest.fixture
def offline_client(monkeypatch,tmp_path):
    monkeypatch.setattr(storage,'SQLITE_PATH',tmp_path/'isolated.sqlite3')
    storage.initialize()
    monkeypatch.setattr(main.config,'LIVE_ENABLED',False)
    async def no_network():return None
    monkeypatch.setattr(main,'verify_providers',no_network)
    monkeypatch.setattr(main,'replay',ReplayController(main.manager))
    with TestClient(main.app) as client:yield client


def real_vessel():
    vessel=next((v for v in records('vessels') if 'NOAA' in v.get('source','') and len(v.get('track',[]))>=3),None)
    if vessel is None:pytest.skip('Real NOAA replay archive not installed.')
    return vessel


def test_aisstream_go_timestamp_parses_without_modifying_source():
    source='2026-09-13 00:57:17.548771885 +0000 UTC'
    assert parse_time(source)==datetime(2026,9,13,0,57,17,548771,tzinfo=timezone.utc)
    assert source.endswith(' +0000 UTC')
    assert parse_time('2026-09-13T00:57:17Z')==parse_time('2026-09-13 00:57:17 UTC')


def test_provider_freshness_never_reports_stale_live():
    provider=AISStreamProvider('test-only')
    stale=(datetime.now(timezone.utc)-timedelta(minutes=5)).isoformat()
    provider.state.update(status='LIVE',last_refresh=stale)
    assert provider.snapshot()['status']=='CONNECTED · NO RECENT DATA'
    provider.state['last_refresh']=datetime.now(timezone.utc).isoformat()
    assert provider.snapshot()['status']=='LIVE'


def test_real_historical_evidence_preserves_provider_and_original_samples():
    vessel=real_vessel();original=deepcopy(vessel['track'])
    result=investigate(vessel,vessel['track'],[])
    evidence=next(e for e in result['evidence'] if e['id']=='observed-track')
    assert evidence['source']=='NOAA MarineCadastre AIS'
    assert evidence['raw']['observations']==original
    assert 'AISStream' not in evidence['source']
    assert not any(e['type']=='gap' for e in result['evidence'])
    assert evidence['confidence']==sum(c['points'] for c in evidence['confidence_components'])
    assert 'not a calibrated probability' in evidence['confidence_methodology']
    assert 0 < result['confidence_score'] < 95
    assert result['source_count']==1


def test_unattributed_event_never_claims_gfw_source():
    event=normalized_event({'type':'fishing'},0)
    assert event['source']=='UNATTRIBUTED EVENT'
    assert event['confidence_components'][0]['points']==0


def test_provider_counts_keep_noaa_gfw_and_identity_distinct(offline_client):
    providers={p['id']:p for p in offline_client.get('/api/providers').json()}
    assert providers['gfw']['records']==len(records('gfw_identity'))
    assert providers['noaa_ais']['replay_vessels']==sum('NOAA' in v.get('source','') for v in records('vessels'))
    assert providers['vessel_identity']['records']==len({str(v.get('mmsi') or v.get('id')) for v in records('vessel_identity')+records('gfw_identity')})
    assert providers['bathymetry']['records']==len(records('bathymetry'))


def test_regional_command_never_silently_selects_us_vessel(offline_client,monkeypatch):
    monkeypatch.setattr(main,'get_vessels',lambda:[real_vessel()])
    response=offline_client.post('/api/command',json={'message':'Show suspicious vessels near Karnataka.'})
    assert response.status_code==200
    result=response.json()
    assert result['mission'] is None and result['results']==[]
    assert 'No cached real vessel positions match Karnataka' in result['message']
    assert storage.mission_summaries()['total']==0


def test_replay_controls_real_track_websocket_and_database_integrity(offline_client):
    vessel=real_vessel();before=deepcopy(vessel['track']);count=storage.ais_count()
    with offline_client.websocket_connect('/ws') as websocket:
        assert websocket.receive_json()['type']=='connected'
        response=offline_client.post('/api/replay/start',json={'vessel_id':vessel['id'],'speed':1,'limit':4})
        assert response.status_code==200
        state=response.json();assert state['status']=='RUNNING' and state['source']==vessel['source']
        for _ in range(8):
            message=websocket.receive_json()
            if message['type']=='ais':break
        point=message['data'];assert message['type']=='ais'
        assert point['timestamp']==before[0]['timestamp']==point['original_timestamp']
        assert point['latitude']==before[0]['latitude'] and point['longitude']==before[0]['longitude']
        assert point['replay'] and point['provenance']=='REAL DATA · DEMO REPLAY'
        assert point['id']==vessel['id']
        paused=offline_client.post('/api/replay/pause').json();assert paused['status']=='PAUSED'
        time.sleep(.05)
        assert offline_client.get('/api/replay/status').json()['index']==paused['index']
        assert offline_client.post('/api/replay/resume').json()['status']=='RUNNING'
        assert offline_client.post('/api/replay/stop').json()['status']=='STOPPED'
        assert offline_client.get('/api/replay/status').json()['session_id']==state['session_id']
    assert storage.ais_count()==count
    assert real_vessel()['track']==before


def test_invalid_replay_does_not_replace_valid_session(offline_client):
    vessel=real_vessel()
    session=offline_client.post('/api/replay/start',json={'vessel_id':vessel['id'],'speed':1}).json()
    assert offline_client.post('/api/replay/start',json={'vessel_id':'nonexistent-real-vessel'}).status_code==409
    assert offline_client.get('/api/replay/status').json()['session_id']==session['session_id']
    offline_client.post('/api/replay/stop')


@pytest.mark.asyncio
async def test_replay_completion_and_replacement_are_single_session():
    vessel=real_vessel();manager=RecordingManager();controller=ReplayController(manager)
    first=await controller.start(vessel['id'],speed=1,limit=3)
    await asyncio.sleep(.01)
    second=await controller.start(vessel['id'],speed=3600,limit=3)
    await asyncio.wait_for(controller.task,timeout=2)
    assert controller.snapshot()['status']=='COMPLETED'
    assert 'not evidence of tracking silence' in controller.snapshot()['detail']
    emitted=[m['data'] for m in manager.messages if m['type']=='ais']
    second_points=[p for p in emitted if p['replay_session_id']==second['session_id']]
    assert [p['timestamp'] for p in second_points]==[p['timestamp'] for p in vessel['track'][:3]]
    first_after_second=False;seen_second=False
    for point in emitted:
        seen_second=seen_second or point['replay_session_id']==second['session_id']
        first_after_second=first_after_second or (seen_second and point['replay_session_id']==first['session_id'])
    assert not first_after_second


def test_repeated_missions_do_not_inflate_scenario_impact(offline_client):
    for index,fuel in enumerate((3,2)):
        storage.save_mission({'id':f'route-test-{index}','type':'route','origin':{'id':'a','name':'A'},'destination':{'id':'b','name':'B'},'savings':{'fuel_t':fuel,'co2_t':fuel*3.114}})
        storage.save_mission({'id':f'investigation-test-{index}','type':'investigation','vessel':{'id':'same-vessel','name':'A'}})
    totals=storage.impact_summary()
    assert totals['unique_route_scenarios']==1 and totals['fuel_saved_t']==2
    assert totals['investigations']==1 and totals['reports_generated']==4
    response=offline_client.get('/api/missions?type=route&limit=1').json()
    assert response['total']==2 and len(response['missions'])==1
    assert response['missions'][0]['title']=='A → B'
    assert offline_client.get('/api/missions?type=other').status_code==422


def test_original_live_timestamp_drives_live_vessel_badge(offline_client,monkeypatch):
    instant=datetime.now(timezone.utc)
    source=instant.strftime('%Y-%m-%d %H:%M:%S.%f')+'123 +0000 UTC'
    storage.record_ais({'id':'test-live-mmsi','mmsi':'test-live-mmsi','name':'Synthetic test fixture only',
        'latitude':13,'longitude':74,'timestamp':source,'received_at':instant.isoformat(),'source':'AISStream PositionReport'})
    monkeypatch.setattr(main.ais,'state',{'status':'LIVE','last_refresh':instant.isoformat(),'detail':'Test fixture'})
    vessel=next(v for v in offline_client.get('/api/vessels').json() if v['id']=='test-live-mmsi')
    assert vessel['provenance']=='LIVE'
    assert vessel['timestamp']==source
    main.ais.state['last_refresh']=(instant-timedelta(minutes=10)).isoformat()
    stale=next(v for v in offline_client.get('/api/vessels').json() if v['id']=='test-live-mmsi')
    assert stale['provenance']=='REAL DATA · OFFLINE CACHE'


def test_three_missions_and_replanning_work_offline_with_real_cache(offline_client):
    port_ids={p['id'] for p in records('ports')}
    if not {'mangaluru','kochi'}<=port_ids:pytest.skip('Regional real port cache not installed.')
    route=offline_client.post('/api/routes/optimize',json={'origin_id':'mangaluru','destination_id':'kochi','speed_knots':12,'reference_fuel_tpd':24})
    assert route.status_code==200
    route=route.json()
    assert route['optimized']['distance_nm']>100
    assert route['optimized']['land_intersections']==0
    assert route['optimized']['fuel_t']<=route['baseline']['fuel_t']+.001
    cleanup=offline_client.post('/api/cleanup/plan',json={'hours':6,'collectors':3})
    assert cleanup.status_code==200
    cleanup=cleanup.json();assert cleanup['hotspots']
    target=cleanup['assignments'][0]['collector_id'] if cleanup['assignments'] else cleanup['collectors'][0]['id']
    replan=offline_client.post('/api/cleanup/replan',json={'mission_id':cleanup['id'],'event':'battery_drop','collector_id':target})
    assert replan.status_code==200
    replan=replan.json()
    assert next(c['battery'] for c in replan['collectors'] if c['id']==target)==14
    assert all(a['collector_id']!=target for a in replan['assignments'])
    assert all(a['estimated_collected_kg'] is None for a in replan['assignments'])
    vessel=real_vessel()
    investigation=offline_client.post('/api/investigations/'+vessel['id'])
    assert investigation.status_code==200
    investigation=investigation.json()
    assert not any(e['type']=='gap' for e in investigation['evidence'])
    for mission in (route,cleanup,replan,investigation):
        saved=offline_client.get('/api/missions/'+mission['id'])
        report=offline_client.get('/api/reports/'+mission['id'])
        assert saved.status_code==200 and saved.json()['id']==mission['id']
        assert report.status_code==200 and 'Print / Save PDF' in report.text
    assert offline_client.get('/api/missions').json()['total']==4
