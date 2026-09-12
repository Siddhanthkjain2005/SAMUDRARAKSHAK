"""Named viewport search, explicitly distinct from legal jurisdiction boundaries."""
from backend.services.geospatial import haversine

REGIONS=[
    (('mangaluru','mangalore'),{'name':'Mangaluru coastal area','center':(12.93,74.81),'radius_km':150}),
    (('karwar',),{'name':'Karwar coastal area','center':(14.82,74.12),'radius_km':150}),
    (('udupi',),{'name':'Udupi coastal area','center':(13.34,74.74),'radius_km':150}),
    (('karnataka',),{'name':'Karnataka coastal region','center':(13.6,74.4),'radius_km':300}),
    (('arabian sea',),{'name':'Arabian Sea regional viewport','bounds':(0,50,26,78)}),
    (('bay of bengal',),{'name':'Bay of Bengal regional viewport','bounds':(5,80,25,98)}),
    (('indian waters','near india','in india','india coastline'),{'name':'India regional viewport','bounds':(5,65,25,92)}),
    (('us waters','united states','american waters'),{'name':'United States regional viewport','bounds':(18,-175,72,-60)}),
]

def filter_named_region(message,vessels):
    region=next((region for aliases,region in REGIONS if any(alias in message.lower() for alias in aliases)),None)
    if region is None:return None,vessels
    matches=[]
    for vessel in vessels:
        try:lat,lon=float(vessel['latitude']),float(vessel['longitude'])
        except (KeyError,TypeError,ValueError):continue
        if 'center' in region:
            inside=haversine((lat,lon),region['center'])<=region['radius_km']
        else:
            south,west,north,east=region['bounds'];inside=south<=lat<=north and west<=lon<=east
        if inside:matches.append(vessel)
    return {**region,'methodology':'Geographic search viewport; not a legal maritime boundary.'},matches
