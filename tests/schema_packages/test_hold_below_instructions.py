"""The instructions that keep one value under a bound (Design.md §17.5)."""

from nomad.units import ureg

from nomad_pv_stability_measurements.schema_packages.hold_below_instructions import (
    HoldBelowAbsoluteHumidity,
    HoldBetweenIrradiance,
)
from nomad_pv_stability_measurements.schema_packages.hold_instructions import (
    HoldAbsoluteHumidity,
    HoldIrradiance,
)
from nomad_pv_stability_measurements.schema_packages.routine import (
    HoldBelowInstruction,
    HoldBetweenInstruction,
    HoldInstruction,
    MonitorControlInstruction,
)
from nomad_pv_stability_measurements.schema_packages.utils import (
    report_overlapping_instructions,
)


def test_a_bound_is_a_sibling_of_a_hold_not_a_kind_of_one():
    # "Keep under 55 %" is not "hold at 55 %", so it shares no `set_point` (§17.5).
    assert issubclass(HoldBelowInstruction, MonitorControlInstruction)
    assert not issubclass(HoldBelowInstruction, HoldInstruction)
    quantities = HoldBelowAbsoluteHumidity.m_def.all_quantities
    assert {'set_point', 'set_point_tolerance'}.isdisjoint(quantities)
    assert quantities['upper_bound'].unit == ureg.dimensionless


def test_only_what_a_standard_bounds_has_a_class():
    # The relative humidity ISOS bounds, the two of an inert atmosphere, and the kind of a
    # range (§22).
    assert [cls.__name__ for cls in HoldBelowInstruction.__subclasses__()] == [
        'HoldBetweenInstruction',
        'HoldBelowAbsoluteHumidity',
        'HoldBelowRelativeHumidity',
        'HoldBelowOxygenFraction',
    ]


def test_a_bare_bound_names_no_quantity(normalized, log):
    normalized(HoldBelowInstruction(name='bound'))

    [error] = log.errors
    assert 'bound is a bare `HoldBelowInstruction`' in error


def test_a_hold_and_a_bound_on_one_quantity_still_overlap(log):
    # `HoldBelow…` must lose its whole prefix, or it lands on a quantity of its own and
    # two instructions commanding the water vapour go unreported (§17.5).
    instructions = [HoldAbsoluteHumidity(), HoldBelowAbsoluteHumidity()]

    report_overlapping_instructions(instructions, 'parallel', 'fork', log)

    [error] = log.errors
    assert '2 AbsoluteHumidity instructions overlap in fork' in error


# A range: two bounds and no target (§22).

IRRADIANCE = ureg.watt / ureg.meter**2


def test_a_range_is_a_bound_with_a_floor_under_it():
    # Kept between two bounds is kept below the upper one, so `upper_bound` means one thing.
    assert issubclass(HoldBetweenInstruction, HoldBelowInstruction)
    assert [cls.__name__ for cls in HoldBetweenInstruction.__subclasses__()] == [
        'HoldBetweenIrradiance'
    ]
    quantities = HoldBetweenIrradiance.m_def.all_quantities
    assert 'set_point' not in quantities
    assert quantities['lower_bound'].unit == IRRADIANCE
    assert quantities['upper_bound'].unit == IRRADIANCE


def test_a_range_round_trips(normalized, log):
    data = {'lower_bound': 800.0, 'upper_bound': 1000.0, 'control': True}
    instruction = normalized(HoldBetweenIrradiance.m_from_dict(data))

    assert instruction.m_to_dict() == data
    assert (log.errors, log.warnings) == ([], [])


def test_a_range_missing_a_bound_is_reported(normalized, log):
    normalized(HoldBetweenIrradiance(name='light', upper_bound=1000 * IRRADIANCE))

    [error] = log.errors
    assert 'light keeps a value between two bounds but is missing one' in error


def test_a_range_upside_down_is_reported_not_repaired(normalized, log):
    instruction = normalized(
        HoldBetweenIrradiance(
            name='light', lower_bound=1000 * IRRADIANCE, upper_bound=800 * IRRADIANCE
        )
    )

    written = (1000 * IRRADIANCE, 800 * IRRADIANCE)
    assert (instruction.lower_bound, instruction.upper_bound) == written
    [error] = log.errors
    assert 'light writes a `lower_bound` above its `upper_bound`' in error


def test_a_bare_range_names_no_quantity(normalized, log):
    normalized(HoldBetweenInstruction(name='range'))

    [error] = log.errors
    assert 'range is a bare `HoldBetweenInstruction`' in error


def test_a_range_and_a_hold_on_one_quantity_still_overlap(log):
    report_overlapping_instructions(
        [HoldIrradiance(), HoldBetweenIrradiance()], 'parallel', 'fork', log
    )

    [error] = log.errors
    assert '2 Irradiance instructions overlap in fork' in error
