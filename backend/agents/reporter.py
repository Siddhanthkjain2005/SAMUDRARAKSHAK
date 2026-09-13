import html
import json

def render_report(mission):
    name={'route':'Green Route Report','investigation':'Vessel Investigation Report','cleanup':'Marine Cleanup Mission Report'}.get(mission['type'],'Mission Report')
    trace=mission.get('trace',[])
    findings=''.join(f"<tr><td>{html.escape(t['agent_name'])}</td><td><b class=\"status-{html.escape(str(t.get('status','COMPLETED')).lower())}\">{html.escape(str(t.get('status','COMPLETED')))}</b> {html.escape(t['message'])}</td><td>{t.get('execution_ms',0):.1f} ms</td></tr>" for t in trace)
    assumptions=''.join(f'<li>{html.escape(str(a))}</li>' for a in mission.get('assumptions',[]))
    coords=mission.get('optimized',{}).get('coordinates',[])
    if not coords:
        coords=[p for a in mission.get('assignments',[]) for p in a.get('coordinates',[])]
    visual=''
    if coords:
        xs=[p[0] for p in coords];ys=[p[1] for p in coords]
        xmin,xmax,ymin,ymax=min(xs),max(xs),min(ys),max(ys)
        points=' '.join(f'{30+(p[0]-xmin)/max(xmax-xmin,.01)*680:.1f},{270-(p[1]-ymin)/max(ymax-ymin,.01)*240:.1f}' for p in coords)
        visual=f'<svg viewBox="0 0 740 300" role="img" aria-label="Computed mission geometry"><rect width="740" height="300" fill="#102a3a"/><polyline points="{points}" fill="none" stroke="#36cfc1" stroke-width="3"/></svg><p class="muted">Computed mission geometry, schematic coordinate projection; not a navigational chart.</p>'
    compact={k:v for k,v in mission.items() if k not in ('trace','vessel')}
    payload=html.escape(json.dumps(compact,indent=2,ensure_ascii=False))
    return f'''<!doctype html><html><head><meta charset="utf-8"><title>{name}</title><style>
    body{{font:15px/1.6 system-ui;color:#152b3c;max-width:960px;margin:48px auto;padding:0 30px}}h1{{font-size:32px}}h2{{margin-top:32px}}.eyebrow{{letter-spacing:3px;color:#087d75}}.muted{{color:#526979;font-size:12px}}table{{border-collapse:collapse;width:100%}}td,th{{text-align:left;border-bottom:1px solid #dce5e9;padding:10px}}pre{{font-size:11px;white-space:pre-wrap;background:#f0f5f7;padding:20px;overflow-wrap:anywhere}}button{{padding:10px 18px;background:#087d75;color:white;border:0;border-radius:8px}}@media print{{button{{display:none}}body{{margin:0}}pre{{font-size:9px}}}}</style></head><body>
    <div class="eyebrow">SAMUDRARAKSHAK AI</div><h1>{name}</h1><p>{html.escape(mission['id'])} · {html.escape(mission.get('created_at',''))}</p><button onclick="window.print()">Print / Save PDF</button>
    {visual}<h2>Decision</h2><p>{html.escape(mission.get('explanation',mission.get('recommendation',str(mission.get('summary','')))))}</p>
    <h2>Agent findings</h2><table><thead><tr><th>Agent</th><th>Finding</th><th>Execution</th></tr></thead><tbody>{findings}</tbody></table>
    <h2>Assumptions and limitations</h2><ul>{assumptions}</ul><h2>Evidence and reproducible output</h2><pre>{payload}</pre>
    <p class="muted">Decision-support prototype. Maritime activity classifications require human verification. No autonomous enforcement or real collector operation is performed.</p></body></html>'''
