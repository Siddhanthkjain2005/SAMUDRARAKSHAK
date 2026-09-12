import asyncio
from fastapi.testclient import TestClient
from backend.main import app
from backend.providers.global_fishing_watch import GlobalFishingWatchProvider
from backend.providers.llm import GroqProvider
from backend.providers.aisstream import AISStreamProvider
from backend.providers.marine_weather import OpenMeteoProvider
from backend.agents.dark_vessel import investigate

client=TestClient(app)

def test_empty_keys_are_honest_and_do_not_raise():
    assert asyncio.run(GlobalFishingWatchProvider('').search('example'))==[]
    assert asyncio.run(GroqProvider('').explain('hello',{})) is None
    assert AISStreamProvider('').state['status']=='MISSING KEY'

def test_external_outage_uses_marine_cache_without_fabricating(monkeypatch):
    import httpx
    async def fail(*args,**kwargs):raise httpx.ConnectError('offline')
    monkeypatch.setattr(httpx.AsyncClient,'get',fail)
    provider=OpenMeteoProvider()
    result=asyncio.run(provider.point(-70,-140))
    assert result=={}
    assert provider.state['status']=='OFFLINE CACHE'
    fishing=GlobalFishingWatchProvider('not-a-real-key')
    assert asyncio.run(fishing.search('vessel'))==[]
    assert fishing.state['status']=='OFFLINE CACHE'

def test_bootstrap_uses_actual_cache_counts():
    response=client.get('/api/bootstrap')
    assert response.status_code==200
    body=response.json()
    assert body['stats']['ports']==len(body['ports'])
    assert body['stats']['debris_observations']>=len(body['debris'])
    assert len(body['agents'])==14
    assert 'GFW_API_ACCESS_TOKEN' not in response.text
    assert 'LLM_API_KEY' not in response.text

def test_api_validates_bad_route_inputs_and_unknown_resources():
    assert client.post('/api/routes/optimize',json={'origin_id':'x','destination_id':'y','speed_knots':-1}).status_code==422
    assert client.get('/api/missions/missing').status_code==404
    assert client.get('/api/data/secrets').status_code==404

def test_historical_age_not_converted_to_ais_silence():
    result=investigate({'id':'test','name':'Archived test identity','timestamp':'2010-01-01','provenance':'HISTORICAL','events':[]},[],[])
    assert result['risk_score']==0
    assert result['confidence_score']==0
    assert result['evidence']==[]
    assert result['graph']['nodes'][0]['id']=='vessel'
