"""Instructions, blocks and plans, which name no PV concept (Design.md §23).

An instruction is completed after its `estimated_duration`; empty means it never
finishes. A block's duration is always derived from what it contains, and only a plan
stops its instructions early.
"""

from datetime import datetime, timezone

import pytest
from nomad.units import ureg

from nomad_pv_stability_measurements.schema_packages.general import (
    CountingRepeatingBlock,
    Instruction,
    InstructionBlock,
    Plan,
    ScheduledPlan,
    SingleInstruction,
    TimedRepeatingBlock,
    combined_duration,
)

#: Any count of iterations more than one.
REPEATS = 5


def single(seconds=None, **fields) -> SingleInstruction:
    if seconds is not None:
        fields['estimated_duration'] = seconds * ureg.second
    return SingleInstruction(**fields)


def seconds(quantity):
    return None if quantity is None else quantity.to('s').magnitude


# `combined_duration`


@pytest.mark.parametrize(
    ('mode', 'expected'), [('sequential', 5400), ('parallel', 3600)]
)
def test_instructions_last_together_as_their_mode_says(mode, expected):
    durations = [1800 * ureg.second, 1 * ureg.hour]

    assert seconds(combined_duration(durations, mode)) == pytest.approx(expected)


@pytest.mark.parametrize('mode', ['sequential', 'parallel'])
def test_one_that_never_finishes_makes_all_of_them_never_finish(mode):
    assert combined_duration([1800 * ureg.second, None], mode) is None


def test_no_instructions_take_no_time():
    assert seconds(combined_duration([], 'sequential')) == 0


# `Instruction`


def test_an_instruction_is_named_and_described():
    assert {'name', 'description', 'estimated_duration'} <= set(
        Instruction.m_def.all_quantities
    )


def test_a_duration_must_be_positive(normalized, log):
    normalized(single(0, name='instant'))

    [error] = log.errors
    assert 'instant writes an `estimated_duration` of 0 s: it must be positive' in error


def test_a_single_instruction_without_sub_instructions_is_fine(normalized, log):
    normalized(single(60))

    assert (log.errors, log.warnings) == ([], [])


def test_a_single_instruction_has_no_sub_instructions(normalized, log):
    normalized(SingleInstruction(name='leaf', sub_instructions=[single(60)]))

    [error] = log.errors
    assert 'leaf is a `SingleInstruction` and cannot have sub-instructions' in error


# `InstructionBlock`, and the two blocks that repeat


def test_both_repeating_blocks_share_the_block_as_their_parent():
    assert CountingRepeatingBlock.__bases__ == (InstructionBlock,)
    assert TimedRepeatingBlock.__bases__ == (InstructionBlock,)
    # Each has only its own way of ending.
    assert 'repeat_duration' not in CountingRepeatingBlock.m_def.all_quantities
    assert 'repeat_n' not in TimedRepeatingBlock.m_def.all_quantities


def test_a_plain_block_runs_its_instructions_once(normalized, log):
    block = normalized(InstructionBlock(sub_instructions=[single(1800), single(3600)]))

    assert block.sub_instruction_execution_mode == 'sequential'
    assert seconds(block.estimated_duration) == pytest.approx(5400)
    assert (log.errors, log.warnings) == ([], [])


def test_a_parallel_block_lasts_as_its_longest_instruction_does(normalized):
    block = normalized(
        InstructionBlock(
            sub_instruction_execution_mode='parallel',
            sub_instructions=[single(1800), single(3600)],
        )
    )

    assert seconds(block.estimated_duration) == pytest.approx(3600)


def test_a_block_with_an_instruction_that_never_finishes_never_finishes(normalized):
    block = normalized(InstructionBlock(sub_instructions=[single(), single(60)]))

    assert block.estimated_duration is None


def test_a_blocks_duration_is_always_derived(normalized):
    # Instructions are consistent on their own: a written duration does not stand.
    block = normalized(
        InstructionBlock(
            estimated_duration=10 * ureg.second, sub_instructions=[single(60)]
        )
    )

    assert seconds(block.estimated_duration) == pytest.approx(60)


def test_a_nested_block_is_measured_before_its_parent_adds_it_up(normalized):
    inner = CountingRepeatingBlock(repeat_n=2, sub_instructions=[single(1800)])
    outer = normalized(InstructionBlock(sub_instructions=[inner, single(600)]))

    assert seconds(outer.estimated_duration) == pytest.approx(4200)


