"""The monitor/control instructions: one class per quantity and kind, and the values a
standard names (Design.md §15.11, §17, §20.3, §22)."""

import pytest
from nomad.units import ureg

from nomad_pv_stability_measurements.schema_packages.hold_below_instructions import (
    HoldBelowRelativeHumidity,
    HoldBetweenIrradiance,
)
from nomad_pv_stability_measurements.schema_packages.hold_instructions import (
    BalanceGas,
    HoldAbsoluteHumidity,
    HoldCurrent,
    HoldIrradiance,
    HoldPressure,
    HoldRelativeHumidity,
    HoldResistance,
    HoldTemperature,
    HoldVoltage,
)
from nomad_pv_stability_measurements.schema_packages.mpp_instructions import (
    MPPTracking,
    VOCTracking,
)
from nomad_pv_stability_measurements.schema_packages.ramp_instructions import (
    RampTemperature,
)
from nomad_pv_stability_measurements.schema_packages.routine import (
    HoldBelowInstruction,
    HoldBetweenInstruction,
    HoldInstruction,
    MonitorControlInstruction,
    RampInstruction,
)
from nomad_pv_stability_measurements.schema_packages.standard_values import (
    Dark,
    RoomTemperature,
)

K = ureg.kelvin


@pytest.mark.parametrize(
    ('cls', 'field', 'unit'),
    [
        (HoldTemperature, 'set_point', 'K'),
        (HoldTemperature, 'set_point_tolerance', 'K'),
        (HoldIrradiance, 'set_point', 'W/m^2'),
        (HoldVoltage, 'set_point', 'V'),
        (HoldCurrent, 'set_point', 'A'),
        (HoldResistance, 'set_point', 'ohm'),
        (HoldPressure, 'set_point', 'Pa'),
        # The atmosphere as a volume ratio, the relative humidity as the fraction (§20.6).
        (HoldAbsoluteHumidity, 'set_point', 'dimensionless'),
        (HoldRelativeHumidity, 'set_point', 'dimensionless'),
        (HoldBelowRelativeHumidity, 'upper_bound', 'dimensionless'),
        (HoldBetweenIrradiance, 'lower_bound', 'W/m^2'),
        (RampTemperature, 'ramp_rate', 'K/s'),
    ],
)
def test_each_class_declares_the_unit_of_its_quantity(cls, field, unit):
    declared = cls.m_def.all_quantities[field].unit

    assert (1 * declared).to(unit).magnitude == pytest.approx(1)


def test_every_quantity_that_can_be_held_can_also_be_ramped():
    holds = {
        cls.__name__.removeprefix('Hold') for cls in HoldInstruction.__subclasses__()
    }
    ramps = {
        cls.__name__.removeprefix('Ramp') for cls in RampInstruction.__subclasses__()
    }

    assert holds == ramps


@pytest.mark.parametrize('cls', [MPPTracking, VOCTracking, BalanceGas])
def test_what_the_cell_decides_or_names_takes_no_set_point(cls):
    assert 'set_point' not in cls.m_def.all_quantities


@pytest.mark.parametrize(
    ('cls', 'points'),
    [
        (HoldVoltage, ['V_MPP', 'near V_MPP', 'V_oc', '-V_oc']),
        (HoldCurrent, ['J_SC', '-J_MPP']),
    ],
)
def test_a_bias_may_be_a_point_of_the_device_and_only_a_known_one(cls, points):
    for point in points:
        assert cls(reference_point=point).reference_point == point
    with pytest.raises(ValueError):
        cls(reference_point='E_g/q')


@pytest.mark.parametrize(
    ('written', 'derived', 'expected'),
    [
        ({'sample_every': 60 * ureg.second}, 'sampling_rate', 1 / 60),
        ({'sampling_rate': 10 * ureg.hertz}, 'sample_every', 0.1),
    ],
)
def test_either_sampling_figure_gives_the_other(normalized, written, derived, expected):
    instruction = normalized(HoldTemperature(**written))

    assert getattr(instruction, derived).magnitude == pytest.approx(expected)


@pytest.mark.parametrize(
    'cls',
    [
        MonitorControlInstruction,
        HoldInstruction,
        HoldBelowInstruction,
        HoldBetweenInstruction,
        RampInstruction,
    ],
)
def test_a_base_that_names_no_quantity_is_reported(normalized, log, cls):
    normalized(cls(name='stray'))

    [error] = log.errors
    assert f'stray is a bare `{cls.__name__}`' in error


# A ramp (§15.11, §21.2).


@pytest.mark.parametrize(
    ('written', 'field', 'expected'),
    [
        ({'estimated_duration': 3600 * ureg.second}, 'ramp_rate', 60 / 3600),
        ({'ramp_rate': 60 * K / ureg.hour}, 'estimated_duration', 3600),
    ],
)
def test_a_ramp_derives_its_rate_or_its_duration(
    normalized, log, written, field, expected
):
    ramp = normalized(
        RampTemperature(start_point=358.15 * K, end_point=298.15 * K, **written)
    )

    # The rate is a magnitude; the direction is the ends.
    assert getattr(ramp, field).magnitude == pytest.approx(expected)
    assert log.errors == []


def test_a_rate_that_contradicts_the_duration_is_reported_not_repaired(normalized, log):
    ramp = normalized(
        RampTemperature(
            start_point=298.15 * K,
            end_point=358.15 * K,
            ramp_rate=60 * K / ureg.hour,
            estimated_duration=7200 * ureg.second,
        )
    )

    assert ramp.estimated_duration.magnitude == pytest.approx(7200)
    [error] = log.errors
    assert '`ramp_rate`' in error


def test_a_cycle_states_no_path_so_it_takes_no_rate(normalized, log):
    ramp = normalized(
        RampTemperature(
            start_point=296.15 * K,
            end_point=338.15 * K,
            end_of_ramp_behavior='cycle',
            ramp_rate=60 * K / ureg.hour,
        )
    )

    assert ramp.estimated_duration is None
    [error] = log.errors
    assert 'does not state' in error


@pytest.mark.parametrize(
    ('section', 'reported'),
    [
        (RampTemperature(start_point=298.15 * K), 'missing an end'),
        (
            HoldBetweenIrradiance(upper_bound=1000 * ureg('W/m^2')),
            'missing one',
        ),
        (
            HoldBetweenIrradiance(
                lower_bound=1000 * ureg('W/m^2'), upper_bound=800 * ureg('W/m^2')
            ),
            'above its `upper_bound`',
        ),
    ],
)
def test_ends_and_bounds_must_both_be_there_and_in_order(
    normalized, log, section, reported
):
    normalized(section)

    [error] = log.errors
    assert reported in error


# Values a standard names (§17.2).


def test_room_temperature_is_23_plus_minus_4_celsius():
    room = RoomTemperature()

    assert room.value.to(ureg.degC).magnitude == pytest.approx(23)
    assert room.tolerance.to(K).magnitude == pytest.approx(4)


def test_dark_is_exactly_no_light():
    dark = Dark()

    assert dark.value.magnitude == 0
    assert dark.tolerance is None
