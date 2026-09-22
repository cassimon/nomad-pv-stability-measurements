"""The steps a stability test records: series over time and J–V sweeps."""

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
from nomad.units import ureg

import nomad_pv_stability_measurements
from nomad_pv_stability_measurements.file_reading import file_reading_SIM
from nomad_pv_stability_measurements.schema_packages.measurement import (
    JVSweepStep,
    StabilityMeasurement,
    StabilitySeriesStep,
)
from nomad_pv_stability_measurements.schema_packages.protocol import (
    StabilityActivity,
)

HOURS = [0.0, 1.0, 2.0] * ureg.hour
START = datetime(2026, 3, 2, 8, tzinfo=timezone.utc)
SIMULATED = (
    Path(nomad_pv_stability_measurements.__file__).parent
    / 'example_uploads'
    / 'simulated_data'
)


def test_a_series_records_only_what_was_measured(normalized, log):
    step = normalized(
        StabilitySeriesStep(
            name='dark storage',
            time=HOURS,
            temperature=[296.0, 296.2, 296.1] * ureg.kelvin,
            relative_humidity=[0.40, 0.41, 0.39],
        )
    )

    assert step.irradiance is None
    assert log.errors == []


@pytest.mark.parametrize(
    ('given', 'fragment'),
    [
        ({'temperature': [296.0, 296.2] * ureg.kelvin}, '`temperature` has 2 values'),
        ({'time': [2.0, 1.0, 3.0] * ureg.hour}, '`time` goes backwards'),
    ],
)
def test_every_sample_has_a_time_and_one_value_of_each_quantity(
    normalized, log, given, fragment
):
    normalized(StabilitySeriesStep(**{'time': HOURS, **given}))

    [message] = log.errors
    assert fragment in message


def test_a_series_without_time_is_reported(normalized, log):
    normalized(StabilitySeriesStep(temperature=[296.0] * ureg.kelvin))

    [message] = log.errors
    assert 'recorded without `time`' in message


def test_a_sweep_has_one_voltage_current_and_direction_per_point(normalized, log):
    normalized(
        JVSweepStep(
            voltage=[1.1, 0.0, 1.1] * ureg.volt,
            current_density=[0.0, 230.0] * ureg('A/m^2'),
            direction=['reverse', 'reverse', 'forward'],
        )
    )

    [message] = log.errors
    assert '2 `current_density`' in message


def test_a_sweep_goes_forward_or_reverse_only():
    with pytest.raises(ValueError, match='sideways'):
        JVSweepStep(direction=['sideways'])


def test_the_steps_are_kept_as_what_they_are_in_an_activity():
    """Written out and read back, as NOMAD stores an entry."""
    activity = StabilityActivity(
        steps=[
            JVSweepStep(name='initial J–V', direction=['reverse']),
            StabilitySeriesStep(name='ageing', time=HOURS),
        ]
    )

    read_back = StabilityActivity.m_from_dict(activity.m_to_dict())

    assert [type(step) for step in read_back.steps] == [
        JVSweepStep,
        StabilitySeriesStep,
    ]
    assert read_back.steps[1].time.to('hour').magnitude.tolist() == [0.0, 1.0, 2.0]


def read_from(protocol, tables):
    """Readers that hand back what they are given, as an institution's would read it
    from files: `protocol` for the run file, `tables` by step file."""
    return {
        'read_protocol': lambda path: protocol,
        'read_stability_series': lambda path: tables[path],
        'read_jv_file': lambda path: tables[path],
    }


def test_a_measurement_takes_who_ran_what_when_and_on_what_from_the_run_file():
    run = {
        'name': 'cell A, damp heat',
        'start': START,
        'location': 'Lab 2',
        'standard': 'ISOS-D-3',
        'operator': 'A. Researcher',
        'notes': 'Simulated.',
        'samples': [{'name': 'cell A', 'lab_id': 'A-1'}],
        'instruments': [{'name': 'climate chamber'}],
    }
    measurement = StabilityMeasurement()

    measurement.read_files('run.yaml', **read_from({'run': run, 'steps': []}, {}))

    assert (measurement.name, measurement.datetime) == ('cell A, damp heat', START)
    assert (measurement.method, measurement.location) == ('ISOS-D-3', 'Lab 2')
    assert (measurement.operator, measurement.description) == (
        'A. Researcher',
        'Simulated.',
    )
    assert [(each.name, each.lab_id) for each in measurement.samples] == [
        ('cell A', 'A-1')
    ]
    assert [each.name for each in measurement.instruments] == ['climate chamber']


def test_each_step_is_read_in_order_by_the_function_for_its_kind():
    steps = [
        {'name': 'initial J–V', 'kind': 'jv', 'file': 'jv.csv', 'start': START},
        {'name': 'ageing', 'kind': 'stability_series', 'file': 'series.csv'},
    ]
    tables = {
        'jv.csv': {
            'voltage': [0.0, 1.1] * ureg.volt,
            'direction': np.array(['reverse', 'forward']),
        },
        'series.csv': {'time': HOURS, 'temperature': [338.0] * 3 * ureg.kelvin},
    }
    measurement = StabilityMeasurement()

    problems = measurement.read_files(
        'run.yaml', **read_from({'run': {}, 'steps': steps}, tables)
    )

    jv, series = measurement.steps
    assert problems == []
    assert (type(jv), jv.name, jv.start_time) == (JVSweepStep, 'initial J–V', START)
    assert jv.direction == ['reverse', 'forward']
    assert type(series) is StabilitySeriesStep
    assert series.temperature.to('K').magnitude.tolist() == [338.0] * 3


def test_what_has_no_place_is_reported_and_the_rest_read():
    steps = [
        {'name': 'photo', 'kind': 'image', 'file': 'photo.png'},
        {'name': 'ageing', 'kind': 'stability_series', 'file': 'series.csv'},
    ]
    tables = {'series.csv': {'time': HOURS, 'wind_speed': [1.0] * 3 * ureg('m/s')}}
    measurement = StabilityMeasurement()

    problems = measurement.read_files(
        'run.yaml', **read_from({'run': {}, 'steps': steps}, tables)
    )

    unknown_kind, unknown_column = problems
    assert [step.name for step in measurement.steps] == ['ageing']
    assert 'kind `image`' in unknown_kind
    assert 'column `wind_speed`' in unknown_column


def test_a_simulated_run_is_read_with_the_functions_of_its_institution():
    measurement = StabilityMeasurement()

    problems = measurement.read_files(
        SIMULATED / 'ISOS-L-2' / 'ISOS-L-2.run.yaml',
        read_protocol=file_reading_SIM.read_protocol,
        read_stability_series=file_reading_SIM.read_stability_series,
        read_jv_file=file_reading_SIM.read_jv_file,
    )

    assert problems == []
    assert measurement.method == 'ISOS-L-2'
    assert [type(step) for step in measurement.steps] == [
        JVSweepStep,
        StabilitySeriesStep,
        JVSweepStep,
    ]
    assert measurement.steps[1].power_density is not None
