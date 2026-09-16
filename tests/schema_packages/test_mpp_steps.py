"""The electrical load's tracked steps (Design.md §15.10)."""

import pytest

from nomad_pv_stability_measurements.schema_packages.mpp_steps import OperatingPoint
from nomad_pv_stability_measurements.schema_packages.routine import (
    HoldStep,
    RampStep,
)


def test_the_load_sits_at_one_point_of_the_jv_curve():
    # One axis with two values, so R4 reads `mpp` and `voc` at once as the contradiction
    # it is — two separate classes never could, since it groups by axis (§15.10).
    assert OperatingPoint(point='mpp').point == 'mpp'
    assert OperatingPoint(point='voc').point == 'voc'
    with pytest.raises(ValueError):
        OperatingPoint(point='somewhere')


def test_a_tracked_point_is_neither_held_nor_ramped():
    # The volts and amps at the point are the cell's answer, so there is no number for
    # the protocol to write, and nothing to move between (§15.10, §15.11).
    assert not issubclass(OperatingPoint, HoldStep | RampStep)
    quantities = set(OperatingPoint.m_def.all_quantities)
    assert {'setpoint', 'start_point', 'end_point', 'ramp_rate'}.isdisjoint(quantities)
    assert {'monitor', 'control'} <= quantities


def test_an_operating_point_names_which_point(normalized, log):
    normalized(OperatingPoint(name='load', monitor=True))

    [error] = log.errors
    assert 'load is an `OperatingPoint` naming no point' in error
