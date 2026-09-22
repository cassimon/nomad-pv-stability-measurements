"""How the institution SIM's run files are recognized and read into plain data."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest
from nomad.units import ureg

import nomad_pv_stability_measurements
from nomad_pv_stability_measurements.parsers.file_reading_SIM import (
    is_jv_file,
    is_protocol_file,
    is_stability_series_file,
    read_jv_file,
    read_protocol,
    read_stability_series,
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
def test_a_protocol_file_is_recognized_by_its_name_and_institution(
    name, content, recognized
):
    assert is_protocol_file(name, content) is recognized


@pytest.mark.parametrize(
    ('name', 'series', 'jv'),
    [
        ('02_stability_series.csv', True, False),
        ('01_jv_initial.csv', False, True),
        ('03_jv_final.csv', False, True),
        ('notes.csv', False, False),
    ],
)
def test_a_step_file_is_recognized_by_its_name(name, series, jv):
    assert (is_stability_series_file(name), is_jv_file(name)) == (series, jv)


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


def test_the_protocol_file_gives_dates_and_step_files_beside_it(tmp_path):
    path = written(
        tmp_path,
        'ISOS-D-1.run.yaml',
        "run:\n  institution: SIM\n  start: '2026-03-02T09:00:00+01:00'\n"
        'steps:\n  - {name: ageing, kind: stability_series,\n'
        "     file: 02_stability_series.csv, start: '2026-03-02T09:12:00+01:00'}\n",
    )

    protocol = read_protocol(path)
    [step] = protocol['steps']

    plus_one = timezone(timedelta(hours=1))
    assert protocol['run']['start'] == datetime(2026, 3, 2, 9, tzinfo=plus_one)
    assert step['start'] == datetime(2026, 3, 2, 9, 12, tzinfo=plus_one)
    assert step['file'] == str(tmp_path / '02_stability_series.csv')


def test_the_simulated_runs_are_recognized_and_read():
    """Every file the example upload ships is recognized as SIM's and readable, each
    step's columns one length."""
    protocol_files = sorted(SIMULATED.glob('*/*.run.yaml'))

    assert len(protocol_files) == ISOS_FILES
    for path in protocol_files:
        assert is_protocol_file(path, path.read_text(encoding='utf-8'))
        for step in read_protocol(path)['steps']:
            read = read_jv_file if is_jv_file(step['file']) else read_stability_series
            assert is_jv_file(step['file']) or is_stability_series_file(step['file'])
            lengths = {np.size(values) for values in read(step['file']).values()}
            assert len(lengths) == 1, step['file']
