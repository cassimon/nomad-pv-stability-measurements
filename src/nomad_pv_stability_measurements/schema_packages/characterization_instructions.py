"""Instructions that characterize the cell during a test, rather than hold a condition."""

import numpy as np
from nomad.metainfo import MEnum, Quantity, SchemaPackage
from nomad.units import ureg

from nomad_pv_stability_measurements.schema_packages.general import SingleInstruction
from nomad_pv_stability_measurements.schema_packages.utils import shown

m_package = SchemaPackage()


class JVScan(SingleInstruction):
    """J–V scans taken over the instruction's duration, one every `interval`: the
    voltage swept as set, the current recorded. Without an `interval`, one scan at the
    start.

    A standard writes it as "J–V every x". How long one scan takes is rarely known, so
    it is no part of the plan: the duration is the stretch the scans are taken over,
    usually the whole block they run beside.
    """

    interval = Quantity(
        type=np.float64,
        unit='s',
        description='The time from one scan to the next.',
    )
    voltage_start = Quantity(
        type=np.float64,
        unit='V',
        description='The voltage a forward scan starts from, the lower end of the range.',
    )
    voltage_stop = Quantity(
        type=np.float64,
        unit='V',
        description='The voltage a forward scan ends at, the upper end of the range.',
    )
    voltage_step = Quantity(
        type=np.float64,
        unit='V',
        description='The voltage between two points of a scan.',
    )
    scan_rate = Quantity(
        type=np.float64,
        unit='V/s',
        description='How fast the voltage is swept.',
    )
    scan_order = Quantity(
        type=MEnum(
            'forward', 'reverse', 'forward then reverse', 'reverse then forward'
        ),
        description='Which scans each J–V takes, in the order taken.',
    )
    irradiance = Quantity(
        type=np.float64,
        unit='W/m^2',
        description='The light the scans are measured under; 1000 W/m² is one sun.',
    )

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        if self.interval is not None and self.interval.to('s').magnitude <= 0:
            logger.error(
                f'{self.label}: the `interval` between scans must be positive.'
            )

    def describe(self) -> str:
        if self.interval is None:
            return 'J–V scan'
        return f'J–V scan every {shown(self.interval.to(ureg.second))}'

    def row_for_plotting(self) -> str:
        return 'J–V scan'

    def role_for_plotting(self) -> str:
        """Monitored: a scan measures the cell, and regulates no condition."""
        return 'monitored'


m_package.__init_metainfo__()
