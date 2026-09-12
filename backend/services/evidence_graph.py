def evidence_graph(vessel,evidence):
    nodes=[{'id':'vessel','label':vessel.get('name','Vessel'),'type':'vessel','source':vessel.get('source'),'confidence':None}]
    nodes.extend(evidence)
    edges=[{'source':'vessel','target':e['id'],'label':'supported by' if e.get('type')!='sar_candidate' else 'unconfirmed candidate'} for e in evidence]
    return {'nodes':nodes,'edges':edges}
