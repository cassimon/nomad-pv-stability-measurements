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
    combined_duration,
    drawing_end,
    instructions_for_plotting,
    seconds_or_inf,
    shown,
    words,
)

m_package = SchemaPackage()


class Instruction(ArchiveSection):
    """Something to be done, which is completed after its `duration`.

    Instructions are consistent on their own: a block's duration is always derived from
    what it contains. Only a `Plan` stops its instructions early.
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

    duration = Quantity(
        type=np.float64,
        unit='s',
        description='How long the whole instruction is going to take, including any '
        'sub-instructions. Must be positive. Empty means the end is indefinite.',
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
        if self.duration is not None and self.duration <= 0:
            logger.error(
                f'{self.name or "<unnamed>"} writes a `duration` of '
                f'{self.duration.to("s").magnitude:g} s: it must be positive.'
            )
        self.label = self.name or self.describe()

    def describe(self) -> str:
        """What the instruction does, in a few words. Only what is written counts, not
        what `normalize` derives, so the label does not change when normalized again."""
        return words(type(self).__name__)


class SingleInstruction(Instruction):
    """One instruction that contains no others."""

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
        endless = self.duration is None
        end = stop if endless else min(stop, start + self.duration.to('s').magnitude)
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
    from its sub-instructions, and empty if any of them never finishes.
    """

    sub_instruction_execution_mode = Quantity(
        type=MEnum('sequential', 'parallel'),
        default='sequential',
        description='Whether the sub-instructions are executed one after another or all '
        'at once.',
    )

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        if not self.sub_instructions:
            logger.error(
                f'{self.name or "<unnamed>"} is a block, but has no sub-instructions.'
            )
        self.duration = self.derive_duration()

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

    def one_iteration(self):
        """How long the sub-instructions take once; `None` if they never finish."""
        return combined_duration(
            [each.duration for each in self.sub_instructions],
            self.sub_instruction_execution_mode,
        )

    def derive_duration(self):
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
        one = seconds_or_inf(self.one_iteration())
        end = start + seconds_or_inf(self.derive_duration())
        time = start
        for _ in range(min(self.repetitions(), ITERATIONS_FOR_PLOTTING)):
            if time >= min(stop, end):
                break
            series.extend(self.iteration_for_plotting(time, min(stop, end)))
            time += one
        # At `stop` too: the drawing may end exactly where the block breaks off.
        if time < end and time <= stop:
            series.breaks.append(AxisBreak(time, end, self.break_label_for_plotting()))
        return series

    def one_iteration_for_plotting(self) -> TimePlotSeries:
        """One pass of the sub-instructions on its own, from 0, as the block's own
        figure shows it; drawn like a plan that never ends where the pass never does."""
        stop = seconds_or_inf(self.one_iteration())
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
    `duration` is empty.
    """

    def describe_repetition(self) -> str:
        return 'Repeat indefinitely'

    def derive_duration(self):
        return None

    def repetitions(self) -> float:
        return inf

    def break_label_for_plotting(self) -> str:
        return 'indefinitely'


class TimedRepeatingBlock(RepeatingBlock):
    """Instructions repeated for `repeat_duration`, then stopped — wherever they are.

    It always finishes: `repeat_duration` is what ends it, and so its
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

    def derive_duration(self):
        return self.repeat_duration

    def break_label_for_plotting(self) -> str:
        return f'until t+{shown(self.repeat_duration)}'


IndefiniteRepeatingBlock = RepeatingBlock
"""Instructions repeated until something outside stops them — it never finishes.

Its `duration` is always empty; only the plan it belongs to ends it.
"""


class CountingRepeatingBlock(RepeatingBlock):
    """Instructions repeated `repeat_n` times — it should finish.

    Its `duration` is one iteration times `repeat_n`. Without a count, or with a
    sub-instruction that never finishes, it does not finish after all: that is warned
    about, and its `duration` is empty.
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
            and (self.one_iteration() is None)
        ):
            logger.warning(
                f'{name} counts its repetitions, but a sub-instruction never finishes, '
                f'so it never finishes either.'
            )

    def describe_repetition(self) -> str:
        if self.repeat_n is None:
            return 'Repeat'
        return 'Run once' if self.repeat_n == 1 else f'Repeat {self.repeat_n} times'

    def derive_duration(self):
        one = self.one_iteration()
        if one is None or self.repeat_n is None or self.repeat_n < 1:
            return None
        return self.repeat_n * one

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

    duration = Quantity(
        type=np.float64,
        unit='s',
        description='How long this plan lasts (assuming everything goes as expected). '
        'Can be used to stop its instructions before they finish. '
        'Empty means the plan has the potential to be executed indefinitely (end '
        'defined elsewhere).',
    )

    #: How a plan runs its `instructions`. A subclass can overwrite the default.
    instruction_execution_mode = Quantity(
        type=MEnum('sequential', 'parallel'),
        default='sequential',
        description='How the instructions are supposed to be executed: `sequential` '
        'means one after another, `parallel` means they all start at once, but may '
        'finish at different times.',
    )

    def combine_instruction_durations(self):
        """How long the instructions last together, run as `instruction_execution_mode`
        says; `None` if one of them never finishes. Override it for any other rule."""
        return combined_duration(
            [instruction.duration for instruction in self.instructions],
            self.instruction_execution_mode,
        )

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        # The instructions are normalized before the plan, so their durations are derived.
        if self.duration is None:
            self.duration = self.combine_instruction_durations()

    def time_series_for_plotting(self) -> TimePlotSeries:
        """The plan drawn from its start until its `duration`. A plan that never ends is
        drawn until the last thing in it starts, finishes or breaks off: found by a first
        pass that nothing stops, then drawn again up to there."""
        stop = seconds_or_inf(self.duration)
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
        if self.scheduled_datetime is not None and self.duration is not None:
            self.scheduled_end_time = self.scheduled_datetime + timedelta(
                seconds=self.duration.to('s').magnitude
            )


m_package.__init_metainfo__()
