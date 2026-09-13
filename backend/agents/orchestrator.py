"""Structured state-machine execution; traces describe actual executed functions."""
import time
from uuid import uuid4
from backend.services.storage import now

AGENTS=[
    ('orchestrator','Mission Orchestrator','Routes typed maritime events through mission state machines.'),
    ('green_route','Green Route','Searches a land-filtered graph for minimum estimated fuel.'),
    ('surveillance','Vessel Surveillance','Records and inspects real AIS observations and freshness.'),
    ('behaviour','Behaviour Analysis','Computes kinematic features and explainable trajectory anomalies.'),
    ('dark_vessel','Dark-Vessel Investigation','Assembles sourced historical and observed tracking evidence.'),
    ('identity','Identity & History','Resolves cached vessel identity and event history.'),
    ('jurisdiction','Jurisdiction','Tests points against available verified boundary polygons.'),
    ('environment','Ocean Environment','Resolves numerical current and wave forecasts.'),
    ('skeptic','Skeptic / Verification','Tests alternative explanations and identifies missing corroboration.'),
    ('debris','Debris Intelligence','Clusters real observations with haversine DBSCAN.'),
    ('drift','Debris Drift','Projects current advection with declared model uncertainty.'),
    ('fleet','Debris Fleet Coordinator','Matches simulated assets to hotspots under energy constraints.'),
    ('risk','Risk Fusion','Separates screening risk from evidence confidence.'),
    ('report','Response & Report','Persists evidence, assumptions and human-review recommendations.'),
]
STATE={i:{'id':i,'name':n,'role':r,'status':'IDLE','last_output':None,'execution_ms':None} for i,n,r in AGENTS}

# Each mission activates only the agents whose inputs are meaningful for that
# mission.  Keeping the scope explicit makes unrelated capabilities visible as
# skipped rather than silently implying that they contributed evidence.
MISSION_SCOPES={
    'investigation': {'orchestrator','surveillance','behaviour','dark_vessel','identity','jurisdiction','environment','skeptic','risk','report'},
    'route': {'orchestrator','green_route','environment','skeptic','report'},
    'cleanup': {'orchestrator','debris','environment','drift','fleet','report'},
}

class Workflow:
    def __init__(self,mission_type,event):
        started=time.perf_counter()
        self.id=mission_type+'-'+uuid4().hex[:10]; self.type=mission_type; self.trace=[]
        elapsed=(time.perf_counter()-started)*1000
        self.record('orchestrator',f'Accepted {event}.',{'event':event,'mission_id':self.id},elapsed=elapsed)
    def record(self,agent,message,output,elapsed=0):
        ms = max(0.1, round(elapsed, 2))
        state=STATE[agent]; state.update(status='COMPLETED',last_output=output,execution_ms=ms)
        entry={'agent':agent,'agent_name':state['name'],'timestamp':now(),'status':'COMPLETED','message':message,'output':output,'execution_ms':ms}
        self.trace.append(entry); return output
    def timed_record(self,agent,message,build_output):
        """Like record(), but times a callable that produces the output."""
        started=time.perf_counter()
        output=build_output() if callable(build_output) else build_output
        elapsed=(time.perf_counter()-started)*1000
        return self.record(agent,message,output,elapsed=elapsed)
    def run(self,agent,message,function,*args,**kwargs):
        started=time.perf_counter(); STATE[agent]['status']='RUNNING'
        try:
            output=function(*args,**kwargs)
        except Exception:
            STATE[agent]['status']='FAILED'; raise
        elapsed=(time.perf_counter()-started)*1000
        return self.record(agent,message,output,elapsed=elapsed)
    def skip_out_of_scope(self):
        """Record non-applicable agents without running them or inventing inputs."""
        scope=MISSION_SCOPES.get(self.type)
        if scope is None:return
        for agent,name,_ in AGENTS:
            if agent in scope or any(entry['agent']==agent for entry in self.trace):
                continue
            output={'mission_type':self.type,'status':'SKIPPED','reason':'Agent is outside this mission scope; no input was consumed.'}
            STATE[agent].update(status='SKIPPED',last_output=output,execution_ms=0.0)
            self.trace.append({'agent':agent,'agent_name':name,'timestamp':now(),'status':'SKIPPED',
                               'message':f'Outside {self.type} mission scope; not executed.',
                               'output':output,'execution_ms':0.0})
    def finish(self,result):
        self.skip_out_of_scope()
        started=time.perf_counter()
        report_output={'mission_id':self.id,'report_url':f'/api/reports/{self.id}'}
        elapsed=(time.perf_counter()-started)*1000
        self.record('report','Mission result prepared with source evidence and assumptions.',report_output,elapsed=elapsed)
        return {'id':self.id,'type':self.type,'created_at':now(),**result,'trace':self.trace,
                'execution_scope':sorted(MISSION_SCOPES.get(self.type, {entry['agent'] for entry in self.trace})),
                'report_url':f'/api/reports/{self.id}'}

def agent_states():return list(STATE.values())
