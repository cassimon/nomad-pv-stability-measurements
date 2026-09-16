"""The checks a block and the protocol both run, tested as the plain functions they
are (Design.md §15.4).

Each is called directly on a list of steps, so what it does is visible without a
`normalize()` pass around it: R4 and R5 report and leave the steps alone, R6 repairs and
says so, `derive_duration` answers, and `normalize_steps` is the four of them in order.
"""

import pytest
from nomad.units import ureg

from nomad_pv_stability_measurements.schema_packages.hold_steps import (
    HoldIrradiance,
    HoldTemperature,
    HoldVoltage,
)
from nomad_pv_stability_measurements.schema_packages.ramp_steps import RampTemperature
from nomad_pv_stability_measurements.schema_packages.routine import (
    PlannedSubroutineStep,
)
from nomad_pv_stability_measurements.schema_packages.utils import (
    derive_duration,
    fit_steps_to_duration,
    normalize_steps,
    report_overlapping_steps,
    report_steps_that_never_run,
)

BLOCK = PlannedSubroutineStep


def step(cls, name=None, seconds=None):
    """One step, `seconds` long. Without one it is a condition, lasting as long as the
    block around it (D13)."""
    fields = {}
    if name is not None:
        fields['name'] = name
    if seconds is not None:
        fields['estimated_duration'] = seconds * ureg.second
    return cls(**fields)


def lengths(steps):
    return [
        None if s.estimated_duration is None else s.estimated_duration.to('s').magnitude
        for s in steps
    ]


# R4 — two steps that speak to one quantity at the same time (report, never repair).


def test_two_steps_on_one_quantity_overlap_in_a_parallel_block(log):
    steps = [step(HoldTemperature, seconds=3600), step(HoldTemperature, seconds=7200)]

    report_overlapping_steps(steps, 'parallel', 'fork', log)

    [error] = log.errors
    assert '2 Temperature steps overlap in fork' in error
    assert 'a `parallel` block runs its steps at the same time' in error
    # Reported, never repaired: both steps stand as authored (D13a).
    assert lengths(steps) == [3600, 7200]


def test_a_condition_overlaps_whatever_else_speaks_to_its_quantity(log):
    # The condition has no duration, so it holds for the whole span, including the turn
    # the other step takes.
    steps = [step(HoldTemperature, seconds=3600), step(HoldTemperature)]

    report_overlapping_steps(steps, 'sequential', 'phase', log)

    [error] = log.errors
    assert "without an `estimated_duration` holds for the block's whole span" in error


def test_steps_with_a_turn_each_are_subsequent_not_overlapping(log):
    steps = [step(HoldTemperature, seconds=3600), step(HoldTemperature, seconds=7200)]

    report_overlapping_steps(steps, 'sequential', 'phase', log)

    assert log.errors == []


def test_different_quantities_never_overlap(log):
    # HoldVoltage and irradiance are tied by the cell, but that is physics (§15.1).
    steps = [step(HoldVoltage), step(HoldIrradiance), step(HoldTemperature)]

    report_overlapping_steps(steps, 'parallel', 'fork', log)

    assert log.errors == []


def test_a_hold_and_a_ramp_on_one_quantity_overlap(log):
    # Two classes, one axis: whichever kind they are, two steps cannot both command the
    # temperature at once (§15.11).
    steps = [step(HoldTemperature), step(RampTemperature)]

    report_overlapping_steps(steps, 'parallel', 'fork', log)

    [error] = log.errors
    assert '2 Temperature steps overlap in fork' in error


def test_blocks_are_not_a_quantity_and_never_overlap(log):
    # A step is recognised as monitor/control by its `monitor` field, which a block has
    # not — two blocks at the same time are the point of `parallel`.
    steps = [step(BLOCK, seconds=3600), step(BLOCK, seconds=3600)]

    report_overlapping_steps(steps, 'parallel', 'fork', log)

    assert log.errors == []


def test_each_crowded_quantity_is_reported_once_with_its_count(log):
    steps = [step(HoldTemperature) for _ in range(3)] + [
        step(HoldVoltage),
        step(HoldVoltage),
    ]

    report_overlapping_steps(steps, 'parallel', 'fork', log)

    crowded = [error.split(' steps overlap')[0] for error in log.errors]
    assert crowded == ['3 Temperature', '2 Voltage']


def test_an_overlap_says_what_to_write_instead(log):
    report_overlapping_steps(
        [step(HoldTemperature), step(HoldTemperature)], 'parallel', 'fork', log
    )

    [error] = log.errors
    assert 'not merged' in error
    assert 'one step with all the keys' in error


