"""The monitor/control steps, one class per quantity (Design.md §15.1).

Each only fixes the unit of its `setpoint`. What a setpoint means physically, which
quantities are tied, and words that stand for values are no part of the schema: such
logic belongs in a `normalize()` once it is needed, or in the parser.

The atmosphere is recorded as an absolute volume ratio — a plain dimensionless fraction,
so `500 ppm` from a glovebox readout and `2 %` from a gas bottle land on one axis and
compare without a conversion table. For an ideal gas the volume fraction and the mole
fraction are the same number, so the glovebox convention (`ppm` is by volume, D6) needs
no second axis. Relative humidity is deliberately no setpoint: it is a property of the
water content *and* the temperature, not of the atmosphere alone, so the same step would
mean something different beside every temperature. Derive it in a `normalize()` if it is
ever needed (§15.7).
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


class BendRadius(PlannedMonitorControlStep):
    """How far the device is bent."""

    setpoint = Quantity(
        type=np.float64, unit='m', description='Radius the device is bent to.'
    )


class Strain(PlannedMonitorControlStep):
    """How far the device is stretched."""

    setpoint = Quantity(
        type=np.float64,
        unit='dimensionless',
        description='How far the device is stretched, as a fraction.',
    )


class WaterVaporFraction(PlannedMonitorControlStep):
    """The water in the atmosphere around the sample, as a volume ratio."""

    setpoint = Quantity(
        type=np.float64,
        unit='dimensionless',
        description='Water vapour to hold, as a volume ratio: the fraction itself, so '
        '`500 ppm` is 5e-4 and `2 %` is 0.02. Absolute on purpose — relative humidity '
        'depends on the temperature and is no part of the schema (§15.7).',
    )


class OxygenFraction(PlannedMonitorControlStep):
    """The oxygen in the atmosphere around the sample, as a volume ratio."""

    setpoint = Quantity(
        type=np.float64,
        unit='dimensionless',
        description='Oxygen to hold, as a volume ratio: the fraction itself, so '
        '`0.1 ppm` is 1e-7 (a glovebox) and `21 %` is 0.21 (air).',
    )


m_package.__init_metainfo__()
