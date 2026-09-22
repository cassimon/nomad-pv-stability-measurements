import numpy as np
from nomad.metainfo import Quantity, SchemaPackage

from nomad_pv_stability_measurements.schema_packages.base_instructions import (
    ElectricalLoad,
    MonitorControlInstruction,
)

m_package = SchemaPackage()


class MPPTracking(ElectricalLoad, MonitorControlInstruction):
    """The load held at the cell's maximum power point, which the tracker finds.

    The parameters are what an operator sets before the run: how far the tracker
    perturbs, how often, and how long it waits before reading back.
    """

    #: The tracker moves the voltage, and the current follows.
    controlled = ('voltage',)
    dependent = ('current',)

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

    def annotation_for_plotting(self) -> str:
        return 'MPP'

    def states_a_value(self) -> bool:
        return True  # the point the tracker finds, and holds the load at

    def quantity_name(self) -> str:
        return 'electrical load'


class VOCTracking(ElectricalLoad, MonitorControlInstruction):
    """The load at open circuit, where the voltage settles with no current drawn.

    No parameters and no set_point: open circuit is a state of the terminals, and the
    voltage there is the cell's answer. ISOS Table 1 writes it `OC`.
    """

    #: No current, by disconnecting the terminals; the voltage follows.
    controlled = ('current',)
    dependent = ('voltage',)

    def annotation_for_plotting(self) -> str:
        return 'open circuit'

    def states_a_value(self) -> bool:
        return True

    def role_for_plotting(self) -> str:
        """Specified, never controlled: the cell is disconnected, and nothing regulates
        it (ISOS consensus: "open-circuit (disconnected) conditions")."""
        return 'specified'

    def quantity_name(self) -> str:
        return 'electrical load'


m_package.__init_metainfo__()
