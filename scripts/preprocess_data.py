#!/usr/bin/env python3
"""Normalize downloaded observations without inventing missing fields or tracks."""
from __future__ import annotations
import csv
import json
import math
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from acquire_data import DATA, ROOT, REGION, write_json, register, build_catalog, record


def load(path, fallback=None):
    try:
        return json.loads(Path(path).read_text())
    except (ValueError, OSError):
        return fallback


def clean(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(k):clean(v) for k,v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if hasattr(value, 'item'):
        return clean(value.item())
    return value


def output(name, data, key=None):
    write_json(DATA/'processed'/name, clean(data))
    count = len(data.get('features',[])) if isinstance(data, dict) and data.get('type')=='FeatureCollection' else len(data)
    if key:
        register(key, records=count, status='ready' if count else 'empty', processed_file='data/processed/'+name)
    return count


def preprocess_geography():
    import geopandas as gpd
    from shapely.geometry import box, mapping, shape
    from shapely import make_valid
    from shapely.strtree import STRtree
    extent = box(*REGION)
    world_file=DATA/'processed'/'land_world.geojson'
    world_source=DATA/'raw'/'ne_10m_land.zip'
    if world_source.exists() and (not world_file.exists() or world_file.stat().st_mtime<world_source.stat().st_mtime):
        world=gpd.read_file(world_source)
        features=[]
        for i,geometry in enumerate(world.geometry):
            simplified=geometry.simplify(.18,preserve_topology=True)
            if not simplified.is_valid:simplified=make_valid(simplified)
            features.append({'type':'Feature','properties':{'id':i,'source':'Natural Earth','provenance':'REAL DATA',
                                                              'simplification_degrees':.18},'geometry':mapping(simplified)})
        output('land_world.geojson',{'type':'FeatureCollection','features':features})
    for key in ['land','coastline']:
        path = DATA/'raw'/f'ne_10m_{key}.zip'
        if not path.exists():
            continue
        cached=DATA/'processed'/f'{key}.geojson'
        full_cached=DATA/'processed'/f'{key}_full.geojson'
        if cached.exists() and full_cached.exists() and min(cached.stat().st_mtime,full_cached.stat().st_mtime)>=path.stat().st_mtime:
            register(key,records=len(load(cached,{})['features']),status='ready')
            continue
        gdf = gpd.read_file(path)
        features, full = [], []
        for i, geometry in enumerate(gdf.geometry):
            if geometry.intersects(extent):
                geometry = make_valid(geometry).intersection(extent)
                if geometry.is_empty:
                    continue
                full.append({'type':'Feature','properties':{'id':i,'source':'Natural Earth','provenance':'REAL DATA'},'geometry':mapping(geometry)})
                features.append({**full[-1], 'geometry':mapping(geometry.simplify(0.008, preserve_topology=True))})
        output(key+'_full.geojson', {'type':'FeatureCollection','features':full})
        output(key+'.geojson', {'type':'FeatureCollection','features':features}, key)
    country_file = DATA/'raw'/'ne_10m_admin_0_countries.zip'
    countries = gpd.read_file(country_file) if country_file.exists() else None
    countries_tree = STRtree(countries.geometry.values) if countries is not None else None
    port_file = DATA/'raw'/'ne_10m_ports.zip'
    if port_file.exists():
        ports = []
        aliases = {'Mangalore':'Mangaluru', 'Cochin':'Kochi', 'Bombay':'Mumbai', 'Madras':'Chennai', 'Calcutta':'Kolkata'}
        for _, r in gpd.read_file(port_file).iterrows():
            name = aliases.get(r['name'],r['name'])
            country, iso = None,None
            if countries_tree is not None:
                c = countries.iloc[int(countries_tree.nearest(r.geometry))]
                country, iso = c.get('ADMIN'), c.get('ISO_A3')
            ports.append({'id':re.sub(r'[^a-z0-9]+','-',name.lower()).strip('-')+'-'+str(r['ne_id']),
                          'name':name,'original_name':r['name'],'latitude':r.geometry.y,'longitude':r.geometry.x,
                          'country':country,'country_code':iso,'country_method':'nearest Natural Earth country polygon',
                          'unlocode':None,'category':r.get('featurecla','Port'),'source':'Natural Earth / High Seas',
                          'source_url':'https://www.naturalearthdata.com/downloads/10m-cultural-vectors/ports/',
                          'provenance':'REAL DATA', 'website':clean(r.get('website'))})
        # Stable convenient IDs for the canonical route scenarios while retaining source IDs separately.
        for p in ports:
            if p['name'] in aliases.values() and p.get('country_code')=='IND':
                p['source_id']=p['id'];p['id']=p['name'].lower()
        output('ports.json',ports,'ports')
    boundary_keys=['eez','territorial_sea','contiguous_zone','high_seas']
    boundary_raw=[DATA/'raw'/f'marineregions_{key}.geojson' for key in boundary_keys]
    boundary_cache=DATA/'processed'/'boundaries.geojson'
    fresh_cache=boundary_cache.exists() and all(not p.exists() or p.stat().st_mtime<=boundary_cache.stat().st_mtime for p in boundary_raw)
    boundaries=load(boundary_cache,{}).get('features',[]) if fresh_cache else []
    for key in ([] if fresh_cache else boundary_keys):
        data = load(DATA/'raw'/f'marineregions_{key}.geojson',{})
        count = 0
        for feature in data.get('features',[]):
            geometry=make_valid(shape(feature['geometry'])).intersection(extent)
            if geometry.is_empty:
                continue
            props = feature.get('properties',{})
            props.update({'id':feature.get('id',props.get('mrgid')),'name':props.get('geoname',key.replace('_',' ').title()),
                          'kind':key,'source':'Marine Regions / VLIZ','provenance':'REAL DATA',
                          'legal_caveat':'Scientific spatial context; verify jurisdiction against current official authorities.'})
            boundaries.append({'type':'Feature','properties':props,'geometry':mapping(geometry.simplify(.01,preserve_topology=True))})
            count+=1
        if data.get('features'):
            register(key,records=count,status='ready')
    output('boundaries.geojson',{'type':'FeatureCollection','features':boundaries})
    for key in boundary_keys:
        count=sum(f.get('properties',{}).get('kind')==key for f in boundaries)
        if count:register(key,records=count,status='ready')
    mpa=load(DATA/'raw'/'india_mpa.geojson',{'type':'FeatureCollection','features':[]})
    output('mpa.geojson',mpa)
    if mpa.get('features'):
        register('mpa',status='ready',records=len(mpa['features']))


def preprocess_debris():
    observations=[]
    seen=set()
    for path in sorted((DATA/'raw').glob('noaa_microplastics_*.geojson')):
        for feature in load(path,{}).get('features',[]):
            p=feature.get('properties',{})
            xy=feature.get('geometry',{}).get('coordinates',[])
            if len(xy)<2:
                continue
            identifier='noaa-'+str(p.get('OBJECTID'))
            if identifier in seen:
                continue
            seen.add(identifier)
            stamp=p.get('Date_m_d_yyyy')
            if isinstance(stamp,(int,float)):
                stamp=datetime.fromtimestamp(stamp/1000,timezone.utc).isoformat()
            measurement=p.get('Microplastics_measurement')
            units=p.get('Unit')
            observations.append({'id':identifier,'observation_id':identifier,'latitude':xy[1],'longitude':xy[0],
                'timestamp':stamp,'date':stamp,'debris_category':'Microplastics','category':'Microplastics',
                'quantity':None,'concentration':measurement,'concentration_unit':units,
                'source':'NOAA NCEI Marine Microplastics','dataset':'NCEI-Marine-Microplastics',
                'provenance':'HISTORICAL · REAL DATA','confidence':None,'region':p.get('Location_Regions'),
                'country':p.get('Country'),'state':p.get('State'),'location':p.get('Beach_Location') or p.get('Location_SubRegions'),
                'medium':p.get('Medium'),'sampling_method':p.get('Sampling_Method'),
                'reference':p.get('Short_Reference'),'doi':p.get('DOI'),'accession':p.get('NCEI_Accession_No'),
                'source_url':p.get('NCEI_Accession_No__Link') or 'https://www.ncei.noaa.gov/products/microplastics',
                'collection_caveat':'Historical concentration sample; does not establish current recoverable debris mass.'})
    if observations:
        output('debris.json',observations,'debris')
        dates=sorted(o['timestamp'] for o in observations if o.get('timestamp'))
        register('debris',coverage_dates=[dates[0],dates[-1]] if dates else None)
    else:
        output('debris.json',[])
    tracker=DATA/'raw'/'debris_tracker.csv'
    if tracker.exists():
        with tracker.open(newline='',encoding='utf-8-sig') as f:
            rows=[]
            for i,r in enumerate(csv.DictReader(f)):
                try:
                    rows.append({'observation_id':'tracker-'+str(r.get('id',i)), 'latitude':float(r['latitude']),
                                 'longitude':float(r['longitude']), 'timestamp':r.get('timestamp') or r.get('date'),
                                 'debris_category':r.get('debris_category') or r.get('item'),'quantity':float(r['quantity']) if r.get('quantity') else None,
                                 'source':'Marine Debris Tracker','dataset':'User-exported licensed dataset','provenance':'HISTORICAL · REAL DATA'})
                except (ValueError,KeyError):
                    continue
        output('debris_tracker.json',rows,'debris_tracker')


def preprocess_nga_ports():
    from shapely.geometry import Point
    from shapely.strtree import STRtree
    ports=load(DATA/'processed'/'ports.json',[])
    ports=[p for p in ports if p.get('source')!='NGA World Port Index 2019 via NOAA']
    tree=STRtree([Point(p['longitude'],p['latitude']) for p in ports]) if ports else None
    added=0
    for path in sorted((DATA/'raw').glob('nga_ports_*.geojson')):
        for feature in load(path,{}).get('features',[]):
            row=feature.get('properties',{});xy=feature['geometry']['coordinates']
            if tree is not None:
                nearest=ports[int(tree.nearest(Point(*xy))) ]
                # Deduplicate nearby port centers; retain NGA attribute enrichment on the same point.
                if math.hypot(nearest['longitude']-xy[0],nearest['latitude']-xy[1])<0.055:
                    nearest['nga_world_port_index_id']=row.get('OBJECTID')
                    nearest['harbor_size']=row.get('HARBORSIZE')
                    nearest['harbor_type']=row.get('HARBORTYPE')
                    nearest['secondary_source']='NGA World Port Index 2019 via NOAA'
                    continue
            name=row.get('PORT_NAME','Unknown port').title()
            ports.append({'id':'karwar' if name=='Karwar' and row.get('COUNTRY')=='IN' else 'nga-'+str(row.get('OBJECTID')),
                          'name':name,'original_name':row.get('PORT_NAME'),'latitude':xy[1],'longitude':xy[0],
                          'country':'India' if row.get('COUNTRY')=='IN' else row.get('COUNTRY'),
                          'country_code':'IND' if row.get('COUNTRY')=='IN' else row.get('COUNTRY'),
                          'category':'Port','unlocode':None,'harbor_size':row.get('HARBORSIZE'),'harbor_type':row.get('HARBORTYPE'),
                          'source':'NGA World Port Index 2019 via NOAA','provenance':'HISTORICAL · REAL DATA',
                          'source_url':'https://gis.ngdc.noaa.gov/arcgis/rest/services/nccos/PIRO_DigitalAtlas/MapServer/30'})
            added+=1
    output('ports.json',ports)
    register('nga_ports',status='ready',added_to_merged_ports=added,processed_file='data/processed/ports.json')
    register('ports',merged_records=len(ports))


def preprocess_marine():
    records=[]
    now=datetime.now(timezone.utc).isoformat()
    for path in sorted((DATA/'raw').glob('marine_grid_*.json')):
        rows=load(path,[])
        if isinstance(rows,dict):
            rows=[rows]
        for p in rows:
            current=p.get('current',{})
            hourly=p.get('hourly',{})
            units=p.get('current_units',{})
            raw_speed=current.get('ocean_current_velocity')
            speed_unit=units.get('ocean_current_velocity','km/h')
            conversion={'km/h':1/3.6,'m/s':1,'kn':0.514444,'knots':0.514444,'mph':0.44704}.get(speed_unit)
            speed=raw_speed*conversion if raw_speed is not None and conversion is not None else None
            if current.get('wave_height') is None and speed is None:
                continue
            records.append({'id':f'marine-{p["latitude"]}-{p["longitude"]}','latitude':p['latitude'],'longitude':p['longitude'],
                'timestamp':current.get('time')+'Z' if current.get('time') else None,'current_speed_ms':speed,
                'current_direction':current.get('ocean_current_direction'),'wave_height':current.get('wave_height'),
                'wave_direction':current.get('wave_direction'),'wave_period':current.get('wave_period'),
                'sea_surface_temperature':current.get('sea_surface_temperature'),'sea_level_height_msl':current.get('sea_level_height_msl'),
                'source':'Open-Meteo Marine / Météo-France / Copernicus Marine','source_url':'https://open-meteo.com/en/docs/marine-weather-api',
                'provenance':'MODEL FORECAST','downloaded_at':datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).isoformat(),
                'original_current_speed':raw_speed,'original_current_speed_unit':speed_unit,
                'hourly':hourly,'hourly_units':p.get('hourly_units',{})})
    output('marine.json',records,'marine' if records else None)
    if records:
        times=[t for r in records for t in r.get('hourly',{}).get('time',[])]
        register('marine',coverage_dates=[min(times),max(times)] if times else None,forecast_hours=sum(len(r.get('hourly',{}).get('time',[])) for r in records))
    weather=load(DATA/'raw'/'coastal_weather.json',[])
    output('weather.json',weather,'weather' if weather else None)


