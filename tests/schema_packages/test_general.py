"""Instructions, blocks and plans (Design.md §23, §27).

An instruction is completed after its `duration`; empty means it never
finishes, except for a single instruction in a parallel block, which lasts as long as the
block (§32). A block's duration is always derived from what it contains. A repeating block's
kind says whether it finishes: a timed one always, an indefinite one never, a counting one
should. Only a plan, or a timed block, stops instructions early.
"""

from datetime import datetime, timezone
from math import inf

import pytest
from nomad.datamodel.metainfo.basesections.v2 import Activity
from nomad.units import ureg

from nomad_pv_stability_measurements.schema_packages.general import (
    CountingRepeatingBlock,
    IndefiniteRepeatingBlock,
    InstructionBlock,
    Objective,
    ScheduledPlan,
    SingleInstruction,
    TimedRepeatingBlock,
    TimePlan,
)


def single(seconds=None) -> SingleInstruction:
    """An instruction lasting `seconds`; without them, one that never finishes."""
    if seconds is None:
        return SingleInstruction()
    return SingleInstruction(duration=seconds * ureg.second)


def seconds(section):
    duration = section.duration
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
        TimePlan(instructions=[InstructionBlock(sub_instructions=[inner, single(60)])])
    )

    assert seconds(plan.instructions[0]) is None
    assert seconds(plan) is None


@pytest.mark.parametrize(
    ('mode', 'sub_instructions', 'expected'),
    [
        # A single instruction without a duration lasts as long as its parallel block.
        ('parallel', [single(), single(60)], 60),
        ('parallel', [single(), single()], None),  # nothing in it finishes
        # A block without a duration never finishes, and keeps its parent going.
        (
            'parallel',
            [single(), IndefiniteRepeatingBlock(sub_instructions=[single(60)])],
            None,
        ),
        # One after another, what never finishes leaves no time for what follows.
        ('sequential', [single(), single(60)], None),
    ],
)
def test_a_parallel_block_lasts_as_long_as_what_finishes_in_it(
    normalized, mode, sub_instructions, expected
):
    block = InstructionBlock(
        sub_instruction_execution_mode=mode, sub_instructions=sub_instructions
    )

    assert seconds(normalized(block)) == expected


def test_a_phase_that_holds_a_condition_ends_with_its_routine(normalized):
    condition = single()
    cycling = CountingRepeatingBlock(repeat_n=2, sub_instructions=[single(1800)])
    phase = InstructionBlock(
        sub_instruction_execution_mode='parallel', sub_instructions=[condition, cycling]
    )
    recovery = single(3600)
    block = normalized(InstructionBlock(sub_instructions=[phase, recovery]))

    phase_ends = 2 * 1800
    assert seconds(block) == pytest.approx(phase_ends + 3600)
    pieces = block.time_series_for_plotting(0, 10**7).pieces
    assert (pieces[0].start, pieces[0].end) == (0, phase_ends)  # the condition
    assert pieces[-1].start == phase_ends  # the recovery


def test_a_blocks_written_duration_is_replaced_by_the_derived_one(normalized):
    block = InstructionBlock(duration=10 * ureg.second, sub_instructions=[single(60)])

    assert seconds(normalized(block)) == pytest.approx(60)


@pytest.mark.parametrize(
    ('written', 'expected'),
    [
        (None, 90),  # derived: one instruction after another
        (600, 600),  # written: where every instruction is stopped
    ],
)
def test_a_plans_duration_is_written_or_derived(normalized, written, expected):
    plan = TimePlan(instructions=[single(30), single(60)])
    if written is not None:
        plan.duration = written * ureg.second

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


