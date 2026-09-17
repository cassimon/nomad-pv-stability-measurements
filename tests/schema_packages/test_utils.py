"""The checks the protocol runs over its own instructions and every block's, tested as the
plain functions they are (Design.md §15.4, §23).

Each is called directly on a list of instructions, so what it does is visible without a
`normalize()` pass around it: R4 and R5 report and leave the instructions alone, and
`check_instructions` is the two of them in order.
"""

from nomad.units import ureg

from nomad_pv_stability_measurements.schema_packages.general import InstructionBlock
from nomad_pv_stability_measurements.schema_packages.hold_instructions import (
    HoldIrradiance,
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
from nomad_pv_stability_measurements.schema_packages.utils import (
    check_instructions,
    report_instructions_that_never_run,
    report_overlapping_instructions,
)

BLOCK = InstructionBlock


def instruction(cls, name=None, seconds=None):
    """One instruction, `seconds` long. Without one it never finishes (§23)."""
    fields = {}
    if name is not None:
        fields['name'] = name
    if seconds is not None:
        fields['estimated_duration'] = seconds * ureg.second
    return cls(**fields)


def lengths(instructions):
    return [
        None if i.estimated_duration is None else i.estimated_duration.to('s').magnitude
        for i in instructions
    ]


# R4 — two instructions that speak to one quantity at the same time (report, never repair).


def test_two_instructions_on_one_quantity_overlap_in_a_parallel_run(log):
    instructions = [
        instruction(HoldTemperature, seconds=3600),
        instruction(HoldTemperature, seconds=7200),
    ]

    report_overlapping_instructions(instructions, 'parallel', 'fork', log)

    [error] = log.errors
    assert '2 Temperature instructions overlap in fork' in error
    assert 'they run at the same time' in error
    # Reported, never repaired: both stand as authored (D13a).
    assert lengths(instructions) == [3600, 7200]


def test_one_after_another_they_never_overlap(log):
    # Even one that never finishes: what comes after it never runs, which R5 reports.
    instructions = [instruction(HoldTemperature), instruction(HoldTemperature)]

    report_overlapping_instructions(instructions, 'sequential', 'phase', log)

    assert log.errors == []


def test_different_quantities_never_overlap(log):
    # HoldVoltage and irradiance are tied by the cell, but that is physics (§15.1).
    instructions = [
        instruction(HoldVoltage),
        instruction(HoldIrradiance),
        instruction(HoldTemperature),
    ]

    report_overlapping_instructions(instructions, 'parallel', 'fork', log)

    assert log.errors == []


def test_a_hold_and_a_ramp_on_one_quantity_overlap(log):
    # Two classes, one axis: whichever kind they are, two instructions cannot both
    # command the temperature at once (§15.11).
    instructions = [instruction(HoldTemperature), instruction(RampTemperature)]

    report_overlapping_instructions(instructions, 'parallel', 'fork', log)

    [error] = log.errors
    assert '2 Temperature instructions overlap in fork' in error


def test_mpp_and_open_circuit_go_unreported(log):
    # A known gap, not an intention: a load sits at one point at a time, so these two do
    # contradict each other — but R4 groups by the class name alone, and the two names
    # differ (§15.13).
    instructions = [instruction(MPPTracking), instruction(VOCTracking)]

    report_overlapping_instructions(instructions, 'parallel', 'fork', log)

    assert log.errors == []


def test_blocks_are_not_a_quantity_and_never_overlap(log):
    # Recognised as monitor/control by the `monitor` field, which a block has not — two
    # blocks at the same time are the point of `parallel`.
    instructions = [instruction(BLOCK), instruction(BLOCK)]

    report_overlapping_instructions(instructions, 'parallel', 'fork', log)

    assert log.errors == []


def test_each_crowded_quantity_is_reported_once_with_its_count(log):
    instructions = [instruction(HoldTemperature) for _ in range(3)] + [
        instruction(HoldVoltage),
        instruction(HoldVoltage),
    ]

    report_overlapping_instructions(instructions, 'parallel', 'fork', log)

    crowded = [error.split(' instructions overlap')[0] for error in log.errors]
    assert crowded == ['3 Temperature', '2 Voltage']


def test_an_overlap_says_what_to_write_instead(log):
    report_overlapping_instructions(
        [instruction(HoldTemperature), instruction(HoldTemperature)],
        'parallel',
        'fork',
        log,
    )

    [error] = log.errors
    assert 'not merged' in error
    assert 'one instruction with all the keys' in error


# R5 — an instruction that is never reached (report, never repair).


def test_an_instruction_after_one_that_never_finishes_never_runs(log):
    instructions = [
        instruction(HoldTemperature, name='forever'),
        instruction(HoldVoltage, name='late', seconds=600),
    ]

    report_instructions_that_never_run(instructions, 'sequential', None, 'phase', log)

    [warning] = log.warnings
    assert 'late never runs' in warning
    assert 'in phase never finish, or are stopped first' in warning
    assert lengths(instructions) == [None, 600]


def test_an_instruction_after_the_stop_never_runs(log):
    instructions = [
        instruction(HoldTemperature, name='warm', seconds=3600),
        instruction(HoldVoltage, name='late', seconds=600),
    ]

    report_instructions_that_never_run(
        instructions, 'sequential', 3600 * ureg.second, 'phase', log
    )

    [warning] = log.warnings
    assert 'late never runs' in warning


def test_an_instruction_that_only_partly_fits_still_runs(log):
    # It starts, so it is not "never": it is stopped while it runs.
    instructions = [
        instruction(HoldTemperature, seconds=1800),
        instruction(HoldVoltage, name='long', seconds=7200),
    ]

    report_instructions_that_never_run(
        instructions, 'sequential', 3600 * ureg.second, 'phase', log
    )

    assert log.warnings == []


def test_every_instruction_past_the_end_is_named(log):
    instructions = [
        instruction(HoldTemperature, name='warm'),
        instruction(HoldVoltage, name='second', seconds=600),
        instruction(HoldIrradiance, name='third', seconds=600),
    ]

    report_instructions_that_never_run(instructions, 'sequential', None, 'phase', log)

    assert ['second' in log.warnings[0], 'third' in log.warnings[1]] == [True, True]


def test_nothing_is_left_behind_in_a_parallel_run(log):
    instructions = [
        instruction(HoldTemperature),
        instruction(HoldVoltage, name='late', seconds=7200),
    ]

    report_instructions_that_never_run(
        instructions, 'parallel', 3600 * ureg.second, 'fork', log
    )

    assert log.warnings == []


def test_without_a_stop_finite_instructions_all_run(log):
    instructions = [
        instruction(HoldTemperature, seconds=7200),
        instruction(HoldVoltage, name='late', seconds=600),
    ]

    report_instructions_that_never_run(instructions, 'sequential', None, 'phase', log)

    assert log.warnings == []


def test_an_unnamed_instruction_is_still_named_in_the_warning(log):
    instructions = [instruction(HoldTemperature), instruction(HoldVoltage, seconds=600)]

    report_instructions_that_never_run(instructions, 'sequential', None, 'phase', log)

    [warning] = log.warnings
    assert '<unnamed> never runs' in warning


# `check_instructions` — both of them, as the protocol runs them.


def test_check_instructions_reports_and_repairs_nothing(log):
    instructions = [
        instruction(HoldTemperature, name='a', seconds=1800),
        instruction(HoldTemperature, name='b', seconds=1800),
    ]

    check_instructions(instructions, 'parallel', None, 'fork', log)
    check_instructions(instructions, 'sequential', 1800 * ureg.second, 'phase', log)

    assert '2 Temperature instructions overlap in fork' in log.errors[0]
    assert 'b never runs' in log.warnings[0]
    assert lengths(instructions) == [1800, 1800]