def preprocess_vessels():
    identities=[]
    vessels={}
    for path in sorted((DATA/'raw').glob('gfw_identity_*.json')):
        for row in load(path,{}).get('entries',[]):
            identities.append(row)
    for path in sorted((DATA/'raw').glob('gfw_events_*.json')):
        for event in load(path,{}).get('entries',[]):
            identity=event.get('vessel',{})
            identifier=identity.get('id')
            position=event.get('position',{})
            lat,lon=position.get('lat'),position.get('lon')
            if not identifier or lat is None or lon is None:
                continue
            lat,lon=float(lat),float(lon)
            if not (-90<=lat<=90 and -180<=lon<=180):
                continue
            vessel=vessels.setdefault(identifier,{'id':identifier,'name':identity.get('name') or identity.get('ssvid') or identifier,
                    'mmsi':identity.get('ssvid'),'flag':identity.get('flag'),'type':identity.get('type','unknown'),
                    'latitude':lat,'longitude':lon,'timestamp':event.get('start'),'speed':None,'course':None,
                    'source':'Global Fishing Watch','provenance':'HISTORICAL · REAL DATA','events':[], 'track':[],
                    'position_kind':'historical event mean position','track_caveat':'No raw AIS track supplied by the event endpoint.'})
            vessel['events'].append({**event,'latitude':lat,'longitude':lon,'source':'Global Fishing Watch','provenance':'HISTORICAL · REAL DATA'})
            if event.get('start','') > (vessel.get('timestamp') or ''):
                vessel.update(latitude=lat,longitude=lon,timestamp=event.get('start'))
    for v in vessels.values():
        v['events'].sort(key=lambda e:e.get('start',''))
    noaa_vessels,noaa_identities=preprocess_noaa_ais()
    output('gfw_identity.json',identities,'gfw_identity' if identities else None)
    output('vessel_identity.json',identities+noaa_identities)
    ordered=sorted(vessels.values(),key=lambda v:(-sum(e.get('type') in ['gap','loitering','encounter'] for e in v['events']),-len(v['events']),v['id']))
    ordered+=noaa_vessels
    output('vessels.json',ordered)
    write_json(DATA/'demo'/'historical_cases.json',[{'id':'case-'+v['id'],'vessel_id':v['id'],'source':v['source'],
               'provenance':'HISTORICAL · REAL DATA','event_count':len(v['events']),
               'track_points':len(v['track']),'geographic_context':v.get('geographic_context','India / Arabian Sea'),
               'caveat':'Real movement review example, not an allegation of unlawful activity. A sample boundary is not an AIS gap.'} for v in ordered[:3]])
    for kind in ['sar','fishing_effort']:
        raw=load(DATA/'raw'/f'gfw_report_{kind}.json',{})
        rows=raw.get('entries',[]) if isinstance(raw,dict) else raw
        if not isinstance(rows,list):
            rows=[]
        output(kind+'.json',rows,'gfw_'+kind if rows else None)


