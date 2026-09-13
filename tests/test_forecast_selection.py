"""Forecast-valid-time, missing-data, and downstream physical-effect checks."""
from copy import deepcopy

import pytest
from shapely.geometry import Polygon

from backend.models.drift_model import drift_forecast
from backend.models.fuel_model import segment_estimate
from backend.services.forecast_environment import select_forecast
from backend.services.geospatial import LandMask
from backend.services.route_optimizer import nearest_environment, optimize_route


@pytest.fixture
def forecast():
    return {
        'latitude': 0, 'longitude': .5,
        'timestamp': '2026-01-01T00:15:00Z',
        'downloaded_at': '2026-01-01T00:20:00Z',
        'source': 'Test model fixture', 'provenance': 'MODEL FORECAST',
        # Deliberately different old snapshot values: these must never leak into hourly selection.
        'current_speed_ms': 9, 'current_direction': 270, 'wave_height': 9,
        'hourly': {
            'time': ['2026-01-01T00:00', '2026-01-01T01:00', '2026-01-01T02:00'],
            'ocean_current_velocity': [0, 3.6, 7.2],
            'ocean_current_direction': [90, 90, 90],
            'wave_height': [1, 1, 1], 'wave_direction': [270, 270, 270],
            'wave_period': [6, 7, 8],
        },
        'hourly_units': {'ocean_current_velocity': 'km/h'},
    }


def test_advancing_default_time_selects_actual_hourly_values_and_units(forecast):
    original = deepcopy(forecast)
    early = select_forecast(forecast, evaluated_at='2026-01-01T00:05:00Z')
    later = select_forecast(forecast, evaluated_at='2026-01-01T01:10:00Z')
    assert early['current_speed_ms'] == 0
    assert later['current_speed_ms'] == pytest.approx(1)
    assert later['observation_time'] == '2026-01-01T01:00:00Z'
    assert later['observation_age_hours'] == pytest.approx(1/6, abs=.001)
    assert later['wave_period'] == 7
    assert later['forecast_status'] == 'AVAILABLE'
    assert later['provenance'] == 'MODEL FORECAST'
    assert 'LIVE' not in later['coverage_label']
    assert forecast == original


def test_planned_time_respects_timezones_and_nearest_not_first_hour(forecast):
    sample = select_forecast(forecast, '2026-01-01T07:10:00+05:30', evaluated_at='2026-01-01T00:00Z')
    assert sample['requested_time'] == '2026-01-01T01:40:00Z'
    assert sample['observation_time'] == '2026-01-01T02:00:00Z'
    assert sample['current_speed_ms'] == pytest.approx(2)
    assert sample['observation_offset_hours'] == pytest.approx(1/3, abs=.001)


@pytest.mark.parametrize('when,status', [
    ('2025-12-31T23:59:00Z', 'NOT_YET_AVAILABLE'),
    ('2026-01-01T02:00:01Z', 'EXPIRED'),
])
def test_outside_time_coverage_does_not_extrapolate_or_fake_calm(forecast, when, status):
    selected = nearest_environment(0, .5, [forecast], planned_at=when)
    assert selected['forecast_status'] == status
    assert selected['coverage_start'] == '2026-01-01T00:00:00Z'
    assert selected['coverage_end'] == '2026-01-01T02:00:00Z'
    assert selected['current_speed_ms'] is None and selected['wave_height'] is None
    assert selected['environment_available'] is False
    assert drift_forecast(0, .5, selected)['points'] == []
    assert segment_estimate(12, 90, environment=selected)['fuel_t'] == segment_estimate(12, 90)['fuel_t']


def test_null_hourly_fields_do_not_inherit_old_snapshot_or_another_hour(forecast):
    forecast['hourly']['ocean_current_velocity'][1] = None
    forecast['hourly']['wave_height'][1] = None
    selected = select_forecast(forecast, '2026-01-01T01:00Z')
    assert selected['current_speed_ms'] is None
    assert selected['wave_height'] is None
    assert selected['forecast_status'] == 'MISSING_VALUES'
    assert selected['observation_time'] == '2026-01-01T01:00:00Z'
    assert selected['environment_available'] is False


def test_missing_direction_or_unknown_speed_unit_never_invents_current(forecast):
    forecast['hourly']['ocean_current_direction'][1] = None
    no_direction = select_forecast(forecast, '2026-01-01T01:00Z')
    assert no_direction['current_speed_ms'] is None
    assert no_direction['forecast_status'] == 'PARTIAL'
    assert no_direction['waves_available'] and not no_direction['current_available']
    forecast['hourly_units']['ocean_current_velocity'] = 'unknown'
    unknown_units = select_forecast(forecast, '2026-01-01T02:00Z')
    assert unknown_units['current_speed_ms'] is None
    assert unknown_units['wave_height'] == 1


def test_current_only_snapshots_expire_and_missing_timestamp_is_unusable():
    snapshot = {'timestamp': '2026-01-01T00:00Z', 'current_speed_ms': 1, 'current_direction': 90, 'wave_height': 1}
    assert select_forecast(snapshot, '2026-01-01T01:00Z')['complete_environment']
    assert select_forecast(snapshot, '2026-01-01T04:00Z')['forecast_status'] == 'EXPIRED'
    snapshot.pop('timestamp')
    assert select_forecast(snapshot, '2026-01-01T01:00Z')['current_speed_ms'] is None


def test_planning_time_changes_fuel_and_expired_metadata_does_not_count_as_coverage(forecast):
    # A remote obstacle creates a valid land mask while leaving this simple test route open.
    land = LandMask(Polygon([(8, 8), (9, 8), (9, 9), (8, 9)]))
    origin, destination = {'latitude': 0, 'longitude': 0}, {'latitude': 0, 'longitude': 1}
    early = optimize_route(origin, destination, [forecast], land=land, planned_at='2026-01-01T00:00Z')
    later = optimize_route(origin, destination, [forecast], land=land, planned_at='2026-01-01T02:00Z')
    expired = optimize_route(origin, destination, [forecast], land=land, planned_at='2026-01-02T00:00Z')
    assert later['baseline']['fuel_t'] < early['baseline']['fuel_t']
    assert later['baseline']['forecast_coverage_pct'] == 100
    assert later['baseline']['forecast']['observation_time_range'] == ['2026-01-01T02:00:00Z']*2
    assert expired['baseline']['forecast_coverage_pct'] == 0
    assert expired['baseline']['current_coverage_pct'] == 0
    assert expired['baseline']['wave_coverage_pct'] == 0
    assert set(expired['baseline']['forecast']['segment_status_counts']) == {'EXPIRED'}
