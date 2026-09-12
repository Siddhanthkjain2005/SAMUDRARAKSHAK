#!/usr/bin/env python3
"""Validate file checksums, source attribution, coordinate ranges and schema invariants."""
import hashlib
import json
import math
import csv
from pathlib import Path
from acquire_data import ROOT,DATA,utc,write_json


def validate():
    errors=[]
    counts={}
    for name in ['ports','debris','marine','vessels','bathymetry']:
        path=DATA/'processed'/(name+'.json')
        if not path.exists():
            errors.append(name+': missing processed file');continue
        rows=json.loads(path.read_text());counts[name]=len(rows)
        for i,row in enumerate(rows):
            lat,lon=row.get('latitude'),row.get('longitude')
            if not isinstance(lat,(float,int)) or not isinstance(lon,(float,int)) or not (-90<=lat<=90 and -180<=lon<=180):
                errors.append(f'{name}[{i}]: invalid coordinates')
            if not row.get('source') or not row.get('provenance'):
                errors.append(f'{name}[{i}]: missing provenance')
            if name=='debris' and row.get('concentration') is not None and row.get('quantity') is not None:
                errors.append(f'{name}[{i}]: concentration must not be mistaken for debris count/mass')
            if name=='marine' and row.get('current_speed_ms') is not None:
                raw,unit=row.get('original_current_speed'),row.get('original_current_speed_unit')
                if unit=='km/h' and not math.isclose(row['current_speed_ms'],raw/3.6):
                    errors.append(f'{name}[{i}]: incorrect current unit conversion')
    from shapely.geometry import shape
    for name in ['land','land_world','coastline','boundaries','mpa']:
        p=DATA/'processed'/(name+'.geojson')
        if not p.exists():
            errors.append(name+': missing geometry file');continue
        features=json.loads(p.read_text())['features'];counts[name]=len(features)
        for i,feature in enumerate(features):
            g=shape(feature['geometry'])
            if g.is_empty or not g.is_valid:
                errors.append(f'{name}[{i}]: empty or invalid geometry')
    manifest=json.loads((DATA/'download_manifest.json').read_text())
    for entry in manifest:
        p=ROOT/entry['file']
        if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest()!=entry['sha256']:
            errors.append(entry['file']+': checksum mismatch')
    catalog=json.loads((DATA/'catalog.json').read_text())
    required={'name','provider','source_type','source','license','attribution','date_downloaded','coverage_dates',
              'geographic_coverage','format','raw_file','processed_file','refresh_strategy'}
    for dataset in catalog['datasets']:
        missing=required-set(dataset)
        if missing:errors.append(f"catalog {dataset.get('id')}: missing {', '.join(sorted(missing))}")
    traceable=0
    noaa_csv=DATA/'raw'/'noaa_ais_2024_01_01_prefix.csv'
    if noaa_csv.exists():
        source_points=set()
        raw_records=0
        with noaa_csv.open(newline='') as f:
            for r in csv.DictReader(f):
                raw_records+=1
                try:source_points.add((r['mmsi'],r['base_date_time'].replace(' ','T')+'Z',float(r['latitude']),float(r['longitude'])))
                except (ValueError,KeyError):pass
        vessels=json.loads((DATA/'processed'/'vessels.json').read_text())
        by_id={v['id']:v for v in vessels}
        for v in vessels:
            if v.get('source')!='NOAA MarineCadastre AIS':continue
            timestamps=[p['timestamp'] for p in v.get('track',[])]
            if timestamps!=sorted(timestamps):errors.append(f"{v['id']}: track is not time ordered")
            for p in v.get('track',[]):
                key=(v['mmsi'],p['timestamp'],p['latitude'],p['longitude'])
                if key not in source_points:errors.append(f"{v['id']}: replay point does not match source CSV")
                else:traceable+=1
        cases=json.loads((DATA/'demo'/'historical_cases.json').read_text())
        if len(cases)<3:errors.append('Fewer than three real historical demo cases')
        for case in cases:
            vessel=by_id.get(case['vessel_id'])
            if not vessel:errors.append(f"{case['id']}: vessel absent from cache")
            elif case.get('track_points')!=len(vessel.get('track',[])):errors.append(f"{case['id']}: track count mismatch")
        counts['historical_ais_broadcast_rows']=raw_records
        counts['historical_ais_replay_points']=traceable
        counts['historical_demo_cases']=len(cases)
        counts['vessel_identities']=len(json.loads((DATA/'processed'/'vessel_identity.json').read_text()))
    unavailable=[{'name':d.get('name',d.get('id')),'status':d.get('status'),'reason':d.get('error')} for d in catalog['datasets']
                 if d.get('status') not in ['ready','downloaded']]
    report={'validated_at':utc(),'ok':not errors,'counts':counts,'errors':errors,'unavailable':unavailable,
            'raw_files_verified':len(manifest),'download_bytes':sum(x['file_size'] for x in manifest)}
    write_json(DATA/'metadata'/'validation.json',report)
    print(json.dumps(report,indent=2))
    return not errors


if __name__=='__main__':
    raise SystemExit(0 if validate() else 1)
