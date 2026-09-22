from datetime import timedelta
from math import inf

import numpy as np
from nomad.datamodel.data import ArchiveSection
from nomad.datamodel.metainfo.basesections.v2 import ActivityStep, BaseSection
from nomad.metainfo import (
    Datetime,
    MEnum,
    Quantity,
    SchemaPackage,
    Section,
    SubSection,
)
from nomad.metainfo.metainfo import Reference, SectionProxy
from nomad.units import ureg

from nomad_pv_stability_measurements.schema_packages.utils import (
    ITERATIONS_FOR_PLOTTING,
    AxisBreak,
    PlotPiece,
    TimePlotSeries,
    drawing_end,
    instructions_for_plotting,
    shown,
    words,
)

m_package = SchemaPackage()

FIXED = 'fixed'
TYPICAL = 'typical'
WHOLE_BLOCK = 'whole_block'
OPEN_ENDED = 'open_ended'
DERIVED = 'derived'
#: The kinds that are a length, and so have a `value`.
WITH_VALUE = (FIXED, TYPICAL, DERIVED)
#: What a kind without a value lasts, in words.
WITHOUT_VALUE = {
    WHOLE_BLOCK: 'as long as its block',
    OPEN_ENDED: 'until something outside the plan stops it',
}


class Duration(ArchiveSection):
    """How long an instruction or a plan lasts, and what kind of length that is."""

    kind = Quantity(
        type=MEnum(FIXED, TYPICAL, WHOLE_BLOCK, OPEN_ENDED, DERIVED),
        description='What kind of length this is. `fixed`: exactly `value`. '
        '`typical`: it takes time the plan does not fix; `value` is a typical one, '
        'used to add up and draw the plan. `whole_block`: as long as the block or plan '
        'it is in, run in parallel; it does not count toward that length. '
        '`open_ended`: until something outside the plan stops it, such as an objective '
        'being reached or the operator. `derived`: worked out from the content, as a '
        "block's is from its sub-instructions; never written by hand.",
    )

    value = Quantity(
        type=np.float64,
        unit='s',
        description='The length. Required for a `fixed` or `typical` duration, and '
        'positive; empty for `whole_block` and `open_ended`; derived for `derived`.',
    )

    includes_typical = Quantity(
        type=bool,
        description='Of a `derived` duration: whether some part of it is only a typical '
        'length, so the whole is one too. Derived.',
    )

    def normalize(self, archive, logger):
        """Whether its value suits its kind, and a `whole_block` one its place."""
        super().normalize(archive, logger)
        owner = getattr(self.m_parent, 'name', None) or '<unnamed>'
        if self.kind == WHOLE_BLOCK:
            self.report_a_place_without_a_parallel_block(owner, logger)
        if self.kind in WITHOUT_VALUE and self.value is not None:
            logger.error(
                f'{owner} lasts {WITHOUT_VALUE[self.kind]}, so its duration takes no '
                f'value.'
            )
        elif self.kind in (FIXED, TYPICAL) and self.value is None:
            logger.error(f'{owner} has a {self.kind} duration, but no value.')
        elif self.kind in (FIXED, TYPICAL) and self.value <= 0:
            logger.error(
                f'{owner} writes a `duration` of {self.value.to("s").magnitude:g} s: '
                f'it must be positive.'
            )

    def report_a_place_without_a_parallel_block(self, owner: str, logger) -> None:
        """As long as its block only exists where the block runs its instructions in
        parallel: one after another, or with no block around it, there is no whole to
        last as long as."""
        container = self.m_parent.m_parent if self.m_parent is not None else None
        mode = execution_mode(container)
        if mode == 'parallel':
            return
        if mode is None:
            where = 'it is in no block'
        else:
            where = (
                f'{getattr(container, "name", None) or "<unnamed>"} runs its '
                f'instructions one after another'
            )
        logger.error(
            f'{owner} lasts as long as its block, but {where}: run it in a parallel '
            f'block, or give it a duration of its own.'
        )


def execution_mode(container) -> str | None:
    """How a block or a plan runs what it contains; `None` for anything else."""
    for field in ('sub_instruction_execution_mode', 'instruction_execution_mode'):
        if container is not None and field in container.m_def.all_quantities:
            return getattr(container, field)
    return None


