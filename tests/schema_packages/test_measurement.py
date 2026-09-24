"""The steps a stability test records: series over time and J–V sweeps."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest
from nomad.datamodel import EntryArchive
from nomad.units import ureg

import nomad_pv_stability_measurements
from nomad_pv_stability_measurements.file_reading import file_reading_SIM
from nomad_pv_stability_measurements.schema_packages.measurement import (
    JVFiguresOfMerit,
    JVSweepStep,
    StabilityMeasurement,
    StabilitySeriesStep,
)
from nomad_pv_stability_measurements.schema_packages.plan_timeline import ROLE_COLORS
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


def test_a_sweep_shows_one_curve_per_direction_in_the_order_swept(normalized):
    step = normalized(
        JVSweepStep(
            name='initial J–V',
            voltage=[1.1, 0.0, 0.0, 1.1] * ureg.volt,
            current_density=[0.0, 230.0, 228.0, 0.0] * ureg('A/m^2'),
            direction=['reverse', 'reverse', 'forward', 'forward'],
        )
    )

    [figure] = step.figures
    curves = figure.figure['data']
    assert [curve['name'] for curve in curves] == ['reverse', 'forward']
    assert curves[0]['x'] == [1.1, 0.0]
    assert curves[1]['y'] == pytest.approx([22.8, 0.0])  # mA/cm²


ELECTRICAL = {
    'voltage': [0.95, 0.94, 0.93] * ureg.volt,
    'current_density': [200.0, 199.0, 197.0] * ureg('A/m^2'),
    'power_density': [190.0, 187.1, 183.2] * ureg('W/m^2'),
}


@pytest.mark.parametrize(
    ('recorded', 'controlled', 'rows'),
    [
        (
            ['voltage', 'current_density', 'power_density'],
            ['voltage'],
            [
                ('power density', 'monitored'),
                ('current density', 'monitored'),
                ('voltage', 'controlled'),
            ],
        ),
        (
            ['voltage', 'current_density'],
            ['voltage'],
            [('current density', 'monitored'), ('voltage', 'controlled')],
        ),
        ([], [], None),
    ],
    ids=['maximum power point', 'fixed voltage', 'dark'],
)
def test_a_series_shows_its_electrical_output_in_the_colour_of_its_role(
    normalized, recorded, controlled, rows
):
    """Controlled or only monitored, in the colours of a protocol's timeline; a
    recorded quantity not said to be controlled was monitored."""
    step = normalized(
        StabilitySeriesStep(
            time=HOURS,
            temperature=[338.0] * 3 * ureg.kelvin,
            controlled=controlled,
            **{name: ELECTRICAL[name] for name in recorded},
        )
    )

    if rows is None:
        assert not step.figures
        return
    [figure] = step.figures
    traces = figure.figure['data']
    assert [trace['name'] for trace in traces] == [
        f'{row} · {role}' for row, role in rows
    ]
    assert [trace['line']['color'] for trace in traces] == [
        ROLE_COLORS[role] for _, role in rows
    ]
    assert all(trace['x'] == [0.0, 1.0, 2.0] for trace in traces)


def test_a_measurement_shows_its_series_over_time_since_it_started(normalized):
    """On top the efficiency each J–V scan reported, one line per direction, at the
    sweep's mark; below, what the series recorded where it ran."""

    def sweep(hour, reverse, forward):
        return JVSweepStep(
            start_time=START + timedelta(hours=hour),
            figures_of_merit=[
                JVFiguresOfMerit(direction='reverse', efficiency=reverse),
                JVFiguresOfMerit(direction='forward', efficiency=forward),
            ],
        )

    measurement = normalized(
        StabilityMeasurement(
            datetime=START,
            steps=[
                sweep(0, 0.20, 0.19),
                StabilitySeriesStep(
                    name='ageing',
                    start_time=START + timedelta(hours=1),
                    time=HOURS,
                    temperature=[338.0] * 3 * ureg.kelvin,
                    power_density=ELECTRICAL['power_density'],
                    controlled=['temperature'],
                ),
                sweep(4, 0.18, 0.16),
            ],
        )
    )

    [figure] = measurement.figures
    reverse, forward, power, temperature = figure.figure['data']
    assert (reverse['name'], reverse['x']) == ('reverse', [0.0, 4.0])
    assert forward['y'] == pytest.approx([19.0, 16.0])  # %
    assert 'markers' in reverse['mode']
    assert power['name'] == 'ageing · power density · monitored'
    assert (temperature['name'], temperature['x']) == (
        'ageing · temperature · controlled',
        [1.0, 2.0, 3.0],
    )
    assert temperature['y'] == pytest.approx([64.85] * 3)  # °C
    assert [mark['x0'] for mark in figure.figure['layout']['shapes']] == [0.0, 4.0]


def test_the_power_each_scan_reported_is_shown_beside_the_tracked_power(normalized):
    measurement = normalized(
        StabilityMeasurement(
            datetime=START,
            steps=[
                StabilitySeriesStep(
                    name='ageing',
                    start_time=START,
                    time=HOURS,
                    power_density=ELECTRICAL['power_density'],
                ),
                JVSweepStep(
                    start_time=START + timedelta(hours=1),
                    figures_of_merit=[
                        JVFiguresOfMerit(
                            direction='reverse',
                            power_density_at_maximum_power_point=190 * ureg('W/m^2'),
                        )
                    ],
                ),
            ],
        )
    )

    [figure] = measurement.figures
    tracked, reported = figure.figure['data']
    assert reported['yaxis'] == tracked['yaxis']  # the same row
    assert (reported['mode'], reported['x']) == ('markers', [1.0])
    assert reported['y'] == pytest.approx([19.0])  # mW/cm²


