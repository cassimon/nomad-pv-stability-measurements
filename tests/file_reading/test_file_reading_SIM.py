"""How the institution SIM's run files are recognized and read into plain data."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest
from nomad.units import ureg

import nomad_pv_stability_measurements
from nomad_pv_stability_measurements.file_reading.file_reading_SIM import (
    STEP_READERS,
    read_jv_file,
    read_stability_run,
    stability_run_belongs_to_this_institution,
)

SIMULATED = (
    Path(nomad_pv_stability_measurements.__file__).parent
    / 'example_uploads'
    / 'simulated_data'
)
#: One run per ISOS file.
ISOS_FILES = 20


def written(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding='utf-8')
    return path


@pytest.mark.parametrize(
    ('name', 'content', 'recognized'),
    [
        ('ISOS-L-2.run.yaml', 'run:\n  institution: SIM\n', True),
        # Another institution's run file, or none said.
        ('ISOS-L-2.run.yaml', 'run:\n  institution: HZB\n', False),
        ('ISOS-L-2.run.yaml', 'run:\n  name: cell A\n', False),
        ('ISOS-L-2.stability.yaml', 'run:\n  institution: SIM\n', False),
    ],
)
def test_a_run_file_is_recognized_by_its_name_and_institution(
    name, content, recognized
):
    assert stability_run_belongs_to_this_institution(name, content) is recognized


def test_a_jv_file_gives_the_direction_of_each_row(tmp_path):
    sweep = read_jv_file(
        written(
            tmp_path,
            '01_jv_initial.csv',
            'voltage (V),current_density (mA/cm^2),direction\n'
            '0.1,20,reverse\n0.1,19.8,forward\n',
        )
    )

    assert list(sweep) == ['voltage', 'current_density', 'direction']
    assert list(sweep['direction']) == ['reverse', 'forward']
    assert sweep['voltage'].units == ureg.volt


def test_the_run_file_gives_dates_and_step_files_beside_it(tmp_path):
    path = written(
        tmp_path,
        'ISOS-D-1.run.yaml',
        "run:\n  institution: SIM\n  start: '2026-03-02T09:00:00+01:00'\n"
        'steps:\n  - {name: ageing, kind: stability_series,\n'
        "     file: 02_stability_series.csv, start: '2026-03-02T09:12:00+01:00'}\n",
    )

    read = read_stability_run(path)
    [step] = read['steps']

    plus_one = timezone(timedelta(hours=1))
    assert read['run']['start'] == datetime(2026, 3, 2, 9, tzinfo=plus_one)
    assert step['start'] == datetime(2026, 3, 2, 9, 12, tzinfo=plus_one)
    assert step['file'] == str(tmp_path / '02_stability_series.csv')


def test_the_simulated_runs_are_recognized_and_read():
    """Every file the example upload ships is recognized as SIM's and readable, each
    step's columns one length, and each J–V sweep reported per direction swept."""
    run_files = sorted(SIMULATED.glob('*/*.run.yaml'))

    assert len(run_files) == ISOS_FILES
    for path in run_files:
        assert stability_run_belongs_to_this_institution(
            path, path.read_text(encoding='utf-8')
        )
        for step in read_stability_run(path)['steps']:
            columns = STEP_READERS[step['kind']](step['file'])
            reported = columns.pop('figures_of_merit', None)
            lengths = {np.size(values) for values in columns.values()}
            assert len(lengths) == 1, step['file']
            if step['kind'] == 'jv':
                assert list(reported['direction']) == list(
                    dict.fromkeys(columns['direction'])
                ), step['file']


def test_a_run_file_describing_its_test_gives_that_protocol(tmp_path):
    described = written(
        tmp_path,
        'x.run.yaml',
        'run: {institution: SIM}\n'
        'test conditions:\n'
        '  name: Damp heat\n'
        '  phases: [{name: soak, duration: 1000 h, temperature: 85 °C}]\n',
    )
    named = written(
        tmp_path,
        'y.run.yaml',
        'run: {institution: SIM, protocol: isos/ISOS-D-3.stability.yaml}\n',
    )

    assert read_stability_run(described)['protocol']['data']['name'] == 'Damp heat'
    assert 'protocol' not in read_stability_run(named)