@pytest.mark.parametrize(
    ('section', 'reported'),
    [
        (SingleInstruction(duration=0 * ureg.second), 'must be positive'),
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
        (
            InstructionBlock(sub_instructions=[single(60)]),
            'Run once: Single instruction',
        ),
        # A block of one instruction is how that instruction is repeated.
        (
            CountingRepeatingBlock(
                repeat_n=5,
                sub_instructions=[
                    SingleInstruction(name='JV scan', duration=60 * ureg.second)
                ],
            ),
            'Repeat 5 times: JV scan',
        ),
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
            'Repeat for 12 h: Single instruction',
        ),
        (
            IndefiniteRepeatingBlock(sub_instructions=[single(60)]),
            'Repeat indefinitely: Single instruction',
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


def test_an_objective_in_words_cannot_be_told_achieved():
    objective = Objective(description='T80 under 1 sun at 65 °C')

    assert objective.is_achieved(Activity()) is None


HOUR = 3600
FAR = 10**7  # s: where the drawing stops, beyond any block here


@pytest.mark.parametrize(
    ('mode', 'starts'), [('sequential', [0, HOUR]), ('parallel', [0, 0])]
)
def test_a_block_draws_its_instructions_one_after_another_or_together(
    normalized, mode, starts
):
    block = normalized(
        InstructionBlock(
            sub_instruction_execution_mode=mode,
            sub_instructions=[single(HOUR), single(HOUR / 2)],
        )
    )

    series = block.time_series_for_plotting(0, FAR)

    assert [piece.start for piece in series.pieces] == starts
    assert series.breaks == []


@pytest.mark.parametrize(
    ('block', 'drawn', 'cut'),
    [
        (CountingRepeatingBlock(repeat_n=2), 2, None),
        (CountingRepeatingBlock(repeat_n=300), 3, (300 * HOUR, 'n=300 repetitions')),
        (
            TimedRepeatingBlock(repeat_duration=300 * ureg.hour),
            3,
            (300 * HOUR, 'until t+300 h'),
        ),
        (IndefiniteRepeatingBlock(), 3, (inf, 'indefinitely')),
    ],
)
def test_a_repeating_block_draws_three_iterations_then_breaks_the_axis_to_its_end(
    normalized, block, drawn, cut
):
    block.sub_instructions = [single(HOUR)]
    series = normalized(block).time_series_for_plotting(0, FAR)

    assert [piece.start for piece in series.pieces] == [n * HOUR for n in range(drawn)]
    breaks = [(each.start, each.end, each.label) for each in series.breaks]
    assert breaks == ([] if cut is None else [(drawn * HOUR, *cut)])


def test_a_condition_in_a_repeating_parallel_block_is_drawn_once_per_iteration(
    normalized,
):
    block = normalized(
        CountingRepeatingBlock(
            repeat_n=2,
            sub_instruction_execution_mode='parallel',
            sub_instructions=[single(), single(HOUR)],
        )
    )

    series = block.time_series_for_plotting(0, FAR)

    conditions = series.pieces[::2]  # each iteration draws the condition first
    assert [(piece.start, piece.end) for piece in conditions] == [
        (0, HOUR),
        (HOUR, 2 * HOUR),
    ]


def test_a_plans_settings_last_as_long_as_its_routine(normalized):
    setting = single()
    routine = CountingRepeatingBlock(repeat_n=2, sub_instructions=[single(HOUR)])
    plan = normalized(
        TimePlan(instruction_execution_mode='parallel', instructions=[setting, routine])
    )

    assert seconds(plan) == pytest.approx(2 * HOUR)
    assert plan.time_series_for_plotting().pieces[0].end == 2 * HOUR


def test_a_plan_that_never_ends_is_drawn_until_its_routine_breaks_off(normalized):
    setting = single()
    routine = IndefiniteRepeatingBlock(sub_instructions=[single(HOUR)])
    plan = normalized(
        TimePlan(instruction_execution_mode='parallel', instructions=[setting, routine])
    )

    series = plan.time_series_for_plotting()

    [cut] = series.breaks
    assert (cut.start, cut.label) == (3 * HOUR, 'indefinitely')
    assert series.pieces[0].end == 3 * HOUR  # the setting runs to the edge


def test_a_plan_is_drawn_until_its_duration(normalized):
    plan = normalized(
        TimePlan(
            duration=90 * ureg.minute, instructions=[single(HOUR) for _ in range(3)]
        )
    )

    pieces = plan.time_series_for_plotting().pieces

    assert [(piece.start, piece.end) for piece in pieces] == [
        (0, HOUR),
        (HOUR, 1.5 * HOUR),
    ]
