"""The template for reading the stability runs of one institution.

Every institution writes its runs in its own format. To read a new one, copy this file
to `file_reading_<INSTITUTION>.py`, set `INSTITUTION`, and fill in each function for
that institution's files. Keep the names and parameters: the parser picks an
institution's module by what it finds in the data and calls these functions, and a
`StabilityMeasurement` is handed the three `read_*` functions by its `read_files`.

Every function returns plain data: dicts, lists, datetimes, text, and pint quantities
from `nomad.units.ureg`. Helpers that more than one institution can use, such as
reading a CSV that names each column's unit in its header, are in
`file_reading_utils.py`. `file_reading_SIM.py` is a complete example.

A run is one file that says how the run went (`read_protocol`) and one file per step
that holds the step's data: a stability series (`read_stability_series`) or a J–V sweep
(`read_jv_file`). The run file either names the protocol file the run followed, in the
same upload, or describes the test itself (`read_embedded_protocol`).
"""

from pathlib import Path

import pint

#: The institution's short name, as in the module's name: `SIM` in
#: `file_reading_SIM.py`.
INSTITUTION = 'TEMPLATE'


def is_protocol_file(path: str | Path, content: str) -> bool:
    """Whether the file at `path`, whose text is `content`, is this institution's run
    file: the file that says how a run went.

    Decide it from the file's name, its content, or both, for example a naming pattern
    and a line that names the institution. Another institution's run file must give
    `False`.
    """
    raise NotImplementedError


def is_stability_series_file(path: str | Path) -> bool:
    """Whether the file at `path` is one of this institution's stability series: a
    step that records conditions and output over time."""
    raise NotImplementedError


def is_jv_file(path: str | Path) -> bool:
    """Whether the file at `path` is one of this institution's J–V sweeps."""
    raise NotImplementedError


def read_protocol(path: str | Path) -> dict:
    """The run file at `path`, as

        {
            'run': {
                'institution': 'SIM',
                'name': 'ISOS-L-2 (65 °C, MPP), cell A',
                'protocol': 'isos/ISOS-L-2.stability.yaml',  # from the upload's root
                'variant': 'ISOS-L-2 (65 °C, MPP)',  # the protocol entry it followed
                'standard': 'ISOS-L-2',
                'operator': 'A. Researcher',
                'start': datetime(...),
                'end': datetime(...),
                'location': 'Berlin, lab 2.14',
                'samples': [{'name': 'cell A'}],
                'instruments': [{'name': 'solar simulator'}],
                'notes': 'Free text.',
            },
            'steps': [
                {
                    'name': 'initial J–V',
                    'kind': 'jv',  # or 'stability_series'
                    'file': '/full/path/to/01_jv_initial.csv',
                    'start': datetime(...),
                },
                {
                    'name': 'ageing',
                    'kind': 'stability_series',
                    'file': '/full/path/to/02_stability_series.csv',
                    'start': datetime(...),
                    'controlled': ['temperature', 'irradiance', 'voltage'],
                },
                ...
            ],
        }

    Leave out what the file does not say. List the steps in the order they ran, and
    give each step's `file` as a path that can be opened as it is. A series' optional
    `controlled` names the recorded quantities that were controlled, by their names in
    a `StabilitySeriesStep`; every other recorded quantity was only monitored.
    """
    raise NotImplementedError


def read_embedded_protocol(path: str | Path) -> dict | None:
    """The protocol the run file at `path` describes itself, or `None` where it names a
    protocol file instead.

    Return what a `*.stability.yaml` file holds, as plain data: `{'data': {...}}`, with
    values as text such as `'85 °C'`. The run's entry and an entry for this protocol are
    both made from the run file, and the run refers to it. Where the file only lists
    phases and the values held in each, `file_reading_utils.protocol_from_phases` builds
    it. Otherwise, `return None`.

    Called when the parser decides which entries a file makes, so it must not fail on a
    run file that names a protocol file.
    """
    raise NotImplementedError


def read_stability_series(path: str | Path) -> dict[str, pint.Quantity]:
    """The stability series at `path`, one quantity array per column, by the name of
    the quantity it fills in a `StabilitySeriesStep`: `time` (from the step's start),
    and whichever of `temperature`, `irradiance`, `relative_humidity`, `voltage`,
    `current_density` and `power_density` the file records. Every array is as long
    as `time`.

    A column with another name is reported when the measurement is read, not stored.
    """
    raise NotImplementedError


def read_jv_file(path: str | Path) -> dict[str, object]:
    """The J–V sweep at `path`: `voltage` and `current_density` as quantity arrays,
    and `direction` as an array of `'forward'` or `'reverse'`, one per point, as in a
    `JVSweepStep`. Current density is positive where the cell delivers power.

    Where the file holds what the J–V station reported of each scan, also
    `figures_of_merit`: a table of one row per scan, one array per column by the name
    of the `JVFiguresOfMerit` quantity it fills (`direction`, `efficiency`,
    `open_circuit_voltage`, ...). They are taken as reported, never worked out again."""
    raise NotImplementedError
