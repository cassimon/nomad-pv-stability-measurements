from datetime import datetime, timedelta

import numpy as np
from nomad.datamodel.data import ArchiveSection, EntryData
from nomad.datamodel.metainfo.basesections.v2 import Activity, ActivityStep
from nomad.metainfo import Datetime, MEnum, Quantity, SchemaPackage, SubSection
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


class Instruction(ArchiveSection):
    """Something to be done, which is completed after its `estimated_duration`.

    Instructions are consistent on their own: a block's duration is always derived from
    what it contains. Only a `Plan` stops its instructions early.
    """

    name = Quantity(type=str, description='A short name for this instruction.')

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

    def one_iteration(self):
        """How long the sub-instructions take once; `None` if they never finish."""
        return combined_duration(
            [each.estimated_duration for each in self.sub_instructions],
            self.sub_instruction_execution_mode,
        )

    def derive_duration(self):
        return self.one_iteration()


class CountingRepeatingBlock(InstructionBlock):
    """Instructions repeated `repeat_n` times — indefinitely if it is empty.

    Its `estimated_duration` is one iteration times `repeat_n`, and empty if it repeats
    indefinitely or any sub-instruction never finishes.
    """

    repeat_n = Quantity(
        type=int,
        description='How many times the sub-instructions are run. Must be positive. '
        'Empty means they are repeated indefinitely.',
    )

    def normalize(self, archive, logger):
        if self.repeat_n is not None and self.repeat_n < 1:
            logger.error(
                f'{self.name or "<unnamed>"} writes `repeat_n` {self.repeat_n}: a block '
                f'runs at least once.'
            )
        super().normalize(archive, logger)

    def derive_duration(self):
        one = self.one_iteration()
        if one is None or self.repeat_n is None or self.repeat_n < 1:
            return None
        return self.repeat_n * one


class TimedRepeatingBlock(InstructionBlock):
    """Instructions repeated for `repeat_duration`, then stopped — wherever they are.

    `repeat_duration` is what ends it, and so its `estimated_duration`.
    """

    repeat_duration = Quantity(
        type=np.float64,
        unit='s',
        description='How long the sub-instructions are repeated for, before they are '
        'stopped. Must be positive. Empty means they are repeated indefinitely.',
    )

    def derive_duration(self):
        return self.repeat_duration


class Plan(EntryData):
    """What is planned to be done, as instructions.

    A plan is not an activity: `execute()` makes one out of it. Its `estimated_duration`
    is the one place instructions can be stopped before they finish.
    """

    #: How a plan runs its `instructions`. A subclass sets its own convention.
    instruction_execution_mode = 'sequential'

    name = Quantity(type=str, description='A short name for this plan.')

    description = Quantity(
        type=str, description='Anything else worth saying about this plan.'
    )

    estimated_duration = Quantity(
        type=np.float64,
        unit='s',
        description='How long this plan lasts. Can be used to stop its instructions before they finish. ' \
        'Empty means the plan has the potential to be executed indefinitely (end defined elsewhere' \
        ').',
    )

    instructions = SubSection(
        section_def=Instruction,
        repeats=True,
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
        if self.estimated_duration is None:
            self.estimated_duration = combined_duration(
                [each.estimated_duration for each in self.instructions],
                self.instruction_execution_mode,
            )


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
