"""The solar cell a stability test was run on.

A placeholder: it holds only what the files of a stability run state about the device,
so that runs can refer to a sample entry. It is to be replaced by the real sample
schema, the device and its substrate as made by the processing entries.
"""

import numpy as np
from nomad.datamodel.metainfo.basesections.v2 import System
from nomad.metainfo import Quantity, SchemaPackage

m_package = SchemaPackage()


class SolarCellSample(System):
    """A solar cell or module, as the files of its stability runs describe it.

    A placeholder until a real sample schema exists: it holds only what those files
    state, and will be replaced by the device and its substrate from the entries of
    their processing.
    """

    cell_area = Quantity(
        type=np.float64,
        unit='m^2',
        description='The active area of one cell, the area its current density is '
        'counted over.',
        a_eln={'component': 'NumberEditQuantity', 'defaultDisplayUnit': 'cm^2'},
    )
    typology = Quantity(
        type=str,
        description='What kind of device it is, as the lab names it: a single `Cell` '
        'or a `Module` of several cells.',
        a_eln={'component': 'StringEditQuantity'},
    )
    number_of_cells = Quantity(
        type=int,
        description='How many cells the device has: 1 for a single cell.',
        a_eln={'component': 'NumberEditQuantity'},
    )


m_package.__init_metainfo__()
