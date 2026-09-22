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


def read_csv_with_units_in_header(path: str | Path) -> dict[str, object]:
    """A CSV whose header names each column and its unit, as `temperature (°C)`.

    One entry per column in the order written, by the column's name: a quantity array
    where the header states a unit, an array of text where it does not. A unit that
    cannot be read raises a `ValueError` naming the column.
    """
    [table] = read_csv_tables_with_units_in_header(path)
    return table


def read_csv_tables_with_units_in_header(path: str | Path) -> list[dict[str, object]]:
    """A CSV of several tables, one after another, an empty line between two: each
    table as `read_csv_with_units_in_header` reads a file of one, in the order
    written."""
    with Path(path).open(newline='', encoding='utf-8') as file:
        lines = list(csv.reader(file))
    tables, table = [], []
    for line in [*lines, []]:
        if any(cell.strip() for cell in line):
            table.append(line)
        elif table:
            tables.append(_read_table(*table))
            table = []
    return tables


def _read_table(header, *rows) -> dict[str, object]:
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
    try:
        factor, unit = split_match_convert(f'1 {match.group("unit")}')
        values = np.array(cells, dtype=float) * factor
        return match.group('name'), ureg.Quantity(values, unit)
    except (ValueError, pint.errors.UndefinedUnitError) as error:
        raise ValueError(f'column `{title}` cannot be read: {error}') from error
