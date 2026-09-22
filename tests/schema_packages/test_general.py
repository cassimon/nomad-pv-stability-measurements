"""Instructions, blocks and plans.

An instruction is completed after its `duration`, whose kind says what it is: a fixed or
typical length, as long as its block, open-ended, or derived. A single instruction states
it; a block's is always derived from what it contains. A repeating block's kind says whether
it finishes: a timed one always, an indefinite one never, a counting one should. Only a
plan, or a timed block, stops instructions early.
"""

from datetime import datetime, timezone
from math import inf

import pytest
from nomad.datamodel.metainfo.basesections.v2 import Activity
from nomad.units import ureg

from nomad_pv_stability_measurements.schema_packages.general import (
    CountingRepeatingBlock,
    Duration,
    IndefiniteRepeatingBlock,
    InstructionBlock,
    Objective,
    ScheduledPlan,
    SingleInstruction,
    TimedRepeatingBlock,
    TimePlan,
)


def single(kind='fixed', seconds=None, **fields) -> SingleInstruction:
    duration = Duration(kind=kind)
    if seconds is not None:
        duration.value = seconds * ureg.second
    return SingleInstruction(duration=duration, **fields)


def fixed(seconds, **fields) -> SingleInstruction:
    return single('fixed', seconds, **fields)


def whole_block() -> SingleInstruction:
    """A setting: as long as the block it is in."""
    return single('whole_block')


def open_ended() -> SingleInstruction:
    return single('open_ended')


def seconds(section):
    """Its length in seconds; `None` where it is open-ended."""
    assert section.duration.kind != 'whole_block'
    if section.duration.kind == 'open_ended':
        return None
    return section.duration.value.to('s').magnitude


@pytest.mark.parametrize(('mode', 'expected'), [('sequential', 90), ('parallel', 60)])
def test_a_block_lasts_one_pass_of_its_instructions(normalized, mode, expected):
    block = InstructionBlock(
        sub_instruction_execution_mode=mode, sub_instructions=[fixed(30), fixed(60)]
    )

    assert seconds(normalized(block)) == pytest.approx(expected)
    assert block.duration.kind == 'derived'


def test_a_counting_block_lasts_its_count_times_one_pass(normalized):
    block = CountingRepeatingBlock(repeat_n=3, sub_instructions=[fixed(30), fixed(60)])

    assert seconds(normalized(block)) == pytest.approx(270)


@pytest.mark.parametrize(
    'block',
    [
        CountingRepeatingBlock(sub_instructions=[fixed(60)]),
        CountingRepeatingBlock(repeat_n=3, sub_instructions=[open_ended()]),
    ],
)
def test_a_counting_block_that_does_not_finish_is_warned_about(normalized, log, block):
    assert seconds(normalized(block)) is None
    [warning] = log.warnings
    assert 'never finishes' in warning


def test_an_indefinite_block_never_finishes(normalized, log):
    block = normalized(IndefiniteRepeatingBlock(sub_instructions=[fixed(60)]))

    assert seconds(block) is None
    assert (log.errors, log.warnings) == ([], [])


def test_a_timed_block_lasts_its_repeat_duration_whatever_it_contains(normalized):
    block = TimedRepeatingBlock(
        repeat_duration=3600 * ureg.second, sub_instructions=[fixed(60), open_ended()]
    )

    assert seconds(normalized(block)) == pytest.approx(3600)
    assert block.duration.kind == 'fixed'


def test_what_is_open_ended_makes_everything_around_it_open_ended(normalized):
    inner = IndefiniteRepeatingBlock(sub_instructions=[fixed(60)])
    plan = normalized(
        TimePlan(instructions=[InstructionBlock(sub_instructions=[inner, fixed(60)])])
    )

    assert seconds(plan.instructions[0]) is None
    assert seconds(plan) is None


@pytest.mark.parametrize(
    ('mode', 'sub_instructions', 'expected'),
    [
        # What lasts as long as its block does not count toward the block's length.
        ('parallel', [whole_block(), fixed(60)], 60),
        ('parallel', [whole_block(), whole_block()], None),  # nothing ends it
        (
            'parallel',
            [whole_block(), IndefiniteRepeatingBlock(sub_instructions=[fixed(60)])],
            None,
        ),
        # One after another, what is open-ended leaves no time for what follows.
        ('sequential', [open_ended(), fixed(60)], None),
    ],
)
def test_a_block_lasts_as_long_as_what_ends_in_it(
    normalized, mode, sub_instructions, expected
):
    block = InstructionBlock(
        sub_instruction_execution_mode=mode, sub_instructions=sub_instructions
    )

    assert seconds(normalized(block)) == expected


@pytest.mark.parametrize('mode', ['sequential', 'parallel'])
def test_a_typical_length_counts_and_makes_the_whole_typical(normalized, mode):
    block = normalized(
        CountingRepeatingBlock(
            repeat_n=2,
            sub_instruction_execution_mode=mode,
            sub_instructions=[single('typical', 60), fixed(30)],
        )
    )

    assert seconds(block) == pytest.approx(180 if mode == 'sequential' else 120)
    assert block.duration.includes_typical is True


@pytest.mark.parametrize(
    'owner',
    [
        InstructionBlock(sub_instructions=[whole_block(), fixed(60)]),
        TimePlan(
            instruction_execution_mode='sequential',
            instructions=[whole_block(), fixed(60)],
        ),
    ],
)
def test_nothing_run_one_after_another_lasts_as_long_as_its_block(
    normalized, log, owner
):
    normalized(owner)

    [error] = log.errors
    assert 'one after another' in error


