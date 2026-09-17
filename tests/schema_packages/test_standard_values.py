"""Values a standard names (Design.md §17.2)."""

import pytest
from nomad.units import ureg

from nomad_pv_stability_measurements.schema_packages.standard_values import (
    Dark,
    RoomTemperature,
    StandardValue,
)


def test_the_base_names_no_unit_and_each_value_declares_its_own():
    quantities = StandardValue.m_def.all_quantities

    assert {'name', 'value', 'tolerance'} <= set(quantities)
    assert quantities['value'].unit is None
    assert RoomTemperature.m_def.all_quantities['value'].unit == ureg.kelvin


def test_room_temperature_is_isos_table_1s_ambient():
    # "Ambient (23 ± 4 °C)": the one figure the table gives for it (§17.2).
    room = RoomTemperature()

    assert room.name == 'room temperature'
    assert room.value.to(ureg.degC).magnitude == pytest.approx(23)
    # A difference, so kelvin — 4 K, never 277.15 K (§17.4).
    assert room.tolerance.to(ureg.kelvin).magnitude == pytest.approx(4)


def test_dark_is_exact():
    dark = Dark()

    assert dark.name == 'dark'
    assert dark.value.to(ureg.watt / ureg.meter**2).magnitude == pytest.approx(0)
    assert dark.tolerance is None


def test_a_standard_value_is_no_step():
    # It is resolved into a step's fields by the parser, never stored as one (§17.3).
    assert {'monitor', 'control', 'estimated_duration'}.isdisjoint(
        RoomTemperature.m_def.all_quantities
    )
