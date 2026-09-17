"""The instructions that keep one value under a bound, or between two, one class per quantity
(Design.md §17.5, §22).

A sibling of `hold_instructions.py`, not an extension of it: "keep under 55 %" is not "hold at
55 %", so the bound is a field of its own rather than a second meaning of `set_point`.

Only the quantities a standard actually bounds have a class: the relative humidity
(`< 55 %`, `< 50 %` in ISOS Table 1), and the absolute humidity and oxygen that describe
an inert atmosphere (§20.5); and the irradiance, the one quantity a standard gives a range
for ("800–1000 W m⁻²", §22). Another quantity is one class here and one line in the
parser's table, whenever a standard states one.
"""

import numpy as np
from nomad.metainfo import Quantity, SchemaPackage

from nomad_pv_stability_measurements.schema_packages.routine import (
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
