"""Auditable triage score, not a calibrated criminal probability."""
from backend.models.behaviour_model import parse_time

def evidence_completeness(item):
    """Reproducible metadata completeness, never a probability of illegality."""
    components=[
        {'label':'Named source','points':15 if item.get('source') and item['source'] not in ('UNATTRIBUTED EVENT','SOURCE UNAVAILABLE') else 0},
        {'label':'Parseable original timestamp','points':15 if parse_time(item.get('timestamp')) else 0},
        {'label':'Original source observation retained','points':25 if item.get('raw') is not None and item.get('raw') != '' else 0},
        {'label':'Source URL retained','points':10 if item.get('source_url') else 0},
        {'label':'Vessel identifier linkage retained','points':10 if item.get('vessel_id') else 0},
    ]
    identity=item.get('identity_fields') or {}
    if identity:
        available=sum(identity.get(field) is not None and identity.get(field) != '' for field in ('mmsi','name','imo','callsign','type','heading'))
        components.append({'label':'Identity metadata completeness','points':round(15*available/max(1, sum(1 for f in ('mmsi','name','imo','callsign','type','heading') if f in identity)),1)})
    coverage=item.get('coverage') or {}
    if coverage:
        samples=float(coverage.get('samples') or 0)
        duration=float(coverage.get('duration_minutes') or 0)
        components.append({'label':'Temporal observation coverage','points':round(15*min(1,max(samples/6,duration/30)),1)})
    return {'confidence':sum(c['points'] for c in components),'confidence_components':components,
        'confidence_methodology':'Metadata completeness index from source, timestamp, raw observation, URL, vessel linkage, identity fields and temporal coverage; not a calibrated probability of observation accuracy or illegality.'}

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
        # The behaviour score is already a composite of speed, course, dwell and
        # straightness signals. Keep the multiplier explicit and bounded so the
        # result is a triage index rather than a calibrated legal probability.
        points=round(min(40,float(behaviour['anomaly_score'])*.35),1)
        contributors.append({'label':'Observed trajectory anomaly','points':points,'count':behaviour['samples'],
            'signals':{'loitering':behaviour.get('loitering'),'sharp_turn_count':behaviour.get('sharp_turn_count'),
                       'track_straightness':behaviour.get('track_straightness'),'speed_drop':round((behaviour.get('speed_mean') or 0)-(behaviour.get('current_speed') or 0),2),
                       'duration_minutes':behaviour.get('duration_minutes')}})
    score=min(100,max(0,sum(c['points'] for c in contributors)))
    if evidence:
        mean_completeness=sum(float(e.get('confidence',0)) for e in evidence)/len(evidence)
        sources={e.get('source','') for e in evidence if e.get('source')}
        source_bonus=min(8, max(0, len(sources)-1)*4)
        confidence=min(94, max(0, round(mean_completeness * 0.98 + min(len(evidence), 5) * 1.5 + source_bonus)))
    else:
        confidence=0
    # Confidence describes completeness and provenance; source diversity adds a
    # small explicit bonus but never turns one provider into independent proof.
    sources={e.get('source','') for e in evidence if e.get('source')}
    return {'risk_score':round(score),'confidence_score':confidence,
        'risk_level':'HIGH' if score>=65 else 'ELEVATED' if score>=35 else 'LOW',
        'contributors':contributors,'methodology':'Weighted screening signals plus a bounded observed-trajectory contribution; no legal or calibrated probability interpretation.',
        'confidence_methodology':'Mean evidence metadata completeness × 0.98, plus 1.5 per evidence item (up to 5), plus 4 per additional named source (up to 8), capped at 94. This is not a calibrated probability of illegal activity.',
        'source_count':len(sources)}
