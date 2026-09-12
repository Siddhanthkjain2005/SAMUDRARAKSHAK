import math
from collections import Counter
from datetime import datetime,timezone
import numpy as np
from sklearn.cluster import DBSCAN
from backend.models.behaviour_model import parse_time

def valid_observations(observations):
    result=[]
    for item in observations:
        try:
            lat,lon=float(item['latitude']),float(item['longitude'])
            if math.isfinite(lat) and math.isfinite(lon) and -90<=lat<=90 and -180<=lon<=180:
                result.append({**item,'latitude':lat,'longitude':lon})
        except (KeyError,TypeError,ValueError):
            continue
    return result

def cluster_debris(observations,eps_km=45,min_samples=3):
    valid=valid_observations(observations)
    if not valid:return []
    coords=np.radians([[o['latitude'],o['longitude']] for o in valid])
    labels=DBSCAN(eps=eps_km/6371.0088,min_samples=min_samples,metric='haversine',algorithm='ball_tree').fit_predict(coords)
    hotspots=[]
    for label in sorted(set(labels)):
        if label<0:continue
        group=[valid[i] for i in np.where(labels==label)[0]]
        categories=Counter(o.get('debris_category') or 'Unclassified debris' for o in group)
        quantities=[float(o['quantity']) for o in group if o.get('quantity') is not None]
        dates=[parse_time(o.get('timestamp')) for o in group]; dates=[d for d in dates if d]
        newest=max(dates).isoformat() if dates else None
        age_days=max(0,(datetime.now(timezone.utc)-max(dates)).days) if dates else None
        concentration=[float(o['concentration']) for o in group if isinstance(o.get('concentration'),(int,float))]
        # Sampling density is not an inferred debris mass or present-day abundance.
        priority=round(min(100,25+15*math.log2(len(group)+1)+(15 if age_days is not None and age_days<365 else 0)))
        hotspots.append({'id':f'hotspot-{int(label)+1}','latitude':float(np.mean([o['latitude'] for o in group])),
            'longitude':float(np.mean([o['longitude'] for o in group])),'count':len(group),'priority':priority,
            'categories':list(categories),'category_counts':dict(categories),'quantity':sum(quantities) if quantities else None,
            'concentration':float(np.median(concentration)) if concentration else None,
            'concentration_units':sorted({str(o.get('concentration_units',o.get('units','unknown'))) for o in group if o.get('concentration') is not None}),
            'newest_observation':newest,'age_days':age_days,'provenance':'COMPUTED · HISTORICAL REAL DATA',
            'observation_ids':[str(o.get('observation_id',o.get('id',''))) for o in group],
            'sources':sorted({str(o.get('source',o.get('dataset',''))) for o in group}),
            'collection_mass_kg':None,'mission_type':'SURVEY / VALIDATION' if any('micro' in c.lower() for c in categories) else 'CLEANUP VALIDATION',
            'methodology':f'DBSCAN haversine radius {eps_km:g} km, minimum {min_samples} observations. Priority ranks sampling concentration, not a current litter mass estimate.'})
    return sorted(hotspots,key=lambda h:(-h['priority'],-h['count'],h['id']))
