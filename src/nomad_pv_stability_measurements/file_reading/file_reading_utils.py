"""Reading helpers that several institutions' `file_reading_<INSTITUTION>.py` share.

Plain functions that return plain data, for formats more than one institution writes.
"""

import csv
import re
from datetime import datetime
from pathlib import Path

import numpy as np
import pint
from nomad.units import ureg

from nomad_pv_stability_measurements.parsers.units import split_match_convert

_HEADER_WITH_UNIT = re.compile(r'(?P<name>[^()]+?)\s*\((?P<unit>[^()]+)\)')

#: Each quantity a phase can set, by its name in a `StabilitySeriesStep` where it has
#: one, and how a protocol file writes it.
SET_POINTS = {
    'temperature': {'channel': 'temperature'},
    'irradiance': {'channel': 'irradiation'},
    'relative_humidity': {'channel': 'atmosphere', 'variable': 'relative_humidity'},
    'electrical_load': {'channel': 'electrical_load'},
    'voltage': {'channel': 'electrical_load', 'variable': 'voltage'},
    'current': {'channel': 'electrical_load', 'variable': 'current'},
}


#: The encodings a text file is tried in, in order. Latin-1 decodes any bytes, so it
#: comes last: a file that is not UTF-8 is read as the Latin-1 that older measurement
#: software writes, where `²` is one byte.
ENCODINGS = ('utf-8', 'latin-1')


def read_text(path: str | Path) -> str:
    """The text of the file at `path`, in the first of `ENCODINGS` that decodes it.

    NOMAD rewrites the file an entry is made from as UTF-8 when it is not, but not the
    other files of a run, so one run can hold both."""
    data = Path(path).read_bytes()
    for encoding in ENCODINGS:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError(f'{path} is in none of the encodings {", ".join(ENCODINGS)}.')


def rename_columns(
    table: dict[str, object],
    names: dict[str, str],
    units: dict[str, str] | None = None,
) -> dict[str, object]:
    """`table` with its columns renamed from the lab's names to the schema's, as
    `names` maps them; a column `names` does not name keeps its own, so that reading
    the measurement reports it rather than dropping it.

    `units` gives, by the schema's name, the unit a column of text or plain numbers is
    in, as text: `{'series_resistance': 'ohm*cm^2', 'efficiency': '%'}`; that column is
    read as numbers in it. A lab whose files label a unit wrongly states the right one
    here. An unreadable unit or number raises a `ValueError` naming the column.
    """
    units = units or {}
    renamed = {}
    for title, values in table.items():
        name = names.get(title, title)
        if name in units and not isinstance(values, pint.Quantity):
            renamed[name] = _quantity(title, values, units[name])
        else:
            renamed[name] = values
    return renamed


def jv_from_side_by_side(
    scans: dict[str, tuple[pint.Quantity, pint.Quantity]],
) -> dict[str, object]:
    """A J–V sweep written as one pair of columns per scan, side by side, as
    `read_jv_file` hands it back: one row per point, the scans one after another in
    the order of `scans`, `direction` telling them apart.

    `scans` are `{direction: (voltage, current_density)}`, each a quantity array. The
    scans of a sweep have different lengths, so the shorter columns of such a file end
    in empty cells: points without a number (NaN) are left out."""
    voltages, densities, directions = [], [], []
    for direction, (voltage, density) in scans.items():
        kept = ~(np.isnan(voltage.magnitude) | np.isnan(density.magnitude))
        voltages.append(voltage[kept])
        densities.append(density[kept])
        directions += [direction] * int(kept.sum())
    return {
        'voltage': _joined(voltages, 'V'),
        'current_density': _joined(densities, 'A/m^2'),
        'direction': np.array(directions, dtype=str),
    }


def _joined(parts: list[pint.Quantity], unit: str) -> pint.Quantity:
    return ureg.Quantity(
        np.concatenate([part.to(unit).magnitude for part in parts] or [[]]), unit
    )


def read_csv_with_units_in_header(path: str | Path) -> dict[str, object]:
    """A CSV whose header names each column and its unit, as `temperature (°C)`.

    One entry per column in the order written, by the column's name: a quantity array
    where the header states a unit, with NaN for an empty cell, an array of text where
    it does not. A unit that cannot be read raises a `ValueError` naming the column.
    """
    [table] = read_csv_tables_with_units_in_header(path)
    return table


