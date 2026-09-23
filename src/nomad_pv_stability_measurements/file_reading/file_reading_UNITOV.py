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
"""

import re
from pathlib import Path

from nomad.units import ureg

from nomad_pv_stability_measurements.file_reading.file_reading_utils import (
    jv_from_side_by_side,
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
    """Not built yet."""
    raise NotImplementedError


def is_stability_series_file(path: str | Path) -> bool:
    """A UNITOV tracking series, by its name: `..._Stability (Tracking)_<device>.txt`."""
    return _kind(path) == 'Tracking'


def is_jv_file(path: str | Path) -> bool:
    """A UNITOV J–V sweep, by its name: `..._Stability (JV)_<device>.txt`."""
    return _kind(path) == 'JV'


def read_protocol(path: str | Path) -> dict:
    """Not built yet."""
    raise NotImplementedError


def read_embedded_protocol(path: str | Path) -> dict | None:
    """Not built yet."""
    raise NotImplementedError


def read_collection(path: str | Path) -> dict | None:
    """Not built yet."""
    raise NotImplementedError


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
