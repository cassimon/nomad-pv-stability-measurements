"""Values a standard names, rather than each protocol restating them (Design.md §17.2).

An authored word such as `RT` stands for one of these. The parser resolves it into the
step's own fields, so an archive holds the numbers and never the word (D8a, §17.3). The
sections exist so that each value has one home, a unit and a description, published in
the metainfo instead of living as a number in a parser table.

Each base field names no unit, and each subclass declares its own, as `HoldStep` and its
subclasses do (§15.11).
"""

import numpy as np
from nomad.datamodel.data import ArchiveSection
from nomad.metainfo import Quantity, SchemaPackage

m_package = SchemaPackage()


class StandardValue(ArchiveSection):
    """A named value with a symmetric tolerance: `value ± tolerance`."""

    name = Quantity(
        type=str,
        description='What the value is called where it is defined.',
    )
    value = Quantity(
        type=np.float64,
        description='The value itself. Each subclass declares it in its own unit.',
    )
    tolerance = Quantity(
        type=np.float64,
        description='How far either side of `value` still counts, as a difference in '
        'the same unit. Empty where the definition states none.',
    )


class RoomTemperature(StandardValue):
    """Room temperature, as the ISOS consensus statement defines it: 23 ± 4 °C.

    "room temperature in the laboratory is assumed to be 23±4 °C" (Khenkin et al.,
    Nature Energy 5, 35–49 (2020), p.36). An *assumed* value: a protocol writing `RT` for
    an ambient laboratory states the figure without claiming anyone regulates it
    (Design.md §17.2, §18.7).
    """

    name = Quantity(type=str, default='room temperature')
    value = Quantity(type=np.float64, unit='K', default=296.15)
    tolerance = Quantity(type=np.float64, unit='K', default=4.0)


class Dark(StandardValue):
    """No light at all — deliberately, and counted (D8a).

    Exact by definition, so it states no tolerance.
    """

    name = Quantity(type=str, default='dark')
    value = Quantity(type=np.float64, unit='W/m^2', default=0.0)
    tolerance = Quantity(type=np.float64, unit='W/m^2')


m_package.__init_metainfo__()
