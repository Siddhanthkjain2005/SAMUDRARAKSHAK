import httpx
from backend.services.storage import now
from backend.services.data_catalog import records

def normalized_current_speed(value,unit):
    if value is None:return None
    converters={'km/h':1/3.6,'m/s':1,'kn':.514444,'knots':.514444,'mph':.44704}
    factor=converters.get(str(unit))
    return float(value)*factor if factor is not None else None

class OpenMeteoProvider:
    def __init__(self):
        self.state={'status':'OFFLINE CACHE','detail':'Marine forecasts loaded from local acquisition cache.','last_refresh':None}
    async def point(self,latitude,longitude):
        variables='wave_height,wave_direction,wave_period,ocean_current_velocity,ocean_current_direction,sea_surface_temperature'
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response=await client.get('https://marine-api.open-meteo.com/v1/marine',params={'latitude':latitude,'longitude':longitude,'current':variables,'hourly':variables,'forecast_days':2,'cell_selection':'sea','timezone':'UTC'})
            response.raise_for_status(); payload=response.json(); current=payload.get('current',{}); units=payload.get('current_units',{})
            self.state.update(status='MODEL FORECAST',detail='Marine endpoint verified; forecasts are numerical model output.',last_refresh=now())
            return {'latitude':payload.get('latitude',latitude),'longitude':payload.get('longitude',longitude),
                'current_speed_ms':normalized_current_speed(current.get('ocean_current_velocity'),units.get('ocean_current_velocity')),
                'current_direction':current.get('ocean_current_direction'),'wave_height':current.get('wave_height'),
                'wave_direction':current.get('wave_direction'),'wave_period':current.get('wave_period'),
                'sea_surface_temperature':current.get('sea_surface_temperature'),'timestamp':current.get('time'),
                'source':'Open-Meteo Marine API','provenance':'MODEL FORECAST','raw_units':units}
        except (httpx.HTTPError,ValueError):
            self.state.update(status='OFFLINE CACHE',detail='Marine API unavailable; only locally cached forecasts are used.')
            from backend.services.route_optimizer import nearest_environment
            return nearest_environment(latitude,longitude,records('marine'))
