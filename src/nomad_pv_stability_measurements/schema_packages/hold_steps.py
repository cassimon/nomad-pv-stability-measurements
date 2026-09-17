"""The steps that hold one value, one class per quantity (Design.md §15.1, §15.11).

Each only fixes the unit of its `set_point`. What a set point means physically, which
quantities are tied, and words that stand for values are no part of the schema: such
logic belongs in a `normalize()` once it is needed, or in the parser.

The atmosphere is recorded as an absolute volume ratio — a plain dimensionless fraction,
so `500 ppm` from a glovebox readout and `2 %` from a gas bottle land on one axis and
compare without a conversion table. For an ideal gas the volume fraction and the mole
fraction are the same number, so the glovebox convention (`ppm` is by volume, D6) needs
no second axis. Relative humidity is deliberately no set point: it is a property of the
water content *and* the temperature, not of the atmosphere alone, so the same step would
mean something different beside every temperature. Derive it in a `normalize()` if it is
ever needed (§15.7).

`BalanceGas` holds something that is not a number — a gas — so it takes no `set_point`
and subclasses the plain monitor/control step instead of `HoldStep` (§15.11). The load's
tracked point is the same shape, and lives in `mpp_steps.py` (§15.10).
"""

import numpy as np
from nomad.metainfo import Quantity, SchemaPackage

from nomad_pv_stability_measurements.schema_packages.routine import (
    HoldStep,
    PlannedMonitorControlStep,
)

m_package = SchemaPackage()


class HoldTemperature(HoldStep):
    """The sample's temperature."""

    set_point = Quantity(type=np.float64, unit='K', description='Temperature to hold.')
    set_point_tolerance = Quantity(
        type=np.float64,
        unit='K',
        description='How far either side of `set_point` still counts.',
    )


class HoldIrradiance(HoldStep):
    """The light on the sample."""

    set_point = Quantity(
        type=np.float64, unit='W/m^2', description='Irradiance to hold.'
    )
    set_point_tolerance = Quantity(
        type=np.float64,
        unit='W/m^2',
        description='How far either side of `set_point` still counts.',
    )
    spectrum = Quantity(
        type=str,
        description='Which spectrum the lamp delivers, e.g. `AM1.5G`. Free text for now.',
    )


class HoldVoltage(HoldStep):
    """The voltage at the cell's terminals."""

    set_point = Quantity(type=np.float64, unit='V', description='Voltage to hold.')
    set_point_tolerance = Quantity(
        type=np.float64,
        unit='V',
        description='How far either side of `set_point` still counts.',
    )


class HoldCurrent(HoldStep):
    """The current through the cell."""

    set_point = Quantity(type=np.float64, unit='A', description='Current to hold.')
    set_point_tolerance = Quantity(
        type=np.float64,
        unit='A',
        description='How far either side of `set_point` still counts.',
    )


class HoldResistance(HoldStep):
    """The load across the cell's terminals."""

    set_point = Quantity(
        type=np.float64, unit='ohm', description='Load resistance to connect.'
    )
    set_point_tolerance = Quantity(
        type=np.float64,
        unit='ohm',
        description='How far either side of `set_point` still counts.',
    )


class HoldBendRadius(HoldStep):
    """How far the device is bent."""

    set_point = Quantity(
        type=np.float64, unit='m', description='Radius the device is bent to.'
    )
    set_point_tolerance = Quantity(
        type=np.float64,
        unit='m',
        description='How far either side of `set_point` still counts.',
    )


class HoldStrain(HoldStep):
    """How far the device is stretched."""

    set_point = Quantity(
        type=np.float64,
        unit='dimensionless',
        description='How far the device is stretched, as a fraction.',
    )
    set_point_tolerance = Quantity(
        type=np.float64,
        unit='dimensionless',
        description='How far either side of `set_point` still counts.',
    )


class HoldWaterVaporFraction(HoldStep):
    """The water in the atmosphere around the sample, as a volume ratio."""

    set_point = Quantity(
        type=np.float64,
        unit='dimensionless',
        description='Water vapour to hold, as a volume ratio: the fraction itself, so '
        '`500 ppm` is 5e-4 and `2 %` is 0.02. Absolute on purpose — relative humidity '
        'depends on the temperature and is no part of the schema (§15.7).',
    )
    set_point_tolerance = Quantity(
        type=np.float64,
        unit='dimensionless',
        description='How far either side of `set_point` still counts.',
    )


class HoldOxygenFraction(HoldStep):
    """The oxygen in the atmosphere around the sample, as a volume ratio."""

    set_point = Quantity(
        type=np.float64,
        unit='dimensionless',
        description='Oxygen to hold, as a volume ratio: the fraction itself, so '
        '`0.1 ppm` is 1e-7 (a glovebox) and `21 %` is 0.21 (air).',
    )
    set_point_tolerance = Quantity(
        type=np.float64,
        unit='dimensionless',
        description='How far either side of `set_point` still counts.',
    )


class HoldPressure(HoldStep):
    """The total pressure of the atmosphere around the sample."""

    set_point = Quantity(
        type=np.float64,
        unit='Pa',
        description='Pressure to hold: the atmosphere as a whole, beside the fractions '
        'the other steps record (§15.10).',
    )
    set_point_tolerance = Quantity(
        type=np.float64,
        unit='Pa',
        description='How far either side of `set_point` still counts.',
    )


class BalanceGas(PlannedMonitorControlStep):
    """What the rest of the atmosphere is, beside the fractions the other steps record.

    A name, not a number, so it declares no `set_point` either (§15.10, §15.11).
    """

    gas = Quantity(
        type=str,
        description='Which gas makes up the balance, e.g. `N2`, `air`, `Ar`. Free text, '
        'like `HoldIrradiance.spectrum`.',
    )


m_package.__init_metainfo__()
