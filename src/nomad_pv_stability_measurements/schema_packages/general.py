import numpy as np
from nomad.common import now
from nomad.datamodel.metainfo.basesections.v2 import Process, ProcessStep
from nomad.metainfo import Datetime, Quantity, SchemaPackage, SubSection

m_package = SchemaPackage()


class PlannedProcessStep(ProcessStep):
    """
    One thing a protocol does — and, like `PlannedProcess`, may still be only a plan.

    `was_executed` is authored, never inferred from the clock, and checked the same way
    `PlannedProcess` checks `datetime`: reported, never repaired.
    """

    was_executed = Quantity(
        type=bool,
        description='Whether this step actually ran. Leave empty for a planned '
        'step nobody has run yet.',
    )
    estimated_start_time = Quantity(
        type=Datetime,
        description='When this is planned to start, for a step not yet run. Use '
        '`start_time` once it actually has.',
    )
    estimated_duration = Quantity(
        type=np.float64,
        unit='s',
        description='How long this step is planned to last. With one, the step takes '
        'its turn in the block around it; leave it empty to last as long as that block '
        'does.',
    )

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        if self.was_executed:
            if self.start_time is None or self.start_time > now():
                logger.error(
                    '`was_executed` is set, but `start_time` is empty or not in '
                    'the past: a step that already ran needs a `start_time` to '
                    'say when.'
                )
        elif self.was_executed is False and self.start_time is not None:
            logger.error('`was_executed` is false, so `start_time` must stay empty.')


class PlannedProcess(Process):
    """A process that may still be only a plan.

    `was_executed` is authored, never inferred from the clock: `normalize()` only
    checks the two field groups are not mixed — it never repairs then.
    """

    was_executed = Quantity(
        type=bool,
        description='Whether this process actually ran. Leave empty for a plan '
        'nobody has run yet.',
    )
    estimated_datetime = Quantity(
        type=Datetime,
        description='When this is planned to start, for a process not yet run. '
        'Use `datetime` once it actually has.',
    )
    estimated_duration = Quantity(
        type=np.float64,
        unit='s',
        description='How long this is planned to take, for a process not yet run. '
        'Use `datetime` / `end_time` once it actually has.',
    )
    estimated_end_time = Quantity(
        type=Datetime,
        description='When this is planned to end, for a process not yet run. Use '
        '`end_time` once it actually has.',
    )
    steps = SubSection(
        section_def=PlannedProcessStep,
        repeats=True,
        description='The steps of this process, in order: monitor/control steps, which '
        'act on one quantity, and subroutine steps, which group further steps. Leave it '
        'empty for a plan that has no steps yet.',
    )

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        if self.was_executed:
            if self.datetime is None or self.datetime > now():
                logger.error(
                    '`was_executed` is set, but `datetime` is empty or not in the '
                    'past: a process that already ran needs a `datetime` to say '
                    'when.'
                )
        elif self.was_executed is False and (
            self.datetime is not None or self.end_time is not None
        ):
            logger.error(
                '`was_executed` is false, so `datetime` / `end_time` must stay '
                'empty; use `estimated_datetime` / `estimated_duration` for a '
                'plan that has not run yet.'
            )


m_package.__init_metainfo__()