def test_a_phase_that_holds_a_condition_ends_with_its_routine(normalized):
    condition = whole_block()
    cycling = CountingRepeatingBlock(repeat_n=2, sub_instructions=[fixed(1800)])
    phase = InstructionBlock(
        sub_instruction_execution_mode='parallel', sub_instructions=[condition, cycling]
    )
    recovery = fixed(3600)
    block = normalized(InstructionBlock(sub_instructions=[phase, recovery]))

    phase_ends = 2 * 1800
    assert seconds(block) == pytest.approx(phase_ends + 3600)
    pieces = block.time_series_for_plotting(0, 10**7).pieces
    assert (pieces[0].start, pieces[0].end) == (0, phase_ends)  # the condition
    assert pieces[-1].start == phase_ends  # the recovery


def test_a_blocks_written_duration_is_replaced_by_the_derived_one(normalized):
    block = InstructionBlock(
        duration=Duration(kind='fixed', value=10 * ureg.second),
        sub_instructions=[fixed(60)],
    )

    assert seconds(normalized(block)) == pytest.approx(60)


@pytest.mark.parametrize(
    ('written', 'expected'),
    [
        (None, 90),  # derived: one instruction after another
        (Duration(kind='fixed', value=600 * ureg.second), 600),  # stops them all there
        (Duration(kind='open_ended'), None),  # ended from outside, e.g. at T80
    ],
)
def test_a_plans_duration_is_written_or_derived(normalized, log, written, expected):
    plan = normalized(TimePlan(duration=written, instructions=[fixed(30), fixed(60)]))

    assert seconds(plan) == (None if expected is None else pytest.approx(expected))
    assert log.errors == []


@pytest.mark.parametrize(
    ('instruction', 'end'),
    [
        (fixed(90), datetime(2026, 1, 1, 0, 1, 30, tzinfo=timezone.utc)),
        (open_ended(), None),
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
        (fixed(0), 'must be positive'),
        (SingleInstruction(), 'states no duration'),
        (single('derived', 60), 'nothing to derive it from'),
        (single('typical'), 'but no value'),
        (single('open_ended', 60), 'takes no value'),
        (fixed(60, sub_instructions=[fixed(60)]), 'cannot have sub-instructions'),
        (InstructionBlock(), 'no sub-instructions'),
        (
            CountingRepeatingBlock(repeat_n=0, sub_instructions=[fixed(60)]),
            'at least once',
        ),
        (TimedRepeatingBlock(sub_instructions=[fixed(60)]), 'no `repeat_duration`'),
        (
            TimePlan(duration=Duration(kind='whole_block'), instructions=[fixed(60)]),
            'in no block',
        ),
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
            InstructionBlock(sub_instructions=[fixed(60)]),
            'Run once: Single instruction',
        ),
        # A block of one instruction is how that instruction is repeated.
        (
            CountingRepeatingBlock(
                repeat_n=5,
                sub_instructions=[fixed(60, name='JV scan')],
            ),
            'Repeat 5 times: JV scan',
        ),
        (
            CountingRepeatingBlock(
                repeat_n=3,
                sub_instruction_execution_mode='parallel',
                sub_instructions=[fixed(60), fixed(60)],
            ),
            'Repeat 3 times (2 instructions, in parallel)',
        ),
        (
            TimedRepeatingBlock(
                repeat_duration=43200 * ureg.second, sub_instructions=[fixed(60)]
            ),
            'Repeat for 12 h: Single instruction',
        ),
        (
            IndefiniteRepeatingBlock(sub_instructions=[fixed(60)]),
            'Repeat indefinitely: Single instruction',
        ),
        # A name, where one is written, is the label.
        (
            IndefiniteRepeatingBlock(name='soak', sub_instructions=[fixed(60)]),
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
            sub_instructions=[fixed(HOUR), fixed(HOUR / 2)],
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
    block.sub_instructions = [fixed(HOUR)]
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
            sub_instructions=[whole_block(), fixed(HOUR)],
        )
    )

    series = block.time_series_for_plotting(0, FAR)

    conditions = series.pieces[::2]  # each iteration draws the condition first
    assert [(piece.start, piece.end) for piece in conditions] == [
        (0, HOUR),
        (HOUR, 2 * HOUR),
    ]


def test_a_plans_settings_last_as_long_as_its_routine(normalized):
    setting = whole_block()
    routine = CountingRepeatingBlock(repeat_n=2, sub_instructions=[fixed(HOUR)])
    plan = normalized(
        TimePlan(instruction_execution_mode='parallel', instructions=[setting, routine])
    )

    assert seconds(plan) == pytest.approx(2 * HOUR)
    assert plan.time_series_for_plotting().pieces[0].end == 2 * HOUR


def test_a_plan_that_never_ends_is_drawn_until_its_routine_breaks_off(normalized):
    setting = whole_block()
    routine = IndefiniteRepeatingBlock(sub_instructions=[fixed(HOUR)])
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
            duration=Duration(kind='fixed', value=90 * ureg.minute),
            instructions=[fixed(HOUR) for _ in range(3)],
        )
    )

    pieces = plan.time_series_for_plotting().pieces

    assert [(piece.start, piece.end) for piece in pieces] == [
        (0, HOUR),
        (HOUR, 1.5 * HOUR),
    ]
