import numpy as np
from nomad.metainfo import MEnum, Quantity, SchemaPackage, SubSection

from nomad_pv_stability_measurements.schema_packages.general import PlannedProcessStep
from nomad_pv_stability_measurements.schema_packages.utils import normalize_steps

m_package = SchemaPackage()


class PlannedMonitorControlStep(PlannedProcessStep):
    """
    One quantity, monitored, controlled, or both.

    Never used on its own: the subclass in `steps.py` is the quantity, and fixes the
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
                f'which names no quantity: use one of the step classes in `steps.py`.'
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
    steps = SubSection(
        section_def=PlannedProcessStep,
        repeats=True,
        description='What this block does, in one list: monitor/control steps and '
        'nested blocks.',
    )

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        normalize_steps(self, self.execution_mode, logger)


m_package.__init_metainfo__()
