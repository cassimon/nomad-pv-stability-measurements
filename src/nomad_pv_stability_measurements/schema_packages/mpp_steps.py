import numpy as np
from nomad.metainfo import Quantity, SchemaPackage

from nomad_pv_stability_measurements.schema_packages.routine import (
    PlannedMonitorControlStep,
)

m_package = SchemaPackage()


class MPPTracking(PlannedMonitorControlStep):
    """The load held at the cell's maximum power point, which the tracker finds.

    The parameters are what an operator sets before the run: how far the tracker
    perturbs, how often, and how long it waits before reading back.
    """

    perturbation_voltage = Quantity(
        type=np.float64,
        unit='V',
        description='How far the tracker steps the voltage when it looks for the peak.',
    )
    perturbation_every = Quantity(
        type=np.float64,
        unit='s',
        description='How often the tracker perturbs. `perturbation_frequency` in '
        'nomad-baseclasses, which is a period in seconds despite the name.',
    )
    perturbation_delay = Quantity(
        type=np.float64,
        unit='s',
        description='How long the tracker waits after perturbing before it reads back, '
        'so the cell has settled.',
    )
    start_voltage_manually = Quantity(
        type=bool,
        description='Whether the operator sets the voltage the tracker starts from, '
        'rather than the tracker choosing it.',
    )
    start_voltage = Quantity(
        type=np.float64,
        unit='V',
        description='The voltage the tracker starts from. Only read with '
        '`start_voltage_manually`.',
    )


class VOCTracking(PlannedMonitorControlStep):
    """The load at open circuit, where the voltage settles with no current drawn.

    No parameters and no set_point: open circuit is a state of the terminals, and the
    voltage there is the cell's answer. ISOS Table 1 writes it `OC`.
    """


m_package.__init_metainfo__()
