"""Transparent cubic speed fuel approximation; no vessel calibration is implied."""
import math

MS_TO_KNOTS=1.94384449
CO2_T_PER_FUEL_T=3.114  # HFO default conversion; configurable/calibration required.

def current_projection(speed_ms,direction,heading):
    return float(speed_ms or 0)*MS_TO_KNOTS*math.cos(math.radians(float(direction or 0)-heading))

def segment_estimate(distance_nm,heading,speed_knots=12,reference_fuel_tpd=24,environment=None,reference_speed=None):
    environment=environment or {}
    assistance=current_projection(environment.get('current_speed_ms'),environment.get('current_direction'),heading)
    ground_speed=max(1,speed_knots+assistance)
    wave_height=max(0,float(environment.get('wave_height') or 0))
    # Wave direction is where waves originate, unlike current direction (towards).
    wave_direction=environment.get('wave_direction')
    opposing=(1+math.cos(math.radians((float(wave_direction)-heading))))/2 if wave_direction is not None else 0.5
    wave_factor=1+0.035*wave_height**2*(0.4+0.6*opposing)
    hours=distance_nm/ground_speed
    speed_ratio=speed_knots/(reference_speed or speed_knots)
    fuel=reference_fuel_tpd/24*speed_ratio**3*wave_factor*hours
    return {'distance_nm':distance_nm,'duration_hours':hours,'fuel_t':fuel,'co2_t':fuel*CO2_T_PER_FUEL_T,
            'current_knots':assistance,'wave_height':wave_height,'speed_over_ground':ground_speed,'wave_factor':wave_factor}
