"""The monitor/control steps, one class per quantity (Design.md §15.1)."""

import pytest
from nomad.units import ureg

from nomad_pv_stability_measurements.schema_packages.routine import (
    PlannedMonitorControlStep,
)
from nomad_pv_stability_measurements.schema_packages.activity_steps import (
    Irradiance,
    Temperature,
)

STEPS = PlannedMonitorControlStep.__subclasses__()


def test_each_step_class_is_one_quantity():
    assert [cls.__name__ for cls in STEPS] == [
        'TemperatureStep',
        'IrradianceStep',
        'VoltageStep',
        'CurrentStep',
        'ResistanceStep',
        'BendRadiusStep',
        'StrainStep',
    ]


def test_every_step_has_a_monitor_and_a_control_tag_and_a_setpoint():
    for cls in STEPS:
        assert {'monitor', 'control', 'setpoint'} <= set(cls.m_def.all_quantities)


def test_each_setpoint_uses_nomads_unit_system():
    units = {
        cls.__name__: str(cls.m_def.all_quantities['setpoint'].unit) for cls in STEPS
    }

    assert units == {
        'TemperatureStep': 'kelvin',
        'IrradianceStep': 'watt / meter ** 2',
        'VoltageStep': 'volt',
        'CurrentStep': 'ampere',
        'ResistanceStep': 'ohm',
        'BendRadiusStep': 'meter',
        'StrainStep': 'dimensionless',
    }
    # The base names no quantity, so its setpoint has no unit (verified, §15.1).
    assert PlannedMonitorControlStep.m_def.all_quantities['setpoint'].unit is None


def test_a_setpoint_reloads_in_its_unit():
    data = {'control': True, 'setpoint': 338.15, 'estimated_duration': 3600.0}
    step = Temperature.m_from_dict(data)

    assert step.setpoint.to(ureg.degC).magnitude == pytest.approx(65)
    assert step.m_to_dict() == data


def test_monitor_and_control_are_independent_tags():
    logged = Temperature(monitor=True)

    assert (logged.monitor, logged.control, logged.setpoint) == (True, None, None)


def test_a_physical_property_is_a_plain_field_of_its_step():
    assert Irradiance(spectrum='AM1.5G').spectrum == 'AM1.5G'
    assert 'spectrum' not in Temperature.m_def.all_quantities


def test_the_schema_holds_no_physics():
    # No sets, no tied variables, no words standing for values (§15.1).
    for cls in [PlannedMonitorControlStep, *STEPS]:
        properties = set(cls.m_def.all_properties)
        assert {'variable_set', 'variable', 'channel', 'hold'}.isdisjoint(properties)
        assert not hasattr(cls, 'alternative_setpoints')
