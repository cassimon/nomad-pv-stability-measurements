"""Reading the stability runs of one institution: UNITOV, the University of Rome Tor
Vergata.

The interface of `file_reading_TEMPLATE.py`, filled in for UNITOV's files.

UNITOV's station writes a run as a folder, one per pixel and start time, with no file
that lists the steps:

    AI14/AI14_1A/17.23.47/
        0000_2025-11-20_17.23.47_Stability (Tracking)_AI14-1A.txt     the series
        0000_2025-11-20_17.23.47_Stability (Parameters)_AI14-1A.txt   figures over time
        0001_2025-11-20_17.23.47_Stability (JV)_AI14-1A.txt           one J–V sweep each
        0002_2025-11-20_17.23.47_Stability (JV)_AI14-1A.txt

Every file is tab-separated text in Latin-1, as `## Header ##`, with `[Section]` blocks
of `key<TAB>value` lines, then `## Data ##` and its tables. A J–V file holds two
tables, an empty row between them: the figures of merit the station reported, one row
per scan, with the units in a row of their own; then the curve, the forward and the
reverse scan side by side.

The station labels the resistances `Ohm`; they are per area, in Ω·cm².

The Tracking file stands for the run: its header says who ran it, on which device and
channel, when it started, and how the load was tracked. The Parameters file logs what
the station reported of every J–V scan, by hours since the start; its row `N` is the
scan of the file numbered `N`. A row whose J–V file is missing becomes a scan with its
figures of merit only, so that no scan is lost. Times are local to Rome.

A pixel's folder is one device, and its whole history one collection: its runs, and
the scans in folders without a Tracking file. The Tracking file of its first run stands
for the collection and its sample; a device without runs is collected from its first
file. `W cell area` and `#W cells` of the `[Cell Settings]` have no place in a sample
yet and are left out.
"""

import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from nomad.units import ureg

from nomad_pv_stability_measurements.file_reading.file_reading_utils import (
    jv_from_side_by_side,
    protocol_from_phases,
    read_text,
    rename_columns,
    table_with_units_in_header,
)

INSTITUTION = 'UNITOV'

#: UNITOV's standard conditions, which its files do not state.
ASSUMED_CONDITIONS: dict[str, str] = {
    'temperature': 'RT',
    'irradiance': '1000 W/m^2',
}

_FILE_NAME = re.compile(
    r'\d{4}_\d{4}-\d{2}-\d{2}_\d{2}\.\d{2}\.\d{2}_Stability '
    r'\((?P<kind>Tracking|Parameters|JV)\)_.+\.txt'
)
_TIME_ZONE = ZoneInfo('Europe/Rome')
#: What was controlled under each tracking algorithm, by its name in lower case.
_CONTROLLED = {'fixed voltage': ['voltage']}
#: A column title of the Parameters file: `Voc (V) FW`.
_PARAMETER = re.compile(r'(?P<name>.+?)\s*\((?P<unit>[^()]*)\)\s*(?P<scan>FW|RV)')
_DIRECTIONS = {'FW': 'forward', 'RV': 'reverse'}
_SCAN_ORDERS = {
    'FW': 'forward',
    'RV': 'reverse',
    'FW then RV': 'forward then reverse',
    'RV then FW': 'reverse then forward',
}
#: The figures of merit of a J–V file, by UNITOV's name.
_FIGURES_OF_MERIT = {
    'Scan': 'direction',
    'Voc': 'open_circuit_voltage',
    'Jsc': 'short_circuit_current_density',
    'V_MPP': 'potential_at_maximum_power_point',
    'J_MPP': 'current_density_at_maximum_power_point',
    'P_MPP': 'power_density_at_maximum_power_point',
    'Rs': 'series_resistance',
    'R//': 'shunt_resistance',
    'FF': 'fill_factor',
    'Eff': 'efficiency',
    # As the Parameters file names them.
    'Fill Factor': 'fill_factor',
    'Efficiency': 'efficiency',
}
#: The units the station labels wrongly, by the schema's name.
_UNITS_MEANT = {'series_resistance': 'ohm*cm^2', 'shunt_resistance': 'ohm*cm^2'}
#: The J–V settings, by UNITOV's key, as the schema's name and the unit the key names.
_JV_SETTINGS = {
    'Vmin (V)': ('voltage_start', 'V'),
    'Vmax (V)': ('voltage_stop', 'V'),
    'Voltage Step (mV)': ('voltage_step', 'mV'),
    'Scan Rate (mV/s)': ('scan_rate', 'mV/s'),
}
#: The columns of a tracking series, by UNITOV's title, as the schema's name and unit.
_SERIES = {
    'Time (Hours)': ('time', 'h'),
    'Voltage (V)': ('voltage', 'V'),
    'Current Density (mA/cm²)': ('current_density', 'mA/cm^2'),
    'Power (mW/cm²)': ('power_density', 'mW/cm^2'),
}
#: The tracker's settings, by UNITOV's key, as the schema's name and unit.
_TRACKING_SETTINGS = {
    'dV track (V)': ('tracking_step', 'V'),
    'track delay (s)': ('tracking_delay', 's'),
}
#: Tracking settings of the run, not of the series: `read_protocol` reads them.
_TRACKING_SETTINGS_OF_RUN = {
    'JV interval (min)',
    'Test duration (min)',
    'Start-up Time',
}
#: J–V settings of the instrument, not of the sweep, which have no place and are left
#: out knowingly. `Auto-detect Voc` is why a scan can end before `Vmax`.
_JV_SETTINGS_NOT_READ = {
    'Auto-detect Voc',
    'Voltage Range (V)',
    'Current Range (V)',
    'Inverted',
    'Auto-range',
}