# R5 — a step the block leaves no time for (report, never repair).


def test_a_step_after_the_time_is_spent_never_runs(log):
    steps = [
        step(HoldTemperature, name='warm', seconds=3600),
        step(HoldVoltage, name='late', seconds=600),
    ]

    report_steps_that_never_run(steps, 'sequential', 3600 * ureg.second, 'phase', log)

    [warning] = log.warnings
    assert 'late never runs' in warning
    assert 'the `estimated_duration` of phase is already spent' in warning
    assert lengths(steps) == [3600, 600]


def test_a_step_that_only_partly_fits_still_runs(log):
    # It starts, so it is not "never": R6 shortens it instead.
    steps = [
        step(HoldTemperature, seconds=1800),
        step(HoldVoltage, name='long', seconds=7200),
    ]

    report_steps_that_never_run(steps, 'sequential', 3600 * ureg.second, 'phase', log)

    assert log.warnings == []


def test_every_step_past_the_end_is_named(log):
    steps = [
        step(HoldTemperature, name='warm', seconds=3600),
        step(HoldVoltage, name='second', seconds=600),
        step(HoldIrradiance, name='third', seconds=600),
    ]

    report_steps_that_never_run(steps, 'sequential', 3600 * ureg.second, 'phase', log)

    assert ['second' in log.warnings[0], 'third' in log.warnings[1]] == [True, True]


def test_a_condition_takes_no_turn_so_it_always_runs(log):
    steps = [step(HoldTemperature, seconds=3600), step(HoldVoltage, name='logged')]

    report_steps_that_never_run(steps, 'sequential', 3600 * ureg.second, 'phase', log)

    assert log.warnings == []


def test_nothing_runs_out_of_time_in_a_parallel_block(log):
    steps = [
        step(HoldTemperature, seconds=7200),
        step(HoldVoltage, name='late', seconds=7200),
    ]

    report_steps_that_never_run(steps, 'parallel', 3600 * ureg.second, 'fork', log)

    assert log.warnings == []


def test_a_block_without_a_duration_leaves_time_for_everything(log):
    steps = [
        step(HoldTemperature, seconds=7200),
        step(HoldVoltage, name='late', seconds=600),
    ]

    report_steps_that_never_run(steps, 'sequential', None, 'phase', log)

    assert log.warnings == []


def test_an_unnamed_step_is_still_named_in_the_warning(log):
    steps = [step(HoldTemperature, seconds=3600), step(HoldVoltage, seconds=600)]

    report_steps_that_never_run(steps, 'sequential', 3600 * ureg.second, 'phase', log)

    [warning] = log.warnings
    assert '<unnamed> never runs' in warning


# R6 — a step that would outlast its block is shortened (the one repair).


def test_the_step_the_time_runs_out_during_is_shortened(log):
    steps = [
        step(HoldTemperature, name='warm', seconds=1800),
        step(HoldVoltage, name='hot', seconds=3600),
    ]

    fit_steps_to_duration(steps, 'sequential', 3600 * ureg.second, 'phase', log)

    assert lengths(steps) == [1800, 1800]
    [warning] = log.warnings
    assert 'hot is shortened from 3600 s to 1800 s' in warning
    assert 'of phase' in warning


def test_a_step_with_no_time_left_is_left_alone(log):
    # R5 already says it never runs; shortening it to nothing would say it does.
    steps = [
        step(HoldTemperature, name='warm', seconds=3600),
        step(HoldVoltage, name='late', seconds=600),
    ]

    fit_steps_to_duration(steps, 'sequential', 3600 * ureg.second, 'phase', log)

    assert lengths(steps) == [3600, 600]
    assert log.warnings == []


def test_a_step_that_fits_exactly_is_not_shortened(log):
    steps = [step(HoldTemperature, name='whole', seconds=3600)]

    fit_steps_to_duration(steps, 'sequential', 3600 * ureg.second, 'phase', log)

    assert lengths(steps) == [3600]
    assert log.warnings == []


def test_only_the_step_that_overruns_is_touched(log):
    steps = [
        step(HoldTemperature, name='warm', seconds=1800),
        step(HoldVoltage, name='hot', seconds=7200),
        step(HoldIrradiance, name='after', seconds=600),
    ]

    fit_steps_to_duration(steps, 'sequential', 3600 * ureg.second, 'phase', log)

    # `warm` fits, `hot` is cut to what is left, `after` had none to begin with.
    assert lengths(steps) == [1800, 1800, 600]
    assert len(log.warnings) == 1