def seconds_of(duration) -> float:
    """A duration's length in seconds; `inf` where it has none: open-ended, as long
    as its block, or not stated at all."""
    if duration is None or duration.kind not in WITH_VALUE or duration.value is None:
        return inf
    return duration.value.to('s').magnitude


def is_typical(duration) -> bool:
    """Whether a duration is, or includes, a typical length."""
    return duration is not None and (
        duration.kind == TYPICAL or bool(duration.includes_typical)
    )


def length_for_plotting(duration) -> str:
    """A length as a figure's title gives it: `725 h`, `≈ 725 h` where some of it is
    only typical; empty where it is open-ended."""
    if seconds_of(duration) == inf:
        return ''
    about = '≈ ' if is_typical(duration) else ''
    return f'{about}{shown(duration.value)}'


def titled_for_plotting(title: str, duration) -> str:
    """`title`, and its length where it has one: `soak · ≈ 725 h`. A variant's name
    has its choices in brackets already."""
    length = length_for_plotting(duration)
    return f'{title} · {length}' if length and title else title or length


def kind_of(instruction) -> str | None:
    duration = instruction.duration
    return None if duration is None else duration.kind


def combined_duration(instructions, mode: str) -> Duration:
    """How long `instructions` last together: one after another (`sequential`), their
    sum; all at once (`parallel`), the longest, not counting what lasts as long as the
    block. Open-ended where any of them is, or where nothing but `whole_block` is there.
    One after another, `whole_block` cannot be, and counts as open-ended."""
    parallel = mode == 'parallel'
    deciding = list(instructions)
    if parallel:
        deciding = [each for each in instructions if kind_of(each) != WHOLE_BLOCK]
        if instructions and not deciding:
            return Duration(kind=OPEN_ENDED)
    lengths = [each.seconds() for each in deciding]
    if inf in lengths:
        return Duration(kind=OPEN_ENDED)
    value = max(lengths, default=0) if parallel else sum(lengths)
    return Duration(
        kind=DERIVED,
        value=value * ureg.second,
        includes_typical=any(is_typical(each.duration) for each in deciding),
    )


def settle_duration(owner, logger) -> None:
    """The duration `owner` works out itself, where it does; else the one it states.
    Only what works it out writes a `derived` one."""
    derived = owner.derive_duration()
    if derived is not None:
        owner.duration = derived
        return
    name = owner.name or '<unnamed>'
    stated = '`fixed` or `typical` with a value, `whole_block` or `open_ended`'
    kind = kind_of(owner)
    if kind is None:
        logger.error(f'{name} states no duration: write {stated}.')
    elif kind == DERIVED:
        logger.error(
            f'{name} has a derived duration, but nothing to derive it from: write '
            f'{stated}.'
        )


class Instruction(ArchiveSection):
    """Something to be done, which is completed after its `duration`.

    Instructions are consistent on their own: a block's duration is always derived from
    what it contains. However, in some instances a `TimePlan`, or a timed block, can stop
    an instruction before it finishes, just like a process in a computer.
    """

    m_def = Section(
        label_quantity='label',
        # action specification
        links=['http://purl.obolibrary.org/obo/IAO_0000007'],
    )

    name = Quantity(type=str, description='A short name for this instruction.')

    label = Quantity(
        type=str,
        description='How the instruction is listed: its `name`, or else what it does, '
        'from what is written in it. Derived.',
    )

    description = Quantity(
        type=str, description='Anything else worth saying about this instruction.'
    )

    duration = SubSection(
        section_def=Duration,
        description='How long the whole instruction is going to take, including any '
        'sub-instructions, and what kind of length that is. A single instruction states '
        "it; a block's is derived from its sub-instructions.",
    )

    sub_instructions = SubSection(
        section_def=SectionProxy('Instruction'),
        repeats=True,
        description='The instructions a block runs. A block of one instruction is how '
        'that instruction is repeated. Empty for a single instruction, whose class '
        'describes what it does.',
    )

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        settle_duration(self, logger)
        self.label = self.name or self.describe()

    def derive_duration(self) -> Duration | None:
        """Its duration, worked out from what it contains or what is written in it;
        `None` where it has none to work out, and states one instead."""
        return None

    def describe(self) -> str:
        """What the instruction does, in a few words. Only what is written counts, not
        what `normalize` derives, so the label does not change when normalized again."""
        return words(type(self).__name__)

    def seconds(self) -> float:
        """How long it lasts in seconds; `inf` where it has no length of its own."""
        return seconds_of(self.duration)