def preprocess_noaa_ais():
    path=DATA/'raw'/'noaa_ais_2024_01_01_prefix.csv'
    if not path.exists():return [],[]
    grouped=defaultdict(list)
    identities={}
    for row in csv.DictReader(path.open(newline='')):
        try:
            mmsi=row['mmsi'];lat=float(row['latitude']);lon=float(row['longitude'])
            if len(mmsi)!=9 or not (-90<=lat<=90 and -180<=lon<=180) or (lat==0 and lon==0):continue
            stamp=row['base_date_time'].replace(' ','T')+'Z'
            speed=float(row['sog']) if row.get('sog') else None
            course=float(row['cog']) if row.get('cog') else None
            heading=float(row['heading']) if row.get('heading') else None
            if speed is not None and (speed<0 or speed>=102.3):speed=None
            if course is not None and not 0<=course<360:course=None
            if heading is not None and not 0<=heading<360:heading=None
            grouped[mmsi].append({'latitude':lat,'longitude':lon,'timestamp':stamp,'speed':speed,'course':course,'heading':heading,
                                  'source':'NOAA MarineCadastre AIS','provenance':'HISTORICAL · REAL DATA'})
            vessel_type=int(row['vessel_type']) if row.get('vessel_type') else 0
            kind='fishing' if vessel_type==30 else 'cargo' if 70<=vessel_type<=79 else 'tanker' if 80<=vessel_type<=89 else 'passenger' if 60<=vessel_type<=69 else 'tug' if vessel_type in [31,32,52] else 'other'
            identities[mmsi]={'id':'noaa-'+mmsi,'mmsi':mmsi,'name':row.get('vessel_name') or mmsi,'imo':row.get('imo') or None,
                              'callsign':row.get('call_sign') or None,'type':kind,'ais_vessel_type':vessel_type,
                              'source':'NOAA MarineCadastre AIS','provenance':'HISTORICAL · REAL DATA',
                              'geographic_context':'United States coastal waters — global demonstration context'}
        except (ValueError,KeyError):continue
    eligible=[]
    for mmsi,track in grouped.items():
        track=sorted({p['timestamp']:p for p in track}.values(),key=lambda p:p['timestamp'])
        if len(track)<8 or not any((p['speed'] or 0)>2 for p in track):continue
        identity=identities[mmsi]
        if identity['name']==mmsi:continue
        latest=track[-1]
        courses=[p['course'] for p in track if p.get('course') is not None]
        course_changes=[abs((b-a+180)%360-180) for a,b in zip(courses,courses[1:])]
        vessel={**identity,**latest,'id':identity['id'],'events':[],'track':track,'position_kind':'actual historical AIS broadcast',
                'observation_window':{'start':track[0]['timestamp'],'end':latest['timestamp']},
                'track_caveat':'Non-random sample of early-day US AIS; absence after sample end does not establish tracking silence.',
                'source_url':'https://noaaocm.blob.core.windows.net/ais/csv2/csv2024/ais-2024-01-01.csv.zst',
                'computed_max_course_change':round(max(course_changes,default=0),2), 'recorded_ais':True}
        eligible.append(vessel)
    eligible.sort(key=lambda v:(-len(v['track']),-v['computed_max_course_change'],v['id']))
    chosen=[]
    # Three diverse, actual maritime movements. Type classification uses AIS source type codes.
    for kind in ['fishing','cargo','tug']:
        candidates=[v for v in eligible if v['type']==kind]
        if candidates:chosen.append(candidates[0])
    chosen_ids={v['id'] for v in chosen}
    chosen += [v for v in eligible if v['id'] not in chosen_ids][:max(0,60-len(chosen))]
    register('historical_ais',status='ready',vessel_identities=len(identities),replay_vessels=len(chosen),
             replay_observations=sum(len(v['track']) for v in chosen),
             coverage_dates=[min(p['timestamp'] for t in grouped.values() for p in t),max(p['timestamp'] for t in grouped.values() for p in t)])
    output('historical_ais_vessels.json',chosen)
    return chosen,list(identities.values())


