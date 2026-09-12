import math
import numpy as np
from scipy.optimize import linear_sum_assignment
from backend.agents.orchestrator import Workflow
from backend.agents.debris_intelligence import cluster_debris
from backend.models.drift_model import drift_forecast
from backend.services.route_optimizer import nearest_environment
from backend.services.geospatial import haversine,project,get_land_mask

def create_collectors(hotspots,count):
    collectors=[]; land=get_land_mask(0)
    for i in range(count):
        hot=hotspots[i%len(hotspots)]
        lat,lon=project(hot['latitude'],hot['longitude'],12+i*3,235)
        if land and land.is_land(lat,lon):
            for direction in range(0,360,30):
                a,b=project(hot['latitude'],hot['longitude'],20,direction)
                if not land.is_land(a,b):lat,lon=a,b;break
        collectors.append({'id':f'collector-{i+1}','name':f'Collector {chr(65+i)}','latitude':lat,'longitude':lon,
            'battery':92-i*8,'speed_knots':8,'capacity_kg':75,'remaining_capacity_kg':75,'state':'READY',
            'provenance':'SIMULATED ASSET','energy_pct_per_hour':8,'battery_reserve_pct':20})
    return collectors

def assign_collectors(collectors,hotspots,drifts,hours=6,wave_warning=False):
    if not collectors or not hotspots:return [],{'assigned':0,'unassigned_hotspots':len(hotspots),'travel_nm':0,'travel_saved_nm':0}
    costs=np.full((len(collectors),len(hotspots)),1e9); details={}; land=get_land_mask(0)
    for i,collector in enumerate(collectors):
        if collector['battery']<=collector.get('battery_reserve_pct',20):continue
        for j,hotspot in enumerate(hotspots):
            drift=next((d for d in drifts if d['hotspot_id']==hotspot['id']),{})
            projected=drift.get('points',[])
            # Start with current centroid and estimate the target at predicted arrival, avoiding full-horizon overshoot.
            target=(hotspot['latitude'],hotspot['longitude'])
            distance=haversine((collector['latitude'],collector['longitude']),target)/1.852
            eta=distance/collector['speed_knots']
            if projected:
                point=min(projected,key=lambda p:abs(p['hours']-eta));target=(point['latitude'],point['longitude'])
            distance=haversine((collector['latitude'],collector['longitude']),target)/1.852
            eta=distance/(collector['speed_knots']*(.65 if wave_warning else 1))
            needed=eta*2*collector.get('energy_pct_per_hour',8)+collector.get('battery_reserve_pct',20)
            if needed>collector['battery'] or eta>hours or collector.get('remaining_capacity_kg',0)<=0:continue
            start=(collector['latitude'],collector['longitude'])
            # Direct routes crossing land are ineligible; no impossible collector motion is animated.
            if land and land.intersects(start,target):continue
            costs[i,j]=distance/(.3+hotspot['priority']/100)*(1+(.4 if wave_warning else 0))
            details[i,j]={'collector_id':collector['id'],'hotspot_id':hotspot['id'],
                'coordinates':[[start[1],start[0]],[target[1],target[0]]],
                'eta_hours':round(eta,3),'distance_nm':round(distance,3),'battery_required_pct':round(needed,1),
                'mission_type':hotspot.get('mission_type','SURVEY / VALIDATION'),'estimated_collected_kg':None,'provenance':'COMPUTED · SIMULATED ASSET'}
    rows,cols=linear_sum_assignment(costs)
    assignments=[details[i,j] for i,j in zip(rows,cols) if (i,j) in details]
    # Compare feasible complete greedy matching against exact matching on the same weighted objective.
    available=set(range(len(hotspots))); greedy=[]
    for i in range(len(collectors)):
        feasible=[j for j in available if (i,j) in details]
        if feasible:
            j=min(feasible,key=lambda j:costs[i,j]);greedy.append(details[i,j]);available.remove(j)
    travel=sum(x['distance_nm'] for x in assignments)
    comparable=len(greedy)==len(assignments)
    saved=sum(x['distance_nm'] for x in greedy)-travel if comparable else 0
    return assignments,{'assigned':len(assignments),'unassigned_hotspots':len(hotspots)-len(assignments),
        'travel_nm':round(travel,2),'travel_saved_nm':round(saved,2),'comparison':'Feasible greedy matching, same assignment count' if comparable else 'No comparable feasible baseline',
        'objective':'Minimum distance / priority weighted matching with round-trip energy reserve','estimated_collected_kg':None}

