import asyncio
from backend.services.storage import ais_observations
from backend.models.behaviour_model import parse_time

async def replay_recording(manager,speed=60,limit=200):
    observations=await asyncio.to_thread(ais_observations,limit)
    previous=None
    for observation in observations:
        timestamp=parse_time(observation.get('timestamp'))
        if previous and timestamp:
            await asyncio.sleep(min(2,max(.05,(timestamp-previous).total_seconds()/speed)))
        replay={**observation,'provenance':'REAL DATA · DEMO REPLAY','replay':True}
        await manager.broadcast('ais',replay)
        previous=timestamp
    await manager.broadcast('replay_complete',{'observations':len(observations),'source':'Recorded original AIS observations; no generated positions.'})