class SingleInstruction(Instruction):
    """One instruction that contains no others.

    It states its own `duration`, and what kind it is: see `Duration`.
    """

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        if self.sub_instructions:
            logger.error(
                f'{self.name or "<unnamed>"} is a `SingleInstruction` and cannot have '
                f'sub-instructions.'
            )

    def time_series_for_plotting(self, start: float, stop: float) -> TimePlotSeries:
        """This instruction drawn from `start` until it finishes, or until `stop` where
        the drawing stops first, in seconds since the plan starts."""
        if start >= stop:
            return TimePlotSeries()
        endless = self.seconds() == inf
        end = stop if endless else min(stop, start + self.seconds())
        piece = PlotPiece(
            row=self.row_for_plotting(),
            label=self.label or self.describe(),
            start=start,
            end=end,
            endless=endless,
        )
        # Where nothing stops the drawing, only the extent is needed: see `TimePlan`.
        corners = None
        if end < inf:
            corners = self.set_values_for_plotting((end - start) * ureg.second)
        piece.bounds = self.bounds_for_plotting()
        piece.role = self.role_for_plotting()
        if corners is None:
            piece.text = self.annotation_for_plotting()
        else:
            times, piece.values = corners
            piece.times = start + times.to('s').magnitude
            piece.assumption = self.assumption_for_plotting()
        if endless:
            piece.cycle = self.cycle_for_plotting()
        if kind_of(self) == TYPICAL:
            piece.typical = f'typically {shown(self.duration.value)}'
        return TimePlotSeries([piece])

    def row_for_plotting(self) -> str:
        """The row it is drawn on: by default its own, named after its class."""
        return words(type(self).__name__)

    def set_values_for_plotting(self, length):
        """The corners `(times, values)` of what it sets over `length`; `None`: nothing
        the plan states as a value. See `MonitorControlInstruction`."""
        return None

    def bounds_for_plotting(self):
        """`(lower, upper)` of a band the value is kept in; `None`: no band."""
        return None

    def cycle_for_plotting(self) -> float | None:
        """s: one cycle of what it repeats by itself; `None`: it repeats nothing."""
        return None

    def assumption_for_plotting(self) -> str | None:
        """What the drawing assumes and the plan does not state; `None`: nothing."""
        return None

    def role_for_plotting(self) -> str:
        """`controlled`, `monitored` or `unspecified`: what colour it is drawn in."""
        return 'unspecified'

    def annotation_for_plotting(self) -> str:
        """What is written in place of a value."""
        return self.label or self.describe()


