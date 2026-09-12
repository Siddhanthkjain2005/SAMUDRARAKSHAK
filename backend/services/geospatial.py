"""All public coordinates use latitude/longitude; GeoJSON uses longitude/latitude."""
import math
from functools import lru_cache
from pathlib import Path
import json
from shapely.geometry import shape, Point, LineString
from shapely.ops import unary_union
from shapely.prepared import prep
from backend.config import PROCESSED

EARTH_KM=6371.0088

def haversine(a,b):
    lat1,lon1,lat2,lon2=map(math.radians,(a[0],a[1],b[0],b[1]))
    dlat,dlon=lat2-lat1,lon2-lon1
    h=math.sin(dlat/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return EARTH_KM*2*math.asin(min(1,math.sqrt(h)))

def angle_difference(a,b):
    return abs((b-a+180)%360-180)

def bearing(a,b):
    p1,p2=math.radians(a[0]),math.radians(b[0]); delta=math.radians(b[1]-a[1])
    return math.degrees(math.atan2(math.sin(delta)*math.cos(p2),math.cos(p1)*math.sin(p2)-math.sin(p1)*math.cos(p2)*math.cos(delta)))%360

def project(latitude,longitude,distance_km,heading):
    lat,lon,b=map(math.radians,(latitude,longitude,heading)); d=distance_km/EARTH_KM
    p=math.asin(math.sin(lat)*math.cos(d)+math.cos(lat)*math.sin(d)*math.cos(b))
    l=lon+math.atan2(math.sin(b)*math.sin(d)*math.cos(lat),math.cos(d)-math.sin(lat)*math.sin(p))
    return math.degrees(p),(math.degrees(l)+540)%360-180

class LandMask:
    def __init__(self,geometry,buffer_km=0):
        self.geometry=geometry.buffer(buffer_km/111) if buffer_km else geometry
        self.prepared=prep(self.geometry)
    def is_land(self,lat,lon):
        return self.prepared.intersects(Point(lon,lat))
    def intersects(self,a,b):
        return self.prepared.intersects(LineString([(a[1],a[0]),(b[1],b[0])]))

@lru_cache(maxsize=8)
def _load_land(path,modified,buffer_km):
    data=json.loads(Path(path).read_text())
    features=data.get('features',[]) if data.get('type')=='FeatureCollection' else [data]
    geometries=[shape(f.get('geometry',f)) for f in features if f.get('geometry',f)]
    return LandMask(unary_union(geometries),buffer_km)

def get_land_mask(buffer_km=1):
    for filename in ('land_full.geojson','land.geojson','coastline_land.geojson','natural_earth_land.geojson'):
        path=PROCESSED/filename
        if path.exists():
            return _load_land(str(path),path.stat().st_mtime_ns,buffer_km)
    return None

def jurisdiction(lat,lon):
    results=[]
    for filename in ('boundaries.geojson','eez.geojson','mpa.geojson'):
        path=PROCESSED/filename
        if not path.exists():
            continue
        try:
            for f in json.loads(path.read_text()).get('features',[]):
                if f.get('geometry') and shape(f['geometry']).covers(Point(lon,lat)):
                    results.append({'name':f.get('properties',{}).get('name',f.get('properties',{}).get('GEONAME','Marine boundary')),'source':filename,'properties':f.get('properties',{})})
        except (ValueError,TypeError):
            continue
    return {'matches':results,'coverage':'AVAILABLE' if results else 'NO VERIFIED BOUNDARY MATCH','legal_determination':False}
