"""How the institution UNITOV's files are recognized and read into plain data."""

from pathlib import Path

import pytest
from nomad.units import ureg

import nomad_pv_stability_measurements
from nomad_pv_stability_measurements.file_reading.file_reading_UNITOV import (
    is_jv_file,
    is_stability_series_file,
    read_jv_file,
    read_stability_series,
)
from nomad_pv_stability_measurements.schema_packages.measurement import (
    StabilityMeasurement,
)

RUN = (
    Path(nomad_pv_stability_measurements.__file__).parent
    / 'example_uploads/institutes/UNITOV/example_batch/AI14/AI14_1A/17.23.47'
)
JV = RUN / '0001_2025-11-20_17.23.47_Stability (JV)_AI14-1A.txt'
TRACKING = RUN / '0000_2025-11-20_17.23.47_Stability (Tracking)_AI14-1A.txt'
PARAMETERS = RUN / '0000_2025-11-20_17.23.47_Stability (Parameters)_AI14-1A.txt'


@pytest.mark.parametrize(
    ('path', 'series', 'jv'),
    [(TRACKING, True, False), (JV, False, True), (PARAMETERS, False, False)],
)
def test_a_step_file_is_known_by_its_name(path, series, jv):
    assert (is_stability_series_file(path), is_jv_file(path)) == (series, jv)


def test_a_jv_file_is_the_curve_forward_then_reverse_as_its_header_says():
    sweep = read_jv_file(JV)

    directions = sweep['direction'].tolist()
    assert directions == sorted(directions)  # every forward point first
    assert sweep['voltage'][0].to('V').magnitude == pytest.approx(-0.1, abs=1e-5)
    # 17.78 mA/cm² at -0.1 V: positive where the cell delivers power.
    assert sweep['current_density'][0].to('mA/cm^2').magnitude == pytest.approx(
        17.78384
    )
    assert sweep['settings']['scan_order'] == 'forward then reverse'
    assert sweep['settings']['scan_rate'] == 200 * ureg('mV/s')


def test_the_reported_resistances_are_per_area_and_percentages_fractions():
    forward, _ = zip(*read_jv_file(JV)['figures_of_merit'].values())

    direction, voc, *_, rs, rsh, ff, eff = forward
    assert (direction, voc.to('V').magnitude) == ('forward', 0.794221)
    # Labelled `Ohm` by the station, meant per area.
    assert rs == 1.24e3 * ureg('ohm*cm^2')
    assert ff.to('').magnitude == pytest.approx(0.2243)
    assert eff.to('').magnitude == pytest.approx(0.0299)


def test_a_jv_file_is_read_into_a_sweep_with_nothing_left_over():
    measurement = StabilityMeasurement()

    problems = measurement.read_files(
        RUN,
        read_protocol=lambda path: {
            'run': {},
            'steps': [{'name': 'J–V', 'kind': 'jv', 'file': JV}],
        },
        read_stability_series=None,
        read_jv_file=read_jv_file,
    )

    [sweep] = measurement.steps
    assert problems == []
    assert [each.direction for each in sweep.figures_of_merit] == [
        'forward',
        'reverse',
    ]
    assert sweep.voltage_stop.to('V').magnitude == pytest.approx(1.5)


def test_a_tracking_file_is_the_series_since_the_start_and_how_it_was_tracked():
    series = read_stability_series(TRACKING)

    assert series['time'][0].to('s').magnitude == pytest.approx(0.003236 * 3600)
    assert series['voltage'][0].to('V').magnitude == pytest.approx(1.4, abs=1e-5)
    # Driven beyond open circuit, the cell takes power: negative.
    assert series['power_density'][0].to('mW/cm^2').magnitude == pytest.approx(
        -6.745534
    )
    assert series['settings'] == {
        'tracking_algorithm': 'fixed voltage',
        'tracking_step': 0.02 * ureg.volt,
        'tracking_delay': 0.5 * ureg.second,
    }


def test_a_tracking_file_is_read_into_a_series_with_nothing_left_over():
    measurement = StabilityMeasurement()

    problems = measurement.read_files(
        RUN,
        read_protocol=lambda path: {
            'run': {},
            'steps': [
                {'name': 'tracking', 'kind': 'stability_series', 'file': TRACKING}
            ],
        },
        read_stability_series=read_stability_series,
        read_jv_file=None,
    )

    [series] = measurement.steps
    assert problems == []
    assert len(series.current_density) == len(series.time)
