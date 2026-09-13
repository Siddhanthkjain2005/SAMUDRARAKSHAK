import asyncio
import json
import logging
from datetime import datetime, timezone
import websockets
from backend.config import AISSTREAM_API_KEY, DATA
from backend.services.storage import record_ais,now
from backend.models.behaviour_model import parse_time

logger=logging.getLogger(__name__)

def normalize_position(message):
    report=message.get('Message',{}).get('PositionReport')
    metadata=message.get('MetaData',{})
    if not report:
        return None
    lat,lon=report.get('Latitude'),report.get('Longitude')
    if lat is None or lon is None or not (-90<=lat<=90 and -180<=lon<=180):
        return None
    mmsi=str(metadata.get('MMSI',report.get('UserID','')))
    if not mmsi:
        return None
    sog,cog,heading=report.get('Sog'),report.get('Cog'),report.get('TrueHeading')
    return {'id':mmsi,'mmsi':mmsi,'name':str(metadata.get('ShipName','')).strip() or 'MMSI '+mmsi,
        'latitude':lat,'longitude':lon,'speed':sog if sog is not None and sog<102.3 else None,
        'course':cog if cog is not None and cog<360 else None,
        'heading':heading if isinstance(heading,(int,float)) and 0<=heading<360 else None,
        'rate_of_turn':report.get('RateOfTurn'),'navigation_status':report.get('NavigationalStatus'),
        'position_accuracy':report.get('PositionAccuracy'),'timestamp':metadata.get('time_utc') or now(),
        'received_at':now(),'source':'AISStream PositionReport','provenance':'LIVE','events':[],'track':[]}

class AISStreamProvider:
    def __init__(self,key=AISSTREAM_API_KEY):
        self.key=key
        self.state={'status':'CONNECTING' if key else 'MISSING KEY','detail':'Waiting for received AIS observations.' if key else 'AISSTREAM_API_KEY is not configured.','last_refresh':None}
    def snapshot(self):
        state=dict(self.state)
        timestamp=parse_time(state.get('last_refresh'))
        age=max(0,(parse_time(now())-timestamp).total_seconds()) if timestamp else None
        state['last_observation_age_seconds']=round(age,1) if age is not None else None
        if state['status']=='LIVE' and (age is None or age>90):
            state.update(status='CONNECTED · NO RECENT DATA',detail='No new AIS observation in the last 90 seconds. Existing positions retain their actual source timestamps; missing reception is not proof of a vessel AIS gap.')
        return state
    async def run(self,on_observation):
        if not self.key:
            return
        retry=5
        while True:
            try:
                self.state.update(status='CONNECTING',detail='Connecting to AISStream regional feed.')
                async with websockets.connect('wss://stream.aisstream.io/v0/stream',open_timeout=15,ping_interval=20,ping_timeout=20) as socket:
                    await socket.send(json.dumps({'APIKey':self.key,'BoundingBoxes':[[[5,60],[26,90]]],'FilterMessageTypes':['PositionReport']}))
                    self.state.update(status='CONNECTED · WAITING',detail='Socket connected; no received positions yet.')
                    while True:
                        try:
                            raw=await asyncio.wait_for(socket.recv(),timeout=60)
                        except asyncio.TimeoutError:
                            self.state.update(status='CONNECTED · NO RECENT DATA',detail='Socket is connected but no AIS message arrived within 60 seconds. Local real recordings remain available.')
                            continue
                        message=json.loads(raw)
                        if message.get('error') or message.get('Error'):
                            self.state.update(status='AUTHENTICATION FAILED',detail='AISStream rejected the subscription. Verify the key in .env.')
                            return
                        observation=normalize_position(message)
                        if observation:
                            await asyncio.to_thread(record_ais,observation)
                            filename=DATA/'raw'/f"live_ais_recording_{datetime.now(timezone.utc):%Y%m%d}.jsonl"
                            with filename.open('a') as stream:
                                stream.write(json.dumps(observation)+'\n')
                            self.state.update(status='LIVE',detail='Recording real PositionReport observations to SQLite and JSONL.',last_refresh=now())
                            await on_observation(observation)
                            retry=5
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.state.update(status='OFFLINE CACHE',detail=f'Live feed unavailable ({type(exc).__name__}). Recorded observations remain accessible.')
                logger.info('AISStream unavailable: %s',type(exc).__name__)
            await asyncio.sleep(retry)
            retry=min(120,retry*2)
