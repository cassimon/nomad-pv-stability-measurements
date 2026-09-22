"""Reading the stability runs of one institution: SIM, the simulated example data.

The interface of `file_reading_TEMPLATE.py`, filled in for SIM's files.

SIM writes a run as a folder:

    ISOS-L-2.run.yaml           read_protocol; says `institution: SIM`
    01_jv_initial.csv           read_jv_file
    02_stability_series.csv     read_stability_series
    03_jv_final.csv             read_jv_file

A run recorded in phases has one stability series per phase and a J–V sweep after
each: `02_stability_series_burn_in.csv`, `03_jv_after_burn_in.csv`, and so on.

A run file either names the protocol file the run followed, as `protocol` and `variant`
under `run`, or describes the test itself under `test conditions`: the phases run one
after another, `repeat` times, and what each holds:

    test conditions:
      name: Damp heat at open circuit
      repeat: 1
      phases:
      - {name: damp heat, duration: 1000 h, temperature: 85 °C, ...}

Each CSV names a column and its unit in the header, as `temperature (°C)`. What
another institution could share is in `file_reading_utils.py`.
"""

import re
from pathlib import Path

import pint
import yaml

from nomad_pv_stability_measurements.file_reading.file_reading_utils import (
    as_datetime,
    protocol_from_phases,
    read_csv_with_units_in_header,
)

INSTITUTION = 'SIM'

_PROTOCOL_FILE_NAME = re.compile(r'.*\.run\.ya?ml')
_SAYS_INSTITUTION = re.compile(
    rf'^\s*institution:\s*[\'"]?{INSTITUTION}[\'"]?\s*$', re.M
)
_STABILITY_SERIES_FILE_NAME = re.compile(r'\d+_stability_series(_\w+)?\.csv')
_JV_FILE_NAME = re.compile(r'\d+_jv_\w+\.csv')


def is_protocol_file(path: str | Path, content: str) -> bool:
    """A SIM run file: named `*.run.yaml`, and saying `institution: SIM`."""
    return bool(
        _PROTOCOL_FILE_NAME.fullmatch(Path(path).name)
        and _SAYS_INSTITUTION.search(content)
    )


def is_stability_series_file(path: str | Path) -> bool:
    """A SIM stability series, by its name: `02_stability_series.csv`, or with its
    phase, `02_stability_series_burn_in.csv`."""
    return bool(_STABILITY_SERIES_FILE_NAME.fullmatch(Path(path).name))


def is_jv_file(path: str | Path) -> bool:
    """A SIM J–V sweep, by its name: `01_jv_initial.csv`."""
    return bool(_JV_FILE_NAME.fullmatch(Path(path).name))


def read_protocol(path: str | Path) -> dict:
    """The run file at `path`, as `{'run': {...}, 'steps': [...]}`.

    Its dates come as datetimes. Each step names its `kind` (`jv` or
    `stability_series`) and its `file`, given as a path beside the run file.
    """
    path = Path(path)
    document = yaml.safe_load(path.read_text(encoding='utf-8'))
    run = document.get('run') or {}
    for key in ('start', 'end'):
        if key in run:
            run[key] = as_datetime(run[key])
    steps = document.get('steps') or []
    for step in steps:
        if 'start' in step:
            step['start'] = as_datetime(step['start'])
        if 'file' in step:
            step['file'] = str(path.parent / step['file'])
    return {'run': run, 'steps': steps}


def read_embedded_protocol(path: str | Path) -> dict | None:
    """The protocol of the run file's `test conditions`, or `None` if it has none."""
    document = yaml.safe_load(Path(path).read_text(encoding='utf-8')) or {}
    conditions = document.get('test conditions')
    return None if conditions is None else protocol_from_phases(**conditions)


def read_stability_series(path: str | Path) -> dict[str, pint.Quantity]:
    """The stability series at `path`, one quantity array per column, by the column's
    name: `time`, and whichever of `temperature`, `irradiance`, `relative_humidity`,
    `voltage`, `current_density` and `power_density` the run recorded."""
    return read_csv_with_units_in_header(path)


def read_jv_file(path: str | Path) -> dict[str, object]:
    """The J–V sweeps at `path`: `voltage` and `current_density` as quantity arrays,
    and `direction`, `reverse` or `forward` for each row, as text."""
    return read_csv_with_units_in_header(path)
