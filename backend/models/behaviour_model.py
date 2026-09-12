from datetime import datetime, timezone
from statistics import mean, median, pvariance
from backend.services.geospatial import haversine, angle_difference

def parse_time(value):
    if not value:
        return None
    try:
        timestamp=str(value).replace(' UTC','+00:00').replace('Z','+00:00')
        parsed=datetime.fromisoformat(timestamp)
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except (ValueError,TypeError):
        return None

def behaviour_features(track):
    points=[p for p in track if p.get('latitude') is not None and p.get('longitude') is not None]
    points.sort(key=lambda p:str(p.get('timestamp','')))
    speeds=[float(p.get('speed',p.get('sog')) or 0) for p in points if p.get('speed',p.get('sog')) is not None]
    courses=[float(p.get('course',p.get('cog'))) for p in points if p.get('course',p.get('cog')) is not None]
    turns=[angle_difference(a,b) for a,b in zip(courses,courses[1:])]
    distances=[haversine((a['latitude'],a['longitude']),(b['latitude'],b['longitude'])) for a,b in zip(points,points[1:])]
    times=[parse_time(p.get('timestamp')) for p in points]
    span=(times[-1]-times[0]).total_seconds()/60 if len(points)>1 and times[0] and times[-1] else 0
    distance=sum(distances)
    net=haversine((points[0]['latitude'],points[0]['longitude']),(points[-1]['latitude'],points[-1]['longitude'])) if len(points)>1 else 0
    center=(mean(p['latitude'] for p in points),mean(p['longitude'] for p in points)) if points else (0,0)
    radius=max([haversine(center,(p['latitude'],p['longitude']))*1000 for p in points] or [0])
    speed_mean=mean(speeds) if speeds else None
    slow_minutes=0
    accelerations=[]
    for i in range(1,len(points)):
        if times[i] and times[i-1]:
            minutes=max(0,(times[i]-times[i-1]).total_seconds()/60)
            a,b=points[i-1].get('speed',points[i-1].get('sog')),points[i].get('speed',points[i].get('sog'))
            if a is not None and b is not None and minutes>0:
                if (float(a)+float(b))/2<2: slow_minutes+=minutes
                accelerations.append((float(b)-float(a))/minutes)
    loitering=len(points)>=3 and span>=20 and radius<=500 and speed_mean is not None and speed_mean<2
    features={'samples':len(points),'speed_mean':speed_mean,'speed_median':median(speeds) if speeds else None,
        'speed_variance':pvariance(speeds) if len(speeds)>1 else 0,'current_speed':speeds[-1] if speeds else None,
        'current_course':courses[-1] if courses else None,'course_change':turns[-1] if turns else 0,
        'turn_frequency':len([t for t in turns if t>30])/max(span,1),'sharp_turn_count':sum(t>60 for t in turns),
        'distance_km':distance,'net_displacement_km':net,'track_straightness':net/distance if distance>0 else None,
        'duration_minutes':span,'dwell_minutes':span if loitering else 0,'slow_speed_minutes':slow_minutes,
        'loitering':loitering,'radius_m':radius,'movement_area_km2':3.14159*(radius/1000)**2,
        'acceleration_knots_per_minute':accelerations[-1] if accelerations else None,
        'historical_deviation':None,'distance_from_normal_route':None,'geofence_duration':None}
    reasons=[]; score=0
    if loitering: score+=25; reasons.append(f'Remained within {radius:.0f} m for {span:.0f} minutes at less than 2 kt.')
    if features['sharp_turn_count']>=3: score+=min(35,features['sharp_turn_count']*5); reasons.append('Repeated course changes greater than 60 degrees.')
    if features['track_straightness'] is not None and distance>1 and features['track_straightness']<.35: score+=20; reasons.append('Track displacement is small compared with distance travelled.')
    if len(speeds)>1 and speeds[0]-speeds[-1]>5: score+=20; reasons.append('Speed fell by more than 5 kt across the observation window.')
    return {**features,'anomaly_score':min(100,score),'model':'deterministic maritime feature rules',
        'reasons':reasons,'limitations':['Anomaly is not a probability of illegal fishing.','No learned baseline is claimed without adequate independent vessel history.']}
