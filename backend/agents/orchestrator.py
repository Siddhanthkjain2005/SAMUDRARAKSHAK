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

class Workflow:
    def __init__(self,mission_type,event):
        self.id=mission_type+'-'+uuid4().hex[:10]; self.type=mission_type; self.trace=[]
        self.record('orchestrator',f'Accepted {event}.',{'event':event,'mission_id':self.id})
    def record(self,agent,message,output,elapsed=0):
        state=STATE[agent]; state.update(status='COMPLETED',last_output=output,execution_ms=round(elapsed,2))
        entry={'agent':agent,'agent_name':state['name'],'timestamp':now(),'status':'COMPLETED','message':message,'output':output,'execution_ms':round(elapsed,2)}
        self.trace.append(entry); return output
    def run(self,agent,message,function,*args,**kwargs):
        started=time.perf_counter(); STATE[agent]['status']='RUNNING'
        try:
            output=function(*args,**kwargs)
        except Exception:
            STATE[agent]['status']='FAILED'; raise
        return self.record(agent,message,output,(time.perf_counter()-started)*1000)
    def finish(self,result):
        self.record('report','Mission result prepared with source evidence and assumptions.',{'mission_id':self.id,'report_url':f'/api/reports/{self.id}'})
        return {'id':self.id,'type':self.type,'created_at':now(),**result,'trace':self.trace,'report_url':f'/api/reports/{self.id}'}

def agent_states():return list(STATE.values())
