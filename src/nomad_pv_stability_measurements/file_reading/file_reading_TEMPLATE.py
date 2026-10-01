"""The template for reading the stability runs of one institution.

To add your institution:

1. Copy this file to `file_reading_<INSTITUTION>.py`, for example
   `file_reading_HZB.py`, and set `INSTITUTION` to the same short name.
2. Fill in the two required functions. Keep their names and parameters.
3. Write one reader per kind of step file your station writes, and list them in
   `STEP_READERS`.
4. Fill in an optional function only if you need it, and delete the others.
5. Add your module to `INSTITUTIONS` in `parsers/measurement_parser.py`.

Return plain data: dicts, lists, text, datetimes with their time zone, and quantities
of `nomad.units.ureg`, as in `ureg.Quantity([0.1, 0.2], 'V')`. Leave out what your files
do not say. For a complete example, see `file_reading_SIM.py`; for one with the optional
functions, `file_reading_UNITOV.py`. Readers you can reuse, such as for a CSV that
gives the units in its header, are in `file_reading_utils.py`.
"""

from pathlib import Path

#: Your institution's short name, as in the module's name.
INSTITUTION = 'TEMPLATE'


# --- Required: fill in both ----------------------------------------------------------


def stability_run_belongs_to_this_institution(path: str | Path, content: str) -> bool:
    """Return `True` if the file at `path` is the file that stands for one of your
    runs, else `False`. `content` is its text.

    Pick one file per run: the file that says how the run went, or, where your
    station writes none, one of its step files, such as its stability series. Decide
    by the file's name first, then by its content, for example a line that names your
    institution: every file of an upload is asked, including other institutions'."""
    raise NotImplementedError


def read_stability_run(path: str | Path) -> dict:
    """Read the run whose file is at `path` (the one you chose above) and return it
    in this form of a Python dict:

        {
            'run': {
                'name': 'ISOS-L-2, cell A',
                'start': datetime(...),
                'time_zone': 'Europe/Berlin',  # where the test ran, an IANA name
                'protocol': 'isos/ISOS-L-2.stability.yaml',  # from the upload's root
                'variant': 'ISOS-L-2 (65 °C, MPP)',  # only for a file with options
                'operator': 'A. Researcher',
                'samples': [{'name': 'cell A'}],
                'instruments': [{'name': 'solar simulator'}],
            },
            'steps': [
                {
                    'name': 'ageing',
                    'kind': 'stability_series',  # a key of `STEP_READERS`
                    'file': '/full/path/to/02_stability_series.csv',
                    'start': datetime(...),
                    'controlled': ['voltage'],  # optional; the rest was monitored
                },
            ],
            'protocol': {...},  # optional, see below
        }

    Only name each step's file here: its reader in `STEP_READERS` reads it. List the
    steps in the order they ran. If the file does not list them, find them beside it,
    for example the other files in its folder.

    Name the protocol the run followed in `protocol` and `variant` under `run`. If
    your file instead describes the test itself (phases and the values held in each),
    build it with `file_reading_utils.protocol_from_phases` and return it as the
    top-level `protocol`."""
    raise NotImplementedError


# --- Step readers: one per kind of step file; rename, add or delete as you need ------


def read_stability_series_file(path: str | Path) -> dict:
    """Read the stability series at `path`, values recorded over time, and return
    one quantity array per column, named as in a `StabilitySeriesStep`:

        {'time': ..., 'voltage': ..., 'current_density': ..., 'power_density': ...}

    `time` counts from the step's start. The other names you can use are
    `temperature`, `irradiance` and `relative_humidity`. Give current and power as
    positive where the cell delivers power; flip the sign if your files write it the
    other way round."""
    raise NotImplementedError


def read_jv_file(path: str | Path) -> dict:
    """Read the J–V sweep at `path` and return its points, named as in a
    `JVSweepStep`:

        {'voltage': ..., 'current_density': ..., 'direction': ['forward', ...]}

    Give current as positive where the cell delivers power. If your file also holds
    what the J–V station reported for each scan, add it as `figures_of_merit`: one
    array per column (`direction`, `efficiency`, `open_circuit_voltage`, ...), one row
    per scan."""
    raise NotImplementedError


#: Your step readers, by the kind of step each reads: a key of `STEP_KINDS` in
#: `schema_packages/measurement.py`, which lists every kind the plugin can hold. Each
#: reader takes a file's `path` and returns its data by the names of that step's
#: quantities. For a new kind of measurement, such as PL, the kind is first added to
#: `STEP_KINDS` with its step class; then add its reader here.
STEP_READERS = {
    'stability_series': read_stability_series_file,
    'jv': read_jv_file,
}


# --- Optional: fill in only if you need it, else delete it ---------------------------

#: Only with `derive_stability_protocol_from_stability_run`: the conditions your
#: tests run under that your files do not state, such as
#: `{'temperature': 'RT', 'irradiance': '1000 W/m^2'}`.
ASSUMED_CONDITIONS: dict[str, str] = {}


def derive_stability_protocol_from_stability_run(path: str | Path) -> dict | None:
    """Fill this in if your files neither name nor describe the protocol a run
    followed, so that one is worked out from what was recorded.

    Return it as `read_stability_run` returns its `protocol`: build it with
    `protocol_from_phases(..., assumed=ASSUMED_CONDITIONS)`, and say in its `notes`
    every value you assumed or worked out instead of read. Return `None` for a file
    that is not a run file."""
    return None


def read_collection_all_measurements_on_device(path: str | Path) -> dict | None:
    """Fill this in to collect a device's whole history in one entry: all its runs,
    and any measurements taken outside a run, such as J–V scans in between.

    Choose one file per device to stand for it, for example the run file of its first
    run. For that file, return

        {
            'name': 'AI14-1A',
            'time_zone': 'Europe/Rome',
            'sample': {'name': 'AI14-1A', 'lab_id': 'AI14-1A', 'cell_area': ...},
            'runs': ['/full/path/to/run/file', ...],
            'steps': [...],  # the measurements outside any run, as in a run's steps
        }

    and `None` for every other file. Then, in `read_stability_run`, name that file in
    each run's sample, as `{'name': ..., 'lab_id': ..., 'file': '/full/path'}`, so the
    run refers to the device's sample entry."""
    return None
