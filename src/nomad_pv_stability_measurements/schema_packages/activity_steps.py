"""The monitor/control steps, one class per quantity (Design.md §15.1).

Each only fixes the unit of its `setpoint`. What a setpoint means physically, which
quantities are tied, and words that stand for values are no part of the schema: such
logic belongs in a `normalize()` once it is needed, or in the parser.
"""

import numpy as np
from nomad.metainfo import Quantity, SchemaPackage

from nomad_pv_stability_measurements.schema_packages.routine import (
    PlannedMonitorControlStep,
)

m_package = SchemaPackage()


class Temperature(PlannedMonitorControlStep):
    """The sample's temperature."""

    setpoint = Quantity(type=np.float64, unit='K', description='Temperature to hold.')


class Irradiance(PlannedMonitorControlStep):
    """The light on the sample."""

    setpoint = Quantity(
        type=np.float64, unit='W/m^2', description='Irradiance to hold.'
    )
    spectrum = Quantity(
        type=str,
        description='Which spectrum the lamp delivers, e.g. `AM1.5G`. Free text for now.',
    )


class Voltage(PlannedMonitorControlStep):
    """The voltage at the cell's terminals."""

    setpoint = Quantity(type=np.float64, unit='V', description='Voltage to hold.')


class Current(PlannedMonitorControlStep):
    """The current through the cell."""

    setpoint = Quantity(type=np.float64, unit='A', description='Current to hold.')


class Resistance(PlannedMonitorControlStep):
    """The load across the cell's terminals."""

    setpoint = Quantity(
        type=np.float64, unit='ohm', description='Load resistance to connect.'
    )


class BendRadiusStep(PlannedMonitorControlStep):
    """How far the device is bent."""

    setpoint = Quantity(
        type=np.float64, unit='m', description='Radius the device is bent to.'
    )


class StrainStep(PlannedMonitorControlStep):
    """How far the device is stretched."""

    setpoint = Quantity(
        type=np.float64,
        unit='dimensionless',
        description='How far the device is stretched, as a fraction.',
    )


m_package.__init_metainfo__()
