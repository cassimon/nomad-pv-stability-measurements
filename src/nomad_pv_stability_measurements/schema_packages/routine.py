from math import isclose

import numpy as np
from nomad.metainfo import MEnum, Quantity, SchemaPackage, SubSection

from nomad_pv_stability_measurements.schema_packages.general import PlannedProcessStep
from nomad_pv_stability_measurements.schema_packages.utils import (
    check_steps,
    derive_duration,
    normalize_steps,
)

m_package = SchemaPackage()


class PlannedMonitorControlStep(PlannedProcessStep):
    """
    One quantity, monitored, controlled, or both.

    Never used on its own: the subclass in `activity_steps.py` is the quantity, and fixes the
    unit of its `setpoint`. What a setpoint means physically is no part of the schema
    (Design.md §15.1). Without an `estimated_duration` the step is a condition holding
    for its block's whole span; the first steps of a protocol set, this way, what holds
    for the whole run.
    """

    monitor = Quantity(
        type=bool,
        description='Log data from this quantity.',
    )
    control = Quantity(
        type=bool,
        description='Regulate this quantity to `setpoint`.',
    )
    setpoint = Quantity(
        type=np.float64,
        description='The value to regulate to. Each step class declares it in its own '
        'unit.',
    )
    sample_every = Quantity(
        type=np.float64,
        unit='s',
        description='How often to sample. Write this or `sampling_rate`; the other '
        'is derived from it.',
    )
    sampling_rate = Quantity(
        type=np.float64,
        unit='Hz',
        description='How fast to sample a continuous stream. Write this or '
        '`sample_every`; the other is derived from it.',
    )

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        # Whichever sampling figure was written, both are stored, so everything
        # downstream can read either (D9).
        if self.sampling_rate is None and self.sample_every is not None:
            self.sampling_rate = 1 / self.sample_every
        if self.sample_every is None and self.sampling_rate is not None:
            self.sample_every = 1 / self.sampling_rate
        if type(self) is PlannedMonitorControlStep:
            logger.error(
                f'{self.name or "<unnamed>"} is a bare `PlannedMonitorControlStep`, '
                f'which names no quantity: use one of the step classes in '
                f'`activity_steps.py`.'
            )


class PlannedSubroutineStep(PlannedProcessStep):
    """
    A step that can contain other steps, which run in sequence or in parallel.
    Running steps in parallel is a little counterintuitive, however the word "step"
    was kept for consistency with NOMAD's own `ProcessStep` and `ActivityStep`.
    """

    execution_mode = Quantity(
        type=MEnum('sequential', 'parallel'),
        default='sequential',
        description='How this block runs the steps that have an `estimated_duration`: '
        '`sequential` one after another, `parallel` at the same time. Steps without '
        "one hold for the block's whole span either way.",
    )
    repeat = Quantity(
        type=MEnum('until_end_of_duration', 'n_times'),
        default='until_end_of_duration',
        description='How often this block runs its steps: `until_end_of_duration` for '
        'as long as its `estimated_duration` lasts, `n_times` for `repeat_n` '
        'iterations of `estimated_duration_one_iteration` each.',
    )
    repeat_n = Quantity(
        type=int,
        description='How many iterations to run. Only read with `repeat: n_times`.',
    )
    estimated_duration_one_iteration = Quantity(
        type=np.float64,
        unit='s',
        description='How long one iteration is planned to last. Only read with '
        '`repeat: n_times`; left empty, it is derived from the steps. The block itself '
        'then lasts `repeat_n` times this.',
    )
    steps = SubSection(
        section_def=PlannedProcessStep,
        repeats=True,
        description='What this block does, in one list: monitor/control steps and '
        'nested blocks.',
    )

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        if self.repeat == 'n_times':
            self.normalize_iterations(logger)
        else:
            self.report_unread_iteration_fields(logger)
            normalize_steps(self, self.execution_mode, logger)

    def report_unread_iteration_fields(self, logger):
        """Dead configuration: neither field means anything without `n_times`."""
        where = self.name or '<unnamed>'
        for written in ('repeat_n', 'estimated_duration_one_iteration'):
            if getattr(self, written) is not None:
                logger.warning(
                    f'{where} writes `{written}`, which is only read with '
                    f'`repeat: n_times`, so it has no effect here.'
                )

    def normalize_iterations(self, logger):
        """The steps are one iteration, run `repeat_n` times: they are checked against
        that one iteration, and the block lasts all of them together (§15.8)."""
        where = self.name or '<unnamed>'
        if self.repeat_n is None:
            logger.error(f'{where} repeats `n_times`, but writes no `repeat_n`.')
        elif self.repeat_n < 1:
            logger.error(
                f'{where} writes `repeat_n` {self.repeat_n}: a block runs at least once.'
            )
        if self.estimated_duration_one_iteration is None:
            derived = derive_duration(self.steps, self.execution_mode)
            if derived is not None:
                self.estimated_duration_one_iteration = derived
        one = self.estimated_duration_one_iteration
        check_steps(self.steps, self.execution_mode, one, where, logger)
        if one is None or self.repeat_n is None or self.repeat_n < 1:
            return
        together = self.repeat_n * one
        if self.estimated_duration is None:
            self.estimated_duration = together
        elif not isclose(
            self.estimated_duration.to('s').magnitude,
            together.to('s').magnitude,
            rel_tol=1e-9,
        ):
            # Reported, never repaired: the authored duration stands (D13a).
            logger.error(
                f'{where} writes an `estimated_duration` of '
                f'{self.estimated_duration.to("s").magnitude:g} s, but '
                f'{self.repeat_n} iterations of {one.to("s").magnitude:g} s last '
                f'{together.to("s").magnitude:g} s.'
            )


m_package.__init_metainfo__()