def test_a_measurement_made_of_others_keeps_the_figure_drawn_of_their_steps(log):
    run = StabilityMeasurement(
        name='run',
        steps=[
            StabilitySeriesStep(
                name='ageing',
                start_time=START,
                time=HOURS,
                power_density=ELECTRICAL['power_density'],
            )
        ],
    )
    collection = StabilityMeasurement(name='device', sub_activities=[run])
    collection.figures = collection.figures_for_plotting(log, list(run.steps))

    collection.normalize(EntryArchive(), log)

    [figure] = collection.figures
    [power] = figure.figure['data']
    assert power['x'] == [0.0, 1.0, 2.0]


def test_a_step_without_a_start_is_left_out_of_the_overview(normalized, log):
    normalized(
        StabilityMeasurement(
            datetime=START,
            steps=[StabilitySeriesStep(name='ageing', time=HOURS)],
        )
    )

    [message] = log.warnings
    assert 'step `ageing` has no `start_time`' in message


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
        {
            'name': 'ageing',
            'kind': 'stability_series',
            'file': 'series.csv',
            'controlled': ['temperature'],
        },
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
    assert series.controlled == ['temperature']


def test_a_sweep_takes_the_figures_of_merit_its_station_reported_per_scan():
    tables = {
        'jv.csv': {
            'voltage': [0.0, 1.1] * ureg.volt,
            'direction': np.array(['reverse', 'forward']),
            'figures_of_merit': {
                'direction': np.array(['reverse', 'forward']),
                'efficiency': [20.1, 19.6] * ureg.percent,
                'open_circuit_voltage': [1.12, 1.11] * ureg.volt,
                'wind_speed': [1.0, 1.0] * ureg('m/s'),
            },
        }
    }
    steps = [{'name': 'initial J–V', 'kind': 'jv', 'file': 'jv.csv'}]
    measurement = StabilityMeasurement()

    problems = measurement.read_files(
        'run.yaml', **read_from({'run': {}, 'steps': steps}, tables)
    )

    reverse, forward = measurement.steps[0].figures_of_merit
    assert (reverse.direction, forward.direction) == ('reverse', 'forward')
    assert forward.efficiency.to('').magnitude == pytest.approx(0.196)
    assert reverse.open_circuit_voltage.to('V').magnitude == pytest.approx(1.12)
    assert ['column `wind_speed`' in problem for problem in problems] == [True, True]


def test_a_scan_whose_curve_was_not_kept_keeps_the_figures_of_merit_logged():
    steps = [
        {
            'name': 'J–V at 0.5 h',
            'kind': 'jv',
            'start': START,
            'figures_of_merit': {
                'direction': ['forward', 'reverse'],
                'efficiency': [15.2, 15.9] * ureg.percent,
            },
        },
        {'name': 'lost', 'kind': 'jv'},
    ]
    measurement = StabilityMeasurement()

    problems = measurement.read_files(
        'run.yaml', **read_from({'run': {}, 'steps': steps}, {})
    )

    scan, _ = measurement.steps
    assert scan.voltage is None
    assert [each.direction for each in scan.figures_of_merit] == ['forward', 'reverse']
    [problem] = problems
    assert 'step `lost` names no file' in problem


def test_a_sweep_takes_how_it_was_set_up_from_its_step_or_its_file():
    steps = [
        {
            'name': 'J–V',
            'kind': 'jv',
            'file': 'jv.csv',
            'settings': {'scan_order': 'forward then reverse', 'colour': 'blue'},
        }
    ]
    tables = {
        'jv.csv': {
            'voltage': [0.0, 1.1] * ureg.volt,
            'settings': {
                'voltage_start': -0.1 * ureg.volt,
                'voltage_stop': 1.5 * ureg.volt,
                'voltage_step': 20 * ureg.millivolt,
                'scan_rate': 200 * ureg('mV/s'),
            },
        },
    }
    measurement = StabilityMeasurement()

    problems = measurement.read_files(
        'run.yaml', **read_from({'run': {}, 'steps': steps}, tables)
    )

    [jv] = measurement.steps
    assert jv.scan_order == 'forward then reverse'
    assert jv.scan_rate.to('V/s').magnitude == pytest.approx(0.2)
    assert jv.voltage_stop.to('V').magnitude == pytest.approx(1.5)
    [problem] = problems
    assert 'a setting `colour`' in problem


def test_a_series_takes_how_its_load_was_tracked_from_its_settings():
    steps = [
        {
            'name': 'ageing',
            'kind': 'stability_series',
            'file': 'series.csv',
            'settings': {
                'tracking_algorithm': 'fixed voltage',
                'tracking_step': 20 * ureg.millivolt,
                'tracking_delay': 0.5 * ureg.second,
            },
        }
    ]
    tables = {'series.csv': {'time': HOURS}}
    measurement = StabilityMeasurement()

    problems = measurement.read_files(
        'run.yaml', **read_from({'run': {}, 'steps': steps}, tables)
    )

    [series] = measurement.steps
    assert problems == []
    assert series.tracking_algorithm == 'fixed voltage'
    assert series.tracking_step.to('V').magnitude == pytest.approx(0.02)
    assert series.tracking_delay.to('s').magnitude == pytest.approx(0.5)


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
    # One series, and sweeps before it, during it where the protocol repeats them,
    # and after it.
    [series] = [
        step for step in measurement.steps if isinstance(step, StabilitySeriesStep)
    ]
    first, *during, last = [step for step in measurement.steps if step is not series]
    assert all(isinstance(step, JVSweepStep) for step in (first, *during, last))
    assert during
    assert series.power_density is not None