class InstructionBlock(Instruction):
    """Instructions run one after another or simultaneously — once.

    The parent of the blocks that repeat. Its `duration` is always derived
    from its sub-instructions: see `sub_instruction_execution_mode`.
    """

    sub_instruction_execution_mode = Quantity(
        type=MEnum('sequential', 'parallel'),
        default='sequential',
        description='Whether the sub-instructions run one after another (`sequential`) '
        "or all at once (`parallel`). This decides the block's `duration`. "
        '`sequential`: the sum of their durations. `parallel`: the longest, not '
        'counting a `whole_block` one, which is held for as long as the block runs. '
        'Either way, anything `open_ended` makes the block open-ended. A `whole_block` '
        'instruction only exists in parallel: to hold a setting during a phase, put it '
        'in a parallel block beside what the phase does.',
    )

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        if not self.sub_instructions:
            logger.error(
                f'{self.name or "<unnamed>"} is a block, but has no sub-instructions.'
            )

    def describe(self) -> str:
        count = len(self.sub_instructions)
        if count == 1:
            [only] = self.sub_instructions
            return f'{self.describe_repetition()}: {only.name or only.describe()}'
        parallel = (
            ', in parallel' if self.sub_instruction_execution_mode == 'parallel' else ''
        )
        return (
            f'{self.describe_repetition()} ({count} '
            f'instruction{"" if count == 1 else "s"}{parallel})'
        )

    def describe_repetition(self) -> str:
        return 'Run once'

    def one_iteration(self) -> Duration:
        """How long the sub-instructions take once."""
        return combined_duration(
            self.sub_instructions, self.sub_instruction_execution_mode
        )

    def derive_duration(self) -> Duration:
        return self.one_iteration()

    def repetitions(self) -> float:
        """How many times the sub-instructions run: once; `inf` where no count ends
        the block."""
        return 1

    def time_series_for_plotting(self, start: float, stop: float) -> TimePlotSeries:
        """Its first iterations, at most `ITERATIONS_FOR_PLOTTING`, then an axis break
        up to where the block ends, labelled with how it goes on. Times are accurate:
        what the break hides is not drawn, never moved."""
        series = TimePlotSeries()
        one = seconds_of(self.one_iteration())
        end = start + seconds_of(self.derive_duration())
        time = start
        for _ in range(min(self.repetitions(), ITERATIONS_FOR_PLOTTING)):
            if time >= min(stop, end):
                break
            # A condition in a parallel pass ends with the pass.
            series.extend(self.iteration_for_plotting(time, min(stop, end, time + one)))
            time += one
        # At `stop` too: the drawing may end exactly where the block breaks off.
        if time < end and time <= stop:
            series.breaks.append(AxisBreak(time, end, self.break_label_for_plotting()))
        return series

    def one_iteration_for_plotting(self) -> TimePlotSeries:
        """One pass of the sub-instructions on its own, from 0, as the block's own
        figure shows it; drawn like a plan that never ends where the pass never does."""
        stop = seconds_of(self.one_iteration())
        if stop == inf:
            stop = drawing_end(self.iteration_for_plotting(0.0, inf))
        series = self.iteration_for_plotting(0.0, stop)
        series.end = stop
        return series

    def title_for_plotting(self) -> str:
        """Its `name`, or else how it repeats and what it runs: `Repeat indefinitely:
        Hold irradiance 1000 W/m² for 1 h → Hold irradiance 0 W/m² for 1 h`."""
        if self.name:
            return self.name
        joint = ' + ' if self.sub_instruction_execution_mode == 'parallel' else ' → '
        labels = [each.label or each.describe() for each in self.sub_instructions]
        return f'{self.describe_repetition()}: {joint.join(labels)}'

    def iteration_for_plotting(self, start: float, stop: float) -> TimePlotSeries:
        """One pass of the sub-instructions."""
        return instructions_for_plotting(
            self.sub_instructions, self.sub_instruction_execution_mode, start, stop
        )

    def break_label_for_plotting(self) -> str:
        """What the axis break after the drawn iterations stands for."""
        return ''


class RepeatingBlock(InstructionBlock):
    """Instructions repeated — a block that may or may not finish.

    Its kind says which: a timed block always finishes, an indefinite one never does, and
    a counting one should. On its own it is not known to finish, so its
    `duration` is open-ended.
    """

    def describe_repetition(self) -> str:
        return 'Repeat indefinitely'

    def derive_duration(self) -> Duration:
        return Duration(kind=OPEN_ENDED)

    def repetitions(self) -> float:
        return inf

    def break_label_for_plotting(self) -> str:
        return 'indefinitely'


class TimedRepeatingBlock(RepeatingBlock):
    """Instructions repeated for `repeat_duration`, then stopped — wherever they are.

    It always finishes: `repeat_duration` is what ends it, and so its fixed
    `duration`, whether or not its sub-instructions ever finish.
    """

    repeat_duration = Quantity(
        type=np.float64,
        unit='s',
        description='How long the sub-instructions are repeated for, before they are '
        'stopped. Must be positive.',
    )

    def normalize(self, archive, logger):
        if self.repeat_duration is None:
            logger.error(
                f'{self.name or "<unnamed>"} is a timed block, but has no '
                f'`repeat_duration`.'
            )
        super().normalize(archive, logger)

    def describe_repetition(self) -> str:
        if self.repeat_duration is None:
            return 'Repeat'
        return f'Repeat for {shown(self.repeat_duration)}'

    def derive_duration(self) -> Duration:
        if self.repeat_duration is None:
            return Duration(kind=OPEN_ENDED)
        return Duration(kind=FIXED, value=self.repeat_duration)

    def break_label_for_plotting(self) -> str:
        return f'until t+{shown(self.repeat_duration)}'


