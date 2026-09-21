import numpy as np
from nomad.metainfo import Quantity, SchemaPackage

from nomad_pv_stability_measurements.schema_packages.base_instructions import (
    HoldBelowInstruction,
    HoldBetweenInstruction,
)

m_package = SchemaPackage()


class HoldBelowAbsoluteHumidity(HoldBelowInstruction):
    """The water in the atmosphere around the sample, kept under a bound."""

    upper_bound = Quantity(
        type=np.float64,
        unit='dimensionless',
        description='The most water vapour allowed, as a volume ratio (§15.7).',
    )


class HoldBelowRelativeHumidity(HoldBelowInstruction):
    """The relative humidity around the sample, kept under a bound (§20.6)."""

    upper_bound = Quantity(
        type=np.float64,
        unit='dimensionless',
        description='The most relative humidity allowed, as a fraction: `55 %` is 0.55.',
    )


class HoldBelowOxygenFraction(HoldBelowInstruction):
    """The oxygen in the atmosphere around the sample, kept under a bound (§20.5)."""

    upper_bound = Quantity(
        type=np.float64,
        unit='dimensionless',
        description='The most oxygen allowed, as a volume ratio: `1 ppm` is 1e-6.',
    )


class HoldBetweenIrradiance(HoldBetweenInstruction):
    """The light on the sample, kept between two bounds (§22)."""

    lower_bound = Quantity(
        type=np.float64, unit='W/m^2', description='The least irradiance allowed.'
    )
    upper_bound = Quantity(
        type=np.float64, unit='W/m^2', description='The most irradiance allowed.'
    )


m_package.__init_metainfo__()
