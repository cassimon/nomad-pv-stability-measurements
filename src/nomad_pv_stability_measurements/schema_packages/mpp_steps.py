"""The electrical load's tracked steps (Design.md §15.10).

The load is the one axis a protocol commands without naming a number. Holding `0.8 V` is
a `HoldVoltage`; sitting at the maximum power point is not a voltage the protocol knows —
it is a point the instrument finds, and the volts and amps there are what the cell
answers. That is what these steps say, and why they declare no `setpoint` and no ramp.

What a tracker *does* to find the point — the algorithm, how far it perturbs, how often
it steps — is logic, and no part of the schema until something needs it (§15.1). This is
the file it would go in, beside the point being tracked. A JV sweep during tracking is
its own step (D17), and belongs here too once it is built.
"""

from nomad.metainfo import MEnum, Quantity, SchemaPackage

from nomad_pv_stability_measurements.schema_packages.routine import (
    PlannedMonitorControlStep,
)

m_package = SchemaPackage()


class OperatingPoint(PlannedMonitorControlStep):
    """Where on the JV curve the load sits, when the instrument finds the point.

    One class with an enum rather than one class per point: a load sits at exactly one
    point at a time, so the two are values on one axis, and R4 then reports `mpp` and
    `voc` at once as the contradiction it is (§15.10).
    """

    point = Quantity(
        type=MEnum('mpp', 'voc'),
        description='Which point the load is held at: `mpp` for maximum power point '
        'tracking, `voc` for the open-circuit condition.',
    )

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        if self.point is None:
            logger.error(
                f'{self.name or "<unnamed>"} is an `OperatingPoint` naming no point: '
                f'write `mpp` or `voc`.'
            )


m_package.__init_metainfo__()
