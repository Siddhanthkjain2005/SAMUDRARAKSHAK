"""One controllable replay of original observations; never a synthetic AIS writer."""
import asyncio
import math
from uuid import uuid4
from backend.services.storage import ais_observations,now
from backend.services.data_catalog import vessels as historical_vessels
from backend.models.behaviour_model import parse_time

class ReplayUnavailable(ValueError):
    pass

def load_recording(vessel_id=None,limit=200):
    """Prefer curated historical tracks; select SQLite only for an actual MMSI."""
    history=historical_vessels()
    vessel=next((v for v in history if (v['id']==vessel_id or str(v.get('mmsi'))==vessel_id) and v.get('track')),None)
    if vessel_id is None:
        vessel=next((v for v in history if v.get('track')),None)
    if vessel:
        points=vessel['track']
    else:
        points=ais_observations(limit,vessel_id)
        if points:
            mmsi=str(points[0].get('mmsi',''))
            points=[p for p in points if str(p.get('mmsi',''))==mmsi]
            vessel={**points[-1],'id':str(points[-1].get('id',mmsi))}
    if not vessel or not points:
        raise ReplayUnavailable('No genuine timestamped AIS recording is available for this vessel. Replay cannot create artificial positions.')
    unique={}
    for point in points:
        timestamp=parse_time(point.get('timestamp'))
        try:
            lat,lon=float(point['latitude']),float(point['longitude'])
            if timestamp is None or not (math.isfinite(lat) and math.isfinite(lon) and -90<=lat<=90 and -180<=lon<=180):
                continue
        except (KeyError,ValueError,TypeError):
            continue
        key=(timestamp.isoformat(),lat,lon)
        unique[key]={**point,'latitude':lat,'longitude':lon}
    observations=sorted(unique.values(),key=lambda p:parse_time(p['timestamp']))[:limit]
    if not observations:
        raise ReplayUnavailable('The recording contains no valid original coordinates with source timestamps.')
    return vessel,observations

class ReplayController:
    """Pause preserves the remaining source-time gap; at most one session emits points."""
    def __init__(self,manager):
        self.manager=manager;self.task=None;self._lock=asyncio.Lock()
        self._running=asyncio.Event();self._changed=asyncio.Event()
        self.state={'session_id':None,'status':'IDLE','vessel_id':None,'vessel_name':None,'source':None,
            'provenance':'REAL DATA · DEMO REPLAY','speed':60,'observations':0,'index':0,'progress_pct':0,
            'current_timestamp':None,'started_at':None,'geographic_context':None,
            'detail':'Select a real historical track or recorded live vessel to replay.'}

    def snapshot(self):return dict(self.state)

    async def publish(self):await self.manager.broadcast('replay_status',self.snapshot())

    async def _cancel(self):
        if self.task and not self.task.done():
            self.task.cancel();await asyncio.gather(self.task,return_exceptions=True)
        self.task=None

    async def start(self,vessel_id=None,speed=60,limit=200):
        # A failed selection does not replace a valid session.
        vessel,observations=await asyncio.to_thread(load_recording,vessel_id,limit)
        async with self._lock:
            await self._cancel()
            self._running=asyncio.Event();self._running.set();self._changed=asyncio.Event()
            self.state={'session_id':'replay-'+uuid4().hex[:10],'status':'RUNNING','vessel_id':vessel['id'],
                'vessel_name':vessel.get('name'),'source':vessel.get('source',observations[0].get('source')),
                'provenance':'REAL DATA · DEMO REPLAY','speed':speed,'observations':len(observations),'index':0,
                'progress_pct':0,'current_timestamp':observations[0]['timestamp'],'started_at':now(),
                'geographic_context':vessel.get('geographic_context','Original recorded geographic coordinates'),
                'recording_start':observations[0]['timestamp'],'recording_end':observations[-1]['timestamp'],
                'detail':'Original timestamps and coordinates; playback ends at the source sample boundary, not an inferred AIS gap.'}
            await self.publish();self.task=asyncio.create_task(self._play(vessel,observations))
            return self.snapshot()

    async def pause(self):
        async with self._lock:
            if self.state['status']=='RUNNING':
                self.state['status']='PAUSED';self._running.clear();self._changed.set();await self.publish()
            return self.snapshot()

    async def resume(self):
        async with self._lock:
            if self.state['status']=='PAUSED':
                self.state['status']='RUNNING';self._running.set();self._changed.set();await self.publish()
            return self.snapshot()

    async def stop(self):
        async with self._lock:
            await self._cancel()
            if self.state['session_id']:
                self.state['status']='STOPPED';self.state['detail']='Playback stopped. Original recording remains available.';await self.publish()
            return self.snapshot()

    async def _delay(self,remaining):
        while remaining>0:
            await self._running.wait();self._changed.clear();started=asyncio.get_running_loop().time()
            try:
                await asyncio.wait_for(self._changed.wait(),remaining)
            except asyncio.TimeoutError:return
            remaining=max(0,remaining-(asyncio.get_running_loop().time()-started))

    async def _play(self,vessel,observations):
        previous=None
        try:
            for index,point in enumerate(observations,1):
                timestamp=parse_time(point['timestamp'])
                if previous:await self._delay(max(0,(timestamp-previous).total_seconds()/self.state['speed']))
                await self._running.wait()
                observation={**point,'id':vessel['id'],'mmsi':vessel.get('mmsi'),'name':vessel.get('name'),
                    'type':vessel.get('type'),'source':point.get('source',vessel.get('source')),
                    'provenance':'REAL DATA · DEMO REPLAY','original_provenance':point.get('provenance',vessel.get('provenance')),
                    'original_timestamp':point['timestamp'],'replay':True,'replay_session_id':self.state['session_id'],
                    'geographic_context':vessel.get('geographic_context'),'track_caveat':vessel.get('track_caveat')}
                self.state.update(index=index,progress_pct=round(index/len(observations)*100,1),current_timestamp=point['timestamp'])
                await self.manager.broadcast('ais',observation);await self.publish();previous=timestamp
            self.state.update(status='COMPLETED',detail='Reached the final recorded source sample. A truncated recording endpoint is not evidence of tracking silence.')
            await self.publish();await self.manager.broadcast('replay_complete',self.snapshot())
        except asyncio.CancelledError:raise
        except Exception as exc:
            self.state.update(status='STOPPED',detail=f'Playback stopped ({type(exc).__name__}); no synthetic replacement observations were created.')
            await self.publish()
