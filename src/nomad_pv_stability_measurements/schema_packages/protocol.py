"""
The protocol tree and the `StabilityProtocol` entry (Design.md §3, §4.2, §4.3).

A protocol is a tree: the root `Protocol` and, below it, `SubProtocol` nodes.
Each node runs its `steps` either one after another (`sequential`) or at the
same time (`parallel`).
"""

from nomad.datamodel.data import ArchiveSection, EntryData
from nomad.datamodel.metainfo.basesections import BaseSection
from nomad.metainfo import MEnum, Quantity, SchemaPackage, SectionProxy, SubSection

m_package = SchemaPackage()


class Protocol(ArchiveSection):
    """The root of the protocol tree. Its `steps` are `SubProtocol`s."""

    name = Quantity(type=str, description='Name of the protocol.')
    mode = Quantity(
        type=MEnum('sequential', 'parallel'),
        default='sequential',
        description='How `steps` run: one after another, or at the same time.',
    )
    steps = SubSection(section_def=SectionProxy('SubProtocol'), repeats=True)


class SubProtocol(Protocol):
    """A node below the root. Nests further through the inherited `steps`."""

    # Subprotocol tag exists for better readability in the yaml
    subprotocol = Quantity(type=str, description='Name of this block of `steps`.')

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        self.name = self.subprotocol


class StabilityProtocol(BaseSection, EntryData):
    """A PV stability test protocol. The entry holds the root of the tree."""

    protocol = SubSection(section_def=Protocol)


m_package.__init_metainfo__()