IndefiniteRepeatingBlock = RepeatingBlock
"""Instructions repeated until something outside stops them — it never finishes.

Its `duration` is always open-ended; only the plan it belongs to ends it.
"""


class CountingRepeatingBlock(RepeatingBlock):
    """Instructions repeated `repeat_n` times — it should finish.

    Its `duration` is one iteration times `repeat_n`. Without a count, or with an
    open-ended sub-instruction, it does not finish after all: that is warned about, and
    its `duration` is open-ended.
    """

    repeat_n = Quantity(
        type=int,
        description='How many times the sub-instructions are run. Must be positive.',
    )

    def normalize(self, archive, logger):
        name = self.name or '<unnamed>'
        if self.repeat_n is None:
            logger.warning(
                f'{name} counts its repetitions, but has no `repeat_n`, so it never '
                f'finishes. A block meant to never finish is an IndefiniteRepeatingBlock.'
            )
        elif self.repeat_n < 1:
            logger.error(
                f'{name} writes `repeat_n` {self.repeat_n}: a block runs at least once.'
            )
        super().normalize(archive, logger)
        if (
            self.repeat_n is not None
            and self.sub_instructions
            and self.one_iteration().kind == OPEN_ENDED
        ):
            logger.warning(
                f'{name} counts its repetitions, but a sub-instruction never finishes, '
                f'so it never finishes either.'
            )

    def describe_repetition(self) -> str:
        if self.repeat_n is None:
            return 'Repeat'
        return 'Run once' if self.repeat_n == 1 else f'Repeat {self.repeat_n} times'

    def derive_duration(self) -> Duration:
        one = self.one_iteration()
        if one.kind == OPEN_ENDED or self.repeat_n is None or self.repeat_n < 1:
            return Duration(kind=OPEN_ENDED)
        return Duration(
            kind=DERIVED,
            value=self.repeat_n * one.value,
            includes_typical=one.includes_typical,
        )

    def repetitions(self) -> float:
        return inf if self.repeat_n is None else self.repeat_n

    def break_label_for_plotting(self) -> str:
        if self.repeat_n is None:
            return super().break_label_for_plotting()
        return f'n={self.repeat_n} repetitions'


class Objective(ArchiveSection):
    """What a plan is meant to achieve: an intended endpoint of the activity running
    it. A specialized objective states a criterion and overrides `is_achieved`.
    """

    m_def = Section(
        # objective specification
        links=['http://purl.obolibrary.org/obo/IAO_0000005'],
    )

    description = Quantity(type=str, description='The objective, in words.')

    def is_achieved(self, activity) -> bool | None:
        """Whether `activity` met this objective at its end. `None` if that cannot be
        told, as for an objective stated only in words."""
        return None


class Plan(BaseSection):
    """What is planned to be done, as instructions, and what for, as objectives."""

    m_def = Section(
        # plan specification
        links=['http://purl.obolibrary.org/obo/IAO_0000104'],
    )

    instructions = SubSection(
        section_def=Instruction,
        repeats=True,
        description='The instructions that make up this plan.',
    )

    objectives = SubSection(
        section_def=Objective,
        repeats=True,
        description='What this plan is meant to achieve. Whether an activity achieved '
        'them is a matter of that activity, not of the plan.',
    )


class Deviation(ArchiveSection):
    """What is different between an activity and the plans it is based on."""

    description = Quantity(
        type=str,
        description='A short description of what is different between the activity '
        'and the plans it is based on.',
    )

    plan = Quantity(
        type=Reference(Plan),
        description='The plan that this deviation is related to. Only needed where '
        'the activity combines several plans.',
    )

    conflicting_instructions = Quantity(
        type=Reference(Instruction),
        description='The instruction that this deviation is related to.',
        shape=['*'],
    )

    conflicting_steps = Quantity(
        type=Reference(ActivityStep),
        description='The steps that are different between the activity and the plans it is based on.',
        shape=['*'],
    )


