"""The electrical load driven to a point it finds (Design.md §15.13)."""

import pytest
from nomad.units import ureg

from nomad_pv_stability_measurements.schema_packages.hold_steps import HoldVoltage
from nomad_pv_stability_measurements.schema_packages.mpp_steps import (
    MPPTracking,
    VOCTracking,
)
from nomad_pv_stability_measurements.schema_packages.routine import (
    HoldStep,
    RampStep,
)

TRACKED = (MPPTracking, VOCTracking)


def test_the_two_ways_of_finding_a_point_are_two_classes():
    # Named for what they do, rather than one class with a `point` enum (§15.13).
    assert [cls.__name__ for cls in TRACKED] == ['MPPTracking', 'VOCTracking']


def test_both_name_one_axis():
    # A load sits at one point at a time, so two of these contradict each other and R4
    # has to see them as one quantity even though they are two classes (§15.13).
    assert {cls.axis for cls in TRACKED} == {'OperatingPoint'}


def test_a_found_point_is_neither_held_nor_ramped():
    # The volts and amps at the point are the cell's answer, so there is no number for
    # the protocol to write, and nothing to move between.
    for cls in TRACKED:
        assert not issubclass(cls, HoldStep | RampStep)
        quantities = set(cls.m_def.all_quantities)
        assert {'setpoint', 'start_point', 'end_point'}.isdisjoint(quantities)
        assert {'monitor', 'control'} <= quantities


def test_a_constant_external_bias_is_a_held_voltage():
    # Including reverse bias: it is a number the protocol names, so it needs no class of
    # its own here (§15.13).
    assert HoldVoltage(setpoint=-1.2 * ureg.volt).setpoint.magnitude == pytest.approx(
        -1.2
    )


def test_the_tracker_takes_what_an_operator_sets_beforehand():
    tracking = MPPTracking(
        perturbation_voltage=0.02 * ureg.volt,
        perturbation_every=10 * ureg.second,
        perturbation_delay=0.5 * ureg.second,
        start_voltage_manually=True,
        start_voltage=0.9 * ureg.volt,
    )

    assert tracking.perturbation_voltage.to(ureg.mV).magnitude == pytest.approx(20)
    assert tracking.perturbation_every.magnitude == pytest.approx(10)
    assert tracking.perturbation_delay.magnitude == pytest.approx(0.5)
    assert tracking.start_voltage.magnitude == pytest.approx(0.9)


def test_what_the_run_reports_back_is_no_part_of_the_plan():
    # nomad-baseclasses keeps these on the same section, but they are the measurement:
    # a protocol cannot plan its own last PCE (§4.5, §15.13).
    quantities = set(MPPTracking.m_def.all_quantities)

    assert {'last_pce', 'last_vmpp', 'status', 'power_density'}.isdisjoint(quantities)
    # And the two the step already has from every other step are not repeated.
    assert {'sampling', 'time'}.isdisjoint(quantities)
    assert {'sample_every', 'sampling_rate', 'estimated_duration'} <= quantities


def test_open_circuit_asks_for_nothing_but_itself():
    assert set(VOCTracking.m_def.all_quantities) == set(
        MPPTracking.m_def.all_quantities
    ) - {
        'perturbation_voltage',
        'perturbation_every',
        'perturbation_delay',
        'start_voltage_manually',
        'start_voltage',
    }