def read_csv_tables_with_units_in_header(path: str | Path) -> list[dict[str, object]]:
    """A CSV of several tables, one after another, an empty line between two: each
    table as `read_csv_with_units_in_header` reads a file of one, in the order
    written."""
    lines = list(csv.reader(read_text(path).splitlines()))
    tables, table = [], []
    for line in [*lines, []]:
        if any(cell.strip() for cell in line):
            table.append(line)
        elif table:
            tables.append(table_with_units_in_header(*table))
            table = []
    return tables


def table_with_units_in_header(header, *rows) -> dict[str, object]:
    """A table given as its `header` and `rows`, each a list of cells as text, read as
    `read_csv_with_units_in_header` reads a file."""
    columns = list(zip(*rows)) if rows else [()] * len(header)
    return dict(_read_column(title, cells) for title, cells in zip(header, columns))


def as_datetime(value) -> datetime:
    """A date from YAML: YAML reads an unquoted date itself; a quoted one is ISO
    text, as `2026-03-02T09:00:00+01:00`."""
    return value if isinstance(value, datetime) else datetime.fromisoformat(value)


def protocol_from_phases(
    name: str, phases: list[dict], repeat: int = 1, **fields
) -> dict:
    """A protocol, for a run file that describes its test instead of naming a protocol
    file: phases run one after another, the whole sequence `repeat` times.

    Each phase is a dict of its `name`, its `duration` as text (`'20 h'`), and the
    value each quantity is held at, by the quantity's name in `SET_POINTS`, as text or
    a word a protocol file knows:

        {'name': 'light soak', 'duration': '4 h', 'temperature': '85 °C',
         'irradiance': '1000 W/m^2', 'relative_humidity': '85 %',
         'electrical_load': 'mpp'}

    Every quantity held is also monitored, except the light in the dark. `fields` are
    further fields of the protocol, as `notes='...'` or `standard='ISOS-D-3'`.

    Returns what a `*.stability.yaml` file holds, as plain data, for the parser to read
    as it reads such a file. A quantity not in `SET_POINTS`, or a phase without a
    `duration`, raises a `ValueError`.
    """
    return {
        'data': {
            'name': name,
            **fields,
            'routine': {
                'name': name,
                'repeat': repeat,
                'instructions': [_phase(phase) for phase in phases],
            },
        }
    }


def _phase(phase: dict) -> dict:
    held = {
        key: value for key, value in phase.items() if key not in {'name', 'duration'}
    }
    unknown = sorted(set(held) - set(SET_POINTS))
    if unknown:
        raise ValueError(
            f'a phase cannot hold {", ".join(unknown)}: only {", ".join(SET_POINTS)}.'
        )
    if 'duration' not in phase:
        raise ValueError(f'the phase `{phase.get("name")}` states no duration.')
    instructions = []
    for quantity, value in held.items():
        instruction = {**SET_POINTS[quantity], 'hold': value}
        if value != 'dark':
            instruction['monitor'] = True
        # The first sets how long the phase lasts; the others last as long.
        instruction['duration'] = 'whole block' if instructions else phase['duration']
        instructions.append(instruction)
    block = {'repeat': 1, 'mode': 'parallel', 'instructions': instructions}
    return {'name': phase['name'], **block} if 'name' in phase else block


def _read_column(title: str, cells) -> tuple[str, object]:
    match = _HEADER_WITH_UNIT.fullmatch(title.strip())
    if match is None:
        return title.strip(), np.array(cells, dtype=str)
    return match.group('name'), _quantity(title, cells, match.group('unit'))


def _quantity(title: str, cells, unit: str) -> pint.Quantity:
    """`cells` as numbers in `unit`, an empty cell as NaN."""
    try:
        factor, unit = split_match_convert(f'1 {unit}')
        numbers = [
            np.nan if isinstance(cell, str) and not cell.strip() else float(cell)
            for cell in cells
        ]
        return ureg.Quantity(np.array(numbers, dtype=float) * factor, unit)
    except (ValueError, pint.errors.UndefinedUnitError) as error:
        raise ValueError(f'column `{title}` cannot be read: {error}') from error