def is_protocol_file(path: str | Path, content: str) -> bool:
    """A UNITOV Tracking file, which stands for its run: named
    `..._Stability (Tracking)_<device>.txt`, and saying `Test	Stability (Tracking)`."""
    return _kind(path) == 'Tracking' and bool(
        re.search(r'^Test\tStability \(Tracking\)\s*$', content, re.M)
    )


def is_stability_series_file(path: str | Path) -> bool:
    """A UNITOV tracking series, by its name: `..._Stability (Tracking)_<device>.txt`."""
    return _kind(path) == 'Tracking'


def is_jv_file(path: str | Path) -> bool:
    """A UNITOV J–V sweep, by its name: `..._Stability (JV)_<device>.txt`."""
    return _kind(path) == 'JV'


def read_protocol(path: str | Path) -> dict:
    """The run the Tracking file at `path` stands for, with the other files of its
    folder as its steps: the tracking series, one J–V sweep per J–V file, and a scan
    with its figures of merit only for each row of the Parameters file whose J–V file
    is missing. The steps are in the order they started."""
    path = Path(path)
    header, _ = _read_sections(path)
    info = header.get('General info', {})
    tracking = header.get('Tracking Settings', {})
    start = _local(tracking['Start-up Time'], '%H:%M:%S %d/%m/%Y')
    run = {
        'institution': INSTITUTION,
        'name': f'{info.get("Device")}, {start:%Y-%m-%d %H:%M:%S}',
        'operator': info.get('User'),
        'start': start,
        'samples': [
            {
                'name': info.get('Device'),
                'lab_id': info.get('Device'),
                'file': str(_anchor(path)),
            }
        ],
        'instruments': [{'name': info.get('Note')}],
    }
    series = {
        'name': 'tracking',
        'kind': 'stability_series',
        'file': str(path),
        'start': start,
    }
    algorithm = tracking.get('Algorithm', '').lower()
    if algorithm in _CONTROLLED:
        series['controlled'] = _CONTROLLED[algorithm]
    scans = _scans(path.parent)
    steps = [series, *scans]
    return {
        'run': {key: value for key, value in run.items() if value is not None},
        'steps': sorted(steps, key=lambda step: step['start']),
    }


def read_embedded_protocol(path: str | Path) -> dict | None:
    """`None`: no UNITOV file states the test a run was to be (`derive_protocol`)."""
    return None


