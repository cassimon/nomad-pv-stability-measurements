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


def read_csv_with_units_in_header(path: str | Path) -> dict[str, object]:
    """A CSV whose header names each column and its unit, as `temperature (°C)`.

    One entry per column in the order written, by the column's name: a quantity array
    where the header states a unit, an array of text where it does not. A unit that
    cannot be read raises a `ValueError` naming the column.
    """
    with Path(path).open(newline='', encoding='utf-8') as file:
        header, *rows = list(csv.reader(file))
    columns = list(zip(*rows)) if rows else [()] * len(header)
    return dict(_read_column(title, cells) for title, cells in zip(header, columns))


def as_datetime(value) -> datetime:
    """A date from YAML: YAML reads an unquoted date itself; a quoted one is ISO
    text, as `2026-03-02T09:00:00+01:00`."""
    return value if isinstance(value, datetime) else datetime.fromisoformat(value)


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
