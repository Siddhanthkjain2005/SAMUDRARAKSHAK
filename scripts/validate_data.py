#!/usr/bin/env python3
"""Validate file checksums, source attribution, coordinate ranges and schema invariants."""
import hashlib
import json
import math
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
    for name in ['land','coastline','boundaries','mpa']:
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
    unavailable=[{'name':d.get('name',d.get('id')),'status':d.get('status'),'reason':d.get('error')} for d in catalog['datasets']
                 if d.get('status') not in ['ready','downloaded']]
    report={'validated_at':utc(),'ok':not errors,'counts':counts,'errors':errors,'unavailable':unavailable,
            'raw_files_verified':len(manifest),'download_bytes':sum(x['file_size'] for x in manifest)}
    write_json(DATA/'metadata'/'validation.json',report)
    print(json.dumps(report,indent=2))
    return not errors


if __name__=='__main__':
    raise SystemExit(0 if validate() else 1)
