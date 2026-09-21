import numpy as np
from nomad.metainfo import Quantity, SchemaPackage

from nomad_pv_stability_measurements.schema_packages.base_instructions import (
    RampInstruction,
)

m_package = SchemaPackage()


class RampTemperature(RampInstruction):
    """The sample's temperature, moving."""

    start_point = Quantity(
        type=np.float64, unit='K', description='Where the ramp starts.'
    )
    end_point = Quantity(type=np.float64, unit='K', description='Where the ramp ends.')
    ramp_rate = Quantity(
        type=np.float64, unit='K/s', description='How fast the temperature moves.'
    )


class RampIrradiance(RampInstruction):
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


class RampVoltage(RampInstruction):
    """The voltage at the cell's terminals, moving."""

    start_point = Quantity(
        type=np.float64, unit='V', description='Where the ramp starts.'
    )
    end_point = Quantity(type=np.float64, unit='V', description='Where the ramp ends.')
    ramp_rate = Quantity(
        type=np.float64, unit='V/s', description='How fast the voltage moves.'
    )


class RampCurrent(RampInstruction):
    """The current through the cell, moving."""

    start_point = Quantity(
        type=np.float64, unit='A', description='Where the ramp starts.'
    )
    end_point = Quantity(type=np.float64, unit='A', description='Where the ramp ends.')
    ramp_rate = Quantity(
        type=np.float64, unit='A/s', description='How fast the current moves.'
    )


class RampResistance(RampInstruction):
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


class RampBendRadius(RampInstruction):
    """How far the device is bent, moving."""

    start_point = Quantity(
        type=np.float64, unit='m', description='Where the ramp starts.'
    )
    end_point = Quantity(type=np.float64, unit='m', description='Where the ramp ends.')
    ramp_rate = Quantity(
        type=np.float64, unit='m/s', description='How fast the radius moves.'
    )


class RampStrain(RampInstruction):
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


class RampAbsoluteHumidity(RampInstruction):
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


class RampRelativeHumidity(RampInstruction):
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


class RampOxygenFraction(RampInstruction):
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


class RampPressure(RampInstruction):
    """The total pressure of the atmosphere around the sample, moving."""

    start_point = Quantity(
        type=np.float64, unit='Pa', description='Where the ramp starts.'
    )
    end_point = Quantity(type=np.float64, unit='Pa', description='Where the ramp ends.')
    ramp_rate = Quantity(
        type=np.float64, unit='Pa/s', description='How fast the pressure moves.'
    )


m_package.__init_metainfo__()