def test_every_step_longer_than_a_parallel_block_is_shortened(log):
    steps = [
        step(HoldTemperature, name='long', seconds=7200),
        step(HoldVoltage, name='longer', seconds=10800),
        step(HoldIrradiance, name='short', seconds=1800),
    ]

    fit_steps_to_duration(steps, 'parallel', 3600 * ureg.second, 'fork', log)

    assert lengths(steps) == [3600, 3600, 1800]
    shortened = [warning.split(' is shortened')[0] for warning in log.warnings]
    assert shortened == ['long', 'longer']


def test_a_condition_is_never_given_a_duration(log):
    # It already lasts exactly as long as the block; a duration would make it an episode
    # that takes a turn (D13).
    steps = [step(HoldTemperature, name='logged')]

    fit_steps_to_duration(steps, 'sequential', 3600 * ureg.second, 'phase', log)

    assert lengths(steps) == [None]
    assert log.warnings == []


def test_a_block_without_a_duration_fits_nothing(log):
    steps = [step(HoldTemperature, name='long', seconds=7200)]

    fit_steps_to_duration(steps, 'sequential', None, 'phase', log)

    assert lengths(steps) == [7200]
    assert log.warnings == []


def test_a_shortened_step_keeps_its_unit(log):
    steps = [step(HoldTemperature, name='hot', seconds=7200)]

    fit_steps_to_duration(steps, 'sequential', 1 * ureg.hour, 'phase', log)

    assert steps[0].estimated_duration.to(ureg.minute).magnitude == pytest.approx(60)


# The length a block has when it writes none of its own.


def test_a_sequential_block_lasts_as_long_as_its_steps_together():
    steps = [step(HoldTemperature, seconds=1800), step(HoldVoltage, seconds=3600)]

    assert derive_duration(steps, 'sequential').to('s').magnitude == pytest.approx(5400)


def test_a_parallel_block_lasts_as_long_as_its_longest_step():
    steps = [step(HoldTemperature, seconds=1800), step(HoldVoltage, seconds=3600)]

    assert derive_duration(steps, 'parallel').to('s').magnitude == pytest.approx(3600)


def test_conditions_add_nothing_to_the_length():
    steps = [
        step(HoldTemperature),
        step(HoldVoltage, seconds=3600),
        step(HoldIrradiance),
    ]

    assert derive_duration(steps, 'sequential').to('s').magnitude == pytest.approx(3600)


@pytest.mark.parametrize('steps', [[], [step(HoldTemperature)]])
def test_nothing_to_measure_leaves_the_length_open(steps):
    assert derive_duration(steps, 'sequential') is None


# `normalize_steps` — the four of them, as a block and the protocol both run them.


def test_normalize_steps_reports_repairs_and_derives(log):
    block = BLOCK(name='phase', estimated_duration=3600 * ureg.second)
    block.steps = [
        step(HoldTemperature, name='logged'),
        step(HoldTemperature, name='warm', seconds=1800),
        step(HoldVoltage, name='hot', seconds=3600),
        step(HoldIrradiance, name='late', seconds=600),
    ]

    normalize_steps(block, 'sequential', log)

    assert [len(log.errors), len(log.warnings)] == [1, 2]
    assert '2 Temperature steps overlap in phase' in log.errors[0]
    assert 'late never runs' in log.warnings[0]
    assert 'hot is shortened from 3600 s to 1800 s' in log.warnings[1]
    assert lengths(block.steps) == [None, 1800, 1800, 600]
    # The block wrote its own length, so it is kept, not recomputed from the steps.
    assert block.estimated_duration.to('s').magnitude == pytest.approx(3600)


def test_normalize_steps_measures_a_block_that_wrote_no_length(log):
    block = BLOCK(name='phase')
    block.steps = [step(HoldTemperature, seconds=1800), step(HoldVoltage, seconds=3600)]

    normalize_steps(block, 'sequential', log)

    assert block.estimated_duration.to('s').magnitude == pytest.approx(5400)
    assert (log.errors, log.warnings) == ([], [])


def test_normalize_steps_names_the_block_it_is_checking(log):
    block = BLOCK()
    block.steps = [step(HoldTemperature), step(HoldTemperature)]

    normalize_steps(block, 'parallel', log)

    [error] = log.errors
    assert 'overlap in <unnamed>' in error