def derive_protocol(path: str | Path) -> dict | None:
    """The test the Tracking file at `path` shows: one phase, as long as its
    `Test duration`, holding the load as its `Algorithm` says, under UNITOV's
    `ASSUMED_CONDITIONS`. No file states the voltage a `Fixed Voltage` run holds, so
    it is the mean of the recorded voltage, rounded to 1 mV; the `notes` say so, and
    name the conditions assumed. A J–V scan every `JV interval`, set up as the run's
    Parameters file says. `None` for any other file."""
    if _kind(path) != 'Tracking':
        return None
    header, _ = _read_sections(path)
    tracking = header.get('Tracking Settings', {})
    duration = f'{float(tracking["Test duration (min)"]):g} min'
    algorithm = tracking.get('Algorithm', '')
    phase = {'name': 'tracking', 'duration': duration}
    notes = []
    if algorithm.lower() == 'fixed voltage':
        recorded = read_stability_series(path)['voltage'].to('V').magnitude
        phase['voltage'] = f'{recorded.mean():.3f} V'
        notes.append(
            'The voltage held is the mean of the recorded voltage, as no file states '
            'it.'
        )
        name = f'Fixed voltage at {phase["voltage"]} for {duration}'
    elif 'mpp' in algorithm.lower() or 'perturb' in algorithm.lower():
        phase['electrical_load'] = 'mpp'
        name = f'MPP tracking for {duration}'
    else:
        notes.append(f'The tracking algorithm `{algorithm}` is not read into the plan.')
        name = f'{algorithm} for {duration}'
    scans = _jv_scans(Path(path).parent, tracking.get('JV interval (min)'))
    if scans:
        phase['jv_scan'] = scans
    return protocol_from_phases(
        name,
        [phase],
        assumed=ASSUMED_CONDITIONS,
        **({'notes': ' '.join(notes)} if notes else {}),
    )


def read_collection(path: str | Path) -> dict | None:
    """The collection of the device the file at `path` was measured on, if this file
    stands for it: the Tracking file of the device's first run, or, for a device
    without runs, its first file. `None` for every other file.

    A device is a pixel's folder, `AI14/AI14_1A/`, with one folder per start time. A
    folder with a Tracking file is a run; the files of any other are the device's
    loose measurements, its scans outside any run, which become the collection's own
    steps."""
    path = Path(path)
    if _kind(path) is None or _anchor(path) != path:
        return None
    header, _ = _read_sections(path)
    info = header.get('General info', {})
    cell = header.get('Cell Settings', {})
    sample = {
        'name': info.get('Device'),
        'lab_id': info.get('Device'),
        'cell_area': _number_in(cell.get('Cell Area (cm2)'), 'cm^2'),
        'typology': cell.get('Tipology'),
        'number_of_cells': int(float(cell['#Cells'])) if '#Cells' in cell else None,
    }
    runs = [folder for folder in _folders(path) if _tracking(folder)]
    loose = [folder for folder in _folders(path) if not _tracking(folder)]
    return {
        'name': info.get('Device'),
        'sample': {key: value for key, value in sample.items() if value is not None},
        'runs': [str(_tracking(folder)) for folder in runs],
        'steps': sorted(
            (step for folder in loose for step in _scans(folder, folder.name)),
            key=lambda step: step['start'],
        ),
    }


def read_stability_series(path: str | Path) -> dict[str, object]:
    """The tracking series at `path`: `time` since the start, `voltage`,
    `current_density` and `power_density`, one value per sample, and the tracker's
    `[Tracking Settings]` as `settings`. A column or setting that is neither read nor
    known to belong elsewhere is handed back under its own name, so that reading the
    measurement reports it."""
    header, [series] = _read_sections(path)
    titles, *rows = _trimmed(series)
    columns = {
        title.strip(): [row[index].strip() for row in rows]
        for index, title in enumerate(titles)
    }
    return {
        **rename_columns(
            columns,
            {title: name for title, (name, _) in _SERIES.items()},
            {name: unit for name, unit in _SERIES.values()},
        ),
        'settings': _tracking_settings(header.get('Tracking Settings', {})),
    }


def read_jv_file(path: str | Path) -> dict[str, object]:
    """The J–V sweep at `path`: the curve, one row per point, the forward and the
    reverse scan in the order the header's `Scan direction` names; the figures of
    merit the station reported, one row per scan; and the `[JV Settings]` as
    `settings`. A setting that is neither read nor known to be left out is handed back
    under its own name, so that reading the measurement reports it."""
    header, tables = _read_sections(path)
    reported, curve = tables
    settings = _jv_settings(header.get('JV Settings', {}))
    curve = table_with_units_in_header(*_trimmed(curve))
    scans = {
        _DIRECTIONS[short]: (curve[f'V_{short}'], curve[f'J_{short}'])
        for short in ('FW', 'RV')
    }
    if settings.get('scan_order') == 'reverse then forward':
        scans = dict(reversed(scans.items()))
    return {
        **jv_from_side_by_side(scans),
        'figures_of_merit': _figures_of_merit(reported),
        'settings': settings,
    }


