import re
from datetime import datetime, timedelta

import numpy as np
from nomad.datamodel.data import ArchiveSection, EntryData
from nomad.datamodel.metainfo.basesections.v2 import Activity, ActivityStep
from nomad.metainfo import (
    Datetime,
    MEnum,
    Quantity,
    SchemaPackage,
    Section,
    SubSection,
)
from nomad.metainfo.metainfo import SectionProxy
from nomad.units import ureg

m_package = SchemaPackage()


def combined_duration(durations, mode: str):
    """How long instructions with these `durations` last together: one after another
    (`sequential`) or all at once (`parallel`). `None` if any of them never finishes."""
    if any(duration is None for duration in durations):
        return None
    seconds = [duration.to('s').magnitude for duration in durations]
    if not seconds:
        return 0 * ureg.second
    return (max(seconds) if mode == 'parallel' else sum(seconds)) * ureg.second


def shown(quantity) -> str:
    """A quantity the way a person reads it: a temperature in °C, a fraction in %, a
    time in the largest of h, min and s that counts it whole."""
    if quantity.check('[temperature]'):
        quantity = quantity.to('degC')
    elif quantity.check('[time]'):
        seconds = quantity.to('s').magnitude
        for unit, size in (('h', 3600), ('min', 60)):
            if seconds >= size and float(seconds / size).is_integer():
                return f'{seconds / size:.4g} {unit}'
        return f'{seconds:.4g} s'
    elif quantity.dimensionless:
        quantity = quantity.to('percent')
    return f'{quantity.magnitude:.4g} {quantity.units:~P}'


def words(class_name: str) -> str:
    """`HoldRelativeHumidity` as `Hold relative humidity`; acronyms stay: `MPP tracking`."""
    parts = re.findall(r'[A-Z]+(?=[A-Z][a-z]|$)|[A-Z]?[a-z]+|\d+', class_name)
    text = ' '.join(part if part.isupper() else part.lower() for part in parts)
    return text[:1].upper() + text[1:]


class Instruction(ArchiveSection):
    """Something to be done, which is completed after its `estimated_duration`.

    Instructions are consistent on their own: a block's duration is always derived from
    what it contains. Only a `Plan` stops its instructions early.
    """

    m_def = Section(label_quantity='label')

    name = Quantity(type=str, description='A short name for this instruction.')

    label = Quantity(
        type=str,
        description='How the instruction is listed: its `name`, or else what it does, '
        'from what is written in it. Derived.',
    )

    description = Quantity(
        type=str, description='Anything else worth saying about this instruction.'
    )

    estimated_duration = Quantity(
        type=np.float64,
        unit='s',
        description='How long the whole instruction is going to take, including any '
        'sub-instructions. Must be positive. Empty means it never finishes.',
    )

    sub_instructions = SubSection(
        section_def=SectionProxy('Instruction'),
        repeats=True,
        description='The instructions this one is made of.',
    )

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        if self.estimated_duration is not None and self.estimated_duration <= 0:
            logger.error(
                f'{self.name or "<unnamed>"} writes an `estimated_duration` of '
                f'{self.estimated_duration.to("s").magnitude:g} s: it must be positive.'
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


class InstructionBlock(Instruction):
    """Instructions run one after another or simultaneously — once.

    The parent of the blocks that repeat. Its `estimated_duration` is always derived
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
        self.estimated_duration = self.derive_duration()

    def describe(self) -> str:
        count = len(self.sub_instructions)
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
            [each.estimated_duration for each in self.sub_instructions],
            self.sub_instruction_execution_mode,
        )

    def derive_duration(self):
        return self.one_iteration()


class RepeatingBlock(InstructionBlock):
    """Instructions repeated — a block that may or may not finish.

    Its kind says which: a timed block always finishes, an indefinite one never does, and
    a counting one should. On its own it is not known to finish, so its
    `estimated_duration` is empty.
    """

    def describe_repetition(self) -> str:
        return 'Repeat indefinitely'

    def derive_duration(self):
        return None


class TimedRepeatingBlock(RepeatingBlock):
    """Instructions repeated for `repeat_duration`, then stopped — wherever they are.

    It always finishes: `repeat_duration` is what ends it, and so its
    `estimated_duration`, whether or not its sub-instructions ever finish.
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


IndefiniteRepeatingBlock = RepeatingBlock
"""Instructions repeated until something outside stops them — it never finishes.

Its `estimated_duration` is always empty; only the plan it belongs to ends it.
"""


class CountingRepeatingBlock(RepeatingBlock):
    """Instructions repeated `repeat_n` times — it should finish.

    Its `estimated_duration` is one iteration times `repeat_n`. Without a count, or with a
    sub-instruction that never finishes, it does not finish after all: that is warned
    about, and its `estimated_duration` is empty.
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


class Plan(EntryData):
    """What is planned to be done, as instructions.

    A plan is not an activity: `execute()` makes one out of it. Its `estimated_duration`
    is the one place instructions can be stopped before they finish.
    """

    #: How the `instruction_block` a translator writes for this kind of plan runs its
    #: instructions. A subclass sets its own convention.
    instruction_execution_mode = 'sequential'

    name = Quantity(type=str, description='A short name for this plan.')

    description = Quantity(
        type=str, description='Anything else worth saying about this plan.'
    )

    estimated_duration = Quantity(
        type=np.float64,
        unit='s',
        description='How long this plan lasts. Can be used to stop its instructions before they finish. '
        'Empty means the plan has the potential to be executed indefinitely (end defined elsewhere'
        ').',
    )

    instruction_block = SubSection(
        section_def=InstructionBlock,
        description='The instructions that make up this plan.',
    )

    def execute(  # noqa: PLR0913 — everything the activity is, given by the caller
        self,
        *,
        name: str,
        description: str,
        datetime: datetime,
        datetime_end: datetime,
        method: str,
        location: str,
        steps: list[ActivityStep],
    ) -> Activity:
        """The activity running this plan would be. Overwrite it to say how the
        instructions become `steps`."""
        return Activity(
            name=name,
            description=description,
            datetime=datetime,
            datetime_end=datetime_end,
            method=method,
            location=location,
            steps=steps,
        )

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        # The block is normalized before the plan, so its duration is already derived.
        if self.estimated_duration is None and self.instruction_block is not None:
            self.estimated_duration = self.instruction_block.estimated_duration


class ScheduledPlan(Plan):
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
        if self.scheduled_datetime is not None and self.estimated_duration is not None:
            self.scheduled_end_time = self.scheduled_datetime + timedelta(
                seconds=self.estimated_duration.to('s').magnitude
            )


m_package.__init_metainfo__()
