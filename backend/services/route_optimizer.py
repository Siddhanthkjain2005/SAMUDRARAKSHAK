import heapq
import math
from collections import defaultdict
from backend.services.geospatial import get_land_mask,haversine,bearing
from backend.models.fuel_model import segment_estimate
from backend.services.forecast_environment import select_forecast,utc_time,iso

class RouteUnavailable(ValueError):
    pass

def nearest_environment(lat,lon,marine,max_distance_km=600,planned_at=None):
    valid=[x for x in marine if x.get('latitude') is not None and x.get('longitude') is not None]
    if not valid:
        return {}
    item=min(valid,key=lambda m:haversine((lat,lon),(m['latitude'],m['longitude'])))
    distance=haversine((lat,lon),(item['latitude'],item['longitude']))
    return {**select_forecast(item,planned_at),'sample_distance_km':round(distance,1)} if distance<=max_distance_km else {}

def optimize_route(origin,destination,marine,speed_knots=12,reference_fuel_tpd=24,safety_buffer_km=1,land=None,planned_at=None):
    forecast_reference=utc_time(planned_at)
    supplied_land=land is not None
    land=land or get_land_mask(safety_buffer_km)
    if land is None:
        raise RouteUnavailable('A coastline land polygon is required. Run data acquisition before routing.')
    a=(float(origin['latitude']),float(origin['longitude'])); b=(float(destination['latitude']),float(destination['longitude']))
    if not supplied_land and not all(-3<=p[0]<=28 and 57<=p[1]<=98 for p in (a,b)):
        raise RouteUnavailable('The downloaded routing coastline covers the Indian Ocean region only. Choose regional ports; acquire validated coastline coverage before routing elsewhere.')
    if haversine(a,b)<3:
        raise RouteUnavailable('Choose two distinct ports at least 3 km apart.')
    if haversine(a,b)>3500:
        raise RouteUnavailable('This regional routing graph supports port pairs up to 3,500 km apart.')
    pad=1.7
    minlat,maxlat=min(a[0],b[0])-pad,max(a[0],b[0])+pad
    minlon,maxlon=min(a[1],b[1])-pad,max(a[1],b[1])+pad
    step=max(.10,(maxlat-minlat)/115,(maxlon-minlon)/115)
    rows,cols=math.ceil((maxlat-minlat)/step),math.ceil((maxlon-minlon)/step)
    nodes={}
    for y in range(rows+1):
        for x in range(cols+1):
            p=(minlat+y*step,minlon+x*step)
            if not land.is_land(*p):
                nodes[(y,x)]=p
    if not nodes:
        raise RouteUnavailable('No navigable water nodes in this regional graph.')
    start=min(nodes,key=lambda n:haversine(a,nodes[n])); end=min(nodes,key=lambda n:haversine(b,nodes[n]))
    if haversine(a,nodes[start])>80 or haversine(b,nodes[end])>80:
        raise RouteUnavailable('A port could not be connected to the offshore grid within 80 km.')
    offsets=[(dy,dx) for dy in range(-2,3) for dx in range(-2,3) if (dy or dx) and math.gcd(abs(dy),abs(dx))==1]
    edge_cache={}; rejected=set(); environment_cache={}; visited=set()
    def neighbors(node):
        for dy,dx in offsets:
            other=(node[0]+dy,node[1]+dx)
            if other not in nodes or (node,other) in rejected:
                continue
            key=(node,other)
            if key not in edge_cache:
                p,q=nodes[node],nodes[other]
                if land.intersects(p,q):
                    rejected.add(key); rejected.add((other,node)); continue
                midpoint=((p[0]+q[0])/2,(p[1]+q[1])/2)
                envkey=(round(midpoint[0],1),round(midpoint[1],1))
                if envkey not in environment_cache:
                    environment_cache[envkey]=nearest_environment(*midpoint,marine,planned_at=forecast_reference)
                estimate=segment_estimate(haversine(p,q)/1.852,bearing(p,q),speed_knots,reference_fuel_tpd,environment_cache[envkey])
                env=environment_cache[envkey]
                estimate['environment_available']=env.get('complete_environment',False)
                estimate['current_available']=env.get('current_available',False)
                estimate['waves_available']=env.get('waves_available',False)
                estimate['forecast_status']=env.get('forecast_status','UNAVAILABLE')
                estimate['observation_time']=env.get('observation_time')
                estimate['observation_age_hours']=env.get('observation_age_hours')
                edge_cache[key]=estimate
            yield other,edge_cache[key]
    def search(cost):
        # Dijkstra is used for fuel so changing currents cannot invalidate a heuristic.
        costs={start:0}; previous={}; queue=[(0,start)]; closed=set()
        while queue:
            value,node=heapq.heappop(queue)
            if node in closed: continue
            closed.add(node); visited.add(node)
            if node==end:
                path=[end]
                while path[-1]!=start: path.append(previous[path[-1]])
                return path[::-1]
            for nxt,estimate in neighbors(node):
                proposed=value+estimate[cost]
                if proposed<costs.get(nxt,float('inf')):
                    costs[nxt]=proposed; previous[nxt]=node; heapq.heappush(queue,(proposed,nxt))
        raise RouteUnavailable('No land-clear connection was found. Try a regional port pair or reduce the safety buffer.')
    baseline_path=search('distance_nm'); optimized_path=search('fuel_t')
    def summarize(path):
        segments=[edge_cache[(x,y)] for x,y in zip(path,path[1:])]
        totals={key:sum(s[key] for s in segments) for key in ('distance_nm','duration_hours','fuel_t','co2_t')}
        distance=totals['distance_nm']
        statuses=defaultdict(int)
        for segment in segments:statuses[segment['forecast_status']]+=1
        observation_times=sorted(s['observation_time'] for s in segments if s['observation_time'])
        ages=[s['observation_age_hours'] for s in segments if s['observation_age_hours'] is not None]
        return {**{k:round(v,3) for k,v in totals.items()},'coordinates':[[nodes[n][1],nodes[n][0]] for n in path],
            'mean_current_knots':round(sum(s['current_knots']*s['distance_nm'] for s in segments)/max(distance,.001),3),
            'mean_wave_height':round(sum(s['wave_height']*s['distance_nm'] for s in segments)/max(distance,.001),3),
            'forecast_coverage_pct':round(100*sum(s['distance_nm'] for s in segments if s['environment_available'])/max(distance,.001),1),
            'current_coverage_pct':round(100*sum(s['distance_nm'] for s in segments if s['current_available'])/max(distance,.001),1),
            'wave_coverage_pct':round(100*sum(s['distance_nm'] for s in segments if s['waves_available'])/max(distance,.001),1),
            'forecast':{'provenance':'MODEL FORECAST','requested_time':iso(forecast_reference),
                'selection':'Nearest hourly conditions at requested planning time; fixed for the route calculation.',
                'coverage_label':'Complete current-and-wave coverage' if segments and all(s['environment_available'] for s in segments) else 'Incomplete or unavailable model coverage; missing effects are not applied',
                'observation_time_range':[observation_times[0],observation_times[-1]] if observation_times else [],
                'maximum_observation_age_hours':max(ages) if ages else None,'segment_status_counts':dict(statuses)},
            'land_intersections':0,'segments':len(segments),'speed_knots':speed_knots}
    baseline,optimized=summarize(baseline_path),summarize(optimized_path)
    fuel_saved=max(0,baseline['fuel_t']-optimized['fuel_t'])
    savings={'fuel_t':round(fuel_saved,3),'fuel_pct':round(100*fuel_saved/max(baseline['fuel_t'],.0001),2),
        'co2_t':round(baseline['co2_t']-optimized['co2_t'],3),'distance_nm':round(baseline['distance_nm']-optimized['distance_nm'],2),
        'eta_minutes':round((optimized['duration_hours']-baseline['duration_hours'])*60,1)}
    return {'baseline':baseline,'optimized':optimized,'savings':savings,'forecast_reference_time':iso(forecast_reference),
        'origin':origin,'destination':destination,'candidates':[{'coordinates':baseline['coordinates'],'objective':'shortest distance'},{'coordinates':optimized['coordinates'],'objective':'minimum estimated fuel'}],
        'graph':{'water_nodes':len(nodes),'evaluated_nodes':len(visited),'evaluated_edges':len(edge_cache),'land_rejected_edges':len(rejected),'grid_degrees':step},
        'port_access':{'origin_offshore_distance_km':round(haversine(a,nodes[start]),2),'destination_offshore_distance_km':round(haversine(b,nodes[end]),2)},
        'explanation':f"The fuel-cost graph estimates {savings['fuel_pct']:.2f}% less fuel than the shortest-distance route at the same {speed_knots:g} kt speed through water. Mean projected current assistance is {optimized['mean_current_knots']:+.2f} kt; mean waves are {optimized['mean_wave_height']:.2f} m. Arrival changes by {savings['eta_minutes']:+.1f} minutes.",
        'assumptions':['AI fuel-efficiency decision support — not a certified navigational route.',
            f'Port coordinates are snapped to offshore grid nodes; harbour approaches are excluded. Land buffer is approximately {safety_buffer_km:g} km.',
            'Natural Earth coastline is generalized. Bathymetry, traffic separation, charted hazards, weather evolution and dynamic closures are not navigationally validated.',
            'Fuel uses a cubic speed law and an illustrative wave-resistance term. Reference burn is supplied by the operator. CO2 uses the default HFO factor 3.114 t/t.',
            'Nearest hourly model forecast within 600 km is selected at the requested planning time (current UTC by default). This time snapshot is fixed across the voyage; weather evolution along the route is not modeled.',
            'Expired forecasts and missing fields are not applied. Missing effects use the zero-current/calm-water baseline, not a claim of measured calm conditions. Current and wave coverage are reported separately.',
            'Routes use the same requested speed through water. Zero saving is a valid result. Protected-area/legal avoidance is not claimed without verified local geometry.']}