def _read_sections(path: str | Path) -> tuple[dict[str, dict[str, str]], list]:
    """A UNITOV file as its header, `{section: {key: value}}`, and the tables of its
    data, each a list of rows of cells as text, split at rows with no text."""
    header, tables, section, table = {}, [], None, []
    part = None
    for line in read_text(path).splitlines():
        if line.strip() in {'## Header ##', '## Data ##'}:
            part = line.strip()
            continue
        cells = line.split('\t')
        if part == '## Header ##':
            if line.startswith('[') and line.strip().endswith(']'):
                section = line.strip()[1:-1]
                header[section] = {}
            elif line.strip() and section is not None:
                header[section][cells[0].strip()] = '\t'.join(cells[1:]).strip()
        elif part == '## Data ##':
            if any(cell.strip() for cell in cells):
                table.append(cells)
            elif table:
                tables.append(table)
                table = []
    if table:
        tables.append(table)
    return header, tables


def _scans(folder: Path, label: str | None = None) -> list[dict]:
    """The J–V scans of a folder, as steps: one per J–V file, and one with its figures
    of merit only for each row of a Parameters file whose J–V file is missing. Each
    named by its number, and by `label` where given."""
    scans = {}

    def named(number: int) -> str:
        return f'J–V {number}' + (f', {label}' if label else '')

    for file in sorted(folder.iterdir()):
        if is_jv_file(file):
            general = _read_sections(file)[0].get('General info', {})
            scans[_number(file)] = {
                'name': named(_number(file)),
                'kind': 'jv',
                'file': str(file),
                'start': _started(general),
            }
    for file in sorted(folder.iterdir()):
        if _kind(file) != 'Parameters':
            continue
        header, _ = _read_sections(file)
        start = _started(header.get('General info', {}))
        settings = _jv_settings(header.get('JV Settings', {}))
        for number, (hours, reported) in enumerate(_read_parameters(file), start=1):
            scans.setdefault(
                number,
                {
                    'name': named(number),
                    'kind': 'jv',
                    'start': start + timedelta(hours=hours),
                    'figures_of_merit': reported,
                    'settings': settings,
                },
            )
    return list(scans.values())


def _folders(path: Path) -> list[Path]:
    """The folders of the device `path` was measured on, one per start time, in the
    order they started."""
    return sorted(
        (folder for folder in path.parent.parent.iterdir() if folder.is_dir()),
        key=lambda folder: (
            min(map(_started_by_name, _files(folder)), default=''),
            folder,
        ),
    )


def _files(folder: Path) -> list[Path]:
    return sorted(file for file in folder.iterdir() if _kind(file) is not None)


def _tracking(folder: Path) -> Path | None:
    return next((file for file in _files(folder) if _kind(file) == 'Tracking'), None)


def _anchor(path: Path) -> Path | None:
    """The file that stands for the collection of the device `path` was measured on:
    the Tracking file of its first run, or else its first file."""
    folders = [folder for folder in _folders(Path(path)) if _files(folder)]
    runs = [_tracking(folder) for folder in folders if _tracking(folder)]
    if runs:
        return runs[0]
    return _files(folders[0])[0] if folders else None


def _started_by_name(path: Path) -> str:
    """When a file's measurement started, as its name says: `2025-11-20_17.23.47`."""
    return '_'.join(Path(path).name.split('_')[1:3])


def _started(general: dict[str, str]) -> datetime:
    """When a file's measurement started, as the `Date` and `Time` of its header."""
    return _local(f'{general["Date"]} {general["Time"]}', '%Y-%m-%d %H:%M:%S')


def _number_in(text: str | None, unit: str):
    return None if text is None else ureg.Quantity(float(text), unit)


