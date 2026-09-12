import json
import math
from functools import lru_cache
from pathlib import Path
import yaml
from backend.config import DATA, PROCESSED

def clean(value):
    if isinstance(value,float) and not math.isfinite(value):
        return None
    if isinstance(value,dict):
        return {k:clean(v) for k,v in value.items()}
    if isinstance(value,list):
        return [clean(v) for v in value]
    return value

@lru_cache(maxsize=32)
def _read(path, modified):
    try:
        return clean(json.loads(Path(path).read_text()))
    except (OSError, ValueError):
        return []

def read_json(name, default=None):
    path=PROCESSED/name
    if not path.exists():
        return [] if default is None else default
    return _read(str(path),path.stat().st_mtime_ns)

def records(name):
    result=read_json(name+'.json')
    if isinstance(result,dict):
        result=result.get('records',result.get('data',result.get(name,[])))
    return result if isinstance(result,list) else []

def catalog():
    for filename in ('catalog.json','catalog.yaml'):
        path=DATA/filename
        if path.exists():
            try:
                data=json.loads(path.read_text()) if filename.endswith('.json') else yaml.safe_load(path.read_text())
                return data.get('datasets',data) if isinstance(data,dict) else data
            except (ValueError,OSError):
                continue
    return []

def normalize_vessel(v):
    result={**v}
    result['id']=str(v.get('id',v.get('mmsi',v.get('vessel_id',''))))
    result['name']=v.get('name') or v.get('shipname') or v.get('ship_name') or ('Vessel '+result['id'][:8])
    result.setdefault('speed',v.get('sog'))
    result.setdefault('course',v.get('cog'))
    result.setdefault('provenance','HISTORICAL')
    result.setdefault('track',[])
    result.setdefault('events',[])
    return result

def vessels():
    return [normalize_vessel(v) for v in records('vessels')]
