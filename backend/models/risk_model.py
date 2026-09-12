"""Auditable triage score, not a calibrated criminal probability."""
def fuse_risk(evidence,behaviour=None):
    weights={'gap':20,'loitering':12,'fishing':9,'encounter':8,'identity_inconsistency':10,'sar_candidate':8,'protected_area':8}
    contributors=[]
    grouped={}
    for item in evidence:
        kind=item.get('type','')
        if kind in weights:
            grouped[kind]=grouped.get(kind,0)+1
    for kind,count in grouped.items():
        value=weights[kind]+min(6,max(0,count-1)*2)
        contributors.append({'label':kind.replace('_',' ').title(),'points':value,'count':count})
    if behaviour and behaviour.get('samples',0)>=3 and behaviour.get('anomaly_score',0)>0:
        contributors.append({'label':'Observed trajectory anomaly','points':round(behaviour['anomaly_score']*.22,1),'count':behaviour['samples']})
    score=min(100,max(0,sum(c['points'] for c in contributors)))
    if evidence:
        confidence=min(90,round(sum(float(e.get('confidence',0)) for e in evidence)/len(evidence)*.68 + min(len(evidence),5)*3))
    else:
        confidence=0
    # Confidence describes completeness and provenance; a single provider does not provide independent corroboration.
    sources={e.get('source','') for e in evidence}
    if len(sources)<=1:
        confidence=min(confidence,62)
    return {'risk_score':round(score),'confidence_score':confidence,
        'risk_level':'HIGH' if score>=65 else 'ELEVATED' if score>=35 else 'LOW',
        'contributors':contributors,'methodology':'Weighted screening signals; no legal or calibrated probability interpretation. Confidence is limited by source independence and evidence completeness.'}