def test_a_block_has_sub_instructions(normalized, log):
    normalized(InstructionBlock(name='empty'))

    [error] = log.errors
    assert 'empty is a block, but has no sub-instructions' in error


# `CountingRepeatingBlock`


def test_a_counting_block_repeats_indefinitely_unless_told_otherwise(normalized, log):
    block = normalized(CountingRepeatingBlock(sub_instructions=[single(60)]))

    assert block.repeat_n is None
    assert block.estimated_duration is None
    assert (log.errors, log.warnings) == ([], [])


def test_indefinitely_survives_being_stored():
    # No default: an empty `repeat_n` is not filled in again when the archive is read.
    stored = CountingRepeatingBlock(sub_instructions=[single(60)]).m_to_dict()

    assert CountingRepeatingBlock.m_from_dict(stored).repeat_n is None


def test_a_counting_block_lasts_its_iterations_together(normalized, log):
    block = normalized(
        CountingRepeatingBlock(
            repeat_n=REPEATS, sub_instructions=[single(1800), single(3600)]
        )
    )

    assert seconds(block.estimated_duration) == pytest.approx(REPEATS * 5400)
    assert (log.errors, log.warnings) == ([], [])


def test_an_indefinite_block_inside_makes_its_parent_indefinite(normalized):
    inner = CountingRepeatingBlock(sub_instructions=[single(1800)])
    outer = normalized(
        CountingRepeatingBlock(repeat_n=REPEATS, sub_instructions=[inner])
    )

    assert outer.repeat_n == REPEATS  # as written: the parent itself is not changed
    assert outer.estimated_duration is None


def test_a_counting_block_runs_at_least_once(normalized, log):
    block = normalized(
        CountingRepeatingBlock(name='cycle', repeat_n=0, sub_instructions=[single(60)])
    )

    assert block.estimated_duration is None
    [error] = log.errors
    assert 'cycle writes `repeat_n` 0: a block runs at least once' in error


# `TimedRepeatingBlock`


def test_a_timed_block_lasts_until_it_is_stopped(normalized, log):
    block = normalized(
        TimedRepeatingBlock(
            repeat_duration=1000 * ureg.hour, sub_instructions=[single(3600), single()]
        )
    )

    # Stopped wherever its instructions are, even inside one that never finishes.
    assert block.estimated_duration.to('hour').magnitude == pytest.approx(1000)
    assert (log.errors, log.warnings) == ([], [])


def test_a_timed_block_without_a_time_never_finishes(normalized):
    block = normalized(TimedRepeatingBlock(sub_instructions=[single(60)]))

    assert block.estimated_duration is None


# `Plan`


def test_a_plan_is_an_entry_named_and_described_but_no_activity():
    assert {'name', 'description', 'estimated_duration'} <= set(
        Plan.m_def.all_quantities
    )
    assert 'datetime' not in Plan.m_def.all_quantities


def test_a_plan_runs_its_instructions_one_after_another(normalized):
    plan = normalized(Plan(instructions=[single(1800), single(3600)]))

    assert seconds(plan.estimated_duration) == pytest.approx(5400)


def test_a_plan_with_an_instruction_that_never_finishes_has_no_end(normalized):
    plan = normalized(Plan(instructions=[single(1800), single()]))

    assert plan.estimated_duration is None


def test_a_written_plan_duration_stops_its_instructions(normalized):
    plan = normalized(
        Plan(
            estimated_duration=600 * ureg.second, instructions=[single(), single(3600)]
        )
    )

    assert seconds(plan.estimated_duration) == pytest.approx(600)


def test_an_empty_plan_takes_no_time(normalized):
    assert seconds(normalized(Plan()).estimated_duration) == 0


def test_execute_takes_what_the_activity_is_from_its_arguments():
    plan = Plan(name='plan name', description='plan description')

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


# `ScheduledPlan`


def test_a_scheduled_plan_ends_its_duration_after_it_starts(normalized):
    plan = normalized(
        ScheduledPlan(
            scheduled_datetime=datetime(2026, 1, 1, tzinfo=timezone.utc),
            instructions=[single(90)],
        )
    )

    assert plan.scheduled_end_time == datetime(
        2026, 1, 1, 0, 1, 30, tzinfo=timezone.utc
    )


def test_a_scheduled_plan_that_never_finishes_has_no_end_time(normalized):
    plan = normalized(
        ScheduledPlan(
            scheduled_datetime=datetime(2026, 1, 1, tzinfo=timezone.utc),
            instructions=[single()],
        )
    )

    assert plan.scheduled_end_time is None
