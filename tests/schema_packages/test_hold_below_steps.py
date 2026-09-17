"""The steps that keep one value under a bound (Design.md §17.5)."""

from nomad.units import ureg

from nomad_pv_stability_measurements.schema_packages.hold_below_steps import (
    HoldBelowWaterVaporFraction,
)
from nomad_pv_stability_measurements.schema_packages.hold_steps import (
    HoldWaterVaporFraction,
)
from nomad_pv_stability_measurements.schema_packages.routine import (
    HoldBelowStep,
    HoldStep,
    PlannedMonitorControlStep,
)
from nomad_pv_stability_measurements.schema_packages.utils import (
    report_overlapping_steps,
)


def test_a_bound_is_a_sibling_of_a_hold_not_a_kind_of_one():
    # "Keep under 55 %" is not "hold at 55 %", so it shares no `set_point` (§17.5).
    assert issubclass(HoldBelowStep, PlannedMonitorControlStep)
    assert not issubclass(HoldBelowStep, HoldStep)
    quantities = HoldBelowWaterVaporFraction.m_def.all_quantities
    assert {'set_point', 'set_point_tolerance'}.isdisjoint(quantities)
    assert quantities['upper_bound'].unit == ureg.dimensionless


def test_only_what_a_standard_bounds_has_a_class():
    assert [cls.__name__ for cls in HoldBelowStep.__subclasses__()] == [
        'HoldBelowWaterVaporFraction'
    ]


def test_a_bare_bound_names_no_quantity(normalized, log):
    normalized(HoldBelowStep(name='bound'))

    [error] = log.errors
    assert 'bound is a bare `HoldBelowStep`' in error


def test_a_hold_and_a_bound_on_one_quantity_still_overlap(log):
    # `HoldBelow…` must lose its whole prefix, or it lands on a quantity of its own and
    # two steps commanding the water vapour go unreported (§17.5).
    steps = [HoldWaterVaporFraction(), HoldBelowWaterVaporFraction()]

    report_overlapping_steps(steps, 'parallel', 'fork', log)

    [error] = log.errors
    assert '2 WaterVaporFraction steps overlap in fork' in error
