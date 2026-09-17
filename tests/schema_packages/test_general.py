"""Instructions, blocks and plans (Design.md §23, §27).

An instruction is completed after its `estimated_duration`; empty means it never
finishes. A block's duration is always derived from what it contains. A repeating block's
kind says whether it finishes: a timed one always, an indefinite one never, a counting one
should. Only a plan, or a timed block, stops instructions early.
"""

from datetime import datetime, timezone

import pytest
from nomad.units import ureg

from nomad_pv_stability_measurements.schema_packages.general import (
    CountingRepeatingBlock,
    IndefiniteRepeatingBlock,
    InstructionBlock,
    Plan,
    ScheduledPlan,
    SingleInstruction,
    TimedRepeatingBlock,
)


def single(seconds=None) -> SingleInstruction:
    """An instruction lasting `seconds`; without them, one that never finishes."""
    if seconds is None:
        return SingleInstruction()
    return SingleInstruction(estimated_duration=seconds * ureg.second)


def seconds(section):
    duration = section.estimated_duration
    return None if duration is None else duration.to('s').magnitude


@pytest.mark.parametrize(('mode', 'expected'), [('sequential', 90), ('parallel', 60)])
def test_a_block_lasts_one_pass_of_its_instructions(normalized, mode, expected):
    block = InstructionBlock(
        sub_instruction_execution_mode=mode, sub_instructions=[single(30), single(60)]
    )

    assert seconds(normalized(block)) == pytest.approx(expected)


def test_a_counting_block_lasts_its_count_times_one_pass(normalized):
    block = CountingRepeatingBlock(
        repeat_n=3, sub_instructions=[single(30), single(60)]
    )

    assert seconds(normalized(block)) == pytest.approx(270)


@pytest.mark.parametrize(
    'block',
    [
        CountingRepeatingBlock(sub_instructions=[single(60)]),
        CountingRepeatingBlock(repeat_n=3, sub_instructions=[single()]),
    ],
)
def test_a_counting_block_that_does_not_finish_is_warned_about(normalized, log, block):
    assert seconds(normalized(block)) is None
    [warning] = log.warnings
    assert 'never finishes' in warning


def test_an_indefinite_block_never_finishes(normalized, log):
    block = normalized(IndefiniteRepeatingBlock(sub_instructions=[single(60)]))

    assert seconds(block) is None
    assert (log.errors, log.warnings) == ([], [])


def test_a_timed_block_lasts_its_repeat_duration_whatever_it_contains(normalized):
    block = TimedRepeatingBlock(
        repeat_duration=3600 * ureg.second, sub_instructions=[single(60), single()]
    )

    assert seconds(normalized(block)) == pytest.approx(3600)


def test_what_never_finishes_makes_everything_around_it_never_finish(normalized):
    inner = IndefiniteRepeatingBlock(sub_instructions=[single(60)])
    plan = normalized(
        Plan(instructions=[InstructionBlock(sub_instructions=[inner, single(60)])])
    )

    assert seconds(plan.instructions[0]) is None
    assert seconds(plan) is None


def test_a_blocks_written_duration_is_replaced_by_the_derived_one(normalized):
    block = InstructionBlock(
        estimated_duration=10 * ureg.second, sub_instructions=[single(60)]
    )

    assert seconds(normalized(block)) == pytest.approx(60)


@pytest.mark.parametrize(
    ('written', 'expected'),
    [
        (None, 90),  # derived: one instruction after another
        (600, 600),  # written: where every instruction is stopped
    ],
)
def test_a_plans_duration_is_written_or_derived(normalized, written, expected):
    plan = Plan(instructions=[single(30), single(60)])
    if written is not None:
        plan.estimated_duration = written * ureg.second

    assert seconds(normalized(plan)) == pytest.approx(expected)


@pytest.mark.parametrize(
    ('instruction', 'end'),
    [
        (single(90), datetime(2026, 1, 1, 0, 1, 30, tzinfo=timezone.utc)),
        (single(), None),
    ],
)
def test_a_scheduled_plan_ends_its_duration_after_it_starts(
    normalized, instruction, end
):
    plan = ScheduledPlan(
        scheduled_datetime=datetime(2026, 1, 1, tzinfo=timezone.utc),
        instructions=[instruction],
    )

    assert normalized(plan).scheduled_end_time == end


def test_execute_builds_the_activity_from_its_arguments_not_from_the_plan():
    plan = Plan(name='plan', description='what is planned')

    activity = plan.execute(
        name='run 1',
        description='the first run',
        datetime=None,
        datetime_end=None,
        method='soak',
        location='lab',
        steps=[],
    )

    assert (activity.name, activity.description) == ('run 1', 'the first run')
    assert (activity.method, activity.location) == ('soak', 'lab')


@pytest.mark.parametrize(
    ('section', 'reported'),
    [
        (SingleInstruction(estimated_duration=0 * ureg.second), 'must be positive'),
        (
            SingleInstruction(sub_instructions=[single(60)]),
            'cannot have sub-instructions',
        ),
        (InstructionBlock(), 'no sub-instructions'),
        (
            CountingRepeatingBlock(repeat_n=0, sub_instructions=[single(60)]),
            'at least once',
        ),
        (TimedRepeatingBlock(sub_instructions=[single(60)]), 'no `repeat_duration`'),
    ],
)
def test_an_impossible_instruction_is_reported(normalized, log, section, reported):
    normalized(section)

    [error] = log.errors
    assert reported in error


@pytest.mark.parametrize(
    ('block', 'label'),
    [
        (InstructionBlock(sub_instructions=[single(60)]), 'Run once (1 instruction)'),
        (
            CountingRepeatingBlock(
                repeat_n=3,
                sub_instruction_execution_mode='parallel',
                sub_instructions=[single(60), single(60)],
            ),
            'Repeat 3 times (2 instructions, in parallel)',
        ),
        (
            TimedRepeatingBlock(
                repeat_duration=43200 * ureg.second, sub_instructions=[single(60)]
            ),
            'Repeat for 12 h (1 instruction)',
        ),
        (
            IndefiniteRepeatingBlock(sub_instructions=[single(60)]),
            'Repeat indefinitely (1 instruction)',
        ),
        # A name, where one is written, is the label.
        (
            IndefiniteRepeatingBlock(name='soak', sub_instructions=[single(60)]),
            'soak',
        ),
    ],
)
def test_an_instruction_is_listed_by_its_name_or_by_what_it_does(
    normalized, block, label
):
    assert normalized(block).label == label
