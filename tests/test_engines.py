"""Physical invariants and source-integrity checks, not snapshot tests of implementation."""
import math
import pytest
from shapely.geometry import Polygon
from backend.services.geospatial import haversine,angle_difference,LandMask,project
from backend.models.fuel_model import current_projection,segment_estimate
from backend.models.behaviour_model import behaviour_features
from backend.models.risk_model import fuse_risk
from backend.models.drift_model import drift_forecast
from backend.agents.debris_intelligence import cluster_debris
from backend.agents.debris_coordinator import assign_collectors
from backend.services.route_optimizer import optimize_route,nearest_environment
from backend.providers.aisstream import normalize_position
from backend.providers.marine_weather import normalized_current_speed

def test_course_wrap():
    assert angle_difference(359,2)==3
    assert angle_difference(2,359)==3
    assert angle_difference(90,270)==180

def test_geodesic_distance_and_projection():
    assert haversine((0,0),(0,1))==pytest.approx(111.195,rel=1e-4)
    assert haversine((12,74),(12,74))==0
    lat,lon=project(12,74,100,90)
    assert haversine((12,74),(lat,lon))==pytest.approx(100,rel=1e-8)

def test_land_intersection_detects_crossing_not_only_endpoints():
    mask=LandMask(Polygon([(1,-1),(2,-1),(2,1),(1,1)]))
    assert not mask.is_land(0,0)
    assert not mask.is_land(0,3)
    assert mask.intersects((0,0),(0,3))
    assert not mask.intersects((2,0),(2,3))

def test_current_projection_respects_direction_and_units():
    assert current_projection(1,90,90)==pytest.approx(1.94384449)
    assert current_projection(1,270,90)==pytest.approx(-1.94384449)
    assert current_projection(1,0,90)==pytest.approx(0,abs=1e-12)
    assert normalized_current_speed(3.6,'km/h')==pytest.approx(1)
    assert normalized_current_speed(1,'unknown') is None

def test_fuel_current_and_wave_monotonicity():
    calm=segment_estimate(120,90,12,24)
    assist=segment_estimate(120,90,12,24,{'current_speed_ms':1,'current_direction':90})
    opposing=segment_estimate(120,90,12,24,{'current_speed_ms':1,'current_direction':270})
    waves=segment_estimate(120,90,12,24,{'wave_height':3,'wave_direction':90})
    assert calm['duration_hours']==10 and calm['fuel_t']==10
    assert assist['fuel_t']<calm['fuel_t']<opposing['fuel_t']
    assert waves['fuel_t']>calm['fuel_t']
    assert calm['co2_t']==pytest.approx(31.14)

def test_loitering_uses_duration_radius_and_speed():
    track=[{'latitude':12+i*.0002,'longitude':74,'speed':1,'course':359 if i%2 else 2,'timestamp':f'2026-01-01T00:{i*10:02}:00Z'} for i in range(4)]
    features=behaviour_features(track)
    assert features['loitering']
    assert features['dwell_minutes']==30
    assert features['sharp_turn_count']==0
    assert features['radius_m']<500
    assert not behaviour_features(track[:2])['loitering']

def test_missing_track_does_not_invent_behaviour():
    result=behaviour_features([])
    assert result['anomaly_score']==0
    assert result['speed_mean'] is None
    assert result['samples']==0

def test_risk_is_not_confidence_and_duplicates_are_bounded():
    low=fuse_risk([])
    assert low['risk_score']==0 and low['confidence_score']==0
    evidence=[{'type':'gap','source':'GFW','confidence':70}]*100
    result=fuse_risk(evidence)
    assert result['risk_score']<=26
    assert result['confidence_score']<=62
    assert result['risk_score']!=result['confidence_score']

def test_dbscan_ignores_invalid_points_and_never_invents_kg():
    observations=[{'observation_id':str(i),'latitude':10+i*.01,'longitude':74,'quantity':None,'concentration':.1,'debris_category':'Microplastics'} for i in range(5)]
    observations += [{'latitude':999,'longitude':74},{'latitude':None,'longitude':74}]
    clusters=cluster_debris(observations)
    assert len(clusters)==1 and clusters[0]['count']==5
    assert clusters[0]['quantity'] is None
    assert clusters[0]['collection_mass_kg'] is None
    assert clusters[0]['mission_type']=='SURVEY / VALIDATION'

def test_drift_distance_and_missing_current():
    result=drift_forecast(0,0,{'current_speed_ms':1,'current_direction':90},3)
    end=result['points'][-1]
    assert haversine((0,0),(end['latitude'],end['longitude']))==pytest.approx(10.8,rel=1e-6)
    assert end['uncertainty_km']>result['points'][0]['uncertainty_km']
    assert drift_forecast(0,0,{},3)['points']==[]

def test_assignment_respects_battery_and_capacity(monkeypatch):
    monkeypatch.setattr('backend.agents.debris_coordinator.get_land_mask',lambda _:None)
    collectors=[{'id':'a','latitude':0,'longitude':0,'battery':90,'speed_knots':8,'remaining_capacity_kg':30},
        {'id':'b','latitude':0,'longitude':.01,'battery':14,'speed_knots':8,'remaining_capacity_kg':30}]
    hotspots=[{'id':'h','latitude':0,'longitude':.1,'priority':90}]
    assignments,_=assign_collectors(collectors,hotspots,[],6)
    assert len(assignments)==1 and assignments[0]['collector_id']=='a'
    collectors[0]['remaining_capacity_kg']=0
    assert assign_collectors(collectors,hotspots,[],6)[0]==[]

def test_graph_routes_around_obstacle_and_optimized_fuel_never_worse():
    mask=LandMask(Polygon([(.35,-.3),(.65,-.3),(.65,.3),(.35,.3)]))
    result=optimize_route({'id':'a','latitude':0,'longitude':0},{'id':'b','latitude':0,'longitude':1},[],land=mask,safety_buffer_km=0)
    for path in ('baseline','optimized'):
        coordinates=result[path]['coordinates']
        assert all(not mask.intersects((a[1],a[0]),(b[1],b[0])) for a,b in zip(coordinates,coordinates[1:]))
    assert result['optimized']['fuel_t']<=result['baseline']['fuel_t']+.001
    assert result['baseline']['distance_nm']>haversine((0,0),(0,1))/1.852
    assert result['optimized']['forecast_coverage_pct']==0

def test_far_away_weather_not_silently_reused():
    assert nearest_environment(12,74,[{'latitude':0,'longitude':0,'current_speed_ms':2}])=={}

def test_ais_sentinels_not_real_speed_or_heading():
    message={'MetaData':{'MMSI':123456789,'ShipName':' Test '},'Message':{'PositionReport':{'Latitude':12,'Longitude':74,'Sog':102.3,'Cog':360,'TrueHeading':511}}}
    item=normalize_position(message)
    assert item['speed'] is None and item['course'] is None and item['heading'] is None
    assert item['name']=='Test' and item['provenance']=='LIVE'
