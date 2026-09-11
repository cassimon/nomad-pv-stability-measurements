import math

import numpy as np
import pytest

from nomad_pv_stability_measurements.schema_packages.timeline import ProtocolTimeline

COLUMNS = ['time', 'target_index', 'state_index', 'value', 'path_index']
LOOKUPS = ['targets', 'target_units', 'state_labels', 'paths']


def small_timeline():
    # chuck_T holds 65 °C from t = 0; bias tracks MPP for 24 h, then sweeps.
    return ProtocolTimeline(
        source='simulated',
        estimated=False,
        truncated=False,
        downsampled=False,
        total_duration=24.01,
        n_points=3,
        time=[0.0, 0.0, 86400.0],
        target_index=[0, 1, 1],
        state_index=[0, 1, 2],
        value=[338.15, math.nan, -0.2],
        path_index=[0, 1, 2],
        targets=['chuck_T.temperature', 'bias.voltage'],
        target_units=['K', 'V'],
        state_labels=['hold', 'track mpp', 'sweep'],
        paths=[
            'light soak/chuck_T: hold 65 °C',
            'light soak/daily cycle[0]/bias: track mpp',
            'light soak/daily cycle[0]/bias: sweep voltage',
        ],
    )


@pytest.mark.parametrize('name', COLUMNS + LOOKUPS + ['messages'])
def test_arrays_are_one_dimensional(name):
    assert ProtocolTimeline.m_def.all_quantities[name].shape == ['*']


def test_units():
    quantities = ProtocolTimeline.m_def.all_quantities
    assert str(quantities['time'].unit) == 'second'
    assert str(quantities['total_duration'].unit) == 'hour'
    assert quantities['value'].unit is None  # canonical unit per target instead


def test_source_is_simulated_or_logged():
    assert ProtocolTimeline(source='logged').source == 'logged'
    with pytest.raises(ValueError):
        ProtocolTimeline(source='guessed')


def test_columns_index_into_the_lookup_tables():
    timeline = small_timeline()
    np.testing.assert_allclose(timeline.time.to('hour').magnitude, [0, 0, 24])
    event = 2
    assert timeline.targets[timeline.target_index[event]] == 'bias.voltage'
    assert timeline.state_labels[timeline.state_index[event]] == 'sweep'
    assert timeline.paths[timeline.path_index[event]].endswith('sweep voltage')


def test_round_trip_keeps_nan_values():
    timeline = small_timeline()
    again = ProtocolTimeline.m_from_dict(timeline.m_to_dict())
    np.testing.assert_array_equal(again.value, timeline.value)
    assert math.isnan(again.value[1])
    for name in ['target_index', 'state_index', 'path_index', *LOOKUPS]:
        assert list(getattr(again, name)) == list(getattr(timeline, name))


def test_timeline_is_read_only():
    quantities = ProtocolTimeline.m_def.all_quantities.values()
    assert [q.name for q in quantities if q.m_get_annotations('eln')] == []
