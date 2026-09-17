"""The steps whose value moves, one class per quantity (Design.md §15.11)."""

import pytest
from nomad.units import ureg

from nomad_pv_stability_measurements.schema_packages.hold_steps import HoldTemperature
from nomad_pv_stability_measurements.schema_packages.ramp_steps import RampTemperature
from nomad_pv_stability_measurements.schema_packages.routine import (
    HoldStep,
    RampStep,
)

RAMPS = RampStep.__subclasses__()


def test_every_quantity_that_can_be_held_can_also_be_ramped():
    # The two files are one list of quantities, in two kinds (§15.11). Importing one
    # hold class is what puts them all on `HoldStep.__subclasses__()`.
    assert HoldTemperature in HoldStep.__subclasses__()
    assert [cls.__name__.removeprefix('Ramp') for cls in RAMPS] == [
        cls.__name__.removeprefix('Hold') for cls in HoldStep.__subclasses__()
    ]


def test_a_ramp_names_both_ends_and_a_rate():
    for cls in RAMPS:
        assert {'start_point', 'end_point', 'ramp_rate'} <= set(
            cls.m_def.all_quantities
        )


def test_a_ramp_holds_nothing():
    # `set_point` sits on `HoldStep`, so a ramp does not carry one it never fills.
    for cls in RAMPS:
        assert 'set_point' not in cls.m_def.all_quantities


def test_both_ends_of_a_ramp_share_one_unit():
    for cls in RAMPS:
        quantities = cls.m_def.all_quantities
        assert quantities['end_point'].unit == quantities['start_point'].unit


def test_a_rate_is_its_quantity_over_a_time():
    for cls in RAMPS:
        quantities = cls.m_def.all_quantities
        rate = 1 * quantities['ramp_rate'].unit
        span = 1 * quantities['start_point'].unit

        assert (rate * ureg.second).dimensionality == span.dimensionality


def test_a_ramp_reloads_in_its_unit():
    data = {'control': True, 'start_point': 298.15, 'end_point': 358.15}
    step = RampTemperature.m_from_dict(data)

    assert step.start_point.to(ureg.degC).magnitude == pytest.approx(25)
    assert step.end_point.to(ureg.degC).magnitude == pytest.approx(85)
    assert step.m_to_dict() == data