def _read_parameters(path: str | Path) -> list[tuple[float, dict[str, object]]]:
    """Each row of a Parameters file: the hours since the start, and the figures of
    merit of its forward and reverse scan, as `read_jv_file` hands them back.

    The station writes the time again before the reverse scan's figures, without a
    title of its own; that column is left out."""
    _, [table] = _read_sections(path)
    titles, *rows = table
    titles = [title.strip() for title in titles if title.strip()]
    columns = {'FW': [], 'RV': []}
    for index, title in enumerate(titles[1:], start=1):
        match = _PARAMETER.fullmatch(title)
        if match is not None:
            unit = match.group('unit').replace('cm2', 'cm^2')
            columns[match.group('scan')].append((index, match.group('name'), unit))
    read = []
    for row in rows:
        cells = [cell.strip() for cell in row]
        if len([cell for cell in cells if cell]) == len(titles) + 1:
            # The untitled time before the reverse scan's figures.
            first_reverse = columns['RV'][0][0]
            del cells[first_reverse]
        names = ['Scan'] + [name for _, name, _ in columns['FW']]
        units = [''] + [unit for _, _, unit in columns['FW']]
        scans = [
            [scan] + [cells[index] for index, _, _ in columns[scan]]
            for scan in ('FW', 'RV')
        ]
        read.append((float(cells[0]), _figures_of_merit([names, units, *scans])))
    return read


def _number(path: str | Path) -> int:
    """The number a file's name starts with: `2` of `0002_...`."""
    return int(Path(path).name.split('_')[0])


def _local(text: str, form: str) -> datetime:
    """A time as the station writes it, in Rome's time zone."""
    return datetime.strptime(text.strip(), form).replace(tzinfo=_TIME_ZONE)


def _kind(path: str | Path) -> str | None:
    match = _FILE_NAME.fullmatch(Path(path).name)
    return match.group('kind') if match else None


def _trimmed(rows: list[list[str]]) -> list[list[str]]:
    """The rows without the columns that have no title."""
    kept = [index for index, title in enumerate(rows[0]) if title.strip()]
    return [[row[index] if index < len(row) else '' for index in kept] for row in rows]


def _figures_of_merit(rows: list[list[str]]) -> dict[str, object]:
    """The table of figures of merit, its units in the row below the names."""
    names, units, *values = _trimmed(rows)
    columns = {
        name.strip(): [row[index].strip() for row in values]
        for index, name in enumerate(names)
    }
    columns['Scan'] = [_DIRECTIONS.get(scan, scan) for scan in columns['Scan']]
    stated = {
        _FIGURES_OF_MERIT.get(name.strip(), name.strip()): unit.strip()
        for name, unit in zip(names, units)
        if unit.strip()
    }
    return rename_columns(columns, _FIGURES_OF_MERIT, {**stated, **_UNITS_MEANT})


def _jv_scans(folder: Path, interval: str | None) -> dict:
    """The J–V scans of a run as its protocol writes them: every `JV interval`, with
    the `[JV Settings]` of the run's Parameters file."""
    scans = {} if interval is None else {'every': f'{float(interval):g} min'}
    for file in sorted(folder.iterdir()):
        if _kind(file) == 'Parameters':
            section = _read_sections(file)[0].get('JV Settings', {})
            for key, (name, unit) in _JV_SETTINGS.items():
                if key in section:
                    scans[name] = f'{float(section[key]):g} {unit}'
            if section.get('Scan direction') in _SCAN_ORDERS:
                scans['scan_order'] = _SCAN_ORDERS[section['Scan direction']]
            break
    return scans


def _tracking_settings(section: dict[str, str]) -> dict[str, object]:
    settings = {}
    for key, value in section.items():
        if key in _TRACKING_SETTINGS:
            name, unit = _TRACKING_SETTINGS[key]
            settings[name] = ureg.Quantity(float(value), unit)
        elif key == 'Algorithm':
            settings['tracking_algorithm'] = value.lower()
        elif key not in _TRACKING_SETTINGS_OF_RUN:
            settings[key] = value
    return settings


def _jv_settings(section: dict[str, str]) -> dict[str, object]:
    settings = {}
    for key, value in section.items():
        if key in _JV_SETTINGS:
            name, unit = _JV_SETTINGS[key]
            settings[name] = ureg.Quantity(float(value), unit)
        elif key == 'Scan direction':
            settings['scan_order'] = _SCAN_ORDERS.get(value, value)
        elif key not in _JV_SETTINGS_NOT_READ:
            settings[key] = value
    return settings
