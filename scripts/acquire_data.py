#!/usr/bin/env python3
"""Download bounded, useful real datasets. No secrets are printed or persisted in metadata."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import sys
import threading
import time
import zipfile
import struct
import zlib
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
for folder in ('raw', 'processed', 'cached', 'demo', 'metadata'):
    (DATA / folder).mkdir(parents=True, exist_ok=True)
load_dotenv(ROOT / '.env')
LOCK = threading.Lock()
REGION = [55, -5, 100, 30]
GFW = 'https://gateway.api.globalfishingwatch.org/v3'
NOAA = 'https://services2.arcgis.com/C8EMgrsFcRFL6LrL/ArcGIS/rest/services/Marine_Microplastics_WGS84/FeatureServer/0'
FORCE = False


def utc():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')))
    temp.replace(path)


def register(key, **fields):
    with LOCK:
        path = DATA / 'metadata' / 'sources.json'
        values = json.loads(path.read_text()) if path.exists() else {}
        values[key] = {**values.get(key, {}), 'id': key, **fields}
        write_json(path, values)


def record(path, url, status='downloaded', parameters=None):
    path = Path(path)
    entry = {'file': str(path.relative_to(ROOT)), 'download_timestamp': utc(), 'source': url,
             'file_size': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
             'processing_status': status, 'request_parameters': parameters or {}}
    with LOCK:
        manifest = DATA / 'download_manifest.json'
        rows = json.loads(manifest.read_text()) if manifest.exists() else []
        rows = [r for r in rows if r.get('file') != entry['file']]
        rows.append(entry)
        write_json(manifest, rows)


def fetch(url, filename, params=None, body=None, auth=False, timeout=50):
    path = DATA / 'raw' / filename
    if path.exists() and not FORCE:
        # Existing public files are still tracked; credentials are never in query parameters.
        if not (DATA / 'download_manifest.json').exists():
            record(path, url, 'cached', params)
        return path
    headers = {'User-Agent': 'SamudraRakshakAI-ResearchPrototype/1.0'}
    if auth:
        token = os.getenv('GFW_TOKEN') or os.getenv('GFW_API_ACCESS_TOKEN')
        if not token:
            raise RuntimeError('GFW_API_ACCESS_TOKEN not configured')
        headers['Authorization'] = 'Bearer ' + token
    response = requests.request('POST' if body is not None else 'GET', url, params=params,
                                json=body, headers=headers, timeout=(15, timeout))
    if not response.ok:
        # Avoid exception URL/header dumps that could reveal tokens from a provider redirect.
        detail = ''
        try:
            payload = response.json()
            detail = str(payload.get('error') or payload.get('reason') or '')[:140]
        except Exception:
            pass
        raise RuntimeError(f'HTTP {response.status_code} {detail}')
    if len(response.content) > 70_000_000:
        raise RuntimeError('Response exceeds 70 MB per-file research budget')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(response.content)
    record(path, url, parameters=params)
    return path


def source(key, name, provider, license, url, processed, **extra):
    register(key, name=name, provider=provider, source_type='API or public bulk download',
             source=url, license=license, attribution=provider, date_downloaded=utc(),
             geographic_coverage='Indian Ocean / India; global context where indicated',
             coverage_dates=extra.pop('coverage_dates', None), format='JSON / GeoJSON', raw_file=[], processed_file=processed,
             refresh_strategy=extra.pop('refresh_strategy', 'Run python scripts/acquire_data.py --all --refresh'),
             status='pending', records=0, **extra)


def safe_run(name, function):
    try:
        function()
        print(f'{name}: acquisition finished', flush=True)
    except Exception as exc:
        reason = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
        register(name, status='unavailable', error=reason, last_attempt=utc())
        print(f'{name}: unavailable ({reason}); existing cache retained', flush=True)


def acquire_ports():
    source('ports', 'Natural Earth world ports', 'Natural Earth / High Seas', 'Public domain',
           'https://www.naturalearthdata.com/downloads/10m-cultural-vectors/ports/', 'data/processed/ports.json')
    p = fetch('https://naturalearth.s3.amazonaws.com/10m_cultural/ne_10m_ports.zip', 'ne_10m_ports.zip')
    register('ports', status='downloaded', raw_file=[str(p.relative_to(ROOT))], format='Shapefile ZIP')
    source('nga_ports', 'NGA World Port Index 2019 via NOAA digital atlas', 'US National Geospatial-Intelligence Agency; NOAA',
           'Public domain US government data', 'https://gis.ngdc.noaa.gov/arcgis/rest/services/nccos/PIRO_DigitalAtlas/MapServer/30',
           'data/processed/ports.json', coverage_dates=['2019','2019'])
    files,count=[],0
    for offset in range(0,10000,2000):
        url='https://gis.ngdc.noaa.gov/arcgis/rest/services/nccos/PIRO_DigitalAtlas/MapServer/30/query'
        p=fetch(url,f'nga_ports_{offset:05}.geojson',{'where':'1=1','outFields':'*','f':'geojson','outSR':4326,
                                                    'resultOffset':offset,'resultRecordCount':2000,'orderByFields':'OBJECTID ASC'})
        rows=json.loads(p.read_text()).get('features',[])
        files.append(str(p.relative_to(ROOT)));count+=len(rows)
        if len(rows)<2000:break
    register('nga_ports',status='downloaded',records=count,raw_file=files)


def acquire_boundaries():
    for key, kind in [('land', 'land'), ('coastline', 'coastline')]:
        source(key, f'Natural Earth 1:10 million {kind}', 'Natural Earth', 'Public domain',
               f'https://www.naturalearthdata.com/downloads/10m-physical-vectors/10m-{kind}/',
               f'data/processed/{key}.geojson', caveat='1:10 million cartographic resolution; not a navigation chart.')
        try:
            p = fetch(f'https://naturalearth.s3.amazonaws.com/10m_physical/ne_10m_{kind}.zip', f'ne_10m_{kind}.zip')
            register(key, status='downloaded', raw_file=[str(p.relative_to(ROOT))], format='Shapefile ZIP')
        except Exception as exc:
            register(key, status='unavailable', error=str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__)
    # Countries supply context and a geographically derived country for port points.
    fetch('https://naturalearth.s3.amazonaws.com/10m_cultural/ne_10m_admin_0_countries.zip', 'ne_10m_admin_0_countries.zip')
    base = 'https://geo.vliz.be/geoserver/MarineRegions/wfs'
    for key, typename in [('eez', 'eez'), ('territorial_sea', 'eez_12nm'), ('contiguous_zone', 'eez_24nm'), ('high_seas', 'high_seas')]:
        source(key, f'Marine Regions {key.replace("_", " ")}', 'Flanders Marine Institute (VLIZ) / Marine Regions',
               'CC BY 4.0; consult the dataset citation and disclaimer',
               'https://www.marineregions.org/downloads.php', 'data/processed/boundaries.geojson',
               caveat='Scientific boundary context, not a definitive statement of legal jurisdiction.')
        try:
            p = fetch(base, f'marineregions_{key}.geojson', {'service':'WFS', 'version':'1.0.0', 'request':'GetFeature',
                      'typeName':f'MarineRegions:{typename}', 'outputFormat':'application/json',
                      'bbox':','.join(map(str, REGION))+',EPSG:4326', 'maxFeatures':200, 'srsName':'EPSG:4326'}, timeout=40)
            payload = json.loads(p.read_text())
            if payload.get('type') != 'FeatureCollection':
                raise RuntimeError('WFS response is not a FeatureCollection')
            register(key, status='downloaded', records=len(payload['features']), raw_file=[str(p.relative_to(ROOT))])
        except Exception as exc:
            register(key, status='manual_download_required', error=str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__,
                     expected_filename=f'data/raw/marineregions_{key}.geojson')
            print(f'DATASET REQUIRES MANUAL DOWNLOAD: {key}; https://www.marineregions.org/downloads.php; place GeoJSON in data/raw/marineregions_{key}.geojson', flush=True)
    source('mpa', 'World Database on Protected Areas marine polygons', 'UNEP-WCMC and IUCN / Protected Planet',
           'Protected Planet terms: https://www.protectedplanet.net/en/legal',
           'https://www.protectedplanet.net/country/IND', 'data/processed/mpa.geojson')
    register('mpa', status='manual_download_required', expected_filename='data/raw/india_mpa.geojson',
             error='Account/terms-controlled download. No replacement circles or approximate legal boundaries are invented.')
    print('DATASET REQUIRES MANUAL DOWNLOAD: India marine protected areas; https://www.protectedplanet.net/country/IND; place licensed polygons in data/raw/india_mpa.geojson', flush=True)


def acquire_debris():
    source('debris', 'NOAA NCEI Marine Microplastics: Indian Ocean subset', 'NOAA National Centers for Environmental Information',
           'Public scientific data; retain original study DOI and NOAA attribution',
           'https://www.ncei.noaa.gov/products/microplastics', 'data/processed/debris.json',
           caveat='Microplastic concentration observations are not recoverable macro-debris mass or fresh cleanup reports.')
    files, count = [], 0
    # Broad Indian Ocean region including India's west/east coasts and nearby island states.
    where = 'Longitude_degree_ >= 40 AND Longitude_degree_ <= 105 AND Latitude__degree_ >= -25 AND Latitude__degree_ <= 30'
    for offset in range(0, 40000, 2000):
        params = {'where':where, 'outFields':'*', 'returnGeometry':'true', 'f':'geojson',
                  'resultRecordCount':2000, 'resultOffset':offset, 'orderByFields':'OBJECTID ASC', 'outSR':4326}
        p = fetch(NOAA+'/query', f'noaa_microplastics_{offset:05}.geojson', params)
        payload = json.loads(p.read_text())
        if 'error' in payload:
            raise RuntimeError('NOAA feature service rejected query')
        batch = payload.get('features', [])
        files.append(str(p.relative_to(ROOT)))
        count += len(batch)
        if len(batch) < 2000:
            break
    register('debris', status='downloaded', records=count, raw_file=files)
    source('debris_tracker', 'Marine Debris Tracker exports', 'Marine Debris Tracker',
           'Dataset-specific export license and contributor terms', 'https://debristracker.org/data/', 'data/processed/debris_tracker.json')
    register('debris_tracker', status='manual_download_required', expected_filename='data/raw/debris_tracker.csv',
             error='Export requires source list selection through the provider interface; import supported by preprocessing.')


def acquire_marine():
    source('marine', 'Open-Meteo Marine regional forecast grid', 'Open-Meteo; Météo-France / Copernicus Marine; ECMWF',
           'CC BY 4.0; free endpoint for non-commercial use', 'https://open-meteo.com/en/docs/marine-weather-api',
           'data/processed/marine.json', provenance='MODEL FORECAST', refresh_strategy='Refresh every 6 hours')
    points = [(lat, lon) for lat in [7, 9, 11, 13, 15, 17, 19, 21, 23] for lon in [64, 66, 68, 70, 72, 74]]
    points += [(lat, lon) for lat in [7, 10, 13, 16, 19] for lon in [82, 85, 88, 91]]
    points += [(lat,lon) for lat,lon in [(12.8,74.5),(13.3,74.4),(14.7,73.8),(9.8,75.8),(15.4,73.2),(18.8,72.3)]]
    variables = 'wave_height,wave_direction,wave_period,ocean_current_velocity,ocean_current_direction,sea_surface_temperature,sea_level_height_msl,swell_wave_height,wind_wave_height'
    files = []
    for offset in range(0, len(points), 20):
        batch = points[offset:offset+20]
        params = {'latitude':','.join(str(p[0]) for p in batch), 'longitude':','.join(str(p[1]) for p in batch),
                  'hourly':variables, 'current':variables, 'forecast_days':3, 'cell_selection':'sea', 'velocity_unit':'ms', 'timezone':'GMT'}
        p = fetch('https://marine-api.open-meteo.com/v1/marine', f'marine_grid_{offset:03}.json', params)
        files.append(str(p.relative_to(ROOT)))
    register('marine', status='downloaded', raw_file=files, records=len(points))
    source('weather', 'Open-Meteo coastal weather forecast', 'Open-Meteo and its weather-model providers',
           'CC BY 4.0; free endpoint for non-commercial use', 'https://open-meteo.com/en/docs', 'data/processed/weather.json', provenance='MODEL FORECAST')
    coastal = points[-6:]
    params = {'latitude':','.join(str(p[0]) for p in coastal), 'longitude':','.join(str(p[1]) for p in coastal),
              'hourly':'temperature_2m,relative_humidity_2m,apparent_temperature,precipitation_probability,precipitation,rain,weather_code,pressure_msl,surface_pressure,cloud_cover,visibility,wind_speed_10m,wind_direction_10m,wind_gusts_10m',
              'daily':'weather_code,temperature_2m_max,temperature_2m_min,sunrise,sunset,uv_index_max,wind_gusts_10m_max,wind_speed_10m_max,wind_direction_10m_dominant,precipitation_sum,precipitation_probability_max',
              'forecast_days':7, 'timezone':'GMT', 'wind_speed_unit':'ms'}
    p = fetch('https://api.open-meteo.com/v1/forecast', 'coastal_weather.json', params)
    register('weather', status='downloaded', records=len(coastal), raw_file=[str(p.relative_to(ROOT))])
    source('copernicus', 'Copernicus Marine enhanced ocean data', 'Copernicus Marine Service',
           'Copernicus Marine product license', 'https://data.marine.copernicus.eu/', 'data/processed/copernicus.json')
    register('copernicus', status='credentials_required', error='Optional service credentials are not configured; Copernicus-derived fields remain available through Open-Meteo.')


def acquire_bathymetry():
    source('bathymetry', 'NOAA ETOPO1 Indian Ocean 15 arc-minute subset', 'NOAA NGDC / NCEI via CoastWatch ERDDAP',
           'Public domain; cite Amante and Eakins (2009), doi:10.7289/V5C8276M',
           'https://www.ncei.noaa.gov/products/etopo-global-relief-model', 'data/processed/bathymetry.json',
           caveat='Subsampled global relief model for context, unsuitable for navigation or under-keel clearance.')
    suffix = '/erddap/griddap/etopo180.csv?altitude[(0):15:(30)][(55):15:(100)]'
    try:
        p = fetch('https://oceanwatch.aoml.noaa.gov'+suffix, 'etopo_indian_ocean.csv', timeout=35)
    except Exception:
        p = fetch('https://coastwatch.pfeg.noaa.gov'+suffix, 'etopo_indian_ocean.csv', timeout=35)
    register('bathymetry', status='downloaded', raw_file=[str(p.relative_to(ROOT))], format='CSV')


def acquire_historical_ais():
    source('historical_ais', 'NOAA MarineCadastre actual AIS broadcast prefix sample, 2024-01-01',
           'NOAA Office for Coastal Management / BOEM / US Coast Guard',
           'Public US government data; NOAA MarineCadastre attribution',
           'https://noaaocm.blob.core.windows.net/ais/csv2/csv2024/index.html', 'data/processed/vessels.json',
           coverage_dates=['2024-01-01','2024-01-01'],
           caveat='US waters / global demonstration context, not Indian AIS. A non-random prefix sample cannot establish tracking silence outside its recording window.')
    url='https://noaaocm.blob.core.windows.net/ais/csv2/csv2024/ais-2024-01-01.csv.zst'
    prefix=DATA/'raw'/'noaa_ais_2024_01_01.zst.prefix'
    csvpath=DATA/'raw'/'noaa_ais_2024_01_01_prefix.csv'
    budget=2*1024*1024
    if not prefix.exists() or FORCE:
        with requests.get(url,headers={'Range':f'bytes=0-{budget-1}'},stream=True,timeout=(15,45)) as response:
            if response.status_code not in [200,206]:
                raise RuntimeError(f'HTTP {response.status_code}')
            content=bytearray()
            for chunk in response.iter_content(65536):
                content.extend(chunk)
                if len(content)>=budget:
                    break
            prefix.write_bytes(bytes(content[:budget]))
    data=prefix.read_bytes()
    try:
        import zstandard
        expanded=zstandard.ZstdDecompressor().decompressobj().decompress(data)
    except ImportError:
        result=subprocess.run(['zstd','-d','-c'],input=data,capture_output=True)
        expanded=result.stdout
    if not expanded:
        raise RuntimeError('No complete AIS rows decoded; install Python zstandard or the zstd command')
    # Only complete CSV rows; the last incomplete line is deliberately discarded.
    expanded=expanded[:expanded.rfind(b'\n')+1]
    csvpath.write_bytes(expanded)
    record(prefix,url,'partial compressed prefix preserved',{'Range':f'bytes=0-{len(data)-1}'})
    record(csvpath,url,'complete CSV rows extracted from Zstandard prefix',{'compressed_prefix':str(prefix.relative_to(ROOT)),
                                                                        'whole_file_checksum_verified':False})
    count=sum(1 for _ in csv.DictReader(io.StringIO(expanded.decode('utf-8-sig'))))
    register('historical_ais',status='downloaded',records=count,raw_file=[str(prefix.relative_to(ROOT)),str(csvpath.relative_to(ROOT))],
             geographic_coverage='United States coastal waters / global scalability context; not India')


def acquire_gfw():
    source('gfw_identity', 'Global Fishing Watch India vessel identity', 'Global Fishing Watch',
           'CC BY-SA 4.0; GFW API terms and data caveats apply', 'https://api-doc.globalfishingwatch.org/docs/v3/vessels/search',
           'data/processed/vessel_identity.json')
    if not (os.getenv('GFW_TOKEN') or os.getenv('GFW_API_ACCESS_TOKEN')):
        register('gfw_identity', status='credentials_required', error='Set GFW_API_ACCESS_TOKEN or GFW_TOKEN in .env')
        return
    files, count, since = [], 0, None
    for page in range(25):
        params = {'datasets[0]':'public-global-vessel-identity:latest', 'where':"flag = 'IND'", 'limit':50}
        if since:
            params['since'] = since
        p = fetch(GFW+'/vessels/search', f'gfw_identity_{page:03}.json', params, auth=True)
        payload = json.loads(p.read_text())
        rows = payload.get('entries', [])
        files.append(str(p.relative_to(ROOT)))
        count += len(rows)
        since = payload.get('since')
        if not since or not rows or count >= payload.get('total', count):
            break
    register('gfw_identity', status='downloaded', records=count, raw_file=files)
    geom = {'type':'Polygon', 'coordinates':[[[60,5],[82,5],[82,26],[60,26],[60,5]]]}
    event_types = {'fishing':'public-global-fishing-events:latest', 'encounter':'public-global-encounters-events:latest',
                   'loitering':'public-global-loitering-events:latest', 'port_visit':'public-global-port-visits-events:latest',
                   'gap':'public-global-gaps-events:latest'}
    for kind, dataset in event_types.items():
        key = 'gfw_'+kind
        source(key, f'GFW historical {kind} events around India', 'Global Fishing Watch', 'CC BY-SA 4.0; GFW API terms and caveats',
               'https://api-doc.globalfishingwatch.org/our-apis/documentation/docs/v3/events/get-all-events', 'data/processed/vessels.json')
        try:
            event_files, total = [], 0
            for offset in range(0, 2000, 500):
                body = {'datasets':[dataset], 'startDate':'2024-01-01', 'endDate':'2026-01-01', 'geometry':geom}
                p = fetch(GFW+'/events', f'gfw_events_{kind}_{offset:04}.json', {'limit':500,'offset':offset}, body=body, auth=True, timeout=55)
                payload = json.loads(p.read_text())
                rows = payload.get('entries', [])
                event_files.append(str(p.relative_to(ROOT)))
                total += len(rows)
                if len(rows)<500 or not payload.get('nextOffset'):
                    break
            register(key, status='downloaded', records=total, raw_file=event_files, coverage_dates=['2024-01-01','2026-01-01'])
        except Exception as exc:
            register(key, status='unavailable', error=str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__)
    # Report requests must run sequentially: GFW permits one report per token at a time.
    for kind, dataset in [('sar','public-global-sar-presence:latest'), ('fishing_effort','public-global-fishing-effort:latest')]:
        key = 'gfw_'+kind
        source(key, f'GFW {kind.replace("_", " ")} regional grid report', 'Global Fishing Watch', 'CC BY-SA 4.0; GFW API terms and caveats',
               'https://api-doc.globalfishingwatch.org/our-apis/documentation/docs/v3/4wings/report', f'data/processed/{kind}.json')
        try:
            params = {'datasets[0]':dataset, 'date-range':'2025-01-01,2025-02-01', 'format':'JSON',
                      'temporal-resolution':'ENTIRE', 'spatial-resolution':'LOW', 'spatial-aggregation':'false'}
            polygon = {'type':'FeatureCollection','features':[{'type':'Feature','properties':{},'geometry':geom}]}
            p = fetch(GFW+'/4wings/report', f'gfw_report_{kind}.json', params, body={'geojson':polygon}, auth=True, timeout=65)
            register(key, status='downloaded', raw_file=[str(p.relative_to(ROOT))], coverage_dates=['2025-01-01','2025-02-01'])
        except Exception as exc:
            register(key, status='unavailable', error=str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__)


def build_catalog():
    path = DATA / 'metadata' / 'sources.json'
    values = json.loads(path.read_text()) if path.exists() else {}
    if values.get('gfw',{}).get('error'):
        error=values['gfw']['error']
        for key,label in [('gfw_identity','vessel identity'),('gfw_fishing','fishing events'),('gfw_encounter','encounters'),
                          ('gfw_loitering','loitering'),('gfw_port_visit','port visits'),('gfw_gap','AIS gaps'),
                          ('gfw_sar','SAR detection report'),('gfw_fishing_effort','fishing activity report')]:
            if values.get(key,{}).get('status') in [None,'pending']:
                values[key]={**values.get(key,{}),'id':key,'name':'Global Fishing Watch '+label,'provider':'Global Fishing Watch',
                             'source':GFW,'source_type':'Authenticated API','license':'GFW API terms / dataset license',
                             'attribution':'Global Fishing Watch','status':'credentials_rejected','error':error,'records':0,
                             'date_downloaded':None,'coverage_dates':None,'geographic_coverage':'India / Arabian Sea',
                             'format':'JSON','raw_file':[],'processed_file':'data/processed/vessels.json',
                             'refresh_strategy':'Replace GFW_API_ACCESS_TOKEN with a valid provider token; rerun scripts/acquire_gfw.py',
                             'manual_download':'Use https://globalfishingwatch.org/data-download/ under its account and license terms. No authenticated endpoint is bypassed.'}
        values.pop('gfw',None)
    manifest_path=DATA/'download_manifest.json'
    manifest=json.loads(manifest_path.read_text()) if manifest_path.exists() else []
    for value in values.values():
        if value.get('status') in ['ready','downloaded']:
            value.pop('error',None)
        stamps=[r['download_timestamp'] for r in manifest if r['file'] in value.get('raw_file',[])]
        if stamps:
            value['date_downloaded']=max(stamps)
    write_json(path,values)
    catalog = {'generated_at':utc(), 'region_bbox':REGION, 'datasets':list(values.values())}
    write_json(DATA / 'catalog.json', catalog)
    (DATA / 'catalog.yaml').write_text(yaml.safe_dump(catalog, sort_keys=False, allow_unicode=True))


GROUPS = {'ports':acquire_ports, 'boundaries':acquire_boundaries, 'debris':acquire_debris,
          'marine':acquire_marine, 'bathymetry':acquire_bathymetry, 'gfw':acquire_gfw,
          'historical_ais':acquire_historical_ais}


def main():
    global FORCE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--all', action='store_true', help='Attempt all accessible sources; preserve valid caches')
    parser.add_argument('--only', choices=GROUPS)
    parser.add_argument('--refresh', action='store_true', help='Refresh existing raw downloads')
    parser.add_argument('--no-preprocess', action='store_true')
    args = parser.parse_args()
    FORCE = args.refresh
    selected = {args.only:GROUPS[args.only]} if args.only else GROUPS
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(safe_run,key,fn) for key,fn in selected.items()]
        for future in as_completed(futures):
            future.result()
    if not args.no_preprocess:
        from preprocess_data import preprocess
        preprocess()
    build_catalog()
    print('Catalog and checksummed download manifest written to data/.', flush=True)


if __name__ == '__main__':
    main()
