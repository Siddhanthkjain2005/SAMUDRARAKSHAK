"""Durable local fallback, including original AIS observations and mission outputs."""
import json
import sqlite3
from datetime import datetime, timezone
from contextlib import contextmanager
from backend.config import SQLITE_PATH

def now():
    return datetime.now(timezone.utc).isoformat()

@contextmanager
def connection():
    db = sqlite3.connect(SQLITE_PATH, timeout=20)
    db.row_factory = sqlite3.Row
    try:
        yield db
        db.commit()
    finally:
        db.close()

def initialize():
    SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connection() as db:
        db.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS ais (id INTEGER PRIMARY KEY, mmsi TEXT NOT NULL,
            timestamp TEXT NOT NULL, latitude REAL, longitude REAL, payload TEXT NOT NULL,
            UNIQUE(mmsi,timestamp,latitude,longitude));
        CREATE INDEX IF NOT EXISTS ais_mmsi_time ON ais(mmsi,timestamp);
        CREATE TABLE IF NOT EXISTS missions (id TEXT PRIMARY KEY, type TEXT, timestamp TEXT, payload TEXT);
        CREATE TABLE IF NOT EXISTS provider_state (id TEXT PRIMARY KEY, payload TEXT);
        ''')

def record_ais(observation):
    with connection() as db:
        db.execute('INSERT OR IGNORE INTO ais(mmsi,timestamp,latitude,longitude,payload) VALUES(?,?,?,?,?)',
            (str(observation['mmsi']),observation['timestamp'],observation['latitude'],observation['longitude'],json.dumps(observation)))

def ais_observations(limit=1000, mmsi=None):
    with connection() as db:
        if mmsi:
            rows=db.execute('SELECT payload FROM ais WHERE mmsi=? ORDER BY timestamp DESC LIMIT ?', (str(mmsi),limit)).fetchall()
        else:
            rows=db.execute('SELECT payload FROM ais ORDER BY timestamp DESC LIMIT ?', (limit,)).fetchall()
    return [json.loads(r['payload']) for r in reversed(rows)]

def live_vessels():
    with connection() as db:
        rows=db.execute('SELECT a.payload FROM ais a JOIN (SELECT mmsi,MAX(id) id FROM ais GROUP BY mmsi) b ON a.id=b.id ORDER BY a.id DESC LIMIT 2000').fetchall()
    return [json.loads(r['payload']) for r in rows]

def ais_count():
    with connection() as db:
        return db.execute('SELECT COUNT(*) FROM ais').fetchone()[0]

def save_mission(mission):
    with connection() as db:
        db.execute('INSERT OR REPLACE INTO missions VALUES(?,?,?,?)',(mission['id'],mission['type'],now(),json.dumps(mission,allow_nan=False)))

def mission_by_id(identifier):
    with connection() as db:
        row=db.execute('SELECT payload FROM missions WHERE id=?',(identifier,)).fetchone()
    return json.loads(row['payload']) if row else None

def recent_missions(limit=50):
    with connection() as db:
        rows=db.execute('SELECT payload FROM missions ORDER BY timestamp DESC LIMIT ?', (limit,)).fetchall()
    return [json.loads(r['payload']) for r in rows]

def mission_summaries(limit=30,offset=0,mission_type=None):
    where='WHERE type=?' if mission_type else ''
    parameters=(mission_type,) if mission_type else ()
    with connection() as db:
        total=db.execute(f'SELECT COUNT(*) FROM missions {where}',parameters).fetchone()[0]
        rows=db.execute(f'''SELECT id,type,timestamp,
            json_extract(payload,'$.origin.name') origin,
            json_extract(payload,'$.destination.name') destination,
            json_extract(payload,'$.vessel.name') vessel_name
            FROM missions {where} ORDER BY timestamp DESC LIMIT ? OFFSET ?''',(*parameters,limit,offset)).fetchall()
    result=[]
    for row in rows:
        title=f"{row['origin']} → {row['destination']}" if row['type']=='route' else row['vessel_name'] if row['type']=='investigation' else 'Marine cleanup coordination'
        result.append({'id':row['id'],'type':row['type'],'created_at':row['timestamp'],'title':title or 'Maritime mission','report_url':f"/api/reports/{row['id']}"})
    return {'missions':result,'total':total}

def impact_summary():
    """Latest scenario estimate per port pair; repeating a demo is not real-world impact."""
    with connection() as db:
        rows=db.execute('''SELECT type,
            json_extract(payload,'$.origin.id') origin,
            json_extract(payload,'$.destination.id') destination,
            json_extract(payload,'$.vessel.id') vessel_id,
            json_extract(payload,'$.savings.fuel_t') fuel,
            json_extract(payload,'$.savings.co2_t') co2,
            json_array_length(json_extract(payload,'$.assignments')) assignments
            FROM missions ORDER BY timestamp DESC''').fetchall()
    routes={};investigations=set();active_collectors=None
    for row in rows:
        if row['type']=='route':routes.setdefault((row['origin'],row['destination']),(row['fuel'] or 0,row['co2'] or 0))
        elif row['type']=='investigation' and row['vessel_id']:investigations.add(row['vessel_id'])
        elif row['type']=='cleanup' and active_collectors is None:active_collectors=row['assignments'] or 0
    return {'fuel_saved_t':round(sum(v[0] for v in routes.values()),3),'co2_avoided_t':round(sum(v[1] for v in routes.values()),3),
        'investigations':len(investigations),'active_collectors':active_collectors or 0,'unique_route_scenarios':len(routes),'reports_generated':len(rows),
        'impact_methodology':'Potential model savings from the latest run of each distinct origin/destination pair, not completed voyages. Investigations count distinct vessel IDs. Cleanup assets are simulated.'}

def save_provider(identifier, state):
    with connection() as db:
        db.execute('INSERT OR REPLACE INTO provider_state VALUES(?,?)',(identifier,json.dumps(state)))
