"""The steps that hold one value, one class per quantity (Design.md §15.1, §15.11)."""

import pytest
from nomad.units import ureg

from nomad_pv_stability_measurements.schema_packages.hold_steps import (
    BalanceGas,
    HoldAbsoluteHumidity,
    HoldCurrent,
    HoldIrradiance,
    HoldOxygenFraction,
    HoldPressure,
    HoldTemperature,
    HoldVoltage,
)
from nomad_pv_stability_measurements.schema_packages.routine import (
    HoldStep,
    PlannedMonitorControlStep,
)

HOLDS = HoldStep.__subclasses__()
#: The step that holds something that is no number: a gas. The load's tracked point is
#: the same shape, in `mpp_steps.py` (§15.10).
NUMBERLESS = (BalanceGas,)


def test_each_hold_class_is_one_quantity():
    assert [cls.__name__ for cls in HOLDS] == [
        'HoldTemperature',
        'HoldIrradiance',
        'HoldVoltage',
        'HoldCurrent',
        'HoldResistance',
        'HoldBendRadius',
        'HoldStrain',
        'HoldAbsoluteHumidity',
        'HoldRelativeHumidity',
        'HoldOxygenFraction',
        'HoldPressure',
    ]


def test_every_step_has_a_monitor_and_a_control_tag_and_a_setpoint():
    for cls in HOLDS:
        assert {'monitor', 'control', 'set_point'} <= set(cls.m_def.all_quantities)


def test_each_setpoint_uses_nomads_unit_system():
    units = {
        cls.__name__: str(cls.m_def.all_quantities['set_point'].unit) for cls in HOLDS
    }

    assert units == {
        'HoldTemperature': 'kelvin',
        'HoldIrradiance': 'watt / meter ** 2',
        'HoldVoltage': 'volt',
        'HoldCurrent': 'ampere',
        'HoldResistance': 'ohm',
        'HoldBendRadius': 'meter',
        'HoldStrain': 'dimensionless',
        # The atmosphere is a volume ratio, so its unit is the fraction (§15.7), and a
        # relative humidity is a fraction too, of a different thing (§20.6).
        'HoldAbsoluteHumidity': 'dimensionless',
        'HoldRelativeHumidity': 'dimensionless',
        'HoldOxygenFraction': 'dimensionless',
        'HoldPressure': 'pascal',
    }
    # The kind names no quantity, so its own set point has no unit (verified, §15.1).
    assert HoldStep.m_def.all_quantities['set_point'].unit is None


def test_a_setpoint_reloads_in_its_unit():
    data = {'control': True, 'set_point': 338.15, 'estimated_duration': 3600.0}
    step = HoldTemperature.m_from_dict(data)

    assert step.set_point.to(ureg.degC).magnitude == pytest.approx(65)
    assert step.m_to_dict() == data


def test_monitor_and_control_are_independent_tags():
    logged = HoldTemperature(monitor=True)

    assert (logged.monitor, logged.control, logged.set_point) == (True, None, None)


def test_a_physical_property_is_a_plain_field_of_its_step():
    assert HoldIrradiance(spectrum='AM1.5G').spectrum == 'AM1.5G'
    assert 'spectrum' not in HoldTemperature.m_def.all_quantities


def test_the_schema_holds_no_physics():
    # No sets, no tied variables, no words standing for values (§15.1).
    for cls in [PlannedMonitorControlStep, *HOLDS, *NUMBERLESS]:
        properties = set(cls.m_def.all_properties)
        assert {'variable_set', 'variable', 'channel', 'hold'}.isdisjoint(properties)
        assert not hasattr(cls, 'alternative_setpoints')


# The atmosphere, as an absolute volume ratio (§15.7).


def test_a_glovebox_and_the_open_air_land_on_one_axis():
    # ppm and % are both dimensionless here, so one field takes either and stores one
    # number — no kinds, no conversion table.
    glovebox = HoldOxygenFraction(set_point=0.1 * ureg.ppm)
    air = HoldOxygenFraction(set_point=21 * ureg.percent)

    assert glovebox.set_point.magnitude == pytest.approx(1e-7)
    assert air.set_point.magnitude == pytest.approx(0.21)


def test_an_atmosphere_step_round_trips_as_the_fraction():
    data = {'monitor': True, 'control': True, 'set_point': 5e-4}

    assert HoldAbsoluteHumidity.m_from_dict(data).m_to_dict() == data


def test_no_atmosphere_step_knows_relative_humidity():
    # It is a property of the water content and the temperature together, so it is no
    # field of either step; a `normalize()` can derive it once something needs it.
    for cls in [HoldAbsoluteHumidity, HoldOxygenFraction]:
        assert 'humidity' not in set(cls.m_def.all_properties)
        assert str(cls.m_def.all_quantities['set_point'].unit) == 'dimensionless'


# The steps that hold no number, and the ambient quantities (§15.10, §15.11).


def test_a_step_that_holds_no_number_takes_no_setpoint():
    # With `set_point` on `HoldStep` rather than on the base, these two inherit no
    # numeric field they would never fill (§15.11).
    for cls in NUMBERLESS:
        assert not issubclass(cls, HoldStep)
        assert 'set_point' not in cls.m_def.all_quantities
        assert {'monitor', 'control'} <= set(cls.m_def.all_quantities)


def test_pressure_is_the_atmosphere_as_a_whole():
    ambient = HoldPressure(set_point=1013.25 * ureg.mbar)

    assert ambient.set_point.to(ureg.pascal).magnitude == pytest.approx(101325)


def test_the_balance_gas_is_a_name_not_a_number():
    assert BalanceGas(gas='N2').gas == 'N2'
    assert 'gas' not in HoldPressure.m_def.all_quantities


def test_every_hold_declares_its_tolerance_in_the_unit_of_its_set_point():
    # `set_point ± set_point_tolerance`, so the two must be comparable (§17.4).
    for cls in HOLDS:
        quantities = cls.m_def.all_quantities
        assert quantities['set_point_tolerance'].unit == quantities['set_point'].unit


def test_a_temperature_tolerance_is_a_difference_in_kelvin():
    step = HoldTemperature(
        set_point=ureg.Quantity(65, ureg.degC), set_point_tolerance=2 * ureg.kelvin
    )

    assert step.set_point_tolerance.to(ureg.kelvin).magnitude == pytest.approx(2)


# A point on the device's own characteristic (§20.3).


@pytest.mark.parametrize(
    ('cls', 'points'),
    [
        (HoldVoltage, ['V_MPP', 'near V_MPP', 'V_oc', '-V_oc']),
        (HoldCurrent, ['J_SC', '-J_MPP']),
    ],
)
def test_a_bias_names_the_point_of_the_device_it_is_taken_from(cls, points):
    for point in points:
        assert cls(reference_point=point).reference_point == point
    # E_g/q is a ceiling the standard recommends staying under, not a bias (§18.6).
    with pytest.raises(ValueError):
        cls(reference_point='E_g/q')


def test_the_base_takes_any_point_and_a_child_narrows_it():
    assert set(PlannedMonitorControlStep.m_def.all_quantities) >= {'reference_point'}
    assert HoldTemperature(reference_point='anything').reference_point == 'anything'
