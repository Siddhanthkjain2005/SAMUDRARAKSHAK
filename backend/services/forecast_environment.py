"""Select actual cached model values by valid time, keeping absence and expiry explicit."""
from datetime import datetime, timezone
import math


FIELDS = {
    'current_speed_ms': 'ocean_current_velocity',
    'current_direction': 'ocean_current_direction',
    'wave_height': 'wave_height',
    'wave_direction': 'wave_direction',
    'wave_period': 'wave_period',
    'sea_surface_temperature': 'sea_surface_temperature',
    'sea_level_height_msl': 'sea_level_height_msl',
    'swell_wave_height': 'swell_wave_height',
    'wind_wave_height': 'wind_wave_height',
}
SPEED_FACTORS = {'km/h': 1/3.6, 'm/s': 1, 'kn': .514444, 'knots': .514444, 'mph': .44704}


def utc_time(value=None):
    """Open-Meteo's timezone-less cache strings are UTC, as requested on acquisition."""
    if value is None:
        return datetime.now(timezone.utc)
    result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)


def iso(value):
    return value.isoformat().replace('+00:00', 'Z') if value else None


def numeric(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _timestamp(value):
    if not value:
        return None
    try:
        return utc_time(value)
    except (ValueError, TypeError, OverflowError):
        return None


def select_forecast(sample, planned_at=None, *, evaluated_at=None, max_snapshot_age_hours=3):
    """Pick the nearest valid-time row; never carry old current fields across hourly nulls.

    Hourly coverage ends at its final supplied timestamp; no temporal extrapolation is
    performed. A current-only response is usable for at most three hours around its
    actual timestamp. Future/past planning beyond that window requires hourly data.
    """
    now = utc_time(evaluated_at)
    requested = utc_time(planned_at) if planned_at is not None else now
    result = {key: value for key, value in sample.items() if key not in ('hourly', 'hourly_units')}
    result.update({key: None for key in FIELDS})
    downloaded = _timestamp(sample.get('downloaded_at'))
    result.update(provenance='MODEL FORECAST', requested_time=iso(requested), observation_time=None,
                  timestamp=None, observation_age_hours=None, observation_offset_hours=None,
                  cache_age_hours=round(max(0, (now-downloaded).total_seconds()/3600), 3) if downloaded else None,
                  coverage_start=None, coverage_end=None, forecast_status='UNAVAILABLE',
                  coverage_label='FORECAST UNAVAILABLE', environment_available=False,
                  current_available=False, waves_available=False, complete_environment=False)
    hourly = sample.get('hourly') or {}
    times = [(i, _timestamp(value)) for i, value in enumerate(hourly.get('time', []))]
    times = [(i, value) for i, value in times if value is not None]
    selected = None
    if times:
        first, last = min(t for _, t in times), max(t for _, t in times)
        result.update(coverage_start=iso(first), coverage_end=iso(last), forecast_resolution='HOURLY')
        if requested < first or requested > last:
            result.update(forecast_status='NOT_YET_AVAILABLE' if requested < first else 'EXPIRED',
                          coverage_label='OUTSIDE FORECAST COVERAGE — NO CONDITIONS APPLIED')
            return result
        index, selected = min(times, key=lambda pair: (abs((pair[1]-requested).total_seconds()), pair[1]))
        units = sample.get('hourly_units') or {}
        for normalized, original in FIELDS.items():
            values = hourly.get(original) or []
            value = numeric(values[index]) if index < len(values) else None
            if normalized == 'current_speed_ms':
                factor = SPEED_FACTORS.get(units.get(original))
                value = value*factor if value is not None and factor is not None else None
            result[normalized] = value
        result['original_current_speed'] = (hourly.get('ocean_current_velocity') or [])[index] if index < len(hourly.get('ocean_current_velocity') or []) else None
        result['original_current_speed_unit'] = units.get('ocean_current_velocity')
    elif hourly.get('time'):
        # A malformed time series must not silently degrade to unrelated snapshot data.
        result['coverage_label'] = 'INVALID FORECAST TIMES — NO CONDITIONS APPLIED'
        return result
    else:
        selected = _timestamp(sample.get('timestamp'))
        result.update(forecast_resolution='SNAPSHOT', coverage_start=iso(selected), coverage_end=iso(selected))
        if selected is None:
            return result
        offset = (requested-selected).total_seconds()/3600
        if abs(offset) > max_snapshot_age_hours:
            result.update(forecast_status='EXPIRED' if offset > 0 else 'NOT_YET_AVAILABLE',
                          coverage_label='OUTSIDE SNAPSHOT VALIDITY — NO CONDITIONS APPLIED')
            return result
        result.update({key: numeric(sample.get(key)) for key in FIELDS})
    result.update(timestamp=iso(selected), observation_time=iso(selected),
                  observation_age_hours=round(max(0, (now-selected).total_seconds()/3600), 3),
                  observation_offset_hours=round((selected-requested).total_seconds()/3600, 3))
    for key in ('current_direction', 'wave_direction'):
        if result[key] is not None and not 0 <= result[key] <= 360:
            result[key] = None
    for key in ('current_speed_ms', 'wave_height', 'wave_period', 'swell_wave_height', 'wind_wave_height'):
        if result[key] is not None and result[key] < 0:
            result[key] = None
    # Missing direction must not become an assumed northerly current in the fuel engine.
    if result['current_direction'] is None and result['current_speed_ms'] != 0:
        result['current_speed_ms'] = None
    current = result['current_speed_ms'] is not None and (result['current_direction'] is not None or result['current_speed_ms'] == 0)
    waves = result['wave_height'] is not None
    status = 'AVAILABLE' if current and waves else 'PARTIAL' if current or waves else 'MISSING_VALUES'
    result.update(current_available=current, waves_available=waves, complete_environment=current and waves,
                  environment_available=current or waves, forecast_status=status,
                  coverage_label={'AVAILABLE': 'MODEL FORECAST — CURRENT AND WAVES',
                                  'PARTIAL': 'PARTIAL MODEL FORECAST — MISSING FIELDS NOT APPLIED',
                                  'MISSING_VALUES': 'MODEL FORECAST — CONDITIONS MISSING'}[status])
    return result