def cleanup_plan(observations,marine,hours=6,count=3,previous=None,event=None,collector_id=None):
    workflow=Workflow('cleanup',event or 'NEW_DEBRIS_OBSERVATION')
    hotspots=workflow.run('debris','Clustered validated real observations using spatial DBSCAN.',cluster_debris,observations)
    # Show regional deployments first. These are real historical observation groups.
    region=[h for h in hotspots if 5<=h['latitude']<=25 and 58<=h['longitude']<=90]
    selected=(region or hotspots)[:max(3,count)]
    workflow.record('environment','Resolved cached current fields near observation clusters.',{'forecast_samples':len(marine),'hotspots':len(selected)})
    drifts=workflow.run('drift','Projected constant-current advection with explicit uncertainty.',lambda:[{'hotspot_id':h['id'],**drift_forecast(h['latitude'],h['longitude'],nearest_environment(h['latitude'],h['longitude'],marine),hours)} for h in selected])
    if not selected:
        return workflow.finish({'hotspots':[],'collectors':[],'assignments':[],'drift':[],'summary':{'assigned':0,'travel_nm':0,'travel_saved_nm':0},'assumptions':['No eligible real debris observations were loaded.']})
    collectors=[dict(c) for c in previous.get('collectors',[])] if previous else create_collectors(selected,count)
    if event=='battery_drop' and collectors:
        target=next((c for c in collectors if c['id']==collector_id),collectors[0]);target.update(battery=14,state='RETURN / HOLD')
        workflow.record('orchestrator','Detected simulated battery reserve violation and requested reassignment.',{'event':'COLLECTOR_LOW_BATTERY','collector_id':target['id'],'battery':14,'provenance':'SIMULATED EVENT'})
    if event=='new_debris_report':
        # A demo trigger reprocesses existing authentic observations; it does not fabricate a real report.
        workflow.record('orchestrator','Simulated report trigger re-evaluated existing real observation clusters.',{'event':'NEW_DEBRIS_OBSERVATION','provenance':'SIMULATED EVENT','new_real_observation_inserted':False})
    assignments,summary=workflow.run('fleet','Solved constrained minimum-cost fleet matching.',assign_collectors,collectors,selected,drifts,hours,event=='wave_warning')
    assigned_ids={a['collector_id'] for a in assignments}
    for c in collectors:
        if c['id'] in assigned_ids:c['state']='TRANSIT'
        elif c['battery']>20:c['state']='STANDBY'
    return workflow.finish({'hotspots':selected,'collectors':collectors,'assignments':assignments,'drift':drifts,
        'summary':summary,'hours':hours,'event':event,'previous_mission_id':previous.get('id') if previous else None,
        'previous_assignments':previous.get('assignments',[]) if previous else [],
        'assumptions':['All collector vessels, batteries, capacity and mission execution are simulated assets.',
            'Historical microplastic observations define survey and validation targets, not confirmed present-day recoverable floating litter.',
            'Reported concentrations are never converted into debris mass or kilograms collected. No cleanup outcome is claimed.',
            'Constant-current drift is illustrative model output; no windage, sinking or validated historical-time hydrodynamics.',
            'Direct collector segments intersecting cached land are rejected. Routes are not certified for navigation.',
            'Assignment includes estimated outbound/return energy and a 20% reserve; capacity is a simulated asset constraint.']})
