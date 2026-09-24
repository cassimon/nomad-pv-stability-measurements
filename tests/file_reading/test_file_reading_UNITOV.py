"""How the institution UNITOV's files are recognized and read into plain data."""

import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from nomad.units import ureg

import nomad_pv_stability_measurements
from nomad_pv_stability_measurements.file_reading.file_reading_UNITOV import (
    derive_protocol,
    is_jv_file,
    is_protocol_file,
    is_stability_series_file,
    read_collection,
    read_embedded_protocol,
    read_jv_file,
    read_protocol,
    read_stability_series,
)
from nomad_pv_stability_measurements.schema_packages.measurement import (
    StabilityMeasurement,
)

BATCH = (
    Path(nomad_pv_stability_measurements.__file__).parent
    / 'example_uploads/institutes/UNITOV/example_batch'
)
RUN = BATCH / 'AI14/AI14_1A/17.23.47'
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


@pytest.mark.parametrize(
    ('path', 'content', 'recognized'),
    [
        (TRACKING, 'Test\tStability (Tracking)\r\n', True),
        (PARAMETERS, 'Test\tStability (Parameters)\r\n', False),
        # Named as UNITOV names it, but not written by its station.
        (TRACKING, 'run:\n  institution: SIM\n', False),
    ],
)
def test_the_tracking_file_stands_for_its_run(path, content, recognized):
    assert is_protocol_file(path, content) is recognized


def test_a_run_says_who_ran_it_when_on_what_device_and_channel():
    run = read_protocol(TRACKING)['run']

    assert run['start'] == datetime(
        2025, 11, 20, 17, 23, 47, tzinfo=ZoneInfo('Europe/Rome')
    )
    assert (run['operator'], run['instruments']) == ('FDN', [{'name': 'SMU 1A'}])
    # The device's entry is made by the file that stands for its collection: the
    # Tracking file of its first run.
    [sample] = run['samples']
    assert sample['name'] == 'AI14-1A'
    assert Path(sample['file']).parent.name == '21.28.49'


def test_a_run_is_its_folder_the_series_then_each_scan_in_the_order_started():
    steps = read_protocol(TRACKING)['steps']

    assert [(step['name'], step['kind']) for step in steps] == [
        ('tracking', 'stability_series'),
        ('J–V 1', 'jv'),
        ('J–V 2', 'jv'),
    ]
    # At a fixed voltage the voltage is controlled; the current follows.
    assert steps[0]['controlled'] == ['voltage']


def test_a_scan_whose_file_is_missing_keeps_what_the_parameters_logged():
    tracking = next((BATCH / 'AI14/AI14_1C/17.23.47').glob('*(Tracking)*'))
    measurement = StabilityMeasurement()

    problems = measurement.read_files(
        tracking, read_protocol, read_stability_series, read_jv_file
    )

    _, logged, kept = measurement.steps
    assert problems == []
    assert (logged.name, logged.voltage) == ('J–V 1', None)
    assert [each.direction for each in logged.figures_of_merit] == [
        'forward',
        'reverse',
    ]
    assert logged.figures_of_merit[0].open_circuit_voltage.to('V').magnitude == (
        pytest.approx(0.4081114)
    )
    assert logged.scan_rate == 200 * ureg('mV/s')
    assert kept.voltage is not None


def test_a_runs_test_is_derived_holding_the_mean_voltage_under_assumed_conditions():
    data = derive_protocol(TRACKING)['data']

    [phase] = data['routine']['instructions']
    *holds, scans = phase['instructions']
    held = {each['channel']: each['specify'] for each in holds}
    assert held == {
        'electrical_load': '1.400 V',
        'temperature': 'RT',
        'irradiation': '1000 W/m^2',
    }
    assert phase['instructions'][0]['duration'] == '1 min'
    # A J–V scan every `JV interval`, as the run's J–V settings set it up.
    assert scans['jv_scan']['every'] == '0.55 min'
    assert scans['jv_scan']['scan_order'] == 'forward then reverse'
    # What was worked out or assumed rather than read is said.
    assert 'mean of the recorded voltage' in data['notes']
    assert 'temperature RT' in data['notes']


def test_no_file_states_a_test_and_only_the_tracking_file_derives_one():
    # UNITOV's files say how the station was set up, not what the test was to be.
    assert read_embedded_protocol(TRACKING) is None
    assert derive_protocol(JV) is None


def loose(folder: Path) -> Path:
    """A J–V scan taken outside any run, in a folder of its own under `folder`."""
    scan = folder / '09.00.00' / '0001_2025-11-21_09.00.00_Stability (JV)_AI14-1A.txt'
    scan.parent.mkdir(parents=True)
    shutil.copy(JV, scan)
    return scan


def test_a_device_is_collected_its_runs_in_order_and_the_scans_between(tmp_path):
    device = tmp_path / 'AI14_1A'
    shutil.copytree(BATCH / 'AI14/AI14_1A', device)
    loose(device)
    runs = sorted(device.glob('*/*(Tracking)*'))

    collections = [read_collection(run) for run in runs]

    # Only the first run's Tracking file stands for the collection.
    [collection] = [each for each in collections if each is not None]
    assert collection['name'] == 'AI14-1A'
    assert [Path(run).parent.name for run in collection['runs']] == [
        '21.28.49',
        '21.30.03',
        '17.23.47',
    ]
    [scan] = collection['steps']
    assert (scan['name'], scan['kind']) == ('J–V 1, 09.00.00', 'jv')
    assert collection['sample']['cell_area'] == 0.09 * ureg('cm^2')


def test_a_device_without_runs_is_collected_from_its_first_file(tmp_path):
    scan = loose(tmp_path / 'AI14_1A')

    collection = read_collection(scan)

    assert (collection['runs'], len(collection['steps'])) == ([], 1)
