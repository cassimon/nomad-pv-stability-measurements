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

A run has one **run file**, the file that stands for it: its entry is made from that
file. Some institutions write a file that says how the run went and lists its steps;
others write only the steps' files, in a folder of their own or under a common name.
Then choose one of them as the run file, and `read_protocol` collects the others around
it. Each step's data is a stability series (`read_stability_series`) or a J–V sweep
(`read_jv_file`). The run file either names the protocol file the run followed, in the
same upload, or describes the test itself (`read_embedded_protocol`).

Data taken outside any run, such as J–V scans in the time between runs, belongs to a
**collection**: one entry per device, which refers to all of the device's runs and holds
the rest as its own steps (`read_collection`).
"""

from pathlib import Path

#: The institution's short name, as in the module's name: `SIM` in
#: `file_reading_SIM.py`.
INSTITUTION = 'TEMPLATE'

#: The conditions this institution's tests run under where its files state none, as
#: `{name in SET_POINTS: value as text}`, for example
#: `{'temperature': 'RT', 'irradiance': '1000 W/m^2'}`. Leave it empty where the files
#: state everything. A protocol that uses one of them says so in its `notes`.
ASSUMED_CONDITIONS: dict[str, str] = {}


def is_protocol_file(path: str | Path, content: str) -> bool:
    """Whether the file at `path`, whose text is `content`, is this institution's run
    file: the file that says how a run went.

    Decide it from the file's name, its content, or both, for example a naming pattern
    and a line that names the institution. Another institution's run file must give
    `False`. Every file of an upload is asked, so look at the name first.
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

    Where the run file does not list the steps, find them beside it, for example the
    other files in its folder, using `is_stability_series_file` and `is_jv_file`.

    Leave out what the file does not say. List the steps in the order they ran, and
    give each step's `file` as a path that can be opened as it is. A series' optional
    `controlled` names the recorded quantities that were controlled, by their names in
    a `StabilitySeriesStep`; every other recorded quantity was only monitored. A step's
    optional `settings` say how it was set up, by the names of the step's quantities,
    as `{'scan_rate': 0.2 * ureg('V/s'), 'scan_order': 'forward then reverse'}`.
    A J–V step whose curve was not kept but whose figures of merit were logged, for
    example in a file of figures over time, carries them as `figures_of_merit`, a table
    as `read_jv_file` hands back, and needs no `file`.
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


def read_stability_series(path: str | Path) -> dict[str, object]:
    """The stability series at `path`, one quantity array per column, by the name of
    the quantity it fills in a `StabilitySeriesStep`: `time` (from the step's start),
    and whichever of `temperature`, `irradiance`, `relative_humidity`, `voltage`,
    `current_density` and `power_density` the file records. Every array is as long
    as `time`.

    A column with another name is reported when the measurement is read, not stored.

    Where the file says how the electrical load was tracked, also `settings`, as in the
    steps of `read_protocol`: `tracking_algorithm`, `tracking_step` and `tracking_delay`.
    """
    raise NotImplementedError


def read_jv_file(path: str | Path) -> dict[str, object]:
    """The J–V sweep at `path`: `voltage` and `current_density` as quantity arrays,
    and `direction` as an array of `'forward'` or `'reverse'`, one per point, as in a
    `JVSweepStep`. Current density is positive where the cell delivers power.

    Where the file holds what the J–V station reported of each scan, also
    `figures_of_merit`: a table of one row per scan, one array per column by the name
    of the `JVFiguresOfMerit` quantity it fills (`direction`, `efficiency`,
    `open_circuit_voltage`, ...). They are taken as reported, never worked out again.

    Where the file says how the sweep was set up, also `settings`, as in the steps of
    `read_protocol`: `voltage_start`, `voltage_stop`, `voltage_step`, `scan_rate` and
    `scan_order`."""
    raise NotImplementedError


def read_collection(path: str | Path) -> dict | None:
    """The collection the file at `path` stands for, or `None` if it stands for none.

    A collection is one device's whole history: all its runs, and the steps taken
    outside any run, whose conditions in between nobody specified. Exactly one file per
    device stands for its collection, for example the run file of its first run, or,
    for a device without runs, its first other file. For it, return

        {
            'name': 'AI14-1A',
            'samples': [{'name': 'AI14-1A'}],
            'runs': ['/full/path/to/run/file', ...],  # the run files of its runs
            'steps': [...],  # the steps outside any run, as in `read_protocol`
        }

    For every other file, and where the institution keeps no collections, `return None`.
    """
    raise NotImplementedError
