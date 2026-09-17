"""The steps whose value moves, one class per quantity (Design.md §15.11).

Each fixes the unit of `start_point`, `end_point` and `ramp_rate` — the rate in that
unit per second, since a rate is the quantity over a time. One class per quantity, as
`hold_steps.py` has: `RampTemperature` and `HoldTemperature` are two kinds of step on
one axis, and R4 reads them as one (`utils.py`).

The move is linear. Any other shape is a curve the schema would have to evaluate, which
is the physics §15.1 keeps out, and a staircase is not a curve at all: it is a `repeat`
block of ordinary holds (§15.8). Where a standard names the two ends of a cycle and not
the path, the ramp's `end_of_ramp_behavior` is `cycle` (§21.2).
"""

import numpy as np
from nomad.metainfo import Quantity, SchemaPackage

from nomad_pv_stability_measurements.schema_packages.routine import RampStep

m_package = SchemaPackage()


class RampTemperature(RampStep):
    """The sample's temperature, moving."""

    start_point = Quantity(
        type=np.float64, unit='K', description='Where the ramp starts.'
    )
    end_point = Quantity(type=np.float64, unit='K', description='Where the ramp ends.')
    ramp_rate = Quantity(
        type=np.float64, unit='K/s', description='How fast the temperature moves.'
    )


class RampIrradiance(RampStep):
    """The light on the sample, moving."""

    start_point = Quantity(
        type=np.float64, unit='W/m^2', description='Where the ramp starts.'
    )
    end_point = Quantity(
        type=np.float64, unit='W/m^2', description='Where the ramp ends.'
    )
    ramp_rate = Quantity(
        type=np.float64, unit='W/m^2/s', description='How fast the irradiance moves.'
    )
    spectrum = Quantity(
        type=str,
        description='Which spectrum the lamp delivers, e.g. `AM1.5G`. Free text for now.',
    )


class RampVoltage(RampStep):
    """The voltage at the cell's terminals, moving."""

    start_point = Quantity(
        type=np.float64, unit='V', description='Where the ramp starts.'
    )
    end_point = Quantity(type=np.float64, unit='V', description='Where the ramp ends.')
    ramp_rate = Quantity(
        type=np.float64, unit='V/s', description='How fast the voltage moves.'
    )


class RampCurrent(RampStep):
    """The current through the cell, moving."""

    start_point = Quantity(
        type=np.float64, unit='A', description='Where the ramp starts.'
    )
    end_point = Quantity(type=np.float64, unit='A', description='Where the ramp ends.')
    ramp_rate = Quantity(
        type=np.float64, unit='A/s', description='How fast the current moves.'
    )


class RampResistance(RampStep):
    """The load across the cell's terminals, moving."""

    start_point = Quantity(
        type=np.float64, unit='ohm', description='Where the ramp starts.'
    )
    end_point = Quantity(
        type=np.float64, unit='ohm', description='Where the ramp ends.'
    )
    ramp_rate = Quantity(
        type=np.float64, unit='ohm/s', description='How fast the resistance moves.'
    )


class RampBendRadius(RampStep):
    """How far the device is bent, moving."""

    start_point = Quantity(
        type=np.float64, unit='m', description='Where the ramp starts.'
    )
    end_point = Quantity(type=np.float64, unit='m', description='Where the ramp ends.')
    ramp_rate = Quantity(
        type=np.float64, unit='m/s', description='How fast the radius moves.'
    )


class RampStrain(RampStep):
    """How far the device is stretched, moving."""

    start_point = Quantity(
        type=np.float64,
        unit='dimensionless',
        description='Where the ramp starts, as a fraction.',
    )
    end_point = Quantity(
        type=np.float64,
        unit='dimensionless',
        description='Where the ramp ends, as a fraction.',
    )
    ramp_rate = Quantity(
        type=np.float64, unit='1/s', description='How fast the strain moves.'
    )


class RampAbsoluteHumidity(RampStep):
    """The water in the atmosphere around the sample, moving."""

    start_point = Quantity(
        type=np.float64,
        unit='dimensionless',
        description='Where the ramp starts, as a volume ratio (§15.7).',
    )
    end_point = Quantity(
        type=np.float64,
        unit='dimensionless',
        description='Where the ramp ends, as a volume ratio.',
    )
    ramp_rate = Quantity(
        type=np.float64, unit='1/s', description='How fast the fraction moves.'
    )


class RampRelativeHumidity(RampStep):
    """The relative humidity around the sample, moving (§20.6)."""

    start_point = Quantity(
        type=np.float64,
        unit='dimensionless',
        description='Where the ramp starts, as a fraction: `30 %` is 0.3.',
    )
    end_point = Quantity(
        type=np.float64,
        unit='dimensionless',
        description='Where the ramp ends, as a fraction.',
    )
    ramp_rate = Quantity(
        type=np.float64, unit='1/s', description='How fast the relative humidity moves.'
    )


class RampOxygenFraction(RampStep):
    """The oxygen in the atmosphere around the sample, moving."""

    start_point = Quantity(
        type=np.float64,
        unit='dimensionless',
        description='Where the ramp starts, as a volume ratio (§15.7).',
    )
    end_point = Quantity(
        type=np.float64,
        unit='dimensionless',
        description='Where the ramp ends, as a volume ratio.',
    )
    ramp_rate = Quantity(
        type=np.float64, unit='1/s', description='How fast the fraction moves.'
    )


class RampPressure(RampStep):
    """The total pressure of the atmosphere around the sample, moving."""

    start_point = Quantity(
        type=np.float64, unit='Pa', description='Where the ramp starts.'
    )
    end_point = Quantity(type=np.float64, unit='Pa', description='Where the ramp ends.')
    ramp_rate = Quantity(
        type=np.float64, unit='Pa/s', description='How fast the pressure moves.'
    )


m_package.__init_metainfo__()
