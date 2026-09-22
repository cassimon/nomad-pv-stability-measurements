"""Reading the stability runs of one institution: SIM, the simulated example data.

Every institution writes its runs in its own format, so each gets a module of its own,
`file_reading_<INSTITUTION>.py`, with the same interface. Plain functions that return
plain data, so that a `StabilityMeasurement` can be handed them and never needs to know
about files:

- `INSTITUTION`: the short name in the module's name.
- `is_protocol_file`, `is_stability_series_file`, `is_jv_file`: whether a file is one
  of this institution's, and which kind; from its name, and where it says so, its
  content.
- `read_protocol`: the file that says how a run went. Which protocol and standard it
  followed, who ran it, when, where, on which samples and instruments, and its steps
  in the order they ran, each with the file that holds its data.
- `read_stability_series`: a step that records conditions and output over time, every
  quantity as one column of a single table.
- `read_jv_file`: a step that sweeps the voltage and records the current density.

SIM writes a run as a folder:

    ISOS-L-2.run.yaml           read_protocol; says `institution: SIM`
    01_jv_initial.csv           read_jv_file
    02_stability_series.csv     read_stability_series
    03_jv_final.csv             read_jv_file

Each CSV names a column and its unit in the header, as `temperature (°C)`. What
another institution could share is in `file_reading_utils.py`.
"""

import re
from pathlib import Path

import pint
import yaml

from nomad_pv_stability_measurements.parsers.file_reading_utils import (
    as_datetime,
    read_csv_with_units_in_header,
)

INSTITUTION = 'SIM'

_PROTOCOL_FILE_NAME = re.compile(r'.*\.run\.ya?ml')
_SAYS_INSTITUTION = re.compile(
    rf'^\s*institution:\s*[\'"]?{INSTITUTION}[\'"]?\s*$', re.M
)
_STABILITY_SERIES_FILE_NAME = re.compile(r'\d+_stability_series\.csv')
_JV_FILE_NAME = re.compile(r'\d+_jv_\w+\.csv')


def is_protocol_file(path: str | Path, content: str) -> bool:
    """A SIM run file: named `*.run.yaml`, and saying `institution: SIM`."""
    return bool(
        _PROTOCOL_FILE_NAME.fullmatch(Path(path).name)
        and _SAYS_INSTITUTION.search(content)
    )


def is_stability_series_file(path: str | Path) -> bool:
    """A SIM stability series, by its name: `02_stability_series.csv`."""
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


def read_stability_series(path: str | Path) -> dict[str, pint.Quantity]:
    """The stability series at `path`, one quantity array per column, by the column's
    name: `time`, and whichever of `temperature`, `irradiance`, `relative_humidity`,
    `voltage`, `current_density` and `power_density` the run recorded."""
    return read_csv_with_units_in_header(path)


def read_jv_file(path: str | Path) -> dict[str, object]:
    """The J–V sweeps at `path`: `voltage` and `current_density` as quantity arrays,
    and `direction`, `reverse` or `forward` for each row, as text."""
    return read_csv_with_units_in_header(path)
