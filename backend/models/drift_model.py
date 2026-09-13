from backend.services.geospatial import project

def drift_forecast(latitude,longitude,environment,hours=6):
    environment=environment or {}
    metadata={key:environment.get(key) for key in ('forecast_status','coverage_label','requested_time','observation_time','observation_age_hours','coverage_start','coverage_end','current_available','waves_available') if key in environment}
    velocity=environment.get('current_speed_ms') if environment else None
    direction=environment.get('current_direction') if environment else None
    if velocity is None or direction is None:
        return {'points':[],'coordinates':[],'status':'CURRENT UNAVAILABLE',**metadata,'assumption':'No drift is projected without an available time-matched modelled current.'}
    steps=sorted(set([0,1,2,3,float(hours)]))
    steps=[h for h in steps if h<=hours]
    points=[]
    for hour in steps:
        lat,lon=project(latitude,longitude,max(0,float(velocity))*hour*3.6,float(direction))
        points.append({'hours':hour,'latitude':lat,'longitude':lon,'uncertainty_km':round(.25+hour*.35,2)})
    return {'points':points,'coordinates':[[p['longitude'],p['latitude']] for p in points],**metadata,
        'status':'MODEL FORECAST','current_speed_ms':velocity,'current_direction':direction,
        'source_timestamp':environment.get('timestamp'),'assumption':'Constant surface-current advection; uncertainty radius is an illustrative parameter, not a calibrated probability interval. Windage, tides, diffusion and sinking are not resolved.'}