class Planned(ArchiveSection):
    """A mixin for an activity based on a plan: inherit it next to an `Activity`, e.g.
    `class StabilityActivity(Measurement, Planned)`.

    A subclass narrows `plan` to the kind of plan it runs.
    """

    m_def = Section(
        # planned process
        links=['http://purl.obolibrary.org/obo/COB_0000082'],
    )

    plan = Quantity(
        type=Reference(Plan),
        description='The plan that this activity is based on.',
    )

    deviations_from_plan = SubSection(
        section_def=Deviation,
        description='What is different between the activity and the plan it is based '
        'on. Derived from the activity and the plan.',
        repeats=True,
    )

    def populate_from_plan(self):
        """Override it to fill in the activity from its `plan`. By default, nothing is
        filled in."""

    def has_reached_objectives(self) -> bool:
        """Override it to state if the objectives were achieved. By default, yes"""
        return True

    def is_consistent_with_plan(self) -> bool:
        """Override it to check the activity against its `plan`. By default, it is
        consistent."""
        return True


class TimePlan(Plan):
    """A plan that knows how long it lasts: written, or derived from its instructions."""

    duration = SubSection(
        section_def=Duration,
        description='How long this plan lasts (assuming everything goes as expected). '
        'Written, it stands: a length stops every instruction still running there, and '
        '`open_ended` says the plan is ended from outside, e.g. when an objective is '
        'reached. Else it is derived from the instructions. A plan is in no block, so '
        'it cannot be `whole_block`.',
    )

    #: How a plan runs its `instructions`. A subclass can overwrite the default.
    instruction_execution_mode = Quantity(
        type=MEnum('sequential', 'parallel'),
        default='sequential',
        description='Whether the instructions run one after another (`sequential`) or '
        'all at once (`parallel`). Where the plan has no written `duration`, this '
        'decides it, as for a block. `sequential`: the sum of their durations. '
        '`parallel`: the longest, not counting a `whole_block` one, which is held for '
        'as long as the plan runs. Either way, anything `open_ended` makes the plan '
        'open-ended.',
    )

    def combine_instruction_durations(self) -> Duration:
        """How long the instructions last together, run as `instruction_execution_mode`
        says. Override it for any other rule."""
        return combined_duration(self.instructions, self.instruction_execution_mode)

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        settle_duration(self, logger)

    def derive_duration(self) -> Duration | None:
        """From the instructions, where no duration is written. The instructions are
        normalized before the plan, so theirs are there."""
        if kind_of(self) not in (None, DERIVED):
            return None
        return self.combine_instruction_durations()

    def seconds(self) -> float:
        """How long it lasts in seconds; `inf` where it is open-ended."""
        return seconds_of(self.duration)

    def time_series_for_plotting(self) -> TimePlotSeries:
        """The plan drawn from its start until its `duration`. A plan that never ends is
        drawn until the last thing in it starts, finishes or breaks off: found by a first
        pass that nothing stops, then drawn again up to there."""
        stop = self.seconds()
        if stop == inf:
            stop = drawing_end(self.instructions_for_plotting(inf))
        series = self.instructions_for_plotting(stop)
        series.end = stop
        return series

    def instructions_for_plotting(self, stop: float) -> TimePlotSeries:
        return instructions_for_plotting(
            self.instructions, self.instruction_execution_mode, 0.0, stop
        )


class ScheduledPlan(TimePlan):
    """A plan that has a scheduled time to run, but has not yet."""

    scheduled_datetime = Quantity(
        type=Datetime,
        description='When this plan is scheduled to start.',
    )

    scheduled_end_time = Quantity(
        type=Datetime,
        description='When this plan is scheduled to end. Empty if it never does.',
    )

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        if self.scheduled_datetime is not None and self.seconds() < inf:
            self.scheduled_end_time = self.scheduled_datetime + timedelta(
                seconds=self.seconds()
            )


m_package.__init_metainfo__()
