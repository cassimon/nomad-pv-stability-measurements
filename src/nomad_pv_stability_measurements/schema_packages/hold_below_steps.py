"""The steps that keep one value under a bound, one class per quantity (Design.md §17.5).

A sibling of `hold_steps.py`, not an extension of it: "keep under 55 %" is not "hold at
55 %", so the bound is a field of its own rather than a second meaning of `set_point`.

Only the quantities a standard actually bounds have a class. ISOS Table 1 bounds the
water vapour alone (`< 55 %`, `< 50 %`); another quantity is one class here and one line
in the parser's table, whenever a standard states one.
"""

import numpy as np
from nomad.metainfo import Quantity, SchemaPackage

from nomad_pv_stability_measurements.schema_packages.routine import HoldBelowStep

m_package = SchemaPackage()


class HoldBelowWaterVaporFraction(HoldBelowStep):
    """The water in the atmosphere around the sample, kept under a bound."""

    upper_bound = Quantity(
        type=np.float64,
        unit='dimensionless',
        description='The most water vapour allowed, as a volume ratio (§15.7).',
    )


m_package.__init_metainfo__()
