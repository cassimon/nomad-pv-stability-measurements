"""Reading helpers the institutions' file readers share."""

import re
from datetime import datetime, timedelta, timezone

import pytest
from nomad.units import ureg

from nomad_pv_stability_measurements.parsers.file_reading_utils import (
    as_datetime,
    read_csv_with_units_in_header,
)


def written(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding='utf-8')
    return path


@pytest.mark.parametrize(
    ('header', 'cell', 'expected'),
    [
        # `h` is an hour here, not Planck's constant.
        ('time (h)', '0.5', 1800 * ureg.second),
        ('temperature (°C)', '65', 338.15 * ureg.kelvin),
        ('relative_humidity (%)', '85', 0.85 * ureg.dimensionless),
        ('irradiance (W/m^2)', '1000', 1000 * ureg('W/m^2')),
        ('current_density (mA/cm^2)', '20', 200 * ureg('A/m^2')),
    ],
)
def test_a_header_unit_makes_a_column_of_quantities(tmp_path, header, cell, expected):
    table = read_csv_with_units_in_header(
        written(tmp_path, 'step.csv', f'{header}\n{cell}\n')
    )
    [(name, values)] = table.items()

    assert name == header.split(' (')[0]
    assert values.to(expected.units).magnitude[0] == pytest.approx(expected.magnitude)


def test_a_table_holds_only_the_columns_written(tmp_path):
    table = read_csv_with_units_in_header(
        written(tmp_path, 'step.csv', 'time (h),temperature (°C)\n')
    )

    assert list(table) == ['time', 'temperature']
    assert table['time'].magnitude.size == 0


def test_a_header_without_unit_makes_a_column_of_text(tmp_path):
    table = read_csv_with_units_in_header(
        written(tmp_path, 'jv.csv', 'voltage (V),direction\n0.1,reverse\n')
    )

    assert list(table['direction']) == ['reverse']
    assert table['voltage'].units == ureg.volt


@pytest.mark.parametrize(
    ('header', 'fragment'),
    [('temperature (wibbles)', 'temperature (wibbles)'), ('rh (%RH)', 'rh (%RH)')],
)
def test_an_unreadable_unit_names_its_column(tmp_path, header, fragment):
    with pytest.raises(ValueError, match=re.escape(fragment)):
        read_csv_with_units_in_header(written(tmp_path, 'step.csv', f'{header}\n1\n'))


@pytest.mark.parametrize(
    'value',
    [
        '2026-03-02T09:00:00+01:00',
        datetime(2026, 3, 2, 9, tzinfo=timezone(timedelta(hours=1))),
    ],
)
def test_a_date_is_read_quoted_or_not(value):
    assert as_datetime(value) == datetime(
        2026, 3, 2, 9, tzinfo=timezone(timedelta(hours=1))
    )
