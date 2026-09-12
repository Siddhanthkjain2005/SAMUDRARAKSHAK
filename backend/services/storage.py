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

def save_provider(identifier, state):
    with connection() as db:
        db.execute('INSERT OR REPLACE INTO provider_state VALUES(?,?)',(identifier,json.dumps(state)))
