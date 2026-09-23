"""Reading helpers the institutions' file readers share."""

import re
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from nomad.datamodel import EntryArchive
from nomad.units import ureg

from nomad_pv_stability_measurements.file_reading.file_reading_utils import (
    as_datetime,
    cumulative_protocol,
    jv_from_side_by_side,
    protocol_from_phases,
    read_csv_with_units_in_header,
    read_text,
    rename_columns,
)
from nomad_pv_stability_measurements.parsers.translate import translate
from nomad_pv_stability_measurements.schema_packages.base_instructions import (
    MonitorControlInstruction,
)
from nomad_pv_stability_measurements.schema_packages.protocol import StabilityProtocol


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


@pytest.mark.parametrize('encoding', ['utf-8', 'latin-1'])
def test_a_file_is_read_in_utf8_or_else_latin1(tmp_path, encoding):
    path = tmp_path / 'series.txt'
    path.write_bytes('J (mA/cm²)'.encode(encoding))

    assert read_text(path) == 'J (mA/cm²)'


def test_columns_are_renamed_to_the_schema_and_read_in_the_unit_stated():
    table = {
        'Rs': np.array(['12.5', '13.0']),
        'Voc': [1.1, 1.09] * ureg.volt,
        'Remark': np.array(['ok', 'ok']),
    }

    renamed = rename_columns(
        table,
        {'Rs': 'series_resistance', 'Voc': 'open_circuit_voltage'},
        units={'series_resistance': 'ohm*cm^2'},
    )

    assert list(renamed) == ['series_resistance', 'open_circuit_voltage', 'Remark']
    assert renamed['series_resistance'].to('ohm*m^2').magnitude == pytest.approx(
        [12.5e-4, 13.0e-4]
    )
    # A column the lab named otherwise keeps its name, to be reported, not dropped.
    assert renamed['Remark'].tolist() == ['ok', 'ok']


def test_a_sweep_written_side_by_side_is_one_row_per_point_in_the_order_swept():
    forward = [-0.1, 0.5, 0.7] * ureg.volt, [20.0, 18.0, 1.0] * ureg('mA/cm^2')
    # The shorter scan's column ends in empty cells.
    reverse = [0.7, 0.5, np.nan] * ureg.volt, [1.0, 18.5, np.nan] * ureg('mA/cm^2')

    sweep = jv_from_side_by_side({'forward': forward, 'reverse': reverse})

    assert sweep['direction'].tolist() == ['forward'] * 3 + ['reverse'] * 2
    assert sweep['voltage'].to('V').magnitude.tolist() == [-0.1, 0.5, 0.7, 0.7, 0.5]
    assert sweep['current_density'].to('mA/cm^2').magnitude[-1] == pytest.approx(18.5)


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


def test_phases_make_a_protocol_run_in_sequence_and_repeated(log):
    document = protocol_from_phases(
        'Day and night',
        [
            {'name': 'day', 'duration': '12 h', 'irradiance': '1000 W/m^2'},
            {'name': 'night', 'duration': '12 h', 'irradiance': 'dark'},
        ],
        repeat=7,
        notes='A lab test.',
    )
    translation = translate(document)
    protocol = StabilityProtocol.m_from_dict(translation.archive['data'])
    for section in protocol.m_all_contents(depth_first=True, include_self=True):
        section.normalize(EntryArchive(), log)
    monitored = [
        each.monitor
        for each in protocol.m_all_contents()
        if isinstance(each, MonitorControlInstruction)
    ]

    assert translation.problems == []
    assert log.errors == []
    assert protocol.seconds() == 7 * 24 * 3600
    assert protocol.notes == 'A lab test.'
    # Held and monitored, except the light in the dark.
    assert monitored == [True, None]


def test_a_collection_follows_a_protocol_that_specifies_nothing(log):
    translation = translate(cumulative_protocol())
    protocol = StabilityProtocol.m_from_dict(translation.archive['data'])
    for section in protocol.m_all_contents(depth_first=True, include_self=True):
        section.normalize(EntryArchive(), log)

    assert translation.problems == [] and log.errors == [] and log.warnings == []
    assert protocol.instructions == []
    assert protocol.duration.kind == 'open_ended'


def test_assumed_conditions_fill_only_what_a_phase_leaves_out_and_are_said():
    document = protocol_from_phases(
        'Soak',
        [{'name': 'soak', 'duration': '1 h', 'temperature': '65 °C'}],
        assumed={'temperature': 'RT', 'irradiance': '1000 W/m^2'},
    )

    data = document['data']
    [phase] = data['routine']['instructions']
    held = {each['channel']: each for each in phase['instructions']}
    assert held['temperature']['specify'] == '65 °C'
    # Assumed, so never recorded: held, not monitored.
    assert (held['irradiation']['specify'], 'monitor' in held['irradiation']) == (
        '1000 W/m^2',
        False,
    )
    assert 'irradiance 1000 W/m^2' in data['notes']
    assert 'temperature' not in data['notes']


@pytest.mark.parametrize(
    ('phase', 'fragment'),
    [
        ({'name': 'soak', 'duration': '1 h', 'pressure': '1 bar'}, 'pressure'),
        ({'name': 'soak', 'temperature': '85 °C'}, 'no duration'),
    ],
)
def test_a_phase_that_cannot_be_written_raises(phase, fragment):
    with pytest.raises(ValueError, match=fragment):
        protocol_from_phases('test', [phase])
