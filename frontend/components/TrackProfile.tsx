'use client';
import {Area,AreaChart,ResponsiveContainer,Tooltip,XAxis,YAxis} from 'recharts';
import {type Vessel,sourceTimeLabel} from '../lib/types';

export default function TrackProfile({vessel}:{vessel:Vessel}){
  let points=(vessel.track||[]).filter(p=>!Array.isArray(p)&&Number.isFinite(p.speed??p.sog)).map(p=>({time:p.timestamp,speed:Number(p.speed??p.sog)}));
  if(points.length===1){
    points=[{...points[0],time:points[0].time||'Start'},{...points[0],time:points[0].time||'Current'}];
  } else if(points.length===0 && Number.isFinite(vessel.speed)){
    points=[{time:vessel.timestamp||'Start',speed:Number(vessel.speed)},{time:vessel.timestamp||'Current',speed:Number(vessel.speed)}];
  }
  if(points.length<2)return null;
  return <section className="track-profile" aria-label="Observed vessel speed history">
    <div className="panel-heading"><span>OBSERVED SPEED · KNOTS</span><span>{points.length} POINTS</span></div>
    <ResponsiveContainer width="100%" height={106}>
      <AreaChart data={points} margin={{top:5,right:6,left:-32,bottom:0}}>
        <defs><linearGradient id="speed-fill" x1="0" y1="0" x2="0" y2="1"><stop stopColor="#79e8c5" stopOpacity={.25}/><stop offset="1" stopColor="#79e8c5" stopOpacity={0}/></linearGradient></defs>
        <XAxis dataKey="time" hide/><YAxis domain={[0, (max: number) => Math.max(5, Math.ceil(max * 1.2))]} tick={{fontSize:8,fill:'#8ca8ac'}} axisLine={false} tickLine={false} width={48}/>
        <Tooltip contentStyle={{background:'#102931',border:'1px solid #42625e',fontSize:10,borderRadius:5}} labelFormatter={value=>sourceTimeLabel(String(value))} formatter={(value:number)=>[`${Number(value).toFixed(1)} kn`,'Observed speed']}/>
        <Area type="linear" dataKey="speed" stroke="#79e8c5" strokeWidth={1.5} fill="url(#speed-fill)" isAnimationActive={false}/>
      </AreaChart>
    </ResponsiveContainer>
    <small>Original AIS observations · {vessel.source||'Global Fishing Watch'}</small>
  </section>
}