def preprocess_bathymetry():
    path=DATA/'raw'/'etopo_indian_ocean.csv'
    rows=[]
    if path.exists():
        for r in csv.DictReader(path.read_text().splitlines()):
            try:
                rows.append({'latitude':float(r['latitude']),'longitude':float(r['longitude']),
                             'elevation_m':float(r['altitude']), 'source':'NOAA ETOPO1','provenance':'REAL DATA'})
            except (KeyError,ValueError):
                continue
    output('bathymetry.json',rows,'bathymetry' if rows else None)


def preprocess():
    preprocess_geography()
    preprocess_nga_ports()
    preprocess_debris()
    preprocess_marine()
    preprocess_vessels()
    preprocess_bathymetry()
    ports=load(DATA/'processed'/'ports.json',[])
    by_name={p['name']:p for p in ports if p.get('country_code')=='IND'}
    scenarios=[]
    for origin,dest in [('Mangaluru','Kochi'),('Mumbai','Mangaluru')]:
        if origin in by_name and dest in by_name:
            scenarios.append({'id':origin.lower()+'-'+dest.lower(),'origin':by_name[origin]['id'],'destination':by_name[dest]['id'],
                              'provenance':'COMPUTED SCENARIO · REAL PORT LOCATIONS','precomputed_route':None})
    write_json(DATA/'demo'/'route_scenarios.json',scenarios)
    preprocess_debris_regions()
    # Record raw files copied before the manifest existed, without altering any original source bytes.
    for filename,url in [('ne_10m_ports.zip','https://naturalearth.s3.amazonaws.com/10m_cultural/ne_10m_ports.zip')]:
        path=DATA/'raw'/filename
        if path.exists():
            existing=load(DATA/'download_manifest.json',[])
            if not any(r.get('file')=='data/raw/'+filename for r in existing):
                record(path,url,'processed')
    build_catalog()
    print('Real observations, forecast units, and geometries normalized.',flush=True)


def preprocess_debris_regions():
    """Deterministic scene anchors; cluster count is computed, never a made-up metric."""
    import numpy as np
    from sklearn.cluster import DBSCAN
    records=load(DATA/'processed'/'debris.json',[])
    if not records:return
    positions=np.radians([[r['latitude'],r['longitude']] for r in records])
    labels=DBSCAN(eps=25/6371.0088,min_samples=3,metric='haversine').fit_predict(positions)
    clusters=[]
    for label in sorted(set(labels)):
        if label<0:continue
        rows=[records[i] for i,v in enumerate(labels) if v==label]
        from collections import Counter
        dominant=Counter((r.get('region') or 'Indian Ocean') for r in rows).most_common(1)[0][0]
        centroid=np.degrees(positions[labels==label]).mean(axis=0)
        clusters.append({'id':f'noaa-region-{int(label)}','name':dominant,'latitude':float(centroid[0]),
                         'longitude':float(centroid[1]),'observation_count':len(rows),
                         'observation_ids':[r['observation_id'] for r in rows],
                         'source':'Computed from NOAA NCEI Marine Microplastics observations',
                         'provenance':'COMPUTED · HISTORICAL REAL DATA',
                         'method':{'algorithm':'DBSCAN','distance':'haversine','eps_km':25,'min_samples':3},
                         'caveat':'Historical sampling cluster; not current cleanup mass. Counts are sample records, not plastic items.'})
    clusters.sort(key=lambda r:(-r['observation_count'],r['id']))
    write_json(DATA/'demo'/'debris_regions.json',clusters)


if __name__=='__main__':
    preprocess()
